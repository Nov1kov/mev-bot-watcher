# MEV bot watcher

CLI-утилита для анализа прибыльности MEV-ботов на Ethereum и EVM-совместимых сетях.

Сканирует блоки, находит транзакции отслеживаемого адреса, парсит ERC20 Transfer-события и рассчитывает P&L (входящие токены - исходящие токены - газ).

## Возможности

- **Ретроспективный анализ** — сканирование диапазона блоков с расчётом прибыли по каждому блоку и итоговой суммы
- **Realtime-мониторинг** — подписка на новые блоки через WebSocket
- **Мультичейн** — поддержка нескольких сетей через конфиг (Ethereum, Arbitrum и др.)

## Установка

```bash
pip install -r requirements.txt
```

## Настройка

Отредактируйте `config.yaml`:

```yaml
bots:
  ethereum:
    blockchain: ethereum
    token_contract_address: '0x...'  # адрес отслеживаемого токена (WETH)
    watched_address: '0x...'         # адрес MEV-бота
    http_rpc_url: 'https://...'
    ws_rpc_url: 'wss://...'
```

## Использование

**Анализ блоков:**
```bash
python main.py analyze -c config.yaml -b ethereum -s 18000000
```

**Мониторинг новых блоков:**
```bash
python main.py monitor -c config.yaml -b ethereum
```

## Стек

Python 3.10+, aiohttp, websockets, Click, PyYAML
