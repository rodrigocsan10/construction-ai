#!/usr/bin/env bash
# Periodic commit + push for this repo. Schedule with launchd (see launchd/ in repo) or cron.
#
# Env:
#   GIT_AUTOSAVE_NO_PUSH=1  — commit only, no push
#   GIT_AUTOSAVE_BRANCH=main — branch to push (default: current)

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "git_autosave: not a git repository" >&2
  exit 1
fi

# Nothing to do
if [ -z "$(git status --porcelain)" ]; then
  exit 0
fi

git add -A

# Only ignored files changed → nothing staged
if git diff --cached --quiet; then
  exit 0
fi

MSG="autosave $(date +"%Y-%m-%d %H:%M %z")"
git commit -m "$MSG"

if [ "${GIT_AUTOSAVE_NO_PUSH:-}" = "1" ]; then
  echo "git_autosave: committed; push skipped (GIT_AUTOSAVE_NO_PUSH=1)"
  exit 0
fi

BRANCH="${GIT_AUTOSAVE_BRANCH:-$(git branch --show-current)}"
git push -u origin "$BRANCH"
