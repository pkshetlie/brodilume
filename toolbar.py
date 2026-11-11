"""Barre d'outils verticale façon Photoshop : icônes dessinées (pas de fichiers), outil actif
surligné, bulle d'aide « Nom (raccourci) » au survol."""
import tkinter as tk

from PIL import Image, ImageDraw, ImageTk

from theme import C


def _icon(draw_fn, size=22, color=None):
    """Icône dessinée en grand (×4) puis réduite : traits nets et lissés."""
    S = 88
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(im), color or C["ink"])
    if draw_fn is _redo:
        im = im.transpose(Image.FLIP_LEFT_RIGHT)
    return im.resize((size, size), Image.LANCZOS)


def _select(d, c):  # flèche de sélection
    d.polygon([(24, 10), (24, 72), (39, 58), (50, 80), (60, 75), (49, 53), (68, 53)], fill=c)


def _wand(d, c):  # baguette magique : sélection d'une partie de couleur
    d.line([(16, 74), (52, 38)], fill=c, width=10)
    d.ellipse((11, 69, 21, 79), fill=c)
    d.polygon([(66, 8), (70, 22), (84, 26), (70, 30), (66, 44), (62, 30), (48, 26), (62, 22)], fill=c)
    d.polygon([(40, 10), (42, 16), (48, 18), (42, 20), (40, 26), (38, 20), (32, 18), (38, 16)], fill=c)
    d.polygon([(78, 50), (80, 55), (85, 57), (80, 59), (78, 64), (76, 59), (71, 57), (76, 55)], fill=c)


def _eraser(d, c):  # gomme inclinée
    body = [(18, 56), (50, 24), (74, 48), (42, 80)]
    d.polygon(body, outline=c, width=7)
    d.polygon([(18, 56), (34, 40), (58, 64), (42, 80)], fill=c)
    d.line([(46, 80), (82, 80)], fill=c, width=6)


def _hand(d, c):  # main : faire glisser la vue
    d.rounded_rectangle((26, 40, 68, 80), radius=14, fill=c)
    for x, top in ((27, 22), (37, 12), (47, 14), (57, 22)):
        d.rounded_rectangle((x, top, x + 9, 52), radius=5, fill=c)
    d.line([(30, 64), (14, 46)], fill=c, width=10)
    d.ellipse((9, 41, 19, 51), fill=c)


def _zoom(d, c):  # loupe
    d.ellipse((12, 12, 60, 60), outline=c, width=8)
    d.line([(54, 54), (78, 78)], fill=c, width=12)
    d.ellipse((72, 72, 84, 84), fill=c)
    d.line([(26, 36), (46, 36)], fill=c, width=6)
    d.line([(36, 26), (36, 46)], fill=c, width=6)


def _undo(d, c):  # flèche courbe vers la gauche (comme Procreate)
    d.arc((20, 22, 78, 80), start=190, end=355, fill=c, width=9)
    d.polygon([(6, 46), (36, 46), (21, 66)], fill=c)


def _redo(d, c):
    _undo(d, c)  # retournée horizontalement dans _icon


def _layers(d, c):  # calques : losanges empilés
    d.polygon([(44, 10), (80, 28), (44, 46), (8, 28)], fill=c)
    d.line([(8, 44), (44, 62), (80, 44)], fill=c, width=7, joint="curve")
    d.line([(8, 60), (44, 78), (80, 60)], fill=c, width=7, joint="curve")


def _props(d, c):  # propriétés : curseurs de réglage
    for y, x in ((20, 58), (44, 28), (68, 50)):
        d.line([(10, y), (78, y)], fill=c, width=6)
        d.ellipse((x - 9, y - 9, x + 9, y + 9), fill=c)


def _image(d, c):  # image : cadre, montagne, soleil
    d.rounded_rectangle((8, 16, 80, 72), radius=8, outline=c, width=6)
    d.polygon([(16, 64), (38, 38), (52, 52), (60, 44), (72, 64)], fill=c)
    d.ellipse((54, 22, 66, 34), fill=c)


