#!/usr/bin/env bash
# Only remove the legacy DocForge GNOME Shell indicator, never unrelated extensions.
set -euo pipefail
UUID='docforge-quick@local'
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
if command -v gnome-extensions >/dev/null 2>&1; then
  gnome-extensions disable "$UUID" >/dev/null 2>&1 || true
  gnome-extensions uninstall "$UUID" >/dev/null 2>&1 || true
fi
rm -rf -- "$DATA_HOME/gnome-shell/extensions/$UUID"
if [[ "${1:-}" != '--quiet' ]]; then
  echo 'Legacy GNOME top-bar indicator removed. Other extensions were left untouched.'
  echo 'If the icon persists in this session, log out and log in again.'
fi
