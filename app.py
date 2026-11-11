"""Brodilume : compose une broderie .vp4 à partir de plusieurs images et broderies (.vp4 / .vp3).

Lancement : double-clic sur « Brodilume.lnk » / « Brodilume.bat » (on peut y glisser des fichiers) ou
            python app.py [images | fichiers .vp4 | .vp3 ...]
"""
import copy
import math
import os
import queue
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser

import numpy as np
from PIL import Image, ImageDraw, ImageTk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vp4 import read_vp4, write_vp4, read_design, STITCH, JUMP, TRIM  # noqa: E402
from vp4.digitize import Settings, image_to_design, background_color, suggest_colors  # noqa: E402
from vp4.render import render, to_display, draw_thread, THREAD_MM  # noqa: E402
from vp4.project import (Item, normalize, compose, erase, thread_key, apply_edits, hull,  # noqa: E402
                         remove_points, positions, merge_closest_colors)
from vp4 import threads as thr  # noqa: E402
from vp4.format import Design, ColorBlock  # noqa: E402
import shortcuts  # noqa: E402
import updater  # noqa: E402
import winsys  # noqa: E402
from toolbar import ToolBar, Tooltip  # noqa: E402
import theme  # noqa: E402
from vp4 import export as exporter  # noqa: E402
from vp4.projectfile import save_project, load_project, EXT as PROJECT_EXT  # noqa: E402

try:  # glisser-déposer dans la fenêtre (facultatif : pip install tkinterdnd2)
    from tkinterdnd2 import TkinterDnD, DND_FILES
    BaseTk = TkinterDnD.Tk
except Exception:
    TkinterDnD = DND_FILES = None
    BaseTk = tk.Tk

APP_NAME = "Brodilume"
APP_VERSION = "1.2"
# Ressources : dossier du script, ou dossier temporaire de l'exécutable compilé (PyInstaller)
ASSETS = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "assets")
INK, CREAM, MINT, PEACH = "#241B33", "#F9F5EF", "#B8F1D7", "#FFC396"   # couleurs du logo
SEL = "#2f7de1"     # cadre de sélection
NO_RANGE = "Couleurs exactes de l'image"
DETAILS = ("Aucun", "Éclats et étoiles", "Tous (liserés, traits)")
IMG_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff")
EMB_EXT = (".vp4", ".vp3")
SPM = 700           # vitesse machine estimée (points / minute)
C = theme.C        # couleurs du thème courant (clair / sombre)
SUPERSAMPLE = 2
HANDLE = 6          # demi-taille des poignées (pixels)


def _safe_name(name):
    """Nom de fichier sans caractères interdits par Windows."""
    return "".join(c for c in name if c not in '\\/:*?"<>|').strip() or "broderie"


def _asset_image(name, width=None):
    try:
        im = Image.open(os.path.join(ASSETS, name)).convert("RGBA")
    except OSError:
        return None
    if width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    return im


