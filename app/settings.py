import datetime
import os

from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    request,
    flash,
    send_file,
    current_app,
    after_this_request,
)
from flask_login import login_required
from app import db
from app.models import SqlConnection, Profile
from app.profiles import get_active_profile
from app.sql_client import test_connection
from app.backup import create_backup_copy, get_last_backup_at
from app.notifications import get_app_settings, send_email, NotificationError

bp = Blueprint("settings", __name__, url_prefix="/settings")


def _fill_from_form(conn: SqlConnection, profile: Profile):
    # O "Nome" identifica o perfil (aparece no dropdown/lista de perfis),
    # não a ligação em si.
    new_name = request.form.get("name", "").strip()
    if new_name:
        profile.name = new_name
    conn.server = request.form.get("server", "").strip()
    conn.port = int(request.form.get("port") or 1433)
    conn.auth_type = request.form.get("auth_type", "sql")
    conn.username = request.form.get("username", "").strip()
    new_password = request.form.get("password", "")
    if new_password:
        conn.password = new_password
    conn.default_database = (
        request.form.get("default_database", "master").strip() or "master"
    )
    conn.driver = request.form.get("driver") or "ODBC Driver 17 for SQL Server"
    conn.trust_server_certificate = bool(request.form.get("trust_server_certificate"))

    def _int_field(name, default):
        raw = request.form.get(name, "").strip()
        try:
            return int(raw) if raw else default
        except ValueError:
            return default

    conn.job_stuck_minutes = _int_field("job_stuck_minutes", 60)
    conn.query_long_seconds = _int_field("query_long_seconds", 30)
    conn.disk_low_pct = _int_field("disk_low_pct", 15)
    conn.backup_stale_days = _int_field("backup_stale_days", 7)
    conn.snapshot_interval_minutes = _int_field("snapshot_interval_minutes", 15)
    conn.checkdb_stale_days = _int_field("checkdb_stale_days", 7)

    # Notificações por email deste perfil (o servidor de envio em si é
    # global — ver AppSetting / _fill_smtp_from_form).
    was_enabled = profile.notify_enabled
    profile.notify_enabled = bool(request.form.get("notify_enabled"))
    profile.notify_email = request.form.get("notify_email", "").strip()
    if profile.notify_enabled != was_enabled:
        # Ao ligar/desligar as notificações, reinicia o estado de "já
        # avisei" — para a próxima verificação, depois de reativares,
        # decidir de novo a partir do estado real da instância, em vez de
        # ficar presa a um estado antigo de quando estava desligado.
        profile.notify_last_state = False


@bp.route("/setup", methods=["GET", "POST"])
@login_required
def setup():
    """Wizard de ligação do perfil atualmente selecionado (também alcançável
    depois como 'Definições'). A lista/gestão de perfis aparece sempre no
    topo desta página."""
    profile = get_active_profile()
    conn = SqlConnection.query.filter_by(profile_id=profile.id).first()

    if request.method == "POST":
        if conn is None:
            conn = SqlConnection(profile_id=profile.id)
            db.session.add(conn)
        _fill_from_form(conn, profile)
        # Guarda sempre (também no "Testar"), para não perder a password
        # já gravada quando o campo vier vazio num submit seguinte.
        db.session.commit()

        if request.form.get("action") == "test":
            ok, message = test_connection(conn)
            flash(
                (
                    ("Ligação bem sucedida: " + message)
                    if ok
                    else ("Falha na ligação: " + message)
                ),
                "success" if ok else "danger",
            )
            return render_template(
                "settings.html",
                conn=conn,
                profile=profile,
                last_backup_at=get_last_backup_at(current_app),
                smtp_settings=get_app_settings(),
            )

        flash("Configuração guardada.", "success")
        return redirect(url_for("dashboard.index"))

    return render_template(
        "settings.html",
        conn=conn,
        profile=profile,
        last_backup_at=get_last_backup_at(current_app),
        smtp_settings=get_app_settings(),
    )


def _fill_smtp_from_form(settings):
    settings.smtp_host = request.form.get("smtp_host", "").strip()
    settings.smtp_port = int(request.form.get("smtp_port") or 587)
    settings.smtp_username = request.form.get("smtp_username", "").strip()
    new_password = request.form.get("smtp_password", "")
    if new_password:
        settings.smtp_password = new_password
    settings.smtp_use_tls = bool(request.form.get("smtp_use_tls"))
    settings.smtp_from_address = request.form.get("smtp_from_address", "").strip()


@bp.route("/smtp", methods=["POST"])
@login_required
def smtp_save():
    """Configuração do servidor de email (SMTP) usado para enviar as
    notificações — é global (não pertence a nenhum perfil), porque
    normalmente só faz sentido teres uma conta/servidor de envio."""
    settings = get_app_settings()
    _fill_smtp_from_form(settings)
    db.session.commit()

    if request.form.get("action") == "test":
        to_address = request.form.get("smtp_test_to", "").strip()
        if not to_address:
            flash("Indica um email de destino para o teste.", "danger")
        else:
            try:
                send_email(
                    settings,
                    to_address,
                    "[SQL Monitor] Email de teste",
                    "Se estás a ler isto, a configuração de email do SQL Monitor está a funcionar.",
                )
                flash(f"Email de teste enviado para {to_address}.", "success")
            except NotificationError as e:
                flash(f"Falha ao enviar o email de teste: {e}", "danger")
    else:
        flash("Configuração de email guardada.", "success")

    return redirect(url_for("settings.setup"))


@bp.route("/backup", methods=["POST"])
@login_required
def backup_download():
    """Gera uma cópia da base de dados local (instance/app.db) e devolve-a
    como download. É sempre manual — não há nada agendado/automático aqui."""
    tmp_path = create_backup_copy(current_app)
    filename = f"sql_monitor_backup_{datetime.datetime.now():%Y%m%d_%H%M%S}.db"

    @after_this_request
    def _cleanup(response):
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return response

    return send_file(
        tmp_path,
        as_attachment=True,
        download_name=filename,
        mimetype="application/octet-stream",
    )
