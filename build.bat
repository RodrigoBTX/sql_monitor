@echo off
REM Compila o SQL Monitor num único ficheiro SQLMonitor.exe (pasta dist\).
REM Corre isto de dentro da venv onde já tens tudo instalado
REM (requirements.txt + requirements-build.txt). Ver README.md, secção
REM "Compilar para .exe", para o passo a passo completo.

if not exist serve.py (
  echo.
  echo ERRO: nao encontrei o ficheiro serve.py nesta pasta.
  echo Corre este script de dentro da pasta sql_monitor ^(onde estao o
  echo run.py, o requirements.txt, etc^), nao de outro sitio.
  exit /b 1
)

pyinstaller --noconfirm --onefile --name SQLMonitor ^
  --icon "assets\sqlmonitor.ico" ^
  --add-data "app\templates;app\templates" ^
  --hidden-import apscheduler.triggers.interval ^
  --hidden-import apscheduler.triggers.date ^
  --hidden-import apscheduler.executors.pool ^
  --hidden-import apscheduler.jobstores.memory ^
  serve.py

if errorlevel 1 (
  echo.
  echo ERRO: a compilacao falhou - ve as mensagens acima para perceber
  echo porque. O dist\SQLMonitor.exe NAO foi criado.
  exit /b 1
)

if not exist dist\SQLMonitor.exe (
  echo.
  echo ERRO: o pyinstaller terminou mas nao encontro dist\SQLMonitor.exe
  exit /b 1
)

echo.
echo Pronto. O executavel fica em dist\SQLMonitor.exe
echo Copia esse ficheiro para o servidor do cliente e corre-o a partir dai
echo (a pasta instance\ e criada automaticamente ao lado do .exe).