"""Aperçu d'un motif (Design) en image."""
from PIL import Image, ImageDraw

from .format import Design, STITCH, JUMP

THREAD_MM = 0.4   # largeur apparente d'un fil de broderie (rayonne 40 ≈ 0,35-0,4 mm)


def to_display(des: Design, x, y):
    # cercle portrait (fichiers exportés) : motif tourné d'un quart de tour
    return (y, -x) if des.hoop_rotated == 0 else (x, y)


def _mix(rgb, target, t):
    return tuple(int(round(c + (g - c) * t)) for c, g in zip(rgb, target))


def draw_thread(dr: ImageDraw.ImageDraw, pts, rgb, width: float, shade: bool = True):
    """Dessine une suite de points (tableau Nx2 en pixels) comme un fil en relief.

    Chaque point devient un brin : bord sombre (ombre entre deux rangs), corps de la couleur
    du fil, reflet clair décalé vers le haut-gauche (lumière rasante sur la rayonne).
    Quand le fil fait moins de 3 pixels de large, un simple trait suffit.
    """
    rgb = tuple(rgb)
    if not shade or width < 3:
        dr.line(pts.ravel().tolist(), fill=rgb, width=max(1, round(width)))
        return
    j = "curve" if width >= 5 else None  # gros plan : jonctions arrondies entre les points
    dr.line(pts.ravel().tolist(), fill=_mix(rgb, (0, 0, 0), 0.45), width=max(1, round(width)), joint=j)
    dr.line(pts.ravel().tolist(), fill=rgb, width=max(1, round(width * 0.62)), joint=j)
    off = width * 0.13
    dr.line((pts - off).ravel().tolist(), fill=_mix(rgb, (255, 255, 255), 0.5), width=max(1, round(width * 0.2)))
    if width >= 10:  # gros plan : trous d'aiguille aux extrémités des points
        r = width * 0.14
        hole = _mix(rgb, (0, 0, 0), 0.6)
        for x, y in pts.tolist():
            dr.ellipse((x - r, y - r, x + r, y + r), fill=hole)


def render(des: Design, width=1200, background="#dce9f5", line=None, show_jumps=False,
           supersample=3) -> Image.Image:
    """Aperçu en relief, lissé par suréchantillonnage. line : épaisseur forcée en pixels (sinon fil réel)."""
    import numpy as np
    segs = []  # (rgb, [points], is_jump)
    for b in des.blocks:
        cur = []
        prev = None
        for op, x, y in b.points():
            p = to_display(des, x, y)
            if op == STITCH or op == "start":
                cur.append(p)
            else:
                if len(cur) > 1:
                    segs.append((b.thread.rgb, cur, False))
                if op == JUMP and prev and show_jumps:
                    segs.append(((150, 150, 150), [prev, p], True))
                cur = [p]
            prev = p
        if len(cur) > 1:
            segs.append((b.thread.rgb, cur, False))
    pts = [p for _, s, _ in segs for p in s]
    if not pts:
        return Image.new("RGB", (width, width // 2), background)
    x0 = min(p[0] for p in pts); x1 = max(p[0] for p in pts)
    y0 = min(p[1] for p in pts); y1 = max(p[1] for p in pts)
    ss = max(1, supersample)
    pad = 30
    sc = (width - 2 * pad) / max(1, x1 - x0)
    height = int((y1 - y0) * sc + 2 * pad)
    img = Image.new("RGB", (width * ss, height * ss), background)
    dr = ImageDraw.Draw(img)
    tw = (line if line else THREAD_MM * 10 * sc) * ss
    for rgb, s, jump in segs:
        a = (np.array(s, float) - (x0, y0)) * sc * ss + pad * ss
        if jump:
            dr.line(a.ravel().tolist(), fill=tuple(rgb), width=ss)
        else:
            draw_thread(dr, a, rgb, tw, shade=line is None)
    return img.reduce(ss) if ss > 1 else img
