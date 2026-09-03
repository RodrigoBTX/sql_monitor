from flask import Blueprint, render_template
from flask_login import login_required
from app.models import SqlConnection, CustomCheck
from app.sql_client import (
    get_summary,
    get_recent_deadlocks,
    get_index_fragmentation,
    get_memory_status,
    get_checkdb_status,
    get_suspect_pages,
    SqlClientError,
)
from app.profiles import get_active_profile

bp = Blueprint("dashboard", __name__, url_prefix="/")


@bp.route("/")
@login_required
def index():
    profile = get_active_profile()
    conn = SqlConnection.query.filter_by(profile_id=profile.id).first()
    checks = (
        CustomCheck.query.filter_by(profile_id=profile.id, active=True).all()
        if conn
        else []
    )
    summary = get_summary(conn, custom_checks=checks) if conn else None

    # Diagnóstico extra (deadlocks, índices fragmentados, memória), só para
    # esta página — de propósito NÃO entra no get_summary() partilhado,
    # para não aumentar a carga das verificações em segundo plano
    # (snapshots a cada poucos minutos, notificações a cada 10 min): estas
    # três consultas só correm quando abres mesmo o dashboard.
    deadlocks_recent = index_fragmented = integrity_alerts = None
    memory_pressure = False
    if conn and summary and not summary.get("error"):
        try:
            deadlocks_recent = len(get_recent_deadlocks(conn))
            frag_rows = get_index_fragmentation(conn, conn.default_database or "master")
            index_fragmented = sum(1 for r in frag_rows if r.get("is_high"))
            memory = get_memory_status(conn)
            memory_pressure = bool(memory.get("ple_low"))

            # Alertas de integridade: páginas suspeitas por resolver (corrupção
            # real já detetada pelo motor) + bases de dados com o CHECKDB
            # atrasado ou nunca corrido — os dois sinais mais importantes de
            # "saúde" de uma base de dados.
            suspect_rows = get_suspect_pages(conn)
            active_suspect = sum(1 for r in suspect_rows if r.get("is_active"))
            checkdb_rows = get_checkdb_status(
                conn, stale_days=conn.checkdb_stale_days or 7
            )
            checkdb_stale = sum(1 for r in checkdb_rows if r.get("is_stale"))
            integrity_alerts = active_suspect + checkdb_stale
        except SqlClientError:
            # Uma falha aqui (ex: falta de permissões só para esta consulta
            # em concreto) não deve derrubar o resto do dashboard — os
            # cartões acima já mostram o essencial mesmo sem isto.
            pass

    return render_template(
        "dashboard.html",
        conn=conn,
        summary=summary,
        deadlocks_recent=deadlocks_recent,
        index_fragmented=index_fragmented,
        memory_pressure=memory_pressure,
        integrity_alerts=integrity_alerts,
    )
