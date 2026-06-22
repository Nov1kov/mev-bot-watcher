import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Iterable, Any

import aiohttp
from croniter import croniter

from coingecko_client import CoinGeckoClient
from tx_analyzer import TokenInfo, normalize_address, compute_profit_usd_for


@dataclass
class TxEvent:
    """Событие транзакции для уведомления.

    net_by_token: словарь token_address -> net изменение баланса бота (raw,
    в наименьших единицах токена) за транзакцию/блок.
    """
    bot_name: str
    watched_address: str
    block_number: int
    tx_count: int
    fail_count: int
    net_by_token: Dict[str, int]
    gas_fee_wei: int
    timestamp: float = field(default_factory=time.time)


@dataclass
class BotInfo:
    """Информация о боте для форматирования уведомлений.

    tokens — отслеживаемые токены ([wrapped, *base]); wrapped — обёртка
    нативного токена, её цена используется для оценки газа.
    balances — текущие raw-балансы по token_address; native_balance_wei —
    нативный баланс (для газа). Обновляются через refresh_balances().
    """
    name: str
    watched_address: str
    tokens: List[TokenInfo]
    eth_client: Any = None
    native_balance_wei: Optional[int] = None
    balances: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        self.watched_address = normalize_address(self.watched_address)

    @property
    def wrapped(self) -> Optional[TokenInfo]:
        if not self.tokens:
            return None
        return next((t for t in self.tokens if t.is_wrapped), self.tokens[0])

    @property
    def native_symbol(self) -> str:
        """Тикер нативного токена: WETH -> ETH, WMON -> MON и т.д."""
        return self.wrapped.native_symbol if self.wrapped else "ETH"

    @property
    def native_coingecko_id(self) -> Optional[str]:
        return self.wrapped.coingecko_id if self.wrapped else None

    @property
    def coingecko_ids(self) -> List[str]:
        ids = {t.coingecko_id for t in self.tokens if t.coingecko_id}
        if self.native_coingecko_id:
            ids.add(self.native_coingecko_id)
        return sorted(ids)

    @classmethod
    async def from_rpc(cls, eth_client, name: str, watched_address: str,
                       tokens: List[TokenInfo]) -> "BotInfo":
        """Создаёт BotInfo и подтягивает текущие балансы по RPC."""
        info = cls(name=name, watched_address=watched_address,
                   tokens=tokens, eth_client=eth_client)
        await info.refresh_balances()
        return info

    async def refresh_balances(self):
        """Перечитать нативный и токеновые балансы watched_address по RPC."""
        if self.eth_client is None:
            return
        try:
            self.native_balance_wei = await self.eth_client.get_balance(self.watched_address)
        except Exception:
            logging.exception(f"[{self.name}] failed to fetch native balance")
        for token in self.tokens:
            try:
                self.balances[token.address] = await self.eth_client.get_erc20_balance(
                    token.address, self.watched_address)
            except Exception:
                logging.exception(f"[{self.name}] failed to fetch balance for {token.symbol}")


def _usd_suffix(amount: float, price: Optional[float], signed: bool = False) -> str:
    """' ($1,234.56)' если есть цена, иначе ''."""
    if price is None:
        return ""
    value = amount * price
    return f" (${value:+,.2f})" if signed else f" (${value:,.2f})"


def _format_balance_lines(info: BotInfo, prices: Optional[Dict[str, float]]) -> List[str]:
    """Строки баланса: нативный токен + каждый отслеживаемый токен."""
    prices = prices or {}
    lines: List[str] = []
    if info.native_balance_wei is not None:
        native_amount = info.native_balance_wei / 1e18
        if round(native_amount, 4) != 0:
            price = prices.get(info.native_coingecko_id) if info.native_coingecko_id else None
            lines.append(f"  `{info.native_symbol}: {native_amount:.4f}"
                         f"{_usd_suffix(native_amount, price)}`")
    for token in info.tokens:
        raw = info.balances.get(token.address)
        if raw is None:
            continue
        amount = raw / 10 ** token.decimals
        if round(amount, 4) == 0:
            continue
        price = prices.get(token.coingecko_id) if token.coingecko_id else None
        lines.append(f"  `{token.symbol}: {amount:.4f}{_usd_suffix(amount, price)}`")
    return lines


