"""Projet à plusieurs éléments : images converties et broderies importées, placés dans le cercle.

Chaque élément garde son motif dans un repère local (affichage : X à droite, Y en bas, 0,1 mm,
centré sur 0) et une transformation : position du centre, rotation, échelle. Le motif final
(`compose`) met tous les éléments bout à bout, dans l'ordre de la liste.

Gomme : les points d'un élément situés dans un polygone sont retirés ; le fil est coupé et
saute par-dessus la partie gommée. Les polygones sont gardés pour être réappliqués quand
l'image est régénérée (nouveaux réglages, nouvelle taille).
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field

import numpy as np

from .format import Design, ColorBlock, STITCH, JUMP, TRIM
from .render import to_display


@dataclass
class Item:
    name: str
    kind: str                          # "image", "texte" ou "broderie"
    image: object = None               # PIL.Image pour une image
    settings: object = None            # digitize.Settings pour une image
    design: Design | None = None       # motif local (déjà gommé, couleurs retouchées)
    x: float = 0.0                     # centre dans le cercle (0,1 mm)
    y: float = 0.0
    angle: float = 0.0                 # degrés, sens horaire à l'écran
    scale: float = 1.0                 # broderie : échelle ; image : aperçu en attendant la régénération
    erases: list = field(default_factory=list)   # [(polygone local Nx2, fil ou None)]
    hidden: set = field(default_factory=set)     # fils masqués dans l'aperçu (indices locaux)
    removed: set = field(default_factory=set)    # fils supprimés (thread_key), même après régénération
    recolors: list = field(default_factory=list)  # fusions de couleurs (image : refaites à la génération)
    generating: bool = False
    visible: bool = True               # œil des calques : masqué = ni affiché ni enregistré
    gen_width: float = 0.1             # image : largeur (mm) du motif généré ; broderie : 0,1
    # texte : {"text", "font" (nom), "path", "index", "rgb", "align", "spacing", "auto_name"} ;
    # son image (lettres dessinées avec la police) est convertie comme une image importée
    text: dict | None = None

    @property
    def generated(self):
        """Image ou texte : points calculés à partir d'une image (régénérables)."""
        return self.kind in ("image", "texte")

    def local_bounds(self):
        if not self.design or not self.design.blocks:
            return (-100.0, -100.0, 100.0, 100.0)
        return self.design.bbox()

    def corners(self):
        """Les 4 coins du cadre de l'élément dans le cercle (pour la sélection à l'écran)."""
        x0, y0, x1, y1 = self.local_bounds()
        pts = np.array([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], float)
        return self.to_world(pts)

    def to_world(self, pts):
        a = math.radians(self.angle)
        c, s = math.cos(a), math.sin(a)
        p = np.asarray(pts, float) * self.scale
        return np.stack([p[:, 0] * c - p[:, 1] * s + self.x, p[:, 0] * s + p[:, 1] * c + self.y], 1)

    def to_local(self, pts):
        a = math.radians(self.angle)
        c, s = math.cos(a), math.sin(a)
        p = np.asarray(pts, float) - (self.x, self.y)
        return np.stack([p[:, 0] * c + p[:, 1] * s, -p[:, 0] * s + p[:, 1] * c], 1) / self.scale

    def contains(self, x, y):
        q = self.to_local([(x, y)])[0]
        x0, y0, x1, y1 = self.local_bounds()
        return x0 <= q[0] <= x1 and y0 <= q[1] <= y1

    def clone(self):
        """Copie pour l'annulation : les listes de points ne sont jamais modifiées sur place."""
        it = copy.copy(self)
        if self.design:
            it.design = copy.copy(self.design)
            it.design.blocks = [ColorBlock(copy.copy(b.thread), b.start, b.records) for b in self.design.blocks]
        it.erases = list(self.erases)
        it.hidden = set(self.hidden)
        it.removed = set(self.removed)
        it.recolors = list(self.recolors)
        if self.text is not None:
            it.text = dict(self.text)
        return it


# --------------------------------------------------------------------------- repère

