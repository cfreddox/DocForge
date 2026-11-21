"""Simple cross-platform conversion picker used by GNOME tiles and Windows tray."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from .core import ConversionError, convert, targets_for


def quick_convert(target: str) -> list[Path]:
    root = tk.Tk()
    root.withdraw()
    result: list[Path] = []
    try:
        files = filedialog.askopenfilenames(title=f'DocForge · выбрать файлы → {target.upper()}', parent=root)
        if not files:
            return []
        bad = [Path(p).name for p in files if target not in targets_for(Path(p))]
        if bad:
            raise ConversionError('Неподдерживаемое преобразование для: ' + ', '.join(bad[:5]))
        for path in files:
            result.append(convert(Path(path), target))
        messagebox.showinfo('DocForge', f'Готово. Создано: {len(result)}\nПапка: {result[-1].parent}', parent=root)
        return result
    except Exception as exc:
        messagebox.showerror('DocForge', str(exc), parent=root)
        return []
    finally:
        root.destroy()