class TelegramNotifier:
    """Агрегированные уведомления в Telegram с контролем частоты отправки"""

    def __init__(self, bot_token: str, chat_id: str, notify_schedule: str = "0 * * * *",
                 cg_client: Optional[CoinGeckoClient] = None):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.notify_schedule = notify_schedule
        self.cg_client = cg_client
        self._pending: List[TxEvent] = []
        self._last_sent: float = 0.0
        self._lock = asyncio.Lock()
        self.bots: Dict[str, BotInfo] = {}

    def register_bot(self, info: BotInfo):
        """Регистрация бота в нотификаторе"""
        self.bots[info.name] = info

    def _seconds_until_next(self) -> float:
        cron = croniter(self.notify_schedule, datetime.now())
        next_time = cron.get_next(float)
        return max(0, next_time - time.time())

    async def add_event(self, event: TxEvent):
        """Добавить событие. Отправит сразу если это первое событие."""
        async with self._lock:
            self._pending.append(event)
            if self._last_sent == 0.0:
                await self._flush()

    async def force_flush(self):
        """Принудительная отправка накопленных событий"""
        async with self._lock:
            await self._flush()

    async def _fetch_prices(self, bot_names: Iterable[str]) -> Dict[str, float]:
        """USD-цены (coingecko_id -> usd) для всех токенов заданных ботов."""
        if not self.cg_client:
            return {}
        ids = set()
        for name in bot_names:
            info = self.bots.get(name)
            if info:
                ids.update(info.coingecko_ids)
        if not ids:
            return {}
        try:
            return await self.cg_client.get_prices_usd(ids)
        except Exception:
            logging.exception("Failed to fetch prices from CoinGecko")
            return {}

    async def _refresh_balances(self, bot_names: Iterable[str]):
        for name in bot_names:
            info = self.bots.get(name)
            if info:
                await info.refresh_balances()

    async def _flush(self):
        if not self._pending:
            return
        events = self._pending.copy()
        self._pending.clear()
        self._last_sent = time.time()
        bot_names = {e.bot_name for e in events}
        prices = await self._fetch_prices(bot_names)
        await self._refresh_balances(bot_names)
        message = format_report(events, bots_info=self.bots, prices=prices)
        await self._send(message)

    async def _send(self, text: str):
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logging.error(f"Telegram API error ({resp.status}): {body}")
                    else:
                        logging.info("Telegram notification sent")
        except Exception:
            logging.exception("Failed to send Telegram notification")

    async def send_startup_message(self):
        """Отправить приветственное сообщение при запуске мониторинга"""
        lines = ["\U0001f680 *MEV Monitor Started*", ""]
        await self._refresh_balances(self.bots.keys())
        prices = await self._fetch_prices(self.bots.keys())
        for name in sorted(self.bots.keys()):
            info = self.bots[name]
            symbol = info.wrapped.symbol if info.wrapped else "ETH"
            native_price = prices.get(info.native_coingecko_id) if info.native_coingecko_id else None
            price_str = f" — ${native_price:,.2f}" if native_price else ""
            lines.append(f"• *{name}* ({symbol}{price_str})")
            lines.append(f"  `{info.watched_address}`")
            balance_lines = _format_balance_lines(info, prices)
            if balance_lines:
                lines.append("  \U0001f4b0 Balance:")
                lines.extend(balance_lines)
        lines.append("")
        lines.append(f"⏰ Schedule: `{self.notify_schedule}`")
        await self._send("\n".join(lines))

    async def run_periodic_flush(self):
        """Фоновая задача: отправляет накопленные события по cron-расписанию"""
        while True:
            delay = self._seconds_until_next()
            await asyncio.sleep(delay)
            await self.force_flush()


def format_report(events: List[TxEvent],
                  bots_info: Optional[Dict[str, BotInfo]] = None,
                  prices: Optional[Dict[str, float]] = None) -> str:
    """Форматирование отчёта для Telegram.

    bots_info — словарь BotInfo по bot_name (токены, decimals, балансы).
    prices    — USD-цены по coingecko_id.
    Профит сводится в USD; ниже выводится текущий баланс по каждому токену.
    """
    prices = prices or {}
    by_bot: Dict[str, List[TxEvent]] = {}
    for e in events:
        by_bot.setdefault(e.bot_name, []).append(e)

    lines = []

    for bot_name in sorted(by_bot.keys()):
        bot_events = by_bot[bot_name]
        info = bots_info.get(bot_name) if bots_info else None

        total_txs = sum(e.tx_count for e in bot_events)
        total_fails = sum(e.fail_count for e in bot_events)
        successful = total_txs - total_fails
        total_gas_wei = sum(e.gas_fee_wei for e in bot_events)

        net_by_token: Dict[str, int] = {}
        for e in bot_events:
            for addr, value in e.net_by_token.items():
                net_by_token[addr] = net_by_token.get(addr, 0) + value

        profit_usd = None
        if info is not None:
            profit_usd = compute_profit_usd_for(info.tokens, info.native_coingecko_id,
                                                net_by_token, total_gas_wei, prices)

        if profit_usd is None:
            emoji = "➖"
        elif profit_usd > 0:
            emoji = "✅"
        elif profit_usd < 0:
            emoji = "❌"
        else:
            emoji = "➖"

        addr = bot_events[0].watched_address
        short_addr = f"{addr[:6]}...{addr[-4:]}"

        lines.append(f"{emoji} *{bot_name.upper()}*")
        lines.append(f"`{short_addr}`")
        lines.append(f"├ Successful txs: {successful}/{total_txs}")
        if profit_usd is not None:
            lines.append(f"└ Total: `${profit_usd:+,.2f}`")
        else:
            lines.append("└ Total: `n/a`")

        if info is not None:
            balance_lines = _format_balance_lines(info, prices)
            if balance_lines:
                lines.append("\U0001f4b0 Balance:")
                lines.extend(balance_lines)
        lines.append("")

    return "\n".join(lines)