def normalize(des: Design):
    """Motif lu dans un fichier -> repère d'affichage, centré sur 0. Retourne (motif, centre)."""
    out = Design(notes=des.notes, hoop_rotated=1, hoop_name=des.hoop_name, hoop_group=des.hoop_group,
                 hoop_size=des.hoop_size)
    rot = des.hoop_rotated == 0
    for b in des.blocks:
        recs = [r if r[0] == TRIM else (r[0], r[2], -r[1]) for r in b.records] if rot else list(b.records)
        out.blocks.append(ColorBlock(copy.copy(b.thread), to_display(des, *b.start), recs))
    if not out.blocks:
        return out, (0.0, 0.0)
    x0, y0, x1, y1 = out.bbox()
    cx, cy = round((x0 + x1) / 2), round((y0 + y1) / 2)
    for b in out.blocks:
        b.start = (b.start[0] - cx, b.start[1] - cy)
    return out, (float(cx), float(cy))


def _abs_points(block: ColorBlock):
    """(types, positions absolues) des enregistrements d'un bloc ; la position 0 est le départ."""
    kinds = [r[0] for r in block.records]
    d = np.array([(0, 0) if r[0] == TRIM else (r[1], r[2]) for r in block.records], float).reshape(-1, 2)
    pos = np.vstack([[block.start], block.start + np.cumsum(d, 0)]) if len(d) else np.array([block.start], float)
    return kinds, pos


def positions(block: ColorBlock):
    """Positions absolues du départ et de chaque enregistrement (Nx2)."""
    return _abs_points(block)[1]


def _rebuild(thread, kinds, pos):
    """Positions absolues (arrondies au 0,1 mm) -> bloc à enregistrements relatifs."""
    p = np.round(pos).astype(int)
    start = (int(p[0, 0]), int(p[0, 1]))
    recs = []
    for i, k in enumerate(kinds):
        if k == TRIM:
            recs.append((TRIM,))
        else:
            dx, dy = int(p[i + 1, 0] - p[i, 0]), int(p[i + 1, 1] - p[i, 1])
            recs.append((k, dx, dy))
    return ColorBlock(thread, start, recs)


def place(item: Item):
    """Blocs de l'élément dans le repère du cercle (rotation, échelle, position)."""
    out = []
    if not item.design:
        return out
    for b in item.design.blocks:
        kinds, pos = _abs_points(b)
        out.append(_rebuild(b.thread, kinds, item.to_world(pos)))
    return out


def compose(items, merge=False):
    """Motif final. Retourne (Design, [(n° élément, n° fil local)] pour chaque bloc).

    merge=True (enregistrement) : deux blocs consécutifs du même fil sont réunis, avec une coupe
    et un saut entre eux, pour éviter un changement de fil inutile."""
    des = Design(notes="Créé avec Brodilume", hoop_rotated=1)
    owners = []
    for ii, it in enumerate(items):
        if not it.visible:
            continue
        for bi, b in enumerate(place(it)):
            if not b.records:
                continue
            if merge and des.blocks and des.blocks[-1].thread == b.thread:
                _append(des.blocks[-1], b)
                continue
            des.blocks.append(b)
            owners.append((ii, bi))
    return des, owners


def _end(block):
    x, y = block.start
    for r in block.records:
        if r[0] != TRIM:
            x += r[1]
            y += r[2]
    return x, y


def _append(a: ColorBlock, b: ColorBlock):
    ex, ey = _end(a)
    a.records = a.records + [(TRIM,), (JUMP, b.start[0] - ex, b.start[1] - ey)] + b.records


# --------------------------------------------------------------------------- gomme

def inside(pts, poly):
    """Points (Nx2) à l'intérieur du polygone (Mx2), règle pair-impair."""
    pts = np.asarray(pts, float)
    poly = np.asarray(poly, float)
    x, y = pts[:, 0][:, None], pts[:, 1][:, None]
    x0, y0 = poly[:, 0][None], poly[:, 1][None]
    x1, y1 = np.roll(poly[:, 0], -1)[None], np.roll(poly[:, 1], -1)[None]
    cross = ((y0 > y) != (y1 > y)) & (x < (x1 - x0) * (y - y0) / np.where(y1 == y0, 1e-9, y1 - y0) + x0)
    return cross.sum(1) % 2 == 1


def erase_block(block: ColorBlock, poly) -> ColorBlock | None:
    """Retire les points du bloc tombant dans le polygone ; coupe + saut par-dessus le trou."""
    kinds, pos = _abs_points(block)
    if not kinds:
        return block
    return remove_points(block, inside(pos, poly))


