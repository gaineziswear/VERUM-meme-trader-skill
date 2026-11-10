"""VERUM Meme Intelligence - FastAPI service.

Read-only public market/security providers; authenticated private paper records.
There is intentionally no live-trading, signing, or wallet-key endpoint.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from verum import providers
from verum.quant import (backtest_breakout, build_trade_plan, evaluate_signal,
                         indicator_features, normalize_bars)
from verum.store import authenticated_user, store

APP_VERSION = "0.1.0"
MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
USDC_MINT = providers.USDC_MINT
ENTRY_FEE_RATE = 0.0025
EXIT_FEE_RATE = 0.0025

app = FastAPI(
    title="VERUM Meme Intelligence API",
    version=APP_VERSION,
    description="Evidence-led Solana/Pump.fun intelligence and paper trading. No live execution.",
    docs_url="/docs",
    redoc_url="/redoc",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "apikey"],
)


def _mint(value: str) -> str:
    if not MINT_RE.fullmatch(value):
        raise HTTPException(status_code=422, detail="invalid_solana_mint")
    return value


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if result == result and abs(result) != float("inf") else None
    except (TypeError, ValueError):
        return None


def _best_pair(pairs: list[dict[str, Any]], mint: str) -> dict[str, Any] | None:
    matches = [pair for pair in pairs
               if (pair.get("baseToken") or {}).get("address") == mint]
    if not matches:
        return None
    return max(matches, key=lambda pair: _number((pair.get("liquidity") or {}).get("usd")) or 0)


def _goplus_flag(value: Any) -> bool:
    if isinstance(value, dict):
        value = value.get("status")
    return str(value) == "1" or value is True


def _security(rug: dict[str, Any] | None, goplus: dict[str, Any] | None,
              pair: dict[str, Any] | None) -> dict[str, Any]:
    flags: list[dict[str, str]] = []
    unknown: list[str] = []
    mint_authority = freeze_authority = None
    top10_pct = lp_locked_pct = dev_hold_pct = rug_score = None

    if not rug:
        unknown.append("RugCheck report unavailable")
    else:
        token = rug.get("token") or {}
        has_mint = "mintAuthority" in token or "mintAuthority" in rug
        has_freeze = "freezeAuthority" in token or "freezeAuthority" in rug
        mint_authority = token.get("mintAuthority", rug.get("mintAuthority"))
        freeze_authority = token.get("freezeAuthority", rug.get("freezeAuthority"))
        if str(mint_authority).lower() in ("none", "null", ""):
            mint_authority = None
        if str(freeze_authority).lower() in ("none", "null", ""):
            freeze_authority = None
        if not has_mint:
            unknown.append("Mint authority status unavailable")
        if not has_freeze:
            unknown.append("Freeze authority status unavailable")
        rug_score = _number(rug.get("score"))
        for risk in rug.get("risks") or []:
            if not isinstance(risk, dict):
                continue
            level = str(risk.get("level", "")).lower()
            if level in ("danger", "critical", "high"):
                flags.append({"level": "CRITICAL", "code": "rugcheck_risk",
                              "message": str(risk.get("name") or risk.get("description") or "RugCheck critical risk")})
            elif level in ("warn", "warning", "medium"):
                flags.append({"level": "CAUTION", "code": "rugcheck_warning",
                              "message": str(risk.get("name") or risk.get("description") or "RugCheck warning")})

        percentages = []
        for holder in (rug.get("topHolders") or rug.get("top_holders") or [])[:10]:
            if isinstance(holder, dict):
                value = _number(holder.get("pct", holder.get("percentage")))
                if value is not None:
                    percentages.append(value)
        if percentages:
            top10_pct = sum(percentages)
            if top10_pct <= 1:
                top10_pct *= 100
        else:
            unknown.append("Top-holder concentration unavailable")

        lp_values = []
        for market in rug.get("markets") or []:
            if not isinstance(market, dict):
                continue
            lp = market.get("lp") or market.get("liquidity") or {}
            value = _number(lp.get("lpLockedPct", lp.get("lockedPct", lp.get("locked_pct"))))
            if value is not None:
                lp_values.append(value)
        if lp_values:
            lp_locked_pct = min(lp_values)
            if lp_locked_pct <= 1:
                lp_locked_pct *= 100
        else:
            unknown.append("Liquidity lock/burn evidence unavailable")

        dev_hold_pct = _number(rug.get("creatorBalancePct", rug.get("creatorPercentage")))
        if dev_hold_pct is None:
            creator = rug.get("creator") or {}
            dev_hold_pct = _number(creator.get("balancePct", creator.get("percentage")))
        if dev_hold_pct is not None and dev_hold_pct <= 1:
            dev_hold_pct *= 100
        if dev_hold_pct is None:
            unknown.append("Creator/developer holding concentration unavailable")

    if not goplus:
        unknown.append("GoPlus report unavailable")
    else:
        for key, label in [
            ("mintable", "Token mint authority may still increase supply"),
            ("freezable", "Token freeze authority may restrict transfers"),
            ("balance_mutable_authority", "Authority may modify token balances"),
            ("closable", "Token account closure capability requires review"),
            ("non_transferable", "Token may be non-transferable"),
        ]:
            if key not in goplus:
                unknown.append("GoPlus field unavailable: " + key)
            elif _goplus_flag(goplus.get(key)):
                flags.append({"level": "CRITICAL", "code": key, "message": label})
        if "transfer_fee" in goplus and _goplus_flag(goplus.get("transfer_fee")):
            flags.append({"level": "CRITICAL", "code": "transfer_fee",
                          "message": "Transfer fee is configured"})
        if "transfer_hook" in goplus and _goplus_flag(goplus.get("transfer_hook")):
            flags.append({"level": "CAUTION", "code": "transfer_hook",
                          "message": "Transfer hook is configured"})

    if mint_authority:
        flags.append({"level": "CRITICAL", "code": "mint_authority",
                      "message": "Mint authority is still present"})
    if freeze_authority:
        flags.append({"level": "CRITICAL", "code": "freeze_authority",
                      "message": "Freeze authority is still present"})

    liquidity = _number((pair or {}).get("liquidity", {}).get("usd"))
    if liquidity is None:
        unknown.append("DEX liquidity is unavailable")
    elif liquidity < 10000:
        flags.append({"level": "CRITICAL", "code": "thin_liquidity",
                      "message": "Pool liquidity is below USD 10,000"})
    elif liquidity < 25000:
        flags.append({"level": "CAUTION", "code": "limited_liquidity",
                      "message": "Pool liquidity is below the preferred USD 25,000 threshold"})

    if top10_pct is not None and top10_pct > 40:
        flags.append({"level": "CRITICAL", "code": "holder_concentration",
                      "message": "Top-ten holder concentration exceeds 40%"})
    elif top10_pct is not None and top10_pct > 20:
        flags.append({"level": "CAUTION", "code": "holder_concentration",
                      "message": "Top-ten holder concentration exceeds 20%"})
    if lp_locked_pct is not None and lp_locked_pct < 50:
        flags.append({"level": "CRITICAL", "code": "lp_control",
                      "message": "Less than half of reported LP value is locked or burned"})
    elif lp_locked_pct is not None and lp_locked_pct < 80:
        flags.append({"level": "CAUTION", "code": "lp_control",
                      "message": "LP lock/burn percentage is below 80%"})
    if dev_hold_pct is not None and dev_hold_pct > 10:
        flags.append({"level": "CRITICAL", "code": "creator_concentration",
                      "message": "Creator/developer holding exceeds 10%"})

    critical = any(flag["level"] == "CRITICAL" for flag in flags)
    caution = any(flag["level"] == "CAUTION" for flag in flags)
    status = "AVOID" if critical else "UNKNOWN" if unknown else "CAUTION" if caution else "PASS"
    required_evidence = 8
    coverage = max(0.0, (required_evidence - len(set(unknown))) / required_evidence)
    return {
        "status": status, "flags": flags, "missing_evidence": sorted(set(unknown)),
        "mint_authority": mint_authority, "freeze_authority": freeze_authority,
        "top10_holder_pct": top10_pct, "dev_hold_pct": dev_hold_pct,
        "lp_locked_pct": lp_locked_pct, "rugcheck_score": rug_score,
        "liquidity_usd": liquidity, "goplus_holder_count": _number((goplus or {}).get("holder_count")),
        "coverage": round(coverage, 2),
        "interpretation": "PASS requires complete evidence from the queried providers and no detected flags; it is not a safety guarantee.",
    }

def _council(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    security = analysis["security"]
    market = analysis["market"]
    features = analysis["features"]
    now = time.time()
    evidence = analysis["provenance"]
    fresh = min([item.get("fetched_at", now) for item in evidence if item.get("fetched_at")] or [now])
    age = max(0, int(now - fresh))
    return [
        {"role": "Launch Investigator", "status": "REVIEWED" if analysis.get("launch") else "PARTIAL",
         "finding": analysis.get("launch", {}).get("graduation_status", "No launch event located"),
         "confidence": 0.9 if analysis.get("launch") else 0.2, "freshness_seconds": age},
        {"role": "Security Auditor", "status": security["status"],
         "finding": f'{len(security["flags"])} flags; {len(security["missing_evidence"])} evidence gaps',
         "confidence": security["coverage"], "freshness_seconds": age},
        {"role": "Smart Wallet Investigator", "status": "PARTIAL",
         "finding": "Creator and wallet activity require transaction-level attribution; no profitability claim made",
         "confidence": 0.2, "freshness_seconds": age},
        {"role": "Market Analyst", "status": "REVIEWED" if market.get("price_usd") else "INSUFFICIENT_DATA",
         "finding": "DEX market and liquidity snapshot" if market.get("price_usd") else "No executable DEX market located",
         "confidence": 0.8 if market.get("price_usd") else 0.0, "freshness_seconds": age},
        {"role": "Quant Strategist", "status": features.get("status", "INSUFFICIENT_DATA"),
         "finding": f'RSI {features.get("rsi14")}; ATR {features.get("atr14")}; volume ratio {features.get("volume_ratio")}',
         "confidence": 0.6 if features.get("status") == "OK" else 0.0, "freshness_seconds": age},
        {"role": "Execution Analyst", "status": "REVIEWED" if market.get("quote_available") else "BLOCKED",
         "finding": "Jupiter route available; quoted impact " + str(market.get("price_impact_pct")) + "%"
                    if market.get("quote_available") else "No fresh executable route within the impact limit",
         "confidence": 0.9 if market.get("quote_available") else 0.0, "freshness_seconds": age},
        {"role": "Risk Manager", "status": "VETO" if security["status"] in ("AVOID", "UNKNOWN") else "REVIEW",
         "finding": "Security veto has priority over momentum", "confidence": 1.0, "freshness_seconds": age},
        {"role": "Independent Signal Reviewer", "status": analysis["signal"]["status"],
         "finding": "; ".join(analysis["signal"]["reasons"][:2]),
         "confidence": analysis["signal"]["confidence"], "freshness_seconds": age},
    ]

async def analyse_token(mint: str, launch: dict[str, Any] | None = None,
                        strategy_validated: bool = False) -> dict[str, Any]:
    mint = _mint(mint)
    (pairs, dex_meta), (rug, rug_meta), (goplus, gp_meta), (candle_payload, candle_meta) = await asyncio.gather(
        providers.dex_pairs(mint),
        providers.rugcheck_report(mint),
        providers.goplus_report(mint),
        providers.jupiter_candles(mint, 500),
    )
    pair = _best_pair(pairs, mint)
    bars = normalize_bars(candle_payload)
    if len(bars) < 120 and pair and pair.get("pairAddress"):
        gecko_payload, gecko_meta = await providers.gecko_candles(pair["pairAddress"], 500)
        gecko_bars = normalize_bars(gecko_payload)
        if len(gecko_bars) > len(bars):
            bars, candle_meta = gecko_bars, gecko_meta

    security = _security(rug, goplus, pair)
    features = indicator_features(bars)
    txns = ((pair or {}).get("txns") or {}).get("h1") or {}
    buys, sells = int(txns.get("buys") or 0), int(txns.get("sells") or 0)
    buy_sell_ratio = buys / max(sells, 1) if buys + sells > 0 else None
    graduated = bool((launch or {}).get("graduation_status") in ("GRADUATED", "MIGRATED") or pair)
    lifecycle = "GRADUATED" if graduated else "BONDING_CURVE" if launch else "UNKNOWN"
    liquidity = _number((pair or {}).get("liquidity", {}).get("usd"))

    quote = None
    quote_meta = {"status": "UNAVAILABLE", "source": "Jupiter quote",
                  "fetched_at": time.time(), "error": "no_graduated_pair"}
    if pair and lifecycle == "GRADUATED":
        quote, quote_meta = await providers.jupiter_quote(USDC_MINT, mint, 25_000_000, 100)
    impact_raw = _number((quote or {}).get("priceImpactPct"))
    price_impact_pct = (
        abs(impact_raw * 100.0 if abs(impact_raw) < 1 else impact_raw)
        if impact_raw is not None else None
    )
    quote_feasible = bool(quote and price_impact_pct is not None and price_impact_pct <= 1.5)
    signal = evaluate_signal(features, security["status"], lifecycle, liquidity,
                             buy_sell_ratio, strategy_validated, quote_feasible, price_impact_pct)
    plan = build_trade_plan(features, liquidity)
    market = {
        "pair_address": (pair or {}).get("pairAddress"), "dex_id": (pair or {}).get("dexId"),
        "price_usd": _number((pair or {}).get("priceUsd")), "liquidity_usd": liquidity,
        "volume_m5": _number(((pair or {}).get("volume") or {}).get("m5")),
        "volume_h1": _number(((pair or {}).get("volume") or {}).get("h1")),
        "volume_h24": _number(((pair or {}).get("volume") or {}).get("h24")),
        "buys_h1": buys, "sells_h1": sells,
        "price_change": (pair or {}).get("priceChange") or {},
        "market_cap": _number((pair or {}).get("marketCap")), "fdv": _number((pair or {}).get("fdv")),
        "pair_created_at": (pair or {}).get("pairCreatedAt"),
        "quote_available": quote_feasible, "price_impact_pct": price_impact_pct,
        "quote_route": (quote or {}).get("routePlan"),
    }
    provenance = [dex_meta, rug_meta, gp_meta, candle_meta, quote_meta]
    coverage = sum(1 for item in provenance if item.get("status") == "OK") / max(1, len(provenance))
    result = {
        "mint": mint, "launch": launch or {},
        "token": {
            "name": (launch or {}).get("name") or ((pair or {}).get("baseToken") or {}).get("name"),
            "symbol": (launch or {}).get("symbol") or ((pair or {}).get("baseToken") or {}).get("symbol"),
            "creator_wallet": (launch or {}).get("creator_wallet"),
            "metadata_uri": (launch or {}).get("metadata_uri"),
        },
        "lifecycle": lifecycle, "security": security, "market": market,
        "features": features, "signal": signal, "trade_plan": plan,
        "evidence_coverage": round(coverage, 3),
        "data_freshness": {"checked_at": datetime.now(timezone.utc).isoformat(),
                           "max_age_seconds": max(0, int(time.time() - min(
                               [x.get("fetched_at", time.time()) for x in provenance] or [time.time()])))},
        "provenance": provenance,
    }
    result["council"] = _council(result)
    return result

async def _account(user_id: str, access_token: str) -> dict[str, Any]:
    rows = await store.select("paper_accounts", access_token,
                              {"select": "*", "user_id": f"eq.{user_id}", "limit": "1"})
    if rows:
        return rows[0]
    inserted = await store.upsert("paper_accounts", {"user_id": user_id}, access_token, "user_id")
    if isinstance(inserted, list) and inserted:
        return inserted[0]
    rows = await store.select("paper_accounts", access_token,
                              {"select": "*", "user_id": f"eq.{user_id}", "limit": "1"})
    if not rows:
        raise HTTPException(status_code=500, detail="paper_account_initialisation_failed")
    return rows[0]


class PaperTradeRequest(BaseModel):
    mint: str
    risk_pct: float | None = Field(default=None, ge=0.1, le=2.0)
    strategy: str = "lifecycle_momentum"


class BacktestRequest(BaseModel):
    mint: str
    fee_bps_per_side: float = Field(default=25.0, ge=0, le=300)
    slippage_bps_per_side: float = Field(default=50.0, ge=0, le=500)


class SettingsRequest(BaseModel):
    timezone: str = "UTC"
    paper_starting_balance: float = Field(default=1000, gt=0, le=1000000)
    max_risk_per_trade_pct: float = Field(default=0.5, gt=0, le=2)
    max_daily_loss_pct: float = Field(default=2, gt=0, le=10)
    max_open_positions: int = Field(default=3, ge=1, le=10)
    max_total_exposure_pct: float = Field(default=20, gt=0, le=100)
    max_slippage_pct: float = Field(default=1.5, gt=0, le=10)


@app.get("/")
async def root() -> dict[str, Any]:
    return {"service": "VERUM Meme Intelligence API", "version": APP_VERSION,
            "docs": "/docs", "paper_only": True}


@app.get("/api/v1/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "service": "verum-api", "version": APP_VERSION,
            "database_configured": store.ready(), "paper_only": True,
            "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/v1/providers")
async def provider_status() -> dict[str, Any]:
    rows = await store.select("provider_status", params={
        "select": "provider,status,last_success_at,last_error,records_seen,latency_ms,updated_at",
        "order": "provider.asc",
    })
    return {"providers": rows, "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/v1/radar")
async def radar(limit: int = 50) -> dict[str, Any]:
    rows = await store.select("token_launches", params={
        "select": "*", "order": "last_seen_at.desc", "limit": str(max(1, min(limit, 100))),
    })
    snapshots = await store.select("token_market_snapshots", params={
        "select": "mint,captured_at,pair_address,dex_id,price_usd,liquidity_usd,volume_m5,volume_h1,volume_h24,buys_m5,sells_m5,price_change_m5,market_cap,fdv",
        "order": "captured_at.desc", "limit": "500",
    })
    latest = {}
    for snapshot in snapshots:
        latest.setdefault(snapshot["mint"], snapshot)
    for row in rows:
        row["market"] = latest.get(row["mint"])
    return {"tokens": rows, "count": len(rows), "as_of": datetime.now(timezone.utc).isoformat()}

@app.get("/api/v1/tokens/{mint}/analysis")
async def token_analysis(mint: str, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    mint = _mint(mint)
    launches = await store.select("token_launches", user["access_token"], {
        "select": "*", "mint": f"eq.{mint}", "limit": "1",
    })
    research = await store.select("research_runs", user["access_token"], {
        "select": "result", "mint": f"eq.{mint}", "limit": "30",
    })
    validated = any((row.get("result") or {}).get("strategy_validation") == "VALIDATED"
                    for row in research)
    result = await analyse_token(mint, launches[0] if launches else None, validated)
    return result


@app.get("/api/v1/signals")
async def signals(limit: int = 12,
                  user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    launches = await store.select("token_launches", user["access_token"], {
        "select": "*", "order": "last_seen_at.desc", "limit": str(max(1, min(limit, 20))),
    })
    research = await store.select("research_runs", user["access_token"], {
        "select": "mint,result", "limit": "100",
    })
    validated_mints = {
        row["mint"] for row in research
        if (row.get("result") or {}).get("strategy_validation") == "VALIDATED"
    }
    semaphore = asyncio.Semaphore(4)

    async def one(launch: dict[str, Any]) -> dict[str, Any] | None:
        async with semaphore:
            try:
                return await analyse_token(launch["mint"], launch, launch["mint"] in validated_mints)
            except Exception as exc:
                return {
                    "mint": launch.get("mint"),
                    "token": {"name": launch.get("name"), "symbol": launch.get("symbol")},
                    "lifecycle": launch.get("graduation_status", "UNKNOWN"),
                    "market": {"price_usd": None, "liquidity_usd": None},
                    "security": {"status": "UNKNOWN", "flags": [],
                                 "missing_evidence": ["Analysis provider or schema error"]},
                    "signal": {"status": "INSUFFICIENT_DATA", "confidence": 0.0,
                               "reasons": ["Analysis unavailable; no signal emitted"],
                               "strategy_validation": "UNVALIDATED"},
                    "trade_plan": None, "evidence_coverage": 0.0,
                    "provenance": [], "error_code": type(exc).__name__,
                }

    analyses = await asyncio.gather(*(one(row) for row in launches))
    results = [item for item in analyses if item]
    results.sort(key=lambda item: (
        item["signal"]["status"] == "BUY",
        item["signal"]["confidence"],
        item["evidence_coverage"],
    ), reverse=True)
    return {"signals": results, "count": len(results),
            "policy": "BUY requires PASS security, fresh executable quotes and validated out-of-sample strategy evidence."}


@app.get("/api/v1/wallets/{address}")
async def wallet_analysis(address: str,
                          user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    if not MINT_RE.fullmatch(address):
        raise HTTPException(status_code=422, detail="invalid_solana_wallet_address")
    rows, provenance = await providers.solana_signatures(address, 100)
    launches = await store.select("token_launches", user["access_token"], {
        "select": "mint,name,symbol,first_seen_at", "creator_wallet": f"eq.{address}",
        "limit": "100",
    })
    timestamps = [row.get("blockTime") for row in rows if row.get("blockTime")]
    return {
        "wallet": address, "recent_transactions": len(rows),
        "first_observed_transaction": min(timestamps) if timestamps else None,
        "last_observed_transaction": max(timestamps) if timestamps else None,
        "creator_launches": launches,
        "realised_pnl_usd": None, "performance_status": "UNKNOWN",
        "coverage": {"transactions_sampled": len(rows), "sample_limit": 100,
                     "complete_trade_ledger": False},
        "conclusion": "Wallet activity is observable; profitability is not inferred from transfers or current holdings.",
        "provenance": [provenance],
    }


@app.get("/api/v1/paper/account")
async def get_paper_account(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    account = await _account(user["id"], user["access_token"])
    return {"account": account, "paper_only": True}


@app.post("/api/v1/paper/account")
async def initialise_paper_account(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    account = await _account(user["id"], user["access_token"])
    return {"account": account, "paper_only": True}


@app.get("/api/v1/paper/positions")
async def paper_positions(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    rows = await store.select("paper_positions", user["access_token"], {
        "select": "*", "order": "opened_at.desc", "limit": "100",
    })
    return {"positions": rows, "count": len(rows)}


@app.post("/api/v1/paper/trades")
async def open_paper_trade(body: PaperTradeRequest,
                           user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    mint = _mint(body.mint)
    research = await store.select("research_runs", user["access_token"], {
        "select": "result", "mint": f"eq.{mint}", "limit": "30",
    })
    strategy_validated = any((row.get("result") or {}).get("strategy_validation") == "VALIDATED"
                             for row in research)
    analysis = await analyse_token(mint, strategy_validated=strategy_validated)
    if analysis["signal"]["status"] != "BUY":
        raise HTTPException(status_code=409, detail={
            "code": "SIGNAL_GATE", "status": analysis["signal"]["status"],
            "reasons": analysis["signal"]["reasons"],
        })
    if analysis["security"]["status"] != "PASS":
        raise HTTPException(status_code=409, detail={
            "code": "SECURITY_VETO", "status": analysis["security"]["status"],
            "missing_evidence": analysis["security"]["missing_evidence"],
            "flags": analysis["security"]["flags"],
        })
    if analysis["lifecycle"] != "GRADUATED":
        raise HTTPException(status_code=409, detail="bonding_curve_token_not_executable_on_jupiter")
    features = analysis["features"]
    if features.get("status") != "OK":
        raise HTTPException(status_code=409, detail="insufficient_ohlcv_for_volatility_adjusted_risk")
    plan = analysis["trade_plan"]
    account = await _account(user["id"], user["access_token"])
    equity = _number(account.get("equity")) or _number(account.get("starting_balance")) or 1000.0
    risk_pct = body.risk_pct or _number(account.get("max_risk_per_trade_pct")) or 0.5
    risk_usd = equity * risk_pct / 100.0
    price = _number(features.get("price"))
    stop = _number(plan.get("stop_loss"))
    if not price or not stop or stop >= price:
        raise HTTPException(status_code=409, detail="invalid_volatility_adjusted_trade_plan")
    stop_distance_pct = (price - stop) / price
    sizing_cost_rate = ENTRY_FEE_RATE + EXIT_FEE_RATE + 0.005
    notional = risk_usd / (stop_distance_pct + sizing_cost_rate)
    cash = _number(account.get("cash_balance")) or 0
    notional = min(notional, cash / (1 + ENTRY_FEE_RATE))
    if notional < 5:
        raise HTTPException(status_code=409, detail="paper_size_below_minimum_after_risk_controls")
    amount_raw = int(notional * 1_000_000)
    quote, quote_meta = await providers.jupiter_quote(USDC_MINT, mint, amount_raw, 100)
    if not quote:
        raise HTTPException(status_code=409, detail="no_executable_jupiter_route_for_selected_mint")
    impact_raw = _number(quote.get("priceImpactPct"))
    if impact_raw is None:
        raise HTTPException(status_code=409, detail="quote_price_impact_unknown")
    impact_pct = abs(impact_raw * 100.0 if abs(impact_raw) < 1 else impact_raw)
    max_impact = _number(account.get("max_slippage_pct")) or 1.5
    if impact_pct > max_impact:
        raise HTTPException(status_code=409, detail={
            "code": "PRICE_IMPACT_LIMIT", "price_impact_pct": impact_pct,
            "maximum_pct": max_impact,
        })
    decimals, decimals_meta = await providers.token_decimals(mint)
    if decimals is None:
        raise HTTPException(status_code=409, detail="token_decimals_unknown")
    quantity = int(quote["outAmount"]) / (10 ** decimals)
    if quantity <= 0:
        raise HTTPException(status_code=409, detail="invalid_quote_output")
    entry_fee = notional * ENTRY_FEE_RATE
    total_cost = notional + entry_fee
    entry_price = total_cost / quantity
    entry_deviation_pct = abs(entry_price - price) / price * 100.0
    if entry_deviation_pct > 2.0:
        raise HTTPException(status_code=409, detail={
            "code": "ENTRY_DEVIATION_LIMIT", "entry_deviation_pct": round(entry_deviation_pct, 4),
            "maximum_pct": 2.0,
        })
    stop = min(stop, entry_price - (1.5 * (_number(features.get("atr14")) or 0)))
    if stop <= 0 or stop >= entry_price:
        raise HTTPException(status_code=409, detail="stop_invalid_after_quote_deviation")
    risk_at_stop = quantity * (entry_price - stop) + total_cost * EXIT_FEE_RATE
    if risk_at_stop > risk_usd * 1.05:
        raise HTTPException(status_code=409, detail={
            "code": "RISK_LIMIT", "risk_at_stop_usd": round(risk_at_stop, 4),
            "risk_budget_usd": round(risk_usd, 4),
        })
    risk_per_token = entry_price - stop
    tp1, tp2 = entry_price + 2 * risk_per_token, entry_price + 3 * risk_per_token
    quote_age = max(0, time.time() - quote_meta.get("quote_at", time.time()))
    if quote_age > 30:
        raise HTTPException(status_code=409, detail="stale_jupiter_quote")
    result = await store.rpc("open_paper_position", {
        "p_mint": mint, "p_symbol": analysis["token"].get("symbol"),
        "p_qty": quantity, "p_amount_usd": total_cost,
        "p_entry_price": entry_price, "p_stop_loss": stop,
        "p_take_profit_1": tp1, "p_take_profit_2": tp2,
        "p_risk_usd": risk_at_stop, "p_fees_usd": entry_fee,
        "p_slippage_pct": impact_pct, "p_entry_quote": {
            "provider": "Jupiter", "quote_at": quote_meta.get("quote_at"),
            "price_impact_pct": impact_pct, "route_plan": quote.get("routePlan"),
            "in_amount": quote.get("inAmount"), "out_amount": quote.get("outAmount"),
            "quote_age_seconds": quote_age,
        }, "p_strategy": body.strategy,
    }, user["access_token"])
    return {"status": "OPEN", "position_id": result, "mint": mint,
            "symbol": analysis["token"].get("symbol"), "quantity": quantity,
            "entry_price": entry_price, "amount_usd": total_cost,
            "stop_loss": stop, "take_profit_1": tp1, "take_profit_2": tp2,
            "risk_at_stop_usd": risk_at_stop, "quote": quote_meta,
            "paper_only": True}


@app.post("/api/v1/paper/positions/{position_id}/close")
async def close_paper_position(position_id: str,
                               user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    positions = await store.select("paper_positions", user["access_token"], {
        "select": "*", "id": f"eq.{position_id}", "status": "eq.OPEN", "limit": "1",
    })
    if not positions:
        raise HTTPException(status_code=404, detail="open_paper_position_not_found")
    position = positions[0]
    mint = _mint(position["mint"])
    decimals, _ = await providers.token_decimals(mint)
    if decimals is None:
        raise HTTPException(status_code=409, detail="token_decimals_unknown")
    quantity = _number(position.get("qty")) or 0
    raw_amount = int(quantity * (10 ** decimals))
    quote, quote_meta = await providers.jupiter_quote(mint, USDC_MINT, raw_amount, 100)
    if not quote:
        raise HTTPException(status_code=409, detail="no_executable_jupiter_exit_route")
    impact_raw = _number(quote.get("priceImpactPct"))
    if impact_raw is None:
        raise HTTPException(status_code=409, detail="exit_quote_price_impact_unknown")
    impact_pct = abs(impact_raw * 100.0 if abs(impact_raw) < 1 else impact_raw)
    account = await _account(user["id"], user["access_token"])
    max_impact = _number(account.get("max_slippage_pct")) or 1.5
    if impact_pct > max_impact:
        raise HTTPException(status_code=409, detail="exit_quote_price_impact_limit")
    quote_age = max(0, time.time() - quote_meta.get("quote_at", time.time()))
    if quote_age > 30:
        raise HTTPException(status_code=409, detail="stale_jupiter_exit_quote")
    proceeds = int(quote["outAmount"]) / 1_000_000
    exit_fee = proceeds * EXIT_FEE_RATE
    exit_price = proceeds / quantity if quantity else 0
    result = await store.rpc("close_paper_position", {
        "p_position_id": position_id, "p_exit_price": exit_price,
        "p_proceeds_usd": proceeds, "p_fees_usd": exit_fee,
        "p_exit_quote": {"provider": "Jupiter", "quote_at": quote_meta.get("quote_at"),
                         "price_impact_pct": quote.get("priceImpactPct"),
                         "route_plan": quote.get("routePlan")},
        "p_reason": "manual_paper_close",
    }, user["access_token"])
    return {"status": "CLOSED", "result": result, "exit_price": exit_price,
            "proceeds_usd": proceeds, "fees_usd": exit_fee, "paper_only": True}


@app.get("/api/v1/journal")
async def journal(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    rows = await store.select("paper_trades", user["access_token"], {
        "select": "*", "order": "created_at.desc", "limit": "250",
    })
    realised = [row for row in rows if row.get("side") == "SELL" and row.get("pnl_usd") is not None]
    total = sum(_number(row.get("pnl_usd")) or 0 for row in realised)
    wins = sum(1 for row in realised if (_number(row.get("pnl_usd")) or 0) > 0)
    return {"trades": rows, "closed_trades": len(realised),
            "realised_pnl_usd": total,
            "win_rate": wins / len(realised) if realised else None,
            "performance_claim": "DESCRIPTIVE_ONLY; no profitability inference from small samples"}


@app.get("/api/v1/strategy/performance")
async def strategy_performance(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    rows = await store.select("research_runs", user["access_token"], {
        "select": "*", "order": "created_at.desc", "limit": "30",
    })
    return {"research_runs": rows, "count": len(rows),
            "validated_strategies": sum(1 for row in rows
                                        if (row.get("result") or {}).get("strategy_validation") == "VALIDATED")}


@app.post("/api/v1/strategy-lab/backtest")
async def strategy_lab(body: BacktestRequest,
                       user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    mint = _mint(body.mint)
    pairs, dex_meta = await providers.dex_pairs(mint)
    pair = _best_pair(pairs, mint)
    payload, meta = await providers.jupiter_candles(mint, 1000)
    bars = normalize_bars(payload)
    if len(bars) < 120 and pair and pair.get("pairAddress"):
        gecko_payload, gecko_meta = await providers.gecko_candles(pair["pairAddress"], 1000)
        gecko_bars = normalize_bars(gecko_payload)
        if len(gecko_bars) > len(bars):
            bars, meta = gecko_bars, gecko_meta
    result = backtest_breakout(bars, body.fee_bps_per_side, body.slippage_bps_per_side)
    if result.get("status") == "COMPLETE":
        result["data_provenance"] = {"candles": meta, "dex_pair": dex_meta}
        result["data_gaps"] = {
            "observations": len(bars),
            "coverage_pct": (result.get("data_quality") or {}).get("coverage_pct"),
            "gap_count": (result.get("data_quality") or {}).get("gap_count"),
            "max_gap_seconds": (result.get("data_quality") or {}).get("max_gap_seconds"),
            "note": "Observed candles only; missing intervals are not interpolated.",
        }
        await store.insert("research_runs", {
            "user_id": user["id"], "mint": mint, "strategy": "15m_breakout_1.5x_volume",
            "dataset_fingerprint": result["dataset_fingerprint"],
            "data_start": datetime.fromtimestamp(bars[0]["t"], timezone.utc).isoformat(),
            "data_end": datetime.fromtimestamp(bars[-1]["t"], timezone.utc).isoformat(),
            "bars": len(bars), "in_sample_metrics": result["in_sample"],
            "out_of_sample_metrics": result["out_of_sample"],
            "assumptions": result["assumptions"], "result": result,
        }, user["access_token"])
    return {"mint": mint, "result": result, "provenance": {"candles": meta, "dex_pair": dex_meta}}

@app.get("/api/v1/settings")
async def get_settings(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    rows = await store.select("user_settings", user["access_token"], {
        "select": "*", "user_id": f"eq.{user['id']}", "limit": "1",
    })
    account = await _account(user["id"], user["access_token"])
    return {"settings": rows[0] if rows else None, "paper_account": account}


@app.put("/api/v1/settings")
async def update_settings(body: SettingsRequest,
                          user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    account = await _account(user["id"], user["access_token"])
    open_positions = await store.select("paper_positions", user["access_token"], {
        "select": "id", "status": "eq.OPEN", "limit": "1",
    })
    trade_history = await store.select("paper_trades", user["access_token"], {
        "select": "id", "limit": "1",
    })
    starting_balance_changed = abs(
        (_number(account.get("starting_balance")) or 1000.0) - body.paper_starting_balance
    ) > 0.0001
    if starting_balance_changed and (open_positions or trade_history):
        raise HTTPException(status_code=409, detail="paper_starting_balance_locked_after_activity")

    payload = body.model_dump()
    payload["user_id"] = user["id"]
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    settings_rows = await store.upsert("user_settings", payload, user["access_token"], "user_id")
    account_patch = {
        "max_risk_per_trade_pct": body.max_risk_per_trade_pct,
        "max_daily_loss_pct": body.max_daily_loss_pct,
        "max_open_positions": body.max_open_positions,
        "max_total_exposure_pct": body.max_total_exposure_pct,
        "max_slippage_pct": body.max_slippage_pct,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if starting_balance_changed:
        account_patch.update({
            "starting_balance": body.paper_starting_balance,
            "cash_balance": body.paper_starting_balance,
            "equity": body.paper_starting_balance,
        })
    account_rows = await store.patch(
        "paper_accounts", user["access_token"],
        {"user_id": f"eq.{user['id']}"}, account_patch,
    )
    return {
        "settings": settings_rows[0] if isinstance(settings_rows, list) and settings_rows else payload,
        "paper_account": account_rows[0] if isinstance(account_rows, list) and account_rows else account,
    }

@app.get("/api/v1/alerts")
async def alerts(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    rows = await store.select("alerts", user["access_token"], {
        "select": "*", "order": "created_at.desc", "limit": "100",
    })
    return {"alerts": rows, "count": len(rows)}


# AETHER-facing read-only surface. AETHER uses a dedicated Supabase service user
# JWT; it receives no paper-trade mutation routes and no live-execution capability.
@app.get("/api/v1/integration/signals")
async def integration_signals(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    return await signals(limit=20, user=user)


@app.get("/api/v1/integration/tokens/{mint}")
async def integration_token(mint: str,
                            user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    return await token_analysis(mint, user)


@app.get("/api/v1/integration/strategies/performance")
async def integration_performance(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    return await strategy_performance(user)


@app.get("/api/v1/integration/paper/results")
async def integration_paper_results(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    return await journal(user)
