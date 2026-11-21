#!/usr/bin/env bash
# Update an installed DocForge 1.x in place. Keeps user settings, venv and files.
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APP_DIR="$DATA_HOME/docforge"
EXT_DIR="$DATA_HOME/nautilus-python/extensions"
SCRIPTS_DIR="$DATA_HOME/nautilus/scripts"
EXTENSION="$EXT_DIR/docforge_extension.py"
ZONE_SCRIPT="$SCRIPTS_DIR/DocForge — стеклянная зона"
if [[ ! -f "$APP_DIR/docforge/__init__.py" ]]; then
  echo 'DocForge not installed; starting a clean installation.'
  exec "$ROOT/install.sh"
fi
if [[ ! -f "$ROOT/docforge/__init__.py" || ! -f "$ROOT/nautilus/docforge_extension.py" ]]; then
  echo 'Не найден полный комплект обновления; распакуйте весь архив.' >&2
  exit 2
fi
mkdir -p -- "$EXT_DIR" "$SCRIPTS_DIR"
backup_dir="$(mktemp -d "$APP_DIR/.backup-XXXXXXXX")"
stage_dir="$(mktemp -d "$APP_DIR/.update-XXXXXXXX")"
success=0
cleanup() {
  local status="$?"
  if [[ "$status" != 0 && "$success" != 1 ]]; then
    if [[ -d "$backup_dir/docforge" ]]; then
      rm -rf -- "$APP_DIR/docforge"
      mv -- "$backup_dir/docforge" "$APP_DIR/docforge"
    fi
    if [[ -d "$backup_dir/assets" ]]; then
      rm -rf -- "$APP_DIR/assets"
      mv -- "$backup_dir/assets" "$APP_DIR/assets"
    fi
    if [[ -f "$backup_dir/extension" ]]; then
      cp -- "$backup_dir/extension" "$EXTENSION"
    else
      rm -f -- "$EXTENSION"
    fi
    if [[ -f "$backup_dir/zone-script" ]]; then
      cp -- "$backup_dir/zone-script" "$ZONE_SCRIPT"
    else
      rm -f -- "$ZONE_SCRIPT"
    fi
    echo 'Ошибка обновления: предыдущие файлы восстановлены.' >&2
  fi
  rm -rf -- "$stage_dir"
}
trap cleanup EXIT

echo '[1/5] Проверка Qt 6 для прозрачного окна...'
# Do not touch existing sources if Qt installation fails. Use the same venv
# that already contains converter libraries; preserve its existing packages.
if [[ "${DOCFORGE_TEST_SKIP_QT_SETUP:-0}" != "1" ]]; then
  if [[ ! -x "$APP_DIR/venv/bin/python" ]]; then
    echo 'Не найдено рабочее окружение Python установленного DocForge.' >&2
    exit 1
  fi
  if ! "$APP_DIR/venv/bin/python" -c 'from PySide6.QtWidgets import QApplication' >/dev/null 2>&1; then
    echo 'Загружаю Qt 6 (PySide6-Essentials), нужен интернет...'
    "$APP_DIR/venv/bin/python" -m pip install --disable-pip-version-check 'PySide6-Essentials>=6.7,<7'
  fi
  "$APP_DIR/venv/bin/python" -c 'from PySide6.QtWidgets import QApplication'
  # pdf2docx is optional: if its download is blocked the local extraction
  # fallback still edits content, but with less precise PDF layout recovery.
  if ! "$APP_DIR/venv/bin/python" -c 'import pdf2docx' >/dev/null 2>&1; then
    echo 'Устанавливаю улучшенный конвертер PDF → DOCX (необязательно)...'
    "$APP_DIR/venv/bin/python" -m pip install --disable-pip-version-check --timeout 12 --retries 0 'pdf2docx>=0.5.13,<0.6' || \
      echo 'pdf2docx недоступен; будет использоваться встроенное извлечение содержимого.'
  fi
fi

if [[ "${DOCFORGE_TEST_SKIP_QT_SETUP:-0}" != "1" ]]; then
  echo 'Устанавливаю независимый движок DOCX/XLSX/PPTX → PDF...'
  "$APP_DIR/venv/bin/python" -m pip install --disable-pip-version-check 'office2pdf-python==0.4.1' 'openpyxl>=3.1,<4' 'python-pptx>=1.0,<2'
