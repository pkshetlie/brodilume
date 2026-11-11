"""Conversion d'une image en broderie (remplissage tatami par couleur).

Coordonnées de travail : X vers la droite, Y vers le bas, unité 0,1 mm.
Le fichier est écrit dans ce même repère, cercle en paysage, comme les
fichiers enregistrés par le logiciel (vérifié à l'ouverture dans le logiciel).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

from .format import Design, ColorBlock, Thread, STITCH, JUMP, TRIM
from . import threads as thr

RES = 2  # 1 pixel de travail = 0,2 mm


@dataclass
class Settings:
    width_mm: float = 100.0        # largeur finale du motif
    colors: int = 4                # nombre de couleurs de fil (hors fond)
    remove_background: bool = True   # ne pas broder le fond extérieur (couleur du bord)
    row_spacing_mm: float = 0.4    # écart entre rangs du remplissage (densité)
    stitch_mm: float = 4.0         # longueur des points de remplissage
    min_area_mm2: float = 3.0      # zones plus petites fondues dans la couleur voisine
    smooth_mm: float = 0.6         # lissage de l'image et des contours
    jump_mm: float = 3.0           # au-delà : coupe + saut au lieu d'un point de liaison
    angle_deg: float = 45.0        # angle du remplissage
    underlay: bool = True          # sous-couche (stabilise le tissu, couvre mieux)
    details: int = 1               # petits détails effacés par le lissage : 0 aucun, 1 éclats, 2 tous
    satin: bool = False            # point satin le long des traits (texte) au lieu du tatami
    # fusions de couleurs demandées : [(polygone local / (largeur*10) ou None, fil source, fil gardé)]
    # fil = (marque, code, rgb) ; fil gardé = (marque, code, nom, rgb)
    recolor: list = field(default_factory=list)
    thread_range: str | None = thr.DEFAULT_RANGE   # None : couleurs exactes de l'image
    notes: str = ""


# --------------------------------------------------------------------------- image -> zones

def _kmeans(rgb: np.ndarray, k: int, iters: int = 15):
    """Réduction des couleurs : k-means avec initialisation par points les plus éloignés."""
    px = rgb.reshape(-1, 3)
    rng = np.random.default_rng(0)
    sample = px[rng.choice(len(px), min(len(px), 20000), replace=False)]
    q = (sample // 16).astype(np.int32)
    keys = q[:, 0] * 256 + q[:, 1] * 16 + q[:, 2]
    centers = [sample[np.bincount(keys).argmax() == keys][0]]
    for _ in range(1, k):
        dist = np.min([((sample - c) ** 2).sum(1) for c in centers], axis=0)
        centers.append(sample[dist.argmax()])
    centers = np.array(centers, dtype=np.float32)
    for _ in range(iters):
        lab = ((sample[:, None, :] - centers[None]) ** 2).sum(2).argmin(1)
        for j in range(k):
            if (lab == j).any():
                centers[j] = sample[lab == j].mean(0)
    full = np.empty(len(px), dtype=np.int32)
    for i in range(0, len(px), 200000):
        full[i:i + 200000] = ((px[i:i + 200000, None, :] - centers[None]) ** 2).sum(2).argmin(1)
    return full.reshape(rgb.shape[:2]), np.round(centers).astype(int)


def segment(img: Image.Image, s: Settings):
    """Retourne une liste de (rgb, masque booléen) en pixels de travail."""
    return segment_full(img, s)[0]


def segment_full(img: Image.Image, s: Settings):
    """Zones à remplir [(rgb, masque)] et détails fins à piquer en point droit [(rgb, masque)]."""
    img = img.convert("RGBA")
    w_px = max(8, int(round(s.width_mm * 10 / RES)))
    h_px = max(8, int(round(img.height * w_px / img.width)))
    img = img.resize((w_px, h_px), Image.LANCZOS)
    arr = np.asarray(img).astype(np.float32)
    alpha = arr[..., 3] / 255.0
    rgb = arr[..., :3] * alpha[..., None] + 255 * (1 - alpha[..., None])  # fond blanc sous la transparence
    transparent = alpha < 0.5
    raw = rgb.copy()  # image non lissée : sert à retrouver les petits détails

    # 1. on gomme la texture fine de l'image (reflets, grain) avant de réduire les couleurs
    sm_px = max(0.0, s.smooth_mm * 10 / RES)
    if sm_px >= 1:
        size = int(sm_px) * 2 + 1
        rgb = np.asarray(Image.fromarray(rgb.astype(np.uint8)).filter(ImageFilter.MedianFilter(size))).astype(np.float32)

    n = s.colors + (1 if s.remove_background else 0)
    idx, pal = _kmeans(rgb, max(1, n))

    bg = None
    if s.remove_background:
        if transparent.any():
            bg = np.bincount(idx[transparent]).argmax()
        else:
            border = np.concatenate([idx[0], idx[-1], idx[:, 0], idx[:, -1]])
            bg = np.bincount(border).argmax()
        idx[transparent] = bg

    # 2. contours lissés : chaque pixel prend la couleur majoritaire autour de lui
    if sm_px >= 0.5:
        labels = np.unique(idx)
        score = np.stack([ndimage.gaussian_filter((idx == c).astype(np.float32), sm_px) for c in labels])
        idx = labels[score.argmax(0)]
        if bg is not None:
            idx[transparent] = bg

    # 3. les petits îlots sont absorbés par la couleur qui les entoure (pas de trous)
    min_px = s.min_area_mm2 * 100 / (RES * RES)
    for _ in range(3):
        changed = False
        for c in np.unique(idx):
            lab, nl = ndimage.label(idx == c)
            if nl == 0:
                continue
            sizes = ndimage.sum(np.ones_like(lab), lab, range(1, nl + 1))
            for k, sl in enumerate(ndimage.find_objects(lab)):
                if sl is None or sizes[k] >= min_px:
                    continue
                sl = tuple(slice(max(0, a.start - 2), a.stop + 2) for a in sl)
                comp = lab[sl] == k + 1
                ring = ndimage.binary_dilation(comp, iterations=2) & ~comp
                around = idx[sl][ring]
                if around.size:
                    idx[sl][comp] = np.bincount(around).argmax()
                    changed = True
        if not changed:
            break

    # 3 bis. petits détails (éclats, étoiles, reflets) effacés par le lissage : on les rend
    idx, lines = _recover_details(idx, raw, pal, transparent, s) if s.details > 0 else (idx, [])

    # 4. fond = uniquement la couleur du bord *reliée au bord* (ou transparente) : un blanc
    #    à l'intérieur du motif (yeux, reflets, lettres évidées…) reste brodé
    keep_out = np.zeros(idx.shape, bool)
    if bg is not None:
        lab, _ = ndimage.label(idx == bg)
        edge = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1], lab[transparent]]))
        keep_out = np.isin(lab, edge[edge > 0]) | transparent

    # 5. zones à broder ; léger recouvrement (0,2 mm) entre couleurs voisines pour éviter les jours
    zones = []
    for c in np.unique(idx):
        m = (idx == c) & ~keep_out
        if m.sum() < min_px:
            continue
        m = m | (ndimage.binary_dilation(m, iterations=1) & ~keep_out)
        zones.append((tuple(int(v) for v in pal[c]), m))
    zones.sort(key=lambda z: -z[1].sum())  # grandes zones d'abord, détails par-dessus
    lines = [(tuple(int(v) for v in pal[c]), m) for c, m in lines]  # même sur le fond retiré
    return zones, [l for l in lines if l[1].any()]


def _recover_details(idx, raw, pal, transparent, s: Settings):
    """Petits détails effacés par le lissage et la réduction des couleurs.

    1. Petites formes pleines (cœur d'une étoile, point de lumière) d'une couleur franchement
       différente de ce qui les entoure : rendues à la zone de leur couleur.
    2. Traits fins plus clairs ou plus foncés que leur entourage (rayons d'étoile, éclats,
       reflets en trait) : repérés sur la luminosité de l'image d'origine (« chapeau haut de
       forme »), puis piqués en point droit avec la couleur de fil qui les fait ressortir.
    """
    h, w = idx.shape
    raw_idx = np.empty(h * w, dtype=np.int32)
    px = raw.reshape(-1, 3)
    for i in range(0, len(px), 200000):
        raw_idx[i:i + 200000] = ((px[i:i + 200000, None, :] - pal[None]) ** 2).sum(2).argmin(1)
    raw_idx = raw_idx.reshape(h, w)
    raw_idx[transparent] = idx[transparent]

    tiny = max(4, 0.25 * 100 / (RES * RES))      # 0,25 mm² : en dessous, c'est du grain
    thick_r = 0.6 * 10 / RES                      # demi-largeur à partir de laquelle on remplit
    lum_pal = pal @ np.array([0.299, 0.587, 0.114])

    # 1. petites formes pleines
    for c in np.unique(raw_idx):
        lost = (raw_idx == c) & (idx != c)
        lab, n = ndimage.label(lost, structure=np.ones((3, 3)))
        for k, sl in enumerate(ndimage.find_objects(lab)):
            sl = tuple(slice(max(0, a.start - 3), a.stop + 3) for a in sl)
            comp = lab[sl] == k + 1
            if comp.sum() < tiny or max(comp.shape) * RES / 10 > 12:
                continue
            dt = ndimage.distance_transform_edt(comp)
            if dt.max() < thick_r:
                continue
            ring = ndimage.binary_dilation(comp, iterations=2) & ~comp
            around = idx[sl][ring]
            around = around[around != c]
            if around.size == 0:
                continue
            dom = np.bincount(around).argmax()
            # entourée d'une seule couleur (pas une frange entre deux couleurs) et contrastée
            if (around == dom).mean() < 0.9 or np.abs(pal[c] - pal[dom]).sum() < 90:
                continue
            thick = ndimage.binary_dilation(dt >= thick_r, iterations=int(thick_r)) & comp
            idx[sl][thick] = c

    # 2. traits fins clairs / foncés
    lum = raw @ np.array([0.299, 0.587, 0.114])
    size = int(round(1.4 * 10 / RES)) | 1         # plus étroit que 1,4 mm = trait fin
    lines = {}
    # niveau 1 : seulement les éclats clairs bien marqués (étoiles, étincelles, points de lumière)
    # niveau 2 : aussi les liserés, reflets en trait et traits foncés
    passes = (True,) if s.details < 2 else (True, False)
    for bright in passes:
        top = ndimage.white_tophat(lum, size=size) if bright else ndimage.black_tophat(lum, size=size)
        mask = (top > (40 if s.details >= 2 else 75)) & ~transparent
        lab, n = ndimage.label(mask, structure=np.ones((3, 3)))
        for k, sl in enumerate(ndimage.find_objects(lab)):
            comp = lab[sl] == k + 1
            span = max(comp.shape) * RES / 10
            if comp.sum() < tiny or span < 1.0 or span > (25 if s.details >= 2 else 12):
                continue
            under = np.bincount(idx[sl][comp], minlength=len(pal)).argmax()
            target = lum[sl][comp].mean()
            # fil le plus proche de la luminosité du trait, et qui ressort sur la zone en dessous
            ok = [j for j in range(len(pal))
                  if (lum_pal[j] - lum_pal[under] > 25 if bright else lum_pal[under] - lum_pal[j] > 25)]
            if not ok:
                continue
            col = raw[sl][comp].mean(0)
            c = min(ok, key=lambda j: np.abs(pal[j] - col).sum() + abs(lum_pal[j] - target))
            m = lines.setdefault(c, np.zeros((h, w), bool))
            m[sl] |= comp
    return idx, list(lines.items())


def background_color(img: Image.Image):
    """Couleur dominante du bord de l'image, ou None si le bord est transparent."""
    img = img.convert("RGBA")
    img.thumbnail((400, 400))
    a = np.asarray(img)
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    if (border[:, 3] < 128).mean() > 0.5:
        return None
    q = (border[:, :3] // 24).astype(int)
    keys = q[:, 0] * 10000 + q[:, 1] * 100 + q[:, 2]
    k = np.bincount(keys - keys.min()).argmax() + keys.min()
    return tuple(int(v) for v in border[keys == k][:, :3].mean(0))


def suggest_colors(img: Image.Image, s: Settings, kmax: int = 12):
    """Nombre de couleurs conseillé pour une image : le plus petit qui la reproduit fidèlement
    (écart de couleur moyen faible) ou au-delà duquel une couleur de plus n'apporte presque rien.
    Retourne (n, [(k, écart moyen)])."""
    im = img.convert("RGBA")
    im.thumbnail((240, 240))
    arr = np.asarray(im).astype(np.float32)
    a = arr[..., 3:] / 255.0
    rgb = arr[..., :3] * a + 255 * (1 - a)
    rgb = np.asarray(Image.fromarray(rgb.astype(np.uint8)).filter(ImageFilter.MedianFilter(3))).astype(np.float32)
    px = rgb.reshape(-1, 3)
    keep = arr.reshape(-1, 4)[:, 3] >= 128
    if s.remove_background:
        bg = background_color(img)
        if bg is not None:  # fond = couleur du bord reliée au bord (pas le blanc à l'intérieur)
            near = np.abs(rgb - np.array(bg, np.float32)).sum(2) <= 45
            lab, _ = ndimage.label(near)
            edge = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
            keep &= ~np.isin(lab, edge[edge > 0]).ravel()
    # les pixels de bord (mélange de deux couleurs, anticrénelage) ne sont pas de vraies couleurs
    spread = np.max([ndimage.maximum_filter(rgb[..., c], 3) - ndimage.minimum_filter(rgb[..., c], 3)
                     for c in range(3)], axis=0)
    flat = spread < 60
    if (keep & flat.ravel()).sum() > 200:
        keep &= flat.ravel()
    px = px[keep]
    if len(px) < 50:
        return s.colors, []
    rng = np.random.default_rng(0)
    px = px[rng.choice(len(px), min(len(px), 6000), replace=False)]
    errs = []
    for k in range(1, kmax + 1):
        lab, cen = _kmeans(px.reshape(-1, 1, 3), k, iters=8)
        dist = np.sqrt(((px - cen[lab.ravel()]) ** 2).sum(1))
        e = float(0.5 * dist.mean() + 0.5 * np.percentile(dist, 97))  # moyenne + petits détails
        errs.append((k, e))
    best = kmax
    for i, (k, e) in enumerate(errs):
        gains = [(errs[j][1] - errs[j + 1][1]) / max(1e-6, errs[j][1]) for j in (i, i + 1) if j + 1 < len(errs)]
        # assez fidèle, ou les deux couleurs suivantes n'apportent presque plus rien
        if e < 25 or (k >= 2 and len(gains) == 2 and max(gains) < 0.08):
            best = k
            break
    return best, errs


# --------------------------------------------------------------------------- remplissage

def _runs(mask: np.ndarray, spacing_mm: float):
    """Rangs horizontaux : liste de (rang, x0, x1, composante, y) en unités."""
    lab, _ = ndimage.label(mask)
    step = max(1.0, spacing_mm * 10 / RES)
    runs = []
    k = 0
    y = step / 2
    while y < mask.shape[0]:
        row = int(y)
        line = mask[row]
        if line.any():
            d = np.diff(np.concatenate([[0], line.astype(np.int8), [0]]))
            for a, b in zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]):
                runs.append((k, a * RES, b * RES, int(lab[row, a]), row * RES))
        k += 1
        y += step
    return runs


