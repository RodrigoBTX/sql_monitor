"""Notificações por email quando algo passa a estar mau numa instância.

Regras, de propósito simples:
  - Cada perfil decide para si próprio se quer notificações e para que
    email (Profile.notify_enabled / Profile.notify_email) — independente
    de ser ou não o perfil "principal para histórico".
  - Todos os perfis usam o mesmo servidor de envio (SMTP), configurado
    uma única vez em Definições (AppSetting) — normalmente só faz
    sentido teres uma conta de email a enviar isto tudo.
  - Só é enviado um email quando algo PASSA a estar mau (transição de
    "tudo bem" para "há problemas"), nunca de forma repetida enquanto o
    problema persistir — para não encheres a caixa de correio. Quando o
    problema for resolvido e voltar a acontecer, volta a avisar.

A verificação corre em segundo plano, a cada 10 minutos fixos, só para os
perfis que têm notify_enabled=True — perfis sem notificações ativas nunca
são tocados por este job, para se manter leve.
"""

import datetime
import smtplib
from email.mime.text import MIMEText

# Mesmas contagens usadas no dashboard para decidir "há alguma situação a
# precisar de atenção" (ver dashboard.html: total_problems).
PROBLEM_KEYS = (
    "jobs_failed",
    "jobs_stuck",
    "sessions_blocked",
    "queries_long_running",
    "backups_stale",
    "disk_low",
    "custom_checks_breached",
)

CHECK_INTERVAL_MINUTES = 10

PROBLEM_LABELS = {
    "jobs_failed": "Jobs com erro",
    "jobs_stuck": "Jobs pendurados",
    "sessions_blocked": "Sessões bloqueadas",
    "queries_long_running": "Queries longas",
    "backups_stale": "Backups desatualizados",
    "disk_low": "Volumes com pouco espaço",
    "custom_checks_breached": "Custom checks acima do limiar",
}


def get_app_settings():
    from app import db
    from app.models import AppSetting

    settings = AppSetting.query.first()
    if settings is None:
        settings = AppSetting()
        db.session.add(settings)
        db.session.commit()
    return settings


class NotificationError(Exception):
    pass


def send_email(settings, to_address, subject, body):
    """Envia um email simples (texto) usando os dados SMTP guardados.
    Lança NotificationError com uma mensagem legível se algo falhar —
    nunca deixa a exceção "crua" do smtplib propagar-se, para o botão de
    teste (e o job em segundo plano) conseguirem mostrar/registar algo
    compreensível."""
    if not settings.is_configured:
        raise NotificationError(
            "O servidor de email (SMTP) ainda não está configurado nas Definições."
        )

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from_address
    msg["To"] = to_address

    try:
        port = settings.smtp_port or 587
        with smtplib.SMTP(settings.smtp_host, port, timeout=10) as server:
            if settings.smtp_use_tls:
                server.starttls()
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password)
            server.sendmail(settings.smtp_from_address, [to_address], msg.as_string())
    except (smtplib.SMTPException, OSError) as e:
        raise NotificationError(str(e)) from e


def _format_alert_body(profile, conn, summary):
    lines = [
        f'SQL Monitor — novo alerta no perfil "{profile.name}" ({conn.server})',
        "",
    ]
    if summary.get("error"):
        lines.append(f"Não foi possível ligar à instância: {summary['error']}")
    else:
        for key in PROBLEM_KEYS:
            value = summary.get(key, 0)
            if value:
                lines.append(f"- {PROBLEM_LABELS[key]}: {value}")
    lines += [
        "",
        "Este é o único email para esta situação — não voltas a ser avisado "
        "enquanto continuar por resolver; só quando ficar resolvida e "
        "acontecer de novo.",
        "",
        f"({datetime.datetime.now():%d/%m/%Y %H:%M})",
    ]
    return "\n".join(lines)


def check_and_notify(app):
    """Corre a cada CHECK_INTERVAL_MINUTES (ver snapshot.setup_scheduler).
    Para cada perfil com notificações ativas, verifica o estado atual e
    envia um email só se acabou de passar de "tudo bem" para "há
    problemas"."""
    with app.app_context():
        from app import db
        from app.models import Profile, SqlConnection, CustomCheck
        from app.sql_client import get_summary

        settings = get_app_settings()
        if not settings.is_configured:
            return

        profiles = Profile.query.filter_by(notify_enabled=True).all()
        for profile in profiles:
            if not profile.notify_email:
                continue
            conn = SqlConnection.query.filter_by(profile_id=profile.id).first()
            if not conn:
                continue

            checks = CustomCheck.query.filter_by(
                profile_id=profile.id, active=True
            ).all()
            summary = get_summary(conn, custom_checks=checks)
            is_bad = bool(summary.get("error")) or any(
                summary.get(k, 0) for k in PROBLEM_KEYS
            )

            if is_bad and not profile.notify_last_state:
                try:
                    send_email(
                        settings,
                        profile.notify_email,
                        f'[SQL Monitor] Alerta em "{profile.name}"',
                        _format_alert_body(profile, conn, summary),
                    )
                except NotificationError:
                    # Falha a enviar (ex: SMTP em baixo) não deve impedir o
                    # resto da app de continuar a funcionar — a próxima
                    # verificação tenta outra vez, já que só mudamos
                    # notify_last_state depois disto (ver abaixo).
                    pass
                else:
                    profile.notify_last_state = True
            elif not is_bad and profile.notify_last_state:
                profile.notify_last_state = False

        db.session.commit()
