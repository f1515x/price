import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from history import DAY, prepare, save_snapshot
from history_store import import_snapshots, list_snapshots, query_daily


class HistoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / "history.sqlite"

    def snapshot(self, name, symbol="BTC", count=400, changed=False, gap=False):
        raw = [{"t": i * DAY, "o": 100 + i, "h": 102 + i,
                "l": 99 + i, "c": 101 + i, "v": 10} for i in range(count)]
        if changed:
            raw[-1]["v"] = 11
        if gap:
            del raw[380]
        rows, report = prepare(raw, symbol, 0, count * DAY, count * DAY)
        directory = self.root / name
        save_snapshot(directory, raw, rows, report)
        return directory, rows

    def test_multi_asset_roundtrip_and_bounds(self):
        btc, expected = self.snapshot("btc")
        eth, _ = self.snapshot("eth", "ETH")
        result = import_snapshots(self.db, [btc, eth])
        self.assertEqual(len(list_snapshots(self.db)), 2)
        self.assertEqual(query_daily(self.db, result[0]["snapshot_id"], "btc"), expected)
        self.assertEqual(query_daily(self.db, result[0]["snapshot_id"], "BTC",
                                    30 * DAY, 33 * DAY), expected[30:33])

    def test_idempotent_import(self):
        path, _ = self.snapshot("btc")
        first = import_snapshots(self.db, [path])[0]
        second = import_snapshots(self.db, [path])[0]
        self.assertEqual(first["snapshot_id"], second["snapshot_id"])
        self.assertFalse(second["inserted"])
        self.assertEqual(len(query_daily(self.db, first["snapshot_id"], "BTC")), 400)

    def test_overlap_never_overwrites_version(self):
        old, rows = self.snapshot("old")
        new, revised = self.snapshot("new", changed=True)
        result = import_snapshots(self.db, [old, new])
        self.assertNotEqual(result[0]["snapshot_id"], result[1]["snapshot_id"])
        self.assertEqual(query_daily(self.db, result[0]["snapshot_id"], "BTC"), rows)
        self.assertEqual(query_daily(self.db, result[1]["snapshot_id"], "BTC"), revised)

    def test_invalid_batch_leaves_existing_database_unchanged(self):
        original, _ = self.snapshot("original")
        import_snapshots(self.db, [original])
        before = self.db.read_bytes()
        good, _ = self.snapshot("good", "ETH")
        bad, _ = self.snapshot("bad", changed=True)
        (bad / "daily.csv").write_text("tampered", encoding="utf-8")
        with self.assertRaises(ValueError):
            import_snapshots(self.db, [good, bad])
        self.assertEqual(self.db.read_bytes(), before)

    def test_sql_failure_rolls_back_entire_batch(self):
        original, _ = self.snapshot("original")
        import_snapshots(self.db, [original])
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("CREATE TRIGGER reject_eth BEFORE INSERT ON daily "
                       "WHEN NEW.symbol = 'ETH' BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        new, _ = self.snapshot("new", changed=True)
        eth, _ = self.snapshot("eth", "ETH")
        with self.assertRaises(sqlite3.IntegrityError):
            import_snapshots(self.db, [new, eth])
        self.assertEqual(len(list_snapshots(self.db)), 1)

    def test_gaps_and_quality_are_preserved(self):
        path, rows = self.snapshot("gap", gap=True)
        result = import_snapshots(self.db, [path])[0]
        self.assertEqual(query_daily(self.db, result["snapshot_id"], "BTC"), rows)
        report = json.loads(list_snapshots(self.db)[0]["report_json"])
        self.assertEqual(report["missing_timestamps"], [380 * DAY])
        self.assertEqual(rows[-1]["return_status"], "INSUFFICIENT_DATA")

    def test_wrong_symbol_version_and_range_rejected(self):
        path, _ = self.snapshot("btc")
        identity = import_snapshots(self.db, [path])[0]["snapshot_id"]
        for sid, symbol, start, end in ((identity, "ETH", None, None),
                                       ("missing", "BTC", None, None),
                                       (identity, "BTC", DAY, 0)):
            with self.assertRaises(ValueError):
                query_daily(self.db, sid, symbol, start, end)

    def test_read_does_not_create_and_foreign_schema_rejected(self):
        with self.assertRaises(sqlite3.OperationalError):
            list_snapshots(self.db)
        self.assertFalse(self.db.exists())
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("CREATE TABLE unrelated (value TEXT)")
        path, _ = self.snapshot("btc")
        with self.assertRaises(ValueError):
            import_snapshots(self.db, [path])


if __name__ == "__main__":
    unittest.main()