def _order(runs, start_pt):
    """Ordonne les rangs en serpentin, composante par composante (glouton)."""
    by_row = {}
    for i, r in enumerate(runs):
        by_row.setdefault(r[0], []).append(i)
    left = set(range(len(runs)))
    pos = start_pt
    path = []

    def near_end(i, p):
        _, x0, x1, _, y = runs[i]
        d0 = math.hypot(x0 - p[0], y - p[1])
        d1 = math.hypot(x1 - p[0], y - p[1])
        return (d0, True) if d0 <= d1 else (d1, False)

    cur = None
    while left:
        nxt = None
        if cur is not None:
            k, x0, x1, comp, _ = runs[cur]
            cand = [j for j in by_row.get(k + 1, []) if j in left and runs[j][3] == comp
                    and runs[j][1] < x1 and runs[j][2] > x0]
            if cand:
                nxt = min(cand, key=lambda j: near_end(j, pos)[0])
        if nxt is None:
            comp = runs[cur][3] if cur is not None else None
            pool = [j for j in left if runs[j][3] == comp] or list(left)
            nxt = min(pool, key=lambda j: near_end(j, pos)[0])
        ltr = near_end(nxt, pos)[1]
        path.append((nxt, ltr))
        left.discard(nxt)
        _, x0, x1, _, y = runs[nxt]
        pos = (x1, y) if ltr else (x0, y)
        cur = nxt
    return path


