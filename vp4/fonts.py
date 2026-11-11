"""Polices pour broder du texte : polices installées sur le PC, polices importées dans Brodilume.

Une police importée est copiée dans %APPDATA%\\Brodilume\\polices : elle n'est pas installée dans
Windows et ne sert qu'à Brodilume. Le texte est dessiné en image (lettres pleines, fond transparent),
qui passe ensuite par la même conversion qu'une image importée.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, asdict

from PIL import Image, ImageDraw, ImageFont

FONT_EXT = (".ttf", ".otf", ".ttc", ".otc")
CACHE_VERSION = 1


@dataclass
class Face:
    name: str          # « Arial Gras », « Comic Sans MS »…
    path: str
    index: int = 0     # visage dans un fichier .ttc
    imported: bool = False


def app_dir():
    return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Brodilume")


def imported_dir():
    return os.path.join(app_dir(), "polices")


def system_dirs():
    out = [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")]
    local = os.environ.get("LOCALAPPDATA")
    if local:  # polices installées « pour moi seulement »
        out.append(os.path.join(local, "Microsoft", "Windows", "Fonts"))
    return out


def _face_name(font):
    family, style = font.getname()
    style = (style or "").strip()
    if not style or style.lower() in ("regular", "normal", "standard", "roman", "book"):
        return family
    return "%s %s" % (family, style)


def read_faces(path, imported=False):
    """Visages d'un fichier de police (plusieurs pour un .ttc). Liste vide si illisible."""
    faces = []
    for index in range(16):
        try:
            font = ImageFont.truetype(path, 24, index=index)
        except (OSError, ValueError):
            break
        faces.append(Face(_face_name(font), path, index, imported))
        if not path.lower().endswith((".ttc", ".otc")):
            break
    return faces


def _files(dirs):
    for d in dirs:
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            if n.lower().endswith(FONT_EXT):
                yield os.path.join(d, n)


def scan(use_cache=True):
    """Toutes les polices utilisables, triées par nom (les importées d'abord en cas de doublon).

    Lire un millier de polices prend quelques secondes : les noms sont gardés dans un cache,
    relu tant que le fichier n'a pas changé (taille, date)."""
    cache_path = os.path.join(app_dir(), "polices-cache.json")
    cache = {}
    if use_cache:
        try:
            with open(cache_path, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("version") == CACHE_VERSION:
                cache = data.get("files", {})
        except (OSError, ValueError):
            pass
    new_cache, faces = {}, []
    for imported, dirs in ((True, [imported_dir()]), (False, system_dirs())):
        for p in _files(dirs):
            try:
                st = os.stat(p)
            except OSError:
                continue
            stamp = [st.st_size, int(st.st_mtime)]
            hit = cache.get(p)
            if hit and hit["stamp"] == stamp:
                fs = [Face(**f) for f in hit["faces"]]
            else:
                fs = read_faces(p, imported)
            new_cache[p] = {"stamp": stamp, "faces": [asdict(f) for f in fs]}
            faces += fs
    try:
        os.makedirs(app_dir(), exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"version": CACHE_VERSION, "files": new_cache}, f, ensure_ascii=False)
    except OSError:
        pass
    seen, out = set(), []
    for f in faces:
        if f.name.lower() not in seen:
            seen.add(f.name.lower())
            out.append(f)
    out.sort(key=lambda f: f.name.lower())
    return out


def import_font(src):
    """Copie un fichier de police dans le dossier de Brodilume. Retourne ses visages.

    ValueError si le fichier n'est pas une police lisible."""
    if not src.lower().endswith(FONT_EXT) or not read_faces(src):
        raise ValueError(os.path.basename(src))
    os.makedirs(imported_dir(), exist_ok=True)
    base, ext = os.path.splitext(os.path.basename(src))
    dest = os.path.join(imported_dir(), base + ext)
    if os.path.exists(dest) and not _same_file(src, dest):
        k = 2
        while os.path.exists(os.path.join(imported_dir(), "%s-%d%s" % (base, k, ext))):
            k += 1
        dest = os.path.join(imported_dir(), "%s-%d%s" % (base, k, ext))
    if not os.path.exists(dest):
        shutil.copyfile(src, dest)
    return read_faces(dest, imported=True)


def _same_file(a, b):
    try:
        if os.path.getsize(a) != os.path.getsize(b):
            return False
        with open(a, "rb") as fa, open(b, "rb") as fb:
            return fa.read() == fb.read()
    except OSError:
        return False


def install_bytes(name, data):
    """Police embarquée dans un projet .brodi : remise dans le dossier des polices importées."""
    os.makedirs(imported_dir(), exist_ok=True)
    dest = os.path.join(imported_dir(), os.path.basename(name))
    if os.path.exists(dest):
        with open(dest, "rb") as f:
            if f.read() == data:
                return dest
        base, ext = os.path.splitext(dest)
        k = 2
        while os.path.exists("%s-%d%s" % (base, k, ext)):
            k += 1
        dest = "%s-%d%s" % (base, k, ext)
    with open(dest, "wb") as f:
        f.write(data)
    return dest


def is_imported(path):
    try:
        return os.path.normcase(os.path.dirname(os.path.abspath(path))) == os.path.normcase(imported_dir())
    except (TypeError, ValueError):
        return False


def render_text(text, path, index=0, rgb=(0, 0, 0), align="center", spacing=1.2, px=200, max_side=5000):
    """Texte (plusieurs lignes possibles) -> image RGBA : lettres pleines sur fond transparent.

    px : hauteur d'une ligne en pixels ; réduite si l'image dépasserait max_side pixels."""
    text = text.replace("\r\n", "\n").strip("\n")
    if not text.strip():
        raise ValueError("texte vide")
    for _ in range(4):
        font = ImageFont.truetype(path, px, index=index)
        probe = ImageDraw.Draw(Image.new("L", (1, 1)))
        gap = max(0, int(round(px * (spacing - 1.0))))
        x0, y0, x1, y1 = (int(round(v)) for v in
                          probe.multiline_textbbox((0, 0), text, font=font, spacing=gap, align=align))
        if max(x1 - x0, y1 - y0) <= max_side or px <= 24:
            break
        px = max(24, int(px * max_side / max(x1 - x0, y1 - y0)))
    pad = max(4, px // 10)
    w, h = x1 - x0 + 2 * pad, y1 - y0 + 2 * pad
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).multiline_text((pad - x0, pad - y0), text, fill=255, font=font, spacing=gap, align=align)
    img = Image.new("RGBA", (w, h), tuple(rgb) + (0,))
    img.putalpha(mask)
    return img
