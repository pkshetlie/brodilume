"""Fenêtre « Cercle à broder » : marque, machine, cercle, orientation, ou taille personnalisée.

Un aperçu montre le cercle et le motif actuel à l'échelle : vert s'il tient, rouge s'il dépasse.
Choix retenu dans les réglages : {"w", "h", "machine", "hoop", "rotated"}.
"""
import tkinter as tk
from tkinter import ttk

import theme
from i18n import _
from vp4 import hoops as H

def describe(info, hoop_mm):
    """Texte court du cercle courant : « creative™ 1.5 · 150 × 150 mm »."""
    m = H.machine(info.get("machine") or "") if info else None
    size = "%g × %g mm" % tuple(hoop_mm)
    if info and info.get("hoop") and m and H.hoop(info["hoop"]):
        return "%s · %s" % (m["name"], size)
    return size


class HoopDialog(tk.Toplevel):
    def __init__(self, app, on_ok):
        super().__init__(app, bg=theme.C["panel"])
        self.app, self.on_ok = app, on_ok
        self.title(_("Cercle à broder"))
        self.transient(app)
        self.resizable(False, False)
        theme.title_bar(self, theme.C["name"] == "dark")
        info = dict(app.hoop_info or {})
        w0, h0 = app.hoop_mm
        frm = ttk.Frame(self, padding=14)
        frm.pack(fill="both", expand=True)
        left = ttk.Frame(frm)
        left.pack(side="left", fill="y", anchor="n")
        right = ttk.Frame(frm)
        right.pack(side="left", fill="both", padx=(16, 0), anchor="n")

        box = ttk.LabelFrame(left, text=_("Type de cercle"), padding=10)
        box.pack(fill="x")
        self.brand_ids = [b for b, _n in H.brands()]
        self.v_brand = tk.StringVar()
        self.v_machine = tk.StringVar()
        self.v_hoop = tk.StringVar()
        ttk.Label(box, text=_("Marque")).grid(row=0, column=0, sticky="w", pady=3)
        self.cb_brand = ttk.Combobox(box, textvariable=self.v_brand, values=[n for _b, n in H.brands()],
                                     state="readonly", width=44)
        self.cb_brand.grid(row=0, column=1, sticky="we", pady=3, padx=(8, 0))
        ttk.Label(box, text=_("Machine")).grid(row=1, column=0, sticky="w", pady=3)
        self.cb_machine = ttk.Combobox(box, textvariable=self.v_machine, state="readonly", width=44)
        self.cb_machine.grid(row=1, column=1, sticky="we", pady=3, padx=(8, 0))
        ttk.Label(box, text=_("Cercle")).grid(row=2, column=0, sticky="w", pady=3)
        self.cb_hoop = ttk.Combobox(box, textvariable=self.v_hoop, state="readonly", width=44)
        self.cb_hoop.grid(row=2, column=1, sticky="we", pady=3, padx=(8, 0))
        self.cb_brand.bind("<<ComboboxSelected>>", lambda e: self._brand_changed())
        self.cb_machine.bind("<<ComboboxSelected>>", lambda e: self._machine_changed())
        self.cb_hoop.bind("<<ComboboxSelected>>", lambda e: self._update())

        ob = ttk.LabelFrame(left, text=_("Orientation"), padding=10)
        ob.pack(fill="x", pady=(10, 0))
        self.v_rot = tk.BooleanVar(value=info.get("rotated", True))
        ttk.Radiobutton(ob, text=_("Pivotée (paysage)"), value=True, variable=self.v_rot,
                        command=self._update).pack(anchor="w")
        ttk.Radiobutton(ob, text=_("Naturelle (portrait)"), value=False, variable=self.v_rot,
                        command=self._update).pack(anchor="w")

        cb = ttk.LabelFrame(left, text=_("Définition de la taille"), padding=10)
        cb.pack(fill="x", pady=(10, 0))
        if not info.get("hoop") and "w" not in info:   # rien d'enregistré : cercle Universal 260 x 200
            info.update(machine="universal", hoop="UniLarge3", rotated=True)
        self.v_custom = tk.BooleanVar(value=not info.get("hoop"))
        ttk.Checkbutton(cb, text=_("Entrer la taille du cercle"), variable=self.v_custom,
                        command=self._update).grid(row=0, column=0, columnspan=4, sticky="w")
        self.v_w, self.v_h = tk.DoubleVar(value=w0), tk.DoubleVar(value=h0)
        ttk.Label(cb, text=_("Largeur")).grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.sp_w = ttk.Spinbox(cb, from_=20, to=1000, increment=5, textvariable=self.v_w, width=7,
                                command=self._update)
        self.sp_w.grid(row=1, column=1, sticky="w", padx=(6, 12), pady=(6, 0))
        ttk.Label(cb, text=_("Hauteur")).grid(row=1, column=2, sticky="w", pady=(6, 0))
        self.sp_h = ttk.Spinbox(cb, from_=20, to=1000, increment=5, textvariable=self.v_h, width=7,
                                command=self._update)
        self.sp_h.grid(row=1, column=3, sticky="w", padx=(6, 0), pady=(6, 0))
        ttk.Label(cb, text="mm").grid(row=1, column=4, sticky="w", padx=(4, 0), pady=(6, 0))
        for sp in (self.sp_w, self.sp_h):
            sp.bind("<KeyRelease>", lambda e: self._update())

        pv = ttk.LabelFrame(right, text=_("Aperçu"), padding=8)
        pv.pack(fill="both")
        self.cv = tk.Canvas(pv, width=280, height=240, bg=theme.C["view"], highlightthickness=0)
        self.cv.pack()
        self.lbl_fit = ttk.Label(right, text="", wraplength=290, justify="left")
        self.lbl_fit.pack(anchor="w", pady=(8, 0))
        ttk.Label(right, text=_("Le fichier .vp4 indique un cercle Universal de mySewnet assez grand pour ce "
                                "cercle ; les autres formats n'enregistrent que les points."),
                  style="Muted.TLabel", wraplength=290, justify="left").pack(anchor="w", pady=(8, 0))

        btns = ttk.Frame(self, padding=(14, 0, 14, 14))
        btns.pack(fill="x")
        ttk.Button(btns, text=_("Annuler"), command=self.destroy).pack(side="right")
        ttk.Button(btns, text="OK", style="Accent.TButton", command=self.ok).pack(side="right", padx=6)
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self.ok())

        # état initial : la machine enregistrée, sinon la première Pfaff
        m = H.machine(info.get("machine") or "")
        brand = m["brand"] if m else (self.brand_ids[0] if self.brand_ids else None)
        if brand in self.brand_ids:
            self.v_brand.set(H.brands()[self.brand_ids.index(brand)][1])
        self._brand_changed(machine=m["id"] if m else None, hoop=info.get("hoop"))
        self.update_idletasks()
        self.geometry("+%d+%d" % (app.winfo_rootx() + 120, app.winfo_rooty() + 80))
        self.grab_set()

    # ------------------------------------------------------------------ listes en cascade
    def _brand_changed(self, machine=None, hoop=None):
        names = [n for _b, n in H.brands()]
        b = self.brand_ids[names.index(self.v_brand.get())] if self.v_brand.get() in names else None
        self.machines = H.machines(b)
        self.cb_machine.configure(values=[m["name"] for m in self.machines])
        ids = [m["id"] for m in self.machines]
        k = ids.index(machine) if machine in ids else 0
        if self.machines:
            self.v_machine.set(self.machines[k]["name"])
        self._machine_changed(hoop=hoop)

    def _machine_changed(self, hoop=None):
        m = self._machine()
        self.hoop_ids = list(m["hoops"]) if m else []
        self.cb_hoop.configure(values=[H.hoop(h)["name"] for h in self.hoop_ids])
        if self.hoop_ids:
            # même cercle si la machine le propose, sinon le plus grand
            k = self.hoop_ids.index(hoop) if hoop in self.hoop_ids else max(
                range(len(self.hoop_ids)), key=lambda i: H.hoop(self.hoop_ids[i])["w"] * H.hoop(self.hoop_ids[i])["h"])
            self.v_hoop.set(H.hoop(self.hoop_ids[k])["name"])
        self._update()

    def _machine(self):
        names = [m["name"] for m in self.machines]
        return self.machines[names.index(self.v_machine.get())] if self.v_machine.get() in names else None

    def _hoop_id(self):
        names = [H.hoop(h)["name"] for h in self.hoop_ids]
        return self.hoop_ids[names.index(self.v_hoop.get())] if self.v_hoop.get() in names else None

    # ------------------------------------------------------------------ taille choisie, aperçu
    def chosen(self):
        """((largeur, hauteur) en mm, infos à enregistrer) ou None si la taille n'est pas valide."""
        if self.v_custom.get():
            try:
                w, h = float(self.v_w.get()), float(self.v_h.get())
            except (tk.TclError, ValueError):
                return None
            if not (20 <= w <= 1000 and 20 <= h <= 1000):
                return None
            return (w, h), {"w": w, "h": h, "machine": None, "hoop": None, "rotated": True}
        hid = self._hoop_id()
        if not hid:
            return None
        w, h = H.size(hid, self.v_rot.get())
        m = self._machine()
        return (w, h), {"w": w, "h": h, "machine": m["id"] if m else None, "hoop": hid,
                        "rotated": bool(self.v_rot.get())}

    def _update(self):
        custom = self.v_custom.get()
        for w in (self.cb_brand, self.cb_machine, self.cb_hoop):
            w.state(["disabled" if custom else "readonly"])
        for w in (self.sp_w, self.sp_h):
            w.state(["!disabled" if custom else "disabled"])
        res = self.chosen()
        if res and not custom:
            self.v_w.set(res[0][0])
            self.v_h.set(res[0][1])
        self._draw(res[0] if res else None)

    def _draw(self, size):
        cv, C = self.cv, theme.C
        cv.delete("all")
        W, Hh = int(cv["width"]), int(cv["height"])
        if not size:
            self.lbl_fit.config(text=_("Taille non valide (20 à 1000 mm)."))
            return
        bb = self.app.design.bbox() if self.app.design and self.app.design.blocks else None
        dw, dh = ((bb[2] - bb[0]) / 10, (bb[3] - bb[1]) / 10) if bb else (0, 0)
        w, h = size
        sc = min((W - 30) / max(w, dw, 1), (Hh - 30) / max(h, dh, 1))
        cx, cy = W / 2, Hh / 2
        cv.create_rectangle(cx - w * sc / 2, cy - h * sc / 2, cx + w * sc / 2, cy + h * sc / 2,
                            fill=C["hoop"], outline=C["hoop_line"], width=2)
        cv.create_line(cx - 6, cy, cx + 6, cy, fill=C["grid_axis"])
        cv.create_line(cx, cy - 6, cx, cy + 6, fill=C["grid_axis"])
        if bb:
            fits = dw <= w + 0.05 and dh <= h + 0.05
            col = "#2e9d5b" if fits else "#d33c3c"
            cv.create_rectangle(cx - dw * sc / 2, cy - dh * sc / 2, cx + dw * sc / 2, cy + dh * sc / 2,
                                outline=col, width=2, dash=(4, 3))
            if fits:
                txt = _("Le motif (%.0f × %.0f mm) tient dans ce cercle.") % (dw, dh)
            else:
                txt = _("Le motif (%.0f × %.0f mm) dépasse ce cercle : il pourra être réduit pour tenir.") % (dw, dh)
            self.lbl_fit.config(text=txt, foreground=col)
        else:
            self.lbl_fit.config(text=_("Zone de broderie : %g × %g mm") % (w, h), foreground=C["fg"])

    def ok(self):
        res = self.chosen()
        if not res:
            return
        self.destroy()
        self.on_ok(*res)