def segment_inside(mask, p, q, res=RES):
    """Le segment p-q (unités) reste-t-il dans le masque (pixels de `res` unités) ?"""
    n = max(2, int(math.hypot(q[0] - p[0], q[1] - p[1]) / (res / 2)) + 1)
    h, w = mask.shape
    for t in np.linspace(0, 1, n):
        x = int((p[0] + (q[0] - p[0]) * t) / res)
        y = int((p[1] + (q[1] - p[1]) * t) / res)
        if not (0 <= x < w and 0 <= y < h and mask[y, x]):
            return False
    return True


def _tatami(mask, spacing_mm, stitch_mm, angle_deg, jump_mm, start=(0, 0)):
    """Remplissage d'un masque. Opérations absolues ('s'|'move', x, y) dans le repère du masque."""
    ang = angle_deg % 180
    rot = ndimage.rotate(mask.astype(np.uint8), ang, order=0, reshape=True) > 0 if ang else mask
    runs = _runs(rot, spacing_mm)
    if not runs:
        return []
    h, w = mask.shape
    H, W = rot.shape
    c, sn = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    cx, cy, CX, CY = w * RES / 2, h * RES / 2, W * RES / 2, H * RES / 2

    def back(x, y):  # repère tourné -> repère du masque
        if not ang:
            return x, y
        dx, dy = x - CX, y - CY
        return cx + c * dx - sn * dy, cy + sn * dx + c * dy

    def fwd(x, y):  # repère du masque -> repère tourné
        if not ang:
            return x, y
        dx, dy = x - cx, y - cy
        return CX + c * dx + sn * dy, CY - sn * dx + c * dy

    L = stitch_mm * 10
    inside = ndimage.binary_dilation(rot, iterations=1)  # bouts de rang posés sur le bord : tolérance 1 px
    ops, last = [], None
    for idx, ltr in _order(runs, fwd(*start)):
        k, x0, x1, comp, y = runs[idx]
        a, b = (x0, x1) if ltr else (x1, x0)
        phase = (k % 3) * L / 3          # décalage des points d'un rang à l'autre (aspect tatami)
        lo, hi = min(a, b), max(a, b)
        g = math.ceil((lo + 10 - phase) / L) * L + phase
        mids = []
        while g < hi - 10:               # pas de point de moins de 1 mm en bout de rang
            mids.append(g)
            g += L
        if not ltr:
            mids.reverse()
        pts = [(a, y)] + [(m, y) for m in mids] + [(b, y)]
        # liaison piquée seulement si elle est courte ET reste dans la forme ; sinon coupe + saut
        # (sans cela, le fil passe au-dessus du vide, ex. entre les jambes d'un M)
        far = last is None or comp != last[2] or math.hypot(pts[0][0] - last[0], pts[0][1] - last[1]) > jump_mm * 10 \
            or not segment_inside(inside, last[:2], pts[0])
        ops.append(("move" if far else "s", *back(*pts[0])))
        ops += [("s", *back(*p)) for p in pts[1:]]
        last = (pts[-1][0], pts[-1][1], comp)
    return ops


