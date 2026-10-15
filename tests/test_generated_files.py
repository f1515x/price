"""Exercise report publishing against temporary Git repositories in remote CI."""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/commit_generated_files.sh"
FILES = ("reports/sizes.txt", "reports/signals.txt", "data/price_steps.json")


class GeneratedFilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.remote = root / "remote.git"
        self.worker = root / "worker"
        self.writer = root / "writer"
        self.env = os.environ.copy()
        self.env.update({
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
        })
        self.git(root, "init", "--bare", "--initial-branch=main", str(self.remote))
        self.git(root, "clone", str(self.remote), str(self.worker))
        self.write(self.worker, "source.py", "original source\n")
        for name in FILES:
            self.write(self.worker, name, "original report\n")
        self.commit(self.worker)
        self.git(self.worker, "push", "origin", "main")
        self.git(root, "clone", str(self.remote), str(self.writer))

    def git(self, cwd, *args):
        return subprocess.run(
            ["git", *args], cwd=cwd, env=self.env, check=True,
            text=True, capture_output=True,
        ).stdout.strip()

    def write(self, repo, name, content):
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def commit(self, repo):
        self.git(repo, "add", ".")
        self.git(repo, "commit", "-m", "test update")

    def publish(self):
        return subprocess.run(
            ["bash", str(SCRIPT), "main"], cwd=self.worker, env=self.env,
            text=True, capture_output=True,
        )

    def remote_text(self, name):
        return self.git(self.remote, "show", f"main:{name}")

    def generate(self):
        for name in FILES:
            self.write(self.worker, name, f"complete generated snapshot: {name}\n")

    def assert_published(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name in FILES:
            self.assertEqual(self.remote_text(name), f"complete generated snapshot: {name}")

    def test_unchanged_does_not_commit(self):
        before = self.git(self.remote, "rev-parse", "main")
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, self.git(self.remote, "rev-parse", "main"))

    def test_stale_checkout_preserves_remote_source_and_whole_reports(self):
        self.generate()
        self.write(self.writer, "source.py", "new upstream source\n")
        self.write(self.writer, FILES[0], "conflicting upstream report\n")
        self.commit(self.writer)
        self.git(self.writer, "push", "origin", "main")
        upstream = self.git(self.writer, "rev-parse", "HEAD")
        self.assert_published(self.publish())
        self.assertEqual(self.remote_text("source.py"), "new upstream source")
        self.git(self.remote, "merge-base", "--is-ancestor", upstream, "main")

    def test_new_generated_file_is_published(self):
        self.git(self.worker, "rm", FILES[2])
        self.commit(self.worker)
        self.git(self.worker, "push", "origin", "main")
        self.generate()
        self.assert_published(self.publish())

    def test_remote_already_has_snapshot_does_not_add_commit(self):
        self.generate()
        for name in FILES:
            self.write(self.writer, name, f"complete generated snapshot: {name}\n")
        self.commit(self.writer)
        self.git(self.writer, "push", "origin", "main")
        before = self.git(self.remote, "rev-parse", "main")
        self.assert_published(self.publish())
        self.assertEqual(before, self.git(self.remote, "rev-parse", "main"))

    def test_update_between_fetch_and_push_is_retried(self):
        self.generate()
        # The first pre-push hook advances origin after the publishing fetch.
        hook = self.worker / ".git/hooks/pre-push"
        writer = shlex.quote(str(self.writer))
        marker = shlex.quote(str(self.worker / ".git/race-done"))
        hook.write_text(
            "#!/bin/sh\nset -eu\n"
            f"if [ ! -f {marker} ]; then\n"
            f"  touch {marker}\n"
            f"  printf 'racing source\\n' > {writer}/source.py\n"
            f"  git -C {writer} add source.py\n"
            f"  git -C {writer} commit -m 'concurrent source update'\n"
            f"  git -C {writer} push origin main\n"
            "fi\n", encoding="utf-8",
        )
        hook.chmod(0o755)
        self.assert_published(self.publish())
        self.assertEqual(self.remote_text("source.py"), "racing source")

    def test_rejected_push_stops_after_three_attempts(self):
        self.generate()
        hook = self.remote / "hooks/pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)
        before = self.git(self.remote, "rev-parse", "main")
        result = self.publish()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("after 3 attempts", result.stderr)
        self.assertEqual(result.stderr.count("failed; refreshing"), 3)
        self.assertEqual(before, self.git(self.remote, "rev-parse", "main"))
