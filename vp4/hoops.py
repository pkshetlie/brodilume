"""Catalogue des cercles à broder (vp4/hoops.json) : marques, machines, cercles et leur taille utile.

Taille d'un cercle : largeur x hauteur en mm dans son orientation « naturelle » (bras de la machine en
haut, cercle en portrait le plus souvent). Brodilume l'affiche par défaut « pivotée » (paysage), comme
mySewnet. Les cercles qui demandent de repositionner le tissu (Grand Dream, cercles pivotants) ne sont
pas proposés : Brodilume brode en une seule fois.
"""
from __future__ import annotations

import json
import os
import sys

_PATH = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                     "vp4", "hoops.json")
_cat = None


def catalog():
    global _cat
    if _cat is None:
        try:
            with open(_PATH, encoding="utf-8") as f:
                _cat = json.load(f)
        except (OSError, ValueError):
            _cat = {"brands": [], "machines": [], "hoops": {}}
    return _cat


def brands():
    """[(id, nom)] dans l'ordre d'affichage."""
    return [(b["id"], b["name"]) for b in catalog()["brands"]]


def machines(brand=None):
    return [m for m in catalog()["machines"] if brand is None or m["brand"] == brand]


def machine(mid):
    return next((m for m in catalog()["machines"] if m["id"] == mid), None)


def hoop(hid):
    return catalog()["hoops"].get(hid)


def size(hid, rotated=True):
    """(largeur, hauteur) affichées en mm ; pivoté : largeur et hauteur échangées."""
    h = hoop(hid)
    if not h:
        return None
    return (h["h"], h["w"]) if rotated else (h["w"], h["h"])


def universal_for(w_mm, h_mm):
    """Plus petit cercle Universal (mySewnet) qui contient w x h (dans un sens ou dans l'autre).

    Retourne (identifiant, (largeur, hauteur) naturelles en 0,1 mm) ou None."""
    best = None
    m = machine("universal")
    for hid in (m["hoops"] if m else []):
        h = hoop(hid)
        if not h:
            continue
        fits = (h["w"] >= w_mm - 0.05 and h["h"] >= h_mm - 0.05) or (h["h"] >= w_mm - 0.05 and h["w"] >= h_mm - 0.05)
        if fits and (best is None or h["w"] * h["h"] < best[1]["w"] * best[1]["h"]):
            best = (hid, h)
    if best is None:
        return None
    hid, h = best
    return hid, (int(round(h["w"] * 10)), int(round(h["h"] * 10)))
