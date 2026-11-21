#!/usr/bin/env bash
# DocForge installer for Ubuntu 24.04+ / Debian 12+. Never requires sudo for app files.
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/docforge"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
NAUTILUS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/nautilus/scripts"
NAUTILUS_EXT="${XDG_DATA_HOME:-$HOME/.local/share}/nautilus-python/extensions"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
SKIP_APT=0
SKIP_PIP=0
AUTOSTART=0
for arg in "$@"; do
  case "$arg" in
    --skip-apt) SKIP_APT=1 ;;
    --skip-pip) SKIP_PIP=1 ;;
    --no-autostart) AUTOSTART=0 ;;
    --autostart) AUTOSTART=1 ;;
    -h|--help) echo 'Использование: ./install.sh [--skip-apt] [--skip-pip] [--no-autostart] [--autostart]'; exit 0 ;;
    *) echo "Неизвестный аргумент: $arg" >&2; exit 2 ;;
  esac
done

# Reuse the existing installation and update in place; never recreate its venv.
if [[ -f "$APP_DIR/docforge/__init__.py" ]]; then
  echo 'Existing DocForge detected; safe in-place update.'
  exec "$ROOT/update.sh"
fi
"$ROOT/remove-gnome-panel.sh" --quiet
echo '[1/5] Проверка системных зависимостей...'
if [[ "$SKIP_APT" == 0 ]]; then
  if command -v apt-get >/dev/null; then
    if command -v sudo >/dev/null; then
      APT=(sudo apt-get)
    elif [[ "${EUID}" == 0 ]]; then
      APT=(apt-get)
    else
      echo 'Для установки системных пакетов требуется sudo.' >&2
      exit 1
    fi
    "${APT[@]}" update
    "${APT[@]}" install -y python3 python3-venv python3-pip python3-tk \
      pandoc poppler-utils ghostscript tesseract-ocr python3-nautilus \
      tesseract-ocr-rus tesseract-ocr-eng fonts-dejavu-core \
      libcairo2 libpango-1.0-0 libgdk-pixbuf-2.0-0 \
      libegl1 libxcb-cursor0 libxkbcommon-x11-0 libxcb-xinerama0
  else
    echo 'Этот установщик рассчитан на Ubuntu/Debian (apt). Запустите с --skip-apt, если компоненты уже установлены.' >&2
    exit 1
  fi
fi

command -v python3 >/dev/null || { echo 'Нужен Python 3' >&2; exit 1; }
mkdir -p "$APP_DIR" "$BIN_DIR" "$DESKTOP_DIR" "$NAUTILUS_DIR" "$NAUTILUS_EXT" "$AUTOSTART_DIR"
echo '[2/5] Установка DocForge...'
rm -rf -- "$APP_DIR/docforge" "$APP_DIR/assets"
cp -R -- "$ROOT/docforge" "$ROOT/assets" "$APP_DIR/"
python3 -m venv "$APP_DIR/venv"
if [[ "$SKIP_PIP" == 0 ]]; then
  "$APP_DIR/venv/bin/python" -m pip install --disable-pip-version-check --upgrade pip
  "$APP_DIR/venv/bin/python" -m pip install --disable-pip-version-check -r "$ROOT/requirements.txt"
  "$APP_DIR/venv/bin/python" -m pip install --disable-pip-version-check --timeout 12 --retries 0 'pdf2docx>=0.5.13,<0.6' || \
    echo 'Дополнительный pdf2docx не установлен. Редактирование содержимого продолжит работать с упрощённым извлечением.'
fi

cat > "$BIN_DIR/docforge" <<EOF
#!/usr/bin/env bash
set -e
export PYTHONPATH="${APP_DIR}\${PYTHONPATH:+:\$PYTHONPATH}"
exec "${APP_DIR}/venv/bin/python" -m docforge "\$@"
EOF
chmod 755 "$BIN_DIR/docforge"

