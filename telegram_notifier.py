import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import List, Dict, Optional

import aiohttp


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


class TelegramNotifier:
    """Агрегированные уведомления в Telegram с контролем частоты отправки"""

    def __init__(self, bot_token: str, chat_id: str, notify_interval_minutes: int = 60,
                 eth_client=None):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.notify_interval = notify_interval_minutes * 60
        self.eth_client = eth_client
        self._pending: List[TxEvent] = []
        self._last_sent: float = 0.0
        self._lock = asyncio.Lock()

    async def add_event(self, event: TxEvent):
        """Добавить событие. Отправит сразу если прошло достаточно времени с последней отправки."""
        async with self._lock:
            self._pending.append(event)
            if time.time() - self._last_sent >= self.notify_interval:
                await self._flush()

    async def force_flush(self):
        """Принудительная отправка накопленных событий"""
        async with self._lock:
            await self._flush()

    async def _flush(self):
        if not self._pending:
            return
        events = self._pending.copy()
        self._pending.clear()
        self._last_sent = time.time()
        eth_price = None
        if self.eth_client:
            try:
                eth_price = await self.eth_client.get_eth_price_usd()
            except Exception:
                logging.exception("Failed to fetch ETH price")
        message = format_report(events, eth_price_usd=eth_price)
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

    async def send_startup_message(self, bots: Dict[str, Dict]):
        """Отправить приветственное сообщение при запуске мониторинга"""
        interval = self.notify_interval // 60
        lines = ["\U0001f680 *MEV Monitor Started*", ""]
        for name, cfg in bots.items():
            chain = cfg.get('blockchain', 'unknown').capitalize()
            addr = cfg.get('watched_address', '')
            lines.append(f"\u2022 *{name}* \u2014 {chain}")
            lines.append(f"  `{addr}`")
        lines.append("")
        lines.append(f"\u23f0 Уведомления: раз в {interval} мин")
        await self._send("\n".join(lines))

    async def run_periodic_flush(self):
        """Фоновая задача: периодически отправляет накопленные события"""
        while True:
            await asyncio.sleep(self.notify_interval)
            await self.force_flush()


def format_report(events: List[TxEvent], eth_price_usd: Optional[float] = None) -> str:
    """Форматирование отчёта для Telegram"""
    by_bot: Dict[str, List[TxEvent]] = {}
    for e in events:
        by_bot.setdefault(e.bot_name, []).append(e)

    lines = []

    for bot_name, bot_events in by_bot.items():
        total_net = sum(e.net_wei_change for e in bot_events)
        total_txs = sum(e.tx_count for e in bot_events)
        total_fails = sum(e.fail_count for e in bot_events)
        blocks = len(bot_events)
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
        lines.append(f"\u251c Блоков: {blocks}")
        lines.append(f"\u251c Транзакций: {total_txs}")
        if total_fails:
            lines.append(f"\u251c Неудачных: {total_fails}")
        total_line = f"\u2514 Итого: `{net_eth:+.6f} ETH"
        if eth_price_usd:
            usd_value = net_eth * eth_price_usd
            total_line += f" (${usd_value:+.2f})"
        total_line += "`"
        lines.append(total_line)
        lines.append("")

    return "\n".join(lines)
