"""Captura periódica de métricas (histórico/tendências).

Corre em segundo plano dentro do próprio processo Flask (via APScheduler),
e vai gravando o estado geral da instância numa tabela local (MetricSnapshot),
para depois a página de Tendências poder desenhar gráficos de evolução.

De propósito, só grava snapshots do perfil marcado como "principal para
histórico" (Profile.is_snapshot_primary) — mesmo que tenhas vários perfis
configurados, isto mantém o processo em segundo plano leve: nunca bate em
mais do que um SQL Server de cada vez, e o histórico/espaço em disco não
cresce proporcionalmente ao número de perfis que tiveres.

setup_scheduler() também arranca, no mesmo scheduler em segundo plano, a
verificação periódica das notificações por email (ver
app/notifications.py) — essa sim corre para todos os perfis que tiverem
notificações ativadas, independentemente de qual é o principal."""

import datetime

from apscheduler.schedulers.background import BackgroundScheduler

_scheduler = None

# Snapshots com mais de 30 dias são apagados automaticamente a cada captura
# (ver capture_snapshot). 30 dias porque é também a maior janela que a
# página de Tendências mostra ("Últimos 30 dias") — não faz sentido guardar
# histórico que a app já não consegue mostrar em lado nenhum, e mantém a
# tabela pequena e leve indefinidamente, como pedido.
SNAPSHOT_RETENTION_DAYS = 30


def _get_primary_profile():
    from app.models import Profile

    return (
        Profile.query.filter_by(is_snapshot_primary=True).first()
        or Profile.query.order_by(Profile.id).first()
    )


def capture_snapshot(app):
    with app.app_context():
        from app import db
        from app.models import SqlConnection, CustomCheck, MetricSnapshot
        from app.sql_client import get_summary

        profile = _get_primary_profile()
        if not profile:
            return
        conn = SqlConnection.query.filter_by(profile_id=profile.id).first()
        if not conn:
            return
        checks = CustomCheck.query.filter_by(profile_id=profile.id, active=True).all()
        summary = get_summary(conn, custom_checks=checks)
        snap = MetricSnapshot(
            profile_id=profile.id,
            jobs_failed=summary.get("jobs_failed", 0),
            jobs_stuck=summary.get("jobs_stuck", 0),
            sessions_blocked=summary.get("sessions_blocked", 0),
            queries_long_running=summary.get("queries_long_running", 0),
            backups_stale=summary.get("backups_stale", 0),
            disk_low=summary.get("disk_low", 0),
            custom_checks_breached=summary.get("custom_checks_breached", 0),
            had_error=bool(summary.get("error")),
        )
        db.session.add(snap)

        # Limpeza dos snapshots antigos deste perfil (mais de
        # SNAPSHOT_RETENTION_DAYS dias) — corre aqui, "de carona" na mesma
        # captura periódica, para não precisar de outro job/scheduler à parte.
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(
            days=SNAPSHOT_RETENTION_DAYS
        )
        MetricSnapshot.query.filter(
            MetricSnapshot.profile_id == profile.id,
            MetricSnapshot.taken_at < cutoff,
        ).delete(synchronize_session=False)

        db.session.commit()


def setup_scheduler(app):
    """Arranca o scheduler uma única vez (a app corre com use_reloader=False
    exatamente para garantir que este código só executa num único processo,
    senão teríamos snapshots duplicados)."""
    global _scheduler
    if _scheduler is not None:
        return

    interval = 15
    with app.app_context():
        from app.models import SqlConnection

        profile = _get_primary_profile()
        if profile:
            conn = SqlConnection.query.filter_by(profile_id=profile.id).first()
            if conn and conn.snapshot_interval_minutes:
                interval = conn.snapshot_interval_minutes

    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        lambda: capture_snapshot(app),
        "interval",
        minutes=interval,
        id="metric_snapshot",
        replace_existing=True,
        # Grava logo o primeiro snapshot no arranque (poucos segundos depois),
        # em vez de obrigar a esperar um intervalo inteiro às cegas para ver
        # se está a funcionar. Os seguintes já seguem o intervalo normal.
        next_run_time=datetime.datetime.now(),
    )

    # Verificação para notificações por email — independente do perfil
    # principal para histórico (ver app/notifications.py): corre para
    # qualquer perfil que tenha notify_enabled=True, com um intervalo fixo
    # próprio, mais espaçado que os snapshots porque não precisa da mesma
    # granularidade.
    from app.notifications import check_and_notify, CHECK_INTERVAL_MINUTES

    _scheduler.add_job(
        lambda: check_and_notify(app),
        "interval",
        minutes=CHECK_INTERVAL_MINUTES,
        id="notification_check",
        replace_existing=True,
        next_run_time=datetime.datetime.now(),
    )

    _scheduler.start()
