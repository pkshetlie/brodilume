"""Lecture du format de broderie .vp3 (Husqvarna Viking / Pfaff, plus ancien que .vp4).

Format (big-endian) :

    en-tête      "%vsm%" ... textes UTF-16 (réglages du lettrage) ...
    u16          nombre de blocs couleur, juste avant le premier bloc
    bloc couleur 00 05 00, u32 longueur (comptée après ce champ),
                 i32 x, i32 y (départ, 0,001 mm ; y vers le haut, contrairement aux points),
                 u8 n, u8 transition, n × (R G B, u8 parts, u16 longueur),
                 u8 type, u8 poids, str code, str nom, str marque,
                 15 octets, 0a f6 00, points jusqu'à la fin du bloc
    str          u16 longueur + octets
    points       paires d'octets signés (dx, dy) en 0,1 mm
                 80 01 i16 dx i16 dy (big-endian) [80 02] : saut s'il suit une coupe,
                 sinon point long (ex. satin de plus de 12,7 mm)
                 80 03 : coupe du fil

Le motif est lu dans le même repère que les .vp4 « portrait » (hoop_rotated = 0).
"""
from __future__ import annotations

import struct

from .format import Design, ColorBlock, Thread, STITCH, JUMP, TRIM


def _str(d, p):
    n = struct.unpack_from(">H", d, p)[0]
    return d[p + 2:p + 2 + n].decode("latin1"), p + 2 + n


def _decode_records(raw: bytes):
    recs, i, trimmed = [], 0, False
    while i < len(raw) - 1:
        if raw[i] == 0x80:
            cmd = raw[i + 1]
            if cmd == 1:
                dx, dy = struct.unpack_from(">hh", raw, i + 2)
                i += 6
                recs.append((JUMP if trimmed else STITCH, dx, dy))
                trimmed = False
                continue
            if cmd == 3:
                recs.append((TRIM,))
                trimmed = True
            i += 2
            continue
        dx, dy = struct.unpack_from("bb", raw, i)
        recs.append((STITCH, dx, dy))
        trimmed = False
        i += 2
    return recs


def read_vp3(path: str) -> Design:
    d = open(path, "rb").read()
    if not d.startswith(b"%vsm%"):
        raise ValueError("ce n'est pas un fichier .vp3")
    des = Design(notes="Importé de %s" % path.replace("\\", "/").rsplit("/", 1)[-1], hoop_rotated=0)
    p = d.find(b"\x00\x05\x00")
    if p < 2:
        raise ValueError("aucun bloc couleur trouvé")
    n_blocks = struct.unpack_from(">H", d, p - 2)[0]
    for _ in range(n_blocks):
        if d[p:p + 3] != b"\x00\x05\x00":
            raise ValueError("bloc couleur invalide à l'octet %d" % p)
        end = p + 7 + struct.unpack_from(">I", d, p + 3)[0]
        sx, sy = struct.unpack_from(">ii", d, p + 7)
        q = p + 15
        nc = d[q]
        rgb = tuple(d[q + 2:q + 5])
        q += 2 + nc * 6 + 2
        code, q = _str(d, q)
        name, q = _str(d, q)
        brand, q = _str(d, q)
        q += 15
        if d[q:q + 3] != b"\x0a\xf6\x00":
            raise ValueError("début des points introuvable à l'octet %d" % q)
        des.blocks.append(ColorBlock(Thread(rgb, code, name, brand), (round(sx / 100), -round(sy / 100)),
                                     _decode_records(d[q + 3:end])))
        p = end
    return des


def read_design(path: str) -> Design:
    """Ouvre un .vp4 ou un .vp3 (détecté par le contenu)."""
    from .format import read_vp4
    with open(path, "rb") as f:
        head = f.read(5)
    if head == b"%vsm%":
        return read_vp3(path)
    return read_vp4(path)
