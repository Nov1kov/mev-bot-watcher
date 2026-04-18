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

## Configuration

Copy `config.example.yaml` to `config.yaml` and fill in your values:

```yaml
telegram:
  bot_token: 'YOUR_BOT_TOKEN'
  chat_id: 'YOUR_CHAT_ID'
  notify_schedule: '0 * * * *'  # cron syntax (every hour)

bots:
  ethereum:
    blockchain: ethereum
    token_contract_address: '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2'
    watched_address: '0xYOUR_BOT_ADDRESS'
    http_rpc_url: 'https://your-rpc-provider.com/api-key'
    ws_rpc_url: 'wss://your-rpc-provider.com/api-key'
```

### WebSocket with Basic Auth

If your WebSocket endpoint requires HTTP Basic authentication, pass `ws_rpc_url`
as a nested block with `url`, `login` and `password` fields. Plain string form
stays supported for endpoints without auth.

```yaml
bots:
  my_node:
    blockchain: arbitrum
    token_contract_address: '0x...'
    watched_address: '0xYOUR_BOT_ADDRESS'
    http_rpc_url: 'http://user:pass@your-node-ip:8549'
    ws_rpc_url:
      url: 'ws://your-node-ip:8549'
      login: 'your_login'
      password: 'your_password'
```

## Telegram notifications

Startup message:
```
🚀 MEV Monitor Started

• ethereum — Ethereum
  0xYOUR_BOT_ADDRESS

⏰ Schedule: 0 * * * *
```

Periodic report:
```
✅ ETHEREUM
0x1234...5678
├ Successful txs: 3/4
└ Total: +0.001000 ETH ($+2.50)
```

## Usage

### Docker

Monitor all bots:
```bash
docker run -d -v ./config.yaml:/app/config.yaml nov1kov/mev-watcher
```

Monitor a specific bot:
```bash
docker run -d -v ./config.yaml:/app/config.yaml nov1kov/mev-watcher monitor -b ethereum
```

Analyze blocks:
```bash
docker run -v ./config.yaml:/app/config.yaml nov1kov/mev-watcher analyze -b ethereum -s 18000000
```

### Local

```bash
pip install -r requirements.txt
python main.py monitor
python main.py analyze -b ethereum -s 18000000
```

## Tests

```bash
python -m unittest discover tests
```
