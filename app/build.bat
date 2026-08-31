@echo off
REM Compila o SQL Monitor num único ficheiro SQLMonitor.exe (pasta dist\).
REM Corre isto de dentro da venv onde já tens tudo instalado
REM (requirements.txt + requirements-build.txt). Ver README.md, secção
REM "Compilar para .exe", para o passo a passo completo.

pyinstaller --noconfirm --onefile --name SQLMonitor ^
  --icon "assets\sqlmonitor.ico" ^
  --add-data "app\templates;app\templates" ^
  --hidden-import apscheduler.triggers.interval ^
  --hidden-import apscheduler.triggers.date ^
  --hidden-import apscheduler.executors.pool ^
  --hidden-import apscheduler.jobstores.memory ^
  serve.py

echo.
echo Pronto. O executavel fica em dist\SQLMonitor.exe
echo Copia esse ficheiro para o servidor do cliente e corre-o a partir dai
echo (a pasta instance\ e criada automaticamente ao lado do .exe).