def fill_points(mask: np.ndarray, s: Settings):
    """Remplit chaque îlot du masque : sous-couche puis remplissage. Coordonnées en unités."""
    lab, n = ndimage.label(mask)
    slices = ndimage.find_objects(lab)
    left = set(range(1, n + 1))
    pos = (0.0, 0.0)
    ops = []
    underlay_min = 20 * 100 / (RES * RES)  # sous-couche à partir de 20 mm²
    inset = max(1, round(0.5 * 10 / RES))  # 0,5 mm en retrait du bord

    def center(k):
        sl = slices[k - 1]
        return ((sl[1].start + sl[1].stop) * RES / 2, (sl[0].start + sl[0].stop) * RES / 2)

    while left:
        k = min(left, key=lambda j: math.hypot(center(j)[0] - pos[0], center(j)[1] - pos[1]))
        left.discard(k)
        sl = slices[k - 1]
        oy, ox = sl[0].start * RES, sl[1].start * RES
        comp = np.pad(lab[sl] == k, 1)
        oy -= RES
        ox -= RES
        local = (pos[0] - ox, pos[1] - oy)
        seqs = []
        if s.underlay and comp.sum() >= underlay_min:
            inner = ndimage.binary_erosion(comp, iterations=inset)
            seqs.append(_tatami(inner, 2.0, 4.0, s.angle_deg + 90, s.jump_mm, local))
        seqs.append(_tatami(comp, s.row_spacing_mm, s.stitch_mm, s.angle_deg, s.jump_mm,
                            seqs[-1][-1][1:] if seqs and seqs[-1] else local))
        for seq in seqs:
            if not seq:
                continue
            seq = [(op, x + ox, y + oy) for op, x, y in seq]
            # liaison courte entre sous-couche et remplissage : simple point (sera recouvert)
            if ops and seq[0][0] == "move" and \
                    math.hypot(seq[0][1] - ops[-1][1], seq[0][2] - ops[-1][2]) <= s.jump_mm * 10 and \
                    segment_inside(ndimage.binary_dilation(comp, iterations=1),
                                   (ops[-1][1] - ox, ops[-1][2] - oy), (seq[0][1] - ox, seq[0][2] - oy)):
                seq[0] = ("s", seq[0][1], seq[0][2])
            ops += seq
        if ops:
            pos = (ops[-1][1], ops[-1][2])
    return ops


