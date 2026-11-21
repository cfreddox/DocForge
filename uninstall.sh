#!/usr/bin/env bash
set -Eeuo pipefail
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/docforge"
BIN="$HOME/.local/bin/docforge"
DESKTOP="${XDG_DATA_HOME:-$HOME/.local/share}/applications/docforge.desktop"
ZONE_DESKTOP="${XDG_DATA_HOME:-$HOME/.local/share}/applications/docforge-dropzone.desktop"
SCRIPTS="${XDG_DATA_HOME:-$HOME/.local/share}/nautilus/scripts"
AUTOSTART="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/docforge-dropzone.desktop"
EXT="${XDG_DATA_HOME:-$HOME/.local/share}/nautilus-python/extensions/docforge_extension.py"
rm -f -- "$BIN" "$DESKTOP" "$ZONE_DESKTOP" "$AUTOSTART" "$EXT"
for name in 'DocForge — выбрать формат' 'DocForge — в PDF' 'DocForge — в Markdown' \
 'DocForge — в Word' 'DocForge — редактировать PDF' 'DocForge — стеклянная зона' 'DocForge — объединить PDF' 'DocForge — сжать PDF'; do
  rm -f -- "$SCRIPTS/$name"
done
UUID='docforge-quick@local'
GNOME_PATH="${XDG_DATA_HOME:-$HOME/.local/share}/gnome-shell/extensions/$UUID"
if command -v gnome-extensions >/dev/null 2>&1; then
  gnome-extensions disable "$UUID" >/dev/null 2>&1 || true
fi
rm -rf -- "$GNOME_PATH" "$APP_DIR"
echo 'DocForge удалён из пользовательских каталогов. Созданные документы сохранены.'
echo 'Системные зависимости не удалялись (они могут использоваться другими приложениями).'