fi
echo '[2/5] Подготовка обновления DocForge 1.10.0...' 
cp -a -- "$ROOT/docforge" "$stage_dir/docforge"
cp -a -- "$ROOT/assets" "$stage_dir/assets"
cp -- "$ROOT/nautilus/docforge_extension.py" "$stage_dir/nautilus.py"
python3 -m compileall -q "$stage_dir/docforge" "$stage_dir/nautilus.py"
[[ -f "$EXTENSION" ]] && cp -a -- "$EXTENSION" "$backup_dir/extension"
[[ -f "$ZONE_SCRIPT" ]] && cp -a -- "$ZONE_SCRIPT" "$backup_dir/zone-script"

echo '[3/5] Обновление файлов программы и внешнего вида...'
mv -- "$APP_DIR/docforge" "$backup_dir/docforge"
if [[ -d "$APP_DIR/assets" ]]; then
  mv -- "$APP_DIR/assets" "$backup_dir/assets"
fi
mv -- "$stage_dir/docforge" "$APP_DIR/docforge"
mv -- "$stage_dir/assets" "$APP_DIR/assets"

echo '[4/5] Добавление интеграции с GNOME Files...'
cp -- "$stage_dir/nautilus.py" "$EXTENSION"
cat > "$ZONE_SCRIPT" <<EOF
#!/usr/bin/env bash
exec "${HOME}/.local/bin/docforge" --dropzone
EOF
chmod 755 "$ZONE_SCRIPT"

# Register PDF editor script and opt-in GNOME Quick Settings tiles.
cat > "$SCRIPTS_DIR/DocForge — редактировать PDF" <<EOF
#!/usr/bin/env bash
if [[ "\$#" -gt 0 ]]; then
  exec "${HOME}/.local/bin/docforge" edit "\$1"
else
  exec "${HOME}/.local/bin/docforge" edit
fi
EOF
chmod 755 "$SCRIPTS_DIR/DocForge — редактировать PDF"
# Remove legacy top-bar indicator even when updating from 1.7/1.9.
"$ROOT/remove-gnome-panel.sh" --quiet
# Install/update only the launchable zone shortcut in the applications grid.
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p -- "$DESKTOP_DIR"
cat > "$DESKTOP_DIR/docforge-dropzone.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=DocForge Zone
Name[ru]=DocForge — зона перетаскивания
Exec="${HOME}/.local/bin/docforge" --dropzone
Icon=${APP_DIR}/assets/docforge-zone.png
Terminal=false
Categories=Office;Utility;
StartupNotify=true
EOF
# Refresh the existing main icon, preserving the user's other desktop entries.
MAIN_DESKTOP="$DESKTOP_DIR/docforge.desktop"
if [[ -f "$MAIN_DESKTOP" ]]; then
  sed -i "s|^Icon=.*|Icon=${APP_DIR}/assets/docforge.png|" "$MAIN_DESKTOP"
fi
AUTOSTART="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/docforge-dropzone.desktop"
if [[ -f "$AUTOSTART" ]]; then
  if grep -q '^Icon=' "$AUTOSTART"; then
    sed -i "s|^Icon=.*|Icon=${APP_DIR}/assets/docforge-zone.png|" "$AUTOSTART"
  else
    printf 'Icon=%s\n' "$APP_DIR/assets/docforge-zone.png" >> "$AUTOSTART"
  fi
fi

echo '[5/5] Проверка версии и завершение...'
PYTHONPATH="$APP_DIR${PYTHONPATH:+:$PYTHONPATH}" python3 -m docforge --version
success=1
echo "Готово. Установленная программа обновлена; настройки и venv сохранены."
echo "Резервная копия исходного кода и оформления: $backup_dir"
if command -v dpkg-query >/dev/null && ! dpkg-query -W -f='${Status}' python3-nautilus 2>/dev/null | grep -q 'install ok installed'; then
  echo 'Для нативного меню GNOME Files установите один раз: sudo apt install python3-nautilus'
  echo 'Без этого по-прежнему работает «Файлы → Сценарии → DocForge». '
fi
echo 'Для появления нового контекстного меню выполните: nautilus -q — затем заново откройте «Файлы». '
echo 'Чтобы обновилась уже запущенная плавающая зона, закройте её и запустите ~/.local/bin/docforge --dropzone.'

echo 'Новый стеклянный интерфейс Qt: ~/.local/bin/docforge --dropzone'
