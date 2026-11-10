"""Lecture / écriture du format de broderie .vp4 (Husqvarna Viking / Pfaff).

Format reconstitué par rétro-ingénierie à partir de fichiers exportés :

    en-tête      29 octets fixes ("%Vp4%" ...)
    info         chunk : nttn (notes) + u32 nb_enregistrements + u32 nb_couleurs
                 + u16 nb_objets + i16 xmin, ymin, xmax, ymax
    01           octet
    hoop         chunk : str16 nom, str16 groupe, u8 orientation, u16 l, u16 h (0,1 mm)
    00           octet
    sbds         chunk : u16 nb_objets + sbdn
    sbdn         chunk : 17 octets nuls + nttn + 00 + u32 nb_couleurs + blocs couleur
    bloc couleur i16 x, i16 y (départ absolu), chunk thrd, u32 n, n octets de points
    thrd         chunk : str16 marque, str16 code, str16 nom, 08 28 R G B 00 00
    points       paires d'octets signés (dx, dy) en 0,1 mm
                 80 01 i16 dx i16 dy : déplacement long (saut)
                 80 01 i16 dx i16 dy 80 02 : point long
                 80 03               : coupe du fil
    chunk        tag(4) u32 0 u32 longueur contenu

Toutes les valeurs sont little-endian. Unité : 0,1 mm.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

HEADER = bytes.fromhex(
    "2556703425" "01000000" "4d73610a" "df74293c876b442c842f003c7cf7e7a0"
)

STITCH, JUMP, TRIM = "s", "j", "t"


@dataclass
class Thread:
    rgb: tuple[int, int, int]
    code: str = ""
    name: str = ""
    brand: str = "Robison-Anton Rayon 40"


@dataclass
class ColorBlock:
    thread: Thread
    start: tuple[int, int]
    # enregistrements relatifs : (STITCH, dx, dy) | (JUMP, dx, dy) | (TRIM,)
    records: list = field(default_factory=list)

    def points(self):
        """Parcourt les positions absolues : (op, x, y)."""
        x, y = self.start
        yield ("start", x, y)
        for r in self.records:
            if r[0] == TRIM:
                yield (TRIM, x, y)
                continue
            x += r[1]
            y += r[2]
            yield (r[0], x, y)


@dataclass
class Design:
    blocks: list[ColorBlock] = field(default_factory=list)
    notes: str = ""
    hoop_name: str = "UniLarge3"
    hoop_group: str = "Universal"
    hoop_rotated: int = 0          # 0 : portrait (l=200,h=260)  1 : paysage
    hoop_size: tuple[int, int] = (2000, 2600)

    def bbox(self):
        xs, ys = [], []
        for b in self.blocks:
            for op, x, y in b.points():
                if op in (STITCH, "start"):
                    xs.append(x)
                    ys.append(y)
        return min(xs), min(ys), max(xs), max(ys)

    def record_count(self):
        return sum(len(b.records) for b in self.blocks) + len(self.blocks)

    def stitch_count(self):
        return sum(1 for b in self.blocks for r in b.records if r[0] == STITCH)


# --------------------------------------------------------------------------- écriture

def _str16(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack("<H", len(b)) + b


def _chunk(tag: bytes, content: bytes) -> bytes:
    return tag + struct.pack("<II", 0, len(content)) + content


def _nttn(text: str) -> bytes:
    return _chunk(b"nttn", struct.pack("<H", 2) + b"ntes" + _str16("") + b"stgs" + _str16(text))


def _encode_records(records) -> bytes:
    out = bytearray()
    for r in records:
        if r[0] == STITCH:
            dx, dy = r[1], r[2]
            if -127 <= dx <= 127 and -127 <= dy <= 127:
                out += struct.pack("<bb", dx, dy)
            else:  # point long : 80 01 dx dy 80 02
                out += b"\x80\x01" + struct.pack("<hh", dx, dy) + b"\x80\x02"
        elif r[0] == JUMP:
            out += b"\x80\x01" + struct.pack("<hh", r[1], r[2])
        elif r[0] == TRIM:
            out += b"\x80\x03"
        else:
            raise ValueError(r)
    return bytes(out)


def write_vp4(design: Design, path: str | None = None) -> bytes:
    nb = len(design.blocks)
    xmin, ymin, xmax, ymax = design.bbox()

    info = (_nttn(design.notes)
            + struct.pack("<IIH", design.record_count(), nb, 1)
            + struct.pack("<hhhh", xmin, ymin, xmax, ymax))

    w, h = design.hoop_size
    if design.hoop_rotated:
        w, h = h, w
    hoop = (_str16(design.hoop_name) + _str16(design.hoop_group)
            + struct.pack("<BHH", design.hoop_rotated, w, h))

    blocks = bytearray()
    for b in design.blocks:
        t = b.thread
        thrd = (_str16(t.brand) + _str16(t.code) + _str16(t.name)
                + bytes([0x08, 0x28, *t.rgb, 0, 0]))
        data = _encode_records(b.records)
        blocks += struct.pack("<hh", *b.start) + _chunk(b"thrd", thrd)
        blocks += struct.pack("<I", len(data)) + data

    sbdn = _chunk(b"sbdn", bytes(17) + _nttn(design.notes) + b"\x00"
                  + struct.pack("<I", nb) + bytes(blocks))
    sbds = _chunk(b"sbds", struct.pack("<H", 1) + sbdn)

    out = HEADER + _chunk(b"info", info) + b"\x01" + _chunk(b"hoop", hoop) + b"\x00" + sbds
    if path:
        with open(path, "wb") as f:
            f.write(out)
    return out


# --------------------------------------------------------------------------- lecture

def _rd_str(d, p):
    n = struct.unpack_from("<H", d, p)[0]
    return d[p + 2:p + 2 + n].decode("utf-8", "replace"), p + 2 + n


def _decode_records(raw: bytes):
    recs, i = [], 0
    while i < len(raw) - 1:
        if raw[i] == 0x80:
            cmd = raw[i + 1]
            if cmd == 1:
                dx, dy = struct.unpack_from("<hh", raw, i + 2)
                i += 6
                if raw[i:i + 2] == b"\x80\x02":   # point long
                    recs.append((STITCH, dx, dy))
                    i += 2
                else:                             # saut (suit normalement une coupe)
                    recs.append((JUMP, dx, dy))
                continue
            if cmd == 3:
                recs.append((TRIM,))
            elif cmd != 2:
                raise ValueError("commande inconnue 0x80 %02x" % cmd)
            i += 2
            continue
        dx, dy = struct.unpack_from("<bb", raw, i)
        recs.append((STITCH, dx, dy))
        i += 2
    if i != len(raw):
        raise ValueError("fin de bloc désalignée")
    return recs


def read_vp4(path) -> Design:
    """path : chemin du fichier, ou directement son contenu (bytes)."""
    d = path if isinstance(path, (bytes, bytearray)) else open(path, "rb").read()
    if not d.startswith(b"%Vp4%"):
        raise ValueError("ce n'est pas un fichier .vp4")
    des = Design()
    n = d.find(b"nttn")
    if n > 0:
        p = n + 12 + 2 + 4
        _, p = _rd_str(d, p)
        des.notes, _ = _rd_str(d, p + 4)
    h = d.find(b"hoop")
    if h > 0:
        p = h + 12
        des.hoop_name, p = _rd_str(d, p)
        des.hoop_group, p = _rd_str(d, p)
        rot, w, hh = struct.unpack_from("<BHH", d, p)
        des.hoop_rotated = rot
        des.hoop_size = (hh, w) if rot else (w, hh)

    t = d.find(b"thrd")
    while t >= 0:
        pre = d[t - 4:t]
        rl = struct.unpack_from("<I", d, t + 8)[0]
        p = t + 12
        try:
            brand, p = _rd_str(d, p)
            code, p = _rd_str(d, p)
            name, p = _rd_str(d, p)
            rgb = tuple(d[p + 2:p + 5])
            ln = struct.unpack_from("<I", d, t + 12 + rl)[0]
        except Exception:
            ln = 0
        start_data = t + 12 + rl + 4
        # les entrées de palette des objets lettrage (précédées de float 1.0) n'ont pas de points
        if pre != b"\x00\x00\x80\x3f" and 4 < ln <= len(d) - start_data:
            try:
                recs = _decode_records(d[start_data:start_data + ln])
                des.blocks.append(ColorBlock(Thread(rgb, code, name, brand),
                                             struct.unpack("<hh", pre), recs))
            except ValueError:
                pass
        t = d.find(b"thrd", t + 4)
    return des
