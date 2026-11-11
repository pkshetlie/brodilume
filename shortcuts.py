"""Raccourcis clavier de Brodilume : liste des actions, lecture des touches, réglages enregistrés.

Les raccourcis sont écrits sous une forme lisible (« Ctrl+Maj+Z », « Suppr », « F5 ») et gardés
dans %APPDATA%/Brodilume/settings.json. Une seule fonction lit toutes les touches de la fenêtre
(`combo_from_event`) : changer un raccourci ne demande donc aucun nouveau « bind » Tk.
"""
import json
import os
import tkinter as tk
from tkinter import ttk, messagebox

# (identifiant, libellé, raccourcis par défaut) — groupés par rubrique pour la fenêtre des réglages
ACTIONS = [
    ("Édition", [
        ("undo", "Annuler", ["Ctrl+Z"]),
        ("redo", "Rétablir", ["Ctrl+Y", "Ctrl+Maj+Z"]),
        ("copy", "Copier (élément ou parties sélectionnées)", ["Ctrl+C"]),
        ("cut", "Couper", ["Ctrl+X"]),
        ("paste", "Coller (élément copié, image ou fichiers du presse-papiers)", ["Ctrl+V", "Maj+Inser"]),
        ("duplicate", "Dupliquer l'élément", ["Ctrl+D"]),
        ("delete", "Supprimer la sélection", ["Suppr", "Retour"]),
        ("select_all", "Sélectionner toutes les parties de l'élément", ["Ctrl+A"]),
        ("merge_parts", "Fusionner les couleurs sélectionnées", ["Ctrl+G"]),
        ("deselect", "Désélectionner", ["Échap"]),
    ]),
    ("Fichier", [
        ("new", "Nouveau projet", ["Ctrl+N"]),
        ("open", "Ouvrir un projet (.brodi)", ["Ctrl+O"]),
        ("add", "Importer une image / broderie", ["Ctrl+I"]),
        ("save", "Enregistrer le projet", ["Ctrl+S"]),
        ("save_as", "Enregistrer le projet sous…", ["Ctrl+Maj+S"]),
        ("export_vp4", "Exporter en .vp4", ["Ctrl+E"]),
        ("export", "Exporter l'aperçu PNG", ["Ctrl+Maj+E"]),
        ("usb", "Envoyer sur la clé USB", ["Ctrl+U"]),
        ("regen", "Régénérer l'image", ["F5"]),
        ("settings", "Paramètres et raccourcis", ["Ctrl+,", "F1"]),
        ("close", "Fermer le projet", ["Ctrl+W"]),
        ("quit", "Quitter", ["Ctrl+Q"]),
    ]),
    ("Outils", [
        ("tool_move", "Outil Sélection (choisir, déplacer, taille, rotation)", ["V"]),
        ("tool_pick", "Outil Couleurs", ["C"]),
        ("tool_erase", "Outil Gomme", ["E"]),
        ("tool_hand", "Outil Main (faire glisser la vue)", ["H"]),
        ("tool_zoom", "Outil Zoom", ["Z"]),
    ]),
    ("Élément", [
        ("rot_cw", "Tourner de 90° (sens horaire)", ["R"]),
        ("rot_ccw", "Tourner de 90° (sens inverse)", ["Maj+R"]),
        ("center", "Centrer dans le cercle", ["Début"]),
        ("order_up", "Broder plus tôt (monter dans la liste)", ["PgPréc"]),
        ("order_down", "Broder plus tard (descendre dans la liste)", ["PgSuiv"]),
        ("colors_less", "Une couleur de moins", ["Ctrl+-"]),
        ("colors_more", "Une couleur de plus", ["Ctrl++"]),
        ("move_left", "Déplacer l'élément à gauche (1 mm, Maj : 10 mm ; sans sélection : la vue)", ["Gauche"]),
        ("move_right", "Déplacer à droite", ["Droite"]),
        ("move_up", "Déplacer vers le haut", ["Haut"]),
        ("move_down", "Déplacer vers le bas", ["Bas"]),
    ]),
    ("Vue", [
        ("fit", "Ajuster la vue au motif", ["0"]),
        ("hoop", "Voir le cercle entier", ["Ctrl+1"]),
        ("zoom_100", "Taille réelle (100 %)", ["Ctrl+0"]),
        ("pan_left", "Faire défiler la vue à gauche (Maj : plus vite)", ["Ctrl+Gauche"]),
        ("pan_right", "Faire défiler la vue à droite", ["Ctrl+Droite"]),
        ("pan_up", "Faire défiler la vue vers le haut", ["Ctrl+Haut"]),
        ("pan_down", "Faire défiler la vue vers le bas", ["Ctrl+Bas"]),
        ("zoom_in", "Zoom avant", ["+"]),
        ("zoom_out", "Zoom arrière", ["-"]),
        ("play", "Simuler / pause (Espace maintenu + glisser : main)", ["Espace"]),
        ("jumps", "Afficher les sauts", ["J"]),
        ("theme", "Basculer thème clair / sombre", ["Ctrl+Maj+T"]),
    ]),
]

