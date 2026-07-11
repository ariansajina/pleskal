#!/bin/bash
# SessionStart hook: prepares the environment for Claude Code on the web so
# tests, linters, and pre-commit are ready without Claude having to spend
# turns installing dependencies itself.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

uv sync --dev
npm install
uv run pre-commit install --install-hooks
