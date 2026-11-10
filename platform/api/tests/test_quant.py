import unittest
from verum.quant import (
    atr, backtest_breakout, block_bootstrap_ci, build_trade_plan,
    dataset_fingerprint, ema, evaluate_signal, indicator_features,
    normalize_bars, risk_of_ruin, rsi,
)

def make_bars(count=240, drift=0.0007, base=1.0):
    bars = []
    price = base
    for index in range(count):
        previous = price
        price *= 1 + drift + (0.001 if index % 9 == 0 else -0.0001)
        bars.append({"t": 1700000000 + index * 60, "o": previous,
                     "h": max(previous, price) * 1.002,
                     "l": min(previous, price) * 0.998, "c": price,
                     "v": 1000.0 if index % 13 == 0 else 500.0})
    return bars

class QuantTests(unittest.TestCase):
    def test_normalize_jupiter_candles(self):
        payload = {"candles": [{"time": 120, "open": 1, "high": 2,
                                "low": 0.9, "close": 1.5, "volume": 10}]}
        self.assertEqual(normalize_bars(payload)[0]["t"], 120)

    def test_millisecond_timestamps_normalize_to_seconds(self):
        payload = {"candles": [{"time": 1700000000000, "open": 1, "high": 2,
                                "low": 0.9, "close": 1.5, "volume": 10}]}
        self.assertEqual(normalize_bars(payload)[0]["t"], 1700000000)

    def test_normalize_deduplicates_and_sorts(self):
        bars = [{"t": 120, "o": 1, "h": 2, "l": 1, "c": 1.5, "v": 2},
                {"t": 60, "o": 1, "h": 2, "l": 1, "c": 1.2, "v": 1},
                {"t": 120, "o": 1, "h": 2, "l": 1, "c": 1.6, "v": 3}]
        result = normalize_bars(bars)
        self.assertEqual([row["t"] for row in result], [60, 120])
        self.assertEqual(result[-1]["c"], 1.6)

    def test_indicators_require_sufficient_history(self):
        self.assertIsNone(ema([1.0, 2.0], 3))
        self.assertIsNone(rsi([1.0, 2.0], 14))
        self.assertIsNone(atr(make_bars(10), 14))

    def test_features_are_deterministic(self):
        bars = make_bars()
        self.assertEqual(indicator_features(bars), indicator_features(bars))
        self.assertEqual(indicator_features(bars)["status"], "OK")

    def test_trade_plan_uses_atr(self):
        plan = build_trade_plan({"price": 10.0, "atr14": 0.2}, 100000)
        self.assertAlmostEqual(plan["stop_loss"], 9.7)
        self.assertAlmostEqual(plan["take_profit_1"], 10.6)
        self.assertAlmostEqual(plan["take_profit_2"], 10.9)

    def test_security_veto_overrides_momentum(self):
        result = evaluate_signal(
            {"status": "OK", "trend": "BULLISH", "rsi14": 60,
             "return_5m_pct": 4, "volume_ratio": 2},
            "AVOID", "GRADUATED", 100000, 2.0, True, True, 0.2)
        self.assertEqual(result["status"], "BLOCKED")

    def test_unvalidated_strategy_never_emits_buy(self):
        result = evaluate_signal(
            {"status": "OK", "trend": "BULLISH", "rsi14": 60,
             "return_5m_pct": 4, "volume_ratio": 2},
            "PASS", "GRADUATED", 100000, 2.0, False, True, 0.2)
        self.assertEqual(result["status"], "WAIT")
        self.assertEqual(result["strategy_validation"], "UNVALIDATED")

    def test_fresh_executable_quote_is_mandatory(self):
        features = {"status": "OK", "trend": "BULLISH", "rsi14": 60,
                    "return_5m_pct": 4, "volume_ratio": 2}
        no_quote = evaluate_signal(features, "PASS", "GRADUATED", 100000, 2.0, True, False, None)
        high_impact = evaluate_signal(features, "PASS", "GRADUATED", 100000, 2.0, True, True, 3.0)
        valid_quote = evaluate_signal(features, "PASS", "GRADUATED", 100000, 2.0, True, True, 0.2)
        self.assertEqual(no_quote["status"], "WAIT")
        self.assertEqual(high_impact["status"], "WAIT")
        self.assertEqual(valid_quote["status"], "BUY")

    def test_bonding_curve_is_not_execution_eligible(self):
        result = evaluate_signal(
            {"status": "OK", "trend": "BULLISH", "rsi14": 60,
             "return_5m_pct": 4, "volume_ratio": 2},
            "PASS", "BONDING_CURVE", 100000, 2.0, True, True, 0.2)
        self.assertEqual(result["status"], "WAIT")

    def test_backtest_is_chronological_and_reproducible(self):
        bars = make_bars(360)
        first = backtest_breakout(bars)
        second = backtest_breakout(bars)
        self.assertEqual(first["dataset_fingerprint"], second["dataset_fingerprint"])
        self.assertEqual(first["out_of_sample"], second["out_of_sample"])
        self.assertEqual(first["split_index"], int(len(bars) * 0.70))
        self.assertEqual(first["optimisation"], "NOT_PERFORMED; holdout remains untouched")
        self.assertTrue(first["data_quality"]["valid_for_validation"])

    def test_large_candle_gaps_prevent_strategy_validation(self):
        bars = make_bars(360)
        for index in range(100, len(bars)):
            bars[index]["t"] += 600
        result = backtest_breakout(bars)
        self.assertFalse(result["data_quality"]["valid_for_validation"])
        self.assertIn("historical candle gaps exceed the validation tolerance",
                      result["validation_reasons"])

    def test_bootstrap_and_risk_of_ruin_reproducible(self):
        values = [1.0, -0.5, 0.25, -0.2, 0.4]
        self.assertEqual(block_bootstrap_ci(values), block_bootstrap_ci(values))
        self.assertEqual(risk_of_ruin(values), risk_of_ruin(values))

    def test_dataset_fingerprint_changes_when_data_changes(self):
        bars = make_bars()
        before = dataset_fingerprint(bars)
        bars[-1]["c"] += 0.01
        self.assertNotEqual(before, dataset_fingerprint(bars))

if __name__ == "__main__":
    unittest.main()