def satin_points(mask: np.ndarray, s: Settings):
    """Point satin le long des traits (lettres) ; une forme trop large pour du satin est remplie en tatami."""
    from .satin import satin_ops
    lab, n = ndimage.label(mask)
    slices = ndimage.find_objects(lab)
    left = set(range(1, n + 1))
    pos, ops = (0.0, 0.0), []
    spacing = min(0.6, max(0.25, s.row_spacing_mm))

    def center(k):
        sl = slices[k - 1]
        return ((sl[1].start + sl[1].stop) * RES / 2, (sl[0].start + sl[0].stop) * RES / 2)

    while left:
        k = min(left, key=lambda j: math.hypot(center(j)[0] - pos[0], center(j)[1] - pos[1]))
        left.discard(k)
        sl = slices[k - 1]
        oy, ox = (sl[0].start - 1) * RES, (sl[1].start - 1) * RES
        comp = np.pad(lab[sl] == k, 1)
        local = (pos[0] - ox, pos[1] - oy)
        seq = satin_ops(comp, RES, spacing, local,
                        fill_fallback=lambda m: _tatami(m, s.row_spacing_mm, s.stitch_mm, s.angle_deg, s.jump_mm))
        if seq is None:  # trait trop large : tatami (avec sous-couche) comme pour une image
            seq = fill_points(comp, s)
        ops += [(op, x + ox, y + oy) for op, x, y in seq]
        if ops:
            pos = (ops[-1][1], ops[-1][2])
    return ops


