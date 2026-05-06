#!/usr/bin/env bash
# scripts/link.sh — create live symlinks so supported hosts read this workspace copy directly.
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${1:-both}"

link_host() {
  local name="$1"
  local dest="$2"
  echo "Linking $name: $HERE -> $dest"
  mkdir -p "$(dirname "$dest")"
  ln -sfn "$HERE" "$dest"
}

case "$HOST" in
  codex)
    link_host "codex" "${CODEX_HOME:-$HOME/.codex}/skills/using-memory"
    ;;
  claude-code)
    link_host "claude-code" "${CLAUDE_HOME:-$HOME/.claude}/skills/using-memory"
    ;;
  both)
    link_host "codex" "${CODEX_HOME:-$HOME/.codex}/skills/using-memory"
    link_host "claude-code" "${CLAUDE_HOME:-$HOME/.claude}/skills/using-memory"
    ;;
  *)
    echo "Usage: $0 [codex|claude-code|both]" >&2
    exit 2
    ;;
esac
