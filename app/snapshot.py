"""Captura periódica de métricas (histórico/tendências).

Corre em segundo plano dentro do próprio processo Flask (via APScheduler),
e vai gravando o estado geral da instância numa tabela local (MetricSnapshot),
para depois a página de Tendências poder desenhar gráficos de evolução.

De propósito, só grava snapshots do perfil marcado como "principal para
histórico" (Profile.is_snapshot_primary) — mesmo que tenhas vários perfis
configurados, isto mantém o processo em segundo plano leve: nunca bate em
mais do que um SQL Server de cada vez, e o histórico/espaço em disco não
cresce proporcionalmente ao número de perfis que tiveres."""

import datetime

from apscheduler.schedulers.background import BackgroundScheduler

_scheduler = None


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
    _scheduler.start()
