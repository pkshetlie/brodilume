"""Nuanciers de fils, lus dans la base du logiciel mySewnet / CREATIVATE (lecture seule).

    C:/ProgramData/mySewnet/Embroidery1/System/system_cdb2.sqlite : toutes les gammes
    C:/ProgramData/mySewnet/Embroidery1/System/user.sqlite        : « My Threads » et
                                                                    les gammes favorites (MyThreadRanges)
ColourID = R + G*256 + B*65536.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

SYSTEM_DIR = r"C:\ProgramData\mySewnet\Embroidery1\System"
DEFAULT_RANGE = "Robison-Anton Rayon 40"
MY_THREADS = "My Threads"


@dataclass(frozen=True)
class ThreadColor:
    brand: str
    code: str
    name: str
    rgb: tuple


def _db(name):
    path = os.path.join(SYSTEM_DIR, name)
    if not os.path.exists(path):
        return None
    return sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)


def _rgb(cid):
    return (cid & 255, (cid >> 8) & 255, (cid >> 16) & 255)


@lru_cache(maxsize=None)
def available_ranges() -> tuple:
    """Gammes favorites de l'utilisateur d'abord (comme dans le logiciel), puis les autres."""
    sysdb, userdb = _db("system_cdb2.sqlite"), _db("user.sqlite")
    if sysdb is None:
        return ()
    names = dict(sysdb.execute("select ManufacturerID, ManufacturerName from Cdb_Manufacturers"))
    fav = []
    if userdb is not None:
        rows = userdb.execute("select ManufacturerID, WhichDB from Cdb_MyThreadRanges order by DisplayOrder")
        for mid, which in rows:
            if which == 1:
                fav.append(MY_THREADS)
            elif mid in names and "Needle" not in names[mid]:
                fav.append(names[mid])
    others = sorted(n for n in names.values() if n not in fav and "Needle" not in n)
    return tuple(fav + others)


@lru_cache(maxsize=None)
def load_range(name: str) -> tuple:
    """Fils unis d'une gamme (les fils dégradés/multicolores sont exclus)."""
    if name == MY_THREADS:
        db = _db("user.sqlite")
        q = "select SerialNumber, ThreadName, ColourID from Cdb_ThreadData where NumberColours = 1"
        args = ()
    else:
        db = _db("system_cdb2.sqlite")
        q = ("select t.SerialNumber, t.ThreadName, t.ColourID from Cdb_ThreadData t "
             "join Cdb_Manufacturers m using(ManufacturerID) "
             "where m.ManufacturerName = ? and t.NumberColours = 1")
        args = (name,)
    if db is None:
        return ()
    sysdb = _db("system_cdb2.sqlite") if name == MY_THREADS else None
    out = []
    for code, tname, cid in db.execute(q, args):
        brand, code = name, str(code or "")
        if sysdb is not None:
            # « RaRa5-2388 » : on retrouve la vraie gamme et le vrai numéro dans la base système
            num = code.split("-", 1)[-1]
            row = sysdb.execute(
                "select m.ManufacturerName, t.SerialNumber from Cdb_ThreadData t join Cdb_Manufacturers m "
                "using(ManufacturerID) where t.SerialNumber = ? and t.ColourID = ? and t.ThreadName = ?",
                (num, cid, tname)).fetchone()
            if row:
                brand, code = row
        out.append(ThreadColor(brand, code, tname or "", _rgb(cid)))
    return tuple(out)


# --------------------------------------------------------------------------- couleur la plus proche

def _lab(rgb):
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def nearest(rgb, threads) -> ThreadColor | None:
    """Fil le plus proche visuellement (distance dans l'espace Lab)."""
    if not threads:
        return None
    lab = _lab([t.rgb for t in threads])
    d = ((lab - _lab([rgb])[0]) ** 2).sum(1)
    return threads[int(d.argmin())]