def _trace(skel: np.ndarray):
    """Découpe un squelette d'un pixel d'épaisseur en chemins [(x, y), ...] (pixels)."""
    pts = set(zip(*np.nonzero(skel)))
    nb = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

    def neigh(p):
        return [(p[0] + a, p[1] + b) for a, b in nb if (p[0] + a, p[1] + b) in pts]
    paths = []
    while pts:
        ends = [p for p in pts if len(neigh(p)) <= 1]
        cur = min(ends) if ends else min(pts)
        path = [cur]
        pts.discard(cur)
        while True:
            nx = neigh(cur)
            if not nx:
                break
            # on continue tout droit de préférence (moins d'angles dans le tracé)
            if len(path) > 1:
                d = (cur[0] - path[-2][0], cur[1] - path[-2][1])
                nx.sort(key=lambda q: -((q[0] - cur[0]) * d[0] + (q[1] - cur[1]) * d[1]))
            cur = nx[0]
            pts.discard(cur)
            path.append(cur)
        paths.append([(x, y) for y, x in path])
    return paths


def line_points(mask: np.ndarray, s: Settings, start=(0.0, 0.0)):
    """Détails fins (rayons d'étoile, traits) : point droit triple le long de leur squelette."""
    from skimage.morphology import skeletonize
    lab, n = ndimage.label(mask, structure=np.ones((3, 3)))
    paths = []
    for k, sl in enumerate(ndimage.find_objects(lab)):
        comp = lab[sl] == k + 1
        oy, ox = sl[0].start, sl[1].start
        for path in _trace(skeletonize(np.pad(comp, 1))):
            path = [((x - 1 + ox + 0.5) * RES, (y - 1 + oy + 0.5) * RES) for x, y in path]
            if len(path) == 1:  # point isolé : petit trait pour qu'il reste visible
                x, y = path[0]
                path = [(x - 3, y), (x + 3, y)]
            paths.append(path)
    step = 12  # 1,2 mm par point : suit les courbes des petits motifs
    ops, pos = [], start
    while paths:
        i = min(range(len(paths)), key=lambda j: min(math.dist(pos, paths[j][0]), math.dist(pos, paths[j][-1])))
        path = paths.pop(i)
        if math.dist(pos, path[-1]) < math.dist(pos, path[0]):
            path.reverse()
        # rééchantillonnage tous les `step`
        pts, acc = [path[0]], 0.0
        for a, b in zip(path, path[1:]):
            acc += math.dist(a, b)
            if acc >= step:
                pts.append(b)
                acc = 0.0
        if pts[-1] != path[-1]:
            pts.append(path[-1])
        if len(pts) < 2:
            pts.append((pts[0][0] + 3, pts[0][1]))
        triple = pts + pts[-2::-1] + pts[1:]  # aller, retour, aller : trait bien couvrant
        ops.append(("move", *triple[0]))
        ops += [("s", x, y) for x, y in triple[1:]]
        pos = triple[-1]
    return ops