def _colors(d, c):  # couleurs : bobine de fil
    d.rectangle((22, 10, 66, 18), fill=c)
    d.rectangle((22, 70, 66, 78), fill=c)
    d.rectangle((28, 18, 60, 70), outline=c, width=5)
    for y in range(26, 66, 9):
        d.line([(30, y), (58, y + 6)], fill=c, width=4)


def _info(d, c):  # infos : i dans un rond
    d.ellipse((8, 8, 80, 80), outline=c, width=7)
    d.ellipse((38, 20, 50, 32), fill=c)
    d.rounded_rectangle((38, 38, 50, 68), radius=4, fill=c)


def _text(d, c):  # texte : un grand T avec empattements
    d.rectangle((14, 12, 74, 24), fill=c)
    d.rectangle((38, 12, 50, 74), fill=c)
    d.rectangle((28, 68, 60, 78), fill=c)
    d.rectangle((14, 12, 22, 32), fill=c)
    d.rectangle((66, 12, 74, 32), fill=c)


ICONS = {"layers": _layers, "props": _props, "text": _text, "image": _image, "colors": _colors, "info": _info,
         "undo": _undo, "redo": _redo, "move": _select, "pick": _wand, "erase": _eraser, "hand": _hand, "zoom": _zoom}


class Tooltip:
    def __init__(self, widget, text_fn):
        self.widget, self.text_fn, self.win, self._after = widget, text_fn, None, None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")

    def _schedule(self, _e=None):
        self._after = self.widget.after(450, self.show)

    def show(self):
        self.hide()
        w = self.widget
        self.win = tk.Toplevel(w)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        tk.Label(self.win, text=self.text_fn(), bg=C["tip_bg"], fg=C["tip_fg"], padx=8, pady=4,
                 font=("Segoe UI", 9)).pack()
        self.win.geometry("+%d+%d" % (w.winfo_rootx() + w.winfo_width() + 6, w.winfo_rooty() + 4))

    def hide(self, _e=None):
        if self._after:
            self.widget.after_cancel(self._after)
            self._after = None
        if self.win:
            self.win.destroy()
            self.win = None


