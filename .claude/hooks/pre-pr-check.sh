#!/bin/bash
# PreToolUse hook (create_pull_request): runs the repo's checks automatically
# instead of relying on Claude to remember them — runs pre-commit (ruff
# format/check, ty check, pytest) across the repo and blocks PR creation until
# it's clean.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# pre-commit checks the working tree, so uncommitted edits could make it pass
# (or fail) on code the PR doesn't contain.
if ! git diff --quiet HEAD --; then
  git status --short --untracked-files=no >&2
  echo "Tracked files have uncommitted changes. Commit and push them (or revert them) before creating the pull request, so the checks run on what the PR contains." >&2
  exit 2
fi

if ! output=$(uv run pre-commit run --all-files 2>&1); then
  echo "$output" >&2
  if ! git diff --quiet HEAD --; then
    echo "pre-commit rewrote files (ruff format / ruff check --fix); review, commit and push those changes." >&2
  fi
  echo "pre-commit run --all-files failed. Fix the issues above before creating the pull request." >&2
  exit 2
fi
