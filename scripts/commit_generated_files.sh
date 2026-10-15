#!/usr/bin/env bash
set -euo pipefail

branch=${1:?Usage: commit_generated_files.sh BRANCH}
files=(reports/sizes.txt reports/signals.txt data/price_steps.json)

if git diff --quiet -- "${files[@]}" \
   && [ -z "$(git ls-files --others --exclude-standard -- "${files[@]}")" ]; then
  echo "Generated files are unchanged; nothing to commit."
  exit 0
fi

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add -- "${files[@]}"
git commit -m "chore: update calculated prices"
generated_commit=$(git rev-parse HEAD)

# Reapply the complete report snapshot to the latest remote tree. Rebasing text
# hunks could mix two runs' reports; only these three generated files are replaced.
for attempt in 1 2 3; do
  git fetch --no-tags origin "refs/heads/$branch"
  git checkout --detach FETCH_HEAD
  git restore --source="$generated_commit" --staged --worktree -- "${files[@]}"

  if git diff --cached --quiet; then
    echo "Remote already contains these generated files; nothing to commit."
    exit 0
  fi

  git commit -m "chore: update calculated prices"
  if git push origin "HEAD:refs/heads/$branch"; then
    exit 0
  fi
  echo "Push attempt $attempt failed; refreshing the remote branch." >&2
done

echo "Unable to publish generated files after 3 attempts." >&2
exit 1
