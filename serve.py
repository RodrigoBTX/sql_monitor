"""Entry-point de PRODUÇÃO do SQL Monitor.

Ao contrário do run.py (servidor de desenvolvimento do Flask — não
pensado para correr sem supervisão nem por longos períodos), este ficheiro
usa o waitress, um servidor WSGI simples e robusto, mais adequado para
deixar a app a correr num servidor ou como serviço do Windows.

É este o ficheiro que deve ser compilado com o PyInstaller (ver README.md,
secção "Compilar para .exe") e/ou registado como serviço do Windows (ver
README.md, secção "Correr como serviço do Windows").

Variáveis de ambiente opcionais:
  SQL_MONITOR_HOST  - por omissão 127.0.0.1 (só a própria máquina).
                       Usa 0.0.0.0 se precisares de aceder a partir de
                       outro PC na mesma rede.
  SQL_MONITOR_PORT  - por omissão 5000.
"""
import os

from waitress import serve

from app import create_app

app = create_app()

if __name__ == "__main__":
    host = os.environ.get("SQL_MONITOR_HOST", "127.0.0.1")
    port = int(os.environ.get("SQL_MONITOR_PORT", "5000"))
    print(f"SQL Monitor a correr em http://{host}:{port}  (Ctrl+C para parar)")
    serve(app, host=host, port=port, threads=4)
