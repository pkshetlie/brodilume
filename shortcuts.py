"""Raccourcis clavier de Brodilume : liste des actions, lecture des touches, réglages enregistrés.

Les raccourcis sont écrits sous une forme lisible (« Ctrl+Maj+Z », « Suppr », « F5 ») et gardés
dans %APPDATA%/Brodilume/settings.json. Une seule fonction lit toutes les touches de la fenêtre
(`combo_from_event`) : changer un raccourci ne demande donc aucun nouveau « bind » Tk.
"""
import json
import os
import tkinter as tk
from tkinter import ttk, messagebox

import i18n
from i18n import _

# (identifiant, libellé, raccourcis par défaut) — groupés par rubrique pour la fenêtre des réglages
ACTIONS = [
    (_("Édition"), [
        ("undo", _("Annuler"), ["Ctrl+Z"]),
        ("redo", _("Rétablir"), ["Ctrl+Y", "Ctrl+Maj+Z"]),
        ("copy", _("Copier (élément ou parties sélectionnées)"), ["Ctrl+C"]),
        ("cut", _("Couper"), ["Ctrl+X"]),
        ("paste", _("Coller (élément copié, image ou fichiers du presse-papiers)"), ["Ctrl+V", "Maj+Inser"]),
        ("duplicate", _("Dupliquer l'élément"), ["Ctrl+D"]),
        ("delete", _("Supprimer la sélection"), ["Suppr", "Retour"]),
        ("select_all", _("Sélectionner toutes les parties de l'élément"), ["Ctrl+A"]),
        ("merge_parts", _("Fusionner les couleurs sélectionnées"), ["Ctrl+G"]),
        ("deselect", _("Désélectionner"), ["Échap"]),
    ]),
    (_("Fichier"), [
        ("new", _("Nouveau projet"), ["Ctrl+N"]),
        ("open", _("Ouvrir un projet (.brodi)"), ["Ctrl+O"]),
        ("add", _("Importer une image / broderie"), ["Ctrl+I"]),
        ("add_text", _("Ajouter un texte"), ["Ctrl+T"]),
        ("save", _("Enregistrer le projet"), ["Ctrl+S"]),
        ("save_as", _("Enregistrer le projet sous…"), ["Ctrl+Maj+S"]),
        ("export_vp4", _("Exporter en .vp4"), ["Ctrl+E"]),
        ("export", _("Exporter l'aperçu PNG"), ["Ctrl+Maj+E"]),
        ("usb", _("Envoyer sur la clé USB"), ["Ctrl+U"]),
        ("choose_hoop", _("Choisir le cercle à broder"), ["Ctrl+H"]),
        ("fit_hoop", _("Ajuster le motif au cercle"), []),
        ("regen", _("Régénérer l'image"), ["F5"]),
        ("settings", _("Paramètres et raccourcis"), ["Ctrl+,", "F1"]),
        ("close", _("Fermer le projet"), ["Ctrl+W"]),
        ("quit", _("Quitter"), ["Ctrl+Q"]),
    ]),
    (_("Outils"), [
        ("tool_move", _("Outil Sélection (choisir, déplacer, taille, rotation)"), ["V"]),
        ("tool_pick", _("Outil Couleurs"), ["C"]),
        ("tool_erase", _("Outil Gomme"), ["E"]),
        ("tool_hand", _("Outil Main (faire glisser la vue)"), ["H"]),
        ("tool_zoom", _("Outil Zoom"), ["Z"]),
    ]),
    (_("Élément"), [
        ("rot_cw", _("Tourner de 90° (sens horaire)"), ["R"]),
        ("rot_ccw", _("Tourner de 90° (sens inverse)"), ["Maj+R"]),
        ("center", _("Centrer dans le cercle"), ["Début"]),
        ("order_up", _("Broder plus tôt (monter dans la liste)"), ["PgPréc"]),
        ("order_down", _("Broder plus tard (descendre dans la liste)"), ["PgSuiv"]),
        ("colors_less", _("Une couleur de moins"), ["Ctrl+-"]),
        ("colors_more", _("Une couleur de plus"), ["Ctrl++"]),
        ("move_left", _("Déplacer l'élément à gauche (1 mm, Maj : 10 mm ; sans sélection : la vue)"), ["Gauche"]),
        ("move_right", _("Déplacer à droite"), ["Droite"]),
        ("move_up", _("Déplacer vers le haut"), ["Haut"]),
        ("move_down", _("Déplacer vers le bas"), ["Bas"]),
    ]),
    (_("Vue"), [
        ("fit", _("Ajuster la vue au motif"), ["0"]),
        ("hoop", _("Voir le cercle entier"), ["Ctrl+1"]),
        ("zoom_100", _("Taille réelle (100 %)"), ["Ctrl+0"]),
        ("pan_left", _("Faire défiler la vue à gauche (Maj : plus vite)"), ["Ctrl+Gauche"]),
        ("pan_right", _("Faire défiler la vue à droite"), ["Ctrl+Droite"]),
        ("pan_up", _("Faire défiler la vue vers le haut"), ["Ctrl+Haut"]),
        ("pan_down", _("Faire défiler la vue vers le bas"), ["Ctrl+Bas"]),
        ("zoom_in", _("Zoom avant"), ["+"]),
        ("zoom_out", _("Zoom arrière"), ["-"]),
        ("play", _("Simuler / pause (Espace maintenu + glisser : main)"), ["Espace"]),
        ("jumps", _("Afficher les sauts"), ["J"]),
        ("theme", _("Basculer thème clair / sombre"), ["Ctrl+Maj+T"]),
    ]),
]

