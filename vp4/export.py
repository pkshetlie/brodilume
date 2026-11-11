"""Export du motif final dans les formats de broderie, et clé USB.

.vp4 : notre propre écrivain (vérifié à l'octet près avec un fichier de mySewnet).
Autres formats : bibliothèque pyembroidery (libre, très utilisée), si elle est installée.
"""
from __future__ import annotations

import ctypes
import os
import string
import sys

from .format import Design, write_vp4, STITCH, JUMP, TRIM

try:  # traduction de l'interface (absente quand vp4 est utilisé seul)
    from i18n import _
except ImportError:
    def _(s):
        return s

# (extension, nom affiché, marques, exemples de machines — liste non exhaustive)
FORMATS = [
    ("vp4", "VP4", _("Husqvarna Viking / Pfaff (mySewnet)"),
     _("format du logiciel mySewnet ; machines récentes connectées (Designer Epic 3, creative icon 2…) — à vérifier")),
    ("vp3", "VP3", _("Husqvarna Viking / Pfaff"),
     _("Designer Epic, Ruby, Topaz, Jade, Sapphire ; Pfaff creative icon, ambition, sensation, 4.5…")),
    ("pes", "PES", _("Brother, Baby Lock"),
     _("Brother Innov-is, Stellaire, Luminaire, PE / SE ; Baby Lock Destiny, Solaris, Flare…")),
    ("jef", "JEF", _("Janome, Elna"),
     _("Janome Memory Craft (MC 400E, 500E, 550E, 9850…) ; Elna eXpressive…")),
    ("exp", "EXP", _("Bernina, Melco"),
     _("Bernina 5, 7 et 8 Series, Aurora ; Melco…")),
    ("xxx", "XXX", _("Singer"),
     _("Singer Futura, Quantum XL, SE / Legacy…")),
    ("dst", "DST", _("format universel des pros"),
     _("Tajima, Ricoma, Happy, SWF, Barudan ; Brother PR ; la plupart des machines multi-têtes")),
    ("u01", "U01", _("Barudan"), _("Barudan, Toyota (machines professionnelles)")),
]


def has_pyembroidery():
    try:
        import pyembroidery  # noqa: F401
        return True
    except ImportError:
        return False


def to_pattern(des: Design):
    """Motif Brodilume -> EmbPattern de pyembroidery (unités 0,1 mm, Y vers le bas)."""
    import pyembroidery as pe
    pat = pe.EmbPattern()
    for k, b in enumerate(des.blocks):
        t = b.thread
        th = pe.EmbThread()
        th.set_color(*t.rgb)
        th.description, th.catalog_number, th.brand = t.name, t.code, t.brand
        pat.add_thread(th)
        if k:
            pat.add_command(pe.COLOR_CHANGE)
        x, y = b.start
        pat.add_stitch_absolute(pe.JUMP, x, y)
        for r in b.records:
            if r[0] == TRIM:
                pat.add_command(pe.TRIM)
                continue
            x, y = x + r[1], y + r[2]
            pat.add_stitch_absolute(pe.STITCH if r[0] == STITCH else pe.JUMP, x, y)
    pat.add_command(pe.END)
    return pat


def export(des: Design, path: str):
    """Écrit le motif ; le format est donné par l'extension du fichier."""
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    if ext == "vp4":
        write_vp4(des, path)
        return
    if not has_pyembroidery():
        raise RuntimeError(_("Pour ce format, installez pyembroidery : python -m pip install pyembroidery"))
    import pyembroidery as pe
    pe.write(to_pattern(des), path)


# --------------------------------------------------------------------------- clé USB

def usb_drives():
    """Lecteurs amovibles branchés : [(« E:\\\\ », nom du volume, place libre en Mo)]."""
    if sys.platform != "win32":
        return []
    k32 = ctypes.windll.kernel32
    out = []
    mask = k32.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if not mask & (1 << i):
            continue
        root = letter + ":\\"
        if k32.GetDriveTypeW(root) != 2:  # DRIVE_REMOVABLE
            continue
        name = ctypes.create_unicode_buffer(261)
        ok = k32.GetVolumeInformationW(root, name, 261, None, None, None, None, 0)
        if not ok:  # lecteur de carte vide, par exemple
            continue
        free = ctypes.c_ulonglong(0)
        k32.GetDiskFreeSpaceExW(root, None, None, ctypes.byref(free))
        out.append((root, name.value or _("Clé USB"), free.value // (1024 * 1024)))
    return out
