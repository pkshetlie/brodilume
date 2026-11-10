@echo off
rem Fabrique dist\Brodilume.exe : un seul fichier, sans Python à installer.
rem Un environnement propre (.build-venv) évite d'embarquer les autres paquets installés sur le PC.
setlocal
cd /d "%~dp0"
if not exist .build-venv\Scripts\python.exe python -m venv .build-venv || goto :erreur
.build-venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller || goto :erreur
.build-venv\Scripts\python.exe -m PyInstaller --noconfirm --onefile --windowed --name Brodilume ^
  --icon "%~dp0assets\brodilume.ico" --add-data "%~dp0assets;assets" ^
  --distpath "%~dp0dist" --workpath "%~dp0build" --specpath "%~dp0build" app.py || goto :erreur
echo.
echo Terminé : dist\Brodilume.exe
exit /b 0
:erreur
echo La fabrication a échoué.
exit /b 1
