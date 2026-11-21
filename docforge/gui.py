"""Tk-based desktop and floating drop zone UI (Russian language)."""
from __future__ import annotations

import os
import json
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from PIL import ImageTk
from typing import Callable

from . import __version__
from .appearance import (ACCENTS, ANIMATION_STYLES, DEFAULTS, SIZES, THEMES, ZONE_STYLES, clamp_primary,
                         load_settings, on_primary, palette, save_settings)
from .glass import glass_panel
from .petals import Action, BASE_W, BASE_H, actions_for
from .core import (SUPPORTED, ConversionError, common_targets, compress_pdf, convert,
                   merge_pdfs, rotate_pdf, source_ext, split_pdf)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    RootClass = TkinterDnD.Tk
    DND_ENABLED = True
except ImportError:
    RootClass = tk.Tk
    DND_FILES = "DND_Files"
    DND_ENABLED = False

BG = "#0b1220"
PANEL = "#111e31"
PANEL2 = "#16263d"
LINE = "#465e7f"
FG = "#edf3fc"
MUTED = "#b6c9e4"
BLUE = "#4289ff"
BLUE_HOVER = "#256de0"
GREEN = "#76e0b3"
ACCENT_TEXT = "#ffffff"
ERROR = "#ff9d9d"
CURRENT_SETTINGS = DEFAULTS.copy()


def select_appearance(config: dict) -> None:
    global BG, PANEL, PANEL2, LINE, FG, MUTED, BLUE, BLUE_HOVER, GREEN, ACCENT_TEXT, ERROR, CURRENT_SETTINGS
    from PIL import ImageColor
    CURRENT_SETTINGS = config.copy()
    colors = palette(config)
    BG, PANEL, PANEL2, LINE = (colors[k] for k in ("bg", "panel", "panel2", "line"))
    FG, MUTED, BLUE, GREEN = (colors[k] for k in ("fg", "muted", "accent", "success"))
    ACCENT_TEXT, ERROR = colors["accent_fg"], colors["error"]
    rgb = ImageColor.getrgb(BLUE)
    BLUE_HOVER = "#%02x%02x%02x" % tuple(max(0, int(v * 0.78)) for v in rgb)


def hover_button(parent, label: str, command: Callable, *, primary: bool = False,
                 width: int | None = None) -> tk.Button:
    bg = BLUE if primary else PANEL2
    active = BLUE_HOVER if primary else "#243957"
    opts = {"text": label, "command": command, "bg": bg, "fg": ACCENT_TEXT if primary else FG, "activebackground": active,
            "activeforeground": ACCENT_TEXT if primary else FG, "relief": "flat", "bd": 0, "cursor": "hand2",
            "font": ("DejaVu Sans", 10, "bold" if primary else "normal"), "padx": 17, "pady": 11}
    if width is not None:
        opts["width"] = width
    btn = tk.Button(parent, **opts)
    btn.bind("<Enter>", lambda event: btn.config(bg=active))
    btn.bind("<Leave>", lambda event: btn.config(bg=bg))
    return btn


def info_label(parent, text: str, *, color: str | None = None, size: int = 10, weight: str = "normal",
               bg: str | None = None, **kwargs) -> tk.Label:
    return tk.Label(parent, text=text, fg=color or MUTED, bg=bg or BG,
                    font=("DejaVu Sans", size, weight), **kwargs)


def setup_style(root: tk.Tk) -> None:
    root.configure(bg=BG)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TCombobox", padding=9, relief="flat", fieldbackground=PANEL2,
                    background=PANEL2, foreground=FG, arrowcolor=FG)
    style.map("TCombobox", fieldbackground=[("readonly", PANEL2)],
              foreground=[("readonly", FG)], selectbackground=[("readonly", PANEL2)])
    style.configure("Doc.TProgressbar", background=BLUE, troughcolor=PANEL2, borderwidth=0)
    style.configure("TScale", background=PANEL)


def bind_drop(widget: tk.Widget, callback: Callable) -> bool:
    if not DND_ENABLED or not hasattr(widget, "drop_target_register"):
        return False
    try:
        widget.drop_target_register(DND_FILES)
        widget.dnd_bind("<<Drop>>", callback)
        return True
    except (tk.TclError, AttributeError):
        return False


def dropped_paths(widget: tk.Widget, event) -> list[Path]:
    """Tcl splitlist handles spaces, Unicode, and braces in dropped filenames."""
    try:
        values = widget.tk.splitlist(event.data)
    except tk.TclError:
        values = [event.data]
    selected = []
    for value in values:
        p = Path(value).expanduser()
        if p.is_file() and p not in selected:
            selected.append(p)
    return selected