MOUSE_HELP = [
    (_("Ctrl + molette (ou Alt + molette)"), _("Zoom sous la souris")),
    (_("Molette"), _("Faire défiler la vue de haut en bas")),
    (_("Maj + molette"), _("Faire défiler la vue de gauche à droite")),
    (_("Bouton du milieu (ou droit) + glisser"), _("Déplacer la vue")),
    (_("… avec Maj"), _("Déplacer la vue sur un seul axe")),
    (_("Espace maintenu + glisser"), _("Déplacer la vue (main temporaire)")),
    (_("Double-clic (outil Couleurs)"), _("Toutes les parties du fil")),
]
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
        self.title(_("Paramètres — Brodilume"))
        self.geometry("760x780")
        self.transient(app)
        self.keys = {a: list(v) for a, v in app.keys.items()}
        import theme
        self.configure(bg=theme.C["panel"])
        theme.title_bar(self, theme.C["name"] == "dark")
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=(10, 0))
        gen = ttk.Frame(nb, padding=12)
        nb.add(gen, text=_("Général"))
        ttk.Label(gen, text=_("Thème"), style="Title.TLabel").pack(anchor="w")
        self.v_theme = tk.StringVar(value=app.theme_mode)
        for m in theme.MODES:
            ttk.Radiobutton(gen, text=theme.MODE_LABELS[m], value=m, variable=self.v_theme,
                            command=lambda: app.set_theme(self.v_theme.get())).pack(anchor="w", pady=1)
        ttk.Label(gen, text=_("« Comme Windows » suit Paramètres > Personnalisation > Couleurs, même pendant que "
                            "Brodilume est ouvert."), style="Muted.TLabel", wraplength=640).pack(anchor="w", pady=(4, 0))
        ttk.Label(gen, text=_("Langue"), style="Title.TLabel").pack(anchor="w", pady=(18, 4))
        lrow = ttk.Frame(gen)
        lrow.pack(anchor="w")
        self.v_lang = tk.StringVar(value=i18n.LANGS[i18n.lang])
        lcb = ttk.Combobox(lrow, textvariable=self.v_lang, values=list(i18n.LANGS.values()), state="readonly",
                           width=14)
        lcb.pack(side="left")
        lcb.bind("<<ComboboxSelected>>", lambda e: self.set_language())
        self.btn_restart = ttk.Button(lrow, text="", command=app.restart)
        self.lbl_lang = ttk.Label(gen, text="", style="Muted.TLabel", wraplength=640)
        self.lbl_lang.pack(anchor="w", pady=(4, 0))
        ttk.Label(gen, text=_("Cercle à broder"), style="Title.TLabel").pack(anchor="w", pady=(18, 4))
        hrow = ttk.Frame(gen)
        hrow.pack(anchor="w")
        import hoopdialog
        self.lbl_hoop = ttk.Label(hrow, text=hoopdialog.describe(app.hoop_info, app.hoop_mm))
        self.lbl_hoop.pack(side="left")
        ttk.Button(hrow, text=_("Choisir le cercle…"),
                   command=lambda: app.choose_hoop(after=lambda: self.lbl_hoop.config(
                       text=hoopdialog.describe(app.hoop_info, app.hoop_mm)))).pack(side="left", padx=(12, 0))
        ttk.Label(gen, text=_("Marque, machine et cercle (plus de 100 machines), ou taille personnalisée. Aussi "
                            "accessible par le bouton du cercle, en haut de la fenêtre."),
                  style="Muted.TLabel", wraplength=640).pack(anchor="w", pady=(4, 0))
        ttk.Label(gen, text=_("Mises à jour"), style="Title.TLabel").pack(anchor="w", pady=(18, 4))
        import updater
        self.v_updates = tk.BooleanVar(value=load_setting("check_updates", True))
        ttk.Checkbutton(gen, text=_("Vérifier les mises à jour au démarrage"), variable=self.v_updates,
                        command=lambda: save_setting("check_updates", bool(self.v_updates.get()))).pack(anchor="w")
        urow = ttk.Frame(gen)
        urow.pack(anchor="w", pady=(4, 0))
        ttk.Label(urow, text=_("Version %s") % updater.VERSION).pack(side="left")
        ttk.Button(urow, text=_("Vérifier maintenant"), command=lambda: app._start_update_check(manual=True)).pack(
            side="left", padx=(12, 0))
        tab = ttk.Frame(nb, padding=8)
        nb.add(tab, text=_("Raccourcis clavier"))
        ttk.Label(tab, text=_("Double-clic sur une action pour lui donner un nouveau raccourci. "
                            "Une action peut en avoir plusieurs."), style="Muted.TLabel").pack(anchor="w")
        cols = ttk.Frame(tab)
        cols.pack(fill="both", expand=True, pady=6)
        self.tree = ttk.Treeview(cols, columns=("keys",), selectmode="browse")
        self.tree.heading("#0", text=_("Action"))
        self.tree.heading("keys", text=_("Raccourci(s)"))
        self.tree.column("#0", width=420)
        self.tree.column("keys", width=220)
        sb = ttk.Scrollbar(cols, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self.capture(replace=True))
        btns = ttk.Frame(tab)
        btns.pack(fill="x")
        for txt, cmd in ((_("Modifier…"), lambda: self.capture(replace=True)),
                         (_("Ajouter un raccourci…"), lambda: self.capture(replace=False)),
                         (_("Retirer les raccourcis"), self.clear), (_("Par défaut (cette action)"), self.reset_one),
                         (_("Tout par défaut"), self.reset_all)):
            ttk.Button(btns, text=txt, command=cmd).pack(side="left", padx=(0, 4))
        ttk.Label(tab, text=_("Dans un champ de saisie, Ctrl+C / X / V / A / Z / Y gardent leur rôle habituel "
                            "(texte)."), style="Muted.TLabel").pack(anchor="w", pady=(8, 0))
        mouse = ttk.LabelFrame(tab, text=_("Souris"), padding=6)
        mouse.pack(fill="x", pady=(8, 0))
        for i, (k_, v_) in enumerate(MOUSE_HELP):
            ttk.Label(mouse, text=k_).grid(row=i, column=0, sticky="w", padx=(0, 16))
            ttk.Label(mouse, text=v_, style="Muted.TLabel").grid(row=i, column=1, sticky="w")
        bottom = ttk.Frame(self, padding=10)
        bottom.pack(fill="x")
        ttk.Label(bottom, text=_("Enregistré dans ") + config_path(), style="Muted.TLabel").pack(side="left")
        ttk.Button(bottom, text=_("Annuler"), command=self.destroy).pack(side="right")
        ttk.Button(bottom, text="OK", command=self.ok).pack(side="right", padx=6)
        self.fill()
        self.grab_set()

    def fill(self):
        sel = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for group, acts in ACTIONS:
            g = self.tree.insert("", "end", text=group, open=True)
            for a, label, _k in acts:
                self.tree.insert(g, "end", iid=a, text=label,
                                 values=(_("   ou   ").join(i18n.key(k) for k in self.keys[a]) or "—",))
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
        win.title(_("Nouveau raccourci"))
        theme.title_bar(win, theme.C["name"] == "dark")
        win.transient(self)
        win.geometry("+%d+%d" % (self.winfo_rootx() + 150, self.winfo_rooty() + 200))
        ttk.Label(win, text=_("« %s »\n\nAppuyez sur la combinaison de touches voulue.\n"
                            "(Échap seul : annuler)") % LABELS[a], padding=20, justify="center").pack()
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
                    _("Raccourci déjà utilisé"), _("« %s » sert déjà à : %s.\n\nLe donner à « %s » à la place ?")
                    % (i18n.key(c), LABELS[other], LABELS[a])):
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

    def set_language(self):
        """La langue choisie est enregistrée ; elle s'applique au prochain lancement de Brodilume."""
        code = next(k for k, v in i18n.LANGS.items() if v == self.v_lang.get())
        try:
            save_setting("language", code)
        except OSError:
            return
        if code == i18n.lang:
            self.lbl_lang.config(text="")
            self.btn_restart.pack_forget()
            return
        # message écrit dans la langue choisie : c'est elle que l'utilisateur sait lire
        self.lbl_lang.config(text=i18n.translate(code, "La nouvelle langue s'appliquera au prochain lancement "
                                                       "de Brodilume."))
        self.btn_restart.config(text=i18n.translate(code, "Relancer maintenant"))
        self.btn_restart.pack(side="left", padx=(10, 0))

    def ok(self):
        self.app.set_bindings(self.keys)
        try:
            save_bindings(self.keys)
        except OSError as e:
            self.app.message(_("Paramètres"), _("Raccourcis appliqués mais non enregistrés :\n%s") % e, kind="warning")
        self.destroy()
