"""Thèmes clair / sombre de Brodilume. Par défaut : celui de Windows (suivi en direct).

Toutes les couleurs de l'interface viennent de `C` (dictionnaire modifié sur place quand on
change de thème) ; `apply()` règle les styles ttk, les fenêtres Tk et la barre de titre Windows.
"""
import ctypes
import sys
import tkinter as tk
from tkinter import ttk

from i18n import _

LIGHT = {
    "name": "light",
    "bg": "#f0f0f0", "panel": "#f0f0f0", "fg": "#1e1e1e", "muted": "#6b6b6b", "faint": "#8a8a8a",
    "field": "#ffffff", "border": "#c8c8c8", "accent": "#2f7de1",
    "list": "#ffffff", "list_sel": "#d7e7fb", "list_head": "#f1f3f6", "list_fg": "#000000",
    "hidden_fg": "#999999", "danger": "#b44444",
    "view": "#dce9f5", "hoop": "#eef4fa", "hoop_line": "#7d93ab", "grid": "#d6e2ee", "grid_axis": "#b3c6da",
    "fade": (236, 242, 248), "jump": "#888888", "hint": "#6f6680", "image_bg": "#f3f3f3",
    "tool_bg": "#e9ecf1", "tool_active": "#cddff6", "tool_border": "#5b8fd6", "tool_hover": "#dde3ec",
    "tool_sep": "#c9ced8", "ink": (52, 48, 64, 255),
    "tip_bg": "#2b2833", "tip_fg": "#ffffff",
}
DARK = {
    "name": "dark",
    "bg": "#202124", "panel": "#26272b", "fg": "#e6e6e9", "muted": "#a2a2aa", "faint": "#7d7d86",
    "field": "#2f3035", "border": "#45464d", "accent": "#5b9cf0",
    "list": "#2a2b30", "list_sel": "#2f4a6e", "list_head": "#33353b", "list_fg": "#ececf0",
    "hidden_fg": "#6f7078", "danger": "#e07070",
    "view": "#17181b", "hoop": "#24262b", "hoop_line": "#6c7a8c", "grid": "#2e3138", "grid_axis": "#434856",
    "fade": (36, 38, 43), "jump": "#8a8a8a", "hint": "#a59db3", "image_bg": "#1b1c1f",
    "tool_bg": "#2b2c31", "tool_active": "#2f4a6e", "tool_border": "#5b9cf0", "tool_hover": "#383a41",
    "tool_sep": "#45464d", "ink": (222, 222, 230, 255),
    "tip_bg": "#f2f2f5", "tip_fg": "#1e1e1e",
}
C = dict(LIGHT)
MODES = ("system", "light", "dark")
MODE_LABELS = {"system": _("Comme Windows"), "light": _("Clair"), "dark": _("Sombre")}


