#!/usr/bin/env bash
# scripts/install.sh — copy the skill tree for a clean install in supported hosts.
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${1:-both}"

install_host() {
  local name="$1"
  local dest="$2"
  echo "Installing $name: $HERE -> $dest"
  mkdir -p "$dest"
  cp -a "$HERE"/. "$dest"/
  find "$dest" \( -name __pycache__ -o -name '*.pyc' -o -name '*.swp' \) -prune -exec rm -rf {} +
  echo "Installed $name. Destination: $dest"
}

case "$HOST" in
  codex)
    install_host "codex" "${CODEX_HOME:-$HOME/.codex}/skills/using-memory"
    ;;
  claude-code)
    install_host "claude-code" "${CLAUDE_HOME:-$HOME/.claude}/skills/using-memory"
    ;;
  both)
    install_host "codex" "${CODEX_HOME:-$HOME/.codex}/skills/using-memory"
    install_host "claude-code" "${CLAUDE_HOME:-$HOME/.claude}/skills/using-memory"
    ;;
  *)
    echo "Usage: $0 [codex|claude-code|both]" >&2
    exit 2
    ;;
esac
