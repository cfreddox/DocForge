"""Dark, rounded glass-inspired dashboard surfaces for the existing Tk UI.

Tk cannot sample the Wayland wallpaper for true backdrop blur; these cards use
subtle gradient shading rather than claiming compositor-level refraction.
"""
from __future__ import annotations

import tkinter as tk
from functools import lru_cache

from PIL import Image, ImageDraw, ImageTk

from .appearance import ACCENTS


def dashboard_colors(settings: dict) -> dict[str, str]:
    dark = settings.get('theme') == 'midnight'
    return {
        'background': '#202a3b' if dark else '#263348',
        'card': '#2d3c53' if dark else '#35445a',
        'inset': '#384961' if dark else '#43546b',
        'border': '#70819a',
        'text': '#f6f8fe',
        'muted': '#b6c7dc',
        'accent': ACCENTS.get(settings.get('accent', 'blue'), ACCENTS['blue'])[1],
        'success': '#91e7c4',
    }


@lru_cache(maxsize=40)
def panel_texture(width: int, height: int, color: str = '#35445a') -> Image.Image:
    """Dark translucent-glass look: subtle vertical light, rounded bevel and rim.

    Tk is composited as an ordinary window, so this is deliberately *not* a
    simulated screenshot of a wallpaper or a claim of native backdrop blur.
    """
    width, height = max(25, width), max(25, height)
    base = tuple(bytes.fromhex(color.lstrip('#')))
    mask = Image.new('L',(width,height),0)
    md=ImageDraw.Draw(mask)
    md.rounded_rectangle((1,1,width-2,height-2),radius=24,fill=255)
    layer=Image.new('RGBA',(width,height),(0,0,0,0))
    draw=ImageDraw.Draw(layer,'RGBA')
    # Cool top reflection, soft shadow near bottom; avoids flat rectangles.
    for y in range(height):
        glow=round(9*(1-y/max(1,height))**2 - 7*(y/max(1,height))**2)
        rgb=tuple(max(0,min(255,channel+glow)) for channel in base)
        draw.line((0,y,width,y),fill=(*rgb,255))
    layer.putalpha(mask)
    rim=ImageDraw.Draw(layer,'RGBA')
    rim.rounded_rectangle((1,1,width-2,height-2),radius=24,
                          outline=(138,176,220,136),width=2)
    rim.arc((7,5,width-9,38),190,350,fill=(221,238,255,55),width=2)
    return layer


class DashboardCard(tk.Canvas):
    """A rounded visual container that hosts ordinary keyboard-accessible Tk controls."""

    def __init__(self, master, *, colors: dict, **kwargs):
        self.colors = colors
        super().__init__(master, bg=colors['background'], bd=0,
                         highlightthickness=0, **kwargs)
        self.inner = tk.Frame(self, bg=colors['card'])
        self._inner_id = self.create_window(14, 14, window=self.inner, anchor='nw')
        self._image_id = self.create_image(0, 0, anchor='nw')
        self.tag_lower(self._image_id)
        self._image = None
        self._last_size = None
        self.bind('<Configure>', self._resize)

    def _resize(self, event) -> None:
        width, height = max(32, event.width), max(32, event.height)
        self.itemconfigure(self._inner_id, width=max(1, width-28), height=max(1, height-28))
        if (width, height) != self._last_size:
            self._last_size = (width, height)
            self._image = ImageTk.PhotoImage(panel_texture(width, height, self.colors['card']))
            self.itemconfigure(self._image_id, image=self._image)


class DashboardButton(tk.Canvas):
    """Pill-shaped action button with disabled/hover states and keyboard support."""

    def __init__(self, master, text: str, command, *, colors: dict,
                 primary: bool = False, height: int = 43):
        self.colors = colors
        self.label = text
        self.command = command
        self.primary = primary
        self._hovered = False
        super().__init__(master, height=height, width=170,
                         highlightthickness=0, bd=0, takefocus=1,
                         bg=master.cget('bg'), cursor='hand2')
        self.bind('<Configure>', lambda _e: self._render())
        self.bind('<Enter>', self._enter)
        self.bind('<Leave>', self._leave)
        self.bind('<ButtonRelease-1>', self._click)
        self.bind('<Return>', self._click)
        self.bind('<space>', self._click)
        self._render()

    def _enter(self, _event) -> None:
        self._hovered = True
        self._render()

    def _leave(self, _event) -> None:
        self._hovered = False
        self._render()

    def _click(self, _event=None) -> None:
        if str(self.cget('state')) != 'disabled':
            self.command()

    def configure(self, cnf=None, **kw):
        out = super().configure(cnf, **kw)
        if 'state' in kw:
            self._render()
        return out

    config = configure

    def _render(self) -> None:
        self.delete('pill')
        w, h = max(35, self.winfo_width()), max(12, self.winfo_height())
        disabled = str(self.cget('state')) == 'disabled'
        if disabled:
            background, foreground = '#4a566a', '#9fabba'
        elif self.primary:
            background, foreground = self.colors['accent'], '#0b1730'
        else:
            background, foreground = ('#5b6f89' if self._hovered else self.colors['inset']), self.colors['text']
        r = min((h - 4)/2, 15)
        self.create_rectangle(2+r, 2, w-2-r, h-2, fill=background, outline='', tags='pill')
        self.create_oval(2, 2, 2+2*r, h-2, fill=background, outline='', tags='pill')
        self.create_oval(w-2-2*r, 2, w-2, h-2, fill=background, outline='', tags='pill')
        self.create_text(w/2, h/2, text=self.label, fill=foreground,
                         font=('DejaVu Sans', 10, 'bold' if self.primary else 'normal'),
                         tags='pill')
