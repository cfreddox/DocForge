#!/usr/bin/env bash
# Polished optional graphical installer for Ubuntu/Debian. Console install.sh remains supported.
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v zenity >/dev/null 2>&1 || [[ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
  echo 'Graphical setup requires Zenity and a desktop session; starting terminal installer.'
  exec "$ROOT/install.sh" "$@"
fi
if ! zenity --question --width=500 --title='DocForge — установка' \
   --ok-label='Установить' --cancel-label='Отмена' \
   --text='<big><b>DocForge — конвертер и PDF-редактор</b></big>\n\nЛокальная обработка документов, отдельная стеклянная зона и быстрые действия в Nautilus.\n\nПосле установки значок DocForge будет в меню программ. Старый индикатор верхней панели GNOME будет удалён.\n\nДля первой установки нужен интернет.'; then
  exit 0
fi
if [[ "${DOCFORGE_SKIP_SYSTEM_PACKAGES:-0}" != '1' ]] && command -v apt-get >/dev/null 2>&1; then
  if ! command -v pkexec >/dev/null 2>&1; then
    zenity --error --width=440 --title='DocForge' --text='Не найден pkexec для системных библиотек. Запустите install.sh в терминале.'
    exit 1
  fi
  zenity --info --width=480 --title='DocForge' --text='Следующий шаг — установка системных библиотек Ubuntu. Может появиться системный запрос авторизации. Это не устанавливает LibreOffice.'
  pkexec /usr/bin/apt-get update
  pkexec /usr/bin/apt-get install -y python3 python3-venv python3-pip python3-tk pandoc \
    poppler-utils ghostscript tesseract-ocr python3-nautilus \
    tesseract-ocr-rus tesseract-ocr-eng fonts-dejavu-core \
    libcairo2 libpango-1.0-0 libgdk-pixbuf-2.0-0 libegl1 \
    libxcb-cursor0 libxkbcommon-x11-0 libxcb-xinerama0
fi
LOG="$(mktemp -t docforge-setup-log-XXXXXXXX)"
STATUS="$(mktemp -t docforge-setup-status-XXXXXXXX)"
trap 'rm -f -- "$STATUS"' EXIT
(
  (
    set +e
    "$ROOT/install.sh" --skip-apt "$@" >"$LOG" 2>&1
    echo "$?" >"$STATUS"
  ) &
  worker=$!
  while kill -0 "$worker" 2>/dev/null; do
    echo '# Устанавливаем DocForge и проверяем конвертеры…'
    sleep 0.5
  done
  wait "$worker" || true
  echo 100
) | zenity --progress --pulsate --no-cancel --auto-close --width=500 \
          --title='DocForge — установка' --text='Подготовка…' || true
if [[ "$(cat "$STATUS" 2>/dev/null || echo 1)" != '0' ]]; then
  zenity --error --width=500 --title='DocForge — ошибка' \
    --text="Установка не завершена. Журнал сохранён: $LOG"
  exit 1
fi
rm -f -- "$LOG"
zenity --info --width=480 --title='DocForge — готово' \
  --text='<big><b>DocForge установлен!</b></big>\n\nЗапусти DocForge или DocForge Zone из меню приложений.\n\nЗначка в верхней панели GNOME больше нет.'
