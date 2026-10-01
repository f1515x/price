"""Build and verify an independent mirror with known historical cookies redacted.

Never changes the source repository or pushes. Requires git-filter-repo 2.47.0.
Secrets stay in memory; reports contain object IDs and counts only.
"""
import argparse
import ast
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys

VERSION = "price-cookie-history-v1"
SENSITIVE_KEYS = {"sessionid", "sessionid_sign", "device_t", "tv_ecuid",
                  "etg", "cachec"}
REPLACEMENT = b"REDACTED_HISTORICAL_COOKIE"


def git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if result.returncode:
        # Git stderr can contain object contents or remote credentials.
        raise RuntimeError("Git operation failed: " + args[0])
    return result.stdout


def refs(repo):
    return dict(line.decode().split(" ", 1) for line in
                git(repo, "for-each-ref", "--format=%(refname) %(objectname)").splitlines())


def objects(repo):
    """Read ALL stored objects, including unreachable objects, without logging data."""
    inventory = git(repo, "cat-file", "--batch-all-objects",
                    "--batch-check=%(objectname) %(objecttype)")
    proc = subprocess.Popen(["git", "-C", str(repo), "cat-file", "--batch"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)
    try:
        for row in inventory.splitlines():
            oid, kind = row.split()
            proc.stdin.write(oid + b"\n")
            proc.stdin.flush()
            header = proc.stdout.readline().split()
            if len(header) != 3 or header[0] != oid or header[1] != kind:
                raise RuntimeError("Invalid Git object stream")
            size = int(header[2])
            body = proc.stdout.read(size)
            if len(body) != size or proc.stdout.read(1) != b"\n":
                raise RuntimeError("Truncated Git object stream")
            yield oid.decode(), kind.decode(), body
    finally:
        proc.stdin.close()
        proc.stdout.close()
        proc.wait()
    if proc.returncode:
        raise RuntimeError("Git object scan failed")


def discover(repo):
    """Extract literal cookie values from every reachable historical month.py."""
    values, keys, checked = set(), set(), 0
    for row in git(repo, "rev-list", "--objects", "--all", "--", "month.py").splitlines():
        parts = row.split(b" ", 1)
        if len(parts) != 2 or parts[1] != b"month.py":
            continue
        checked += 1
        body = git(repo, "cat-file", "blob", parts[0].decode())
        try:
            tree = ast.parse(body)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Dict):
                    continue
                names = {k.value for k in node.keys if isinstance(k, ast.Constant)
                         and isinstance(k.value, str)}
                if "sessionid" not in names:
                    continue
                cookies = ast.literal_eval(node)
                for key, value in cookies.items():
                    if key in SENSITIVE_KEYS or key.startswith("_sp_id."):
                        if not isinstance(value, str) or len(value.encode()) < 8:
                            raise ValueError("Unsafe cookie literal length/type")
                        values.add(value.encode())
                        keys.add(key)
        except (SyntaxError, ValueError, TypeError):
            raise ValueError("Cannot safely parse historical cookie literals") from None
    if not values:
        raise ValueError("No known historical cookie literals found")
    return sorted(values, key=lambda v: (-len(v), v)), sorted(keys), checked


def scan(repo, values):
    counts, hits = {}, []
    for oid, kind, body in objects(repo):
        counts[kind] = counts.get(kind, 0) + 1
        if any(value in body for value in values):
            hits.append(dict(object_id=oid, object_type=kind))
    return dict(object_counts=counts, matching_objects=hits)


