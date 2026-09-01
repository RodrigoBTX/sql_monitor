"""Backup manual da base de dados local da app (instance/app.db).

Não há nada automático aqui de propósito — só um botão em Definições que,
quando clicado, gera uma cópia da base de dados atual e entrega-a ao
browser para download (o browser é que decide se pergunta a pasta de
destino ou usa a pasta de transferências por omissão, consoante as
definições do próprio browser).

A cópia é feita com a API de backup do módulo sqlite3 da biblioteca
standard, em vez de um simples "copiar ficheiro" — isto garante uma cópia
consistente mesmo que a app esteja a escrever na base de dados nesse
preciso momento (o que um copy de ficheiro normal não garante com SQLite).
"""

import datetime
import os
import sqlite3
import tempfile

LAST_BACKUP_FILENAME = "last_backup.txt"


def _db_path(app):
    return os.path.join(app.instance_path, "app.db")


def _last_backup_path(app):
    return os.path.join(app.instance_path, LAST_BACKUP_FILENAME)


def get_last_backup_at(app):
    """Devolve o datetime (UTC) do último backup feito, ou None se nunca
    foi feito nenhum."""
    path = _last_backup_path(app)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            raw = f.read().strip()
        return datetime.datetime.fromisoformat(raw) if raw else None
    except (OSError, ValueError):
        return None


def _record_backup_now(app):
    with open(_last_backup_path(app), "w") as f:
        f.write(datetime.datetime.utcnow().isoformat())


def create_backup_copy(app):
    """Cria uma cópia consistente de instance/app.db num ficheiro temporário
    e devolve o caminho. Regista também a data/hora deste backup, para
    aparecer nas Definições. Quem chama esta função é responsável por
    apagar o ficheiro temporário depois de o entregar (ver settings.py)."""
    src_path = _db_path(app)
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".db", prefix="sql_monitor_backup_")
    os.close(tmp_fd)

    src_conn = sqlite3.connect(src_path)
    dst_conn = sqlite3.connect(tmp_path)
    try:
        with dst_conn:
            src_conn.backup(dst_conn)
    finally:
        src_conn.close()
        dst_conn.close()

    _record_backup_now(app)
    return tmp_path
