"""Fichier projet Brodilume (.brodi) : tout le travail, réouvrable et modifiable.

C'est une archive zip :
    projet.json          réglages, cercle, et pour chaque élément : nom, type, position, rotation,
                         échelle, réglages de conversion, gomme, fusions et suppressions de couleurs
    images/<n>.png       image d'origine d'un élément « image » (sans perte, transparence gardée),
                         ou lettres dessinées d'un élément « texte »
    polices/<n>-<nom>    police importée dans Brodilume utilisée par un texte (le projet reste
                         modifiable sur un autre PC ; les polices de Windows ne sont pas copiées)
    motifs/<n>.vp4       points de l'élément (repère local), au format .vp4
    apercu.png           petite vignette (pour l'Explorateur ou une future liste de projets)
"""
from __future__ import annotations

import dataclasses
import io
import json
import os
import zipfile

import numpy as np
from PIL import Image

from .digitize import Settings
from . import fonts
from .format import write_vp4, read_vp4
from .project import Item

EXT = ".brodi"
VERSION = 1


def _lists(v):
    """numpy / tuples -> listes JSON (récursif)."""
    if v is None:
        return None
    if isinstance(v, np.ndarray):
        return v.tolist()
    if isinstance(v, (list, tuple)):
        return [_lists(x) for x in v]
    if isinstance(v, (np.floating, np.integer)):
        return v.item()
    return v


def _tuples(v):
    if isinstance(v, list):
        return tuple(_tuples(x) for x in v)
    return v


def save_project(path, items, hoop_mm, preview=None):
    data = {"app": "Brodilume", "version": VERSION, "hoop_mm": list(hoop_mm), "items": []}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n, it in enumerate(items):
            e = {"name": it.name, "kind": it.kind, "x": it.x, "y": it.y, "angle": it.angle, "scale": it.scale,
                 "gen_width": it.gen_width, "visible": it.visible, "hidden": sorted(it.hidden),
                 "removed": [_lists(k) for k in it.removed],
                 "erases": [[_lists(p), _lists(k)] for p, k in it.erases],
                 "recolors": [[_lists(p), _lists(s), _lists(d)] for p, s, d in it.recolors]}
            if it.settings is not None:
                st = dataclasses.asdict(it.settings)
                st["recolor"] = []  # les fusions sont gardées dans « recolors »
                e["settings"] = st
            if it.text is not None:
                e["text"] = {k: _lists(v) for k, v in it.text.items()}
                fpath = it.text.get("path") or ""
                if fonts.is_imported(fpath) and os.path.exists(fpath):
                    e["font_file"] = "polices/%d-%s" % (n, os.path.basename(fpath))
                    with open(fpath, "rb") as f:
                        z.writestr(e["font_file"], f.read())
            if it.image is not None:
                buf = io.BytesIO()
                it.image.save(buf, "PNG")
                e["image"] = "images/%d.png" % n
                z.writestr(e["image"], buf.getvalue())
            if it.design is not None and it.design.blocks:
                e["design"] = "motifs/%d.vp4" % n
                z.writestr(e["design"], write_vp4(it.design))
            data["items"].append(e)
        if preview is not None:
            buf = io.BytesIO()
            preview.save(buf, "PNG")
            z.writestr("apercu.png", buf.getvalue())
        z.writestr("projet.json", json.dumps(data, ensure_ascii=False, indent=1))


def load_project(path):
    """Retourne (éléments, (largeur, hauteur) du cercle en mm)."""
    with zipfile.ZipFile(path) as z:
        data = json.loads(z.read("projet.json").decode("utf-8"))
        if data.get("app") != "Brodilume":
            raise ValueError("ce n'est pas un projet Brodilume")
        items = []
        for e in data["items"]:
            it = Item(e["name"], e["kind"], x=e["x"], y=e["y"], angle=e["angle"], scale=e["scale"])
            it.gen_width = e.get("gen_width", 0.1)
            it.visible = e.get("visible", True)
            it.hidden = set(e.get("hidden", []))
            it.removed = {_tuples(k) for k in e.get("removed", [])}
            it.erases = [(None if p is None else np.array(p, float), _tuples(k)) for p, k in e.get("erases", [])]
            it.recolors = [(None if p is None else np.array(p, float), _tuples(s), _tuples(d))
                           for p, s, d in e.get("recolors", [])]
            if "settings" in e:
                known = {f.name for f in dataclasses.fields(Settings)}
                it.settings = Settings(**{k: v for k, v in e["settings"].items() if k in known})
            if "text" in e:
                it.text = dict(e["text"])
                fpath = it.text.get("path") or ""
                if not os.path.exists(fpath) and "font_file" in e:  # police importée, venue d'un autre PC
                    try:
                        name = os.path.basename(e["font_file"]).split("-", 1)[-1]
                        it.text["path"] = fonts.install_bytes(name, z.read(e["font_file"]))
                    except (OSError, KeyError):
                        pass
            if "image" in e:
                it.image = Image.open(io.BytesIO(z.read(e["image"])))
                it.image.load()
            if "design" in e:
                it.design = read_vp4(z.read(e["design"]))
            items.append(it)
        return items, tuple(data.get("hoop_mm", (260, 200)))