MOUSE_HELP = [
    ("Ctrl + molette (ou Alt + molette)", "Zoom sous la souris"),
    ("Molette", "Faire défiler la vue de haut en bas"),
    ("Maj + molette", "Faire défiler la vue de gauche à droite"),
    ("Bouton du milieu (ou droit) + glisser", "Déplacer la vue"),
    ("… avec Maj", "Déplacer la vue sur un seul axe"),
    ("Espace maintenu + glisser", "Déplacer la vue (main temporaire)"),
    ("Double-clic (outil Couleurs)", "Toutes les parties du fil"),
]
HOOPS = [(100, 100), (120, 115), (120, 120), (150, 150), (170, 100), (180, 130), (200, 200), (225, 140),
         (240, 150), (260, 200), (260, 260), (360, 200), (360, 260), (360, 350)]
DEFAULTS = {a: list(keys) for _, acts in ACTIONS for a, _, keys in acts}
LABELS = {a: label for _, acts in ACTIONS for a, label, _ in acts}
# actions qui gardent Maj comme variante (déplacement de 10 mm au lieu de 1 mm)
SHIFT_VARIANT = {"move_left", "move_right", "move_up", "move_down", "pan_left", "pan_right", "pan_up",
                 "pan_down"}

NAMES = {
    "space": "Espace", "Delete": "Suppr", "BackSpace": "Retour", "Escape": "Échap", "Return": "Entrée",
    "KP_Enter": "Entrée", "Tab": "Tab", "Insert": "Inser", "Home": "Début", "End": "Fin",
    "Prior": "PgPréc", "Next": "PgSuiv", "Left": "Gauche", "Right": "Droite", "Up": "Haut",
    "Down": "Bas", "plus": "+", "KP_Add": "+", "minus": "-", "KP_Subtract": "-", "equal": "=",
    "comma": ",", "period": ".", "semicolon": ";", "colon": ":", "exclam": "!", "slash": "/",
    "KP_Divide": "/", "asterisk": "*", "KP_Multiply": "*", "question": "?",
    "agrave": "0",  # AZERTY : la touche 0 sans Maj donne « à »
}
NAMED_KEYS = set(NAMES.values()) - {"+", "-", "=", ",", ".", ";", ":", "!", "/", "*", "?"}
MODIFIERS = {"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Meta_L", "Meta_R",
             "Win_L", "Win_R", "Caps_Lock", "Num_Lock", "ISO_Level3_Shift", "App"}


def key_name(keysym):
    if keysym in NAMES:
        return NAMES[keysym]
    if keysym.startswith("KP_") and keysym[3:].isdigit():
        return keysym[3:]
    if len(keysym) == 1:
        return keysym.upper()
    return keysym  # F1…F12, etc.


