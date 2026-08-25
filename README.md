# MEV Bot Watcher

[![Tests](https://github.com/Nov1kov/mev-bot-watcher/actions/workflows/tests.yml/badge.svg)](https://github.com/Nov1kov/mev-bot-watcher/actions/workflows/tests.yml)
[![Docker](https://img.shields.io/docker/v/nov1kov/mev-watcher?label=docker&sort=semver)](https://hub.docker.com/r/nov1kov/mev-watcher)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[Русская версия](README.ru.md)

CLI tool for analyzing and realtime monitoring of MEV bot profitability on EVM-compatible networks (Ethereum, Arbitrum, etc.).

Scans historical blocks or subscribes to new ones via WebSocket, finds transactions of a watched address, parses ERC20 Transfer (and WETH Deposit/Withdrawal) events for a set of tracked tokens and calculates P&L converted to USD: `Σ(net per token × price) − gas spent in the native token × native price`.

## Features

- **Multi-token P&L in USD** — track the wrapped native token plus any number of `base_tokens` (e.g. USDC/USDT/DAI for stablecoin arbitrage); each token's balance change is valued at its own price and decimals, gas is valued via the native token
- **Retrospective analysis** — scan a range of blocks, calculate profit per block and total summary
- **Realtime monitoring** — subscribe to new blocks via WebSocket
- **Multichain** — multiple networks via config (Ethereum, Arbitrum, etc.)
- **Telegram notifications** — aggregated reports with configurable interval, USD profit and per-token balances; bot addresses can link to a block explorer via `scanner_url`
- **Instant loss alerts** — optional per-network `loss_alert_usd`: as soon as a block turns out unprofitable, a separate message is sent with links to the offending transactions

## Configuration

Copy `config.example.yaml` to `config.yaml` and fill in your values:

```yaml
telegram:
  bot_token: 'YOUR_BOT_TOKEN'
  chat_id: 'YOUR_CHAT_ID'
  notify_schedule: '0 * * * *'  # cron syntax (every hour)

bots:
  ethereum:
    # wrapped_token — the wrapped native token (WETH). Its price values the gas
    # spent, and it is also counted as a profit token.
    wrapped_token: '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2'
    # base_tokens (optional) — extra tokens whose balance change is included in
    # the profit (e.g. stablecoins for arbitrage). Each may have its own decimals.
    base_tokens:
      - '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48'   # USDC
      - '0xdAC17F958D2ee523a2206206994597C13D831ec7'   # USDT
    watched_address: '0xYOUR_BOT_ADDRESS'
    # scanner_url (optional) — base URL of the network block explorer. Used to
    # turn the bot address in Telegram notifications into a clickable link.
    # Examples: ethereum — https://etherscan.io/, arbitrum — https://arbiscan.io/
    scanner_url: 'https://etherscan.io/'
    # loss_alert_usd (optional) — send an instant alert as soon as a block's P&L
    # in this network is below -$loss_alert_usd. Omit to disable, 0 for any loss.
    loss_alert_usd: 1.0
    http_rpc_url: 'https://your-rpc-provider.com/api-key'
    ws_rpc_url: 'wss://your-rpc-provider.com/api-key'
```

Token `symbol`/`decimals` are read from each contract over RPC, and the USD price
is auto-resolved via CoinGecko by symbol. For tokens that are not the wrapped
native token, `base_tokens` is optional — omit it for single-token bots.

`scanner_url` is optional too: when set, the bot address in Telegram messages
becomes a clickable link to its page on the block explorer (e.g.
`https://etherscan.io/address/0x...`); when omitted, the address is shown as
plain monospace text.

### WebSocket with Basic Auth

If your WebSocket endpoint requires HTTP Basic authentication, pass `ws_rpc_url`
as a nested block with `url`, `login` and `password` fields. Plain string form
stays supported for endpoints without auth.

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

## Telegram notifications

Startup message. Per-token balances are fetched via RPC (native `eth_getBalance` + `balanceOf` for each tracked token); USD prices are auto-resolved via CoinGecko:
```
🚀 MEV Monitor Started

• ethereum (WETH — $3,210.50)
  0xYOUR_BOT_ADDRESS
  💰 Balance:
  ETH: 1.5000 ($4,815.75)
  USDC: 1000.0000 ($1,000.00)

⏰ Schedule: 0 * * * *
```

If a token cannot be resolved on CoinGecko, its USD part is omitted and only the amount is shown.

Periodic report. Profit is the multi-token P&L converted to USD (token balance
changes minus gas), and the current per-token balances are refreshed via RPC at
send time:
```
✅ ETHEREUM
0x1234...5678
├ Successful txs: 3/4
└ Total: $+2.50
💰 Balance:
  ETH: 1.4980 ($4,809.32)
  USDC: 1001.7200 ($1,001.72)
```

### Instant loss alerts

`loss_alert_usd` is set per network, next to that bot's `watched_address` — so
you can alert on any loss on a cheap L2 and only on large ones on mainnet, or
leave it out entirely for networks you don't want alerts for.

When it is set, every block containing transactions of the watched address is
priced right after it is read. If its P&L (token balance changes minus gas) is
below `-loss_alert_usd`, a separate message is sent immediately — without
waiting for the next scheduled report. The block still counts towards the
periodic report as usual.

Transaction hashes link to the block explorer when `scanner_url` is configured
(otherwise they are shown as plain monospace text). A block may contain several
transactions of the bot — all of them are listed:
```
🚨 LOSS — ETHEREUM $-10.12
0x1234...5678
├ Block: 21500123
├ Txs: 2 (failed: 1)
├ WETH: -0.004200 ($-10.50)
├ USDC: +1.500000 ($+1.50)
└ Gas: 0.001500 ETH ($3.75)
🔗 0xaa1111...111111, 0xbb2222...222222
```

`loss_alert_usd: 0` alerts on any loss; a higher value (e.g. `5`) filters out
noise from cheap failed transactions. USD prices are cached for a minute, so
frequent blocks do not hammer the CoinGecko API.

## Usage

### Docker

Monitor all bots:
```bash
docker run -d -v ./config.yaml:/app/config.yaml nov1kov/mev-watcher
```

### Docker Compose

Create `docker-compose.yml` next to your `config.yaml`:

```yaml
services:
  mev-watcher:
    image: nov1kov/mev-watcher
    restart: unless-stopped
    volumes:
      - ./config.yaml:/app/config.yaml
```

### Local

```bash
pip install -r requirements.txt
python main.py monitor
python main.py analyze -b ethereum -s 18000000
```

## Commands

`monitor` — subscribe to new blocks via WebSocket:
- `-b, --bot-name <name>` — specific bot (optional; all bots if omitted)

`analyze` — retrospective analysis. Exactly one of the block options is required:
- `-b, --bot-name <name>` — bot to analyze (required)
- `-s, --start-block <N>` — scan from block N to the latest
- `-n, --block <N>` — prefetch and analyze a single block (debug mode)

`-c, --config <path>` — path to config (default `config.yaml`) for both commands.

Examples:
```bash
python main.py monitor -b ethereum
python main.py analyze -b ethereum -s 18000000
python main.py analyze -b ethereum -n 18500000
```

## Tests

```bash
python -m unittest discover tests
```
