"""Configuração dos logs da aplicação.

Isto existe porque a app corre muitas vezes sem supervisão (como serviço
do Windows, sem consola visível) — sem um registo em disco, uma falha no
scheduler em segundo plano (ex: envio de email a falhar, uma captura de
snapshot a rebentar) passaria completamente despercebida.

Os ficheiros ficam em instance/logs/sqlmonitor.log, com rotação diária (à
meia-noite) e no máximo LOG_RETENTION_DAYS dias guardados — o mais antigo
é apagado automaticamente a cada rotação, tal como já acontece com o
histórico de snapshots, para nunca acumulares registos indefinidamente."""

import logging
import logging.handlers
import os

LOG_RETENTION_DAYS = 30

_configured = False


def setup_logging(app):
    """Liga um ficheiro de log (com rotação/limpeza automática) tanto ao
    logger próprio da app ("sql_monitor", usado no snapshot/notificações)
    como ao logger do Flask (app.logger) — este último apanha também
    qualquer erro não tratado numa rota (erro 500), que de outra forma só
    apareceria na consola, inexistente quando isto corre como serviço."""
    global _configured
    if _configured:
        return
    _configured = True

    log_dir = os.path.join(app.instance_path, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "sqlmonitor.log")

    handler = logging.handlers.TimedRotatingFileHandler(
        log_path,
        when="midnight",
        backupCount=LOG_RETENTION_DAYS,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "%Y-%m-%d %H:%M:%S",
        )
    )

    logger = logging.getLogger("sql_monitor")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    app.logger.handlers = []
    app.logger.setLevel(logging.INFO)
    app.logger.addHandler(handler)

    return logger


def get_logger():
    return logging.getLogger("sql_monitor")
