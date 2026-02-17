# MEV Bot Watcher

[![Tests](https://github.com/Nov1kov/mev-bot-watcher/actions/workflows/tests.yml/badge.svg)](https://github.com/Nov1kov/mev-bot-watcher/actions/workflows/tests.yml)
[![Docker](https://img.shields.io/docker/v/nov1kov/mev-watcher?label=docker&sort=semver)](https://hub.docker.com/r/nov1kov/mev-watcher)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[Русская версия](README.ru.md)

CLI tool for analyzing and realtime monitoring of MEV bot profitability on EVM-compatible networks (Ethereum, Arbitrum, etc.).

Scans historical blocks or subscribes to new ones via WebSocket, finds transactions of a watched address, parses ERC20 Transfer events and calculates P&L (incoming tokens - outgoing tokens - gas).

## Features

- **Retrospective analysis** — scan a range of blocks, calculate profit per block and total summary
- **Realtime monitoring** — subscribe to new blocks via WebSocket
- **Multichain** — multiple networks via config (Ethereum, Arbitrum, etc.)
- **Telegram notifications** — aggregated reports with configurable interval and USD prices

## Setup

```bash
pip install -r requirements.txt
```

Copy `config.example.yaml` to `config.yaml` and fill in your values:

```yaml
telegram:
  bot_token: 'YOUR_BOT_TOKEN'
  chat_id: 'YOUR_CHAT_ID'
  notify_interval_minutes: 60

bots:
  ethereum:
    blockchain: ethereum
    token_contract_address: '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2'
    watched_address: '0xYOUR_BOT_ADDRESS'
    http_rpc_url: 'https://your-rpc-provider.com/api-key'
    ws_rpc_url: 'wss://your-rpc-provider.com/api-key'
```

## Usage

**Analyze blocks:**
```bash
python main.py analyze -c config.yaml -b ethereum -s 18000000
```

**Monitor new blocks:**
```bash
python main.py monitor -c config.yaml -b ethereum
```

## Docker

**Build:**
```bash
docker build -t mev-watcher .
```

**Run:**
```bash
docker run -v ./config.yaml:/app/config.yaml mev-watcher
```

Monitor a specific bot:
```bash
docker run -v ./config.yaml:/app/config.yaml mev-watcher \
  python main.py monitor -c /app/config.yaml -b arbitrum
```

Analyze blocks:
```bash
docker run -v ./config.yaml:/app/config.yaml mev-watcher \
  python main.py analyze -c /app/config.yaml -b ethereum -s 18000000
```

## Tests

```bash
python -m unittest discover tests
```

## Stack

Python 3.10+, aiohttp, websockets, Click, PyYAML