class Splash(tk.Toplevel):
    """Écran de démarrage : logo, slogan, barre de chargement aux couleurs de Brodilume."""
    W, H = 600, 360

    def __init__(self, master):
        super().__init__(master)
        self.overrideredirect(True)
        self.configure(bg=CREAM)
        x = (self.winfo_screenwidth() - self.W) // 2
        y = (self.winfo_screenheight() - self.H) // 3
        self.geometry("%dx%d+%d+%d" % (self.W, self.H, x, y))
        self.attributes("-topmost", True)
        cv = tk.Canvas(self, width=self.W, height=self.H, bg=CREAM, highlightthickness=0)
        cv.pack()
        cv.create_rectangle(1, 1, self.W - 2, self.H - 2, outline="#e4dccf")
        logo = _asset_image("brodilume-logo.png", 430)
        if logo is not None:
            bg = Image.new("RGBA", logo.size, CREAM)
            self._logo = ImageTk.PhotoImage(Image.alpha_composite(bg, logo))
            cv.create_image(self.W // 2, 120, image=self._logo)
        else:
            cv.create_text(self.W // 2, 120, text=APP_NAME, fill=INK, font=("Segoe UI", 40, "bold"))
        cv.create_text(self.W // 2, 222, text="Vos images, prêtes à broder", fill=INK,
                       font=("Segoe UI", 15))
        cv.create_text(self.W // 2, 250, text="Image → .vp4  ·  Visionneuse .vp4 / .vp3", fill="#6f6680",
                       font=("Segoe UI", 10))
        # barre de chargement : un « fil » menthe qui avance point par point
        self.x0, self.x1, self.y = 150, self.W - 150, 300
        cv.create_line(self.x0, self.y, self.x1, self.y, fill="#e4dccf", width=6, capstyle="round")
        self.bar = cv.create_line(self.x0, self.y, self.x0 + 1, self.y, fill=MINT, width=6, capstyle="round")
        self.star = cv.create_text(self.x0, self.y - 14, text="✦", fill=PEACH, font=("Segoe UI", 12))
        self.msg = cv.create_text(self.W // 2, 326, text="", fill="#6f6680", font=("Segoe UI", 9))
        cv.create_text(self.W - 14, self.H - 12, text="v" + APP_VERSION, anchor="e", fill="#a59db3",
                       font=("Segoe UI", 8))
        self.cv = cv
        self.update()

    def progress(self, f, text=None):
        x = self.x0 + (self.x1 - self.x0) * max(0.0, min(1.0, f))
        self.cv.coords(self.bar, self.x0, self.y, max(self.x0 + 1, x), self.y)
        self.cv.coords(self.star, x, self.y - 14)
        if text is not None:
            self.cv.itemconfigure(self.msg, text=text)
        self.update()


class View:
    """Aperçu vectoriel : zoom molette, déplacement, cercle, simulation, outils de l'application.

    Bouton gauche : outil courant (déplacer / tourner / redimensionner un élément, ou gomme) ;
    sur une zone vide, il fait glisser la vue. Bouton droit ou du milieu : toujours la vue."""

    def __init__(self, app, parent):
        self.app = app
        self.cv = tk.Canvas(parent, bg=C["view"], highlightthickness=0)
        self.zoom = 1.0          # pixels par 0,1 mm
        self.cx = self.cy = 0.0  # point du motif au centre du canevas (repère affichage)
        self.segs = []           # (n° bloc, tableau Nx2, indice global du 1er point, n° partie, indice local)
        self.bbs = np.zeros((0, 4))
        self.jumps = []          # (n° bloc, p, q, indice global)
        self.total = 0
        self.limit = None        # simulation : nombre de points affichés (None = tout)
        self.skip = set()        # blocs masqués
        self.design = None
        self.hoop = (app.hoop_mm[0] * 10, app.hoop_mm[1] * 10)
        self._img = None
        self._pan = None
        self._pending = None
        cv = self.cv
        cv.bind("<Configure>", lambda e: self.redraw())
        cv.bind("<MouseWheel>", self._wheel)
        cv.bind("<ButtonPress-1>", self._press)
        cv.bind("<B1-Motion>", self._drag)
        cv.bind("<ButtonRelease-1>", self._release)
        for b in ("2", "3"):
            cv.bind("<ButtonPress-%s>" % b, self._pan_start)
            cv.bind("<B%s-Motion>" % b, self._pan_move)
            cv.bind("<ButtonRelease-%s>" % b, self._pan_end)
        cv.bind("<Double-Button-1>", lambda e: app.on_double(e.x, e.y, *self.s2w(e.x, e.y),
                                                            add=bool(e.state & 5)))
        cv.bind("<Motion>", self._hover)
        cv.bind("<Leave>", lambda e: app.v_pos.set(""))

    # -------------------------------------------------------------- repères
    def w2s(self, x, y):
        W, H = self.cv.winfo_width(), self.cv.winfo_height()
        return (x - self.cx) * self.zoom + W / 2, (y - self.cy) * self.zoom + H / 2

    def s2w(self, sx, sy):
        W, H = self.cv.winfo_width(), self.cv.winfo_height()
        return self.cx + (sx - W / 2) / self.zoom, self.cy + (sy - H / 2) / self.zoom

    # -------------------------------------------------------------- données
    def load(self, design, skip=(), keep_view=False):
        self.design = design
        self.skip = set(skip)
        self.segs, self.jumps, n = [], [], 0
        self.hoop = (self.app.hoop_mm[0] * 10, self.app.hoop_mm[1] * 10)
        if design:
            for bi, b in enumerate(design.blocks):
                # une « partie » = suite de points sans coupe ni saut (une zone remplie, un trait…)
                cur, prev, k0, r = [], None, 0, 0
                for k, (op, x, y) in enumerate(b.points()):
                    p = to_display(design, x, y)
                    if op in (STITCH, "start"):
                        cur.append(p)
                        n += op == STITCH
                    else:
                        if len(cur) > 1:
                            self.segs.append((bi, np.array(cur, float), n - len(cur) + 1, r, k0))
                            r += 1
                        if op == JUMP and prev is not None:
                            self.jumps.append((bi, prev, p, n))
                        cur, k0 = [p], k
                    prev = p
                if len(cur) > 1:
                    self.segs.append((bi, np.array(cur, float), n - len(cur) + 1, r, k0))
        self.total = n
        self.bbs = np.array([(p[:, 0].min(), p[:, 1].min(), p[:, 0].max(), p[:, 1].max())
                             for _, p, *_ in self.segs]).reshape(-1, 4)
        self._lines = None
        if self.limit is not None and self.limit > n:
            self.limit = None
        if not keep_view:
            self.fit()
        else:
            self.redraw()

    def hit_part(self, sx, sy, tol_px=7):
        """Partie de couleur sous la souris (la dernière brodée, donc visible, l'emporte)."""
        if not self.segs:
            return None
        if self._lines is None:
            a, b, owner = [], [], []
            for k, (bi, pts, *_r) in enumerate(self.segs):
                a.append(pts[:-1])
                b.append(pts[1:])
                owner.append(np.full(len(pts) - 1, k))
            self._lines = (np.concatenate(a), np.concatenate(b), np.concatenate(owner))
        A, B, own = self._lines
        x, y = self.s2w(sx, sy)
        d = B - A
        L = (d ** 2).sum(1)
        t = np.clip(((x - A[:, 0]) * d[:, 0] + (y - A[:, 1]) * d[:, 1]) / np.where(L == 0, 1, L), 0, 1)
        dist = np.hypot(A[:, 0] + t * d[:, 0] - x, A[:, 1] + t * d[:, 1] - y)
        ok = dist <= tol_px / self.zoom
        if self.skip:
            ok &= ~np.isin(np.array([self.segs[k][0] for k in own]), list(self.skip))
        if not ok.any():
            return None
        k = own[ok].max()
        return self.segs[k][0], self.segs[k][3]

    def bounds(self):
        if not self.segs:
            return None
        a = np.concatenate([s[1] for s in self.segs])
        return a[:, 0].min(), a[:, 1].min(), a[:, 0].max(), a[:, 1].max()

    # -------------------------------------------------------------- vue
    def fit(self, hoop=False):
        W, H = max(50, self.cv.winfo_width()), max(50, self.cv.winfo_height())
        bb = self.bounds()
        hw, hh = self.hoop
        if hoop or bb is None:
            bb = (-hw / 2, -hh / 2, hw / 2, hh / 2) if bb is None else (
                min(bb[0], -hw / 2), min(bb[1], -hh / 2), max(bb[2], hw / 2), max(bb[3], hh / 2))
        x0, y0, x1, y1 = bb
        self.zoom = min((W - 60) / max(1, x1 - x0), (H - 60) / max(1, y1 - y0))
        self.cx, self.cy = (x0 + x1) / 2, (y0 + y1) / 2
        self.redraw()

    def pan_by(self, dx, dy, mult=1):
        """Défilement au clavier : 60 pixels (×4 avec Maj)."""
        self.cx += dx * 60 * mult / self.zoom
        self.cy += dy * 60 * mult / self.zoom
        self.redraw_soon()

    def zoom_real(self):
        """Taille réelle : 1 mm du motif = 1 mm à l'écran (d'après la résolution annoncée par Windows)."""
        px_per_mm = self.cv.winfo_fpixels("1m")
        self.zoom = px_per_mm / 10
        self.redraw_soon()

    def zoom_by(self, f):
        self._zoom_at(self.cv.winfo_width() / 2, self.cv.winfo_height() / 2, f)

    def _zoom_at(self, sx, sy, f):
        mx, my = self.s2w(sx, sy)
        self.zoom = min(60.0, max(0.02, self.zoom * f))
        W, H = self.cv.winfo_width(), self.cv.winfo_height()
        self.cx = mx - (sx - W / 2) / self.zoom
        self.cy = my - (sy - H / 2) / self.zoom
        self.redraw_soon()

    def _wheel(self, e):
        """Ctrl (ou Alt) + molette : zoom sous la souris ; molette : défiler en hauteur ;
        Maj + molette : défiler en largeur (comme Photoshop)."""
        ctrl, shift, alt = e.state & 0x4, e.state & 0x1, e.state & 0x20000
        if ctrl or alt:
            self._zoom_at(e.x, e.y, 1.25 if e.delta > 0 else 0.8)
            return
        step = -e.delta / 120 * 80 / self.zoom   # 80 pixels par cran
        if shift:
            self.cx += step
        else:
            self.cy += step
        self.redraw_soon()

    def _pan_start(self, e):
        self._pan = (e.x, e.y, self.cx, self.cy)
        self.cv.config(cursor="fleur")

    def _pan_move(self, e):
        if not self._pan:
            return
        x, y, cx, cy = self._pan
        dx, dy = e.x - x, e.y - y
        if e.state & 0x1:  # Maj : on reste sur l'axe principal du mouvement
            if abs(dx) >= abs(dy):
                dy = 0
            else:
                dx = 0
        self.cx = cx - dx / self.zoom
        self.cy = cy - dy / self.zoom
        self.cv.coords("img", self.cv.winfo_width() // 2 + dx, self.cv.winfo_height() // 2 + dy)
        self.app.draw_overlay()

    def _pan_end(self, e):
        if self._pan:
            self._pan = None
            self.cv.config(cursor="")
            self.redraw()

    def _press(self, e):
        if self.app._space_down:  # Espace maintenu : main temporaire (comme Photoshop)
            self.app._space_used = True
            self._pan_start(e)
            return
        if not self.app.on_press(e.x, e.y, *self.s2w(e.x, e.y), shift=bool(e.state & 1),
                                 ctrl=bool(e.state & 4)):
            self._pan_start(e)

    def _drag(self, e):
        if self._pan:
            self._pan_move(e)
        else:
            self.app.on_drag(e.x, e.y, *self.s2w(e.x, e.y), shift=bool(e.state & 1))

    def _release(self, e):
        if self._pan:
            self._pan_end(e)
        else:
            self.app.on_release(*self.s2w(e.x, e.y))

    def _hover(self, e):
        x, y = self.s2w(e.x, e.y)
        self.app.v_pos.set("x %.1f  y %.1f mm   zoom %.0f %%" % (x / 10, y / 10, self.zoom * 100 / 3.78))
        if not self._pan:
            self.cv.config(cursor=self.app.cursor_at(e.x, e.y, x, y))

    def redraw_soon(self):
        """Pendant le zoom : rendu rapide tout de suite, rendu fin dès que la souris se calme."""
        if self._pending:
            self.cv.after_cancel(self._pending)
        self.redraw(fine=False)
        self._pending = self.cv.after(200, self.redraw)

    # -------------------------------------------------------------- dessin
    def redraw(self, fine=True):
        if fine and self._pending:
            self.cv.after_cancel(self._pending)
        if fine:
            self._pending = None
        cv = self.cv
        W, H = max(10, cv.winfo_width()), max(10, cv.winfo_height())
        ss = SUPERSAMPLE if fine else 1   # suréchantillonnage : bords lisses, fils fins nets
        z = self.zoom * ss
        ox, oy = W * ss / 2 - self.cx * z, H * ss / 2 - self.cy * z
        img = Image.new("RGB", (W * ss, H * ss), C["view"])
        dr = ImageDraw.Draw(img)

        # cercle à broder et quadrillage tous les 10 mm
        hw, hh = self.hoop
        hx0, hy0, hx1, hy1 = ox - hw / 2 * z, oy - hh / 2 * z, ox + hw / 2 * z, oy + hh / 2 * z
        dr.rounded_rectangle((hx0, hy0, hx1, hy1), radius=max(2, 150 * z), fill=C["hoop"],
                             outline=C["hoop_line"], width=2 * ss)
        if self.zoom * 100 >= 12:
            for gx in range(-int(hw / 2) // 100 * 100, int(hw / 2) + 1, 100):
                X = ox + gx * z
                dr.line((X, hy0, X, hy1), fill=C["grid"] if gx else C["grid_axis"], width=ss)
            for gy in range(-int(hh / 2) // 100 * 100, int(hh / 2) + 1, 100):
                Y = oy + gy * z
                dr.line((hx0, Y, hx1, Y), fill=C["grid"] if gy else C["grid_axis"], width=ss)

        des = self.design
        if des and self.segs:
            lim = self.total if self.limit is None else self.limit
            vx0, vy0 = -ox / z, -oy / z
            vx1, vy1 = vx0 + W * ss / z, vy0 + H * ss / z
            bb = self.bbs
            vis = (bb[:, 2] >= vx0) & (bb[:, 0] <= vx1) & (bb[:, 3] >= vy0) & (bb[:, 1] <= vy1)
            tw = THREAD_MM * 10 * z  # largeur d'un fil en pixels
            shade = fine and tw >= 3
            hl = self.app.highlight()  # sélection : le reste est estompé
            for k, (bi, pts, i0, r, _k0) in enumerate(self.segs):
                if i0 >= lim or bi in self.skip or not vis[k]:
                    continue
                if i0 + len(pts) - 1 > lim:
                    pts = pts[:lim - i0 + 1]
                rgb = des.blocks[bi].thread.rgb
                if hl and (bi, r) not in hl[0] and bi not in hl[1]:
                    rgb = tuple(int(c + (g - c) * 0.75) for c, g in zip(rgb, C["fade"]))
                    draw_thread(dr, pts * z + (ox, oy), rgb, tw, False)
                    continue
                draw_thread(dr, pts * z + (ox, oy), rgb, tw, shade)
            if self.app.v_jumps.get():
                for bi, p, q, i in self.jumps:
                    if i <= lim and bi not in self.skip:
                        dr.line((p[0] * z + ox, p[1] * z + oy, q[0] * z + ox, q[1] * z + oy),
                                fill=C["jump"], width=ss)
            if self.limit is not None:  # aiguille
                for bi, pts, i0, *_r in self.segs:
                    if i0 <= lim < i0 + len(pts):
                        X, Y = pts[lim - i0] * z + (ox, oy)
                        r = 6 * ss
                        dr.ellipse((X - r, Y - r, X + r, Y + r), outline=C["fg"], width=2 * ss)
                        break
        if ss > 1:
            img = img.reduce(ss)
        self._img = ImageTk.PhotoImage(img)
        cv.delete("all")
        cv.create_image(W // 2, H // 2, image=self._img, tags="img")
        if not self.app.items:
            cv.create_text(W // 2, H // 2, fill=C["hint"], font=("Segoe UI", 12),
                           text="Glissez ici des images ou des broderies (.vp4 / .vp3)\n"
                                "ou Ctrl+O pour les choisir, Ctrl+V pour coller une image copiée",
                           justify="center")
        self.app.draw_overlay()


class App(BaseTk):
    def __init__(self, splash=True):
        super().__init__()
        self.withdraw()
        self._splash = Splash(self) if splash else None
        self._t0 = time.time()
        self._step(0.1, "Préparation de l'atelier…")
        self.title(APP_NAME)
        self._set_icon()
        self.theme_mode = shortcuts.load_setting("theme", "system")
        hp = shortcuts.load_setting("hoop", {}) or {}
        self.hoop_mm = (float(hp.get("w", 260)), float(hp.get("h", 200)))
        self._theme_name = theme.apply(self, self.theme_mode)
        self.geometry("1440x880")
        self.minsize(1100, 680)
        self.items = []              # éléments du projet, dans l'ordre de broderie
        self.sel = None              # n° de l'élément sélectionné
        self.thread_sel = None       # fil sélectionné : (n° élément, n° fil)
        self.parts = set()           # parties de couleur sélectionnées : (n° bloc du motif, n° partie)
        self.design = None           # motif final (tous les éléments)
        self.owners = []             # pour chaque bloc du motif final : (n° élément, n° fil)
        self.undo_stack = []
        self.redo_stack = []
        self.project_path = None     # fichier .brodi du projet ouvert
        self.dirty = False           # modifications non enregistrées
        self._loading_project = False
        self.clip = []               # éléments copiés (Ctrl+C)
        self._paste_n = 0
        self._loading = False        # remplissage des champs : pas de réaction aux changements
        self._queue = []             # éléments à (re)générer
        self._job = None
        self._regen_after = {}
        self._apply_after = None
        self._play_after = None
        self._tk_img = None
        self._act = None             # action souris en cours
        self._lasso = []

        self.v_width = tk.DoubleVar(value=100)
        self.v_colors = tk.IntVar(value=4)
        self.v_bg = tk.BooleanVar(value=True)
        self.v_spacing = tk.DoubleVar(value=0.4)
        self.v_stitch = tk.DoubleVar(value=4.0)
        self.v_angle = tk.DoubleVar(value=45)
        self.v_minarea = tk.DoubleVar(value=3.0)
        self.v_jumps = tk.BooleanVar(value=False)
        self.v_underlay = tk.BooleanVar(value=True)
        self.v_auto = tk.BooleanVar(value=True)
        self.v_details = tk.StringVar(value=DETAILS[1])
        self.v_x = tk.DoubleVar(value=0)
        self.v_y = tk.DoubleVar(value=0)
        self.v_rot = tk.DoubleVar(value=0)
        self.v_size = tk.DoubleVar(value=100)
        self.v_tool = tk.StringVar(value="move")
        self.v_erase_one = tk.BooleanVar(value=False)
        self.v_pos = tk.StringVar()
        self.v_status = tk.StringVar(value="Prêt")
        self.v_sim = tk.DoubleVar(value=0)
        self.v_speed = tk.IntVar(value=3)
        self._step(0.3, "Chargement des nuanciers de fils…")
        self.ranges = list(thr.available_ranges())
        self._step(0.6, "Installation des outils…")
        self.v_range = tk.StringVar(value=thr.DEFAULT_RANGE if thr.DEFAULT_RANGE in self.ranges else NO_RANGE)
        self._build()
        self._bind_keys()
        theme.recolor_tree(self)
        self._step(0.9, "Enfilage de l'aiguille…")
        for v in (self.v_colors, self.v_bg, self.v_spacing, self.v_stitch, self.v_angle,
                  self.v_minarea, self.v_underlay, self.v_range, self.v_details):
            v.trace_add("write", lambda *a: self._settings_changed())
        for v in (self.v_x, self.v_y, self.v_rot, self.v_size):
            v.trace_add("write", lambda *a: self._transform_changed())
        self.v_tool.trace_add("write", lambda *a: self._tool_changed())
        self.refresh_items()
        self.refresh_panels()
        self._history_buttons()
        self.after(3000, self._watch_system_theme)
        self.after(500, self._watch_usb)
        self.protocol("WM_DELETE_WINDOW", self.quit_app)
        self._update_title()
        self._update_q = queue.Queue()
        self.after(500, self._poll_update)
        if shortcuts.load_setting("check_updates", True):
            self.after(4000, self._start_update_check)
        self.after(max(0, int(1800 - (time.time() - self._t0) * 1000)), self._show_main)

    # ------------------------------------------------------------------ démarrage
    def _step(self, f, text):
        if self._splash:
            self._splash.progress(f, text)

    def _show_main(self):
        self.dirty = False
        self._update_title()
        if self._splash:
            self._splash.progress(1.0, "Prêt !")
            self.after(250, self._splash.destroy)
            self._splash = None
        self.deiconify()
        self.lift()
        self.focus_force()
        self.enable_drop()

    # ------------------------------------------------------------------ thème
    def set_theme(self, mode, save=True):
        self.theme_mode = mode
        if save:
            try:
                shortcuts.save_setting("theme", mode)
            except OSError:
                pass
        self.apply_theme()

    def toggle_theme(self):
        """Bascule clair <-> sombre (le choix devient explicite, plus « comme Windows »)."""
        self.set_theme("light" if self._theme_name == "dark" else "dark")
        self.v_status.set("Thème %s (Paramètres pour revenir à « comme Windows »)"
                          % ("sombre" if self._theme_name == "dark" else "clair"))

    def apply_theme(self):
        self._theme_name = theme.apply(self, self.theme_mode)
        theme.recolor_tree(self)
        for w in theme._all_children(self):
            if isinstance(w, tk.Toplevel):
                theme.title_bar(w, self._theme_name == "dark")
        self.view.cv.configure(bg=C["view"])
        self.cv_img.configure(bg=C["image_bg"])
        self.items_box.configure(bg=C["list"])
        self.items_cv.configure(bg=C["list"], highlightbackground=C["border"])
        self.panelbar.retheme()
        self._thumbs = {}
        self.pal_cv.configure(bg=C["list"])
        self.pal.configure(bg=C["list"])
        self.toolbar.retheme()
        self._update_logo()
        self.refresh_items()
        self.refresh_palette()
        self.show_image()
        self.view.redraw()

    def _update_logo(self):
        """(le logo de la barre du haut a laissé la place au menu Fichier)"""

    def _watch_system_theme(self):
        """Mode « comme Windows » : suit le changement de thème de Windows sans redémarrer."""
        if self.theme_mode == "system" and theme.resolve("system") != self._theme_name:
            self.apply_theme()
        self.after(3000, self._watch_system_theme)

    def enable_drop(self):
        if TkinterDnD or getattr(self, "_drop_on", False):
            return
        self.update_idletasks()
        try:
            self._drop_on = winsys.enable_file_drop(self, self.on_drop)
        except Exception as e:
            self.v_status.set("Glisser-déposer indisponible : %s" % e)

    def on_drop(self, files):
        ok = [f for f in files if f.lower().endswith(IMG_EXT + EMB_EXT + (PROJECT_EXT,))]
        if not ok:
            self.v_status.set("Fichiers déposés ignorés (ni images, ni broderies .vp4 / .vp3, ni projets)")
            return
        self.lift()
        self.add_paths(ok)

    def _set_icon(self):
        if sys.platform == "win32":  # icône propre dans la barre des tâches (pas celle de Python)
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Brodilume.App")
            except Exception:
                pass
        try:
            self.iconbitmap(default=os.path.join(ASSETS, "brodilume.ico"))
        except tk.TclError:
            pass
        icon = _asset_image("brodilume-icone.png", 64)
        if icon is not None:
            self._icon = ImageTk.PhotoImage(icon)
            self.iconphoto(True, self._icon)

    # ------------------------------------------------------------------ interface
    def _build(self):
        style = ttk.Style(self)
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))
        style.configure("Title.TLabel", font=("Segoe UI", 10, "bold"))

        # ---- barre d'état (bas) : message, résumé du motif, position de la souris
        bar = ttk.Frame(self, padding=(8, 2))
        bar.pack(side="bottom", fill="x")
        ttk.Label(bar, textvariable=self.v_status).pack(side="left")
        self.progress = ttk.Progressbar(bar, length=180, mode="determinate")
        ttk.Label(bar, textvariable=self.v_pos, style="Muted.TLabel").pack(side="right")
        self.lbl_summary = ttk.Label(bar, text="", style="Muted.TLabel")
        self.lbl_summary.pack(side="right", padx=(0, 18))

        # ---- barre du haut : logo + fichiers ; thème et paramètres à droite
        top = ttk.Frame(self, padding=(8, 6, 8, 4))
        top.pack(side="top", fill="x")
        self.file_menu = tk.Menu(self, tearoff=0, postcommand=self._build_file_menu)
        self.btn_file = ttk.Menubutton(top, text="☰  Fichier", menu=self.file_menu)
        self.btn_file.pack(side="left", padx=(0, 10))
        ttk.Button(top, text="＋ Importer…", style="Accent.TButton", command=self.add_files).pack(side="left",
                                                                                                padx=(0, 4))
        ttk.Button(top, text="Enregistrer", command=self.save).pack(side="left", padx=(0, 4))
        self.btn_usb = ttk.Button(top, text="⇪ Envoyer sur la clé USB", command=self.send_usb_default)
        self.btn_usb.pack(side="left", padx=(0, 4))
        Tooltip(self.btn_usb, lambda: self._usb_tip())
        ttk.Button(top, text="⚙", width=3, command=self.open_settings).pack(side="right")
        ttk.Button(top, text="◐", width=3, command=self.toggle_theme).pack(side="right", padx=(0, 3))

        # ---- à droite : barre d'icônes des panneaux + un panneau ouvert à la fois (façon Photoshop)
        self.v_panel = tk.StringVar(value="layers")
        self.panelbar = ToolBar(self, self.v_panel, [
            ("layers", "Calques : les éléments du projet", None),
            ("props", "Propriétés : position, taille, rotation", None),
            ("image", "Image : réglages de conversion", None),
            ("colors", "Couleurs : fils de l'élément ou du projet", None),
            ("info", "Infos : taille, points, durée", None),
        ], self.key_label, toggle=True)
        self.panelbar.pack(side="right", fill="y")
        self.panel_host = ttk.Frame(self, padding=(8, 6, 8, 8), width=300)
        self.panel_host.pack(side="right", fill="y")
        self.panel_host.pack_propagate(False)
        head = ttk.Frame(self.panel_host)
        head.pack(fill="x", pady=(0, 6))
        self.lbl_panel = ttk.Label(head, text="", style="Title.TLabel")
        self.lbl_panel.pack(side="left")
        ttk.Button(head, text="»", width=3, command=lambda: self.v_panel.set("")).pack(side="right")
        self.panels = {k: ttk.Frame(self.panel_host) for k in ("layers", "props", "image", "colors", "info")}

        main = ttk.Frame(self, padding=(4, 0, 4, 4))
        main.pack(side="left", fill="both", expand=True)
        self.main_area = main

        # ---- panneau Calques
        pl = self.panels["layers"]
        ttk.Label(pl, text="En haut de la liste : brodé en dernier (dessus).", style="Muted.TLabel").pack(anchor="w")
        lw = ttk.Frame(pl)
        lw.pack(fill="both", expand=True, pady=(4, 4))
        self.items_cv = tk.Canvas(lw, highlightthickness=1, highlightbackground=C["border"], bg=C["list"])
        lsb = ttk.Scrollbar(lw, orient="vertical", command=self.items_cv.yview)
        self.items_cv.configure(yscrollcommand=lsb.set)
        lsb.pack(side="right", fill="y")
        self.items_cv.pack(side="left", fill="both", expand=True)
        self.items_box = tk.Frame(self.items_cv, bg=C["list"])
        self._items_win = self.items_cv.create_window(0, 0, window=self.items_box, anchor="nw")
        self.items_box.bind("<Configure>", lambda e: self.items_cv.configure(scrollregion=self.items_cv.bbox("all")))
        self.items_cv.bind("<Configure>", lambda e: self.items_cv.itemconfigure(self._items_win, width=e.width))
        acts = ttk.Frame(pl)
        acts.pack(fill="x")
        for txt, cmd, tip in (("＋", self.add_files, "Ajouter"), ("⧉", self.duplicate_item, "Dupliquer"),
                              ("▲", lambda: self.move_item(1), "Monter (brodé plus tard)"),
                              ("▼", lambda: self.move_item(-1), "Descendre (brodé plus tôt)"),
                              ("✕", self.delete_item, "Supprimer")):
            b = ttk.Button(acts, text=txt, width=3, command=cmd)
            b.pack(side="left", padx=(0, 3))
            Tooltip(b, lambda tip=tip: tip)

        # ---- panneau Propriétés
        pp = self.panels["props"]
        pos = ttk.LabelFrame(pp, text="Position et taille", padding=8)
        pos.pack(fill="x")
        self.pos_box = pos
        self.lbl_size = ttk.Label(pos, text="Largeur mm")
        fields = (("X mm", self.v_x, -200, 200, 1), ("Y mm", self.v_y, -200, 200, 1),
                  (None, self.v_size, 5, 400, 1), ("Rotation °", self.v_rot, -360, 360, 5))
        for i, (txt, var, lo, hi, inc) in enumerate(fields):
            lab = self.lbl_size if txt is None else ttk.Label(pos, text=txt)
            lab.grid(row=i // 2, column=(i % 2) * 2, sticky="w", padx=(0, 4), pady=3)
            ttk.Spinbox(pos, from_=lo, to=hi, increment=inc, textvariable=var, width=7).grid(
                row=i // 2, column=(i % 2) * 2 + 1, sticky="w", padx=(0, 8))
        self.lbl_height = ttk.Label(pos, text="", style="Muted.TLabel")
        self.lbl_height.grid(row=2, column=0, columnspan=4, sticky="w", pady=(2, 0))
        quick = ttk.Frame(pos)
        quick.grid(row=3, column=0, columnspan=4, sticky="w", pady=(6, 0))
        for txt, cmd in (("Centrer", self.center_item), ("↺ 90°", lambda: self.rotate_item(-90)),
                         ("↻ 90°", lambda: self.rotate_item(90))):
            ttk.Button(quick, text=txt, width=len(txt) + 1, command=cmd).pack(side="left", padx=(0, 2))
        ttk.Button(pp, text="Annuler la gomme de cet élément", command=self.clear_erases).pack(fill="x", pady=(8, 0))

        # ---- panneau Image (réglages de conversion)
        box = ttk.LabelFrame(self.panels["image"], text="Réglages de l'image sélectionnée", padding=8)
        box.pack(fill="x")
        self.settings_box = box
        rows = [
            ("Nombre de couleurs", self.v_colors, 1, 15, 1),
            ("Écart entre rangs (mm)", self.v_spacing, 0.25, 1.5, 0.05),
            ("Longueur de point (mm)", self.v_stitch, 2, 7, 0.5),
            ("Angle du remplissage (°)", self.v_angle, 0, 175, 5),
            ("Zone mini (mm²)", self.v_minarea, 0, 50, 0.5),
        ]
        for i, (txt, var, lo, hi, inc) in enumerate(rows):
            ttk.Label(box, text=txt).grid(row=i, column=0, sticky="w", pady=2)
            ttk.Spinbox(box, from_=lo, to=hi, increment=inc, textvariable=var, width=7).grid(
                row=i, column=1, sticky="e", padx=(6, 0))
        r = len(rows)
        ttk.Label(box, text="Gamme de fils").grid(row=r, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Combobox(box, textvariable=self.v_range, values=[NO_RANGE] + self.ranges, state="readonly",
                     width=30).grid(row=r + 1, column=0, columnspan=2, sticky="we")
        ttk.Label(box, text="Petits détails").grid(row=r + 2, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(box, textvariable=self.v_details, values=DETAILS, state="readonly", width=17).grid(
            row=r + 2, column=1, sticky="e", pady=(6, 0))
        ttk.Checkbutton(box, text="Sous-couche (recommandé)", variable=self.v_underlay).grid(
            row=r + 3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Checkbutton(box, text="Retirer le fond extérieur (non brodé)", variable=self.v_bg).grid(
            row=r + 4, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(box, text="Régénérer à chaque changement", variable=self.v_auto).grid(
            row=r + 5, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.btn_gen = ttk.Button(box, text="Régénérer  (F5)", command=lambda: self.regenerate(self.cur()))
        self.btn_gen.grid(row=r + 6, column=0, columnspan=2, sticky="we", pady=(8, 0))

        # ---- panneau Couleurs
        pc = self.panels["colors"]
        self.lbl_threads = ttk.Label(pc, text="Couleurs", style="Title.TLabel")
        self.lbl_threads.pack(anchor="w")
        ncol = ttk.Frame(pc)
        ncol.pack(fill="x", pady=(4, 2))
        ttk.Label(ncol, text="Nombre :").pack(side="left")
        ttk.Button(ncol, text="−", width=3, command=lambda: self.change_colors(-1)).pack(side="left", padx=(4, 0))
        self.lbl_ncol = ttk.Label(ncol, text="–", width=3, anchor="center", font=("Segoe UI", 10, "bold"))
        self.lbl_ncol.pack(side="left")
        ttk.Button(ncol, text="+", width=3, command=lambda: self.change_colors(1)).pack(side="left")
        ttk.Button(ncol, text="Suggérer", command=self.suggest).pack(side="left", padx=(6, 0))
        ttk.Label(pc, text="Pastille : couleur · ● : masquer · clic droit : menu",
                  style="Muted.TLabel").pack(anchor="w")
        acts = ttk.Frame(pc)
        acts.pack(fill="x", pady=(2, 4))
        for txt, cmd, w in (("▲", lambda: self.move_block(-1), 3), ("▼", lambda: self.move_block(1), 3),
                            ("Fusionner ↑", self.merge_up, 10), ("Supprimer", self.delete_selection, 9)):
            ttk.Button(acts, text=txt, width=w, command=cmd).pack(side="left", padx=(0, 2))
        wrap = ttk.Frame(pc)
        wrap.pack(fill="both", expand=True)
        self.pal_cv = tk.Canvas(wrap, highlightthickness=0, bg=C["list"])
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.pal_cv.yview)
        self.pal_cv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.pal_cv.pack(side="left", fill="both", expand=True)
        self.pal = tk.Frame(self.pal_cv, bg=C["list"])
        self._pal_win = self.pal_cv.create_window(0, 0, window=self.pal, anchor="nw")
        self.pal.bind("<Configure>", lambda e: self.pal_cv.configure(scrollregion=self.pal_cv.bbox("all")))
        self.pal_cv.bind("<Configure>", lambda e: self.pal_cv.itemconfigure(self._pal_win, width=e.width))

        # ---- panneau Infos
        self.stats = ttk.Label(self.panels["info"], text="", wraplength=270, justify="left")
        self.stats.pack(anchor="w")

        # ---- centre : outils + aperçu + simulation
        nb = ttk.Notebook(main)
        nb.pack(fill="both", expand=True)
        tab = ttk.Frame(nb)
        nb.add(tab, text="Cercle à broder")
        self.cv_img = tk.Canvas(nb, bg=C["image_bg"], highlightthickness=0)
        nb.add(self.cv_img, text="Image d'origine")
        self.cv_img.bind("<Configure>", lambda e: self.show_image())
        self.nb = nb

        tools = ttk.Frame(tab, padding=(0, 4))
        tools.pack(fill="x")
        # options de l'outil courant (comme la barre d'options de Photoshop)
        self.lbl_tool = ttk.Label(tools, text="", font=("Segoe UI", 9, "bold"))
        self.lbl_tool.pack(side="left", padx=(4, 8))
        self.opts = ttk.Frame(tools)
        self.opts.pack(side="left")
        self.chk_one = ttk.Checkbutton(self.opts, text="seulement le fil sélectionné", variable=self.v_erase_one)
        self.btn_merge = ttk.Button(self.opts, text="Fusionner les couleurs", command=self.merge_parts)
        self.btn_rot = [ttk.Button(self.opts, text=t, command=c) for t, c in
                        (("↺ 90°", lambda: self.rotate_item(-90)), ("↻ 90°", lambda: self.rotate_item(90)),
                         ("Centrer", self.center_item))]
        ttk.Separator(tools, orient="vertical").pack(side="left", fill="y", padx=6)
        for txt, cmd in (("Ajuster (0)", lambda: self.view.fit()), ("Cercle", lambda: self.view.fit(True)),
                         ("+", lambda: self.view.zoom_by(1.4)), ("−", lambda: self.view.zoom_by(1 / 1.4))):
            ttk.Button(tools, text=txt, width=len(txt) + 2, command=cmd).pack(side="left", padx=(0, 3))
        ttk.Checkbutton(tools, text="Sauts", variable=self.v_jumps,
                        command=lambda: self.view.redraw()).pack(side="left", padx=8)
        self.lbl_hint = ttk.Label(tools, text="", style="Muted.TLabel")
        self.lbl_hint.pack(side="right", padx=(0, 6))

        body = tk.Frame(tab)
        body.pack(fill="both", expand=True)
        self.toolbar = ToolBar(body, self.v_tool, [
            ("move", "Sélection : choisir, déplacer, taille, rotation", "tool_move"),
            ("pick", "Couleurs : sélectionner des parties de fil", "tool_pick"),
            ("erase", "Gomme : retirer des points", "tool_erase"),
            None,
            ("hand", "Main : faire glisser la vue", "tool_hand"),
            ("zoom", "Zoom : clic = avant, Maj+clic = arrière", "tool_zoom"),
        ], self.key_label, commands=[
            ("undo", "Annuler", "undo", lambda: self.undo()),
            ("redo", "Rétablir", "redo", lambda: self.redo()),
        ])
        self.toolbar.pack(side="left", fill="y")
        self.view = View(self, body)
        self.view.cv.pack(side="left", fill="both", expand=True)

        sim = ttk.Frame(tab, padding=(0, 6, 0, 0))
        sim.pack(fill="x")
        self.btn_play = ttk.Button(sim, text="▶ Simuler", width=10, command=self.toggle_play)
        self.btn_play.pack(side="left")
        self.scale = ttk.Scale(sim, from_=0, to=1, variable=self.v_sim, command=self._sim_changed)
        self.scale.pack(side="left", fill="x", expand=True, padx=8)
        self.lbl_sim = ttk.Label(sim, text="", width=24)
        self.lbl_sim.pack(side="left")
        ttk.Label(sim, text="Vitesse").pack(side="left")
        ttk.Spinbox(sim, from_=1, to=10, textvariable=self.v_speed, width=3).pack(side="left", padx=(4, 0))

        self.menu = tk.Menu(self, tearoff=0)
        if TkinterDnD:
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", lambda e: self.on_drop(self.splitlist(e.data)))
        self.v_panel.trace_add("write", lambda *a: self._show_panel())
        self._show_panel()
        self._tool_changed()

    PANEL_TITLES = {"layers": "Calques", "props": "Propriétés", "image": "Image", "colors": "Couleurs",
                    "info": "Infos"}

    def _show_panel(self):
        """Un seul panneau ouvert à droite ; aucun (icône active recliquée ou ») = cercle plus grand."""
        name = self.v_panel.get()
        if name and not self.panelbar.tool_enabled(name):  # ex. Image alors qu'aucune image n'est choisie
            self.v_panel.set("layers")
            return
        for f in self.panels.values():
            f.pack_forget()
        if not name:
            self.panel_host.pack_forget()
            return
        if not self.panel_host.winfo_ismapped():
            self.panel_host.pack(side="right", fill="y", before=self.main_area)
        self.lbl_panel.config(text=self.PANEL_TITLES.get(name, ""))
        self.panels[name].pack(fill="both", expand=True)

    def _panel_availability(self):
        it = self.cur()
        self.panelbar.set_tool_enabled("props", it is not None)
        self.panelbar.set_tool_enabled("image", it is not None and it.kind == "image")
        if not self.panelbar.tool_enabled(self.v_panel.get()):
            self.v_panel.set("layers")

    def _bind_keys(self):
        """Toutes les touches passent par _on_key : les raccourcis se changent dans les Paramètres."""
        self.set_bindings(shortcuts.load_bindings())
        self.bind("<KeyPress>", self._on_key)
        self.bind("<KeyRelease-space>", self._space_release)
        self._space_down = self._space_used = False
        mv = lambda dx, dy: (lambda c: self.nudge(dx, dy, 100 if "Maj+" in c else 10))  # noqa: E731
        pan = lambda dx, dy: (lambda c: self.view.pan_by(dx, dy, 4 if "Maj+" in c else 1))  # noqa: E731
        self.actions = {
            "undo": lambda c: self.undo(), "redo": lambda c: self.redo(),
            "copy": lambda c: self.copy(), "cut": lambda c: self.cut(), "paste": lambda c: self.paste(),
            "duplicate": lambda c: self.duplicate_item(), "delete": lambda c: self.delete_selection(),
            "select_all": lambda c: self.select_all(), "deselect": lambda c: self.clear_selection(),
            "merge_parts": lambda c: self.merge_parts(),
            "add": lambda c: self.add_files(), "new": lambda c: self.new_project(),
            "save": lambda c: self.save(), "export": lambda c: self.export_png(),
            "open": lambda c: self.open_project(), "save_as": lambda c: self.save_as(),
            "export_vp4": lambda c: self.export_format("vp4"), "usb": lambda c: self.send_usb_default(),
            "close": lambda c: self.close_project(), "quit": lambda c: self.quit_app(),
            "regen": lambda c: self.regenerate(self.cur()), "settings": lambda c: self.open_settings(),
            "tool_move": lambda c: self.v_tool.set("move"), "tool_pick": lambda c: self.v_tool.set("pick"),
            "tool_erase": lambda c: self.v_tool.set("erase"),
            "tool_hand": lambda c: self.v_tool.set("hand"), "tool_zoom": lambda c: self.v_tool.set("zoom"),
            "rot_cw": lambda c: self.rotate_item(90), "rot_ccw": lambda c: self.rotate_item(-90),
            "center": lambda c: self.center_item(),
            "order_up": lambda c: self.move_item(-1), "order_down": lambda c: self.move_item(1),
            "colors_less": lambda c: self.change_colors(-1), "colors_more": lambda c: self.change_colors(1),
            "move_left": mv(-1, 0), "move_right": mv(1, 0), "move_up": mv(0, -1), "move_down": mv(0, 1),
            "fit": lambda c: self.view.fit(), "hoop": lambda c: self.view.fit(True),
            "zoom_100": lambda c: self.view.zoom_real(),
            "pan_left": pan(-1, 0), "pan_right": pan(1, 0), "pan_up": pan(0, -1), "pan_down": pan(0, 1),
            "zoom_in": lambda c: self.view.zoom_by(1.4), "zoom_out": lambda c: self.view.zoom_by(1 / 1.4),
            "play": lambda c: self.toggle_play(), "theme": lambda c: self.toggle_theme(),
            "jumps": lambda c: (self.v_jumps.set(not self.v_jumps.get()), self.view.redraw()),
        }

    def set_bindings(self, keys):
        self.keys = {a: list(v) for a, v in keys.items()}
        self._key_table = shortcuts.lookup_table(self.keys)

    def key_label(self, action):
        k = self.keys.get(action) or []
        return k[0] if k else ""

    TEXT_KEYS = {"C", "X", "V", "A", "Z", "Y", "Gauche", "Droite", "Début", "Fin", "Retour", "Suppr"}

    def _on_key(self, e):
        if e.widget.winfo_toplevel() is not self:   # fenêtre des paramètres, boîte de dialogue…
            return None
        combo = shortcuts.combo_from_event(e)
        if not combo:
            return None
        if isinstance(e.widget, (tk.Entry, ttk.Entry, ttk.Spinbox, ttk.Combobox, tk.Text)):
            # en saisie : seulement les raccourcis avec Ctrl (hors édition de texte) et les F1-F12
            last = combo.split("+")[-1] if not combo.endswith("++") else "+"
            is_f = last.startswith("F") and last[1:].isdigit()
            if not is_f and (not combo.startswith("Ctrl+") or last in self.TEXT_KEYS):
                return None
        action = self._key_table.get(combo)
        if not action:
            return None
        if action == "play" and combo == "Espace":
            # Espace : maintenu + glisser = main ; simple appui = lancer / arrêter la simulation
            if not self._space_down:
                self._space_down, self._space_used = True, False
                self.view.cv.config(cursor="fleur")
            return "break"
        self.actions[action](combo)
        return "break"

    def _space_release(self, e):
        if not self._space_down:
            return
        self._space_down = False
        self.view.cv.config(cursor="")
        if not self._space_used:
            self.toggle_play()

    def open_settings(self):
        shortcuts.SettingsDialog(self)

    # ------------------------------------------------------------------ éléments
    def cur(self):
        return self.items[self.sel] if self.sel is not None and self.sel < len(self.items) else None

    def image_tip(self, img, path=""):
        """Petit conseil selon le fichier importé (format, taille, transparence)."""
        ext = os.path.splitext(path)[1].lower()
        w, h = img.size
        if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
            tip = "Fond transparent : il ne sera pas brodé, c'est l'idéal 👌"
        elif ext in (".jpg", ".jpeg"):
            tip = ("Astuce : le JPEG brouille un peu les bords. Un PNG, idéalement avec fond transparent, "
                   "donne des contours plus nets.")
        elif ext == ".gif":
            tip = "Le GIF va très bien pour un logo aux couleurs franches (seule la 1re image d'un GIF animé est prise)."
        elif ext == ".webp":
            tip = "WebP bien reçu ! S'il a un fond transparent, il ne sera pas brodé."
        else:
            tip = "Image importée. Les dessins aux couleurs franches donnent les plus belles broderies."
        if max(w, h) < 400:
            tip += "  Image petite (%d × %d px) : une version plus grande donnera des contours plus fins." % (w, h)
        return tip

    def toast(self, text, ms=7000):
        """Message discret en haut du cercle, qui disparaît tout seul."""
        if getattr(self, "_toast", None):
            self._toast.destroy()
        lab = tk.Label(self.view.cv, text=text, bg=C["tip_bg"], fg=C["tip_fg"], padx=12, pady=6,
                       font=("Segoe UI", 9), wraplength=520, justify="left")
        lab.place(relx=0.5, y=10, anchor="n")
        lab.bind("<Button-1>", lambda e: lab.destroy())
        self._toast = lab
        self.after(ms, lambda: lab.winfo_exists() and lab.destroy())

    def add_files(self, kind="tout"):
        imgs = ("Images (PNG, JPEG, GIF, WebP)", "*.png *.jpg *.jpeg *.gif *.webp *.bmp *.tif *.tiff")
        embs = ("Broderies .vp4 / .vp3", "*.vp4 *.vp3")
        types = {"image": [imgs], "broderie": [embs]}.get(kind, [
            ("Images et broderies", " ".join("*" + e for e in IMG_EXT + EMB_EXT)), imgs, embs])
        ps = filedialog.askopenfilenames(
            title={"image": "Importer une image", "broderie": "Importer une broderie"}.get(kind, "Importer"),
            filetypes=types + [("Tous les fichiers", "*.*")])
        if ps:
            self.add_paths(ps)

    def add_paths(self, paths):
        for p in paths:
            if p.lower().endswith(PROJECT_EXT):
                self.open_project(p)
            elif p.lower().endswith(EMB_EXT):
                self.add_embroidery(p)
            else:
                self.add_image(p)

    def _place_new(self, it):
        """Nouvel élément : au centre, décalé s'il y en a déjà (pour ne pas les empiler)."""
        spots = [(0, 0), (-600, -450), (600, -450), (-600, 450), (600, 450)]
        it.x, it.y = (float(v) for v in spots[len(self.items) % len(spots)])

    def add_image(self, p):
        try:
            img = Image.open(p)
            img.load()
        except Exception as e:
            self.message("Image", kind="error", text="Impossible d'ouvrir l'image :\n%s" % e)
            return
        self.add_image_obj(img, os.path.basename(p))
        self.toast(self.image_tip(img, p))

    def add_image_obj(self, img, name):
        ratio = img.height / img.width
        s = self.settings_from_vars() or Settings()
        s.width_mm = round(min(100.0, 260, 200 / ratio))
        s.remove_background = self.ask_background(img)
        s.notes = "Créé par Brodilume"
        it = Item(name, "image", image=img, settings=s)
        it.gen_width = s.width_mm
        self._snapshot()
        self._place_new(it)
        self.items.append(it)
        self.select_item(len(self.items) - 1)
        self.regenerate(it)

    def add_embroidery(self, p):
        try:
            des = read_design(p)
        except Exception as e:
            self.message("Broderie", kind="error", text="Impossible de lire le fichier :\n%s" % e)
            return
        if not des.blocks:
            self.message("Broderie", kind="warning", text="Aucun point trouvé dans ce fichier.")
            return
        des, (cx, cy) = normalize(des)
        it = Item(os.path.basename(p), "broderie", design=des, x=cx, y=cy)
        it.gen_width = 0.1
        self._snapshot()
        if self.items:  # seul : garde sa place d'origine ; sinon on évite de l'empiler
            self._place_new(it)
        self.items.append(it)
        self.select_item(len(self.items) - 1)
        self.recompose(keep_view=len(self.items) > 1)
        self.v_status.set("Ajouté : %s" % p)

    # ------------------------------------------------------------------ projet (fichier .brodi)
    def project_name(self):
        if self.project_path:
            return os.path.splitext(os.path.basename(self.project_path))[0]
        if self.items:
            return os.path.splitext(self.items[0].name)[0]
        return "Sans titre"

    def _update_title(self):
        self.title("%s%s — %s" % ("• " if self.dirty else "", self.project_name(), APP_NAME))

    def mark_dirty(self):
        if not self._loading_project and not self.dirty:
            self.dirty = True
            self._update_title()

    def maybe_save(self):
        """Avant de fermer : propose d'enregistrer. Retourne False si l'utilisateur annule."""
        if not self.dirty or not self.items:
            return True
        r = self._dialog("Modifications non enregistrées",
                         "Enregistrer les modifications de « %s » avant de continuer ?" % self.project_name(),
                         [("Enregistrer", "save"), ("Ne pas enregistrer", "drop"), ("Annuler", None)], icon="?")
        if r == "save":
            return self.save()
        return r == "drop"

    def _reset_project(self, items=(), path=None):
        self.items, self.sel, self.thread_sel, self.parts = list(items), None, None, set()
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._history_buttons()
        self._queue.clear()
        self.project_path = path
        self._loading_project = True
        self.refresh_all()
        self.view.fit(True)
        self._loading_project = False
        self.dirty = False
        self._update_title()

    def new_project(self):
        if self.maybe_save():
            self._reset_project()
            self.v_status.set("Nouveau projet")

    def close_project(self):
        if self.maybe_save():
            self._reset_project()
            self.v_status.set("Projet fermé")

    def quit_app(self):
        if self._job or self._queue:
            if not self.ask_yes_no("Quitter", "Une image est encore en cours de génération. Quitter quand même ?"):
                return
        if self.maybe_save():
            self.destroy()

    def open_project(self, path=None):
        if not self.maybe_save():
            return
        path = path or filedialog.askopenfilename(
            title="Ouvrir un projet Brodilume", filetypes=[("Projet Brodilume", "*" + PROJECT_EXT)])
        if not path:
            return
        try:
            items, hoop = load_project(path)
        except Exception as e:
            self.message("Ouvrir", kind="error", text="Impossible d'ouvrir ce projet :\n%s" % e)
            self._forget_recent(path)
            return
        self.hoop_mm = (float(hoop[0]), float(hoop[1]))
        self.view.hoop = (self.hoop_mm[0] * 10, self.hoop_mm[1] * 10)
        self._reset_project(items, path)
        for it in self.items:  # image sans points enregistrés : on la régénère
            if it.kind == "image" and it.design is None:
                self.regenerate(it)
        self._add_recent(path)
        self.v_status.set("Projet ouvert : %s (%d éléments)" % (path, len(items)))

    def save(self, as_new=False):
        """Enregistre le projet (.brodi). Retourne True si c'est fait."""
        if not self.items:
            self.message(APP_NAME, kind="info", text="Rien à enregistrer : importez d'abord une image ou une broderie.")
            return False
        if any(it.generating or it in self._queue for it in self.items):
            self.message(APP_NAME, kind="info", text="Une image est encore en cours de génération, réessayez dans un instant.")
            return False
        path = self.project_path
        if as_new or not path:
            path = filedialog.asksaveasfilename(
                title="Enregistrer le projet", defaultextension=PROJECT_EXT,
                initialfile=self.project_name() + PROJECT_EXT,
                filetypes=[("Projet Brodilume (modifiable)", "*" + PROJECT_EXT)])
            if not path:
                return False
        try:
            prev = render(self.design, width=360) if self.design and self.design.blocks else None
            save_project(path, self.items, self.hoop_mm, prev)
        except Exception as e:
            self.message("Enregistrement", kind="error", text=str(e))
            return False
        self.project_path = path
        self.dirty = False
        self._update_title()
        self._add_recent(path)
        self.v_status.set("Projet enregistré : %s" % path)
        return True

    def save_as(self):
        return self.save(as_new=True)

    # ------------------------------------------------------------------ export, clé USB
    def _design_for_output(self):
        des = self.final_design()
        if not des or not des.blocks:
            self.message(APP_NAME, kind="info", text="Rien à exporter : importez d'abord une image ou une broderie.")
            return None
        if any(it.generating or it in self._queue for it in self.items):
            self.message(APP_NAME, kind="info", text="Une image est encore en cours de génération, réessayez dans un instant.")
            return None
        return des

    def export_format(self, ext):
        des = self._design_for_output()
        if des is None:
            return
        name, machines = next(((n, m) for e, n, m, _x in exporter.FORMATS if e == ext), (ext.upper(), ""))
        p = filedialog.asksaveasfilename(title="Exporter en .%s (%s)" % (ext, machines), defaultextension="." + ext,
                                         initialfile=self.project_name() + "." + ext,
                                         filetypes=[("Broderie %s" % name, "*." + ext)])
        if not p:
            return
        try:
            exporter.export(des, p)
        except Exception as e:
            self.message("Exporter", kind="error", text=str(e))
            return
        self.v_status.set("Exporté : %s (%d fils, %d points)" % (p, len(des.blocks), des.stitch_count()))

    def _usb_tip(self):
        d = exporter.usb_drives()
        if not d:
            return "Aucune clé USB détectée : branchez-la, le bouton s'active tout seul"
        return "Envoyer la broderie sur %s (choix du format à l'étape suivante)" % ", ".join(
            "%s %s" % (r, n) for r, n, _f in d)

    def usb_formats(self):
        known = [e for e, *_r in exporter.FORMATS]
        v = shortcuts.load_setting("usb_formats", ["vp3", "vp4"])
        return [e for e in v if e in known] or ["vp3"]

    # ------------------------------------------------------------------ version et mises à jour
    def about(self):
        self.message("À propos", text=(
            "Brodilume %s\n\nImage → broderie .vp4 (Husqvarna Viking / Pfaff) et autres formats.\n"
            "Licence : PolyForm Noncommercial 1.0.0 (usage non commercial).\n"
            "Bibliothèques tierces : voir THIRD-PARTY-NOTICES.md.\n\nhttps://github.com/%s"
            % (updater.VERSION, updater.REPO)))

    def _start_update_check(self, manual=False):
        """Interroge GitHub en arrière-plan ; le résultat revient par _poll_update (thread-safe)."""
        def work():
            try:
                self._update_q.put(("found", updater.fetch_latest(), manual))
            except Exception as e:
                self._update_q.put(("err", str(e), manual))
        threading.Thread(target=work, daemon=True).start()

    def _poll_update(self):
        try:
            while True:
                kind, data, manual = self._update_q.get_nowait()
                if kind == "found":
                    self._update_found(data, manual)
                elif kind == "err" and manual:
                    self.message("Mise à jour", kind="warning",
                                 text="Impossible de vérifier les mises à jour :\n%s" % data)
                elif kind == "dl_ok":
                    self.v_status.set("Téléchargement terminé : redémarrage…")
                    updater.install_and_restart(data)
                    self.destroy()
                    return
                elif kind == "dl_err":
                    self.message("Mise à jour", kind="error", text="Le téléchargement a échoué :\n%s" % data)
                    self.v_status.set("Mise à jour annulée")
        except queue.Empty:
            pass
        self.after(300, self._poll_update)

    def _update_found(self, info, manual):
        if not info:
            if manual:
                self.message("Mise à jour", text="Aucune version publiée pour le moment.")
            return
        if not updater.is_newer(info["version"]):
            if manual:
                self.message("Mise à jour", text="Brodilume %s est à jour." % updater.VERSION)
            return
        if not manual and shortcuts.load_setting("skip_version") == info["version"]:
            return
        notes = info["notes"].strip()
        notes = (notes[:400] + "…") if len(notes) > 400 else notes
        text = "Nouvelle version : %s (vous utilisez la %s)." % (info["version"], updater.VERSION)
        if notes:
            text += "\n\n" + notes
        if not updater.is_frozen() or not info["asset"]:
            if self.ask_yes_no("Mise à jour", text + "\n\nOuvrir la page de téléchargement ?"):
                updater.open_page(info["url"])
            return
        choice = self._dialog("Mise à jour", text + "\n\nBrodilume se fermera puis se relancera tout seul.",
                              [("Mettre à jour", "now"), ("Plus tard", "later"), ("Ignorer cette version", "skip")],
                              icon="↑")
        if choice == "skip":
            shortcuts.save_setting("skip_version", info["version"])
        elif choice == "now":
            self._do_update(info)

    def _do_update(self, info):
        if self._job or self._queue:
            if not self.ask_yes_no("Mise à jour", "Une image est encore en cours de génération. Continuer quand même ?"):
                return
        if not self.maybe_save():
            return
        dest = os.path.join(tempfile.gettempdir(), "Brodilume-%s.exe" % info["version"])
        self.v_status.set("Téléchargement de la version %s…" % info["version"])

        def work():
            try:
                self._update_q.put(("dl_ok", updater.download(info["asset"], dest), False))
            except Exception as e:
                self._update_q.put(("dl_err", str(e), False))
        threading.Thread(target=work, daemon=True).start()

    def _watch_usb(self):
        """Le bouton « clé USB » s'active dès qu'une clé est branchée."""
        try:
            on = bool(exporter.usb_drives())
        except Exception:
            on = False
        self.btn_usb.state(["!disabled" if on else "disabled"])
        self.after(2000, self._watch_usb)

    def send_usb_default(self):
        """Fenêtre « Envoyer sur la clé USB » : clé, nom du fichier, format(s) avec des exemples de machines."""
        drives = exporter.usb_drives()
        if not drives:
            self.message("Clé USB", kind="warning", text="Aucune clé USB détectée.\nBranchez-la puis réessayez.")
            return
        des = self._design_for_output()
        if des is None:
            return
        win = tk.Toplevel(self, bg=C["panel"])
        win.title("Envoyer sur la clé USB")
        win.transient(self)
        win.resizable(False, False)
        frm = ttk.Frame(win, padding=16)
        frm.pack(fill="both")
        row = ttk.Frame(frm)
        row.pack(fill="x")
        ttk.Label(row, text="Clé :").pack(side="left")
        labels = ["%s  %s  (%d Mo libres)" % d for d in drives]
        v_drive = tk.StringVar(value=labels[0])
        ttk.Combobox(row, textvariable=v_drive, values=labels, state="readonly", width=34).pack(side="left", padx=6)
        row2 = ttk.Frame(frm)
        row2.pack(fill="x", pady=(8, 0))
        ttk.Label(row2, text="Nom :").pack(side="left")
        v_name = tk.StringVar(value=_safe_name(self.project_name()))
        ttk.Entry(row2, textvariable=v_name, width=36).pack(side="left", padx=6)
        ttk.Label(frm, text="Format(s) à copier — choisissez celui de votre machine :",
                  style="Title.TLabel").pack(anchor="w", pady=(14, 4))
        chosen = set(self.usb_formats())
        vars_ = {}
        ok_pe = exporter.has_pyembroidery()
        for ext, name, brands, examples in exporter.FORMATS:
            v = tk.BooleanVar(value=ext in chosen)
            vars_[ext] = v
            r = ttk.Frame(frm)
            r.pack(fill="x", pady=2)
            cb = ttk.Checkbutton(r, text=".%s  —  %s" % (ext, brands), variable=v)
            cb.pack(anchor="w")
            if ext != "vp4" and not ok_pe:
                cb.state(["disabled"])
            ttk.Label(r, text="ex. " + examples, style="Muted.TLabel", wraplength=520,
                      justify="left").pack(anchor="w", padx=(24, 0))
        ttk.Label(frm, text="Listes données à titre indicatif : en cas de doute, cochez-en plusieurs, la machine "
                            "n'affichera que ceux qu'elle sait lire.", style="Muted.TLabel", wraplength=560,
                  justify="left").pack(anchor="w", pady=(10, 0))
        res = []
        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(14, 0))
        ttk.Button(btns, text="Annuler", command=win.destroy).pack(side="right")
        ttk.Button(btns, text="Envoyer", style="Accent.TButton",
                   command=lambda: (res.append(True), win.destroy())).pack(side="right", padx=6)
        win.bind("<Escape>", lambda e: win.destroy())
        win.update_idletasks()
        win.geometry("+%d+%d" % (self.winfo_rootx() + max(0, (self.winfo_width() - win.winfo_width()) // 2),
                                 self.winfo_rooty() + 60))
        win.grab_set()
        if getattr(self, "_usb_dialog_hook", None):  # tests
            self.after(300, lambda: self._usb_dialog_hook(win, vars_, v_drive, v_name, res))
        self.wait_window(win)
        if not res:
            return
        formats = [e for e, v in vars_.items() if v.get()]
        if not formats:
            self.message("Clé USB", kind="warning", text="Choisissez au moins un format.")
            return
        try:
            shortcuts.save_setting("usb_formats", formats)
        except OSError:
            pass
        root = drives[labels.index(v_drive.get())][0]
        self.send_usb(root, formats, v_name.get().strip() or "broderie", des)

    def send_usb(self, root, formats=None, base=None, des=None):
        des = des or self._design_for_output()
        if des is None:
            return
        formats = formats or self.usb_formats()
        base = _safe_name(base or self.project_name())
        files = [os.path.join(root, base + "." + e) for e in formats]
        exist = [f for f in files if os.path.exists(f)]
        if exist and not self.ask_yes_no("Clé USB", "%s existe déjà sur la clé.\nLe remplacer ?"
                                         % ", ".join(os.path.basename(f) for f in exist)):
            return
        try:
            for f in files:
                exporter.export(des, f)
        except Exception as e:
            self.message("Clé USB", kind="error", text="L'écriture sur la clé a échoué :\n%s" % e)
            return
        names = [os.path.basename(f) for f in files]
        self.message("Clé USB", text="Broderie copiée sur %s :\n%s\n\nPensez à éjecter la clé (icône de la barre "
                                     "des tâches) avant de la retirer." % (root, "\n".join(names)))
        self.v_status.set("Envoyé sur la clé %s : %s" % (root, ", ".join(names)))

    def export_sheet(self):
        """Fiche de broderie (PNG) : aperçu, dimensions, durée et liste des fils dans l'ordre."""
        des = self._design_for_output()
        if des is None:
            return
        p = filedialog.asksaveasfilename(title="Fiche de broderie", defaultextension=".png",
                                         initialfile=self.project_name() + " - fiche.png",
                                         filetypes=[("Image PNG", "*.png")])
        if not p:
            return
        from PIL import ImageFont
        prev = render(des, width=900, background="#ffffff")
        x0, y0, x1, y1 = des.bbox()
        n = des.stitch_count()
        rows = len(des.blocks)
        H = prev.height + 170 + rows * 34
        sheet = Image.new("RGB", (980, H), "white")
        dr = ImageDraw.Draw(sheet)
        try:
            f1, f2 = ImageFont.truetype("segoeuib.ttf", 26), ImageFont.truetype("segoeui.ttf", 17)
        except OSError:
            f1 = f2 = ImageFont.load_default()
        dr.text((40, 26), self.project_name(), fill="#241B33", font=f1)
        dr.text((40, 66), "%.0f × %.0f mm  ·  %d points  ·  %d fils  ·  environ %d min  ·  cercle %g × %g mm" % (
            (x1 - x0) / 10, (y1 - y0) / 10, n, rows, round(n / SPM + rows), *self.hoop_mm), fill="#555", font=f2)
        sheet.paste(prev, (40, 110))
        y = prev.height + 130
        for i, b in enumerate(des.blocks):
            t = b.thread
            dr.rectangle((40, y, 80, y + 24), fill=tuple(t.rgb), outline="#888")
            pts = sum(1 for r in b.records if r[0] == STITCH)
            dr.text((96, y), "%d.  %s  %s  —  %s  ·  %d points" % (i + 1, t.code, t.name, t.brand, pts),
                    fill="#222", font=f2)
            y += 34
        sheet.save(p)
        self.v_status.set("Fiche de broderie enregistrée : %s" % p)

    # ------------------------------------------------------------------ projets récents
    def recent(self):
        return [r for r in shortcuts.load_setting("recent", []) if isinstance(r, str)]

    def _add_recent(self, path):
        path = os.path.abspath(path)
        lst = [path] + [r for r in self.recent() if os.path.normcase(r) != os.path.normcase(path)]
        try:
            shortcuts.save_setting("recent", lst[:10])
        except OSError:
            pass

    def _forget_recent(self, path):
        try:
            shortcuts.save_setting("recent", [r for r in self.recent() if r != path])
        except OSError:
            pass

    def _build_file_menu(self):
        m = self.file_menu
        m.delete(0, "end")
        k = self.key_label
        has = bool(self.items)
        st = lambda on: "normal" if on else "disabled"  # noqa: E731
        m.add_command(label="Nouveau projet", accelerator=k("new"), command=self.new_project)
        m.add_command(label="Ouvrir un projet…", accelerator=k("open"), command=self.open_project)
        rec = tk.Menu(m, tearoff=0)
        recents = self.recent()
        for i, r in enumerate(recents):
            rec.add_command(label="%d  %s" % (i + 1, os.path.basename(r)), command=lambda r=r: self.open_project(r),
                            state=st(os.path.exists(r)))
        if recents:
            rec.add_separator()
            rec.add_command(label="Effacer la liste", command=lambda: shortcuts.save_setting("recent", []))
        m.add_cascade(label="Projets récents", menu=rec, state=st(bool(recents)))
        m.add_separator()
        m.add_command(label="Importer une image…  (PNG, JPEG, GIF, WebP)", accelerator=k("add"),
                      command=lambda: self.add_files("image"))
        m.add_command(label="Importer une broderie…  (.vp4, .vp3)", command=lambda: self.add_files("broderie"))
        m.add_command(label="Coller une image", accelerator=k("paste"), command=self.paste)
        m.add_separator()
        m.add_command(label="Enregistrer", accelerator=k("save"), command=self.save, state=st(has))
        m.add_command(label="Enregistrer sous…", accelerator=k("save_as"), command=self.save_as, state=st(has))
        ex = tk.Menu(m, tearoff=0)
        for i, (ext, name, machines, _ex) in enumerate(exporter.FORMATS):
            if i == 2:
                ex.add_separator()
            ex.add_command(label=".%s  —  %s" % (ext, machines),
                           accelerator=k("export_vp4") if ext == "vp4" else "",
                           command=lambda e=ext: self.export_format(e),
                           state=st(ext == "vp4" or exporter.has_pyembroidery()))
        ex.add_separator()
        ex.add_command(label="Aperçu en image (PNG)", accelerator=k("export"), command=self.export_png)
        ex.add_command(label="Fiche de broderie (PNG : aperçu + liste des fils)", command=self.export_sheet)
        m.add_cascade(label="Exporter", menu=ex, state=st(has))
        drives = exporter.usb_drives()
        lbl = "Envoyer sur la clé USB…" + ("" if drives else "  — aucune clé détectée")
        m.add_command(label=lbl, accelerator=k("usb"), command=self.send_usb_default, state=st(has and drives))
        m.add_separator()
        m.add_command(label="Paramètres…", accelerator=k("settings"), command=self.open_settings)
        m.add_command(label="Vérifier les mises à jour…", command=lambda: self._start_update_check(manual=True))
        m.add_command(label="À propos de Brodilume", command=self.about)
        m.add_separator()
        m.add_command(label="Fermer le projet", accelerator=k("close"), command=self.close_project)
        m.add_command(label="Quitter", accelerator=k("quit"), command=self.quit_app)

    def select_item(self, i):
        if i is not None and not 0 <= i < len(self.items):
            i = None
        if i != self.sel:
            self.thread_sel = None
            self.parts = set()
        self.sel = i
        self.refresh_items()
        self.refresh_panels()
        self.refresh_palette()
        self.show_image()
        self.draw_overlay()

    def move_item(self, step):
        i = self.sel
        if i is None or not 0 <= i + step < len(self.items):
            return
        self._snapshot()
        self.items[i], self.items[i + step] = self.items[i + step], self.items[i]
        self.sel = i + step
        self.recompose(True)
        self.refresh_items()

    def duplicate_item(self):
        it = self.cur()
        if not it:
            return
        self._snapshot()
        dup = it.clone()
        dup.name = "Copie de " + it.name
        dup.x += 100
        dup.y += 100
        dup.generating = False
        self.items.insert(self.sel + 1, dup)
        self.select_item(self.sel + 1)
        self.recompose(True)

    def delete_item(self):
        it = self.cur()
        if not it:
            return
        self._snapshot()
        del self.items[self.sel]
        if it in self._queue:
            self._queue.remove(it)
        self.select_item(min(self.sel, len(self.items) - 1) if self.items else None)
        self.recompose(True)

    def nudge(self, dx, dy, step):
        it = self.cur()
        if not it:  # rien de sélectionné : les flèches font défiler la vue
            self.view.pan_by(dx, dy, 4 if step > 10 else 1)
            return
        self._snapshot(merge_key=("nudge", id(it)))
        it.x += dx * step
        it.y += dy * step
        self.refresh_panels()
        self.recompose(True)

    def center_item(self):
        it = self.cur()
        if it:
            self._snapshot()
            it.x = it.y = 0.0
            self.refresh_panels()
            self.recompose(True)

    def rotate_item(self, deg):
        it = self.cur()
        if it:
            self._snapshot()
            it.angle = (it.angle + deg + 180) % 360 - 180
            self.refresh_panels()
            self.recompose(True)

    def clear_erases(self):
        it = self.cur()
        if not it or not it.erases:
            return
        self._snapshot()
        it.erases = []
        if it.kind == "image":
            self.regenerate(it)
        else:
            self.v_status.set("La gomme d'une broderie importée s'annule avec Ctrl+Z")

    # ------------------------------------------------------------------ fichiers
    def ask_background(self, img):
        """Fond transparent : jamais brodé. Sinon on demande s'il faut broder la couleur du bord."""
        rgb = background_color(img)
        if rgb is None:
            self.v_status.set("Fond transparent : il ne sera pas brodé")
            return True
        light = sum(rgb) > 600
        name = "blanc" if light and max(rgb) - min(rgb) < 25 else "#%02x%02x%02x" % rgb
        return self.ask_yes_no(
            "Fond de l'image",
            "Le fond de l'image est %s.\n\n"
            "Oui : ne pas le broder (le tissu reste visible autour du motif).\n"
            "Non : le broder aussi (remplit tout le rectangle de l'image).\n\n"
            "Les zones de cette couleur à l'intérieur du motif sont brodées dans les deux cas.\n"
            "Modifiable ensuite avec « Retirer le fond extérieur »." % name)

    def final_design(self):
        """Motif enregistré : fils identiques consécutifs réunis (moins de changements de fil)."""
        if not self.items:
            return None
        return self._apply_hoop(compose(self.items, merge=True)[0])

    def export_png(self):
        if not self.design:
            return
        p = filedialog.asksaveasfilename(title="Exporter l'aperçu", defaultextension=".png",
                                         filetypes=[("Image PNG", "*.png")])
        if p:
            shown = compose(self.items)[0]
            shown.blocks = [b for k, b in enumerate(shown.blocks) if k not in self.view.skip]
            if shown.blocks:
                render(shown, width=2000, show_jumps=self.v_jumps.get()).save(p)
                self.v_status.set("Aperçu exporté : %s" % p)

    # ------------------------------------------------------------------ réglages / génération
    def settings_from_vars(self):
        try:
            return Settings(width_mm=float(self.v_width.get()), colors=int(self.v_colors.get()),
                            remove_background=self.v_bg.get(), row_spacing_mm=float(self.v_spacing.get()),
                            stitch_mm=float(self.v_stitch.get()), angle_deg=float(self.v_angle.get()),
                            min_area_mm2=float(self.v_minarea.get()), underlay=self.v_underlay.get(),
                            details=DETAILS.index(self.v_details.get()),
                            thread_range=None if self.v_range.get() == NO_RANGE else self.v_range.get(),
                            notes="Créé par Brodilume")
        except (tk.TclError, ValueError):
            return None

    def _settings_changed(self):
        it = self.cur()
        if self._loading or not it or it.kind != "image":
            return
        s = self.settings_from_vars()
        if s is None:
            self.v_status.set("⚠ Un réglage n'est pas un nombre valide")
            return
        s.width_mm = it.settings.width_mm
        it.settings = s
        if self.v_auto.get():
            self.regenerate(it, delay=700)

    def regenerate(self, it, delay=0):
        if not it or it.kind != "image":
            return
        if delay:
            if id(it) in self._regen_after:
                self.after_cancel(self._regen_after[id(it)])
            self._regen_after[id(it)] = self.after(delay, lambda: self.regenerate(it))
            return
        self._regen_after.pop(id(it), None)
        if it not in self._queue:
            self._queue.append(it)
        self._next_job()

    def _next_job(self):
        if self._job or not self._queue:
            return
        it = self._queue.pop(0)
        if it not in self.items:
            return self._next_job()
        s = copy.copy(it.settings)
        s.recolor = list(it.recolors)
        img = it.image.copy()
        job = {"item": it, "width": s.width_mm, "done": None, "error": None, "step": (0, 1)}

        def work():
            try:
                job["done"] = image_to_design(img, s, progress=lambda k, n: job.__setitem__("step", (k, n)))
            except Exception as e:
                job["error"] = e
        self._job = job
        it.generating = True
        self.v_status.set("Génération de « %s »…" % it.name)
        self.progress.pack(side="left", padx=8)
        self.progress["value"] = 0
        self.refresh_items()
        threading.Thread(target=work, daemon=True).start()
        self.after(100, self._poll)

    def _poll(self):
        job = self._job
        k, n = job["step"]
        self.progress["value"] = 100 * k / max(1, n)
        if job["done"] is None and job["error"] is None:
            self.after(100, self._poll)
            return
        self._job = None
        it = job["item"]
        it.generating = False
        self.progress.pack_forget()
        if it in self.items:
            if job["error"]:
                self.v_status.set("⚠ « %s » : %s" % (it.name, job["error"]))
            elif it not in self._queue:  # pas déjà redemandée avec d'autres réglages
                it.gen_width = job["width"]
                # fils supprimés, parties supprimées et gomme : réappliqués à la nouvelle génération
                it.design = apply_edits(it, job["done"])
                if self.thread_sel and self.items[self.thread_sel[0]] is it:
                    self.thread_sel = None
                self.parts = set()
                it.scale = 1.0
                it.hidden = set()
                first = self.design is None or not self.design.blocks
                self.recompose(keep_view=not first)
                self.refresh_palette()
                self.v_status.set("« %s » générée — Ctrl+S pour enregistrer" % it.name)
        self.refresh_items()
        self._next_job()

    # ------------------------------------------------------------------ transformation
    def _transform_changed(self):
        it = self.cur()
        if self._loading or not it:
            return
        try:
            x, y, rot, size = (float(v.get()) for v in (self.v_x, self.v_y, self.v_rot, self.v_size))
        except (tk.TclError, ValueError):
            return
        self._snapshot(merge_key=("fields", id(it)))
        it.x, it.y, it.angle = x * 10, y * 10, rot
        if size > 0:
            self._set_size(it, size)
        if self._apply_after:
            self.after_cancel(self._apply_after)
        self._apply_after = self.after(150, lambda: self.recompose(True))

    def _width_mm(self, it):
        """Image : largeur de l'image convertie ; broderie : largeur réelle des points."""
        if it.kind == "image":
            return it.gen_width * it.scale
        x0, y0, x1, y1 = it.local_bounds()
        return (x1 - x0) * it.scale / 10

    def _set_size(self, it, size_mm):
        """Image : nouvelle largeur -> aperçu étiré tout de suite, puis vraie régénération
        (densité des points conservée). Broderie : simple mise à l'échelle des points."""
        if it.kind == "image":
            if abs(size_mm - it.settings.width_mm) < 0.05:
                return
            it.settings.width_mm = size_mm
            it.scale = size_mm / it.gen_width
            self.regenerate(it, delay=500)
        else:
            x0, y0, x1, y1 = it.local_bounds()
            it.scale = size_mm * 10 / max(1, x1 - x0)

    def refresh_panels(self):
        """Champs Position et Réglages = élément sélectionné."""
        it = self.cur()
        self._loading = True
        try:
            if it:
                self.v_x.set(round(it.x / 10, 1))
                self.v_y.set(round(it.y / 10, 1))
                self.v_rot.set(round(it.angle, 1))
                if it.kind == "image":
                    self.v_size.set(round(it.settings.width_mm, 1))
                    s = it.settings
                    self.v_colors.set(s.colors)
                    self.v_spacing.set(s.row_spacing_mm)
                    self.v_stitch.set(s.stitch_mm)
                    self.v_angle.set(s.angle_deg)
                    self.v_minarea.set(s.min_area_mm2)
                    self.v_underlay.set(s.underlay)
                    self.v_bg.set(s.remove_background)
                    self.v_details.set(DETAILS[s.details])
                    self.v_range.set(s.thread_range or NO_RANGE)
                else:
                    self.v_size.set(round(self._width_mm(it), 1))
            self._update_height()
        finally:
            self._loading = False
        state = "!disabled" if it and it.kind == "image" else "disabled"
        for w in self.settings_box.winfo_children():
            try:
                w.state([state])
            except (AttributeError, tk.TclError):
                pass
        for w in self.pos_box.winfo_children() + self.pos_box.winfo_children()[-1].winfo_children():
            try:
                w.state(["!disabled" if it else "disabled"])
            except (AttributeError, tk.TclError):
                pass
        self.settings_box.config(text="Réglages de l'image sélectionnée" if it and it.kind == "image"
                                 else "Réglages (sélectionnez une image)")
        self._update_height()
        self._panel_availability()

    def _update_height(self):
        it = self.cur()
        if it and it.design and it.design.blocks:
            x0, y0, x1, y1 = it.local_bounds()
            self.lbl_height.config(text="Hauteur : %.1f mm (proportions gardées)" % ((y1 - y0) * it.scale / 10))
        else:
            self.lbl_height.config(text="")

    # ------------------------------------------------------------------ souris sur le cercle
    TOOL_NAMES = {"move": "Sélection", "pick": "Couleurs", "erase": "Gomme", "hand": "Main", "zoom": "Zoom"}

    def _tool_changed(self):
        tool = self.v_tool.get()
        self.lbl_tool.config(text=self.TOOL_NAMES.get(tool, ""))
        for w in self.opts.winfo_children():
            w.pack_forget()
        shown = {"erase": [self.chk_one], "pick": [self.btn_merge], "move": self.btn_rot}.get(tool, [])
        for w in shown:
            w.pack(side="left", padx=(0, 4))
        self.lbl_hint.config(text={"erase": "Entourez les points à retirer",
                                   "pick": "Ctrl+clic : ajouter · double-clic : tout le fil",
                                   "hand": "Glisser : déplacer la vue",
                                   "zoom": "Clic : zoom avant · Maj+clic : arrière",
                                   }.get(tool, "Coins : taille · rond : rotation (Maj : 15°)"))
        if tool != "pick" and self.parts:
            self.parts = set()
            self.view.redraw()
        self.draw_overlay()

    def _handles(self, it):
        """Poignées de l'élément à l'écran : 4 coins (taille) et le rond de rotation."""
        c = [self.view.w2s(*p) for p in it.corners()]
        top = ((c[0][0] + c[1][0]) / 2, (c[0][1] + c[1][1]) / 2)
        cx, cy = self.view.w2s(it.x, it.y)
        d = math.hypot(top[0] - cx, top[1] - cy) or 1
        rot = (top[0] + (top[0] - cx) / d * 28, top[1] + (top[1] - cy) / d * 28)
        return c, top, rot

    def _hit(self, sx, sy, x, y):
        it = self.cur()
        if it and self.v_tool.get() == "move":
            c, top, rot = self._handles(it)
            if math.hypot(sx - rot[0], sy - rot[1]) <= HANDLE + 3:
                return "rotate", self.sel
            for p in c:
                if abs(sx - p[0]) <= HANDLE + 2 and abs(sy - p[1]) <= HANDLE + 2:
                    return "scale", self.sel
        if it and it.contains(x, y):  # l'élément sélectionné reste prioritaire
            return "move", self.sel
        for i in range(len(self.items) - 1, -1, -1):  # sinon le dernier brodé, qui est dessus
            if self.items[i].contains(x, y):
                return "move", i
        return None, None

    def cursor_at(self, sx, sy, x, y):
        if self.v_tool.get() == "hand":
            return "fleur"
        if self.v_tool.get() == "zoom":
            return "plus"
        if self.v_tool.get() == "erase":
            return "pencil" if self.items else ""
        if self.v_tool.get() == "pick":
            return "hand2" if self.view.hit_part(sx, sy) else ""
        kind, _ = self._hit(sx, sy, x, y)
        return {"rotate": "exchange", "scale": "sizing", "move": "fleur"}.get(kind, "")

    def on_press(self, sx, sy, x, y, shift=False, ctrl=False):
        self.stop_play()
        if self.v_tool.get() == "hand":
            return False  # la vue glisse
        if self.v_tool.get() == "zoom":
            self.view._zoom_at(sx, sy, 1 / 1.6 if shift else 1.6)
            return True
        if self.v_tool.get() == "erase":
            if not self.items:
                return False
            self._act = ("erase",)
            self._lasso = [(x, y)]
            return True
        if self.v_tool.get() == "pick":
            return self.pick_part(sx, sy, shift, ctrl)
        kind, i = self._hit(sx, sy, x, y)
        if kind is None:
            return False
        if i != self.sel:
            self.select_item(i)
        it = self.cur()
        self._snapshot()
        self._act = (kind, x, y, it.x, it.y, it.angle, it.scale)
        self._ghost = []  # contour allégé des points, pour suivre la souris sans tout redessiner
        for b in it.design.blocks if it.design else []:
            color, seg, step = "#%02x%02x%02x" % b.thread.rgb, [], max(1, len(b.records) // 600)
            for k, (op, px, py) in enumerate(b.points()):
                if op in (STITCH, "start"):
                    if k % step == 0:
                        seg.append((px, py))
                else:
                    if len(seg) > 1:
                        self._ghost.append((color, np.array(seg, float)))
                    seg = [(px, py)]
            if len(seg) > 1:
                self._ghost.append((color, np.array(seg, float)))
        self._ghost = self._ghost[:300]
        return True

    def on_drag(self, sx, sy, x, y, shift=False):
        act = self._act
        if not act:
            return
        if act[0] == "erase":
            self._lasso.append((x, y))
            self.draw_overlay()
            return
        it = self.cur()
        kind, px, py, ox, oy, oa, osc = act
        if kind == "move":
            it.x, it.y = ox + x - px, oy + y - py
        elif kind == "rotate":
            a0 = math.atan2(py - oy, px - ox)
            a1 = math.atan2(y - oy, x - ox)
            a = oa + math.degrees(a1 - a0)
            if shift:
                a = round(a / 15) * 15
            it.angle = (a + 180) % 360 - 180
        elif kind == "scale":
            d0 = math.hypot(px - ox, py - oy) or 1
            f = max(0.05, math.hypot(x - ox, y - oy) / d0)
            it.scale = osc * f
        self.refresh_panels_light(it)
        self.draw_overlay(ghost=True)

    def refresh_panels_light(self, it):
        self._loading = True
        try:
            self.v_x.set(round(it.x / 10, 1))
            self.v_y.set(round(it.y / 10, 1))
            self.v_rot.set(round(it.angle, 1))
            self.v_size.set(round(self._width_mm(it), 1))
        finally:
            self._loading = False

    def on_release(self, x, y):
        act, self._act = self._act, None
        if not act:
            return
        if act[0] == "erase":
            self._apply_lasso()
            return
        it = self.cur()
        if act[0] == "scale" and it.kind == "image":
            it.settings.width_mm = round(it.gen_width * it.scale, 1)
            self.regenerate(it, delay=10)
        self.refresh_panels()
        self.recompose(True)

    def on_double(self, sx, sy, x, y, add=False):
        if not self.items:
            self.add_files()
        elif self.v_tool.get() == "pick":
            self.pick_part(sx, sy, whole=True, add=add)

    def _apply_lasso(self):
        poly, self._lasso = np.array(self._lasso, float), []
        if len(poly) < 3 or np.ptp(poly[:, 0]) + np.ptp(poly[:, 1]) < 5:
            self.draw_overlay()
            return
        targets = [self.cur()] if self.cur() else list(self.items)
        key = None
        if self.v_erase_one.get():
            if not self._valid(self.thread_sel):
                self.v_status.set("Gomme : sélectionnez d'abord un fil dans la liste de droite")
                self.draw_overlay()
                return
            it, b = self._block(self.thread_sel)
            targets, key = [it], thread_key(b.thread)
        self._snapshot()
        before = sum(it.design.stitch_count() for it in targets if it.design)
        for it in targets:
            if not it.design:
                continue
            local = it.to_local(poly)
            it.design = erase(it.design, local, key)
            it.erases.append((local / (it.gen_width * 10), key))
        after = sum(it.design.stitch_count() for it in targets if it.design)
        self.thread_sel = None
        self.recompose(True)
        self.refresh_palette()
        self.v_status.set("Gomme : %d points retirés (Ctrl+Z pour annuler)" % (before - after))

    def draw_overlay(self, ghost=False):
        cv = self.view.cv
        cv.delete("ov")
        if self._lasso:
            pts = [c for p in self._lasso for c in self.view.w2s(*p)]
            if len(pts) >= 4:
                cv.create_line(*pts, fill="#d33", width=2, dash=(4, 3), tags="ov")
            return
        it = self.cur()
        if not it or not it.design:
            return
        c, top, rot = self._handles(it)
        flat = [v for p in c for v in p]
        cv.create_polygon(*flat, outline=SEL, fill="", width=2 if ghost else 1, dash=(5, 3), tags="ov")
        if ghost:  # aperçu du déplacement : tracé allégé des points de l'élément
            for color, pts in getattr(self, "_ghost", []):
                if len(pts) > 1:
                    w = it.to_world(pts)
                    sp = [v for p in w for v in self.view.w2s(*p)]
                    cv.create_line(*sp, fill=color, tags="ov")
        if self.v_tool.get() != "move":
            return
        cv.create_line(*top, *rot, fill=SEL, tags="ov")
        cv.create_oval(rot[0] - HANDLE, rot[1] - HANDLE, rot[0] + HANDLE, rot[1] + HANDLE,
                       fill="white", outline=SEL, width=2, tags="ov")
        for p in c:
            cv.create_rectangle(p[0] - HANDLE, p[1] - HANDLE, p[0] + HANDLE, p[1] + HANDLE,
                                fill="white", outline=SEL, width=2, tags="ov")

    # ------------------------------------------------------------------ annulation
    def _state(self, merge_key=None):
        return [it.clone() for it in self.items], self.sel, merge_key

    def _snapshot(self, merge_key=None):
        """Mémorise l'état ; merge_key : plusieurs petits changements de suite = une seule étape."""
        if merge_key is not None and self.undo_stack and self.undo_stack[-1][2] == merge_key:
            return
        self.undo_stack.append(self._state(merge_key))
        self.undo_stack[:] = self.undo_stack[-60:]
        self.redo_stack.clear()
        self._history_buttons()

    def _history_buttons(self):
        if hasattr(self, "toolbar"):
            self.toolbar.set_enabled("undo", bool(self.undo_stack))
            self.toolbar.set_enabled("redo", bool(self.redo_stack))

    def _restore(self, state):
        items, sel, _ = state
        self.items = items
        self.sel = sel if sel is not None and sel < len(items) else None
        self.thread_sel = None
        self.parts = set()
        for it in self.items:  # une image dont la génération était en cours : on la relance
            if it.kind == "image" and it.design is None:
                self.regenerate(it)
        self.refresh_all()
        self._history_buttons()

    def undo(self):
        if not self.undo_stack:
            self.v_status.set("Rien à annuler")
            return
        self.redo_stack.append(self._state())
        self._restore(self.undo_stack.pop())
        self.v_status.set("Annulé (%s pour rétablir)" % self.key_label("redo"))

    def redo(self):
        if not self.redo_stack:
            self.v_status.set("Rien à rétablir")
            return
        self.undo_stack.append(self._state())
        self._restore(self.redo_stack.pop())
        self.v_status.set("Rétabli")

    # ------------------------------------------------------------------ copier / couper / coller
    def _extract(self):
        """Élément « broderie » fait des parties sélectionnées (ou de tout le fil sélectionné)."""
        if self.parts:
            chosen = self.parts
        elif self._valid(self.thread_sel):
            bis = {k for k, o in enumerate(self.owners) if o == tuple(self.thread_sel)}
            chosen = {(b, r) for b, _p, _i, r, _k in self.view.segs if b in bis}
        else:
            return None
        des = Design(hoop_rotated=1)
        cur_bi, blk, last = None, None, None
        for bi, pts, _i0, r, _k0 in self.view.segs:  # dans l'ordre de broderie
            if (bi, r) not in chosen:
                continue
            q = [tuple(int(round(v)) for v in p) for p in pts]
            if bi != cur_bi:
                blk = ColorBlock(self.design.blocks[bi].thread, q[0], [])
                des.blocks.append(blk)
                cur_bi, last = bi, q[0]
            else:
                blk.records += [(TRIM,), (JUMP, q[0][0] - last[0], q[0][1] - last[1])]
                last = q[0]
            for a, b in zip(q, q[1:]):
                blk.records.append((STITCH, b[0] - a[0], b[1] - a[1]))
                last = b
        if not des.blocks:
            return None
        des, (cx, cy) = normalize(des)
        src = self.items[self.owners[next(iter(chosen))[0]][0]].name
        it = Item("Extrait de " + src, "broderie", design=des, x=cx, y=cy)
        it.gen_width = 0.1
        return it

    def copy(self):
        ext = self._extract()
        if ext is not None:
            self.clip = [ext]
            what = "%d partie(s) copiée(s) — %s pour coller (nouvel élément)" % (
                len(self.parts) or 1, self.key_label("paste"))
        elif self.cur():
            self.clip = [self.cur().clone()]
            what = "Élément « %s » copié — %s pour coller" % (self.cur().name, self.key_label("paste"))
        else:
            self.v_status.set("Rien à copier : sélectionnez un élément ou des parties (outil Couleurs)")
            return False
        self._paste_n = 0
        try:  # le presse-papiers Windows retient qu'on a copié un élément (et plus une image)
            self.clipboard_clear()
            self.clipboard_append("Brodilume : " + self.clip[0].name)
        except tk.TclError:
            pass
        self.v_status.set(what)
        return True

    def cut(self):
        if self.copy():
            self.delete_selection()
            self.v_status.set("Coupé — %s pour coller" % self.key_label("paste"))

    def paste(self):
        kind, data = winsys.clipboard_content()
        if kind == "image":
            self._paste_n += 1
            self.add_image_obj(data, "Image collée %d" % self._paste_n)
            return
        if kind == "files":
            ok = [f for f in data if f.lower().endswith(IMG_EXT + EMB_EXT)]
            if ok:
                self.add_paths(ok)
            else:
                self.v_status.set("Le presse-papiers contient des fichiers qui ne sont ni des images ni des broderies")
            return
        if not self.clip:
            self.v_status.set("Presse-papiers vide : copiez un élément, des parties ou une image")
            return
        self._snapshot()
        self._paste_n += 1
        at = self.sel + 1 if self.sel is not None else len(self.items)
        for k, src in enumerate(self.clip):
            it = src.clone()
            it.generating = False
            it.x += 50 * self._paste_n
            it.y += 50 * self._paste_n
            self.items.insert(at + k, it)
            if it.kind == "image" and it.design is None:
                self.regenerate(it)
        self.select_item(at + len(self.clip) - 1)
        self.recompose(True)
        self.v_status.set("Collé : « %s »" % self.items[self.sel].name)

    def select_all(self):
        if not self.items:
            return
        idx = [self.sel] if self.sel is not None else list(range(len(self.items)))
        bis = {k for k, o in enumerate(self.owners) if o[0] in idx}
        self.v_tool.set("pick")
        self.parts = {(b, r) for b, _p, _i, r, _k in self.view.segs if b in bis}
        self.view.redraw()
        self.v_status.set("%d parties sélectionnées" % len(self.parts))

    # ------------------------------------------------------------------ fils et parties de couleur
    def _valid(self, ref):
        if ref is None or not 0 <= ref[0] < len(self.items):
            return False
        it = self.items[ref[0]]
        return it.design is not None and 0 <= ref[1] < len(it.design.blocks)

    def _block(self, ref):
        it = self.items[ref[0]]
        return it, it.design.blocks[ref[1]]

    def highlight(self):
        """Ce qui est mis en avant à l'écran : (parties, blocs entiers) du motif, ou None."""
        if self.parts:
            return self.parts, set()
        if self._valid(self.thread_sel):
            return set(), {k for k, o in enumerate(self.owners) if o == tuple(self.thread_sel)}
        return None

    def clear_selection(self):
        if self.parts or self.thread_sel:
            self.parts, self.thread_sel = set(), None
            self.refresh_palette()
            self.view.redraw()
        else:
            self.select_item(None)

    def select_thread(self, ref):
        self.thread_sel = None if ref == self.thread_sel else ref
        self.parts = set()
        self.refresh_palette()
        self.view.redraw()

    def pick_part(self, sx, sy, shift=False, ctrl=False, whole=False, add=False):
        """Outil Couleurs : clic = une partie (zone ou trait d'une couleur) ; Ctrl+clic ou Maj+clic =
        ajouter / retirer de la sélection ; double-clic = toutes les parties de ce fil."""
        hit = self.view.hit_part(sx, sy)
        if hit is None:
            if self.parts and not (shift or ctrl):
                self.parts = set()
                self.refresh_palette()
                self.view.redraw()
            return False
        bi, r = hit
        if whole:
            sel = {(b, rr) for b, _p, _i, rr, _k in self.view.segs if b == bi}
            self.parts = (self.parts | sel) if add else sel
        elif shift or ctrl:
            self.parts ^= {hit}
        else:
            self.parts = {hit}
        ii, lb = self.owners[bi]
        if self.sel != ii:
            self.sel = ii
            self.refresh_items()
            self.refresh_panels()
            self.show_image()
        self.thread_sel = (ii, lb)
        self.refresh_palette()
        self.view.redraw()
        b = self.items[ii].design.blocks[lb]
        n = sum(len(p) - 1 for bb, p, _i, rr, _k in self.view.segs if (bb, rr) in self.parts)
        nc = len({thread_key(self.design.blocks[bb].thread) for bb, _r in self.parts})
        self.v_status.set("%d partie(s) · %d points · %d couleur(s) — %s : fusionner, Suppr : supprimer"
                          % (len(self.parts), n, nc, self.key_label("merge_parts")))
        return True

    def merge_parts(self):
        """Fusionne les couleurs des parties sélectionnées en une seule (demandée si plusieurs).

        Image : la fusion est refaite sur l'image puis la broderie est recalculée (la zone fusionnée
        est remplie d'un seul tenant). Broderie importée : les points sont gardés et passent au fil
        choisi (brodés avec lui)."""
        if self.v_tool.get() != "pick" or not self.parts:
            self.v_status.set("Outil Couleurs : sélectionnez les parties à fusionner (Ctrl+clic pour en ajouter)")
            return
        owners = {self.owners[bi] for bi, _r in self.parts}
        if len({ii for ii, _ in owners}) > 1:
            self.v_status.set("Fusion impossible : les parties viennent de plusieurs éléments")
            return
        ii = next(iter(owners))[0]
        it = self.items[ii]
        count = {}
        for bi, pts, _i, r, _k in self.view.segs:
            if (bi, r) in self.parts:
                t = self.design.blocks[bi].thread
                c = count.setdefault(thread_key(t), [t, 0])
                c[1] += len(pts) - 1
        if len(count) < 2:
            self.v_status.set("Ces parties ont déjà la même couleur")
            return
        keep = self.ask_keep_color([v for v in count.values()])
        if keep is None:
            return
        kkey = thread_key(keep)
        self._snapshot()
        if it.kind == "image":
            for key in count:
                if key == kkey:
                    continue
                mine = [(bi, r) for bi, r in self.parts if thread_key(self.design.blocks[bi].thread) == key]
                every = {(b, rr) for b, _p, _i, rr, _k in self.view.segs
                         if self.owners[b][0] == ii and thread_key(self.design.blocks[b].thread) == key}
                if set(mine) >= every:
                    poly = None  # toute la couleur : fusion partout
                else:
                    pts = np.concatenate([p for b, p, _i, rr, _k in self.view.segs if (b, rr) in mine])
                    poly = hull(it.to_local(pts), margin=8.0) / (it.gen_width * 10)
                it.recolors.append((poly, (key[0], key[1], key[2]),
                                    (keep.brand, keep.code, keep.name, tuple(keep.rgb))))
            self.parts, self.thread_sel = set(), None
            self.regenerate(it)
            self.v_status.set("Fusion vers %s %s : recalcul de la broderie…" % (keep.code, keep.name))
            return
        # broderie importée : les parties passent dans le bloc du fil gardé
        masks = {}
        for bi, pts, _i0, r, k0 in self.view.segs:
            if (bi, r) in self.parts and thread_key(self.design.blocks[bi].thread) != kkey:
                lb = self.owners[bi][1]
                blk = it.design.blocks[lb]
                m = masks.setdefault(lb, np.zeros(len(blk.records) + 1, bool))
                m[k0:k0 + len(pts)] = True
        runs = []
        for lb, hit in masks.items():
            pos = positions(it.design.blocks[lb])
            idx = np.flatnonzero(hit)
            for grp in np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1):
                runs.append(np.round(pos[grp]).astype(int))
        bl = list(it.design.blocks)
        for lb in sorted(masks, reverse=True):
            nb = remove_points(bl[lb], masks[lb])
            if nb is None:
                del bl[lb]
            else:
                bl[lb] = nb
        ti = next(i for i, b in enumerate(bl) if thread_key(b.thread) == kkey)
        tb = bl[ti]
        recs = list(tb.records)
        x, y = tb.start
        for rr in tb.records:
            if rr[0] != TRIM:
                x, y = x + rr[1], y + rr[2]
        for run in runs:
            recs += [(TRIM,), (JUMP, int(run[0][0] - x), int(run[0][1] - y))]
            for a, b in zip(run, run[1:]):
                recs.append((STITCH, int(b[0] - a[0]), int(b[1] - a[1])))
            x, y = run[-1]
        bl[ti] = ColorBlock(tb.thread, tb.start, recs)
        it.design.blocks = bl
        it.hidden = set()
        self.parts, self.thread_sel = set(), None
        self.recompose(True)
        self.refresh_palette()
        self.v_status.set("Fusion vers %s %s (broderie importée : points gardés, pas de recalcul)"
                          % (keep.code, keep.name))

    def ask_keep_color(self, choices):
        """Fenêtre « Quelle couleur garder ? » ; choices = [(fil, nb de points)]. Retourne le fil."""
        if getattr(self, "_ask_color_override", None):
            return self._ask_color_override(choices)
        win = tk.Toplevel(self, bg=C["panel"])
        win.title("Fusionner les couleurs")
        theme.title_bar(win, C["name"] == "dark")
        win.transient(self)
        win.resizable(False, False)
        ttk.Label(win, text="Quelle couleur garder pour les parties sélectionnées ?",
                  padding=(14, 12, 14, 6)).pack(anchor="w")
        choices = sorted(choices, key=lambda c: -c[1])
        var = tk.IntVar(value=0)
        for i, (t, n) in enumerate(choices):
            row = ttk.Frame(win, padding=(14, 2))
            row.pack(fill="x")
            ttk.Radiobutton(row, variable=var, value=i).pack(side="left")
            sw = tk.Label(row, bg="#%02x%02x%02x" % t.rgb, width=4, relief="solid", bd=1)
            sw.pack(side="left", padx=6)
            sw.bind("<Button-1>", lambda e, i=i: var.set(i))
            lb = ttk.Label(row, text="%s %s — %d points sélectionnés" % (t.code, t.name, n))
            lb.pack(side="left")
            lb.bind("<Button-1>", lambda e, i=i: var.set(i))
        ttk.Label(win, text="Image : la broderie est recalculée (zone fusionnée remplie d'un seul tenant).\n"
                            "Broderie importée : les points sont gardés et changent de fil.",
                  style="Muted.TLabel", padding=(14, 8)).pack(anchor="w")
        res = []
        btns = ttk.Frame(win, padding=(14, 0, 14, 12))
        btns.pack(fill="x")
        ttk.Button(btns, text="Annuler", command=win.destroy).pack(side="right")
        ttk.Button(btns, text="Fusionner", command=lambda: (res.append(choices[var.get()][0]), win.destroy())
                   ).pack(side="right", padx=6)
        win.bind("<Return>", lambda e: (res.append(choices[var.get()][0]), win.destroy()))
        win.bind("<Escape>", lambda e: win.destroy())
        win.geometry("+%d+%d" % (self.winfo_rootx() + 400, self.winfo_rooty() + 250))
        win.grab_set()
        win.focus_force()
        self.wait_window(win)
        return res[0] if res else None

    def delete_selection(self):
        """Suppr : parties sélectionnées, sinon le fil sélectionné, sinon l'élément."""
        if self.parts:
            self.delete_parts()
        elif self._valid(self.thread_sel):
            self.delete_thread()
        else:
            self.delete_item()

    def delete_parts(self):
        self._snapshot()
        masks = {}
        for bi, pts, _i0, r, k0 in self.view.segs:
            if (bi, r) in self.parts:
                ii, lb = self.owners[bi]
                blk = self.items[ii].design.blocks[lb]
                m = masks.setdefault((ii, lb), np.zeros(len(blk.records) + 1, bool))
                m[k0:k0 + len(pts)] = True
        removed = 0
        for (ii, lb), hit in sorted(masks.items(), key=lambda kv: (kv[0][0], -kv[0][1])):
            it = self.items[ii]
            blk = it.design.blocks[lb]
            pos = positions(blk)
            if it.kind == "image":  # mémorisé pour la prochaine génération de l'image
                it.erases.append((hull(pos[hit]) / (it.gen_width * 10), thread_key(blk.thread)))
            before = sum(1 for r in blk.records if r[0] == STITCH)
            nb = remove_points(blk, hit)
            bl = list(it.design.blocks)
            if nb is None:
                del bl[lb]
                it.hidden = {h if h < lb else h - 1 for h in it.hidden if h != lb}
            else:
                bl[lb] = nb
            removed += before - (sum(1 for r in nb.records if r[0] == STITCH) if nb else 0)
            it.design.blocks = bl
        n = len(self.parts)
        self.parts, self.thread_sel = set(), None
        self.recompose(True)
        self.refresh_palette()
        self.v_status.set("%d partie(s) supprimée(s), %d points en moins (Ctrl+Z pour annuler)" % (n, removed))

    def delete_thread(self, ref=None):
        ref = ref or self.thread_sel
        if not self._valid(ref):
            self.v_status.set("Sélectionnez d'abord un fil")
            return
        it, b = self._block(ref)
        key = thread_key(b.thread)
        self._snapshot()
        it.removed.add(key)  # une image régénérée n'aura plus ce fil non plus
        it.design.blocks = [x for x in it.design.blocks if thread_key(x.thread) != key]
        it.hidden = set()
        self.parts, self.thread_sel = set(), None
        self.recompose(True)
        self.refresh_palette()
        self.v_status.set("Fil supprimé : %s %s (Ctrl+Z pour annuler)" % (b.thread.code, b.thread.name))

    def _color_target(self):
        it = self.cur()
        if it is None and len(self.items) == 1:
            it = self.items[0]
        return it

    def change_colors(self, delta):
        """Une couleur de plus ou de moins pour l'élément sélectionné."""
        it = self._color_target()
        if not it:
            self.v_status.set("Sélectionnez un élément")
            return
        if it.kind == "image":
            n = max(1, min(15, it.settings.colors + delta))
            if n == it.settings.colors:
                return
            self._snapshot()
            it.settings.colors = n
            it.removed = set()  # nouvelles couleurs : les fils supprimés ne correspondent plus
            it.recolors = []
            self.refresh_panels()
            self.regenerate(it)
            self.v_status.set("« %s » : %d couleurs, génération…" % (it.name, n))
        elif delta < 0:
            self._snapshot()
            res = merge_closest_colors(it.design)
            if not res:
                return
            it.hidden = set()
            self.thread_sel = None
            self.recompose(True)
            self.refresh_palette()
            self.v_status.set("Couleur fusionnée : %s %s → %s %s" % (res[0].code, res[0].name,
                                                                     res[1].code, res[1].name))
        else:
            self.v_status.set("Une broderie importée n'a pas d'image d'origine : on ne peut que réduire "
                              "ses couleurs")

    def suggest(self):
        it = self._color_target()
        if not it or it.kind != "image":
            self.v_status.set("La suggestion fonctionne sur une image (pas sur une broderie importée)")
            return
        n, errs = suggest_colors(it.image, it.settings)
        if n != it.settings.colors:
            self._snapshot()
            it.settings.colors = n
            it.removed = set()
            it.recolors = []
            self.refresh_panels()
            self.regenerate(it)
        self.v_status.set("Suggestion pour « %s » : %d couleurs (au-delà, une couleur de plus change peu "
                          "le résultat)" % (it.name, n))

    def move_block(self, step, ref=None):
        ref = ref or self.thread_sel
        if not self._valid(ref):
            return
        ii, i = ref
        it = self.items[ii]
        if not 0 <= i + step < len(it.design.blocks):
            return
        self._snapshot()
        bl = list(it.design.blocks)
        bl[i], bl[i + step] = bl[i + step], bl[i]
        it.design.blocks = bl
        it.hidden = {i + step if h == i else i if h == i + step else h for h in it.hidden}
        self.thread_sel = (ii, i + step)
        self.recompose(True)
        self.refresh_palette()

    def merge_up(self, ref=None):
        """Fusionne le fil dans le précédent du même élément : un changement de fil en moins."""
        ref = ref or self.thread_sel
        if not self._valid(ref) or not ref[1]:
            self.v_status.set("Sélectionnez un fil (pas le premier) à fusionner avec le précédent")
            return
        ii, i = ref
        it = self.items[ii]
        self._snapshot()
        bl = list(it.design.blocks)
        a, b = bl[i - 1], bl[i]
        x, y = a.start
        for r in a.records:
            if r[0] != TRIM:
                x += r[1]
                y += r[2]
        bl[i - 1] = type(a)(a.thread, a.start,
                            a.records + [(TRIM,), (JUMP, b.start[0] - x, b.start[1] - y)] + b.records)
        del bl[i]
        it.design.blocks = bl
        it.hidden = {h if h < i else h - 1 for h in it.hidden if h != i}
        self.thread_sel = (ii, i - 1)
        self.recompose(True)
        self.refresh_palette()
        self.v_status.set("Fils fusionnés : %s %s" % (a.thread.code, a.thread.name))

    def toggle_hidden(self, ref):
        it = self.items[ref[0]]
        it.hidden ^= {ref[1]}
        self.refresh_palette()
        self._update_skip()

    def pick_color(self, ref):
        it, block = self._block(ref)
        i = ref[1]
        rgb = colorchooser.askcolor(color="#%02x%02x%02x" % block.thread.rgb, title="Couleur du fil")[0]
        if not rgb:
            return
        self._snapshot()
        rgb = tuple(int(v) for v in rgb)
        rng = (it.settings.thread_range if it.settings else None) or (
            self.v_range.get() if self.v_range.get() != NO_RANGE else None)
        t = thr.nearest(rgb, thr.load_range(rng)) if rng else None
        new = type(block.thread)(block.thread.rgb, block.thread.code, block.thread.name, block.thread.brand)
        if t:  # on prend le vrai fil le plus proche de la couleur choisie
            new.rgb, new.code, new.name, new.brand = t.rgb, t.code, t.name, t.brand
        else:
            new.rgb, new.code = rgb, "%02X%02X%02X" % rgb
        bl = list(it.design.blocks)
        bl[i] = type(block)(new, block.start, block.records)
        it.design.blocks = bl
        self.recompose(True)
        self.refresh_palette()

    def context_menu(self, e, ref):
        it = self.items[ref[0]]
        i = ref[1]
        self.thread_sel = ref
        self.parts = set()
        self.refresh_palette()
        self.view.redraw()
        m = self.menu
        m.delete(0, "end")
        n = len(it.design.blocks)
        m.add_command(label="Changer la couleur…", command=lambda: self.pick_color(ref))
        m.add_command(label="Supprimer ce fil", command=lambda: self.delete_thread(ref))
        m.add_command(label="Sélectionner ses parties sur le cercle",
                      command=lambda: self._select_all_parts(ref))
        m.add_separator()
        m.add_command(label="Afficher" if i in it.hidden else "Masquer dans l'aperçu",
                      command=lambda: self.toggle_hidden(ref))
        m.add_command(label="Afficher seulement ce fil",
                      command=lambda: (setattr(it, "hidden", set(range(n)) - {i}), self.refresh_palette(),
                                       self._update_skip()))
        m.add_command(label="Tout afficher", command=lambda: (it.hidden.clear(), self.refresh_palette(),
                                                              self._update_skip()))
        m.add_command(label="Gommer seulement ce fil",
                      command=lambda: (self.v_erase_one.set(True), self.v_tool.set("erase")))
        m.add_separator()
        m.add_command(label="Monter", command=lambda: self.move_block(-1, ref), state="normal" if i else "disabled")
        m.add_command(label="Descendre", command=lambda: self.move_block(1, ref),
                      state="normal" if i < n - 1 else "disabled")
        m.add_command(label="Fusionner avec le fil précédent", command=lambda: self.merge_up(ref),
                      state="normal" if i else "disabled")
        m.tk_popup(e.x_root, e.y_root)

    def _select_all_parts(self, ref):
        bis = {k for k, o in enumerate(self.owners) if o == tuple(ref)}
        self.parts = {(b, r) for b, _p, _i, r, _k in self.view.segs if b in bis}
        self.v_tool.set("pick")
        self.parts = {(b, r) for b, _p, _i, r, _k in self.view.segs if b in bis}
        self.view.redraw()
        self.v_status.set("%d parties sélectionnées — Suppr pour supprimer, Maj+clic pour en retirer"
                          % len(self.parts))

    # ------------------------------------------------------------------ simulation
    def toggle_play(self):
        if self._play_after:
            self.stop_play()
            return
        if not self.view.total:
            return
        if self.view.limit is None or self.view.limit >= self.view.total:
            self.view.limit = 0
        self.btn_play.config(text="⏸ Pause")
        self._tick()

    def stop_play(self):
        if self._play_after:
            self.after_cancel(self._play_after)
            self._play_after = None
            self.view.redraw()
        self.btn_play.config(text="▶ Simuler")

    def _tick(self):
        v = self.view
        step = max(1, int(v.total * (2 ** int(self.v_speed.get() or 3)) / 6000))
        v.limit = min(v.total, (v.limit or 0) + step)
        self._update_sim()
        if v.limit >= v.total:
            v.redraw()
            self.stop_play()
            return
        v.redraw(fine=False)
        self._play_after = self.after(30, self._tick)

    def _sim_changed(self, _=None):
        v = self.view
        if not v.total:
            return
        lim = int(float(self.v_sim.get()) * v.total)
        v.limit = None if lim >= v.total else lim
        self._update_sim(False)
        v.redraw_soon()

    def _update_sim(self, move_scale=True):
        v = self.view
        lim = v.total if v.limit is None else v.limit
        if move_scale:
            self.v_sim.set(lim / max(1, v.total))
        k = 0
        for bi, pts, i0, *_r in v.segs:
            if i0 <= lim:
                k = bi
        color = " · fil %d" % (k + 1) if v.limit is not None and self.design and self.design.blocks else ""
        self.lbl_sim.config(text="%d / %d points%s" % (lim, v.total, color))

    # ------------------------------------------------------------------ affichage
    def _apply_hoop(self, des):
        """Taille du cercle choisie dans les Paramètres -> aperçu et fichier .vp4.
        Jusqu'à 260 × 200 mm, on écrit le cercle « UniLarge3 » (vérifié avec mySewnet) ; au-delà,
        le nom Universal_LxH du logiciel (non vérifié)."""
        if des is None:
            return des
        w, h = self.hoop_mm
        des.hoop_size = (int(round(h * 10)), int(round(w * 10)))
        if w <= 260 and h <= 200:
            des.hoop_name, des.hoop_group = "UniLarge3", "Universal"
            des.hoop_size = (2000, 2600)
        else:
            des.hoop_name, des.hoop_group = "Universal_%dx%d" % (round(w), round(h)), "Universal"
        return des

    def set_hoop(self, w, h, save=True):
        self.hoop_mm = (float(w), float(h))
        if save:
            try:
                shortcuts.save_setting("hoop", {"w": float(w), "h": float(h)})
            except OSError:
                pass
        self.view.hoop = (self.hoop_mm[0] * 10, self.hoop_mm[1] * 10)
        self.recompose(True)
        self.view.fit(True)
        self.v_status.set("Espace de broderie : %g × %g mm" % self.hoop_mm)

    def recompose(self, keep_view=False):
        self.mark_dirty()
        self.design, self.owners = compose(self.items) if self.items else (None, [])
        self._apply_hoop(self.design)
        self.view.limit = None
        self.view.load(self.design, self._skip(), keep_view)
        self._update_sim()
        self.refresh_stats()
        self.refresh_items()

    def _skip(self):
        return {k for k, (ii, bi) in enumerate(self.owners) if bi in self.items[ii].hidden}

    def _update_skip(self):
        self.view.skip = self._skip()
        self.view.redraw()

    def refresh_all(self):
        self.recompose(True)
        self.refresh_items()
        self.refresh_panels()
        self.refresh_palette()
        self.show_image()

    def _thumb(self, it):
        """Vignette de l'élément pour les calques (gardée tant que ses points ne changent pas)."""
        if not it.design or not it.design.blocks:
            return None
        key = (id(it.design), id(it.design.blocks), C["name"])
        cache = self.__dict__.setdefault("_thumbs", {})
        if key not in cache:
            im = render(it.design, width=120, background=C["field"], supersample=2)
            im.thumbnail((46, 34), Image.LANCZOS)
            box = Image.new("RGB", (48, 36), C["border"])
            inner = Image.new("RGB", (46, 34), C["field"])
            inner.paste(im, ((46 - im.width) // 2, (34 - im.height) // 2))
            box.paste(inner, (1, 1))
            cache[key] = ImageTk.PhotoImage(box)
        return cache[key]

    def refresh_items(self):
        for w in self.items_box.winfo_children():
            w.destroy()
        if not self.items:
            tk.Label(self.items_box, text="Aucun élément\nCtrl+O ou glissez des fichiers ici", bg=C["list"],
                     fg=C["faint"], pady=14).pack(fill="x")
            return
        for i in range(len(self.items) - 1, -1, -1):  # comme les calques : le dessus en haut
            it = self.items[i]
            sel = i == self.sel
            bg = C["list_sel"] if sel else C["list"]
            f = tk.Frame(self.items_box, bg=bg, padx=4, pady=4)
            f.pack(fill="x")
            eye = tk.Label(f, text="●" if it.visible else "○", bg=bg, cursor="hand2", width=2,
                           fg=C["list_fg"] if it.visible else C["hidden_fg"], font=("Segoe UI", 11))
            eye.pack(side="left")
            eye.bind("<Button-1>", lambda e, i=i: self.toggle_item_visible(i))
            th = self._thumb(it)
            tl = tk.Label(f, image=th, bg=bg) if th else tk.Label(f, text="…", width=6, bg=bg, fg=C["faint"])
            tl.pack(side="left", padx=(2, 6))
            state = " · génération…" if it.generating or it in self._queue else ""
            if it.design and it.design.blocks:
                x0, y0, x1, y1 = it.local_bounds()
                size = "%.0f × %.0f mm" % ((x1 - x0) * it.scale / 10, (y1 - y0) * it.scale / 10)
            else:
                size = ""
            fg = C["list_fg"] if it.visible else C["hidden_fg"]
            lb = tk.Label(f, text="%s\n%s · %s%s%s" % (it.name[:30], it.kind, size,
                                                      " · %d°" % it.angle if it.angle else "", state),
                          bg=bg, fg=fg, anchor="w", justify="left",
                          font=("Segoe UI", 9, "bold") if sel else ("Segoe UI", 9))
            lb.pack(side="left", fill="x", expand=True)
            for w in (f, lb, tl):
                w.bind("<Button-1>", lambda e, i=i: self.select_item(i))
                w.bind("<Double-Button-1>", lambda e, i=i: (self.select_item(i), self.v_panel.set("props")))
                w.bind("<Button-3>", lambda e, i=i: self.layer_menu(e, i))
            for w in (f, lb, tl, eye):
                w.bind("<MouseWheel>", lambda e: self.items_cv.yview_scroll(-1 if e.delta > 0 else 1, "units"))

    def toggle_item_visible(self, i):
        self._snapshot()
        it = self.items[i]
        it.visible = not it.visible
        self.recompose(True)
        self.v_status.set("« %s » %s" % (it.name, "affiché" if it.visible else
                                          "masqué (ni affiché ni enregistré)"))

    def _dialog(self, title, text, buttons, icon="ℹ"):
        """Boîte de message aux couleurs du thème (celles de Windows restent toujours claires).
        buttons = [(libellé, valeur)] ; le premier est le bouton par défaut (Entrée)."""
        win = tk.Toplevel(self, bg=C["panel"])
        win.title(title)
        win.transient(self)
        win.resizable(False, False)
        frm = ttk.Frame(win, padding=(16, 14))
        frm.pack(fill="both")
        row = ttk.Frame(frm)
        row.pack(fill="x")
        ttk.Label(row, text=icon, font=("Segoe UI", 20), foreground=C["accent"]).pack(side="left", anchor="n",
                                                                                   padx=(0, 12))
        ttk.Label(row, text=text, wraplength=420, justify="left").pack(side="left", anchor="w")
        res = []
        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(14, 0))
        first = None
        for label, value in reversed(buttons):
            b = ttk.Button(btns, text=label, command=lambda v=value: (res.append(v), win.destroy()))
            b.pack(side="right", padx=(6, 0))
            first = b if value == buttons[0][1] else first
        win.bind("<Return>", lambda e: (res.append(buttons[0][1]), win.destroy()))
        win.bind("<Escape>", lambda e: win.destroy())
        win.update_idletasks()
        win.geometry("+%d+%d" % (self.winfo_rootx() + max(0, (self.winfo_width() - win.winfo_width()) // 2),
                                 self.winfo_rooty() + max(0, (self.winfo_height() - win.winfo_height()) // 3)))
        if first:
            first.focus_set()
        win.grab_set()
        self.wait_window(win)
        return res[0] if res else None

    def ask_yes_no(self, title, text, yes="Oui", no="Non"):
        return self._dialog(title, text, [(yes, True), (no, False)], icon="?") is True

    def message(self, title, text="", kind="info"):
        self._dialog(title, text, [("OK", True)], icon={"error": "✕", "warning": "⚠"}.get(kind, "ℹ"))

    def ask_text(self, title, label, value=""):
        """Petite fenêtre de saisie aux couleurs du thème (simpledialog de Tk ignore le thème)."""
        win = tk.Toplevel(self, bg=C["panel"])
        win.title(title)
        win.transient(self)
        win.resizable(False, False)
        frm = ttk.Frame(win, padding=14)
        frm.pack(fill="both")
        ttk.Label(frm, text=label).pack(anchor="w")
        var = tk.StringVar(value=value)
        ent = ttk.Entry(frm, textvariable=var, width=40)
        ent.pack(fill="x", pady=(4, 10))
        res = []
        btns = ttk.Frame(frm)
        btns.pack(fill="x")
        ttk.Button(btns, text="Annuler", command=win.destroy).pack(side="right")
        ttk.Button(btns, text="OK", command=lambda: (res.append(var.get()), win.destroy())).pack(side="right", padx=6)
        win.bind("<Return>", lambda e: (res.append(var.get()), win.destroy()))
        win.bind("<Escape>", lambda e: win.destroy())
        win.geometry("+%d+%d" % (self.winfo_rootx() + 400, self.winfo_rooty() + 250))
        ent.focus_set()
        ent.select_range(0, "end")
        win.grab_set()
        self.wait_window(win)
        return res[0] if res else None

    def rename_item(self, i):
        it = self.items[i]
        name = self.ask_text("Renommer", "Nom de l'élément :", it.name)
        if name and name.strip():
            self._snapshot()
            it.name = name.strip()
            self.refresh_items()

    def layer_menu(self, e, i):
        self.select_item(i)
        m = self.menu
        m.delete(0, "end")
        it = self.items[i]
        m.add_command(label="Propriétés…", command=lambda: self.v_panel.set("props"))
        if it.kind == "image":
            m.add_command(label="Réglages de l'image…", command=lambda: self.v_panel.set("image"))
        m.add_command(label="Couleurs…", command=lambda: self.v_panel.set("colors"))
        m.add_separator()
        m.add_command(label="Renommer…", command=lambda: self.rename_item(i))
        m.add_command(label="Masquer" if it.visible else "Afficher", command=lambda: self.toggle_item_visible(i))
        m.add_command(label="Dupliquer", command=self.duplicate_item)
        m.add_command(label="Monter (brodé plus tard)", command=lambda: self.move_item(1),
                      state="normal" if i < len(self.items) - 1 else "disabled")
        m.add_command(label="Descendre (brodé plus tôt)", command=lambda: self.move_item(-1),
                      state="normal" if i else "disabled")
        m.add_separator()
        m.add_command(label="Supprimer", command=self.delete_item)
        m.tk_popup(e.x_root, e.y_root)

    def refresh_palette(self):
        """Fils de l'élément sélectionné ; sans sélection, toutes les couleurs du projet."""
        for w in self.pal.winfo_children():
            w.destroy()
        it = self.cur()
        if it:
            groups = [(self.sel, it)]
            self.lbl_threads.config(text="Couleurs de « %s »" % it.name[:30])
        else:
            groups = list(enumerate(self.items))
            self.lbl_threads.config(text="Toutes les couleurs du projet")
        tgt = self._color_target()
        if tgt is None or not tgt.design:
            self.lbl_ncol.config(text="–")
        elif tgt.kind == "image":
            self.lbl_ncol.config(text=str(tgt.settings.colors))
        else:
            self.lbl_ncol.config(text=str(len({thread_key(b.thread) for b in tgt.design.blocks})))
        if not any(g.design for _, g in groups):
            tk.Label(self.pal, text="Ajoutez une image ou une broderie", bg=C["list"], fg=C["faint"]).pack(pady=8)
            return
        for ii, g in groups:
            if not g.design:
                continue
            if len(groups) > 1:
                h = tk.Label(self.pal, text="%d. %s" % (ii + 1, g.name), bg=C["list_head"], fg=C["list_fg"], anchor="w",
                             font=("Segoe UI", 9, "bold"), padx=6, cursor="hand2")
                h.pack(fill="x", pady=(4, 0))
                h.bind("<Button-1>", lambda e, ii=ii: self.select_item(ii))
            for i, b in enumerate(g.design.blocks):
                ref = (ii, i)
                sel = ref == self.thread_sel
                hid = i in g.hidden
                bg = C["list_sel"] if sel else C["list"]
                f = tk.Frame(self.pal, bg=bg, padx=4, pady=3)
                f.pack(fill="x")
                eye = tk.Label(f, text="○" if hid else "●", bg=bg, cursor="hand2",
                               fg=C["hidden_fg"] if hid else C["list_fg"], font=("Segoe UI", 10))
                eye.pack(side="left")
                eye.bind("<Button-1>", lambda e, ref=ref: self.toggle_hidden(ref))
                sw = tk.Label(f, bg="#%02x%02x%02x" % b.thread.rgb, width=3, relief="solid", bd=1, cursor="hand2")
                sw.pack(side="left", padx=4)
                sw.bind("<Button-1>", lambda e, ref=ref: self.pick_color(ref))
                n = sum(1 for r in b.records if r[0] == STITCH)
                parts = sum(1 for r in b.records if r[0] == JUMP) + 1
                txt = "%d. %s %s\n    %d pts · %d partie%s" % (i + 1, b.thread.code, b.thread.name, n, parts,
                                                              "s" if parts > 1 else "")
                lb = tk.Label(f, text=txt, bg=bg, justify="left", anchor="w", fg=C["hidden_fg"] if hid else C["list_fg"])
                lb.pack(side="left", fill="x", expand=True)
                dl = tk.Label(f, text="✕", bg=bg, fg=C["danger"], cursor="hand2", font=("Segoe UI", 10))
                dl.pack(side="right")
                dl.bind("<Button-1>", lambda e, ref=ref: self.delete_thread(ref))
                for w in (f, lb):
                    w.bind("<Button-1>", lambda e, ref=ref: self.select_thread(ref))
                for w in (f, lb, sw, eye, dl):
                    w.bind("<Button-3>", lambda e, ref=ref: self.context_menu(e, ref))
                    w.bind("<MouseWheel>", lambda e: self.pal_cv.yview_scroll(-1 if e.delta > 0 else 1, "units"))

    def refresh_stats(self):
        des = self.design
        hidden = sum(1 for it in self.items if not it.visible)
        if not des or not des.blocks:
            self.stats.config(text="")
            self.lbl_summary.config(text="")
            return
        x0, y0, x1, y1 = des.bbox()
        n = des.stitch_count()
        jumps = sum(1 for b in des.blocks for r in b.records if r[0] == JUMP)
        changes = sum(1 for a, b in zip(des.blocks, des.blocks[1:]) if a.thread != b.thread)
        txt = ("Éléments : %d\nTaille totale : %.1f × %.1f mm\nPoints : %d\nChangements de fil : %d\n"
               "Sauts / coupes : %d\nDurée estimée : %d min"
               % (len(self.items), (x1 - x0) / 10, (y1 - y0) / 10, n, changes, jumps,
                  round(n / SPM + len(des.blocks))))
        hw, hh = self.view.hoop
        if x0 < -hw / 2 or x1 > hw / 2 or y0 < -hh / 2 or y1 > hh / 2:
            txt += "\n⚠ Dépasse le cercle %d × %d mm" % (hw / 10, hh / 10)
        if hidden:
            txt += "\n%d élément(s) masqué(s) : non enregistré(s)" % hidden
        self.stats.config(text=txt)
        self.lbl_summary.config(text="%.0f × %.0f mm · %d points · %d changement%s de fil · ~%d min%s" % (
            (x1 - x0) / 10, (y1 - y0) / 10, n, changes, "s" if changes > 1 else "",
            round(n / SPM + len(des.blocks)), "  ⚠ dépasse le cercle" if "Dépasse" in txt else ""))

    def show_image(self):
        cv = self.cv_img
        cv.delete("all")
        W, H = max(50, cv.winfo_width()), max(50, cv.winfo_height())
        it = self.cur()
        if not it or it.image is None:
            cv.create_text(W // 2, H // 2, fill=C["faint"], text="Sélectionnez une image dans la liste des éléments")
            return
        img = it.image.convert("RGB")
        sc = min(W / img.width, H / img.height, 1.0)
        im = img.resize((max(1, int(img.width * sc)), max(1, int(img.height * sc))), Image.LANCZOS)
        self._tk_img = ImageTk.PhotoImage(im)
        cv.create_image(W // 2, H // 2, image=self._tk_img)


if __name__ == "__main__":
    if "--uninstall" in sys.argv[1:]:  # Paramètres > Applications > Brodilume > Désinstaller
        import install_win
        install_win.run_uninstall_ui()
        sys.exit(0)
    if updater.is_frozen():
        try:
            import install_win
            if install_win.is_installed_copy(sys.executable):  # version à jour dans Paramètres > Applications
                install_win.set_registered_version(updater.VERSION)
        except Exception:
            pass
    app = App()
    files = [a for a in sys.argv[1:] if os.path.exists(a)]
    if files:
        app.after(1900, lambda: app.add_paths(files))
    app.mainloop()
