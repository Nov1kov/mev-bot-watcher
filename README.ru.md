# MEV Bot Watcher

[English version](README.md)

CLI-утилита для анализа прибыльности MEV-ботов на Ethereum и EVM-совместимых сетях.

Сканирует блоки, находит транзакции отслеживаемого адреса, парсит ERC20 Transfer-события и рассчитывает P&L (входящие токены - исходящие токены - газ).

## Возможности

- **Ретроспективный анализ** — сканирование диапазона блоков с расчётом прибыли по каждому блоку и итоговой суммы
- **Realtime-мониторинг** — подписка на новые блоки через WebSocket
- **Мультичейн** — поддержка нескольких сетей через конфиг (Ethereum, Arbitrum и др.)
- **Telegram-уведомления** — агрегированные отчёты с настраиваемым интервалом и ценами в USD

## Установка

```bash
pip install -r requirements.txt
```

Скопируйте `config.example.yaml` в `config.yaml` и заполните своими значениями:

```yaml
telegram:
  bot_token: 'YOUR_BOT_TOKEN'
  chat_id: 'YOUR_CHAT_ID'
  notify_interval_minutes: 60

bots:
  ethereum:
    blockchain: ethereum
    token_contract_address: '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2'
    watched_address: '0x...'
    http_rpc_url: 'https://your-rpc-provider.com/api-key'
    ws_rpc_url: 'wss://your-rpc-provider.com/api-key'
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

## Docker

**Сборка:**
```bash
docker build -t mev-watcher .
```

**Запуск:**
```bash
docker run -v ./config.yaml:/app/config.yaml mev-watcher
```

Мониторинг конкретного бота:
```bash
docker run -v ./config.yaml:/app/config.yaml mev-watcher \
  python main.py monitor -c /app/config.yaml -b arbitrum
```

Анализ блоков:
```bash
docker run -v ./config.yaml:/app/config.yaml mev-watcher \
  python main.py analyze -c /app/config.yaml -b ethereum -s 18000000
```

## Тесты

```bash
python -m unittest discover tests
```

## Стек

Python 3.10+, aiohttp, websockets, Click, PyYAML