echo '[3/5] Интеграция с приложениями Ubuntu...'
cat > "$DESKTOP_DIR/docforge.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=DocForge
Name[ru]=DocForge — конвертер документов
Comment=Локальная конвертация документов и работа с PDF
Exec="${BIN_DIR}/docforge" --open %F
TryExec=${BIN_DIR}/docforge
Icon=${APP_DIR}/assets/docforge.png
Terminal=false
Categories=Office;Utility;
MimeType=application/pdf;text/markdown;text/plain;text/html;application/vnd.openxmlformats-officedocument.wordprocessingml.document;application/msword;application/vnd.oasis.opendocument.text;image/png;image/jpeg;image/webp;
StartupNotify=true
EOF

# Dedicated launcher in the app grid (not a GNOME Shell panel icon).
cat > "$DESKTOP_DIR/docforge-dropzone.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=DocForge Zone
Name[ru]=DocForge — зона перетаскивания
Comment=Drag files onto the compact DocForge conversion zone
Exec="${BIN_DIR}/docforge" --dropzone
TryExec=${BIN_DIR}/docforge
Icon=${APP_DIR}/assets/docforge-zone.png
Terminal=false
Categories=Office;Utility;
StartupNotify=true
EOF

create_nautilus_script() {
  local name="$1"; shift
  local file="$NAUTILUS_DIR/$name"
  {
    printf '#!/usr/bin/env bash\n'
    printf 'exec %q ' "$BIN_DIR/docforge"
    printf '%q ' "$@"
    printf '"$@"\n'
  } > "$file"
  chmod 755 "$file"
}

create_nautilus_script 'DocForge — выбрать формат' --quick
# If python3-nautilus is missing, the Scripts submenu still exposes the glass panel.
cat > "$NAUTILUS_DIR/DocForge — стеклянная зона" <<EOF
#!/usr/bin/env bash
exec "${BIN_DIR}/docforge" --dropzone
EOF
chmod 755 "$NAUTILUS_DIR/DocForge — стеклянная зона"
cp -- "$ROOT/nautilus/docforge_extension.py" "$NAUTILUS_EXT/docforge_extension.py"
create_nautilus_script 'DocForge — в PDF' convert --to pdf --notify
create_nautilus_script 'DocForge — в Markdown' convert --to md --notify
create_nautilus_script 'DocForge — в Word' convert --to docx --notify
cat > "$NAUTILUS_DIR/DocForge — редактировать PDF" <<EOF
#!/usr/bin/env bash
if [[ "\$#" -gt 0 ]]; then
  exec "${BIN_DIR}/docforge" edit "\$1"
else
  exec "${BIN_DIR}/docforge" edit
fi
EOF
chmod 755 "$NAUTILUS_DIR/DocForge — редактировать PDF"
create_nautilus_script 'DocForge — объединить PDF' merge --notify
create_nautilus_script 'DocForge — сжать PDF' compress --notify

if [[ "$AUTOSTART" == 1 ]]; then
  cat > "$AUTOSTART_DIR/docforge-dropzone.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=DocForge Drop Zone
Name[ru]=DocForge — зона для перетаскивания
Exec="${BIN_DIR}/docforge" --dropzone
Icon=${APP_DIR}/assets/docforge-zone.png
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
else
  rm -f -- "$AUTOSTART_DIR/docforge-dropzone.desktop"
fi

if command -v update-desktop-database >/dev/null; then
  update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
fi

# No GNOME Shell top-bar extension is installed by DocForge.

echo '[4/5] Проверка компонентов...'
"$BIN_DIR/docforge" doctor || {
  echo 'Некоторые компоненты недоступны. Доступные преобразования будут определяться автоматически.' >&2
}

echo '[5/5] Готово.'
echo "Откройте DocForge в меню программ или выполните: $BIN_DIR/docforge"
echo "Контекстное меню: Файлы → правой кнопкой → DocForge · конвертер…"
echo "Если меню не видно, перезапустите Nautilus: nautilus -q (или используйте Сценарии → DocForge)."
echo "Плавающая зона: $BIN_DIR/docforge --dropzone"
if [[ "$AUTOSTART" == 1 ]] && [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
  # Launch only if not already running; avoids duplicates on repeated installs.
  if ! pgrep -u "$(id -u)" -f '[p]ython.*docforge.*dropzone' >/dev/null 2>&1; then
    nohup "$BIN_DIR/docforge" --dropzone >/dev/null 2>&1 </dev/null &
  fi
fi
