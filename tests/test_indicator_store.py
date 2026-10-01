import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from io import StringIO
from pathlib import Path

from history import DAY, prepare, save_snapshot
from history_store import import_snapshots, query_daily
from indicator_store import build_indicators, list_runs, query_indicators, main
from indicators import Config, calculate


class IndicatorStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / "history.sqlite"
        self.rows = {}
        directories = []
        for symbol in ("BTC", "ETH"):
            raw = [dict(t=i * DAY, o=100+i, h=102+i, l=99+i, c=101+i, v=10)
                   for i in range(410) if i != 400]
            rows, quality = prepare(raw, symbol, 0, 410*DAY, 410*DAY)
            directory = self.root / symbol
            save_snapshot(directory, raw, rows, quality)
            directories.append(directory)
            self.rows[symbol] = rows
        self.snapshots = import_snapshots(self.db, directories)
        self.ids = [s["snapshot_id"] for s in self.snapshots]

    def test_roundtrip_multi_asset_warmup_gap_and_boundaries(self):
        for run in build_indicators(self.db, self.ids):
            actual = query_indicators(self.db, run["run_id"], run["symbol"])
            self.assertEqual(actual, calculate(self.rows[run["symbol"]]))
            self.assertIsNone(actual[0]["return_percentile"])
            self.assertEqual(actual[-1]["reasons"]["ret_30d"], "INSUFFICIENT_CONTIGUOUS_DATA")
            self.assertEqual(query_indicators(self.db, run["run_id"], run["symbol"], 395*DAY, 402*DAY),
                             [r for r in actual if 395*DAY <= r["timestamp"] < 402*DAY])
        self.assertEqual(len(list_runs(self.db)), 2)
        for snapshot in self.snapshots:
            self.assertEqual(query_daily(self.db, snapshot["snapshot_id"], snapshot["symbol"]),
                             self.rows[snapshot["symbol"]])

    def test_repeated_build_and_parameter_versions(self):
        first = build_indicators(self.db, self.ids)
        repeated = build_indicators(self.db, self.ids)
        self.assertTrue(all(not r["inserted"] for r in repeated))
        self.assertEqual([r["run_id"] for r in first], [r["run_id"] for r in repeated])
        alternate = build_indicators(self.db, self.ids, Config(window=180))
        self.assertTrue(all(r["inserted"] for r in alternate))
        self.assertEqual(len(list_runs(self.db)), 4)
        for run in alternate:
            self.assertEqual(query_indicators(self.db, run["run_id"], run["symbol"]),
                             calculate(self.rows[run["symbol"]], Config(window=180)))

    def test_tampered_original_rejects_whole_batch(self):
        before = self.db.read_bytes()
        (self.root / "ETH" / "daily.csv").write_text("tampered", encoding="utf-8")
        with self.assertRaises(ValueError):
            build_indicators(self.db, self.ids)
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(list_runs(self.db), [])

    def test_tampered_database_rejected(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("UPDATE daily SET volume=11 WHERE snapshot_id=?", (self.ids[1],))
            db.commit()
        with self.assertRaises(ValueError):
            build_indicators(self.db, self.ids)
        self.assertEqual(list_runs(self.db), [])

    def test_sql_failure_rolls_back_all_new_runs(self):
        build_indicators(self.db, [self.ids[0]])
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("CREATE TRIGGER reject_eth BEFORE INSERT ON indicator_runs "
                       "WHEN NEW.symbol='ETH' BEGIN SELECT RAISE(ABORT, 'failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            build_indicators(self.db, self.ids, Config(window=180))
        self.assertEqual(len(list_runs(self.db)), 1)

    def test_invalid_selection_and_missing_database(self):
        for ids in ([], ["missing"]):
            with self.assertRaises(ValueError):
                build_indicators(self.db, ids)
        run = build_indicators(self.db, [self.ids[0]])[0]
        for rid, symbol, start, end in ((run["run_id"], "ETH", None, None),
                                       ("missing", "BTC", None, None),
                                       (run["run_id"], "BTC", DAY, 0)):
            with self.assertRaises(ValueError):
                query_indicators(self.db, rid, symbol, start, end)
        missing = self.root / "absent.sqlite"
        with self.assertRaises(sqlite3.OperationalError):
            list_runs(missing)
        self.assertFalse(missing.exists())

    def test_cli_build_list_query(self):
        def cli(*args):
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["--database", str(self.db), *args]), 0)
            return json.loads(output.getvalue())
        run = cli("build", self.ids[0], "--window", "180")[0]
        self.assertEqual(cli("list")[0]["run_id"], run["run_id"])
        rows = cli("query", "BTC", "--run-id", run["run_id"],
                   "--start", "1970-02-01", "--end", "1970-02-03")
        self.assertEqual([r["timestamp"] for r in rows], [31*DAY, 32*DAY])


if __name__ == "__main__":
    unittest.main()
