"""Vérifie que l'écrivain reproduit à l'octet près un .vp4 exporté par le logiciel d'origine."""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from vp4 import read_vp4, write_vp4  # noqa: E402


def test_exporte_identique():
    src = os.path.join(ROOT, "samples", "exporte.vp4")
    if not os.path.exists(src):  # fichier de référence absent du dépôt public
        print("ignoré : samples/exporte.vp4 introuvable")
        return
    orig = open(src, "rb").read()
    out = write_vp4(read_vp4(src))
    if out != orig:
        n = next((i for i, (a, b) in enumerate(zip(out, orig)) if a != b), min(len(out), len(orig)))
        raise AssertionError("différence à l'octet %d (tailles %d / %d)\n écrit : %s\n orig  : %s"
                             % (n, len(out), len(orig), out[n:n + 24].hex(" "), orig[n:n + 24].hex(" ")))


if __name__ == "__main__":
    test_exporte_identique()
    print("OK : fichier réécrit identique à l'original")
