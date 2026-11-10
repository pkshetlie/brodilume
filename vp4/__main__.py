"""Ligne de commande : python -m vp4 image.png -o motif.vp4 [--width 100] [--colors 4] ..."""
import argparse

from PIL import Image

from . import write_vp4, read_vp4
from .digitize import Settings, image_to_design
from .render import render


def main():
    ap = argparse.ArgumentParser(description="Convertit une image en broderie .vp4")
    ap.add_argument("image")
    ap.add_argument("-o", "--output", help="fichier .vp4 (défaut : même nom que l'image)")
    ap.add_argument("--width", type=float, default=100, help="largeur du motif en mm")
    ap.add_argument("--colors", type=int, default=4, help="nombre de couleurs de fil")
    ap.add_argument("--keep-background", action="store_true", help="brode aussi la couleur du fond")
    ap.add_argument("--spacing", type=float, default=0.4, help="écart entre rangs en mm")
    ap.add_argument("--stitch", type=float, default=4.0, help="longueur de point en mm")
    ap.add_argument("--angle", type=float, default=45, help="angle du remplissage en degrés")
    ap.add_argument("--preview", help="enregistre aussi un aperçu PNG")
    a = ap.parse_args()

    s = Settings(width_mm=a.width, colors=a.colors, remove_background=not a.keep_background,
                 row_spacing_mm=a.spacing, stitch_mm=a.stitch, angle_deg=a.angle)
    des = image_to_design(Image.open(a.image), s)
    out = a.output or a.image.rsplit(".", 1)[0] + ".vp4"
    write_vp4(des, out)
    back = read_vp4(out)
    print("%s : %d couleurs, %d points" % (out, len(back.blocks), back.stitch_count()))
    if a.preview:
        render(back).save(a.preview)


if __name__ == "__main__":
    main()
