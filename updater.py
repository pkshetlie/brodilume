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

VERSION = "1.2.0"
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

    Un fichier en cours d'exécution ne peut pas être écrasé : un petit script attend la fin de Brodilume
    (et de son lanceur PyInstaller, qui garde le fichier ouvert un instant de plus), remplace le fichier,
    relance l'application et se supprime. Si le remplacement échoue pendant une minute, le nouveau
    fichier est lancé depuis le dossier temporaire. Le déroulement est noté dans brodilume_maj.log.
    """
    current = os.path.normpath(sys.executable)
    new_exe = os.path.normpath(new_exe)
    tmp = tempfile.gettempdir()
    bat = os.path.join(tmp, "brodilume_maj.bat")
    log = os.path.join(tmp, "brodilume_maj.log")
    pids = [os.getpid()]
    if is_frozen() and os.getppid() not in pids:  # lanceur PyInstaller (« onefile »)
        pids.append(os.getppid())
    lines = ["@echo off", 'echo %%date%% %%time%% debut > "%s"' % log]
    for k, pid in enumerate(pids):
        # « timeout » ne marche pas sans console : « ping » sert de pause d'une seconde
        lines += [":attente%d" % k,
                  'tasklist /NH /FI "PID eq %d" 2>nul | find " %d " >nul' % (pid, pid),
                  "if not errorlevel 1 (ping -n 2 127.0.0.1 >nul & goto attente%d)" % k]
    lines += [
        "set /a essais=0",
        ":copie",
        "set /a essais+=1",
        'copy /Y /B "%s" "%s" >nul 2>&1' % (new_exe, current),
        "if not errorlevel 1 goto ok",
        "if %essais% GEQ 60 goto echec",
        "ping -n 2 127.0.0.1 >nul",
        "goto copie",
        ":ok",
        'echo %%date%% %%time%% remplace apres %%essais%% essai(s) >> "%s"' % log,
        'del "%s" >nul 2>&1' % new_exe,
        'start "" "%s"' % current,
        'del "%~f0"',
        "exit /b 0",
        ":echec",
        'echo %%date%% %%time%% echec du remplacement, lancement depuis le dossier temporaire >> "%s"' % log,
        'start "" "%s"' % new_exe,
        "exit /b 1",
        "",
    ]
    with open(bat, "w", encoding="mbcs", newline="\r\n") as f:
        f.write("\n".join(lines))
    spawn(["cmd", "/c", bat])


def clean_env():
    """Environnement sans les variables internes de PyInstaller.

    Sans cela, un Brodilume.exe lancé par Brodilume se croit déjà décompressé et cherche ses fichiers
    dans le dossier temporaire de l'ancien, effacé à sa fermeture : il s'arrête sans rien afficher."""
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("_PYI_", "_MEIPASS"))}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def spawn(args, **kw):
    """Lance un programme indépendant de Brodilume : il survit à sa fermeture (hors du « job » du
    lanceur PyInstaller quand Windows le permet), sans fenêtre de console, environnement nettoyé."""
    base = 0x08000000 | 0x00000200  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    err = None
    for flags in (base | 0x01000000, base):  # + CREATE_BREAKAWAY_FROM_JOB, refusé par certains jobs
        try:
            return subprocess.Popen(args, creationflags=flags, close_fds=True, env=clean_env(), **kw)
        except OSError as e:
            err = e
    raise err


def plain_notes(text: str, limit: int = 1500) -> str:
    """Notes de version (Markdown de GitHub) -> texte simple pour la fenêtre de mise à jour."""
    import re
    out = []
    for line in text.replace("\r\n", "\n").split("\n"):
        line = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), line)
        line = re.sub(r"`([^`]*)`", r"\1", line)
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        line = re.sub(r"^\s*#+\s*", "", line)
        line = re.sub(r"^(\s*)[-*+]\s+", r"\1• ", line)
        out.append(line.rstrip())
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    if len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        text = text[:cut if cut > limit // 2 else limit].rstrip() + "\n…"
    return text


def open_page(url: str = PAGE_LATEST) -> None:
    webbrowser.open(url)
