import contextlib
import io
from pathlib import Path
import subprocess
import tempfile
import unittest

import sanitize_history as history


class HistorySanitizationTests(unittest.TestCase):
    def command(self, repo, *args):
        return history.git(repo, *args)

    def fixture(self, root):
        repo = root / "source"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main", str(repo)],
                       capture_output=True, check=True)
        self.command(repo, "config", "user.name", "Fixture")
        self.command(repo, "config", "user.email", "fixture@example.test")
        self.command(repo, "config", "gc.auto", "0")
        self.command(repo, "config", "maintenance.auto", "false")
        token = b"fixture-session-token-0123456789"
        (repo / "month.py").write_bytes(b"cookies = {'sessionid': '" + token + b"'}\n")
        (repo / "unchanged.txt").write_text("preserve me\n")
        self.command(repo, "add", ".")
        self.command(repo, "commit", "-m", "historical cookie")
        self.command(repo, "tag", "-a", "old", "-m", "tag " + token.decode())
        self.command(repo, "checkout", "-b", "side")
        (repo / "renamed.bin").write_bytes(b"\x00" + token + b"\xff")
        self.command(repo, "add", ".")
        self.command(repo, "commit", "-m", "message " + token.decode())
        self.command(repo, "checkout", "main")
        self.command(repo, "checkout", "-b", "feature")
        (repo / "month.py").write_text("cookies = {}\n")
        self.command(repo, "add", ".")
        self.command(repo, "commit", "-m", "remove current cookie")
        self.command(repo, "update-ref", "refs/remotes/origin/side",
                     self.command(repo, "rev-parse", "side").decode().strip())
        return repo, token

    def test_mirror_cleans_branches_tags_binary_and_messages_preserving_source(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            root = Path(temp)
            repo, token = self.fixture(root)
            original = history.refs(repo)
            output = io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                report = history.sanitize(repo, root / "clean.git")
            self.assertEqual(history.refs(repo), original)
            self.assertTrue(history.scan(repo, [token])["matching_objects"])
            self.assertFalse(report["after"]["matching_objects"])
            self.assertEqual(report["source_commit_count"], 3)
            self.assertEqual(report["sanitized_commit_count"], 3)
            self.assertTrue(report["feature_tree_unchanged"])
            self.assertFalse(report["session_revoked"])
            self.assertFalse(report["remote_history_cleaned"])
            clean = root / "clean.git"
            self.assertEqual(self.command(clean, "remote"), b"")
            self.assertFalse((clean / "objects" / "info" / "alternates").exists())
            self.assertEqual(self.command(clean, "show", "side:renamed.bin"),
                             b"\x00" + history.REPLACEMENT + b"\xff")
            self.assertNotIn(token.decode(), output.getvalue())
            self.assertNotIn(token.decode(), (clean / "sanitization-audit.json").read_text())
            self.assertEqual(self.command(clean, "show", "feature:unchanged.txt"), b"preserve me\n")

    def test_refuses_existing_or_nested_destination(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            root = Path(temp)
            repo, _ = self.fixture(root)
            existing = root / "exists"
            existing.mkdir()
            (existing / "marker").write_text("keep")
            for destination in (repo, repo / "nested", existing):
                with self.assertRaises(ValueError):
                    history.sanitize(repo, destination)
            self.assertEqual((existing / "marker").read_text(), "keep")
            self.assertFalse((repo / "nested").exists())

    def test_no_cookie_and_short_cookie_fail_without_creating_output(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            root = Path(temp)
            for number, body in enumerate(("cookies = {}\n", "cookies = {'sessionid': 'x'}\n")):
                source = root / str(number)
                source.mkdir()
                subprocess.run(["git", "init", "-b", "feature", str(source)],
                               capture_output=True, check=True)
                self.command(source, "config", "user.name", "Fixture")
                self.command(source, "config", "user.email", "fixture@example.test")
                self.command(source, "config", "gc.auto", "0")
                self.command(source, "config", "maintenance.auto", "false")
                (source / "month.py").write_text(body)
                self.command(source, "add", ".")
                self.command(source, "commit", "-m", "fixture")
                destination = root / ("clean-" + str(number))
                with self.assertRaises(ValueError):
                    history.sanitize(source, destination)
                self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
