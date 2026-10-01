import tempfile
import unittest
from pathlib import Path

from history import DAY, fetch_daily, load_snapshot, prepare, save_snapshot


def bars(count):
    return [{"t": i * DAY, "o": 100 + i, "h": 102 + i, "l": 99 + i,
             "c": 101 + i, "v": 10} for i in range(count)]


class HistoryTests(unittest.TestCase):
    def prepare(self, raw, count=400, as_of=None):
        return prepare(raw, "BTC", 0, count * DAY, count * DAY if as_of is None else as_of)

    def test_returns_and_roundtrip(self):
        raw = bars(400)
        rows, report = self.prepare(raw)
        self.assertEqual(report["research_status"], "READY")
        self.assertEqual(rows[29]["ret_30d"], "")
        self.assertAlmostEqual(rows[30]["ret_30d"], 131 / 101 - 1)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot"
            save_snapshot(path, raw, rows, report)
            self.assertEqual(load_snapshot(path)[0], rows)
            with self.assertRaises(FileExistsError):
                save_snapshot(path, raw, rows, report)
            (path / "daily.csv").write_text("tampered")
            with self.assertRaises(ValueError):
                load_snapshot(path)

    def test_missing_day_resets_returns(self):
        raw = bars(400)
        del raw[380]
        rows, report = self.prepare(raw)
        self.assertEqual(report["missing_timestamps"], [380 * DAY])
        self.assertEqual(rows[-1]["ret_30d"], "")
        self.assertEqual(report["research_status"], "INSUFFICIENT_DATA")

    def test_duplicates(self):
        raw = bars(400)
        rows, report = self.prepare(raw + [dict(raw[10])])
        self.assertEqual(len(rows), 400)
        self.assertEqual(report["issues"][0]["reason"], "DUPLICATE")
        rows, report = self.prepare(raw + [dict(raw[10], v=99)])
        self.assertEqual(len(rows), 399)
        self.assertIn(10 * DAY, report["missing_timestamps"])

    def test_invalid_bars(self):
        for change in ({"c": "NaN"}, {"v": -1}, {"c": 0}, {"h": 1}, {"o": None}):
            with self.subTest(change=change):
                raw = bars(400)
                raw[399].update(change)
                rows, report = self.prepare(raw)
                self.assertEqual(len(rows), 399)
                self.assertEqual(report["research_status"], "INSUFFICIENT_DATA")

    def test_unclosed_boundary(self):
        rows, report = self.prepare(bars(400), as_of=399 * DAY + 1)
        self.assertEqual(len(rows), 399)
        self.assertEqual(report["issues"][0]["reason"], "UNCLOSED")
        self.assertEqual(report["missing_timestamps"], [])
        self.assertEqual(len(self.prepare(bars(400))[0]), 400)

    def test_bad_timestamp_and_sort(self):
        rows, report = self.prepare(list(reversed(bars(400))) + [{"t": "NaN"}, {"t": 1}])
        self.assertEqual(rows[0]["timestamp"], 0)
        self.assertEqual(len(report["issues"]), 2)

    def test_pagination_and_empty_page(self):
        calls = []
        def fetch(params):
            calls.append(params)
            return []
        raw, pages = fetch_daily("btc", 0, 2001 * DAY, fetch=fetch)
        self.assertEqual(len(pages), 3)
        self.assertEqual(calls[1]["from"], calls[0]["to"] + 1)
        self.assertEqual(calls[-1]["to"], 2001 * DAY - 1)
        self.assertNotIn("limit", calls[0])
        self.assertEqual(raw, [])

    def test_empty_and_future_independence(self):
        self.assertEqual(self.prepare([])[1]["research_status"], "INSUFFICIENT_DATA")
        prefix = self.prepare(bars(100), count=100)[0]
        self.assertEqual(prefix, self.prepare(bars(400))[0][:100])


if __name__ == "__main__":
    unittest.main()
