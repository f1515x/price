import json
import math
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from io import StringIO
from pathlib import Path

from history import DAY, prepare, save_snapshot
from history_store import import_snapshots, query_daily
from indicator_store import build_indicators, query_indicators
from structure_history import Config, replay
from structure_store import build_structures, list_runs, query_structures, main


class StructureStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / "history.sqlite"
        self.rows = {}
        directories = []
        for symbol in ("BTC", "ETH"):
            raw = [dict(t=i*DAY, o=c, h=c+1, l=c-1, c=c, v=10)
                   for i in range(65) if i != 55
                   for c in [100 + 15*math.sin(i/3) + i/5]]
            rows, quality = prepare(raw, symbol, 0, 65*DAY, 65*DAY)
            directory = self.root / symbol
            save_snapshot(directory, raw, rows, quality)
            directories.append(directory)
            self.rows[symbol] = rows
        self.snapshots = import_snapshots(self.db, directories)
        self.ids = [s["snapshot_id"] for s in self.snapshots]

    def test_roundtrip_confirmation_gap_and_existing_indicators(self):
        indicator = build_indicators(self.db, [self.ids[0]])[0]
        before = query_indicators(self.db, indicator["run_id"], "BTC")
        for run in build_structures(self.db, self.ids, Config(2)):
            rows = query_structures(self.db, run["run_id"], run["symbol"])
            self.assertEqual(rows, replay(self.rows[run["symbol"]], Config(2)))
            self.assertIsNone(rows[0]["structure"])
            self.assertTrue(any(r["status"] == "OK" for r in rows))
            for row in rows:
                if row["structure"]:
                    self.assertLessEqual(row["structure_confirmed_at"], row["signal_time"])
                if row["gap_before"]:
                    self.assertIsNone(row["structure"])
            selected = query_structures(self.db, run["run_id"], run["symbol"], 53*DAY, 58*DAY)
            self.assertEqual(selected, [r for r in rows if 53*DAY <= r["timestamp"] < 58*DAY])
        self.assertEqual(before, query_indicators(self.db, indicator["run_id"], "BTC"))
        for snapshot in self.snapshots:
            self.assertEqual(query_daily(self.db, snapshot["snapshot_id"], snapshot["symbol"]),
                             self.rows[snapshot["symbol"]])

    def test_idempotency_and_parameter_versions(self):
        first = build_structures(self.db, self.ids, Config(2))
        again = build_structures(self.db, self.ids, Config(2))
        self.assertTrue(all(not r["inserted"] for r in again))
        self.assertEqual([r["run_id"] for r in first], [r["run_id"] for r in again])
        alternate = build_structures(self.db, self.ids, Config(3))
        self.assertTrue(all(r["inserted"] for r in alternate))
        self.assertEqual(len(list_runs(self.db)), 4)
        self.assertEqual(set(first[0]["implementation_sha256"]),
                         {"structure_history.py", "smc.py", "indicators.py"})

    def test_evidence_tampering_rejects_batch(self):
        before = self.db.read_bytes()
        (self.root / "ETH" / "daily.csv").write_text("tampered", encoding="utf-8")
        with self.assertRaises(ValueError):
            build_structures(self.db, self.ids, Config(2))
        self.assertEqual(self.db.read_bytes(), before)

    def test_database_tampering_rejected(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("UPDATE daily SET volume=11 WHERE snapshot_id=?", (self.ids[1],))
            db.commit()
        with self.assertRaises(ValueError):
            build_structures(self.db, self.ids, Config(2))
        self.assertEqual(list_runs(self.db), [])

    def test_batch_sql_failure_rolls_back(self):
        build_structures(self.db, [self.ids[0]], Config(2))
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("CREATE TRIGGER reject_eth BEFORE INSERT ON structure_runs "
                       "WHEN NEW.symbol='ETH' BEGIN SELECT RAISE(ABORT, 'failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            build_structures(self.db, self.ids, Config(3))
        self.assertEqual(len(list_runs(self.db)), 1)

    def test_invalid_queries_and_missing_database(self):
        self.assertEqual(list_runs(self.db), [])
        for ids in ([], ["missing"]):
            with self.assertRaises(ValueError):
                build_structures(self.db, ids)
        run = build_structures(self.db, [self.ids[0]], Config(2))[0]
        for rid, symbol, start, end in ((run["run_id"], "ETH", None, None),
                                       ("missing", "BTC", None, None),
                                       (run["run_id"], "BTC", DAY, 0)):
            with self.assertRaises(ValueError):
                query_structures(self.db, rid, symbol, start, end)
        missing = self.root / "absent.sqlite"
        with self.assertRaises(sqlite3.OperationalError):
            list_runs(missing)
        self.assertFalse(missing.exists())

    def test_cli(self):
        def cli(*args):
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["--database", str(self.db), *args]), 0)
            return json.loads(output.getvalue())
        run = cli("build", self.ids[0], "--swing-length", "2")[0]
        self.assertEqual(cli("list")[0]["run_id"], run["run_id"])
        rows = cli("query", "BTC", "--run-id", run["run_id"],
                   "--start", "1970-02-01", "--end", "1970-02-03")
        self.assertEqual([r["timestamp"] for r in rows], [31*DAY, 32*DAY])


if __name__ == "__main__":
    unittest.main()
