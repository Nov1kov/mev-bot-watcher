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
    blockchain: ethereum
    token_contract_address: '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2'
    watched_address: '0x...'
    http_rpc_url: 'https://your-rpc-provider.com/api-key'
    ws_rpc_url: 'wss://your-rpc-provider.com/api-key'
```

## Telegram-уведомления

Сообщение при старте:
```
🚀 MEV Monitor Started

• ethereum — Ethereum
  0xYOUR_BOT_ADDRESS

⏰ Schedule: 0 * * * *
```

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

Мониторинг конкретного бота:
```bash
docker run -d -v ./config.yaml:/app/config.yaml nov1kov/mev-watcher monitor -b ethereum
```

Анализ блоков:
```bash
docker run -v ./config.yaml:/app/config.yaml nov1kov/mev-watcher analyze -b ethereum -s 18000000
```

### Локально

```bash
pip install -r requirements.txt
python main.py monitor
python main.py analyze -b ethereum -s 18000000
```

## Тесты

```bash
python -m unittest discover tests
```
