import logging
from typing import Optional, Dict, List, Iterable

import aiohttp


COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"

# Оверрайды для популярных нативных токенов. Нужны для разрешения
# неоднозначности (у одного тикера может быть много coin id в CoinGecko).
_KNOWN_NATIVE_IDS = {
    "eth": "ethereum",
    "btc": "bitcoin",
    "bnb": "binancecoin",
    "matic": "matic-network",
    "pol": "polygon-ecosystem-token",
    "sol": "solana",
    "avax": "avalanche-2",
    "ftm": "fantom",
    "trx": "tron",
    "near": "near",
    "ada": "cardano",
    "dot": "polkadot",
    "mon": "monad",
}


class CoinGeckoClient:
    """Клиент CoinGecko: резолвит coin id по тикеру и получает цены в USD."""

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._symbol_to_ids: Optional[Dict[str, List[str]]] = None

    async def __aenter__(self):
        self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session:
            await self._session.close()
            self._session = None

    async def _ensure_coins_list(self):
        """Одноразовая загрузка списка монет CoinGecko с кешем на процесс."""
        if self._symbol_to_ids is not None:
            return
        url = f"{COINGECKO_BASE_URL}/coins/list"
        async with self._session.get(url) as resp:
            coins = await resp.json()
        mapping: Dict[str, List[str]] = {}
        for coin in coins:
            sym = (coin.get("symbol") or "").lower()
            if not sym:
                continue
            mapping.setdefault(sym, []).append(coin["id"])
        self._symbol_to_ids = mapping

    async def resolve_id_by_symbol(self, symbol: str) -> Optional[str]:
        """Подбор coingecko id по тикеру.

        Для wrapped-обёрток (символ начинается с W) первым делом пробуем
        нативный эквивалент: WETH->ETH, WMON->MON и т.д. — это корректно,
        т.к. цены wrapped-токена и нативного равны по смыслу 1:1. Если
        нативный не находится уверенно, падаем обратно к точному поиску
        исходного символа.
        """
        await self._ensure_coins_list()
        sym = symbol.lower()

        if sym.startswith("w") and len(sym) > 1:
            unwrapped = self._confident_lookup(sym[1:])
            if unwrapped:
                return unwrapped

        return self._best_effort_lookup(sym)

    def _confident_lookup(self, sym: str) -> Optional[str]:
        """Возвращает id только если уверены: либо оверрайд, либо id == sym."""
        if sym in _KNOWN_NATIVE_IDS:
            return _KNOWN_NATIVE_IDS[sym]
        for cid in self._symbol_to_ids.get(sym) or []:
            if cid == sym:
                return cid
        return None

    def _best_effort_lookup(self, sym: str) -> Optional[str]:
        """Точное совпадение по тикеру, даже если однозначности нет."""
        confident = self._confident_lookup(sym)
        if confident:
            return confident
        candidates = self._symbol_to_ids.get(sym) or []
        return candidates[0] if candidates else None

    async def get_prices_usd(self, ids: Iterable[str]) -> Dict[str, float]:
        """Получение цен сразу пачкой (CoinGecko поддерживает ids через запятую)."""
        unique = sorted({cid for cid in ids if cid})
        if not unique:
            return {}
        url = f"{COINGECKO_BASE_URL}/simple/price?ids={','.join(unique)}&vs_currencies=usd"
        async with self._session.get(url) as resp:
            data = await resp.json()
        return {cid: payload["usd"] for cid, payload in data.items() if "usd" in payload}

    async def get_price_usd(self, coingecko_id: str) -> Optional[float]:
        prices = await self.get_prices_usd([coingecko_id])
        return prices.get(coingecko_id)