class ToolBar(tk.Frame):
    """tools = [(identifiant, nom, action de raccourci) ou None pour un séparateur].
    commands = [(identifiant, nom, action de raccourci, fonction)] : boutons en bas de la barre
    (annuler / rétablir), grisés quand il n'y a rien à faire."""

    def __init__(self, master, variable, tools, key_label, commands=(), toggle=False):
        super().__init__(master, bg=C["tool_bg"], padx=4, pady=6)
        self._keep_bg = True
        self.var = variable
        self.toggle = toggle          # recliquer l'outil actif le désactive (panneaux repliables)
        self.tool_on = {}
        self.buttons = {}
        self.seps = []
        self._imgs = {}
        for t in tools:
            if t is None:
                sep = tk.Frame(self, bg=C["tool_sep"], height=1)
                sep._keep_bg = True
                sep.pack(fill="x", pady=6, padx=4)
                self.seps.append(sep)
                continue
            tid, name, action = t
            img = ImageTk.PhotoImage(_icon(ICONS[tid]))
            self._imgs[tid] = img
            b = tk.Label(self, image=img, bg=C["tool_bg"], width=34, height=32, bd=1, relief="flat",
                         highlightthickness=1, highlightbackground=C["tool_bg"], cursor="hand2")
            b.pack(pady=1)
            b.bind("<Button-1>", lambda e, tid=tid: self._click(tid))
            b.bind("<Enter>", lambda e, tid=tid: self._hover(tid, True), add="+")
            b.bind("<Leave>", lambda e, tid=tid: self._hover(tid, False), add="+")
            Tooltip(b, lambda name=name, action=action: "%s  (%s)" % (name, key_label(action))
                    if key_label(action) else name)
            self.buttons[tid] = b
            self.tool_on[tid] = True
        self.cmds, self.enabled = {}, {}
        for cid, name, action, fn in reversed(list(commands)):
            b = tk.Label(self, bg=C["tool_bg"], width=34, height=32, bd=1, relief="flat",
                         highlightthickness=1, highlightbackground=C["tool_bg"], cursor="hand2")
            b.pack(side="bottom", pady=1)
            b.bind("<Button-1>", lambda e, cid=cid, fn=fn: self.enabled.get(cid, True) and fn())
            b.bind("<Enter>", lambda e, b=b, cid=cid: self.enabled.get(cid, True) and b.config(bg=C["tool_hover"]),
                   add="+")
            b.bind("<Leave>", lambda e, b=b: b.config(bg=C["tool_bg"]), add="+")
            Tooltip(b, lambda name=name, action=action: "%s  (%s)" % (name, key_label(action))
                    if key_label(action) else name)
            self.cmds[cid] = b
            self.enabled[cid] = True
        sep = tk.Frame(self, bg=C["tool_sep"], height=1)
        sep._keep_bg = True
        if self.cmds:
            sep.pack(side="bottom", fill="x", pady=6, padx=4)
            self.seps.append(sep)
        self._cmd_imgs()
        variable.trace_add("write", lambda *a: self.refresh())
        self.refresh()

    def _cmd_imgs(self):
        dim = tuple(int(v) for v in C["ink"][:3]) + (90,)
        for cid, b in self.cmds.items():
            img = ImageTk.PhotoImage(_icon(ICONS[cid], color=None if self.enabled[cid] else dim))
            self._imgs["cmd_" + cid] = img
            b.config(image=img, cursor="hand2" if self.enabled[cid] else "")

    def set_enabled(self, cid, on):
        if cid in self.enabled and self.enabled[cid] != bool(on):
            self.enabled[cid] = bool(on)
            self._cmd_imgs()

    def _click(self, tid):
        if not self.tool_on.get(tid, True):
            return
        self.var.set("" if self.toggle and self.var.get() == tid else tid)

    def tool_enabled(self, tid):
        return not tid or self.tool_on.get(tid, True)

    def set_tool_enabled(self, tid, on):
        if self.tool_on.get(tid) == bool(on):
            return
        self.tool_on[tid] = bool(on)
        dim = tuple(int(v) for v in C["ink"][:3]) + (80,)
        self._imgs[tid] = ImageTk.PhotoImage(_icon(ICONS[tid], color=None if on else dim))
        self.buttons[tid].config(image=self._imgs[tid], cursor="hand2" if on else "")

    def _hover(self, tid, inside):
        if tid != self.var.get() and self.tool_on.get(tid, True):
            self.buttons[tid].config(bg=C["tool_hover"] if inside else C["tool_bg"])

    def refresh(self):
        cur = self.var.get()
        for tid, b in self.buttons.items():
            on = tid == cur
            b.config(bg=C["tool_active"] if on else C["tool_bg"],
                     highlightbackground=C["tool_border"] if on else C["tool_bg"])

    def retheme(self):
        """Nouvelles couleurs (et icônes redessinées dans la couleur d'encre du thème)."""
        self.config(bg=C["tool_bg"])
        for sep in self.seps:
            sep.config(bg=C["tool_sep"])
        dim = tuple(int(v) for v in C["ink"][:3]) + (80,)
        for tid, b in self.buttons.items():
            self._imgs[tid] = ImageTk.PhotoImage(_icon(ICONS[tid], color=None if self.tool_on[tid] else dim))
            b.config(image=self._imgs[tid])
        for b in self.cmds.values():
            b.config(bg=C["tool_bg"], highlightbackground=C["tool_bg"])
        self._cmd_imgs()
        self.refresh()