def combo_from_event(e):
    """Touche pressée -> « Ctrl+Maj+Z » ; None pour une touche de modification seule.

    Maj n'est gardé que pour les lettres, les touches nommées (flèches, Suppr…) et les F1-F12 :
    sur un clavier AZERTY, « 0 » ou « + » s'obtiennent avec Maj, qui ne doit donc pas compter."""
    if e.keysym in MODIFIERS or not e.keysym or e.keysym == "??":
        return None
    name = key_name(e.keysym)
    ctrl, shift, alt = bool(e.state & 0x4), bool(e.state & 0x1), bool(e.state & 0x20000)
    keep_shift = (len(name) == 1 and name.isalpha()) or name in NAMED_KEYS or (
        name.startswith("F") and name[1:].isdigit())
    parts = []
    if ctrl:
        parts.append("Ctrl")
    if alt:
        parts.append("Alt")
    if shift and keep_shift:
        parts.append("Maj")
    parts.append(name)
    return "+".join(parts)  # « Ctrl++ » pour Ctrl et la touche +


def config_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Brodilume", "settings.json")


def load_bindings():
    keys = {a: list(v) for a, v in DEFAULTS.items()}
    try:
        with open(config_path(), encoding="utf-8") as f:
            saved = json.load(f).get("keys", {})
        for a, v in saved.items():
            if a in keys and isinstance(v, list):
                keys[a] = [str(x) for x in v]
    except (OSError, ValueError):
        pass
    return keys


def load_setting(key, default=None):
    try:
        with open(config_path(), encoding="utf-8") as f:
            return json.load(f).get(key, default)
    except (OSError, ValueError):
        return default


def save_setting(key, value):
    path = config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        pass
    data[key] = value
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_bindings(keys):
    path = config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        pass
    data["keys"] = keys
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def lookup_table(keys):
    """« Ctrl+Z » -> action (et « Maj+Gauche » -> move_left pour le pas de 10 mm)."""
    table = {}
    for a, combos in keys.items():
        for c in combos:
            table.setdefault(c, a)
            if a in SHIFT_VARIANT and "Maj+" not in c:
                parts = c.split("+")
                table.setdefault("+".join(parts[:-1] + ["Maj", parts[-1]]), a)
    return table


