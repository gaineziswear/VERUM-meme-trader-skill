# Upstream 13-skill audit

Repository: gaineziswear/VERUM-meme-trader-skill  
Audit scope: complete Git tree, 13 skill manifests, 13 Python implementations, test suite, fixtures, README, plugin manifest, installation notes and MIT licence.

## Repository-level findings

- The repository contains 13 root skill folders, one Python implementation per skill, a plugin manifest, a README, an MIT licence and a fixture-based unittest suite.
- The original skill implementations use Python standard-library modules only. Network calls use urllib; parsing uses standard-library JSON, XML, CSV, gzip, sockets and SSL.
- Tests are largely deterministic and fixture-driven. They verify repository structure, module contracts, risk rules, broker confirmation, provider parsing and replay calculations; they are not live end-to-end provider acceptance tests.
- The original README reports a historical test across 11 active tokens: 52 trades, average expectancy -0.6R, and a 96% simulated probability of halving the account within 50 trades. The result is a material negative prior. It is not evidence of a profitable strategy.
- Original skill source files and the MIT licence are retained. Platform additions live under platform/. The repository structure test was extended to permit that new product directory.

## Per-skill disposition

| Skill | Original responsibility | VERUM treatment |
|---|---|---|
| Meme Scanner | Multi-provider token discovery and heuristic scoring | Rebuilt as provider-backed Radar plus evidence-gated token analysis. Candidate ranking remains conservative. |
| Meme Radar | Pump.fun create/migration websocket, early event context and follow-up checks | Reused event model. New persistent Edge Function samples create/migration events and supplements with DexScreener profiles. Follow-up dev-wallet and copycat graph analysis is not yet complete. |
| Meme Analyst | RugCheck/GoPlus risk review and token report | Rebuilt as structured security assessment. Missing mint/freeze, holder, creator and LP evidence remains UNKNOWN. |
| Meme News | RSS/social and market-news aggregation | Audited but deferred from the initial product UI. No unverified news is converted into a trading signal. |
| Meme Entry | Breakout/momentum entry criteria and price/volume context | Rebuilt with deterministic indicators, ATR-based levels and a fresh Jupiter route requirement. BUY also requires empirical strategy validation. |
| Meme Exit | Stop/target planning, volatility and cost-aware exits | Rebuilt with ATR-derived levels, two targets, break-even after TP1, stop logic and quote-backed paper exits. Advanced ATR trailing is deferred. |
| Meme Time Machine | Historical candle replay, parameter comparison, Monte Carlo and risk-of-ruin | Rebuilt as chronological 70/30 research, three expanding walk-forward folds, out-of-sample metrics, block-bootstrap intervals and risk-of-ruin. Parameter optimisation is intentionally disabled for certification. |
| Meme Risk | Test-phase gating, loss limits and trade veto | Rebuilt as a server-side SQL Risk Manager with daily loss, exposure, per-trade risk, slippage, consecutive-loss and drawdown controls. |
| Meme Budget | Position sizing and estimated transaction costs | Rebuilt with risk-distance sizing, quote-derived amount and configured exposure/impact caps. Estimates remain simulation inputs. |
| Meme Broker | Explicit confirmation and paper/live broker boundary | Live broker functionality is not carried forward. VERUM has no wallet signer or live-trade endpoint. Paper entries use exact mint and Jupiter quote evidence. |
| Meme Alerts | Local monitoring loop and event alerts | Persistent paper-position monitoring and database alerts are implemented. Push delivery and per-wallet notification rules remain deferred. |
| Meme Whales | Wallet transaction monitoring and observed wallet behaviour | Recent Solana signatures and creator links are exposed. Wallet profitability, common-funding clusters and coordinated-trader claims remain UNKNOWN. |
| Meme Journal | Trade history, P&L and research notes | Rebuilt as persistent, user-isolated paper trades, positions, research runs and alerts. |

## Specific weaknesses carried forward as warnings

1. Breakout expectancy: the upstream negative result is not ignored. The platform starts with BUY disabled and requires an independent holdout with at least 30 trades, positive expectancy after fees/slippage, profit factor above 1.1, a positive 95% block-bootstrap lower bound, no more than 5% simulated probability of a 50% drawdown, and acceptable candle coverage.
2. Candle-only replay: OHLCV replay cannot reproduce bonding-curve state, transaction ordering, sandwiching, pool depth, quote failure, priority fees or executable partial fills. It is a research approximation, not a historical execution simulator.
3. Indicative pricing: a displayed DEX price is not an executable fill. VERUM requires a current Jupiter route quote and enforces a maximum quoted impact before a paper entry or exit.
4. Security field absence: RugCheck and GoPlus schemas are not complete for every token. Missing authority, top-holder, creator and LP lock evidence is UNKNOWN and prevents a PASS.
5. Wallet attribution: transfers, current holdings and token receipts do not prove realised trading profit. No wallet is labelled profitable without a transaction-level cost-basis and realised P&L ledger.
6. Monitoring persistence: the original local alert loop depends on a running process. VERUM moves monitoring into Supabase Edge Functions and PostgreSQL Cron.
7. Provider dependency: public endpoints have rate limits, outages and schema drift. Provider status, source timestamps and evidence provenance are retained; no missing response is interpreted as safe.

## Licence and provenance

The original MIT licence file remains in the repository. The upstream 13 skill directories are not overwritten by the platform implementation. New platform code is independently authored and the upstream project is credited as the design and reference source.