def open_directory(path: Path) -> None:
    directory = path if path.is_dir() else path.parent
    try:
        if os.name == 'nt':
            os.startfile(str(directory))
        else:
            subprocess.Popen(["xdg-open", str(directory)], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


class AppHost:
    """Common thread-safe task dispatch for quick window and main window."""
    def __init__(self, root: tk.Tk):
        self.root = root
        self.events: queue.Queue = queue.Queue()
        self.root.after(120, self._poll)

    def submit(self, job: Callable, finished: Callable, failed: Callable):
        def worker():
            try:
                self.events.put((finished, job()))
            except Exception as exc:
                self.events.put((failed, str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        try:
            while True:
                callback, data = self.events.get_nowait()
                callback(data)
        except queue.Empty:
            pass
        try:
            if self.root.winfo_exists():
                self.root.after(120, self._poll)
        except tk.TclError:
            pass


def _glass_button(canvas: tk.Canvas, x: int, y: int, width: int, height: int,
                  text: str, action: Callable, *, primary: bool = False, tag: str = "button") -> None:
    """Draw a clickable rounded capsule entirely on canvas (no opaque widget blocks)."""
    bg = BLUE if primary else ("#DCE8F8" if CURRENT_SETTINGS["theme"] == "liquid_light" else "#38506B")
    foreground = ACCENT_TEXT if primary else FG
    all_tag = (tag,)
    canvas.create_oval(x, y, x + height, y + height, fill=bg, outline="", tags=all_tag)
    canvas.create_oval(x + width - height, y, x + width, y + height,
                       fill=bg, outline="", tags=all_tag)
    canvas.create_rectangle(x + height//2, y, x + width - height//2,
                            y + height, fill=bg, outline="", tags=all_tag)
    canvas.create_text(x + width//2, y + height//2, text=text,
                       font=("DejaVu Sans", 10, "bold" if primary else "normal"),
                       fill=foreground, tags=all_tag)
    canvas.tag_bind(tag, "<Button-1>", lambda event: action())
    canvas.tag_bind(tag, "<Enter>", lambda event: canvas.config(cursor="hand2"))
    canvas.tag_bind(tag, "<Leave>", lambda event: canvas.config(cursor=""))


class QuickDialog(tk.Toplevel):
    """Glossy and translucent quick conversion chooser, centered on primary screen."""
    def __init__(self, host: AppHost, paths: list[Path]):
        super().__init__(host.root)
        self.host = host
        self.paths = list(dict.fromkeys(paths))
        self.title("DocForge — быстрое преобразование")
        self.out: Path | None = None
        self.busy = False
        self.target_buttons: list[str] = []
        self.targets = common_targets(self.paths)
        self.width = 472
        self.height = max(318, 278 + 48 * ((len(self.targets) + 3) // 4))
        self.resizable(False, False)
        # A managed window can be covered, minimized and switched via Alt+Tab.
        # override-redirect was forcing the glass panel above other apps on XWayland.
        self.bind("<Escape>", lambda event: self._close())
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.lift()
        self.focus_force()

    def _build(self):
        self.configure(bg=BG)
        self.geometry(on_primary(self.host.root, self.width, self.height))
        self.attributes("-topmost", CURRENT_SETTINGS["always_on_top"])
        try:
            self.attributes("-alpha", CURRENT_SETTINGS["opacity"])
        except tk.TclError:
            pass
        if hasattr(self, "canvas"):
            self.canvas.destroy()
        self.canvas = tk.Canvas(self, width=self.width, height=self.height, bg=BG,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self._glass_image = ImageTk.PhotoImage(glass_panel(self.width, self.height,
                                        CURRENT_SETTINGS["theme"], BLUE))
        self.canvas.create_image(0, 0, anchor="nw", image=self._glass_image)
        c = self.canvas
        c.create_text(31, 39, text="◈  DOCFORGE", anchor="w",
                      fill=BLUE, font=("DejaVu Sans", 11, "bold"))
        c.create_text(31, 82, text="Выберите формат", anchor="w", fill=FG,
                      font=("DejaVu Sans", 23, "bold"))
        name = self.paths[0].name if len(self.paths) == 1 else f"Выбрано файлов: {len(self.paths)}"
        if len(name) > 55:
            name = name[:51] + "…"
        c.create_text(32, 116, text=name, anchor="w", fill=MUTED,
                      font=("DejaVu Sans", 10))
        c.create_line(30, 143, self.width - 30, 143, fill=LINE, width=1)
        c.create_text(self.width - 27, 33, text="×", fill=MUTED,
                      font=("DejaVu Sans", 18), tags=("close",))
        c.tag_bind("close", "<Button-1>", lambda event: self._close())
        self.target_buttons.clear()
        if not self.targets:
            c.create_text(30, 176, text="Нет подходящих форматов. Проверьте компоненты.",
                          anchor="w", fill=ERROR, font=("DejaVu Sans", 10))
        for n, target in enumerate(self.targets):
            x, y = 30 + (n % 4) * 104, 160 + (n // 4) * 47
            tag = f"target_{n}"
            _glass_button(c, x, y, 96, 36, target.upper(),
                          lambda fmt=target: self._start(fmt), tag=tag)
            self.target_buttons.append(tag)
        self.status_id = c.create_text(31, self.height - 83,
                                       text="Готовый файл появится рядом с исходным.",
                                       anchor="w", fill=MUTED, width=self.width - 55,
                                       font=("DejaVu Sans", 9))
        _glass_button(c, self.width - 142, self.height - 53, 111, 34, "Закрыть", self._close, tag="close_btn")
        _glass_button(c, 30, self.height - 53, 151, 34, "Открыть папку",
                      lambda: open_directory(self.out) if self.out else None,
                      tag="open_folder")
        c.tag_bind("header", "<ButtonPress-1>", self._start_drag)
        # Move with the top area; close button is excluded.
        c.bind("<ButtonPress-1>", self._start_drag)
        c.bind("<B1-Motion>", self._move)
        self._drag_offset = None

    def _start_drag(self, event):
        self._drag_offset = (event.x_root - self.winfo_x(), event.y_root - self.winfo_y()) if event.y < 62 and event.x < self.width - 65 else None

    def _move(self, event):
        if self._drag_offset:
            x, y = clamp_primary(self.host.root, event.x_root - self._drag_offset[0],
                                 event.y_root - self._drag_offset[1], self.width, self.height)
            self.geometry(f"+{x}+{y}")

    def apply_settings(self):
        if not self.busy:
            self._build()

    def _close(self):
        host_root = self.host.root
        others = [w for w in host_root.winfo_children() if isinstance(w, tk.Toplevel)
                  and w is not self and w.winfo_exists()]
        self.destroy()
        if not others and host_root.state() == "withdrawn":
            host_root.destroy()

    def _start(self, target: str):
        if self.busy:
            return
        self.busy = True
        self.canvas.itemconfigure(self.status_id, text="Преобразование…", fill=MUTED)
        def job():
            return [convert(path, target) for path in self.paths]
        def success(files):
            self.busy = False
            self.out = files[-1]
            self.canvas.itemconfigure(self.status_id,
                                      text=f"Готово: {len(files)} шт. · {files[-1].name}", fill=GREEN)
        def failure(error):
            self.busy = False
            self.canvas.itemconfigure(self.status_id, text=f"Ошибка: {error}"[:310], fill=ERROR)
        self.host.submit(job, success, failure)


class DropZone(tk.Toplevel):
    """Frameless glass hub. Targets grow 9% on hover with a damped spring.

    X11 optional shape makes transparent outside pixels noninteractive. Under
    Wayland, the compositor controls how a frameless XWayland window behaves.
    """
    def __init__(self, host: AppHost, *, temporary: bool = False):
        super().__init__(host.root)
        self.host = host
        self.temporary = temporary
        self.title("DocForge — зона преобразования")
        self.resizable(False, False)
        # Keep normal window-manager stacking (not permanently above apps).
        # Motif hints suppress the title bar on Mutter/Openbox/XWayland X11.
        # If the compositor ignores this hint, a title bar may remain.
        self.withdraw()
        self._borderless = False
        self.attributes("-topmost", CURRENT_SETTINGS["always_on_top"])
        self._expanded = False
        self._progress = 0.0
        self._hovered: int | None = None
        self._scales: list[float] = []
        self._velocities: list[float] = []
        self._actions: list[Action] = []
        self._paths: list[Path] = []
        self._dragging_file = False
        self._mouse: tuple[int, int] | None = None
        self._moved = False
        self._busy = False
        self._status = ""
        self._tick_job: str | None = None
        self._leave_job: str | None = None
        self._shape_frame = 0
        self._image = None
        self._context = tk.Menu(self, tearoff=False)
        self._context.add_command(label="Выбрать файл…", command=self.open_file)
        self._context.add_command(label="Настройки оформления…", command=self._settings)
        self._context.add_separator()
        self._context.add_command(label="Закрыть зону", command=self._close)
        self.configure(bg="#F7F2EE")
        self.drop = tk.Canvas(self, bg="#F7F2EE", bd=0, highlightthickness=0, cursor="hand2")
        self.drop.pack(fill="both", expand=True)
        self.drop.bind("<ButtonPress-1>", self._start_drag)
        self.drop.bind("<B1-Motion>", self._move)
        self.drop.bind("<ButtonRelease-1>", self._release)
        self.drop.bind("<Motion>", self._mouse_motion)
        self.drop.bind("<Leave>", self._mouse_leave)
        self.drop.bind("<Button-3>", self._popup)
        self.drop.bind("<Escape>", lambda event: self._collapse())
        self.bind("<Escape>", lambda event: self._collapse())
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._position_initial()
        self.update_idletasks()
        from .xshape import request_borderless_managed_window
        self._borderless = request_borderless_managed_window(self)
        self.deiconify()
        self._paint()
        if DND_ENABLED:
            for target in (self.drop, self):
                if not hasattr(target, "drop_target_register"):
                    continue
                try:
                    target.drop_target_register(DND_FILES)
                    target.dnd_bind("<<DropEnter>>", self._on_enter)
                    target.dnd_bind("<<DropPosition>>", self._on_position)
                    target.dnd_bind("<<DropLeave>>", self._on_leave)
                    target.dnd_bind("<<Drop>>", self._on_drop)
                except (tk.TclError, AttributeError):
                    pass
        self.bind("<Destroy>", self._destroy_event, add="+")

    def _position_initial(self):
        from .appearance import primary_monitor
        px, py, pw, ph = primary_monitor(self.host.root)
        w, h = SIZES[CURRENT_SETTINGS["zone_size"]]
        # Leave room for the petals to open to the left and right, without
        # relocating the central drop target when an external drag begins.
        cx = px + min(max(370, pw - 345), max(0, pw - 370)) if pw >= 740 else px + pw // 2
        cy = py + min(max(330, ph // 2), ph - 340) if ph >= 700 else py + ph // 2
        cx = max(px + w // 2, min(cx, px + pw - w // 2))
        cy = max(py + h // 2, min(cy, py + ph - h // 2))
        self._center = (int(cx), int(cy))
        self._resize(False)

    def _bounds(self, expanded: bool):
        standard = SIZES[CURRENT_SETTINGS["zone_size"]][0] / SIZES["standard"][0]
        if expanded:
            return round(BASE_W * standard), round(BASE_H * standard)
        return SIZES[CURRENT_SETTINGS["zone_size"]]

    def _resize(self, expanded: bool):
        from .appearance import primary_monitor
        w, h = self._bounds(expanded)
        px, py, pw, ph = primary_monitor(self.host.root)
        cx, cy = self._center
        if expanded:
            # If display is too small, leave some margin at the edges.
            if w > pw - 6 or h > ph - 6:
                sf = min((pw-6)/w, (ph-6)/h)
                w, h = round(w*sf), round(h*sf)
            cx = max(px + w//2, min(cx, px + pw - w//2))
            cy = max(py + h//2, min(cy, py + ph - h//2))
        x, y = round(cx - w/2), round(cy - h/2)
        self._center = (cx, cy)
        self.width, self.height = w, h
        self.geometry(f"{w}x{h}{x:+d}{y:+d}")
        self.drop.configure(width=w, height=h)
        try:
            self.attributes("-alpha", CURRENT_SETTINGS["opacity"])
        except tk.TclError:
            pass

    def _paint(self):
        from .petals import render_zone
        from .xshape import set_window_shape
        style = CURRENT_SETTINGS.get("zone_style", "fuzzy")
        image = render_zone(self.width, self.height, style=style, accent=BLUE,
                            actions=tuple(self._actions) if self._expanded or self._progress > .005 else (),
                            progress=self._progress,
                            magnifications=tuple(self._scales), selected=self._hovered,
                            status=self._status)
        photo = ImageTk.PhotoImage(image)
        self._image = photo
        if not hasattr(self, "_canvas_image"):
            self._canvas_image = self.drop.create_image(0, 0, image=photo, anchor="nw")
        else:
            self.drop.itemconfigure(self._canvas_image, image=photo)
        self._shape_frame += 1
        # Set shape on first render and every ~3 frames; all gaps between petals
        # remain click-through on X11, unlike a giant invisible full-size canvas.
        if self._shape_frame % 3 == 1 or self._progress in (0.0,1.0):
            self.update_idletasks()
            set_window_shape(self, image, threshold=12)

    def _tick(self):
        self._tick_job = None
        if not self.winfo_exists():
            return
        changed = False
        goal = 1.0 if self._expanded else 0.0
        if CURRENT_SETTINGS.get("petal_animation", True):
            next_progress = self._progress + (goal - self._progress)*0.26
            if abs(next_progress - goal) < 0.012:
                next_progress = goal
        else:
            next_progress = goal
        if next_progress != self._progress:
            self._progress = next_progress
            changed = True
        for i in range(len(self._scales)):
            target = 1.09 if self._hovered == i else 1.0
            if not CURRENT_SETTINGS.get("petal_animation", True):
                updated, velocity = target, 0.0
            else:
                from .petals import spring_step
                updated, velocity = spring_step(self._scales[i], self._velocities[i], target,
                                                CURRENT_SETTINGS.get("bounce", 1.0))
            if self._scales[i] != updated:
                self._scales[i] = updated
                changed = True
            self._velocities[i] = velocity
        if changed:
            self._paint()
        if abs(self._progress-goal) > .005 or any(abs(v-(1.09 if i == self._hovered else 1)) > .002
                    for i,v in enumerate(self._scales)) or any(abs(v) > .002 for v in self._velocities):
            self._tick_job = self.after(33,self._tick)
        elif not self._expanded and self.width != self._bounds(False)[0]:
            self._actions = []
            self._scales = []
            self._velocities = []
            self._resize(False)
            self._paint()

    def _schedule_tick(self):
        if self._tick_job is None and self.winfo_exists():
            self._tick_job = self.after(20,self._tick)

    def _show_petals(self, paths: list[Path] | None = None):
        if self._busy:
            return
        if self._leave_job:
            self.after_cancel(self._leave_job)
            self._leave_job = None
        if paths:
            self._paths = paths
            self._actions = actions_for(paths)
        else:
            # TkDnD explicitly does not expose file paths in <<DropEnter>>.
            # Generic petals appear while hovering; validate after <<Drop>>.
            self._actions = [Action(fmt, fmt) for fmt in ("pdf", "docx", "md", "png", "jpg", "txt", "html", "odt")]
        if not self._actions:
            return
        if not self._expanded:
            self._expanded = True
            self._scales = [1.0 for _ in self._actions]
            self._velocities = [0.0 for _ in self._actions]
            self._progress = 0.0
            self._resize(True)
            self._paint()
        elif len(self._scales) != len(self._actions):
            self._scales = [1.0 for _ in self._actions]
            self._velocities = [0.0 for _ in self._actions]
            self._paint()
        self._schedule_tick()

    def _collapse(self):
        if self._busy:
            return
        self._expanded = False
        self._hovered = None
        self._dragging_file = False
        self._paths = []
        self._status = ""
        self._schedule_tick()

    def _coords(self,event):
        if hasattr(event,"x_root") and hasattr(event,"y_root"):
            return event.x_root-self.winfo_rootx(), event.y_root-self.winfo_rooty()
        return event.x,event.y

    def _update_hover(self,event):
        from .petals import hit_test
        if not self._expanded:
            return
        x,y = self._coords(event)
        index = hit_test(x,y,len(self._actions),self.width,self.height,
                         scale=min(self.width/BASE_W,self.height/BASE_H),magnifications=self._scales)
        if index != self._hovered:
            self._hovered = index
            self._schedule_tick()
        if index is not None:
            self.drop.configure(cursor="hand2")
        else:
            self.drop.configure(cursor="plus")

    def _on_enter(self,event):
        self._dragging_file = True
        self._show_petals(dropped_paths(self,event))
        self._update_hover(event)
        return "copy"

    def _on_position(self,event):
        self._dragging_file = True
        if not self._expanded:
            self._show_petals(dropped_paths(self,event))
        if self._leave_job:
            self.after_cancel(self._leave_job)
            self._leave_job = None
        self._update_hover(event)
        return "copy"

    def _on_leave(self,event):
        # Resizing X11 drop surfaces can emit a short spurious Leave. Delay the
        # collapse so the drag can continue across the newly expanded petals.
        if self._leave_job:
            self.after_cancel(self._leave_job)
        self._leave_job = self.after(550,self._collapse)
        return "copy"

    def _on_drop(self,event):
        if self._leave_job:
            self.after_cancel(self._leave_job)
            self._leave_job = None
        paths = dropped_paths(self,event)
        self._dragging_file = False
        if not paths:
            self._status = "Файл не распознан"
            self._paint()
            self.after(1100,self._collapse)
            return "copy"
        self._paths = paths
        self._drop_or_choose(paths,event)
        return "copy"

    def _drop_or_choose(self,paths,event):
        from .petals import hit_test
        x,y = self._coords(event)
        idx = hit_test(x,y,len(self._actions),self.width,self.height,
                       scale=min(self.width/BASE_W,self.height/BASE_H),magnifications=self._scales) if self._expanded else None
        picked = self._actions[idx] if idx is not None else None
        allowed = actions_for(paths)
        if picked is not None:
            valid = next((a for a in allowed if a.key == picked.key and a.operation == picked.operation),None)
            if valid:
                self._paths = paths
                self._actions = allowed
                self._run_action(valid)
                return
        # File can be dropped into central bubble, or an unsupported generic
        # target: update petals with actual formats so users can click one.
        self._show_petals(paths)
        self._status = "Выберите формат"
        self._paint()

    def _run_action(self,action: Action):
        if self._busy or not self._paths:
            return
        paths = list(self._paths)
        self._busy = True
        self._status = "Преобразование…"
        self._hovered = None
        self._paint()
        def job():
            if action.operation == 'edit':
                import sys
                command = ([sys.executable] if getattr(sys, 'frozen', False)
                           else [sys.executable, '-m', 'docforge'])
                subprocess.Popen(command + ['edit', str(paths[0])],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return [paths[0]]
            if action.operation == "convert":
                return [convert(path, action.target) for path in paths]
            if action.operation == "split":
                return [split_pdf(p,"all") for p in paths]
            if action.operation == "compress":
                return [compress_pdf(p,"ebook") for p in paths]
            if action.operation == "merge":
                return [merge_pdfs(paths)]
            if action.operation == "rotate":
                return [rotate_pdf(p,90) for p in paths]
            raise ConversionError("Неподдерживаемая операция")
        def success(outputs):
            self._busy = False
            self._last_output = outputs[-1]
            self._status = "Готово ✓"
            self._paint()
            if self.temporary:
                self.after(1300,self._close)
            else:
                self.after(1750,self._collapse)
        def failure(error):
            self._busy = False
            self._status = "Ошибка преобразования"
            self._paint()
            messagebox.showerror("DocForge",error,parent=self)
            self._collapse()
        self.host.submit(job,success,failure)

    def _start_drag(self,event):
        self._mouse = (event.x_root-self.winfo_x(), event.y_root-self.winfo_y())
        self._moved = False

    def _move(self,event):
        if self._mouse and not self._dragging_file:
            self._moved = True
            x,y = event.x_root-self._mouse[0],event.y_root-self._mouse[1]
            from .appearance import clamp_primary
            x,y = clamp_primary(self.host.root,x,y,self.width,self.height)
            self.geometry(f"+{x}+{y}")
            self._center = (x+self.width//2,y+self.height//2)

    def _release(self,event):
        self._mouse = None
        if self._moved or self._dragging_file:
            return
        if self._expanded and self._paths:
            from .petals import hit_test
            idx = hit_test(event.x,event.y,len(self._actions),self.width,self.height,
                           scale=min(self.width/BASE_W,self.height/BASE_H),magnifications=self._scales)
            if idx is not None:
                self._run_action(self._actions[idx])
                return
            # Clicking the central bubble closes the petals again.
            self._collapse()
        elif not self._expanded:
            self.open_file()

    def _mouse_motion(self,event):
        if self._expanded and not self._dragging_file:
            self._update_hover(event)

    def _mouse_leave(self,event):
        if not self._dragging_file and self._expanded and not self._busy and not self._paths:
            if self._leave_job:
                self.after_cancel(self._leave_job)
            self._leave_job = self.after(1200,self._collapse)

    def open_file(self):
        if self._busy:
            return
        files = filedialog.askopenfilenames(parent=self, title="Выберите документы")
        if files:
            self._show_petals([Path(p) for p in files])

    def _popup(self,event):
        try:
            self._context.tk_popup(event.x_root,event.y_root)
        finally:
            self._context.grab_release()

    def _settings(self):
        SettingsDialog(self,lambda: refresh_appearance(self.host.root))

    def apply_settings(self):
        self.attributes("-topmost", CURRENT_SETTINGS["always_on_top"])
        self._resize(self._expanded)
        self._paint()

    def _destroy_event(self,event):
        if event.widget is self:
            if self._tick_job:
                try: self.after_cancel(self._tick_job)
                except tk.TclError: pass
                self._tick_job = None

    def _close(self):
        parent = self.host.root
        others = [w for w in parent.winfo_children() if isinstance(w,tk.Toplevel)
                  and w is not self and w.winfo_exists()]
        self.destroy()
        if not others and parent.state() == "withdrawn":
            parent.destroy()


class SettingsDialog(tk.Toplevel):
    """Graphical appearance editor; changes are previewed and saved in XDG config."""
    def __init__(self, master: tk.Tk, on_apply: Callable):
        super().__init__(master)
        self.title("DocForge · Настройка внешнего вида")
        self.geometry(on_primary(master, 760, 680))
        self.minsize(700, 570)
        self.configure(bg=BG)
        self.transient(master)
        self.on_apply = on_apply
        self.grab_set()
        self.values = load_settings()
        self.theme_var = tk.StringVar(value=self.values["theme"])
        self.accent_var = tk.StringVar(value=self.values["accent"])
        self.opacity_var = tk.IntVar(value=round(self.values["opacity"] * 100))
        self.size_var = tk.StringVar(value=self.values["zone_size"])
        self.scale_var = tk.StringVar(value=str(int(self.values["scale"] * 100)))
        self.top_var = tk.BooleanVar(value=self.values["always_on_top"])
        self.zone_style_var = tk.StringVar(value=self.values["zone_style"])
        self.petal_var = tk.BooleanVar(value=self.values["petal_animation"])
        self.animation_style_var = tk.StringVar(value=self.values["animation_style"])
        self.reveal_ms_var = tk.IntVar(value=self.values["reveal_ms"])
        self.bounce_var = tk.IntVar(value=round(self.values["bounce"] * 100))
        self.refraction_var = tk.IntVar(value=round(self.values["refraction"] * 100))
        self.hover_scale_var = tk.IntVar(value=round(self.values["hover_scale"] * 100))
        self._preview_image = None
        self._build()
        self._preview()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _build(self):
        holder = tk.Frame(self, bg=BG, padx=31, pady=18)
        holder.pack(fill="both", expand=True)
        info_label(holder, "Внешний вид", color=FG, size=22, weight="bold").pack(anchor="w")
        info_label(holder, "Настройте интерфейс и плавающую зону под свой рабочий стол.",
                   size=10).pack(anchor="w", pady=(4, 11))
        # Reserve the footer first so action buttons stay visible on short screens.
        bar = tk.Frame(holder, bg=BG)
        bar.pack(side="bottom", fill="x", pady=(12, 0))
        # Scrollable preferences; on 720p laptop screens the Save button stays
        # visible instead of falling below the bottom edge of the display.
        scroll = tk.Frame(holder, bg=BG)
        scroll.pack(fill="both", expand=True)
        scrollbar = tk.Scrollbar(scroll, orient="vertical")
        scrollbar.pack(side="right", fill="y")
        canvas = tk.Canvas(scroll, bg=BG, bd=0, highlightthickness=0,
                           yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=canvas.yview)
        layout = tk.Frame(canvas, bg=BG)
        window_id = canvas.create_window((0,0), window=layout, anchor="nw")
        layout.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window_id, width=e.width))
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta/120), "units"))
        controls = tk.Frame(layout, bg=BG)
        controls.pack(side="left", fill="both", expand=True, padx=(0, 20))
        right = tk.Frame(layout, bg=PANEL, highlightthickness=1, highlightbackground=LINE)
        right.pack(side="right", fill="y")
        right.configure(width=264)
        right.pack_propagate(False)
        info_label(controls, "СТИЛЬ ОКНА", size=9, weight="bold").pack(anchor="w", pady=(0, 8))
        theme_combo = ttk.Combobox(controls, state="readonly", width=30,
                                   values=list(THEMES.values()))
        self.theme_combo = theme_combo
        theme_combo.pack(fill="x", pady=(0, 13))
        theme_combo.set(THEMES[self.theme_var.get()])
        def set_theme(event=None):
            self.theme_var.set(next(key for key, value in THEMES.items() if value == theme_combo.get()))
            self._preview()
        theme_combo.bind("<<ComboboxSelected>>", set_theme)

        info_label(controls, "ЦВЕТ АКЦЕНТА", size=9, weight="bold").pack(anchor="w", pady=(0, 8))
        chips = tk.Frame(controls, bg=BG)
        chips.pack(anchor="w", pady=(0, 11))
        self.chips = {}
        for name, (description, color) in ACCENTS.items():
            btn = tk.Button(chips, text="●", bg=BG, fg=color, activeforeground=color,
                            activebackground=BG, bd=0, relief="flat", cursor="hand2",
                            font=("DejaVu Sans", 17), command=lambda n=name: self._set_accent(n))
            btn.pack(side="left", padx=(0, 4))
            self.chips[name] = btn

        info_label(controls, "ПРОЗРАЧНОСТЬ ОКНА", size=9, weight="bold").pack(anchor="w")
        opacity_row = tk.Frame(controls, bg=BG)
        opacity_row.pack(fill="x", pady=(4, 9))
        self.opacity_scale = tk.Scale(opacity_row, from_=10, to=98, orient="horizontal",
                showvalue=False, bg=BG, fg=FG, activebackground=BLUE, troughcolor=PANEL2,
                bd=0, highlightthickness=0, variable=self.opacity_var,
                command=lambda unused: self._preview())
        self.opacity_scale.pack(side="left", fill="x", expand=True)
        self.opacity_label = info_label(opacity_row, "93%", color=FG)
        self.opacity_label.pack(side="right", padx=(5, 0))

        info_label(controls, "СТИЛЬ ПЛАВАЮЩЕГО СТЕКЛА", size=9, weight="bold").pack(anchor="w", pady=(0, 5))
        zone_style_combo = ttk.Combobox(controls, state="readonly", width=27,
                                        values=list(ZONE_STYLES.values()))
        self.zone_style_combo = zone_style_combo
        zone_style_combo.pack(fill="x", pady=(0, 8))
        zone_style_combo.set(ZONE_STYLES[self.zone_style_var.get()])
        def set_zone_style(event=None):
            self.zone_style_var.set(next(key for key, value in ZONE_STYLES.items()
                                         if value == zone_style_combo.get()))
            self._preview()
        zone_style_combo.bind("<<ComboboxSelected>>", set_zone_style)
        tk.Checkbutton(controls, text="Плавное раскрытие и увеличение лепестков",
                       variable=self.petal_var, command=self._preview,
                       bg=BG, fg=FG, activebackground=BG, activeforeground=FG,
                       selectcolor=PANEL2, font=("DejaVu Sans", 9)).pack(anchor="w", pady=(0, 4))
        info_label(controls, "СТИЛЬ АНИМАЦИИ", size=9, weight="bold").pack(anchor="w", pady=(4, 3))
        style_combo = ttk.Combobox(controls, state="readonly", width=27,
                                   values=list(ANIMATION_STYLES.values()))
        self.animation_style_combo = style_combo
        style_combo.set(ANIMATION_STYLES[self.animation_style_var.get()])
        style_combo.pack(fill="x", pady=(0, 7))
        style_combo.bind("<<ComboboxSelected>>", lambda _e: (
            self.animation_style_var.set(next(k for k, v in ANIMATION_STYLES.items()
                                              if v == style_combo.get())), self._preview()))
        info_label(controls, "ВРЕМЯ РАСКРЫТИЯ (МС)", size=9, weight="bold").pack(anchor="w")
        duration_row = tk.Frame(controls, bg=BG)
        duration_row.pack(fill="x", pady=(2, 8))
        tk.Scale(duration_row, from_=250, to=800, resolution=25, orient="horizontal",
                 showvalue=False, bg=BG, fg=FG, activebackground=BLUE,
                 troughcolor=PANEL2, bd=0, highlightthickness=0,
                 variable=self.reveal_ms_var,
                 command=lambda _value: self._preview()).pack(side="left", fill="x", expand=True)
        self.reveal_label = info_label(duration_row, "450 мс", color=FG)
        self.reveal_label.pack(side="right", padx=(5, 0))
        info_label(controls, "УПРУГОСТЬ И ОТСКОК ЛЕПЕСТКОВ", size=9, weight="bold").pack(anchor="w")
        bounce_row = tk.Frame(controls, bg=BG)
        bounce_row.pack(fill="x", pady=(2, 8))
        tk.Scale(bounce_row, from_=0, to=160, orient="horizontal", showvalue=False,
                 bg=BG, fg=FG, activebackground=BLUE, troughcolor=PANEL2,
                 bd=0, highlightthickness=0, variable=self.bounce_var,
                 command=lambda _unused: self._preview()).pack(side="left", fill="x", expand=True)
        self.bounce_label = info_label(bounce_row, "100%", color=FG)
        self.bounce_label.pack(side="right", padx=(5, 0))

        info_label(controls, "ПРЕЛОМЛЕНИЕ КРОМКИ СТЕКЛА", size=9, weight="bold").pack(anchor="w")
        tk.Scale(controls, from_=0, to=100, orient="horizontal", showvalue=True,
                 variable=self.refraction_var, bg=BG, fg=FG, troughcolor=PANEL2,
                 bd=0, highlightthickness=0, command=lambda _unused: self._preview()).pack(fill="x")
        info_label(controls, "УВЕЛИЧЕНИЕ ЛЕПЕСТКА ПРИ НАВЕДЕНИИ", size=9,
                   weight="bold").pack(anchor="w")
        tk.Scale(controls, from_=5, to=16, orient="horizontal", showvalue=True,
                 variable=self.hover_scale_var, bg=BG, fg=FG, troughcolor=PANEL2,
                 bd=0, highlightthickness=0, command=lambda _unused: self._preview()).pack(fill="x")
        info_label(controls, "РАЗМЕР ПЛАВАЮЩЕЙ ЗОНЫ", size=9, weight="bold").pack(anchor="w", pady=(0, 8))
        self.size_combo = ttk.Combobox(controls, state="readonly", width=20,
                                       values=["Компактный", "Обычный", "Большой"])
        self.size_combo.pack(fill="x", pady=(0, 12))
        size_labels = {"compact": "Компактный", "standard": "Обычный", "large": "Большой"}
        self.size_combo.set(size_labels[self.size_var.get()])
        self.size_combo.bind("<<ComboboxSelected>>", lambda unused: (
            self.size_var.set(next(k for k, v in size_labels.items() if v == self.size_combo.get())), self._preview()))

        info_label(controls, "МАСШТАБ ГЛАВНОГО ОКНА", size=9, weight="bold").pack(anchor="w", pady=(0, 8))
        scale_combo = ttk.Combobox(controls, textvariable=self.scale_var,
                                   state="readonly", width=20, values=["80", "100", "110", "125", "150"])
        scale_combo.pack(fill="x", pady=(0, 8))
        info_label(controls, "Проценты: 100 — обычный размер", size=9).pack(anchor="w", pady=(0, 7))
        check = tk.Checkbutton(controls, text="Закреплять поверх всех окон", variable=self.top_var,
                               bg=BG, fg=FG, activebackground=BG, activeforeground=FG,
                               selectcolor=PANEL2, font=("DejaVu Sans", 10))
        check.pack(anchor="w")

        info_label(right, "ПРЕДПРОСМОТР ЗОНЫ", color=MUTED, size=9, weight="bold", bg=PANEL).pack(pady=(22, 18))
        self.preview = tk.Canvas(right, width=236, height=222, bg=PANEL,
                                  highlightthickness=0)
        self.preview.pack(padx=12)
        info_label(right, "Капсула без полосы окна.\nПравый клик — меню и закрытие.", size=9, bg=PANEL,
                   justify="center").pack(pady=14)
        info_label(right, "Эффект стекла зависит от\nкомпозитора Ubuntu / Wayland.",
                   size=8, bg=PANEL, justify="center", wraplength=205).pack(pady=(0, 12))

        hover_button(bar, "Сохранить и применить", self._save, primary=True).pack(side="right")
        hover_button(bar, "Отмена", self.destroy).pack(side="right", padx=8)
        hover_button(bar, "По умолчанию", self._reset).pack(side="left")

    def _set_accent(self, name):
        self.accent_var.set(name)
        self._preview()

    def _preview(self):
        from PIL import Image, ImageDraw, ImageFilter, ImageChops
        from .petals import render_zone
        self.opacity_label.configure(text=f"{self.opacity_var.get()}%")
        self.bounce_label.configure(text=f"{self.bounce_var.get()}%")
        self.reveal_label.configure(text=f"{self.reveal_ms_var.get()} мс")
        for name, button in self.chips.items():
            button.configure(relief="sunken" if name == self.accent_var.get() else "flat")
        self.preview.delete("all")
        accent = ACCENTS[self.accent_var.get()][1]
        # Real appearance preview over a neutral desktop surface.
        back = Image.new("RGBA", (236, 222), "#D3CFC9")
        d = ImageDraw.Draw(back)
        for y in range(222):
            color = (202+int(24*y/222), 198+int(16*y/222), 198+int(24*y/222), 255)
            d.line((0,y,236,y),fill=color)
        layer = render_zone(226, 213, style=self.zone_style_var.get(), accent=accent)
        # A larger transparency setting must expose MORE of the wallpaper.
        alpha = layer.getchannel("A").point(
            lambda value: round(value * (1.0 - self.opacity_var.get() / 115)))
        layer.putalpha(alpha)
        # Preview the optical rim strength as well as the background density.
        intensity = self.refraction_var.get() / 100
        if intensity:
            edge = ImageChops.subtract(
                alpha, alpha.filter(ImageFilter.MinFilter(7)))
            edge = edge.point(lambda value: round(value * intensity))
            highlight = Image.new("RGBA", layer.size, (218, 240, 255, 0))
            highlight.putalpha(edge)
            layer = Image.alpha_composite(layer, highlight)
        back.alpha_composite(layer, (5, 4))
        self._preview_image = ImageTk.PhotoImage(back)
        self.preview.configure(width=236, height=222)
        self.preview.create_image(0, 0, image=self._preview_image, anchor="nw")

    def _reset(self):
        self.theme_var.set(DEFAULTS["theme"])
        self.accent_var.set(DEFAULTS["accent"])
        self.opacity_var.set(round(DEFAULTS["opacity"] * 100))
        self.size_var.set(DEFAULTS["zone_size"])
        self.scale_var.set("100")
        self.top_var.set(DEFAULTS["always_on_top"])
        self.zone_style_var.set(DEFAULTS["zone_style"])
        self.petal_var.set(DEFAULTS["petal_animation"])
        self.animation_style_var.set(DEFAULTS["animation_style"])
        self.animation_style_combo.set(ANIMATION_STYLES[DEFAULTS["animation_style"]])
        self.reveal_ms_var.set(DEFAULTS["reveal_ms"])
        self.bounce_var.set(round(DEFAULTS["bounce"] * 100))
        self.refraction_var.set(round(DEFAULTS["refraction"] * 100))
        self.hover_scale_var.set(round(DEFAULTS["hover_scale"] * 100))
        self.zone_style_combo.set(ZONE_STYLES[DEFAULTS["zone_style"]])
        self.size_combo.set("Обычный")
        self.theme_combo.set(THEMES[DEFAULTS["theme"]])
        self._preview()

    def _save(self):
        settings = {
            "theme": self.theme_var.get(),
            "accent": self.accent_var.get(),
            "opacity": self.opacity_var.get() / 100,
            "scale": int(self.scale_var.get()) / 100,
            "zone_size": self.size_var.get(),
            "always_on_top": self.top_var.get(),
            "zone_style": self.zone_style_var.get(),
            "petal_animation": self.petal_var.get(),
            "animation_style": self.animation_style_var.get(),
            "reveal_ms": self.reveal_ms_var.get(),
            "bounce": self.bounce_var.get() / 100,
            "refraction": self.refraction_var.get() / 100,
            "hover_scale": self.hover_scale_var.get() / 100,
        }
        try:
            save_settings(settings)
        except OSError as exc:
            messagebox.showerror("Ошибка настроек", str(exc), parent=self)
            return
        self.grab_release()
        self.destroy()
        self.on_apply()


class MainWindow:
    def __init__(self, root: tk.Tk, initial: list[Path] | None = None):
        self.root = root
        root.docforge_main = self
        self.host = AppHost(root)
        self.paths: list[Path] = []
        self.last_output: Path | None = None
        self.busy = False
        root.title(f"DocForge {__version__} — документы и PDF")
        root.geometry(on_primary(root, 1280, 820))
        root.minsize(970, 690)
        self._build()
        if initial:
            self.add_files(initial)

    def _build(self):
        """Dark, rounded dashboard matching the standalone glass settings."""
        from .dashboard import DashboardButton, DashboardCard, dashboard_colors
        c = dashboard_colors(load_settings())
        self.dashboard_colors = c
        self.root.configure(bg=c['background'])
        def label(master, value, *, size=10, bold=False, muted=False, bg=None):
            return tk.Label(master, text=value, bg=bg or master.cget('bg'),
                            fg=c['muted'] if muted else c['text'],
                            font=('DejaVu Sans', size, 'bold' if bold else 'normal'))
        def button(master, title, command, primary=False):
            return DashboardButton(master, title, command, colors=c, primary=primary)
        style = ttk.Style(self.root)
        style.configure('Dashboard.TCombobox', padding=10, relief='flat',
                        fieldbackground=c['inset'], background=c['inset'],
                        foreground=c['text'], arrowcolor=c['text'], borderwidth=1,
                        bordercolor=c['border'], lightcolor=c['border'], darkcolor=c['inset'])
        style.map('Dashboard.TCombobox', fieldbackground=[('readonly', c['inset'])],
                  foreground=[('readonly', c['text'])])
        style.configure('Dashboard.Vertical.TScrollbar', background=c['inset'],
                        troughcolor=c['card'], borderwidth=0, arrowsize=10)

        top = tk.Frame(self.root, bg=c['background'])
        top.pack(fill='x', padx=26, pady=(24, 18))
        branding = tk.Frame(top, bg=c['background'])
        branding.pack(side='left', fill='y')
        label(branding, '◆  DocForge', size=22, bold=True).pack(anchor='w')
        label(branding, 'Локально · без загрузки документов', size=9, muted=True).pack(anchor='w')
        button(top, 'Зона на экране', self.show_zone).pack(side='right', padx=(9, 0))
        button(top, '⚙  Оформление', self.open_settings).pack(side='right')

        # Always-visible workspace navigation, rather than hiding features in a menu.
        navigation = tk.Frame(self.root, bg=c['background'])
        navigation.pack(fill='x', padx=26, pady=(0, 12))
        for title, handler in [
            ('Главная', lambda: self.drop_label.focus_set()),
            ('Конвертация', lambda: self.combo.focus_set()),
            ('Редактор PDF', self.edit_pdf),
            ('Инструменты', lambda: self.status.configure(text='Инструменты PDF — справа')),
            ('Настройки', self.open_settings),
        ]:
            nav_btn = tk.Button(navigation, text=title, command=handler,
                                bg=c['inset'] if title == 'Главная' else c['card'],
                                fg=c['text'], activebackground=c['inset'],
                                activeforeground=c['text'], bd=0, relief='flat',
                                padx=17, pady=7, cursor='hand2',
                                font=('DejaVu Sans', 10, 'bold' if title == 'Главная' else 'normal'))
            nav_btn.pack(side='left', padx=(0, 7))

        middle = tk.Frame(self.root, bg=c['background'])
        middle.pack(fill='both', expand=True, padx=26)
        sidebar_card = DashboardCard(middle, colors=c, width=200)
        sidebar_card.pack(side='left', fill='y', padx=(0, 12))
        sidebar_card.pack_propagate(False)
        sidebar = sidebar_card.inner
        label(sidebar, 'ФАЙЛЫ', muted=True, bold=True).pack(anchor='w', padx=5, pady=(13, 12))
        button(sidebar, '+ Открыть файл', self.browse).pack(fill='x', padx=4, pady=3)
        label(sidebar, 'БЫСТРЫЕ ДЕЙСТВИЯ', muted=True, bold=True, size=9).pack(anchor='w', padx=5, pady=(19, 9))
        button(sidebar, 'Редактор PDF', self.edit_pdf).pack(fill='x', padx=4, pady=3)
        button(sidebar, 'Конвертировать', lambda: self.combo.focus_set()).pack(fill='x', padx=4, pady=3)
        button(sidebar, 'Проверить MD', self.check_md_links).pack(fill='x', padx=4, pady=3)
        label(sidebar, 'ПОСЛЕДНИЕ', muted=True, bold=True, size=9).pack(anchor='w', padx=5, pady=(18, 9))
        self.recent_list = tk.Listbox(sidebar, bg=c['card'], fg=c['muted'], bd=0, relief='flat',
                                      highlightthickness=0, selectbackground=c['inset'],
                                      selectforeground=c['text'], activestyle='none',
                                      font=('DejaVu Sans', 9), cursor='hand2')
        self.recent_list.pack(fill='both', expand=True, padx=4, pady=(0, 10))
        self._refresh_recent()
        self.recent_list.bind('<Double-1>', self._open_recent)
        left_card = DashboardCard(middle, colors=c)
        left_card.pack(side='left', fill='both', expand=True, padx=(0, 13))
        left = left_card.inner
        main_hint = ('↓\nПеретащите файлы сюда\nили нажмите для выбора' if DND_ENABLED
                     else '↓\nНажмите для выбора файлов\n(для Drag & Drop нужен tkinterdnd2)')
        self.drop_label = tk.Label(left, text=main_hint, bg=c['inset'], fg=c['text'],
                                   font=('DejaVu Sans', 10), pady=6, cursor='hand2',
                                   highlightbackground=c['border'], highlightthickness=1)
        self.drop_label.pack(fill='x', padx=10, pady=(10, 12))
        self.drop_label.bind('<Button-1>', lambda e: self.browse())
        bind_drop(self.drop_label, self._on_drop)
        bind_drop(left, self._on_drop)
        files_header = tk.Frame(left, bg=c['card'])
        files_header.pack(fill='x', padx=12, pady=(0, 12))
        label(files_header, 'Файлы', bold=True, size=12).pack(side='left')
        button(files_header, 'Очистить', self.clear).pack(side='right')
        listframe = tk.Frame(left, bg=c['card'])
        listframe.pack(fill='x', padx=12, pady=(0, 10))
        listframe.configure(height=85)
        listframe.pack_propagate(False)
        self.filelist = tk.Listbox(listframe, bg=c['card'], fg=c['text'],
                                   selectbackground=c['inset'], selectforeground='white',
                                   activestyle='none', relief='flat', bd=0, highlightthickness=0,
                                   font=('DejaVu Sans', 10), selectmode='extended')
        self.filelist.pack(side='left', fill='both', expand=True)
        bar = ttk.Scrollbar(listframe, style='Dashboard.Vertical.TScrollbar', command=self.filelist.yview)
        bar.pack(side='right', fill='y')
        self.filelist.configure(yscrollcommand=bar.set)
        self.filelist.bind('<Delete>', lambda e: self.remove_selected())
        self.filelist.bind('<BackSpace>', lambda e: self.remove_selected())
        bind_drop(self.filelist, self._on_drop)
        self.filelist.bind('<<ListboxSelect>>', lambda _e: self._preview_selected_pdf())
        preview_header = tk.Frame(left, bg=c['card'])
        preview_header.pack(fill='x', padx=12, pady=(0,6))
        label(preview_header,'ПРЕДПРОСМОТР ДОКУМЕНТА',muted=True,bold=True,size=9).pack(side='left')
        button(preview_header,'Открыть редактор',self.edit_pdf).pack(side='right')
        self.preview_canvas = tk.Canvas(left, bg='#19273d', bd=0, highlightthickness=0)
        self.preview_canvas.pack(fill='both', expand=True, padx=12, pady=(0,12))
        self._preview_image = None
        self._preview_cache = None
        self.preview_canvas.bind('<Configure>', lambda _e:self.root.after_idle(self._preview_selected_pdf))
        self.preview_canvas.bind('<Double-1>', lambda _e:self.edit_pdf())
        self._preview_selected_pdf()

        right_card = DashboardCard(middle, colors=c, width=329)
        right_card.pack(side='right', fill='y')
        right_card.pack_propagate(False)
        right = right_card.inner
        label(right, 'КОНВЕРТАЦИЯ', muted=True, bold=True, size=10).pack(anchor='w', padx=12, pady=(12, 14))
        label(right, 'Выходной формат', size=11).pack(anchor='w', padx=12)
        self.format_var = tk.StringVar()
        self.combo = ttk.Combobox(right, state='readonly', textvariable=self.format_var,
                                   style='Dashboard.TCombobox', width=23)
        self.combo.pack(fill='x', padx=12, pady=(8, 15))
        self.convert_btn = button(right, 'Преобразовать', self.convert_selected, True)
        self.convert_btn.pack(fill='x', padx=12, pady=(0, 17))
        tk.Frame(right, bg=c['border'], height=1).pack(fill='x', padx=12, pady=6)
        label(right, 'PDF-ИНСТРУМЕНТЫ', muted=True, bold=True, size=10).pack(anchor='w', padx=12, pady=(7, 7))
        button(right, '✎  Редактор PDF', self.edit_pdf, True).pack(fill='x', padx=12, pady=(0, 4))
        for title, op in [('Объединить PDF', 'merge'), ('Разделить на страницы', 'split'),
                          ('Повернуть страницы', 'rotate'), ('Сжать PDF', 'compress')]:
            button(right, title, lambda t=op: self.do_tool(t)).pack(fill='x', padx=12, pady=2)
        label(right, 'Для операций выберите PDF слева.', muted=True, size=9).pack(anchor='w', padx=12, pady=(14, 0))

        quickbar = tk.Frame(self.root, bg=c['background'])
        quickbar.pack(fill='x', padx=26, pady=(11, 0))
        label(quickbar, 'БЫСТРАЯ КОНВЕРТАЦИЯ', muted=True, bold=True, size=9).pack(side='left', padx=(0, 12))
        for title, color in [('PDF', '#FF7998'), ('MD', '#BE90FF'),
                             ('DOCX', '#77BDFF'), ('TXT', '#67DDC0')]:
            from PIL import ImageColor
            rgb = ImageColor.getrgb(color)
            dark = '#%02x%02x%02x' % tuple(max(0,int(v*.24)) for v in rgb)
            tk.Button(quickbar, text='  '+title+'  ', command=lambda fmt=title.lower(): self.quick_target(fmt),
                      bg=dark, fg=color, activebackground=color, activeforeground='#152a43',
                      bd=1, relief='solid', highlightthickness=1, highlightbackground=color,
                      padx=16, pady=7, cursor='hand2',
                      font=('DejaVu Sans', 10, 'bold')).pack(side='left', padx=5)
        bottom = tk.Frame(self.root, bg=c['background'])
        bottom.pack(fill='x', padx=26, pady=(10, 17))
        self.status = label(bottom, 'Готово к работе', muted=True)
        self.status.pack(side='left')
        button(bottom, 'Папка результата', self.show_last).pack(side='right', padx=(9, 0))
        button(bottom, '+  Добавить файлы', self.browse, True).pack(side='right')
        self._autostart_var = tk.BooleanVar(value=self.is_autostart())
        autostart = tk.Checkbutton(bottom, text='Зона при входе в систему',
                                  variable=self._autostart_var, command=self.toggle_autostart,
                                  bg=c['background'], fg=c['muted'], selectcolor=c['card'],
                                  activebackground=c['background'], activeforeground=c['text'],
                                  font=('DejaVu Sans', 9))
        autostart.pack(side='right', padx=8)
        self.refresh_formats()

    def _preview_selected_pdf(self) -> None:
        if not hasattr(self, 'preview_canvas') or not self.preview_canvas.winfo_exists():
            return
        canvas=self.preview_canvas
        canvas.delete('all')
        choices=self.filelist.curselection()
        candidates=([self.paths[i] for i in choices if i<len(self.paths)] if choices else self.paths)
        pdf=next((p for p in candidates if source_ext(p)=='pdf'),None)
        w,h=max(10,canvas.winfo_width()),max(10,canvas.winfo_height())
        if not pdf or w<90 or h<90:
            canvas.create_text(w/2,max(35,h/2),text='PDF · предпросмотр страниц\n\nДобавьте PDF и выделите его в списке',
                               fill='#A5BDD8',font=('DejaVu Sans',11),justify='center')
            return
        try:
            import fitz
            from PIL import Image, ImageTk
            with fitz.open(pdf) as doc:
                page=doc[0]
                scale=min((w-42)/page.rect.width,(h-36)/page.rect.height,1.25)
                if scale < .07: return
                pix=page.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False)
                image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
            self._preview_image=ImageTk.PhotoImage(image)
            cx,cy=w//2,h//2
            canvas.create_rectangle(cx-image.width//2-3,cy-image.height//2-3,
                                    cx+image.width//2+3,cy+image.height//2+3,
                                    fill='#07111f',outline='#8db8ef',width=1)
            canvas.create_image(cx,cy,image=self._preview_image)
        except Exception as exc:
            canvas.create_text(w/2,h/2,text='Предпросмотр недоступен',fill='#a7bedc')

    @staticmethod
    def _recent_file() -> Path:
        root = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config')))
        return root / 'docforge' / 'recent.json'

    def _read_recent(self) -> list[Path]:
        try:
            raw = json.loads(self._recent_file().read_text(encoding='utf-8'))
            return [Path(p) for p in raw[:20] if isinstance(p, str) and Path(p).is_file()]
        except (OSError, ValueError, TypeError):
            return []

    def _refresh_recent(self) -> None:
        self._recent_paths = self._read_recent()
        if not hasattr(self, 'recent_list'):
            return
        self.recent_list.delete(0, 'end')
        for path in self._recent_paths:
            self.recent_list.insert('end', path.name[:30])

    def _open_recent(self, _event=None) -> None:
        indices = self.recent_list.curselection()
        if indices:
            self.add_files([self._recent_paths[indices[0]]])

    def _remember_files(self, paths: list[Path]) -> None:
        remembered = list(dict.fromkeys([*paths, *self._read_recent()]))[:20]
        config = self._recent_file()
        try:
            config.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            config.write_text(json.dumps([str(p) for p in remembered], ensure_ascii=False), encoding='utf-8')
            os.chmod(config, 0o600)
        except OSError:
            pass
        self._refresh_recent()

    def check_md_links(self) -> None:
        from .md_assets import inspect_markdown
        selected = [p for p in self.paths if source_ext(p) == 'md']
        if not selected:
            name = filedialog.askopenfilename(parent=self.root, filetypes=[('Markdown', '*.md *.markdown')])
            if not name:
                return
            selected = [Path(name)]
        try:
            for path in selected:
                info = inspect_markdown(path)
                self.status.configure(text=f'{path.name}: изображений {len(info.images)}, вложений {len(info.attachments)}')
            messagebox.showinfo('DocForge · Markdown',
                                'Все локальные ресурсы доступны. Проверено файлов: ' + str(len(selected)),
                                parent=self.root)
        except (ValueError, OSError) as exc:
            messagebox.showerror('Недоступные вложения MD', str(exc), parent=self.root)

    def quick_target(self, target: str) -> None:
        if not self.paths:
            self.browse()
        if not self.paths:
            return
        if target not in common_targets(self.paths):
            messagebox.showinfo('DocForge', f'Формат {target.upper()} недоступен для выбранных файлов', parent=self.root)
            return
        self.format_var.set(target.upper())
        self.convert_selected()

    def edit_pdf(self):
        import sys
        selected = self.filelist.curselection()
        candidates = [self.paths[i] for i in selected] if selected else self.paths
        pdf = next((p for p in candidates if p.suffix.lower() == '.pdf'), None)
        if pdf is None:
            choice = filedialog.askopenfilename(parent=self.root, title='Редактировать PDF',
                                                filetypes=[('PDF', '*.pdf')])
            if not choice:
                return
            pdf = Path(choice)
        try:
            command = ([sys.executable] if getattr(sys, 'frozen', False)
                       else [sys.executable, '-m', 'docforge'])
            subprocess.Popen(command + ['edit', str(pdf)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            messagebox.showerror('DocForge', str(exc), parent=self.root)

    def show_zone(self):
        # The glass zone is now native Qt/ARGB; Tk canvas cannot produce
        # true per-pixel translucency under GNOME Wayland.
        import sys
        try:
            command = ([sys.executable] if getattr(sys, 'frozen', False)
                       else [sys.executable, '-m', 'docforge'])
            subprocess.Popen(command + ['--dropzone'],
                             start_new_session=(os.name != 'nt'), stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            self.status.config(text="Стеклянная зона открыта", fg=GREEN)
        except OSError as exc:
            messagebox.showerror("DocForge", str(exc), parent=self.root)

    def open_settings(self):
        # Keep the complete appearance editor in the same slate-glass visual
        # family as the new dashboard and the independent Qt zone settings.
        # This changes only the editor palette, not the saved user theme.
        select_appearance({**load_settings(), 'theme': 'liquid_dark'})
        SettingsDialog(self.root, lambda: refresh_appearance(self.root))

    def apply_settings(self):
        select_appearance(load_settings())
        setup_style(self.root)
        try:
            self.root.tk.call("tk", "scaling", CURRENT_SETTINGS["scale"] * 1.3)
        except tk.TclError:
            pass
        # Rebuild widgets without discarding the loaded document selection.
        for child in list(self.root.winfo_children()):
            if isinstance(child, DropZone):
                child.apply_settings()
            elif isinstance(child, QuickDialog):
                child.apply_settings()
            elif isinstance(child, tk.Toplevel):
                continue
            else:
                child.destroy()
        saved = self.paths.copy()
        self._build()
        for path in saved:
            self.filelist.insert("end", f"  {path.name}    ·    {path.suffix.upper().lstrip('.')}")
        self.refresh_formats()
        self.status.configure(text="Оформление обновлено", fg=GREEN)

    def _on_drop(self, event):
        self.add_files(dropped_paths(self.root, event))
        return "copy"

    def add_files(self, paths: list[Path]):
        invalid = []
        added = []
        bad_md_resources = []
        for raw in paths:
            p = Path(raw).expanduser().absolute()
            if not p.is_file() or source_ext(p) not in SUPPORTED:
                invalid.append(p.name)
                continue
            if p not in self.paths:
                self.paths.append(p)
                added.append(p)
                self.filelist.insert("end", f"  {p.name}    ·    {p.suffix.upper().lstrip('.')}")
                if source_ext(p) == 'md':
                    from .md_assets import inspect_markdown
                    try:
                        inspect_markdown(p)
                    except (ValueError, OSError) as exc:
                        bad_md_resources.append(f'{p.name}: {exc}')
        if added:
            self.drop_label.configure(text="↓  Добавить файлы (нажмите здесь)", pady=5)
            self._remember_files(added)
            if hasattr(self,'preview_canvas'):
                self.root.after_idle(self._preview_selected_pdf)
        self.refresh_formats()
        if bad_md_resources:
            self.status.config(text='MD: проверьте вложения перед конвертацией', fg='#ffadad')
            messagebox.showwarning('DocForge · Markdown', '\n'.join(bad_md_resources[:4]), parent=self.root)
        elif invalid:
            self.status.config(text="Пропущены неподдерживаемые файлы: " + ", ".join(invalid[:3]), fg="#ffadad")
        else:
            self.status.config(text=f"Добавлено файлов: {len(self.paths)}", fg=MUTED)

    def clear(self):
        self.paths.clear()
        self.drop_label.configure(text="↓  Перетащите файлы сюда или выберите", pady=12)
        self.filelist.delete(0, "end")
        self.refresh_formats()
        self._preview_selected_pdf()

    def remove_selected(self):
        for index in reversed(self.filelist.curselection()):
            del self.paths[index]
            self.filelist.delete(index)
        self.refresh_formats()

    def browse(self):
        paths = filedialog.askopenfilenames(title="Выберите документы")
        if paths:
            self.add_files([Path(p) for p in paths])

    def refresh_formats(self):
        targets = common_targets(self.paths)
        self.combo["values"] = [p.upper() for p in targets]
        current = self.format_var.get().lower()
        self.format_var.set(current.upper() if current in targets else (targets[0].upper() if targets else ""))
        self.convert_btn.configure(state="normal" if targets else "disabled")

    def _execute(self, label: str, work: Callable):
        if self.busy:
            return
        self.busy = True
        self.convert_btn.configure(state="disabled")
        self.status.config(text=label + "…", fg=MUTED)
        def completed(outputs):
            self.busy = False
            self.refresh_formats()
            self.last_output = outputs[-1]
            self.status.config(text=f"Готово: {len(outputs)} результат(ов). Последний: {outputs[-1].name}", fg=GREEN)
        def failed(reason):
            self.busy = False
            self.refresh_formats()
            self.status.config(text="Ошибка — проверьте сообщение", fg="#ffadad")
            messagebox.showerror("Ошибка DocForge", reason, parent=self.root)
        self.host.submit(work, completed, failed)

    def convert_selected(self):
        if not self.paths or not self.format_var.get():
            return
        items, target = self.paths.copy(), self.format_var.get().lower()
        self._execute(f"Конвертация в {target.upper()}", lambda: [convert(p, target) for p in items])

    def do_tool(self, tool: str):
        import tkinter.simpledialog as dialog
        pdfs = [p for p in self.paths if source_ext(p) == "pdf"]
        if not pdfs:
            messagebox.showinfo("Выберите PDF", "Добавьте PDF-файл в список слева.", parent=self.root)
            return
        if tool == "merge":
            if len(pdfs) < 2:
                messagebox.showinfo("Объединение", "Для объединения нужно два PDF или больше.", parent=self.root)
                return
            self._execute("Объединение PDF", lambda: [merge_pdfs(pdfs)])
        elif tool == "split":
            spec = dialog.askstring("Разделение PDF", "Страницы: all или 1,3-5", initialvalue="all", parent=self.root)
            if spec is None:
                return
            self._execute("Разделение PDF", lambda: [split_pdf(pdfs[0], spec)])
        elif tool == "rotate":
            degrees = dialog.askinteger("Поворот PDF", "Угол: 90, 180 или 270", initialvalue=90,
                                        parent=self.root, minvalue=90, maxvalue=270)
            if degrees is None:
                return
            self._execute("Поворот PDF", lambda: [rotate_pdf(p, degrees) for p in pdfs])
        elif tool == "compress":
            level = dialog.askstring("Сжатие PDF", "Качество: screen (низкое), ebook (среднее), printer (высокое)",
                                     initialvalue="ebook", parent=self.root)
            if level is None:
                return
            self._execute("Сжатие PDF", lambda: [compress_pdf(p, level.strip().lower()) for p in pdfs])

    def show_last(self):
        if self.last_output:
            open_directory(self.last_output)
        else:
            messagebox.showinfo("DocForge", "Сначала преобразуйте документ.", parent=self.root)

    @staticmethod
    def autostart_path() -> Path:
        return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "autostart" / "docforge-dropzone.desktop"

    @classmethod
    def is_autostart(cls) -> bool:
        return cls.autostart_path().is_file()

    def toggle_autostart(self):
        path = self.autostart_path()
        if self._autostart_var.get():
            path.parent.mkdir(parents=True, exist_ok=True)
            launcher = Path.home() / ".local" / "bin" / "docforge"
            path.write_text("[Desktop Entry]\nType=Application\nName=DocForge Drop Zone\n" +
                            f"Exec={launcher} --dropzone\nTerminal=false\nX-GNOME-Autostart-enabled=true\n",
                            encoding="utf-8")
            self.status.config(text="Зона добавлена в автозапуск", fg=GREEN)
        else:
            path.unlink(missing_ok=True)
            self.status.config(text="Автозапуск отключён", fg=MUTED)


def refresh_appearance(root: tk.Tk) -> None:
    """Apply visual changes to all active windows, including standalone dropzone."""
    main = getattr(root, "docforge_main", None)
    if main is not None:
        main.apply_settings()
        return
    select_appearance(load_settings())
    setup_style(root)
    try:
        from PIL import Image, ImageTk
        icon_path = (Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
                     / 'assets' / 'docforge.png')
        if icon_path.is_file():
            icon_image = ImageTk.PhotoImage(Image.open(icon_path).resize((64, 64)))
            root.iconphoto(True, icon_image)
            root._docforge_icon = icon_image  # keep Tk image alive
    except (OSError, ImportError, tk.TclError):
        pass
    try:
        root.tk.call("tk", "scaling", CURRENT_SETTINGS["scale"] * 1.3)
    except tk.TclError:
        pass
    for window in list(root.winfo_children()):
        if isinstance(window, (DropZone, QuickDialog)) and window.winfo_exists():
            window.apply_settings()


def show_gui(mode: str = "main", files: list[Path] | None = None) -> None:
    if os.name != "nt" and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        raise ConversionError("Не найдена графическая сессия. Для конвертации в терминале используйте: docforge convert --to pdf файл.md")
    try:
        root = RootClass()
    except tk.TclError as exc:
        raise ConversionError(f"Не удалось открыть графический интерфейс: {exc}") from exc
    select_appearance(load_settings())
    setup_style(root)
    if hasattr(root, 'iconphoto'):
        try:
            from PIL import Image, ImageTk
            icon_path = (Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
                         / 'assets' / 'docforge.png')
            if icon_path.is_file():
                icon_image = ImageTk.PhotoImage(Image.open(icon_path).resize((64, 64)), master=root)
                root.iconphoto(True, icon_image)
                root._docforge_icon = icon_image  # keep Tk image alive
        except (OSError, ImportError, tk.TclError, RuntimeError):
            pass
    try:
        root.tk.call("tk", "scaling", CURRENT_SETTINGS["scale"] * 1.3)
    except tk.TclError:
        pass
    if mode == "main":
        MainWindow(root, files)
    else:
        host = AppHost(root)
        root.withdraw()
        if mode in ("dropzone", "dropzone_once"):
            DropZone(host, temporary=False)
        elif mode == "quick":
            if not files:
                root.destroy()
                raise ConversionError("Нужно выбрать хотя бы один файл")
            QuickDialog(host, files)
    root.mainloop()
