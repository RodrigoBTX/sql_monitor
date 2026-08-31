from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required
from app import db
from app.models import SqlConnection, Profile
from app.profiles import get_active_profile
from app.sql_client import test_connection

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
            return render_template("settings.html", conn=conn, profile=profile)

        flash("Configuração guardada.", "success")
        return redirect(url_for("dashboard.index"))

    return render_template("settings.html", conn=conn, profile=profile)
