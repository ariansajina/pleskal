#!/bin/bash
# SessionStart hook: prepares the environment for Claude Code on the web so
# tests, linters, and pre-commit are ready without Claude having to spend
# turns installing dependencies itself.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# The container ships no Python 3.14 and its uv predates the current 3.14
# patch releases (it would fetch a 3.14 release candidate), so install the
# interpreter from .python-version with an up-to-date uv first.
uvx uv@latest python install
uv sync --dev
npm install
uv run pre-commit install --install-hooks