def system_is_dark():
    """Windows : Paramètres > Personnalisation > Couleurs > mode des applications."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def resolve(mode):
    if mode == "system":
        return "dark" if system_is_dark() else "light"
    return "dark" if mode == "dark" else "light"


def hexc(rgb):
    return "#%02x%02x%02x" % tuple(rgb[:3])


def title_bar(win, dark):
    """Barre de titre Windows sombre ou claire (Windows 10 20H1+ / 11)."""
    if sys.platform != "win32":
        return
    try:
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        val = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (et l'ancien numéro)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), 4) == 0:
                break
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x27)  # SWP_FRAMECHANGED : redessine
    except Exception:
        pass


def apply(root, mode):
    """Applique le thème (mode = system / light / dark) ; retourne le nom effectif."""
    name = resolve(mode)
    C.clear()
    C.update(DARK if name == "dark" else LIGHT)
    st = ttk.Style(root)
    if not hasattr(root, "_native_theme"):
        root._native_theme = st.theme_use()
    if name == "light":
        st.theme_use(root._native_theme)  # les réglages faits pour « clam » ne touchent pas ce thème
        st.configure("Muted.TLabel", foreground=C["muted"])
    else:
        st.theme_use("clam")
        bg, fg, field, border = C["panel"], C["fg"], C["field"], C["border"]
        st.configure(".", background=bg, foreground=fg, fieldbackground=field, bordercolor=border,
                     lightcolor=bg, darkcolor=bg, troughcolor=C["bg"], focuscolor=C["accent"],
                     selectbackground=C["list_sel"], selectforeground=fg, insertcolor=fg, arrowcolor=fg)
        st.map(".", foreground=[("disabled", C["faint"])], background=[("disabled", bg)])
        for s in ("TFrame", "TLabel", "TLabelframe", "TCheckbutton", "TRadiobutton"):
            st.configure(s, background=bg, foreground=fg)
        st.configure("TLabelframe", bordercolor=border)
        st.configure("TLabelframe.Label", background=bg, foreground=fg)
        st.configure("TButton", background="#34363c", foreground=fg, bordercolor=border, padding=(8, 3))
        st.map("TButton", background=[("pressed", "#2a2c31"), ("active", "#3d4047"), ("disabled", bg)],
               foreground=[("disabled", C["faint"])])
        st.map("TCheckbutton", background=[("active", bg)], indicatorcolor=[("selected", C["accent"]),
                                                                           ("!selected", field)])
        st.map("TRadiobutton", background=[("active", bg)], indicatorcolor=[("selected", C["accent"]),
                                                                           ("!selected", field)])
        for s in ("TEntry", "TSpinbox", "TCombobox"):
            st.configure(s, fieldbackground=field, foreground=fg, background="#34363c", arrowcolor=fg,
                         bordercolor=border)
        st.map("TCombobox", fieldbackground=[("readonly", field), ("disabled", bg)],
               foreground=[("disabled", C["faint"])], selectbackground=[("readonly", field)],
               selectforeground=[("readonly", fg)])
        st.map("TSpinbox", fieldbackground=[("disabled", bg)], foreground=[("disabled", C["faint"])])
        st.configure("TNotebook", background=C["bg"], bordercolor=border, tabmargins=(2, 2, 2, 0))
        st.configure("TNotebook.Tab", background="#2b2c31", foreground=C["muted"], bordercolor=border,
                     padding=(10, 3))
        st.map("TNotebook.Tab", background=[("selected", bg)], foreground=[("selected", fg)],
               lightcolor=[("selected", bg)])
        st.configure("Treeview", background=C["list"], fieldbackground=C["list"], foreground=fg,
                     bordercolor=border)
        st.configure("Treeview.Heading", background="#34363c", foreground=fg, bordercolor=border)
        st.map("Treeview", background=[("selected", C["list_sel"])], foreground=[("selected", fg)])
        st.configure("TScrollbar", background="#3a3c42", troughcolor=C["bg"], bordercolor=bg, arrowcolor=fg)
        st.configure("TProgressbar", background=C["accent"], troughcolor=C["bg"], bordercolor=border)
        st.configure("Horizontal.TScale", background="#4a4d55", troughcolor="#34363c", bordercolor=border)
        st.configure("TSeparator", background=border)
        st.configure("Muted.TLabel", foreground=C["muted"], background=bg)
    st.configure("Toolbutton", padding=(6, 3))
    st.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))
    st.configure("Title.TLabel", font=("Segoe UI", 10, "bold"))
    root.option_add("*TCombobox*Listbox.background", C["field"])
    root.option_add("*TCombobox*Listbox.foreground", C["fg"])
    root.option_add("*TCombobox*Listbox.selectBackground", C["list_sel"])
    root.option_add("*Menu.background", C["field"])
    root.option_add("*Menu.foreground", C["fg"])
    root.option_add("*Menu.activeBackground", C["list_sel"])
    root.option_add("*Menu.activeForeground", C["fg"])
    root.configure(bg=C["bg"])
    title_bar(root, name == "dark")
    if not getattr(root, "_title_hook", False):
        # toute fenêtre Tk (paramètres, boîtes de dialogue…) reçoit la barre de titre du thème au moment
        # où Windows crée son cadre : avant, il n'y a pas encore de barre à régler
        def on_map(e):
            if e.widget is e.widget.winfo_toplevel():
                title_bar(e.widget, C["name"] == "dark")
        root.bind_class("Toplevel", "<Map>", on_map, add="+")
        root.bind_class("Tk", "<Map>", on_map, add="+")
        root._title_hook = True
    return name


def recolor_tree(widget):
    """Fenêtres Tk « classiques » (Frame, Label, Canvas, Toplevel) aux couleurs du thème."""
    for w in [widget] + _all_children(widget):
        cls = w.winfo_class()
        try:
            if cls in ("Frame", "Toplevel", "Tk") and not getattr(w, "_keep_bg", False):
                w.configure(bg=C["panel"])
            elif cls == "Menu":
                w.configure(bg=C["field"], fg=C["fg"], activebackground=C["list_sel"], activeforeground=C["fg"])
            elif cls == "Text":
                w.configure(bg=C["field"], fg=C["fg"], insertbackground=C["fg"], highlightbackground=C["border"],
                            highlightcolor=C["accent"], selectbackground=C["list_sel"], selectforeground=C["fg"])
        except tk.TclError:
            pass


def _all_children(w):
    out = []
    for c in w.winfo_children():
        out.append(c)
        out.extend(_all_children(c))
    return out
