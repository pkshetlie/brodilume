"""Génère les images PNG / ICO de l'application à partir des SVG (à relancer si les SVG changent).

Tkinter ne sait pas afficher le SVG : on le rastérise avec Edge (ou Chrome) en mode headless.
    python assets/build_assets.py
"""
import os
import subprocess
import tempfile

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
BROWSERS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe"]


def raster(svg, out_png, width, height):
    browser = next(b for b in BROWSERS if os.path.exists(b))
    with open(os.path.join(HERE, svg), encoding="utf-8") as f:
        body = f.read()
    html = ("<html><body style='margin:0;background:transparent'>"
            "<div style='width:%dpx;height:%dpx'>%s</div>"
            "<style>svg{width:100%%;height:100%%;display:block}</style></body></html>" % (width, height, body))
    with tempfile.TemporaryDirectory() as tmp:
        page = os.path.join(tmp, "page.html")
        with open(page, "w", encoding="utf-8") as f:
            f.write(html)
        shot = os.path.join(tmp, "shot.png")
        subprocess.run([browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        "--default-background-color=00000000", "--force-device-scale-factor=1",
                        "--window-size=%d,%d" % (width, height), "--screenshot=" + shot, page],
                       check=True, capture_output=True, timeout=60)
        Image.open(shot).convert("RGBA").crop((0, 0, width, height)).save(os.path.join(HERE, out_png))


if __name__ == "__main__":
    raster("brodilume-icone.svg", "brodilume-icone.png", 512, 512)
    raster("brodilume-logo.svg", "brodilume-logo.png", 1598, 448)
    ico = Image.open(os.path.join(HERE, "brodilume-icone.png"))
    ico.save(os.path.join(HERE, "brodilume.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                                                         (128, 128), (256, 256)])
    print("assets générés dans", HERE)
