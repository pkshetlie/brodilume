"""Intégration Windows sans dépendance : glisser-déposer de fichiers depuis l'Explorateur et
lecture du presse-papiers (image copiée, fichiers copiés).

Glisser-déposer : la fenêtre s'inscrit avec DragAcceptFiles et sa procédure de fenêtre est
« sous-classée » pour recevoir WM_DROPFILES (même principe que la bibliothèque windnd).
"""
import ctypes
import sys
from ctypes import wintypes

WM_DROPFILES = 0x0233
GWLP_WNDPROC = -4

if sys.platform == "win32":
    user32 = ctypes.windll.user32
    shell32 = ctypes.windll.shell32
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    user32.CallWindowProcW.restype = LRESULT
    user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                       wintypes.LPARAM]
    user32.GetParent.restype = wintypes.HWND
    user32.GetParent.argtypes = [wintypes.HWND]
    shell32.DragQueryFileW.restype = wintypes.UINT
    shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
    shell32.DragFinish.argtypes = [ctypes.c_void_p]
    shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
    # autorise le dépôt quand l'application tourne avec des droits différents de l'Explorateur
    try:
        user32.ChangeWindowMessageFilter(WM_DROPFILES, 1)
        user32.ChangeWindowMessageFilter(0x0049, 1)  # WM_COPYGLOBALDATA
    except Exception:
        pass


def top_hwnd(widget):
    """Fenêtre Windows « cadre » d'une fenêtre Tk (celle qui a la barre de titre)."""
    hwnd = widget.winfo_id()
    parent = user32.GetParent(hwnd)
    return parent or hwnd


def enable_file_drop(widget, callback):
    """callback(liste de chemins) est appelé quand on dépose des fichiers sur la fenêtre.

    La procédure de fenêtre est appelée par Windows au milieu de la boucle de Tk : elle ne fait
    que noter les fichiers ; un petit relevé périodique (after) les transmet ensuite."""
    if sys.platform != "win32":
        return False
    hwnd = top_hwnd(widget)
    old = user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, None)
    user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, old)

    def proc(h, msg, wp, lp):
        if msg == WM_DROPFILES:
            n = shell32.DragQueryFileW(wp, 0xFFFFFFFF, None, 0)
            files = []
            for i in range(n):
                ln = shell32.DragQueryFileW(wp, i, None, 0) + 1
                buf = ctypes.create_unicode_buffer(ln)
                shell32.DragQueryFileW(wp, i, buf, ln)
                files.append(buf.value)
            shell32.DragFinish(wp)
            dropped.append(files)  # surtout pas d'appel à Tk ici (on est dans la boucle de Tk)
            return 0
        return user32.CallWindowProcW(old, h, msg, wp, lp)

    dropped = []

    def poll():  # côté Tk : on traite les dépôts mis de côté par la procédure de fenêtre
        while dropped:
            callback(dropped.pop(0))
        widget.after(150, poll)

    ref = WNDPROC(proc)
    widget._drop_proc = ref  # garder une référence : sinon le ramasse-miettes la libère
    user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, ctypes.cast(ref, ctypes.c_void_p))
    shell32.DragAcceptFiles(hwnd, True)
    widget.after(150, poll)
    return True


def clipboard_content():
    """Contenu du presse-papiers Windows : ("image", PIL.Image), ("files", [chemins]) ou (None, None)."""
    try:
        from PIL import ImageGrab
        data = ImageGrab.grabclipboard()
    except Exception:
        return None, None
    if data is None:
        return None, None
    if isinstance(data, list):
        return ("files", [str(p) for p in data]) if data else (None, None)
    return "image", data
