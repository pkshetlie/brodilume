"""Programme d'installation de Brodilume (Brodilume-Setup.exe).

Contient Brodilume.exe et l'installe pour l'utilisateur courant, sans droits administrateur :
voir install_win.py pour ce qui est créé. Fabriqué par build_exe.bat.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk

from i18n import _
import install_win
import theme
import updater

HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def _payload() -> str:
    """Brodilume.exe embarqué (ou dist\\Brodilume.exe quand on lance ce script depuis le code source)."""
    for p in (os.path.join(HERE, "Brodilume.exe"), os.path.join(HERE, "dist", "Brodilume.exe")):
        if os.path.exists(p):
            return p
    raise FileNotFoundError(_("Brodilume.exe introuvable dans le programme d'installation"))


def _license_text() -> str:
    for p in (os.path.join(HERE, "LICENSE"),):
        if os.path.exists(p):
            return open(p, encoding="utf-8").read()
    return "PolyForm Noncommercial License 1.0.0 — https://polyformproject.org/licenses/noncommercial/1.0.0"


class Setup(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(_("Installer Brodilume"))
        self.resizable(False, False)
        theme.apply(self, "system")
        C = theme.C
        self.configure(bg=C["panel"])
        ico = os.path.join(HERE, "assets", "brodilume.ico")
        if os.path.exists(ico):
            try:
                self.iconbitmap(ico)
            except tk.TclError:
                pass
        frm = ttk.Frame(self, padding=(24, 20))
        frm.pack(fill="both")
        logo = os.path.join(HERE, "assets", "brodilume-icone-72.png")
        if os.path.exists(logo):
            self._logo = tk.PhotoImage(file=logo)
            ttk.Label(frm, image=self._logo).pack(anchor="w", pady=(0, 14))
        ttk.Label(frm, text=_("Installer Brodilume %s") % updater.VERSION, style="Title.TLabel",
                  font=("Segoe UI", 13, "bold")).pack(anchor="w")
        ttk.Label(frm, text=_("Brodilume sera installé pour vous seul, sans droits administrateur, dans :"),
                  wraplength=460, justify="left").pack(anchor="w", pady=(8, 0))
        ttk.Label(frm, text=install_win.install_dir(), style="Muted.TLabel", wraplength=460,
                  justify="left").pack(anchor="w")
        old = install_win.installed_version()
        if old:
            ttk.Label(frm, text=_("La version %s déjà installée sera remplacée. Vos projets et vos réglages sont "
                                "conservés.") % old, wraplength=460, justify="left").pack(anchor="w", pady=(8, 0))
        self.v_desktop = tk.BooleanVar(value=True)
        self.v_assoc = tk.BooleanVar(value=True)
        self.v_launch = tk.BooleanVar(value=True)
        opts = ttk.Frame(frm)
        opts.pack(anchor="w", pady=(14, 0))
        ttk.Checkbutton(opts, text=_("Créer un raccourci sur le Bureau"), variable=self.v_desktop).pack(anchor="w")
        ttk.Checkbutton(opts, text=_("Ouvrir les projets .brodi avec Brodilume (double-clic)"),
                        variable=self.v_assoc).pack(anchor="w", pady=2)
        ttk.Checkbutton(opts, text=_("Lancer Brodilume à la fin de l'installation"),
                        variable=self.v_launch).pack(anchor="w")
        lic = ttk.Frame(frm)
        lic.pack(anchor="w", fill="x", pady=(14, 0))
        ttk.Label(lic, text=_("Licence PolyForm Noncommercial : utilisation libre, sauf commerciale."),
                  style="Muted.TLabel").pack(side="left")
        ttk.Button(lic, text=_("Lire la licence"), command=self.show_license).pack(side="left", padx=(8, 0))
        self.v_status = tk.StringVar(value="")
        ttk.Label(frm, textvariable=self.v_status, wraplength=460, justify="left").pack(anchor="w", pady=(12, 0))
        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(14, 0))
        ttk.Button(btns, text=_("Annuler"), command=self.destroy).pack(side="right")
        self.btn = ttk.Button(btns, text=_("Installer"), style="Accent.TButton", command=self.install)
        self.btn.pack(side="right", padx=(0, 8))
        self.btn.focus_set()
        self.bind("<Return>", lambda e: self.install())
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        x = (self.winfo_screenwidth() - self.winfo_width()) // 2
        y = (self.winfo_screenheight() - self.winfo_height()) // 3
        self.geometry("+%d+%d" % (x, y))

    def show_license(self):
        win = tk.Toplevel(self, bg=theme.C["panel"])
        win.title(_("Licence de Brodilume"))
        win.transient(self)
        txt = tk.Text(win, width=90, height=30, wrap="word", bg=theme.C["field"], fg=theme.C["fg"],
                      relief="flat", padx=10, pady=10)
        txt.insert("1.0", _license_text())
        txt.config(state="disabled")
        txt.pack(fill="both", expand=True, padx=10, pady=10)
        ttk.Button(win, text=_("Fermer"), command=win.destroy).pack(pady=(0, 10))

    def install(self):
        if str(self.btn["state"]) == "disabled":
            return
        target = install_win.exe_path()
        if install_win.is_running(target):
            self.v_status.set(_("Brodilume est ouvert : fermez-le, puis cliquez de nouveau sur « Installer »."))
            return
        self.btn.state(["disabled"])
        self.v_status.set(_("Installation en cours…"))
        self.update()
        try:
            exe = install_win.install(_payload(), updater.VERSION, desktop=self.v_desktop.get(),
                                      associate=self.v_assoc.get())
        except Exception as e:
            self.btn.state(["!disabled"])
            self.v_status.set(_("L'installation a échoué :\n%s") % e)
            return
        if self.v_launch.get():
            subprocess.Popen([exe], cwd=os.path.dirname(exe), close_fds=True,
                             creationflags=0x00000008)  # DETACHED_PROCESS
            self.destroy()
            return
        self.v_status.set(_("Brodilume est installé. Vous le trouverez dans le menu Démarrer."))
        self.btn.config(text=_("Terminer"), command=self.destroy)
        self.btn.state(["!disabled"])


if __name__ == "__main__":
    Setup().mainloop()
