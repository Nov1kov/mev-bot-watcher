import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import List, Dict

import aiohttp


@dataclass
class TxEvent:
    """Событие транзакции для уведомления"""
    bot_name: str
    block_number: int
    tx_count: int
    fail_count: int
    net_wei_change: int
    gas_fee_wei: int
    timestamp: float = field(default_factory=time.time)


class TelegramNotifier:
    """Агрегированные уведомления в Telegram с контролем частоты отправки"""

    def __init__(self, bot_token: str, chat_id: str, notify_interval_minutes: int = 60):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.notify_interval = notify_interval_minutes * 60
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
        message = format_report(events)
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


def format_report(events: List[TxEvent]) -> str:
    """Форматирование отчёта для Telegram"""
    by_bot: Dict[str, List[TxEvent]] = {}
    for e in events:
        by_bot.setdefault(e.bot_name, []).append(e)

    lines = ["\U0001f4ca *MEV Bot Report*", ""]

    for bot_name, bot_events in by_bot.items():
        total_net = sum(e.net_wei_change for e in bot_events)
        total_gas = sum(e.gas_fee_wei for e in bot_events)
        total_txs = sum(e.tx_count for e in bot_events)
        total_fails = sum(e.fail_count for e in bot_events)
        blocks = len(bot_events)

        if total_net > 0:
            emoji = "\u2705"
        elif total_net < 0:
            emoji = "\u274c"
        else:
            emoji = "\u2796"

        net_eth = total_net / 1e18
        gas_eth = total_gas / 1e18

        lines.append(f"*{bot_name.upper()}* {emoji}")
        lines.append(f"\u251c Блоков: {blocks}")
        lines.append(f"\u251c Транзакций: {total_txs}")
        if total_fails:
            lines.append(f"\u251c Неудачных: {total_fails}")
        lines.append(f"\u251c Gas: {gas_eth:.6f} ETH")
        lines.append(f"\u2514 Итого: `{net_eth:+.6f} ETH`")
        lines.append("")

    return "\n".join(lines)
