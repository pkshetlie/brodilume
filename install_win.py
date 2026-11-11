"""Installation de Brodilume pour l'utilisateur courant (sans droits administrateur).

- Programme : %LOCALAPPDATA%\\Programs\\Brodilume\\Brodilume.exe (dossier modifiable par l'utilisateur,
  ce qui permet aussi la mise à jour automatique).
- Raccourcis : menu Démarrer (toujours), Bureau (au choix).
- Fichiers .brodi : double-clic = ouvrir dans Brodilume (au choix).
- Entrée « Brodilume » dans Paramètres > Applications, qui lance « Brodilume.exe --uninstall ».

Tout est écrit dans HKEY_CURRENT_USER. Les réglages (%APPDATA%\\Brodilume) sont conservés à la désinstallation.
Pour les tests, BRODILUME_TEST_ROOT redirige dossiers et registre vers un emplacement isolé.
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import winreg

APP = "Brodilume"
EXE = "Brodilume.exe"
PROG_ID = "Brodilume.Projet"
PUBLISHER = "Rhokapa"
UNINSTALL_KEY = r"Microsoft\Windows\CurrentVersion\Uninstall\Brodilume"
DESCRIPTION = "Image vers broderie (.vp4, .vp3, .pes…)"


def _test_root():
    return os.environ.get("BRODILUME_TEST_ROOT")


def _known_folder(csidl: int) -> str:
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
    return buf.value


def install_dir() -> str:
    t = _test_root()
    if t:
        return os.path.join(t, "Programs", APP)
    return os.path.join(os.environ.get("LOCALAPPDATA") or _known_folder(0x1C), "Programs", APP)


def start_menu_dir() -> str:
    t = _test_root()
    return os.path.join(t, "StartMenu") if t else _known_folder(0x02)  # CSIDL_PROGRAMS


def desktop_dir() -> str:
    t = _test_root()
    return os.path.join(t, "Desktop") if t else _known_folder(0x10)  # CSIDL_DESKTOPDIRECTORY


def _reg_base() -> str:
    return r"Software\BrodilumeTest" if _test_root() else "Software"


def exe_path() -> str:
    return os.path.join(install_dir(), EXE)


def is_installed() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _reg_base() + "\\" + UNINSTALL_KEY):
            return True
    except OSError:
        return False


def installed_version():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _reg_base() + "\\" + UNINSTALL_KEY) as k:
            return winreg.QueryValueEx(k, "DisplayVersion")[0]
    except OSError:
        return None


def is_running(path: str) -> bool:
    """Un .exe en cours d'exécution ne peut pas être ouvert en écriture."""
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r+b"):
            return False
    except PermissionError:
        return True
    except OSError:
        return False


def is_installed_copy(path: str) -> bool:
    """Ce programme est-il la copie installée (et non un .exe portable posé ailleurs) ?"""
    return os.path.normcase(os.path.abspath(path)) == os.path.normcase(exe_path())


# --------------------------------------------------------------------------- raccourcis

def make_shortcut(lnk: str, target: str, description: str = "") -> None:
    """Raccourci Windows (.lnk) via WScript.Shell. Les chemins passent par l'environnement (pas d'échappement)."""
    os.makedirs(os.path.dirname(lnk), exist_ok=True)
    env = dict(os.environ, BL_LNK=lnk, BL_TARGET=target, BL_DIR=os.path.dirname(target), BL_DESC=description)
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:BL_LNK);"
          "$s.TargetPath=$env:BL_TARGET;$s.WorkingDirectory=$env:BL_DIR;"
          "$s.IconLocation=$env:BL_TARGET+',0';$s.Description=$env:BL_DESC;$s.Save()")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], env=env,
                       creationflags=0x08000000, capture_output=True)
    if r.returncode != 0 or not os.path.exists(lnk):
        err = r.stderr.decode("mbcs", "replace").strip().splitlines()
        raise RuntimeError("raccourci non créé (%s) : %s" % (lnk, err[0] if err else r.returncode))


def shortcut_paths():
    """(menu Démarrer, Bureau)"""
    return [os.path.join(start_menu_dir(), APP + ".lnk"), os.path.join(desktop_dir(), APP + ".lnk")]


# --------------------------------------------------------------------------- registre

def _set(key, name, value, kind=winreg.REG_SZ):
    winreg.SetValueEx(key, name, 0, kind, value)


def register(version: str, associate: bool) -> None:
    exe = exe_path()
    base = _reg_base()
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + "\\" + UNINSTALL_KEY) as k:
        _set(k, "DisplayName", APP)
        _set(k, "DisplayVersion", version)
        _set(k, "Publisher", PUBLISHER)
        _set(k, "DisplayIcon", exe + ",0")
        _set(k, "InstallLocation", install_dir())
        _set(k, "UninstallString", '"%s" --uninstall' % exe)
        _set(k, "URLInfoAbout", "https://github.com/pkshetlie/brodilume")
        _set(k, "NoModify", 1, winreg.REG_DWORD)
        _set(k, "NoRepair", 1, winreg.REG_DWORD)
        size_kb = os.path.getsize(exe) // 1024 if os.path.exists(exe) else 0
        _set(k, "EstimatedSize", size_kb, winreg.REG_DWORD)
    if associate:
        classes = base + r"\Classes"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, classes + r"\.brodi") as k:
            _set(k, "", PROG_ID)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, classes + "\\" + PROG_ID) as k:
            _set(k, "", "Projet Brodilume")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, classes + "\\" + PROG_ID + r"\DefaultIcon") as k:
            _set(k, "", exe + ",0")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, classes + "\\" + PROG_ID + r"\shell\open\command") as k:
            _set(k, "", '"%s" "%%1"' % exe)
        _notify_shell()


