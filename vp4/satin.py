"""Point satin le long des traits (texte, formes fines) : la méthode des logiciels de broderie pour les lettres.

Principe :
1. Le masque d'une couleur est affiné à 0,1 mm, puis réduit à son squelette (axe médian) : la ligne
   au milieu de chaque trait, avec en chaque point la demi-largeur du trait (distance au bord).
2. Le squelette devient un graphe : nœuds (bouts de trait, croisements), arêtes (tronçons de trait).
   Les petites branches parasites (empattements, coins) sont élaguées.
3. Chaque tronçon est brodé en satin : des points serrés qui vont d'un bord à l'autre du trait,
   perpendiculaires à sa direction. Les points restent dans le trait (disque inscrit), avec une petite
   compensation de traction pour que le satin atteigne le bord une fois brodé.
4. Parcours sans saut : on part d'un bout de trait ; pour chaque tronçon, un point droit au milieu
   (sous-couche) va jusqu'au nœud suivant, on traite la suite, puis le satin revient au point de départ
   en recouvrant la sous-couche. Une lettre d'un seul tenant se brode donc sans coupe ni saut.
5. Ce que le satin ne couvre pas (coins, empattements élagués) est rempli avant, en petit tatami.

Trait trop large pour du satin (plus de SATIN_MAX_MM) : la forme est remplie en tatami, comme avant.
Coordonnées : unités de 0,1 mm dans le repère du masque (comme fill_points).
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

SATIN_MAX_MM = 7.0      # au-delà, un point de satin est trop long (il s'accroche, il bâille)
PULL_MM = 0.15          # compensation de traction, de chaque côté
UNDERLAY_MM = 1.8       # longueur des points de la sous-couche au milieu du trait
UP = 2                  # affinage du masque : pixels de RES/UP unités


# --------------------------------------------------------------------------- squelette -> graphe

_NB = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def _graph(skel):
    """Squelette (bool) -> (nœuds {id: [(y, x)…]}, arêtes [(n0, n1, [(y, x)…])]).

    Nœud = bout de trait (1 voisin) ou amas de pixels de croisement (3 voisins ou plus).
    Une boucle sans nœud (lettre « o ») reçoit un nœud arbitraire."""
    pts = set(zip(*np.nonzero(skel)))

    def neigh(p):
        return [(p[0] + a, p[1] + b) for a, b in _NB if (p[0] + a, p[1] + b) in pts]

    deg = {p: len(neigh(p)) for p in pts}
    special = {p for p, d in deg.items() if d != 2}
    node_of, nodes = {}, {}
    for p in special:  # amas de pixels spéciaux voisins = un seul nœud
        if p in node_of:
            continue
        nid = len(nodes)
        stack, members = [p], []
        node_of[p] = nid
        while stack:
            q = stack.pop()
            members.append(q)
            for r in neigh(q):
                if r in special and r not in node_of:
                    node_of[r] = nid
                    stack.append(r)
        nodes[nid] = members
    edges, used = [], set()

    def walk(start_node, first, prev):
        path = [prev, first] if prev is not None else [first]
        cur, last = first, prev
        while cur not in node_of:
            used.add(cur)
            nxt = [r for r in neigh(cur) if r != last and r not in used and (r in node_of or deg[r] == 2)]
            if not nxt:
                # bout de boucle revenu au début, ou impasse
                back = [r for r in neigh(cur) if r in node_of]
                if back:
                    path.append(back[0])
                    return node_of[back[0]], path
                return None, path
            # tout droit de préférence
            if last is not None:
                d = (cur[0] - last[0], cur[1] - last[1])
                nxt.sort(key=lambda r: -((r[0] - cur[0]) * d[0] + (r[1] - cur[1]) * d[1]))
            last, cur = cur, nxt[0]
            path.append(cur)
        return node_of[cur], path

    for nid, members in nodes.items():
        for p in members:
            for r in neigh(p):
                if r in node_of or r in used:
                    if r in node_of and node_of[r] != nid and (min(nid, node_of[r]), max(nid, node_of[r]), "direct") \
                            not in used:
                        used.add((min(nid, node_of[r]), max(nid, node_of[r]), "direct"))
                        edges.append((nid, node_of[r], [p, r]))
                    continue
                end, path = walk(nid, r, p)
                if end is not None and len(path) >= 2:
                    edges.append((nid, end, path))
    # boucles sans nœud (o, 0, D sans croisement…)
    rest = [p for p in pts if p not in used and p not in node_of]
    while rest:
        p = rest[0]
        nid = len(nodes)
        nodes[nid] = [p]
        node_of[p] = nid
        nb = neigh(p)
        if nb:
            end, path = walk(nid, nb[0], p)
            if end is not None:
                edges.append((nid, end, path))
        used.add(p)
        rest = [q for q in pts if q not in used and q not in node_of]
    return nodes, edges


def _prune(nodes, edges, dist, factor=3.0, rounds=3):
    """Retire les petites branches qui finissent en bout de trait (coins, empattements, bavures)."""
    for _ in range(rounds):
        deg = {}
        for a, b, _p in edges:
            deg[a] = deg.get(a, 0) + 1
            deg[b] = deg.get(b, 0) + 1
        keep, removed = [], False
        for a, b, path in edges:
            tip = a if deg.get(a) == 1 else b if deg.get(b) == 1 else None
            other = b if tip == a else a
            if tip is not None and deg.get(other, 0) >= 3:
                width = max(dist[p] for p in nodes[other]) if nodes.get(other) else dist[path[0]]
                if len(path) < factor * width:
                    removed = True
                    continue
            keep.append((a, b, path))
        edges = keep
        if not removed:
            break
    return edges


def _merge_chains(edges):
    """Recolle les tronçons qui se suivent à un nœud de passage (2 tronçons) : un trait continu
    (jambe puis diagonale d'un M) ne forme plus qu'un tronçon, dont on repère ensuite les angles vifs."""
    edges = [list(e) for e in edges]
    while True:
        inc = {}
        for i, (a, b, _p) in enumerate(edges):
            inc.setdefault(a, []).append(i)
            inc.setdefault(b, []).append(i)
        node = next((n for n, l in inc.items() if len(l) == 2 and l[0] != l[1]), None)
        if node is None:
            return [tuple(e) for e in edges]
        i, j = inc[node]
        a1, b1, p1 = edges[i]
        a2, b2, p2 = edges[j]
        if b1 != node:                      # e1 orienté pour finir au nœud
            a1, b1, p1 = b1, a1, p1[::-1]
        if a2 != node:                      # e2 orienté pour partir du nœud
            a2, b2, p2 = b2, a2, p2[::-1]
        merged = [a1, b2, list(p1) + list(p2[1:])]
        edges = [e for k, e in enumerate(edges) if k not in (i, j)] + [merged]


# --------------------------------------------------------------------------- géométrie d'un tronçon

def _smooth(path, k=3):
    p = np.asarray(path, float)
    if len(p) < 2 * k + 2:
        return p
    out = p.copy()
    c = np.cumsum(np.vstack([np.zeros((1, 2)), p]), 0)
    out[k:-k] = (c[2 * k + 1:] - c[:-2 * k - 1]) / (2 * k + 1)
    return out


def _resample(p, step):
    """Polyligne -> points tous les `step` (longueur d'arc)."""
    seg = np.hypot(*np.diff(p, axis=0).T)
    s = np.concatenate([[0], np.cumsum(seg)])
    if s[-1] < 1e-6:
        return p[:1]
    n = max(2, int(math.ceil(s[-1] / step)) + 1)
    t = np.linspace(0, s[-1], n)
    return np.stack([np.interp(t, s, p[:, 0]), np.interp(t, s, p[:, 1])], 1)


def _corners(p, hw, max_turn=55.0):
    """Indices des angles vifs (virage de plus de `max_turn` degrés sur environ une largeur de trait)."""
    w = max(3, int(round(1.2 * hw)))
    if len(p) < 2 * w + 3:
        return []
    turn = np.zeros(len(p))
    for i in range(w, len(p) - w):
        v1, v2 = p[i] - p[i - w], p[i + w] - p[i]
        n1, n2 = math.hypot(*v1), math.hypot(*v2)
        if n1 > 0 and n2 > 0:
            turn[i] = math.degrees(math.acos(max(-1.0, min(1.0, float(v1 @ v2) / (n1 * n2)))))
    cuts = []
    for i in np.argsort(-turn):
        if turn[i] < max_turn:
            break
        if all(abs(i - j) > 2 * w for j in cuts):
            cuts.append(int(i))
    return sorted(cuts)


def _trim(p, length, end, keep=0.6):
    """Retire `length` pixels de longueur au bout `end` (0 ou -1), sans enlever plus de 1-keep du tronçon."""
    if len(p) < 4 or length <= 0:
        return p
    q = p if end == -1 else p[::-1]
    seg = np.hypot(*np.diff(q, axis=0).T)
    total = seg.sum()
    length = min(length, total * (1 - keep))
    acc, i = 0.0, len(q) - 1
    while i > 1 and acc + seg[i - 1] <= length:
        acc += seg[i - 1]
        i -= 1
    q = q[:i + 1]
    return q if end == -1 else q[::-1]


def _extend(p, mask, end):
    """Prolonge le tronçon au bout `end` (0 ou -1) jusqu'au bord du trait (fin de lettre)."""
    q = p if end == -1 else p[::-1]
    if len(q) < 2:
        return p
    a = q[-min(len(q), 12)]
    b = q[-1]
    d = b - a
    n = math.hypot(*d)
    if n < 1e-6:
        return p
    d = d / n
    h, w = mask.shape
    ext = []
    for k in range(1, 400):
        c = b + d * k * 0.5
        y, x = int(round(c[0])), int(round(c[1]))
        if not (0 <= y < h and 0 <= x < w and mask[y, x]):
            break
        ext.append(c)
    if not ext:
        return p
    ext = np.array(ext)
    return np.vstack([q, ext]) if end == -1 else np.vstack([q, ext])[::-1]


def _columns(p, dist, mask, spacing_px, pull_px):
    """Points gauche / droite du satin le long de la polyligne p (pixels fins)."""
    p = _resample(p, spacing_px)
    if len(p) < 2:
        return None
    tan = np.gradient(p, axis=0)
    tn = np.hypot(tan[:, 0], tan[:, 1])[:, None]
    tan = tan / np.where(tn == 0, 1, tn)
    nor = np.stack([-tan[:, 1], tan[:, 0]], 1)
    h, w = dist.shape
    yi = np.clip(np.round(p[:, 0]).astype(int), 0, h - 1)
    xi = np.clip(np.round(p[:, 1]).astype(int), 0, w - 1)
    d0 = dist[yi, xi]
    # plafond : un peu plus que la demi-largeur habituelle du trait (aux croisements, le bord le plus
    # proche est loin, dans l'autre trait : le satin ne doit pas s'y étaler en éventail)
    inner = d0[d0 > 1.0]
    cap = 1.35 * (np.median(inner) if inner.size else max(1.0, d0.max())) + 1.0
    steps = np.arange(0.5, cap + 0.5, 0.5)

    def reach(sign):
        """Distance jusqu'au bord, de chaque point de l'axe, le long de la normale (côté `sign`)."""
        q = p[:, None, :] + sign * nor[:, None, :] * steps[None, :, None]
        y = np.round(q[..., 0]).astype(int)
        x = np.round(q[..., 1]).astype(int)
        ok = (y >= 0) & (y < h) & (x >= 0) & (x < w)
        inside = np.zeros(ok.shape, bool)
        inside[ok] = mask[y[ok], x[ok]]
        out = ~inside
        first = np.where(out.any(1), out.argmax(1), len(steps))   # 1er pas hors du trait
        return np.where(first > 0, steps[np.maximum(first - 1, 0)], 0.3)

    hl, hr = reach(1) + pull_px, reach(-1) + pull_px
    # bords lissés : pas de dents de scie dues aux pixels
    k = np.ones(3) / 3
    if len(p) >= 3:
        hl = np.concatenate([hl[:1], np.convolve(hl, k, "valid"), hl[-1:]])
        hr = np.concatenate([hr[:1], np.convolve(hr, k, "valid"), hr[-1:]])
    return p + nor * hl[:, None], p - nor * hr[:, None], p


# --------------------------------------------------------------------------- broderie d'une forme

def satin_ops(mask, res, spacing_mm=0.4, start=(0.0, 0.0), fill_fallback=None):
    """Satin d'un masque (pixels de `res` unités). Retourne des opérations ('s'|'move', x, y) en unités,
    ou None si la forme est trop large pour du satin (l'appelant la remplit alors en tatami).

    fill_fallback(sous_masque) -> ops : remplissage des parties non couvertes par le satin."""
    from skimage.morphology import medial_axis
    up = UP
    big = ndimage.zoom(ndimage.gaussian_filter(np.pad(mask, 2).astype(np.float32), 0.6), up, order=1) > 0.5
    px = res / up                          # unités par pixel fin
    skel, dist = medial_axis(big, return_distance=True)
    if not skel.any():
        return None
    if 2 * dist[skel].max() * px > SATIN_MAX_MM * 10:
        return None
    nodes, edges = _graph(skel)
    distd = {p: dist[p] for p in zip(*np.nonzero(skel))}
    edges = _prune(nodes, edges, distd)
    edges = _merge_chains(edges)
    if not edges:
        return None
    spacing_px = spacing_mm * 10 / px
    pull_px = PULL_MM * 10 / px
    deg = {}
    for a, b, _p in edges:
        deg[a] = deg.get(a, 0) + 1
        deg[b] = deg.get(b, 0) + 1

    def to_units(pt):  # pixel fin (y, x) -> unités dans le repère du masque d'origine
        return ((pt[1] + 0.5) * px - 2 * res, (pt[0] + 0.5) * px - 2 * res)

    cols = []   # par arête : ([(gauche, droite) par morceau], axe) en pixels fins, sens a -> b
    for a, b, path in edges:
        hw = float(np.median([dist[q] for q in path]))      # demi-largeur habituelle du trait
        p = _smooth(path, k=max(3, int(round(hw * 0.8))))
        for node, end in ((a, 0), (b, -1)):
            if deg.get(node) == 1:
                # bout de trait : l'axe y fourche vers les coins -> on coupe la courbe, puis tout droit
                p = _extend(_trim(p, 1.2 * hw, end), big, end)
            elif deg.get(node, 0) >= 3:
                # croisement : on s'arrête avant, la zone commune est remplie dessous
                p = _trim(p, 1.2 * hw, end)
        # angle vif dans le tronçon (coin d'un M, pointe d'un V) : un satin par côté, coin rempli dessous
        cuts = _corners(p, hw)
        pieces = []
        for i0, i1 in zip([0] + cuts, cuts + [len(p) - 1]):
            q = p[i0:i1 + 1]
            if i0 > 0:
                q = _trim(q, 1.0 * hw, 0)
            if i1 < len(p) - 1:
                q = _trim(q, 1.0 * hw, -1)
            c = _columns(q, dist, big, spacing_px, pull_px) if len(q) >= 2 else None
            if c is not None:
                pieces.append(c[:2])
        cols.append((pieces, p) if pieces else None)

    # couverture du satin -> parties oubliées (coins, empattements) remplies en premier, dessous
    cover = Image.new("1", (big.shape[1], big.shape[0]), 0)
    dr = ImageDraw.Draw(cover)
    for c in cols:
        if c is None:
            continue
        for L, R in c[0]:
            for i in range(len(L) - 1):
                dr.polygon([(L[i][1], L[i][0]), (L[i + 1][1], L[i + 1][0]), (R[i + 1][1], R[i + 1][0]),
                            (R[i][1], R[i][0])], fill=1)
    left = big & ~ndimage.binary_dilation(np.asarray(cover, bool), iterations=1)
    left = ndimage.binary_opening(left, iterations=1)
    ops = []
    if fill_fallback is not None and left.any():
        lab, n = ndimage.label(left)
        sizes = ndimage.sum(np.ones_like(lab), lab, range(1, n + 1))
        min_px = 0.4 * 100 / (px * px)                     # 0,4 mm²
        keep = np.isin(lab, [k + 1 for k, s in enumerate(sizes) if s >= min_px])
        if keep.any():
            small = ndimage.zoom(keep.astype(np.float32), 1 / up, order=1)[2:-2, 2:-2] > 0.3
            small = small[:mask.shape[0], :mask.shape[1]] & ndimage.binary_dilation(mask, iterations=1)
            if small.any():
                ops += fill_fallback(small)

    # parcours : sous-couche à l'aller, satin au retour ; chaque arête une seule fois
    adj = {}
    for k, (a, b, _p) in enumerate(edges):
        adj.setdefault(a, []).append((k, b, True))
        adj.setdefault(b, []).append((k, a, False))
    done = set()
    seen_nodes = set()
    under_px = UNDERLAY_MM * 10 / px

    def under(axis):
        q = _resample(axis, under_px)
        return [("s", *to_units(pt)) for pt in q[1:]]

    def satin(c, forward):
        out = []
        for L, R in (c[0] if forward else [(L[::-1], R[::-1]) for L, R in c[0][::-1]]):
            for i in range(len(L)):  # un aller-retour d'un bord à l'autre tous les `spacing`
                out.append(("s", *to_units(L[i])))
                out.append(("s", *to_units(R[i])))
        return out

    def node_pt(n):
        m = nodes[n]
        return m[len(m) // 2]

    def visit(n):
        seen_nodes.add(n)
        # tronçons du nœud : le plus court d'abord (moins de sous-couche visible en cas d'aller-retour)
        for k, other, fwd in sorted(adj.get(n, []), key=lambda e: len(edges[e[0]][2])):
            if k in done or cols[k] is None:
                continue
            done.add(k)
            axis = cols[k][1] if fwd else cols[k][1][::-1]
            seq.extend(under(axis))
            if other not in seen_nodes:
                visit(other)
            seq.extend(satin(cols[k], not fwd))

    pos = start
    # composantes du graphe, la plus proche d'abord ; départ : un bout de trait si possible
    while len(done) < sum(1 for c in cols if c is not None):
        free = [n for n in adj if any(k not in done and cols[k] is not None for k, _o, _f in adj[n])]
        tips = [n for n in free if deg.get(n) == 1] or free
        n0 = min(tips, key=lambda n: math.dist(to_units(node_pt(n)), pos))
        seq = [("move", *to_units(node_pt(n0)))]
        visit(n0)
        ops += seq
        pos = (ops[-1][1], ops[-1][2])
    return ops
