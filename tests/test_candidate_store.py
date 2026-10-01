import json
import math
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from io import StringIO
from pathlib import Path

from candidate_store import Config, build_candidates, decisions, list_runs, query_candidates, main
from event_study import study
from history import DAY, prepare, save_snapshot
from history_store import import_snapshots, query_daily
from indicators import Config as IndicatorConfig
from structure_history import Config as StructureConfig
from structure_store import build_structures, query_structures


class CandidateStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / "history.sqlite"
        self.rows = {}
        directories = []
        for symbol in ("BTC", "ETH"):
            raw = [dict(t=i*DAY, o=c, h=c+1, l=c-1, c=c, v=10)
                   for i in range(105) if i != 85
                   for c in [100 + 15*math.sin(i/3) + i/5]]
            rows, quality = prepare(raw, symbol, 0, 105*DAY, 105*DAY)
            directory = self.root / symbol
            save_snapshot(directory, raw, rows, quality)
            directories.append(directory)
            self.rows[symbol] = rows
        self.snapshots = import_snapshots(self.db, directories)
        self.ids = [s["snapshot_id"] for s in self.snapshots]
        self.ic, self.sc = IndicatorConfig(window=5), StructureConfig(2)

    def build(self, ids=None, config=Config()):
        return build_candidates(self.db, self.ids if ids is None else ids, config, self.ic, self.sc)

    def test_roundtrip_all_decisions_and_m4_compatibility(self):
        structure = build_structures(self.db, [self.ids[0]], self.sc)[0]
        before = query_structures(self.db, structure["run_id"], "BTC")
        for run in self.build():
            rows = query_candidates(self.db, run["run_id"], run["symbol"])
            self.assertEqual(rows, decisions(self.rows[run["symbol"]], indicator_config=self.ic,
                                             structure_config=self.sc))
            research = study(self.rows[run["symbol"]], indicator_config=self.ic, structure_config=self.sc)
            eligible = [r for r in rows if r["eligible"]]
            self.assertEqual(len(eligible), research["eligible"])
            for row, candidate in zip(eligible, research["candidates"]):
                self.assertEqual({k: v["direction"] for k, v in row["decisions"].items()}, candidate["signals"])
            self.assertTrue(eligible)
            self.assertTrue(any(d["direction"] for r in rows for d in r["decisions"].values()))
            for row in rows:
                self.assertFalse(row["execution_authorized"])
                self.assertIsNone(row["opportunity_score"])
                self.assertEqual(row["signal_time"], row["timestamp"] + DAY)
                for decision in row["decisions"].values():
                    self.assertTrue(decision["reasons"])
                if not row["eligible"]:
                    self.assertTrue(all(d["status"] == "UNAVAILABLE" and not d["direction"]
                                        for d in row["decisions"].values()))
                if row["structure"]["structure"]:
                    self.assertLessEqual(row["structure"]["structure_confirmed_at"], row["signal_time"])
            self.assertEqual(query_daily(self.db, run["snapshot_id"], run["symbol"]), self.rows[run["symbol"]])
        self.assertEqual(before, query_structures(self.db, structure["run_id"], "BTC"))

    def test_causal_prefix_and_gap(self):
        rows = self.rows["BTC"]
        full = decisions(rows, indicator_config=self.ic, structure_config=self.sc)
        self.assertEqual(full[:70], decisions(rows[:70], indicator_config=self.ic, structure_config=self.sc))
        gap = next(r for r in full if r["indicator"]["gap_before"])
        self.assertFalse(gap["eligible"])
        self.assertIn("MISSING_RET_30D", gap["reasons"])

    def test_idempotency_and_versions(self):
        first = self.build()
        again = self.build()
        self.assertEqual([r["run_id"] for r in first], [r["run_id"] for r in again])
        self.assertTrue(all(not r["inserted"] for r in again))
        alternate = self.build(config=Config(tail=20))
        self.assertTrue(all(r["inserted"] for r in alternate))
        self.assertEqual(len(list_runs(self.db)), 4)
        different = build_candidates(self.db, [self.ids[0]], indicator_config=IndicatorConfig(window=6),
                                     structure_config=self.sc)[0]
        self.assertNotEqual(different["run_id"], first[0]["run_id"])
        for config in (dict(tail=50), dict(move=0), dict(stretch=float("nan"))):
            with self.assertRaises(ValueError):
                Config(**config)

    def test_evidence_tampering_rejects_entire_batch(self):
        before = self.db.read_bytes()
        (self.root / "ETH" / "daily.csv").write_text("tampered", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.build()
        self.assertEqual(self.db.read_bytes(), before)

    def test_database_tampering_rejected(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("UPDATE daily SET volume=11 WHERE snapshot_id=?", (self.ids[1],))
            db.commit()
        with self.assertRaises(ValueError):
            self.build()
        self.assertEqual(list_runs(self.db), [])

    def test_sql_failure_rolls_back(self):
        self.build([self.ids[0]])
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("CREATE TRIGGER reject_eth BEFORE INSERT ON candidate_runs "
                       "WHEN NEW.symbol='ETH' BEGIN SELECT RAISE(ABORT, 'failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.build(config=Config(tail=20))
        self.assertEqual(len(list_runs(self.db)), 1)

    def test_query_boundaries_invalid_inputs_missing_database(self):
        self.assertEqual(list_runs(self.db), [])
        for ids in ([], ["missing"]):
            with self.assertRaises(ValueError):
                self.build(ids)
        run = self.build([self.ids[0]])[0]
        rows = query_candidates(self.db, run["run_id"], "BTC", 83*DAY, 88*DAY)
        self.assertEqual([r["timestamp"] for r in rows], [83*DAY, 84*DAY, 86*DAY, 87*DAY])
        for rid, symbol, start, end in ((run["run_id"], "ETH", None, None),
                                       ("missing", "BTC", None, None),
                                       (run["run_id"], "BTC", DAY, 0)):
            with self.assertRaises(ValueError):
                query_candidates(self.db, rid, symbol, start, end)
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
        run = cli("build", self.ids[0], "--window", "5", "--swing-length", "2")[0]
        self.assertEqual(cli("list")[0]["run_id"], run["run_id"])
        rows = cli("query", "BTC", "--run-id", run["run_id"],
                   "--start", "1970-02-01", "--end", "1970-02-03")
        self.assertEqual([r["timestamp"] for r in rows], [31*DAY, 32*DAY])


if __name__ == "__main__":
    unittest.main()
