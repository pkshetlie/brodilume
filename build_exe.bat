@echo off
rem Fabrique dist\Brodilume.exe (portable) puis dist\Brodilume-Setup.exe (installeur qui le contient).
rem Un environnement propre (.build-venv) évite d'embarquer les autres paquets installés sur le PC.
setlocal
cd /d "%~dp0"
if not exist .build-venv\Scripts\python.exe python -m venv .build-venv || goto :erreur
.build-venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller || goto :erreur
set PYI=.build-venv\Scripts\python.exe -m PyInstaller --noconfirm --onefile --windowed --distpath "%~dp0dist" --workpath "%~dp0build" --specpath "%~dp0build" --icon "%~dp0assets\brodilume.ico"
%PYI% --name Brodilume --add-data "%~dp0assets;assets" --add-data "%~dp0lang;lang" app.py || goto :erreur
%PYI% --name Brodilume-Setup --add-data "%~dp0dist\Brodilume.exe;." --add-data "%~dp0LICENSE;." --add-data "%~dp0lang;lang" ^
  --add-data "%~dp0assets\brodilume.ico;assets" --add-data "%~dp0assets\brodilume-icone-72.png;assets" ^
  --exclude-module numpy --exclude-module scipy --exclude-module skimage --exclude-module PIL installer.py || goto :erreur
echo.
echo Terminé : dist\Brodilume.exe (portable) et dist\Brodilume-Setup.exe (installeur)
exit /b 0
:erreur
echo La fabrication a échoué.
exit /b 1
