# VERUM Meme Intelligence

Standalone Solana/Pump.fun launch research, security evidence, deterministic quantitative analysis and paper trading.

## Product boundary

- No live trading, wallet signing, seed phrases or private-key handling.
- BUY requires complete security evidence, adequate market data, a fresh executable Jupiter quote, and a strategy that passes out-of-sample validation.
- The initial breakout strategy is not validated by default. The expected initial state is WAIT, BLOCKED or INSUFFICIENT_DATA until evidence qualifies.
- Missing provider data is UNKNOWN, never safe.
- Wallet transfers and balances are not treated as realised trading P&L.
- The Risk Manager can veto every candidate. Paper trading is the only execution mode.

## Upstream repository audit

See docs/UPSTREAM_AUDIT.md for the 13-skill source review, test-suite review, licence handling and limitations. The upstream repository README reports 11 active tokens, 52 trades, average expectancy of -0.6R and a 96% simulated probability of halving the account within 50 trades. That result is treated as a warning, not discarded.

## Architecture

- api/: Python 3.12 FastAPI service, provider adapters, token and wallet assessment, deterministic quant engine, strategy lab, risk controls and paper-trade APIs.
- frontend/: React/Vite mobile-first application, optimised for iPhone Safari.
- supabase/migrations/: persistent schema, RLS and transactional paper-trade functions.
- supabase/functions/radar-ingest/: PumpPortal create/migration events, DexScreener profile discovery and time-series market snapshots.
- supabase/functions/paper-monitor/: persistent mark-to-market, stop/target/time-stop checks and quote-backed simulated exits.
- PostgreSQL Cron invokes both Edge Functions independently of an open browser tab.

## Provider matrix

| Provider | Purpose | Access |
|---|---|---|
| PumpPortal | Pump.fun create and migration stream | Public stream; no paid trade subscriptions |
| DexScreener | DEX pairs, price, liquidity, volume and transaction counts | Public endpoints |
| RugCheck | Solana token risk report | Public endpoint |
| GoPlus | Solana token security flags | Public endpoint |
| Jupiter | Executable route quotes | Free keyless access or optional free API key |
| Jupiter Data API / GeckoTerminal | OHLCV history | Public endpoints; GeckoTerminal public API is approximately 10 calls/minute |
| Solana RPC | Token decimals and recent wallet signatures | Public RPC; rate limits apply |

No paid API or transaction service is enabled. PumpPortal account-trade and token-trade subscriptions are intentionally not enabled because some streams can incur SOL-denominated charges. Jupiter quotes are read-only; no swap transaction is built, signed or submitted. Without a Jupiter API key, quote calls are spaced for the public keyless rate limit. An optional free API key raises throughput. GeckoTerminal requests are serialized at a conservative 6.1-second interval; historical replay pages up to 3,000 one-minute candles when the pool has that history. Configure JUPITER_API_KEY in the API project and as a Supabase Edge Function secret if desired.

Snapshot retention is seven days by default to control free-tier database growth. The five-minute Radar job also probes RugCheck, GoPlus, Jupiter, Solana RPC and GeckoTerminal, while recording PumpPortal and DexScreener ingestion status. Provider failures preserve the last successful timestamp and are not treated as healthy.

## API

Versioned base path: /api/v1

- GET /health
- GET /providers
- GET /radar
- GET /tokens/{mint}/analysis (authenticated)
- GET /signals (authenticated)
- GET /wallets/{address} (authenticated)
- GET /paper/account, POST /paper/account
- GET /paper/positions
- POST /paper/trades
- POST /paper/positions/{id}/close
- GET /journal
- GET /strategy/performance
- POST /strategy-lab/backtest
- GET /settings, PUT /settings
- GET /alerts
- Read-only AETHER endpoints: /integration/signals, /integration/tokens/{mint}, /integration/strategies/performance, /integration/paper/results

FastAPI OpenAPI: /openapi.json; interactive documentation: /docs. AETHER integration details are in docs/API_INTEGRATION.md.

All private routes require a Supabase Auth bearer JWT. The API uses the Supabase publishable key and the user's JWT; the service-role key is never placed in the API or frontend environment.

## Deployment

Create two Vercel projects from this GitHub repository:

1. API root directory: platform/api, framework: FastAPI, region: Singapore (sin1).
2. Frontend root directory: platform/frontend, framework: Vite.

