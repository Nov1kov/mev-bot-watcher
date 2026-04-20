# MEV Bot Watcher

[![Tests](https://github.com/Nov1kov/mev-bot-watcher/actions/workflows/tests.yml/badge.svg)](https://github.com/Nov1kov/mev-bot-watcher/actions/workflows/tests.yml)
[![Docker](https://img.shields.io/docker/v/nov1kov/mev-watcher?label=docker&sort=semver)](https://hub.docker.com/r/nov1kov/mev-watcher)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[English version](README.md)

CLI-утилита для анализа и realtime-мониторинга прибыльности MEV-ботов на EVM-совместимых сетях (Ethereum, Arbitrum и др.).

Сканирует исторические блоки или подписывается на новые через WebSocket, находит транзакции отслеживаемого адреса, парсит ERC20 Transfer-события и рассчитывает P&L (входящие токены - исходящие токены - газ).

## Возможности

- **Ретроспективный анализ** — сканирование диапазона блоков с расчётом прибыли по каждому блоку и итоговой суммы
- **Realtime-мониторинг** — подписка на новые блоки через WebSocket
- **Мультичейн** — поддержка нескольких сетей через конфиг (Ethereum, Arbitrum и др.)
- **Telegram-уведомления** — агрегированные отчёты с настраиваемым интервалом и ценами в USD

## Конфигурация

Скопируйте `config.example.yaml` в `config.yaml` и заполните своими значениями:

```yaml
telegram:
  bot_token: 'YOUR_BOT_TOKEN'
  chat_id: 'YOUR_CHAT_ID'
  notify_schedule: '0 * * * *'  # cron синтаксис (каждый час)

bots:
  ethereum:
    token_contract_address: '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2'
    watched_address: '0x...'
    http_rpc_url: 'https://your-rpc-provider.com/api-key'
    ws_rpc_url: 'wss://your-rpc-provider.com/api-key'
```

### WebSocket с Basic-авторизацией

Если WebSocket-эндпоинт требует HTTP Basic-авторизацию, задайте `ws_rpc_url`
вложенной секцией с полями `url`, `login` и `password`. Плоская строка по-прежнему
поддерживается для эндпоинтов без авторизации.

```yaml
bots:
  my_node:
    token_contract_address: '0x...'
    watched_address: '0xYOUR_BOT_ADDRESS'
    http_rpc_url: 'http://user:pass@your-node-ip:8549'
    ws_rpc_url:
      url: 'ws://your-node-ip:8549'
      login: 'your_login'
      password: 'your_password'
```

## Telegram-уведомления

Сообщение при старте. Тикер и баланс берутся по RPC (символ + нативный `eth_getBalance` + wrapped ERC20 `balanceOf`, суммируются); цена в USD автоматически резолвится через CoinGecko:
```
🚀 MEV Monitor Started

• ethereum (WETH — $3,210.50)
  0xYOUR_BOT_ADDRESS
  💰 Balance: 1.5000 ETH ($4,815.75)

• monad (WMON — $0.03)
  0xYOUR_BOT_ADDRESS
  💰 Balance: 42.0000 MON ($1.29)

⏰ Schedule: 0 * * * *
```

Если токен не удалось найти в CoinGecko, USD-часть скрывается и в сообщении остаётся только тикер (например, `• monad (WMON)`).

Периодический отчёт:
```
✅ ETHEREUM
0x1234...5678
├ Successful txs: 3/4
└ Total: +0.001000 ETH ($+2.50)
```

## Использование

### Docker

Мониторинг всех ботов:
```bash
docker run -d -v ./config.yaml:/app/config.yaml nov1kov/mev-watcher
```

### Docker Compose

Создайте `docker-compose.yml` рядом с вашим `config.yaml`:

```yaml
services:
  mev-watcher:
    image: nov1kov/mev-watcher
    restart: unless-stopped
    volumes:
      - ./config.yaml:/app/config.yaml
```

### Локально

```bash
pip install -r requirements.txt
python main.py monitor
python main.py analyze -b ethereum -s 18000000
```

## Команды

`monitor` — подписка на новые блоки через WebSocket:
- `-b, --bot-name <name>` — конкретный бот (опционально; без флага мониторятся все)

`analyze` — ретроспективный анализ. Нужно указать ровно одну из опций по блокам:
- `-b, --bot-name <name>` — имя бота (обязательно)
- `-s, --start-block <N>` — скан от блока N до последнего
- `-n, --block <N>` — прогон одиночного блока (режим отладки)

`-c, --config <path>` — путь к конфигу (по умолчанию `config.yaml`) для обеих команд.

Примеры:
```bash
python main.py monitor -b ethereum
python main.py analyze -b ethereum -s 18000000
python main.py analyze -b ethereum -n 18500000
```

## Тесты

```bash
python -m unittest discover tests
```
