"""Número de build da app, lido do ficheiro VERSION na raiz do projeto.

Esse ficheiro é incrementado automaticamente a cada commit pelo hook em
.githooks/pre-commit (ver README.md, secção "Número de versão"). Serve só
para saberes rapidamente, ao veres a app (rodapé/Definições), que build
está instalado num PC/servidor de cliente — útil quando dás suporte remoto
e há várias instalações espalhadas.
"""

import os
import sys


def _resolve_project_root():
    """Onde procurar o ficheiro VERSION. Tal como os templates, quando a
    app corre compilada (PyInstaller/sys.frozen), o VERSION vai empacotado
    dentro do bundle (sys._MEIPASS) — ver build.bat, --add-data "VERSION;.".
    Em modo normal (python run.py), fica na raiz do projeto, ao lado do
    run.py."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_app_version():
    path = os.path.join(_resolve_project_root(), "VERSION")
    try:
        with open(path) as f:
            value = f.read().strip()
        return value or "dev"
    except OSError:
        return "dev"