# --------------------------------------------------------------------------- points -> enregistrements

def _lock(recs):
    # point d'arrêt : petit aller-retour sur place
    recs += [(STITCH, 2, 0), (STITCH, -2, 0), (STITCH, 2, 0), (STITCH, -2, 0)]


def _stitch_to(recs, cur, x, y, maxlen=120):
    dx, dy = x - cur[0], y - cur[1]
    n = max(1, math.ceil(max(abs(dx), abs(dy)) / maxlen))
    px, py = cur
    for i in range(1, n + 1):
        nx, ny = round(cur[0] + dx * i / n), round(cur[1] + dy * i / n)
        if nx != px or ny != py:
            recs.append((STITCH, nx - px, ny - py))
        px, py = nx, ny
    return (px, py)


def build_block(thread: Thread, ops, offset):
    """ops en coordonnées image ; offset centre le motif dans le cercle."""
    def to_file(x, y):
        return (int(round(x - offset[0])), int(round(y - offset[1])))

    first = to_file(*ops[0][1:])
    recs = []
    cur = first
    _lock(recs)
    for op, x, y in ops[1:]:
        p = to_file(x, y)
        if op == "move":
            _lock(recs)
            recs.append((TRIM,))
            recs.append((JUMP, p[0] - cur[0], p[1] - cur[1]))
            cur = p
            _lock(recs)
        else:
            cur = _stitch_to(recs, cur, *p)
    _lock(recs)
    return ColorBlock(thread, first, recs)


def thread_for(rgb, s: Settings, k: int) -> Thread:
    if s.thread_range:
        t = thr.nearest(rgb, thr.load_range(s.thread_range))
        if t:
            return Thread(t.rgb, code=t.code, name=t.name, brand=t.brand)
    return Thread(tuple(rgb), code="%02X%02X%02X" % tuple(rgb), name="Couleur %d" % (k + 1))


