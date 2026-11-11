"""Traductions : chaque texte _("…") du code a sa traduction anglaise et allemande, avec les mêmes
marqueurs %s / %d (sinon le formatage planterait dans cette langue).

python tests/test_i18n.py            -> vérifie
python tests/test_i18n.py --missing  -> affiche les textes à traduire (JSON)
"""
import ast
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES = ["app.py", "shortcuts.py", "theme.py", "installer.py", "install_win.py", "vp4/export.py"]
LANGS = ["en", "de"]
PLACEHOLDER = re.compile(r"%(?:\([^)]*\))?[-+ #0]*\d*(?:\.\d+)?[sdfgrx%]")


def source_texts():
    """Textes français du code : _("…") et i18n.translate(code, "…")."""
    out = {}
    for rel in SOURCES:
        tree = ast.parse(open(os.path.join(ROOT, rel), encoding="utf-8").read())
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            arg = None
            if isinstance(n.func, ast.Name) and n.func.id == "_" and n.args:
                arg = n.args[0]
            elif isinstance(n.func, ast.Attribute) and n.func.attr == "translate" and len(n.args) == 2:
                arg = n.args[1]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                out.setdefault(arg.value, "%s:%d" % (rel, n.lineno))
    return out


def load(code):
    with open(os.path.join(ROOT, "lang", code + ".json"), encoding="utf-8") as f:
        return json.load(f)


def problems():
    texts = source_texts()
    errs = []
    for code in LANGS:
        table = load(code)["texts"]
        for t, where in texts.items():
            tr = table.get(t)
            if not tr:
                errs.append("%s : pas de traduction pour %r (%s)" % (code, t, where))
            elif sorted(PLACEHOLDER.findall(t)) != sorted(PLACEHOLDER.findall(tr)):
                errs.append("%s : marqueurs différents pour %r -> %r" % (code, t, tr))
        for t in table:
            if t not in texts:
                errs.append("%s : traduction inutilisée %r" % (code, t))
    return errs


def test_translations_complete():
    errs = problems()
    assert not errs, "\n".join(errs[:40])


if __name__ == "__main__":
    if "--missing" in sys.argv:
        texts = source_texts()
        for code in LANGS:
            try:
                have = load(code)["texts"]
            except OSError:
                have = {}
            print(code, json.dumps([t for t in texts if t not in have], ensure_ascii=False, indent=0))
    else:
        errs = problems()
        print("\n".join(errs) or "traductions complètes")
        sys.exit(1 if errs else 0)