def set_registered_version(version: str) -> None:
    """Après une mise à jour automatique : la version affichée dans Paramètres > Applications suit."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _reg_base() + "\\" + UNINSTALL_KEY, 0,
                            winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
            if winreg.QueryValueEx(k, "DisplayVersion")[0] != version:
                _set(k, "DisplayVersion", version)
    except OSError:
        pass


def _delete_tree(root, path):
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_READ | winreg.KEY_WRITE) as k:
            while True:
                try:
                    sub = winreg.EnumKey(k, 0)
                except OSError:
                    break
                _delete_tree(root, path + "\\" + sub)
        winreg.DeleteKey(root, path)
    except FileNotFoundError:
        pass


def unregister() -> None:
    base = _reg_base()
    _delete_tree(winreg.HKEY_CURRENT_USER, base + "\\" + UNINSTALL_KEY)
    classes = base + r"\Classes"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, classes + r"\.brodi") as k:
            ours = winreg.QueryValueEx(k, "")[0] == PROG_ID
    except OSError:
        ours = False
    if ours:  # ne pas toucher une association choisie par l'utilisateur pour un autre programme
        _delete_tree(winreg.HKEY_CURRENT_USER, classes + r"\.brodi")
    _delete_tree(winreg.HKEY_CURRENT_USER, classes + "\\" + PROG_ID)
    _notify_shell()


def _notify_shell():
    if not _test_root():
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED


# --------------------------------------------------------------------------- installer / désinstaller

def install(source_exe: str, version: str, desktop: bool = True, associate: bool = True) -> str:
    """Copie le programme, crée les raccourcis et l'entrée de désinstallation. Renvoie le chemin installé."""
    os.makedirs(install_dir(), exist_ok=True)
    target = exe_path()
    tmp = target + ".nouveau"
    shutil.copyfile(source_exe, tmp)
    os.replace(tmp, target)
    menu, desk = shortcut_paths()
    make_shortcut(menu, target, DESCRIPTION)
    if desktop:
        make_shortcut(desk, target, DESCRIPTION)
    elif os.path.exists(desk):
        os.remove(desk)
    register(version, associate)
    return target


def uninstall() -> list:
    """Retire raccourcis et registre, puis le programme (après sa fermeture s'il se désinstalle lui-même).
    Renvoie les éléments qui n'ont pas pu être retirés."""
    left = []
    for lnk in shortcut_paths():
        try:
            if os.path.exists(lnk):
                os.remove(lnk)
        except OSError:
            left.append(lnk)
    unregister()
    folder = install_dir()
    if is_installed_copy(sys.executable):
        _delete_after_exit(folder)
    elif os.path.isdir(folder):
        shutil.rmtree(folder, ignore_errors=True)
        if os.path.isdir(folder):
            left.append(folder)
    return left


def _delete_after_exit(folder: str) -> None:
    """Un programme ne peut pas s'effacer lui-même : un petit script attend sa fermeture puis supprime le dossier."""
    pid = os.getpid()
    bat = os.path.join(tempfile.gettempdir(), "brodilume_desinstall.bat")
    lines = [
        "@echo off",
        ":attente",
        'tasklist /FI "PID eq %d" 2>nul | find "%d" >nul' % (pid, pid),
        "if not errorlevel 1 (timeout /t 1 /nobreak >nul & goto attente)",
        'rmdir /S /Q "%s"' % os.path.normpath(folder),
        'del "%~f0"',
        "",
    ]
    with open(bat, "w", encoding="mbcs", newline="\r\n") as f:
        f.write("\n".join(lines))
    subprocess.Popen(["cmd", "/c", bat], creationflags=0x08000000 | 0x00000008, close_fds=True)


def run_uninstall_ui() -> None:
    """« Brodilume.exe --uninstall » (lancé depuis Paramètres > Applications)."""
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    if not messagebox.askyesno("Désinstaller Brodilume",
                               "Désinstaller Brodilume ?\n\nVos projets (.brodi) et vos réglages sont conservés."):
        root.destroy()
        return
    left = uninstall()
    if left:
        messagebox.showwarning("Désinstaller Brodilume",
                               "Brodilume est désinstallé, mais ces éléments n'ont pas pu être retirés :\n\n"
                               + "\n".join(left))
    else:
        messagebox.showinfo("Désinstaller Brodilume", "Brodilume a été désinstallé.")
    root.destroy()
