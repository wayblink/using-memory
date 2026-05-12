#!/usr/bin/env bash
# scripts/link.sh - create live symlinks so supported hosts read this workspace copy directly.
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${1:-both}"

run_first_time_setup() {
 local config_path="${USING_MEMORY_CONFIG:-$HOME/.skills/using-memory/config.yaml}"
 if [ "${USING_MEMORY_SKIP_SETUP:-0}" = "1" ]; then
  echo "Skipping memory storage setup because USING_MEMORY_SKIP_SETUP=1"
  return
 fi
 if [ -f "$config_path" ]; then
  echo "Memory storage config already exists: $config_path"
  return
 fi
 if [ -t 0 ]; then
  echo "No memory storage config found. Starting first-time setup."
  python3 "$HERE/scripts/memory_tool.py" setup
 else
  echo "No memory storage config found: $config_path"
  echo "Run this later to configure memory storage path, remote Git repo, namespace, and machine ID:"
  echo "  python3 $HERE/scripts/memory_tool.py setup"
 fi
}

link_host() {
 local name="$1"
 local dest="$2"
 echo "Linking $name: $HERE -> $dest"
 mkdir -p "$(dirname "$dest")"
 if [ -e "$dest" ] && [ ! -L "$dest" ]; then
  echo "refusing to replace existing directory: $dest" >&2
  echo "Remove it manually or run scripts/install.sh for a copied install." >&2
  exit 2
 fi
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

run_first_time_setup
