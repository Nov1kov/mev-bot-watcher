import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Iterable

import aiohttp
from croniter import croniter

from coingecko_client import CoinGeckoClient


@dataclass
class TxEvent:
    """Событие транзакции для уведомления"""
    bot_name: str
    watched_address: str
    block_number: int
    tx_count: int
    fail_count: int
    net_wei_change: int
    gas_fee_wei: int
    timestamp: float = field(default_factory=time.time)


@dataclass
class BotInfo:
    """Информация о боте, используемая для форматирования уведомлений"""
    name: str
    watched_address: str
    token_address: str
    token_symbol: str = "ETH"
    coingecko_id: Optional[str] = None
    total_balance_wei: Optional[int] = None

    @property
    def native_symbol(self) -> str:
        """Тикер нативного токена: WETH -> ETH, WMON -> MON и т.д."""
        s = self.token_symbol
        if len(s) > 1 and s[0].upper() == "W":
            return s[1:]
        return s

    @classmethod
    async def from_rpc(cls, eth_client, cg_client, name: str,
                       watched_address: str, token_address: str) -> "BotInfo":
        """Собирает BotInfo: тикер и суммарный баланс (native + wrapped ERC20)
        — по RPC, coingecko_id — автоподбором через CoinGecko."""
        token_symbol = "ETH"
        try:
            token_symbol = await eth_client.get_token_symbol(token_address)
        except Exception:
            logging.exception(f"[{name}] failed to fetch token symbol, fallback to 'ETH'")

        coingecko_id: Optional[str] = None
        try:
            coingecko_id = await cg_client.resolve_id_by_symbol(token_symbol)
        except Exception:
            logging.exception(f"[{name}] failed to resolve coingecko_id")

        total_balance_wei: Optional[int] = None
        try:
            native = await eth_client.get_balance(watched_address)
            wrapped = await eth_client.get_erc20_balance(token_address, watched_address)
            total_balance_wei = native + wrapped
        except Exception:
            logging.exception(f"[{name}] failed to fetch balance")

        if coingecko_id:
            logging.info(f"[{name}] token {token_symbol} -> coingecko_id {coingecko_id}")
        else:
            logging.warning(f"[{name}] token {token_symbol}: no coingecko match, USD price will be hidden")

        return cls(
            name=name,
            watched_address=watched_address,
            token_address=token_address,
            token_symbol=token_symbol,
            coingecko_id=coingecko_id,
            total_balance_wei=total_balance_wei,
        )


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
        """Загружает USD-цены для заданных ботов одним batch-запросом к CoinGecko."""
        if not self.cg_client:
            return {}
        name_to_id = {
            name: self.bots[name].coingecko_id
            for name in bot_names
            if name in self.bots and self.bots[name].coingecko_id
        }
        if not name_to_id:
            return {}
        try:
            prices_by_id = await self.cg_client.get_prices_usd(name_to_id.values())
        except Exception:
            logging.exception("Failed to fetch prices from CoinGecko")
            return {}
        return {name: prices_by_id[cid] for name, cid in name_to_id.items() if cid in prices_by_id}

    async def _flush(self):
        if not self._pending:
            return
        events = self._pending.copy()
        self._pending.clear()
        self._last_sent = time.time()
        prices = await self._fetch_prices({e.bot_name for e in events})
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
        prices = await self._fetch_prices(self.bots.keys())
        for name, info in self.bots.items():
            price = prices.get(name)
            price_str = f" \u2014 ${price:,.2f}" if price else ""
            lines.append(f"\u2022 *{name}* ({info.token_symbol}{price_str})")
            lines.append(f"  `{info.watched_address}`")
            if info.total_balance_wei is not None:
                balance = info.total_balance_wei / 1e18
                balance_line = f"  \U0001f4b0 Balance: `{balance:.4f} {info.native_symbol}"
                if price:
                    balance_line += f" (${balance * price:,.2f})"
                balance_line += "`"
                lines.append(balance_line)
        lines.append("")
        lines.append(f"\u23f0 Schedule: `{self.notify_schedule}`")
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

    bots_info — словарь BotInfo по bot_name, задаёт символ токена.
    prices    — словарь USD-цен по bot_name.
    """
    by_bot: Dict[str, List[TxEvent]] = {}
    for e in events:
        by_bot.setdefault(e.bot_name, []).append(e)

    lines = []

    for bot_name, bot_events in by_bot.items():
        info = bots_info.get(bot_name) if bots_info else None
        symbol = info.token_symbol if info else "ETH"
        price = prices.get(bot_name) if prices else None

        total_net = sum(e.net_wei_change for e in bot_events)
        total_txs = sum(e.tx_count for e in bot_events)
        total_fails = sum(e.fail_count for e in bot_events)
        successful = total_txs - total_fails
        addr = bot_events[0].watched_address
        short_addr = f"{addr[:6]}...{addr[-4:]}"

        if total_net > 0:
            emoji = "\u2705"
        elif total_net < 0:
            emoji = "\u274c"
        else:
            emoji = "\u2796"

        net_eth = total_net / 1e18

        lines.append(f"{emoji} *{bot_name.upper()}*")
        lines.append(f"`{short_addr}`")
        lines.append(f"\u251c Successful txs: {successful}/{total_txs}")
        total_line = f"\u2514 Total: `{net_eth:+.6f} {symbol}"
        if price:
            usd_value = net_eth * price
            total_line += f" (${usd_value:+.2f})"
        total_line += "`"
        lines.append(total_line)
        lines.append("")

    return "\n".join(lines)
