"""Decode a Husqvarna Viking / Pfaff .vp4 or .vp3 embroidery file and render it to PNG.

Usage: python vp4_decode.py <file.vp4|file.vp3> <out.png> [orientation]
(.vp3 is detected by its "%vsm%" header, see parse_vp3)
orientation: "native" (default, x right / y down) or "rot" (x,y) -> (y,-x)

Format notes (reverse-engineered):
  thrd record : "thrd" u32(0) u32(record_len) str16 brand, str16 code, str16 name,
                08 28 RR GG BB 00 00, u32 stitch_byte_len, stitch bytes
  start pos   : int16 x, int16 y (0.1 mm) in the 4 bytes just before "thrd"
  stitches    : signed byte pairs (dx, dy) in 0.1 mm
                80 01 <int16 dx> <int16 dy> : long move (jump)
                80 03                       : trim
  Palette-only thread entries (inside lettering objects) are preceded by
  float 1.0 (00 00 80 3f) and are skipped.
"""
import struct, sys
from PIL import Image, ImageDraw

src, out = sys.argv[1], sys.argv[2]
orient = sys.argv[3] if len(sys.argv) > 3 else "native"
d = open(src, "rb").read()


def rd_str(p):
    n = struct.unpack_from("<H", d, p)[0]
    return d[p + 2:p + 2 + n].decode("latin1"), p + 2 + n


def decode(raw, x, y):
    segs, cur, i = [], [(x, y)], 0
    while i < len(raw) - 1:
        if raw[i] == 0x80:
            cmd = raw[i + 1]
            if cmd == 1:
                dx, dy = struct.unpack_from("<hh", raw, i + 2)
                i += 6
                x += dx; y += dy
                if len(cur) > 1: segs.append(cur)
                cur = [(x, y)]
                continue
            if cmd == 3:
                if len(cur) > 1: segs.append(cur)
                cur = [(x, y)]
            elif cmd != 2:
                raise ValueError("unknown command %d at %d" % (cmd, i))
            i += 2
            continue
        dx, dy = struct.unpack_from("bb", raw, i)
        x += dx; y += dy
        cur.append((x, y))
        i += 2
    if i != len(raw):
        raise ValueError("misaligned end")
    if len(cur) > 1: segs.append(cur)
    return segs


def decode_vp3(raw, x, y):
    """VP3 stitches: like vp4, but long-move offsets are big-endian int16.
    80 01 <dx> <dy> 80 02 is a jump only right after a trim (80 03);
    otherwise it is a long stitch (e.g. wide satin > 12.7 mm, as in a big dot)."""
    segs, cur, i, trimmed = [], [(x, y)], 0, False
    while i < len(raw) - 1:
        if raw[i] == 0x80:
            cmd = raw[i + 1]
            if cmd == 1:
                dx, dy = struct.unpack_from(">hh", raw, i + 2)
                i += 6
                x += dx; y += dy
                if trimmed:
                    if len(cur) > 1: segs.append(cur)
                    cur = [(x, y)]
                else:
                    cur.append((x, y))
                trimmed = False
                continue
            if cmd == 3:
                if len(cur) > 1: segs.append(cur)
                cur = [(x, y)]
                trimmed = True
            i += 2
            continue
        trimmed = False
        dx, dy = struct.unpack_from("bb", raw, i)
        x += dx; y += dy
        cur.append((x, y))
        i += 2
    if len(cur) > 1: segs.append(cur)
    return segs


def rd_str_be(p):
    n = struct.unpack_from(">H", d, p)[0]
    return d[p + 2:p + 2 + n].decode("latin1"), p + 2 + n


def parse_vp3():
    """VP3 color block (big-endian):
      00 05 00, u32 block_len, i32 start_x, i32 start_y (0.001 mm),
      u8 n_colors, u8 transition, n_colors * (RGB, u8 parts, u16 len),
      u8 type, u8 weight, str code, str name, str brand,
      15 bytes, 0a f6 00, stitch bytes up to block end.
    The color-block count (u16) sits just before the first block."""
    out = []
    p = d.find(b"\x00\x05\x00")
    n_blocks = struct.unpack_from(">H", d, p - 2)[0]
    for _ in range(n_blocks):
        if d[p:p + 3] != b"\x00\x05\x00":
            raise ValueError("bad color block at %d" % p)
        ln = struct.unpack_from(">I", d, p + 3)[0]
        end = p + 7 + ln
        sx, sy = struct.unpack_from(">ii", d, p + 7)
        sx, sy = sx // 100, sy // 100
        q = p + 15
        nc = d[q]; q += 2
        rgb = "#%02x%02x%02x" % tuple(d[q:q + 3])
        q += nc * 6 + 2
        code, q = rd_str_be(q); desc, q = rd_str_be(q); brand, q = rd_str_be(q)
        q += 15
        if d[q:q + 3] != b"\x0a\xf6\x00":
            raise ValueError("missing stitch marker at %d" % q)
        segs = decode_vp3(d[q + 3:end], sx, sy)
        out.append((code, desc, rgb, segs))
        print("%-5s %-14s %s start %5d %5d  stitches %5d" %
              (code, desc, rgb, sx, sy, sum(len(s) for s in segs)))
        p = end
    return out


blocks = []
t = -1 if d.startswith(b"%vsm%") else d.find(b"thrd")
if t < 0 and d.startswith(b"%vsm%"):
    blocks = parse_vp3()
while t >= 0:
    pre = d[t - 4:t]
    p = t + 12
    try:
        brand, p = rd_str(p); code, p = rd_str(p); desc, p = rd_str(p)
        rgb = "#%02x%02x%02x" % (d[p + 2], d[p + 3], d[p + 4])
        ln = struct.unpack_from("<I", d, p + 7)[0]
    except Exception:
        ln = 0
    if pre != b"\x00\x00\x80\x3f" and 4 < ln <= len(d) - (p + 11):
        sx, sy = struct.unpack("<hh", pre)
        try:
            segs = decode(d[p + 11:p + 11 + ln], sx, sy)
            blocks.append((code, desc, rgb, segs))
            print("%-5s %-14s %s start %5d %5d  stitches %5d" %
                  (code, desc, rgb, sx, sy, sum(len(s) for s in segs)))
        except ValueError as e:
            print("skip", code, desc, e)
    t = d.find(b"thrd", t + 4)


def tf(q):
    return (q[1], -q[0]) if orient == "rot" else q


pts = [tf(q) for b in blocks for s in b[3] for q in s]
x0 = min(q[0] for q in pts); x1 = max(q[0] for q in pts)
y0 = min(q[1] for q in pts); y1 = max(q[1] for q in pts)
print("size: %.1f x %.1f mm, %d stitches" % ((x1 - x0) / 10, (y1 - y0) / 10, len(pts)))
S = 1600 / (x1 - x0 + 60)
img = Image.new("RGB", (1600, int((y1 - y0 + 60) * S)), "#cfe3f7")
dr = ImageDraw.Draw(img)
for code, desc, rgb, segs in blocks:
    for s in segs:
        dr.line([((tf(q)[0] - x0 + 30) * S, (tf(q)[1] - y0 + 30) * S) for q in s], fill=rgb, width=2)
img.save(out)
print("saved", out)
