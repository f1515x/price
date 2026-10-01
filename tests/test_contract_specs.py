import json
from pathlib import Path
import tempfile
import unittest

from contract_specs import collect, load_snapshot, normalize, scenario_config
from trade_simulation import Config, simulate
from test_trade_simulation import data, candidate


def raw(symbol="BTC", **changes):
    return dict(name=symbol + "_USDT", type="direct", quanto_multiplier="0.0001",
                order_size_min="1", order_size_max="100000", order_price_round="0.1",
                enable_decimal=False, in_delisting=False, status="trading",
                maker_fee_rate="-0.0001", taker_fee_rate="0.00075", funding_interval=28800,
                **changes)


class ContractSpecsTests(unittest.TestCase):
    def collect(self, path):
        return collect(["BTC", "ETH"], path,
                       fetch=lambda s: json.dumps(raw(s)).encode(), clock=lambda: 1000)

    def test_snapshot_roundtrip_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "specs"
            report = self.collect(path)
            self.assertEqual(load_snapshot(path), report)
            self.assertEqual(report["temporal_scope"], "CURRENT_SNAPSHOT_ONLY")
            self.assertEqual(report["contracts"][0]["maker_fee_rate"], "-0.0001")
            with self.assertRaises(FileExistsError):
                self.collect(path)

    def test_raw_and_normalized_tampering(self):
        for field in ("raw", "multiplier", "raw_file", "source_url", "observed_at"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "specs"
                report = self.collect(path)
                if field == "raw":
                    (path / "BTC-raw.json").write_text("{}")
                else:
                    report["contracts"][0][field] = {"multiplier": "1", "raw_file": "../other",
                                                     "source_url": "https://example.com", "observed_at": 0}[field]
                    (path / "specs.json").write_text(json.dumps(report))
                with self.assertRaises(ValueError):
                    load_snapshot(path)

    def test_identity_type_flags_and_size_validation(self):
        for changes in ({"name": "ETH_USDT"}, {"type": "inverse"}, {"enable_decimal": 0},
                        {"in_delisting": "false"}, {"order_size_min": "1.5"},
                        {"order_size_max": "0.5"}, {"order_size_min": "0"},
                        {"order_size_min": "-1"}, {"funding_interval": True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                normalize(dict(raw(), **changes), "BTC")

    def test_invalid_numeric_values(self):
        for key in ("quanto_multiplier", "order_size_min", "order_size_max", "order_price_round",
                    "maker_fee_rate", "taker_fee_rate"):
            for value in ("NaN", "Infinity", None, True, "invalid"):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    normalize(dict(raw(), **{key: value}), "BTC")
        for value in ("0", "-1"):
            with self.assertRaises(ValueError):
                normalize(dict(raw(), quanto_multiplier=value), "BTC")

    def test_decimal_and_delisted_are_not_mapped(self):
        for changes, status in (({"enable_decimal": True, "order_size_min": "0.1"}, "UNSUPPORTED_DECIMAL_STEP"),
                                ({"enable_decimal": True, "order_size_min": 0}, "UNSUPPORTED_DECIMAL_STEP"),
                                ({"in_delisting": True}, "NOT_TRADING"), ({"status": "halted"}, "NOT_TRADING")):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as tmp:
                record = dict(raw(), **changes)
                collect(["BTC"], tmp + "/s", fetch=lambda s: json.dumps(record).encode(), clock=lambda: 1000)
                self.assertEqual(normalize(record, "BTC")["status"], status)
                with self.assertRaises(ValueError):
                    scenario_config(tmp + "/s", "BTC", Config(10000, .01, 1, .2), assume_current_specs=True)

    def test_explicit_scenario_preserves_costs_and_risk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "specs"
            self.collect(path)
            base = Config(10000, .01, 1, .2)
            with self.assertRaises(ValueError):
                scenario_config(path, "BTC", base)
            with self.assertRaises(ValueError):
                scenario_config(path, "SOL", base, assume_current_specs=True)
            cfg = scenario_config(path, "BTC", base, assume_current_specs=True)
            self.assertEqual((cfg.multiplier, cfg.quantity_step, cfg.min_quantity), (.0001, 1, 1))
            self.assertEqual((cfg.fee_rate, cfg.funding_daily, cfg.risk_fraction),
                             (base.fee_rate, base.funding_daily, base.risk_fraction))

    def test_mapped_contract_count_hand_calculation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "specs"
            self.collect(path)
            base = Config(10000, .01, 1, .2, entry_atr=0, stop_atr=1,
                          fee_rate=0, slippage=0, funding_daily=0)
            cfg = scenario_config(path, "BTC", base, assume_current_specs=True)
            result = simulate(data([(100, 100, 100, 100), (100, 130, 80, 100)]), [candidate()], cfg)
            trade = result["trades"][0]
            self.assertEqual(trade["quantity"], 100000)  # 10 BTC / 0.0001 BTC per contract
            self.assertAlmostEqual(trade["net_pnl"], -100)
            self.assertAlmostEqual(result["summary"]["final_equity"], 9900)

    def test_invalid_collection_has_no_partial_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "specs"
            for symbols in ([], ["BTC", "btc"], ["../BTC"]):
                with self.assertRaises(ValueError):
                    collect(symbols, path)
            with self.assertRaises(ValueError):
                collect(["BTC", "ETH"], path, fetch=lambda s: json.dumps(raw()).encode())
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
