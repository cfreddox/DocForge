# Архитектура

`docforge/core.py`: конвертация, `md_assets.py`: ресурсы Markdown, `office_native.py`: офисный PDF-рендер, `word_workflow.py` и `word_ui.py`: редактируемая копия PDF через DOCX. `gui.py`: главное окно, `liquid_qt.py`: стеклянная Qt-зона, `zone_lock.py`: Linux-блокировка второго экземпляра. `nautilus/`: интеграция GNOME Files. `windows/`: пользовательский установщик, ярлыки и диагностические скрипты. `tests/`: регрессионные тесты.

Установка Windows работает в `%LOCALAPPDATA%\DocForge` и использует внутренний Python/venv; Linux — в `~/.local/share/docforge` и виртуальном окружении. Настройки находятся вне директории исходников. Конвертация локальная, кроме загрузки программных зависимостей в момент установки.
