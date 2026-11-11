"""Version de Brodilume et mises à jour depuis les « Releases » GitHub.

Rien n'est envoyé à GitHub à part une requête anonyme « dernière version ».
Le téléchargement et le remplacement de l'exécutable ne se font qu'après accord de l'utilisateur.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import urllib.request
import webbrowser

VERSION = "1.1.0"
REPO = "pkshetlie/brodilume"          # dépôt GitHub public (propriétaire/nom)
API_LATEST = "https://api.github.com/repos/%s/releases/latest" % REPO
PAGE_LATEST = "https://github.com/%s/releases/latest" % REPO
ALLOWED_HOSTS = ("https://github.com/", "https://objects.githubusercontent.com/")
ASSET_NAME = "Brodilume.exe"


def parse(v: str) -> tuple:
    """« v1.2.3 » -> (1, 2, 3) ; les parties non numériques sont ignorées."""
    nums = []
    for part in str(v).strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        if not digits:
            break
        nums.append(int(digits))
    return tuple(nums) or (0,)


def is_newer(latest: str, current: str = VERSION) -> bool:
    return parse(latest) > parse(current)


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def fetch_latest(timeout: float = 8.0):
    """Dernière version publiée : dict(version, tag, notes, url, asset), ou None si rien n'est publié."""
    req = urllib.request.Request(API_LATEST, headers={
        "User-Agent": "Brodilume/%s" % VERSION,
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    tag = data.get("tag_name") or ""
    if not tag:
        return None
    asset = None
    for a in data.get("assets") or []:
        if a.get("name", "").lower() == ASSET_NAME.lower():
            asset = a.get("browser_download_url")
            break
    return {"version": tag.lstrip("vV"), "tag": tag, "notes": data.get("body") or "",
            "url": data.get("html_url") or PAGE_LATEST, "asset": asset}


def download(url: str, dest: str, timeout: float = 60.0) -> str:
    """Télécharge le fichier de la version publiée (uniquement depuis GitHub)."""
    if not url.startswith(ALLOWED_HOSTS):
        raise RuntimeError("adresse de téléchargement non autorisée")
    req = urllib.request.Request(url, headers={"User-Agent": "Brodilume/%s" % VERSION})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
    if os.path.getsize(dest) < 1024 * 1024:
        raise RuntimeError("fichier téléchargé incomplet")
    return dest


def install_and_restart(new_exe: str) -> None:
    """Remplace l'exécutable en cours par new_exe, puis le relance.

    Un fichier en cours d'exécution ne peut pas être écrasé : un petit script attend la fin de Brodilume,
    copie le nouveau fichier, relance l'application et se supprime. Si la copie échoue (30 essais),
    le nouveau fichier est lancé depuis le dossier temporaire.
    """
    current = os.path.normpath(sys.executable)
    new_exe = os.path.normpath(new_exe)
    pid = os.getpid()
    bat = os.path.join(tempfile.gettempdir(), "brodilume_maj.bat")
    lines = [
        "@echo off",
        ":attente",
        'tasklist /FI "PID eq %d" 2>nul | find "%d" >nul' % (pid, pid),
        "if not errorlevel 1 (timeout /t 1 /nobreak >nul & goto attente)",
        "set /a essais=0",
        ":copie",
        "set /a essais+=1",
        'move /Y "%s" "%s" >nul 2>&1' % (new_exe, current),
        "if not errorlevel 1 goto ok",
        "if %essais% GEQ 30 goto echec",
        "timeout /t 1 /nobreak >nul",
        "goto copie",
        ":ok",
        'start "" "%s"' % current,
        'del "%~f0"',
        "exit /b 0",
        ":echec",
        'start "" "%s"' % new_exe,
        "exit /b 1",
        "",
    ]
    with open(bat, "w", encoding="mbcs", newline="\r\n") as f:
        f.write("\n".join(lines))
    flags = 0x08000000 | 0x00000008  # CREATE_NO_WINDOW | DETACHED_PROCESS
    subprocess.Popen(["cmd", "/c", bat], creationflags=flags, close_fds=True)


def open_page(url: str = PAGE_LATEST) -> None:
    webbrowser.open(url)
