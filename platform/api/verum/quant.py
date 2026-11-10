"""Deterministic, reproducible quantitative primitives for VERUM.

All calculations consume timestamped OHLCV observations. No future candle is
used to make a decision on an earlier candle. Unknown inputs remain unknown.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from statistics import mean
from typing import Any


def normalize_bars(payload: Any) -> list[dict[str, float]]:
    """Normalize Jupiter candles, GeckoTerminal OHLCV and fixture bars."""
    rows: list[dict[str, float]] = []
    if isinstance(payload, dict) and isinstance(payload.get("candles"), list):
        source = payload["candles"]
        for item in source:
            try:
                rows.append({
                    "t": float(item.get("time", item.get("t"))),
                    "o": float(item.get("open", item.get("o"))),
                    "h": float(item.get("high", item.get("h"))),
                    "l": float(item.get("low", item.get("l"))),
                    "c": float(item.get("close", item.get("c"))),
                    "v": float(item.get("volume", item.get("v", 0)) or 0),
                })
            except (TypeError, ValueError, AttributeError):
                continue
    elif isinstance(payload, dict):
        attrs = (payload.get("data") or {}).get("attributes") or {}
        for item in attrs.get("ohlcv_list") or []:
            try:
                t, o, h, low, c, v = item[:6]
                rows.append({"t": float(t), "o": float(o), "h": float(h),
                             "l": float(low), "c": float(c), "v": float(v or 0)})
            except (TypeError, ValueError):
                continue
    elif isinstance(payload, list):
        for item in payload:
            try:
                rows.append({"t": float(item.get("t", item.get("time"))),
                             "o": float(item["o"]), "h": float(item["h"]),
                             "l": float(item["l"]), "c": float(item["c"]),
                             "v": float(item.get("v", item.get("volume", 0)) or 0)})
            except (TypeError, ValueError, KeyError, AttributeError):
                continue
    deduped = {}
    for row in rows:
        if row["t"] > 1e12:
            row["t"] /= 1000.0
        if row["t"] > 0 and row["o"] > 0 and row["h"] > 0 and row["l"] > 0 and row["c"] > 0 and row["v"] >= 0:
            deduped[row["t"]] = row
    return [deduped[key] for key in sorted(deduped)]


def ema(values: list[float], period: int) -> float | None:
    if period < 1 or len(values) < period:
        return None
    alpha = 2.0 / (period + 1.0)
    result = sum(values[:period]) / period
    for value in values[period:]:
        result = alpha * value + (1.0 - alpha) * result
    return result


def rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) < period + 1:
        return None
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(change, 0.0) for change in changes[-period:]]
    losses = [max(-change, 0.0) for change in changes[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def atr(bars: list[dict[str, float]], period: int = 14) -> float | None:
    if len(bars) < period + 1:
        return None
    ranges = []
    for previous, current in zip(bars[:-1], bars[1:]):
        ranges.append(max(current["h"] - current["l"],
                          abs(current["h"] - previous["c"]),
                          abs(current["l"] - previous["c"])))
    return sum(ranges[-period:]) / period


def indicator_features(bars: list[dict[str, float]]) -> dict[str, Any]:
    if len(bars) < 51:
        return {"status": "INSUFFICIENT_DATA", "bars": len(bars),
                "required_bars": 51, "missing": ["at least 51 completed candles"]}
    closes = [bar["c"] for bar in bars]
    volumes = [bar["v"] for bar in bars]
    last = bars[-1]
    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    atr14 = atr(bars, 14)
    average_volume = mean(volumes[-21:-1]) if len(volumes) >= 21 else None
    volume_ratio = (volumes[-1] / average_volume) if average_volume and average_volume > 0 else None
    return_5 = ((closes[-1] / closes[-6]) - 1.0) * 100.0 if len(closes) >= 6 else None
    return_15 = ((closes[-1] / closes[-16]) - 1.0) * 100.0 if len(closes) >= 16 else None
    volatility_pct = (atr14 / last["c"] * 100.0) if atr14 and last["c"] else None
    return {
        "status": "OK", "bars": len(bars), "as_of": int(last["t"]),
        "price": last["c"], "ema20": ema20, "ema50": ema50,
        "rsi14": rsi(closes), "atr14": atr14, "atr_pct": volatility_pct,
        "volume_ratio": volume_ratio, "return_5m_pct": return_5,
        "return_15m_pct": return_15,
        "trend": "BULLISH" if ema20 and ema50 and last["c"] > ema20 > ema50
                 else "BEARISH" if ema20 and ema50 and last["c"] < ema20 < ema50
                 else "RANGE",
    }


def build_trade_plan(features: dict[str, Any], liquidity_usd: float | None,
                     max_risk_pct: float = 0.5) -> dict[str, Any]:
    price = features.get("price")
    atr_value = features.get("atr14")
    if not price or not atr_value or atr_value <= 0:
        return {"status": "INSUFFICIENT_DATA", "missing": ["price", "ATR"]}
    stop = price - 1.5 * atr_value
    if stop <= 0 or stop >= price:
        return {"status": "BLOCKED", "reason": "invalid volatility-adjusted stop"}
    risk_per_token = price - stop
    tp1 = price + 2.0 * risk_per_token
    tp2 = price + 3.0 * risk_per_token
    deviation = max(0.5 * atr_value, price * 0.002)
    impact_limit = min(2.0, max(0.25, 100.0 * (500.0 / max(liquidity_usd or 500.0, 500.0))))
    return {
        "status": "WAIT", "entry": price, "stop_loss": stop,
        "take_profit_1": tp1, "take_profit_2": tp2,
        "risk_reward_1": 2.0, "risk_reward_2": 3.0,
        "max_entry_deviation": deviation,
        "max_price_impact_pct": impact_limit,
        "risk_per_token": risk_per_token,
        "sizing_method": "equity risk divided by volatility-adjusted stop distance",
        "max_risk_pct": max_risk_pct,
    }


def evaluate_signal(features: dict[str, Any], security_status: str,
                    lifecycle: str, liquidity_usd: float | None,
                    buy_sell_ratio: float | None = None,
                    strategy_validated: bool = False,
                    execution_feasible: bool = False,
                    price_impact_pct: float | None = None) -> dict[str, Any]:
    """Conservative deterministic gate. Security, quote and validation are mandatory."""
    if security_status == "AVOID":
        return {"status": "BLOCKED", "confidence": 0.0,
                "reasons": ["Security assessment contains critical risk findings"]}
    if security_status != "PASS":
        return {"status": "INSUFFICIENT_DATA", "confidence": 0.0,
                "reasons": ["Security evidence is incomplete or inconclusive"]}
    if lifecycle != "GRADUATED":
        return {"status": "WAIT", "confidence": 0.0,
                "reasons": ["Bonding-curve tokens are not yet eligible for paper execution"]}
    if features.get("status") != "OK":
        return {"status": "INSUFFICIENT_DATA", "confidence": 0.0,
                "reasons": ["Insufficient completed OHLCV observations"]}
    reasons = []
    trend = features.get("trend") == "BULLISH"
    momentum = (features.get("rsi14") is not None
                and 50 <= features["rsi14"] <= 72
                and (features.get("return_5m_pct") or 0) > 0)
    volume = features.get("volume_ratio") is not None and features["volume_ratio"] >= 1.5
    pressure = buy_sell_ratio is not None and buy_sell_ratio >= 1.05
    depth = liquidity_usd is not None and liquidity_usd >= 25000
    quote_ok = execution_feasible and price_impact_pct is not None and price_impact_pct <= 1.5
    for ok, label in [
        (trend, "EMA trend is not bullish"),
        (momentum, "momentum confirmation is absent"),
        (volume, "volume expansion is below 1.5x"),
        (pressure, "buy pressure is not confirmed"),
        (depth, "liquidity is below the minimum depth gate"),
        (quote_ok, "fresh executable Jupiter quote is unavailable or impact exceeds 1.5%"),
    ]:
        if not ok:
            reasons.append(label)
    if not strategy_validated:
        reasons.append("Strategy has not passed independent out-of-sample validation")
    coverage = sum([trend, momentum, volume, pressure, depth, quote_ok]) / 6.0
    confidence = round(coverage * (0.35 if not strategy_validated else 0.8), 3)
    status = "BUY" if not reasons else "WAIT"
    return {"status": status, "confidence": confidence, "reasons": reasons,
            "evidence_coverage": round(coverage, 3),
            "strategy_validation": "VALIDATED" if strategy_validated else "UNVALIDATED",
            "execution_feasible": bool(quote_ok), "price_impact_pct": price_impact_pct}

def dataset_fingerprint(bars: list[dict[str, float]]) -> str:
    payload = json.dumps(bars, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _trade_metrics(trades: list[dict[str, float]]) -> dict[str, Any]:
    if not trades:
        return {"trades": 0, "expectancy_r": None, "profit_factor": None,
                "win_rate": None, "max_drawdown_r": None}
    rs = [trade["r_net"] for trade in trades]
    wins = [value for value in rs if value > 0]
    losses = [value for value in rs if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    equity = peak = 0.0
    max_drawdown = 0.0
    for value in rs:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return {
        "trades": len(rs), "wins": len(wins), "losses": len(losses),
        "win_rate": len(wins) / len(rs),
        "expectancy_r": mean(rs),
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
        "average_win_r": mean(wins) if wins else None,
        "average_loss_r": mean(losses) if losses else None,
        "max_drawdown_r": max_drawdown,
        "best_trade_r": max(rs), "worst_trade_r": min(rs),
    }


def _breakout_trades(bars: list[dict[str, float]], fee_bps: float,
                     slippage_bps: float, start: int, end: int) -> list[dict[str, float]]:
    trades = []
    i = max(start, 20)
    while i < end - 2:
        prior = bars[max(0, i - 15):i]
        if len(prior) < 15:
            i += 1
            continue
        range_high = max(bar["h"] for bar in prior)
        avg_volume = mean(bar["v"] for bar in prior)
        current = bars[i]
        if current["c"] <= range_high or avg_volume <= 0 or current["v"] < 1.5 * avg_volume:
            i += 1
            continue
        entry = current["c"] * (1.0 + slippage_bps / 10000.0)
        local_atr = atr(bars[:i + 1], 14)
        if not local_atr or local_atr <= 0:
            i += 1
            continue
        stop = entry - 1.5 * local_atr
        if stop <= 0 or stop >= entry:
            i += 1
            continue
        target = entry + 2.0 * (entry - stop)
        risk = entry - stop
        exit_price = None
        exit_reason = "TIME"
        exit_index = min(end - 1, i + 60)
        for j in range(i + 1, exit_index + 1):
            bar = bars[j]
            # Conservative intrabar ordering: if both levels trade, assume stop first.
            if bar["l"] <= stop:
                exit_price, exit_reason = stop, "STOP"
                exit_index = j
                break
            if bar["h"] >= target:
                exit_price, exit_reason = target, "TARGET"
                exit_index = j
                break
        if exit_price is None:
            exit_price = bars[exit_index]["c"]
        exit_price *= (1.0 - slippage_bps / 10000.0)
        gross_r = (exit_price - entry) / risk
        round_trip_cost_r = (2.0 * fee_bps + 2.0 * slippage_bps) / 10000.0 * entry / risk
        trades.append({"entry_index": float(i), "exit_index": float(exit_index),
                       "r_gross": gross_r, "r_net": gross_r - round_trip_cost_r,
                       "reason": exit_reason})
        i = exit_index + 1
    return trades


def block_bootstrap_ci(values: list[float], runs: int = 1000,
                       block_size: int = 5, seed: int = 19) -> dict[str, Any]:
    if len(values) < 2:
        return {"lower": None, "upper": None, "runs": 0, "method": "block bootstrap"}
    rng = random.Random(seed)
    estimates = []
    n = len(values)
    for _ in range(runs):
        sample = []
        while len(sample) < n:
            start = rng.randrange(n)
            sample.extend(values[(start + offset) % n] for offset in range(block_size))
        estimates.append(mean(sample[:n]))
    estimates.sort()
    return {"lower": estimates[int(0.025 * (runs - 1))],
            "upper": estimates[int(0.975 * (runs - 1))],
            "runs": runs, "block_size": block_size, "seed": seed,
            "method": "circular block bootstrap"}


def risk_of_ruin(values: list[float], risk_fraction: float = 0.005,
                 runs: int = 1000, trades: int = 50, seed: int = 19) -> dict[str, Any]:
    if not values:
        return {"probability_half": None, "runs": 0, "reason": "no completed trades"}
    rng = random.Random(seed)
    ruined = 0
    endings = []
    for _ in range(runs):
        equity = 1.0
        hit_half = False
        for _ in range(trades):
            equity *= max(0.0, 1.0 + values[rng.randrange(len(values))] * risk_fraction)
            if equity <= 0.5:
                hit_half = True
            if equity <= 0:
                break
        ruined += int(hit_half)
        endings.append(equity)
    endings.sort()
    return {"probability_half": ruined / runs, "runs": runs, "trades": trades,
            "risk_fraction": risk_fraction, "seed": seed,
            "median_ending_equity": endings[len(endings) // 2]}


def backtest_breakout(bars: list[dict[str, float]], fee_bps: float = 25.0,
                      slippage_bps: float = 50.0) -> dict[str, Any]:
    """Chronological 70/30 holdout plus fixed-parameter rolling OOS folds."""
    if len(bars) < 150:
        return {"status": "INSUFFICIENT_DATA", "bars": len(bars),
                "required_bars": 150, "metrics": None}
    timestamps = [bar["t"] for bar in bars]
    gaps = [timestamps[i] - timestamps[i - 1] for i in range(1, len(timestamps))
            if timestamps[i] - timestamps[i - 1] > 90]
    missing_estimate = sum(max(1, round(gap / 60) - 1) for gap in gaps)
    expected_bars = len(bars) + missing_estimate
    gap_rate = missing_estimate / max(1, expected_bars)
    max_gap_seconds = max(gaps) if gaps else 0
    data_quality = {
        "gap_count": len(gaps), "estimated_missing_minutes": missing_estimate,
        "gap_rate": round(gap_rate, 5),
        "coverage_pct": round(100.0 * len(bars) / max(1, expected_bars), 3),
        "max_gap_seconds": max_gap_seconds,
        "valid_for_validation": gap_rate <= 0.01 and max_gap_seconds <= 180,
    }
    split = int(len(bars) * 0.70)
    train = _breakout_trades(bars, fee_bps, slippage_bps, 50, split)
    test = _breakout_trades(bars, fee_bps, slippage_bps, split, len(bars))
    train_metrics = _trade_metrics(train)
    test_metrics = _trade_metrics(test)
    oos_r = [trade["r_net"] for trade in test]
    ci = block_bootstrap_ci(oos_r)
    ruin = risk_of_ruin(oos_r)
    walk_forward = []
    boundaries = [(0.50, 0.6667), (0.6667, 0.8333), (0.8333, 1.0)]
    for fold, (train_fraction, test_fraction) in enumerate(boundaries, 1):
        train_end = int(len(bars) * train_fraction)
        test_end = min(len(bars), int(len(bars) * test_fraction))
        if train_end >= 50 and test_end - train_end >= 50:
            fold_trades = _breakout_trades(bars, fee_bps, slippage_bps, train_end, test_end)
            walk_forward.append({
                "fold": fold, "training_bars": train_end,
                "test_start_index": train_end, "test_end_index": test_end,
                **_trade_metrics(fold_trades),
            })
    validation_reasons = []
    if test_metrics["trades"] < 30:
        validation_reasons.append("fewer than 30 out-of-sample trades")
    if test_metrics["expectancy_r"] is None or test_metrics["expectancy_r"] <= 0:
        validation_reasons.append("out-of-sample net expectancy is not positive")
    if test_metrics["profit_factor"] is None or test_metrics["profit_factor"] <= 1.1:
        validation_reasons.append("out-of-sample profit factor does not exceed 1.1")
    if ci["lower"] is None or ci["lower"] <= 0:
        validation_reasons.append("95% out-of-sample bootstrap lower bound is not positive")
    if ruin["probability_half"] is None or ruin["probability_half"] > 0.05:
        validation_reasons.append("simulated 50% drawdown probability exceeds 5%")
    if not data_quality["valid_for_validation"]:
        validation_reasons.append("historical candle gaps exceed the validation tolerance")
    validated = not validation_reasons
    return {
        "status": "COMPLETE", "bars": len(bars), "split_index": split,
        "dataset_fingerprint": dataset_fingerprint(bars), "data_quality": data_quality,
        "assumptions": {"entry": "15-bar close breakout with >=1.5x prior volume",
                        "stop": "1.5 ATR", "target": "2R", "time_stop_bars": 60,
                        "intrabar_conflict": "stop first", "fee_bps_per_side": fee_bps,
                        "slippage_bps_per_side": slippage_bps, "seed": 19},
        "in_sample": train_metrics, "out_of_sample": test_metrics,
        "expectancy_ci_95": ci, "risk_of_ruin": ruin, "walk_forward": walk_forward,
        "strategy_validation": "VALIDATED" if validated else "NOT_VALIDATED",
        "validation_reasons": validation_reasons,
        "validation_rule": ">=30 OOS trades; positive net expectancy; PF > 1.1; positive 95% OOS block-bootstrap lower bound; <=5% simulated 50% drawdown probability; candle gaps <=1%",
        "optimisation": "NOT_PERFORMED; holdout remains untouched",
    }