class SettingsDialog(tk.Toplevel):
    """Paramètres : onglet « Raccourcis clavier » (modifier, ajouter, retirer, rétablir)."""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Paramètres — Brodilume")
        self.geometry("760x780")
        self.transient(app)
        self.keys = {a: list(v) for a, v in app.keys.items()}
        import theme
        self.configure(bg=theme.C["panel"])
        theme.title_bar(self, theme.C["name"] == "dark")
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=(10, 0))
        gen = ttk.Frame(nb, padding=12)
        nb.add(gen, text="Général")
        ttk.Label(gen, text="Thème", style="Title.TLabel").pack(anchor="w")
        self.v_theme = tk.StringVar(value=app.theme_mode)
        for m in theme.MODES:
            ttk.Radiobutton(gen, text=theme.MODE_LABELS[m], value=m, variable=self.v_theme,
                            command=lambda: app.set_theme(self.v_theme.get())).pack(anchor="w", pady=1)
        ttk.Label(gen, text="« Comme Windows » suit Paramètres > Personnalisation > Couleurs, même pendant que "
                            "Brodilume est ouvert.", style="Muted.TLabel", wraplength=640).pack(anchor="w", pady=(4, 0))
        ttk.Label(gen, text="Espace de broderie (cercle)", style="Title.TLabel").pack(anchor="w", pady=(18, 4))
        hrow = ttk.Frame(gen)
        hrow.pack(anchor="w")
        w0, h0 = app.hoop_mm
        names = ["%d × %d mm" % wh for wh in HOOPS] + ["Personnalisé"]
        cur = "%d × %d mm" % (w0, h0)
        self.v_hoop = tk.StringVar(value=cur if cur in names else "Personnalisé")
        self.v_hw, self.v_hh = tk.DoubleVar(value=w0), tk.DoubleVar(value=h0)
        cb = ttk.Combobox(hrow, textvariable=self.v_hoop, values=names, state="readonly", width=16)
        cb.pack(side="left")
        ttk.Label(hrow, text="  largeur").pack(side="left")
        ttk.Spinbox(hrow, from_=50, to=500, increment=5, textvariable=self.v_hw, width=6).pack(side="left", padx=4)
        ttk.Label(hrow, text="hauteur").pack(side="left")
        ttk.Spinbox(hrow, from_=50, to=500, increment=5, textvariable=self.v_hh, width=6).pack(side="left", padx=4)
        ttk.Label(hrow, text="mm").pack(side="left")
        ttk.Button(hrow, text="Appliquer", command=self.apply_hoop).pack(side="left", padx=(10, 0))

        def preset(_e=None):
            if self.v_hoop.get() != "Personnalisé":
                w, h = HOOPS[names.index(self.v_hoop.get())]
                self.v_hw.set(w)
                self.v_hh.set(h)
                self.apply_hoop()
        cb.bind("<<ComboboxSelected>>", preset)
        ttk.Label(gen, text="Cercles « Universal » de mySewnet. Jusqu'à 260 × 200 mm, le fichier indique le cercle "
                            "UniLarge3 (vérifié) ; au-delà, son nom Universal_LxH (à vérifier dans mySewnet).",
                  style="Muted.TLabel", wraplength=640).pack(anchor="w", pady=(4, 0))
        ttk.Label(gen, text="Mises à jour", style="Title.TLabel").pack(anchor="w", pady=(18, 4))
        import updater
        self.v_updates = tk.BooleanVar(value=load_setting("check_updates", True))
        ttk.Checkbutton(gen, text="Vérifier les mises à jour au démarrage", variable=self.v_updates,
                        command=lambda: save_setting("check_updates", bool(self.v_updates.get()))).pack(anchor="w")
        urow = ttk.Frame(gen)
        urow.pack(anchor="w", pady=(4, 0))
        ttk.Label(urow, text="Version %s" % updater.VERSION).pack(side="left")
        ttk.Button(urow, text="Vérifier maintenant", command=lambda: app._start_update_check(manual=True)).pack(
            side="left", padx=(12, 0))
        tab = ttk.Frame(nb, padding=8)
        nb.add(tab, text="Raccourcis clavier")
        ttk.Label(tab, text="Double-clic sur une action pour lui donner un nouveau raccourci. "
                            "Une action peut en avoir plusieurs.", style="Muted.TLabel").pack(anchor="w")
        cols = ttk.Frame(tab)
        cols.pack(fill="both", expand=True, pady=6)
        self.tree = ttk.Treeview(cols, columns=("keys",), selectmode="browse")
        self.tree.heading("#0", text="Action")
        self.tree.heading("keys", text="Raccourci(s)")
        self.tree.column("#0", width=420)
        self.tree.column("keys", width=220)
        sb = ttk.Scrollbar(cols, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self.capture(replace=True))
        btns = ttk.Frame(tab)
        btns.pack(fill="x")
        for txt, cmd in (("Modifier…", lambda: self.capture(replace=True)),
                         ("Ajouter un raccourci…", lambda: self.capture(replace=False)),
                         ("Retirer les raccourcis", self.clear), ("Par défaut (cette action)", self.reset_one),
                         ("Tout par défaut", self.reset_all)):
            ttk.Button(btns, text=txt, command=cmd).pack(side="left", padx=(0, 4))
        ttk.Label(tab, text="Dans un champ de saisie, Ctrl+C / X / V / A / Z / Y gardent leur rôle habituel "
                            "(texte).", style="Muted.TLabel").pack(anchor="w", pady=(8, 0))
        mouse = ttk.LabelFrame(tab, text="Souris", padding=6)
        mouse.pack(fill="x", pady=(8, 0))
        for i, (k_, v_) in enumerate(MOUSE_HELP):
            ttk.Label(mouse, text=k_).grid(row=i, column=0, sticky="w", padx=(0, 16))
            ttk.Label(mouse, text=v_, style="Muted.TLabel").grid(row=i, column=1, sticky="w")
        bottom = ttk.Frame(self, padding=10)
        bottom.pack(fill="x")
        ttk.Label(bottom, text="Enregistré dans " + config_path(), style="Muted.TLabel").pack(side="left")
        ttk.Button(bottom, text="Annuler", command=self.destroy).pack(side="right")
        ttk.Button(bottom, text="OK", command=self.ok).pack(side="right", padx=6)
        self.fill()
        self.grab_set()

    def fill(self):
        sel = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for group, acts in ACTIONS:
            g = self.tree.insert("", "end", text=group, open=True)
            for a, label, _ in acts:
                self.tree.insert(g, "end", iid=a, text=label, values=("   ou   ".join(self.keys[a]) or "—",))
        if sel and self.tree.exists(sel[0]):
            self.tree.selection_set(sel[0])
            self.tree.see(sel[0])

    def current(self):
        s = self.tree.selection()
        return s[0] if s and s[0] in DEFAULTS else None

    def capture(self, replace):
        a = self.current()
        if not a:
            return
        import theme
        win = tk.Toplevel(self, bg=theme.C["panel"])
        win.title("Nouveau raccourci")
        theme.title_bar(win, theme.C["name"] == "dark")
        win.transient(self)
        win.geometry("+%d+%d" % (self.winfo_rootx() + 150, self.winfo_rooty() + 200))
        ttk.Label(win, text="« %s »\n\nAppuyez sur la combinaison de touches voulue.\n"
                            "(Échap seul : annuler)" % LABELS[a], padding=20, justify="center").pack()
        win.focus_force()
        win.grab_set()

        def on_key(e):
            c = combo_from_event(e)
            if not c:
                return "break"
            win.destroy()
            if c == "Échap" and a != "deselect":
                return "break"
            other = next((b for b, cs in self.keys.items() if c in cs and b != a), None)
            if other and not self.app.ask_yes_no(
                    "Raccourci déjà utilisé", "« %s » sert déjà à : %s.\n\nLe donner à « %s » à la place ?"
                    % (c, LABELS[other], LABELS[a])):
                return "break"
            if other:
                self.keys[other].remove(c)
            if replace:
                self.keys[a] = [c]
            elif c not in self.keys[a]:
                self.keys[a].append(c)
            self.fill()
            return "break"
        win.bind("<KeyPress>", on_key)

    def clear(self):
        a = self.current()
        if a:
            self.keys[a] = []
            self.fill()

    def reset_one(self):
        a = self.current()
        if a:
            for c in DEFAULTS[a]:  # on reprend aussi la touche à une autre action qui l'aurait prise
                for b in self.keys:
                    if b != a and c in self.keys[b]:
                        self.keys[b].remove(c)
            self.keys[a] = list(DEFAULTS[a])
            self.fill()

    def reset_all(self):
        self.keys = {a: list(v) for a, v in DEFAULTS.items()}
        self.fill()

    def apply_hoop(self):
        try:
            w, h = float(self.v_hw.get()), float(self.v_hh.get())
        except (tk.TclError, ValueError):
            return
        if 20 <= w <= 1000 and 20 <= h <= 1000:
            self.app.set_hoop(w, h)

    def ok(self):
        self.app.set_bindings(self.keys)
        try:
            save_bindings(self.keys)
        except OSError as e:
            self.app.message("Paramètres", "Raccourcis appliqués mais non enregistrés :\n%s" % e, kind="warning")
        self.destroy()
