# MEV Bot Watcher

[![Tests](https://github.com/Nov1kov/mev-bot-watcher/actions/workflows/tests.yml/badge.svg)](https://github.com/Nov1kov/mev-bot-watcher/actions/workflows/tests.yml)
[![Docker](https://img.shields.io/docker/v/nov1kov/mev-watcher?label=docker&sort=semver)](https://hub.docker.com/r/nov1kov/mev-watcher)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[English version](README.md)

CLI-утилита для анализа и realtime-мониторинга прибыльности MEV-ботов на EVM-совместимых сетях (Ethereum, Arbitrum и др.).

Сканирует исторические блоки или подписывается на новые через WebSocket, находит транзакции отслеживаемого адреса, парсит ERC20 Transfer (и WETH Deposit/Withdrawal) события для набора отслеживаемых токенов и рассчитывает P&L, приведённый к USD: `Σ(net по токену × цена) − газ в нативном токене × цена нативного`.

## Возможности

- **Мультитокенный P&L в USD** — отслеживается обёртка нативного токена плюс любое число `base_tokens` (например, USDC/USDT/DAI для арбитража стейблов); изменение баланса каждого токена оценивается по его цене и decimals, газ — через нативный токен
- **Ретроспективный анализ** — сканирование диапазона блоков с расчётом прибыли по каждому блоку и итоговой суммы
- **Realtime-мониторинг** — подписка на новые блоки через WebSocket
- **Мультичейн** — поддержка нескольких сетей через конфиг (Ethereum, Arbitrum и др.)
- **Telegram-уведомления** — агрегированные отчёты с настраиваемым интервалом, профитом в USD и балансами по каждому токену

## Конфигурация

Скопируйте `config.example.yaml` в `config.yaml` и заполните своими значениями:

```yaml
telegram:
  bot_token: 'YOUR_BOT_TOKEN'
  chat_id: 'YOUR_CHAT_ID'
  notify_schedule: '0 * * * *'  # cron синтаксис (каждый час)

bots:
  ethereum:
    # wrapped_token — обёртка нативного токена (WETH). Её цена используется для
    # оценки потраченного газа, и она также учитывается как профитный токен.
    wrapped_token: '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2'
    # base_tokens (опционально) — дополнительные токены, чьё изменение баланса
    # учитывается в профите (например, стейблы для арбитража). У каждого свои decimals.
    base_tokens:
      - '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48'   # USDC
      - '0xdAC17F958D2ee523a2206206994597C13D831ec7'   # USDT
    watched_address: '0x...'
    http_rpc_url: 'https://your-rpc-provider.com/api-key'
    ws_rpc_url: 'wss://your-rpc-provider.com/api-key'
```

`symbol`/`decimals` каждого токена читаются из контракта по RPC, а цена в USD
автоматически резолвится через CoinGecko по символу. `base_tokens` опционально —
для однотокенных ботов его можно не указывать.

### WebSocket с Basic-авторизацией

Если WebSocket-эндпоинт требует HTTP Basic-авторизацию, задайте `ws_rpc_url`
вложенной секцией с полями `url`, `login` и `password`. Плоская строка по-прежнему
поддерживается для эндпоинтов без авторизации.

```yaml
bots:
  my_node:
    wrapped_token: '0x...'
    watched_address: '0xYOUR_BOT_ADDRESS'
    http_rpc_url: 'http://user:pass@your-node-ip:8549'
    ws_rpc_url:
      url: 'ws://your-node-ip:8549'
      login: 'your_login'
      password: 'your_password'
```

## Telegram-уведомления

Сообщение при старте. Балансы по каждому токену берутся по RPC (нативный `eth_getBalance` + `balanceOf` для каждого отслеживаемого токена); цены в USD автоматически резолвятся через CoinGecko:
```
🚀 MEV Monitor Started

• ethereum (WETH — $3,210.50)
  0xYOUR_BOT_ADDRESS
  💰 Balance:
  ETH: 1.5000 ($4,815.75)
  WETH: 0.0000 ($0.00)
  USDC: 1000.0000 ($1,000.00)

⏰ Schedule: 0 * * * *
```

Если токен не удалось найти в CoinGecko, его USD-часть скрывается и остаётся только количество.

Периодический отчёт. Профит — это мультитокенный P&L, приведённый к USD
(изменение балансов токенов минус газ), а текущие балансы по токенам
обновляются по RPC в момент отправки:
```
✅ ETHEREUM
0x1234...5678
├ Successful txs: 3/4
└ Total: $+2.50
💰 Balance:
  ETH: 1.4980 ($4,809.32)
  USDC: 1001.7200 ($1,001.72)
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