def _apply_recolor(zl, s: Settings, shape):
    """Fusions de couleurs demandées par l'utilisateur, appliquées *avant* le remplissage :
    la zone fusionnée est ensuite brodée d'un seul tenant, comme si l'image avait cette couleur."""
    from PIL import ImageDraw
    h, w = shape
    for poly, src, dst in s.recolor:
        if poly is None:
            area = np.ones(shape, bool)
        else:
            pts = np.asarray(poly, float) * s.width_mm * 10 + (w * RES / 2, h * RES / 2)
            im = Image.new("1", (w, h), 0)
            ImageDraw.Draw(im).polygon([tuple(p) for p in pts / RES], fill=1, outline=1)
            area = np.asarray(im, bool)
        moved_fill, moved_thin = np.zeros(shape, bool), np.zeros(shape, bool)
        for z in zl:
            if (z[0].brand, z[0].code, tuple(z[0].rgb)) == tuple(src[:2]) + (tuple(src[2]),):
                moved_fill |= z[1] & area
                moved_thin |= z[2] & area
                z[1] = z[1] & ~area
                z[2] = z[2] & ~area
        if moved_fill.any() or moved_thin.any():
            brand, code, name, rgb = dst
            zl.append([Thread(tuple(rgb), code=code, name=name, brand=brand), moved_fill, moved_thin])


def image_to_design(img: Image.Image, s: Settings, progress=None) -> Design:
    zones, lines = segment_full(img, s)
    if not zones and not lines:
        raise ValueError("aucune zone à broder trouvée dans l'image")
    shape = (zones or lines)[0][1].shape

    # chaque couleur devient le fil le plus proche de la gamme ; deux couleurs -> même fil : fusion
    zl = [[thread_for(rgb, s, k), mask.copy(), np.zeros(shape, bool)] for k, (rgb, mask) in enumerate(zones)]
    zl += [[thread_for(rgb, s, len(zones) + k), np.zeros(shape, bool), mask.copy()]
           for k, (rgb, mask) in enumerate(lines)]
    _apply_recolor(zl, s, shape)
    merged = {}
    for t, mask, thin in zl:
        key = (t.brand, t.code, tuple(t.rgb))
        if key in merged:
            merged[key][1] |= mask
            merged[key][2] |= thin
        else:
            merged[key] = [t, mask, thin]

    h, w = shape
    offset = (w * RES / 2, h * RES / 2)
    items = list(merged.values())
    # un détail fin est piqué avec sa couleur s'il n'est recouvert par aucune couleur brodée
    # après ; sinon il est reporté à la fin (un changement de fil de plus, mais il reste visible)
    late = []
    for k, it in enumerate(items):
        after = np.zeros(shape, bool)
        for t2, m2, _ in items[k + 1:]:
            after |= m2
        lab, n = ndimage.label(it[2], structure=np.ones((3, 3)))
        if n:
            hidden = np.unique(lab[ndimage.binary_dilation(after, iterations=2) & (lab > 0)])
            if hidden.size:
                late.append((it[0], np.isin(lab, hidden)))
                it[2] = it[2] & ~np.isin(lab, hidden)

    # cercle en paysage (orientation 1), comme les fichiers enregistrés par le logiciel lui-même
    des = Design(notes=s.notes or "Créé par VP4 Studio à partir d'une image", hoop_rotated=1)
    for k, (t, mask, thin) in enumerate(items):
        if progress:
            progress(k, len(items) + len(late))
        ops = (satin_points(mask, s) if s.satin else fill_points(mask, s)) if mask.any() else []
        if thin.any():
            ops += line_points(thin, s, (ops[-1][1], ops[-1][2]) if ops else (0.0, 0.0))
        if ops:
            des.blocks.append(build_block(t, ops, offset))
    for t, thin in late:
        ops = line_points(thin, s)
        # un détail de quelques points ne vaut pas un changement de fil de plus
        if sum(1 for o in ops if o[0] == "s") < 40:
            continue
        last = des.blocks[-1] if des.blocks else None
        blk = build_block(t, ops, offset)
        if last and last.thread == t:  # même fil que le dernier : pas de changement de fil
            end = (last.start[0] + sum(r[1] for r in last.records if r[0] != TRIM),
                   last.start[1] + sum(r[2] for r in last.records if r[0] != TRIM))
            last.records += [(TRIM,), (JUMP, blk.start[0] - end[0], blk.start[1] - end[1])] + blk.records
        else:
            des.blocks.append(blk)
    return des
