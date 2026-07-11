#!/bin/bash
# PreToolUse hook (create_pull_request): enforces the "Remote Session
# Requirements" from CLAUDE.md automatically instead of relying on Claude to
# remember to run them — runs pre-commit (ruff format/check, ty check,
# pytest) across the repo and blocks PR creation until it's clean.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

if ! output=$(uv run pre-commit run --all-files 2>&1); then
  echo "$output" >&2
  echo "pre-commit run --all-files failed. Fix the issues above before creating the pull request." >&2
  exit 2
fi
