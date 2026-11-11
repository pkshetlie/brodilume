"""Traduction de l'interface : français (langue du code, par défaut), anglais, allemand.

Les textes sont écrits en français dans le code, entourés de `_()`. Les fichiers lang/<code>.json
associent chaque texte français à sa traduction ; un texte absent reste en français.
La langue est lue dans les réglages au démarrage : en changer demande de relancer Brodilume.

    "texts" : {"Texte français": "Translation", ...}
    "keys"  : noms des touches affichés (« Maj » -> « Shift »), les raccourcis restant
              enregistrés sous leur nom français.
"""
import json
import os
import sys

LANGS = {"fr": "Français", "en": "English", "de": "Deutsch"}
DEFAULT = "fr"
LANG_DIR = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "lang")

_texts = {}
_keys = {}
lang = DEFAULT


def _saved_language():
    """Langue des réglages (%APPDATA%\\Brodilume\\settings.json, lu ici sans passer par shortcuts,
    qui utilise lui-même les traductions)."""
    path = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Brodilume", "settings.json")
    try:
        with open(path, encoding="utf-8") as f:
            v = json.load(f).get("language", DEFAULT)
    except (OSError, ValueError, AttributeError):
        v = DEFAULT
    return v if v in LANGS else DEFAULT


def load(code=None):
    """Charge la langue `code` (par défaut celle des réglages)."""
    global _texts, _keys, lang
    code = code or _saved_language()
    lang, _texts, _keys = code, {}, {}
    if code == DEFAULT:
        return
    try:
        with open(os.path.join(LANG_DIR, code + ".json"), encoding="utf-8") as f:
            data = json.load(f)
        _texts = data.get("texts", {})
        _keys = data.get("keys", {})
    except (OSError, ValueError):
        lang = DEFAULT


def _(text):
    """Texte traduit dans la langue choisie (le texte français s'il n'est pas traduit)."""
    return _texts.get(text) or text


def translate(code, text):
    """Texte dans une autre langue que celle de l'interface (ex. pour annoncer un changement de langue)."""
    if code == DEFAULT:
        return text
    try:
        with open(os.path.join(LANG_DIR, code + ".json"), encoding="utf-8") as f:
            return json.load(f).get("texts", {}).get(text) or text
    except (OSError, ValueError):
        return text


def key(combo):
    """« Ctrl+Maj+Z » affiché dans la langue choisie (« Ctrl+Shift+Z », « Strg+Umschalt+Z »)."""
    if not combo or not _keys:
        return combo
    if combo.endswith("++"):
        return "+".join(_keys.get(p, p) for p in combo[:-2].split("+")) + "++"
    return "+".join(_keys.get(p, p) for p in combo.split("+"))


load()