API environment:
- SUPABASE_URL
- SUPABASE_PUBLISHABLE_KEY
- JUPITER_API_KEY (optional, free tier)

Frontend environment:
- VITE_API_BASE_URL
- VITE_SUPABASE_URL
- VITE_SUPABASE_PUBLISHABLE_KEY

For Supabase Edge Functions, JUPITER_API_KEY is also optional. Never put SUPABASE_SERVICE_ROLE_KEY in Vercel or browser code. Supabase Edge Functions use their managed service-role environment internally.

After the frontend URL is known, add it to Supabase Authentication URL Configuration and the allowed redirect URLs. Run supabase/cron.sql only after deploying both Edge Functions; replace YOUR_PROJECT_REF with the project reference. The script creates a random schedule secret inside Vault and stores only its SHA-256 hash in a service-role-only table.

## Paper risk defaults

- Virtual starting equity: USD 1,000 (not a deposit and not real funds)
- Risk per trade: 0.5% of paper equity
- Daily loss cap: 2%
- Maximum open positions: 3
- Maximum aggregate exposure: 20%
- Maximum quoted price impact: 1.5%
- Maximum entry deviation from reference price: 2%
- Three consecutive losing exits trigger a pause
- 10% portfolio drawdown triggers a pause
- Strategy time stop: 60 minutes

Paper execution applies a separate 25 bps overhead fee and 50 bps adverse slippage per side in this release. Jupiter route output already reflects quoted AMM fees and price impact; the extra fee and slippage are conservative simulation assumptions, not claims about exact network fees or actual fill quality. The maximum quoted route impact is checked separately against the account limit. Backtests default to 25 bps fee and 50 bps slippage per side, both explicit inputs.

These are conservative simulation defaults, not empirically optimised values. Starting balance is locked after the first paper trade.

## Research methodology

The initial research baseline uses a 15-bar close breakout with 1.5x prior volume, a 1.5 ATR stop, 2R target and 60-bar time exit. Intrabar stop/target conflicts resolve to the stop. Fees and slippage are explicit inputs. The chronological split is 70% in-sample / 30% out-of-sample. The holdout is not used for optimisation. Three expanding-window walk-forward folds, block-bootstrap intervals and Monte Carlo risk-of-ruin are reproducible with a fixed seed.

A strategy is not marked validated unless the holdout has at least 30 trades, positive net expectancy, profit factor above 1.1, a positive 95% block-bootstrap lower bound, simulated probability of 50% drawdown no greater than 5%, and candle-gap coverage within tolerance. A failed or underpowered strategy remains unvalidated. Data gaps are not interpolated.

## Tests

Run the original repository suite and the new platform suite:

    python -m unittest discover -s tests -v
    cd platform/api
    python -m unittest discover -s tests -v
    python -m compileall -q .

GitHub Actions runs both Python suites and compile checks, plus the frontend type-check/build.

## Known limitations in the initial release

- Wallet profitability and coordinated-wallet attribution remain UNKNOWN until complete transaction-level accounting and labelled cluster data exist.
- PumpPortal ingestion is a 12-second WebSocket sampling window every five minutes; it is not a permanent sub-second stream.
- DexScreener latest-profile discovery supplements PumpPortal and is not proof of a Pump.fun launch.
- Jupiter quote availability and route support vary by mint and pool; GeckoTerminal is the OHLCV fallback.
- RugCheck/GoPlus fields such as creator holdings and LP lock state may be absent; missing fields keep security status UNKNOWN.
- Parameter optimisation is not performed in the initial release.
- The first strategy is a research baseline, not a profitability claim.
- Paper monitoring requires a fresh executable Jupiter exit quote; if no route is available or impact exceeds the configured limit, the position remains open and an alert is recorded.
- Initial paper monitor supports a 50% first-target exit and moves the remaining stop to break-even; advanced ATR trailing and full microstructure partial-fill modelling are deferred.
- The Intelligence Council is deterministic and role-based in this release; multiple AI opinions are not used as evidence.
- New-launch alerts are currently available through the Radar feed; per-wallet push notifications and a news-verification pipeline are deferred.

## Licence

The upstream 13-skill repository remains MIT-licensed. Its original LICENSE and copyright notices are retained. Platform-specific additions are separately authored.
