# Bibliothèques tierces

Brodilume utilise les bibliothèques libres suivantes. Elles sont incluses dans `Brodilume.exe`
(ou installées avec `pip` pour lancer le code source). Leurs licences complètes sont dans le dossier
[`licenses/`](licenses/). Merci à leurs auteurs.

| Bibliothèque | Version | Rôle | Licence | Fichier de licence |
|---|---|---|---|---|
| Python | 3.10 | langage et bibliothèque standard | PSF License | `licenses/Python-LICENSE.txt` |
| Tcl/Tk (tkinter) | inclus à Python | interface graphique | Tcl/Tk License | inclus avec Python |
| Pillow | 12.x | lecture et écriture d'images | MIT-CMU (HPND) | `licenses/pillow-LICENSE` |
| NumPy | 2.x | calcul numérique | BSD-3-Clause | `licenses/numpy-LICENSE.txt` |
| SciPy | 1.x | traitement d'image (filtres) | BSD-3-Clause | `licenses/scipy-LICENSE.txt` |
| scikit-image | 0.25.x | squelettisation, traitement d'image | BSD-3-Clause | `licenses/scikit-image-LICENSE.txt` |
| pyembroidery | 1.5.x | exports PES, JEF, DST, EXP, XXX, U01, VP3 | MIT | `licenses/pyembroidery-LICENSE` |
| ImageIO | 2.x | dépendance de scikit-image | BSD-2-Clause | `licenses/ImageIO-LICENSE` |
| NetworkX | 3.x | dépendance de scikit-image | BSD-3-Clause | `licenses/networkx-LICENSE.txt` |
| tifffile | 2025.x | dépendance de scikit-image | BSD-3-Clause | `licenses/tifffile-LICENSE` |
| lazy_loader | 0.4 | dépendance de scikit-image | BSD-3-Clause | `licenses/lazy_loader-LICENSE.md` |
| packaging | 25.0 | dépendance de scikit-image | Apache-2.0 / BSD-2-Clause | `licenses/packaging-LICENSE` |

Outil de fabrication de l'exécutable (non inclus dans `Brodilume.exe`) :

| Outil | Licence |
|---|---|
| PyInstaller 6.x | GPL-2.0-or-later avec exception « bootloader » : l'exécutable produit peut être distribué sous la licence de votre choix. |

## Marques et formats

- **Husqvarna Viking**, **Pfaff**, **mySewnet**, **Brother**, **Janome**, **Bernina**, **Singer**, **Baby Lock**, **Elna**,
  **Barudan**, **Tajima**, **Ricoma** sont des marques appartenant à leurs propriétaires respectifs.
  Brodilume n'est ni affilié ni approuvé par ces entreprises. Les noms de machines ne servent qu'à indiquer la compatibilité.
- Les formats .vp3, .vp4, .pes, .jef, .exp, .xxx, .dst et .u01 sont cités pour l'interopérabilité. Brodilume n'embarque
  aucune donnée propriétaire : les nuanciers de fils sont lus dans la base de *votre* installation de mySewnet,
  si vous en avez une, et ne sont pas redistribués.
- La matrice de fils par défaut (« Robison-Anton Rayon 40 ») est une marque de Robison-Anton ; elle est citée à titre de référence.