def sanitize(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists() or source == destination or source in destination.parents:
        raise ValueError("Destination must be new and outside the source repository")
    if git(source, "rev-parse", "--is-shallow-repository").strip() != b"false":
        raise ValueError("Shallow source cannot establish complete local history")
    if importlib.metadata.version("git-filter-repo") != "2.47.0":
        raise ValueError("Use git-filter-repo==2.47.0 for reproducibility")
    original_refs = refs(source)
    values, keys, checked = discover(source)
    before = scan(source, values)
    head_tree = git(source, "rev-parse", "refs/heads/feature^{tree}").strip().decode()
    destination.parent.mkdir(parents=True, exist_ok=True)
    # --no-local avoids hard links, alternates, and copying unreachable source objects.
    result = subprocess.run(["git", "clone", "--mirror", "--no-local", str(source),
                             str(destination)], capture_output=True)
    if result.returncode:
        raise RuntimeError("Independent mirror clone failed")

    # Isolate filter-repo's process-global state and subprocess output. Secret values
    # travel through stdin, never command-line arguments, files or console output.
    worker = """import json, sys, git_filter_repo as f
values = [bytes.fromhex(v) for v in json.load(sys.stdin)]
def redact(body):
    for value in values:
        body = body.replace(value, b'REDACTED_HISTORICAL_COOKIE')
    return body
def blob_callback(blob, metadata):
    blob.data = redact(blob.data)
args = f.FilteringOptions.parse_args(['--force', '--partial', '--prune-empty', 'never', '--prune-degenerate', 'never'])
f.RepoFilter(args, blob_callback=blob_callback, message_callback=redact).run()
"""
    rewritten = subprocess.run([sys.executable, "-c", worker], cwd=destination,
                               input=json.dumps([v.hex() for v in values]).encode(),
                               capture_output=True)
    if rewritten.returncode:
        raise RuntimeError("History rewrite failed; output must not be published")
    # Remove clone transport regardless of filter-repo's origin-removal behavior.
    for remote in git(destination, "remote").decode().splitlines():
        git(destination, "config", "--remove-section", "remote." + remote)
    git(destination, "reflog", "expire", "--expire=now", "--all")
    git(destination, "-c", "gc.autoDetach=false", "gc", "--prune=now")
    after = scan(destination, values)
    if after["matching_objects"]:
        raise ValueError("Redaction incomplete; output must not be published")
    cleaned_refs = refs(destination)
    if set(cleaned_refs) != set(original_refs):
        raise ValueError("Reference coverage changed")
    if git(destination, "rev-parse", "refs/heads/feature^{tree}").strip().decode() != head_tree:
        raise ValueError("Current feature tree changed; output needs review")
    git(destination, "fsck", "--full", "--no-reflogs")
    if refs(source) != original_refs:
        raise ValueError("Source references changed during operation")
    source_count = int(git(source, "rev-list", "--all", "--count"))
    clean_count = int(git(destination, "rev-list", "--all", "--count"))
    if source_count != clean_count:
        raise ValueError("Commit count changed")
    report = dict(version=VERSION, status="LOCAL_SANITIZED_MIRROR_VERIFIED",
                  source=str(source), destination=str(destination),
                  cookie_keys=keys, unique_sensitive_values=len(values),
                  historical_month_blobs_checked=checked,
                  before=before, after=after, source_refs=original_refs,
                  sanitized_refs=cleaned_refs, source_commit_count=source_count,
                  sanitized_commit_count=clean_count, feature_tree=head_tree,
                  source_refs_unchanged=True, feature_tree_unchanged=True,
                  remotes=[], remote_history_cleaned=False, session_revoked=False,
                  source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  filter_repo_version="2.47.0",
                  limitations=["Known literal cookies only; not a general secret scanner.",
                               "Original source and GitHub history remain unchanged.",
                               "Account session revocation has not been performed.",
                               "Local refs only; remote-only refs and caches are outside scope."])
    (destination / "sanitization-audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("destination", help="New independent bare mirror directory")
    args = parser.parse_args()
    report = sanitize(args.source, args.destination)
    print(json.dumps({k: report[k] for k in
                      ("status", "unique_sensitive_values", "source_commit_count",
                       "sanitized_commit_count", "feature_tree_unchanged")}, indent=2))


if __name__ == "__main__":
    main()