def remove_points(block: ColorBlock, hit) -> ColorBlock | None:
    """Retire les points marqués (hit[k] : k-ième position, 0 = départ) ; coupe + saut par-dessus."""
    kinds, pos = _abs_points(block)
    hit = np.asarray(hit, bool)
    if not kinds or not hit.any():
        return block
    out_k, out_p = [], [pos[0]]
    gap = bool(hit[0])
    if gap:
        out_p = []
    for i, k in enumerate(kinds):
        p = pos[i + 1]
        if k == TRIM:
            if out_p and out_k and out_k[-1] != TRIM:
                out_k.append(TRIM)
                out_p.append(out_p[-1])
            continue
        if hit[i + 1]:
            gap = True
            continue
        if hit[i]:                        # ce point part de la zone gommée : on y saute
            gap = True
        if not out_p:                     # premier point gardé : nouveau départ
            out_p = [p]
            gap = False
            continue
        if gap:                           # on saute par-dessus la partie gommée
            if not out_k or out_k[-1] != TRIM:
                out_k.append(TRIM)
                out_p.append(out_p[-1])
            out_k.append(JUMP)
            out_p.append(p)
            gap = False
            continue
        out_k.append(k)
        out_p.append(p)
    while out_k and out_k[-1] in (TRIM, JUMP):  # pas de coupe ou de saut pendant en fin de bloc
        out_k.pop()
        out_p.pop()
    if not any(k == STITCH for k in out_k):
        return None
    # le tableau des positions a un élément de plus que les types : out_p[0] est le départ
    return _rebuild(block.thread, out_k, np.array(out_p, float))


def thread_key(thread):
    return (thread.brand, thread.code, tuple(thread.rgb))


def erase(design: Design, poly, only=None) -> Design:
    """Gomme un polygone (repère local) ; only = thread_key du seul fil à gommer (sinon tous)."""
    out = copy.copy(design)
    out.blocks = []
    for b in design.blocks:
        if only is not None and thread_key(b.thread) != only:
            out.blocks.append(b)
            continue
        nb = erase_block(b, poly)
        if nb is not None:
            out.blocks.append(nb)
    return out


def apply_edits(item: Item, design: Design) -> Design:
    """Nouvelle génération d'une image : on y refait les suppressions et la gomme de l'élément."""
    if item.removed:
        design.blocks = [b for b in design.blocks if thread_key(b.thread) not in item.removed]
    for poly, key in item.erases:
        design = erase(design, np.asarray(poly) * item.gen_width * 10, key)
    return design


def hull(points, margin=3.0):
    """Polygone convexe autour de points (Nx2), élargi de `margin` : mémorise une partie supprimée."""
    pts = np.unique(np.round(np.asarray(points, float), 1), axis=0)
    if len(pts) < 3:
        c = pts.mean(0)
        return np.array([c + (-margin, -margin), c + (margin, -margin), c + (margin, margin),
                         c + (-margin, margin)])
    pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]

    def half(seq):
        out = []
        for p in seq:
            while len(out) >= 2 and np.cross(out[-1] - out[-2], p - out[-2]) <= 0:
                out.pop()
            out.append(p)
        return out
    h = np.array(half(pts)[:-1] + half(pts[::-1])[:-1])
    c = h.mean(0)
    d = h - c
    n = np.hypot(d[:, 0], d[:, 1])[:, None]
    return h + d / np.where(n == 0, 1, n) * margin


def merge_closest_colors(design: Design):
    """Une couleur de moins : les deux fils les plus proches deviennent le même (le plus utilisé).
    Retourne (fil retiré, fil gardé) ou None."""
    keys = {}
    for b in design.blocks:
        k = thread_key(b.thread)
        n = sum(1 for r in b.records if r[0] == STITCH)
        keys.setdefault(k, [b.thread, 0])[1] += n
    if len(keys) < 2:
        return None
    ks = list(keys)
    best = None
    for i in range(len(ks)):
        for j in range(i + 1, len(ks)):
            a, b = np.array(ks[i][2], float), np.array(ks[j][2], float)
            d = np.abs(a - b).sum()
            if best is None or d < best[0]:
                best = (d, ks[i], ks[j])
    _, ka, kb = best
    keep, drop = (ka, kb) if keys[ka][1] >= keys[kb][1] else (kb, ka)
    t = keys[keep][0]
    blocks = []
    for b in design.blocks:
        nb = ColorBlock(t, b.start, b.records) if thread_key(b.thread) == drop else b
        if blocks and thread_key(blocks[-1].thread) == thread_key(nb.thread):
            last = ColorBlock(blocks[-1].thread, blocks[-1].start, list(blocks[-1].records))
            _append(last, nb)
            blocks[-1] = last
        else:
            blocks.append(nb)
    design.blocks = blocks
    return keys[drop][0], t
