"""Windows 10/11 notification area menu; does not modify the battery flyout."""
from __future__ import annotations
import subprocess
import sys
from PIL import Image, ImageDraw


def _command(*args):
    return ([sys.executable] if getattr(sys, 'frozen', False) else [sys.executable, '-m', 'docforge']) + list(args)


def run_tray():
    try:
        import pystray
    except ImportError as exc:
        raise RuntimeError('Для значка в области уведомлений установите pystray: pip install pystray') from exc
    if sys.platform != 'win32':
        raise RuntimeError('Значок системного трея предназначен для Windows 10/11')
    from pathlib import Path
    source = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent)) / 'assets' / 'docforge.png'
    if source.is_file():
        icon = Image.open(source).convert('RGBA').resize((64, 64))
    else:
        icon = Image.new('RGBA', (64, 64), '#315cbe')

    def launch(*args):
        subprocess.Popen(_command(*args), close_fds=True)

    menu = pystray.Menu(
        pystray.MenuItem('▣  DocForge', lambda *_: launch('gui'), default=True),
        pystray.MenuItem('🟥  PDF', lambda *_: launch('quick-to', 'pdf')),
        pystray.MenuItem('🟪  Markdown', lambda *_: launch('quick-to', 'md')),
        pystray.MenuItem('🟦  DOCX', lambda *_: launch('quick-to', 'docx')),
        pystray.MenuItem('🟨  Редактор PDF', lambda *_: launch('edit')),
        pystray.MenuItem('＋  Зона', lambda *_: launch('dropzone')),
        pystray.MenuItem('Выход', lambda tray, _: tray.stop()),
    )
    pystray.Icon('DocForge', icon, 'DocForge — быстрые действия', menu).run()
