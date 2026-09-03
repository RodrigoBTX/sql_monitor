import datetime
import decimal

from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required
from app.models import SqlConnection
from app.profiles import get_active_profile
from app.sql_client import (
    get_jobs_status,
    get_sessions,
    get_running_queries,
    SqlClientError,
    get_query_store_status,
    get_query_store_regressed,
    get_query_store_top_resource,
    get_query_store_overall_consumption,
    get_query_store_wait_stats,
    get_query_store_high_variation,
    get_query_store_forced_plans,
    get_backup_status,
    get_wait_stats,
    get_volume_space,
    get_io_stats,
    get_memory_status,
    get_index_fragmentation,
    get_recent_deadlocks,
    get_checkdb_status,
    get_suspect_pages,
    get_stale_statistics,
)

bp = Blueprint("monitoring", __name__, url_prefix="/monitoring")


def _jsonable(value):
    """Converte tipos que o pyodbc devolve (Decimal, datetime) para algo que
    o jsonify consiga serializar."""
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    return value


def _rows_to_json(rows):
    return [{k: _jsonable(v) for k, v in row.items()} for row in rows]


def _get_conn():
    profile = get_active_profile()
    return SqlConnection.query.filter_by(profile_id=profile.id).first()


@bp.route("/jobs")
@login_required
def jobs():
    conn = _get_conn()
    rows, error = [], None
    try:
        rows = (
            get_jobs_status(conn, stuck_minutes=conn.job_stuck_minutes or 60)
            if conn
            else []
        )
    except SqlClientError as e:
        error = str(e)
    return render_template("jobs.html", rows=rows, error=error)


@bp.route("/sessions")
@login_required
def sessions():
    conn = _get_conn()
    rows, error = [], None
    try:
        rows = get_sessions(conn) if conn else []
    except SqlClientError as e:
        error = str(e)
    return render_template("sessions.html", rows=rows, error=error)


@bp.route("/queries")
@login_required
def queries():
    conn = _get_conn()
    rows, error = [], None
    try:
        rows = (
            get_running_queries(conn, long_seconds=conn.query_long_seconds or 30)
            if conn
            else []
        )
    except SqlClientError as e:
        error = str(e)
    return render_template("queries.html", rows=rows, error=error)


@bp.route("/query-store")
@login_required
def query_store():
    """Página principal: só confirma o estado da Query Store. Cada relatório
    (regressed, top resource, etc.) é pedido depois via JS aos endpoints /api/*
    abaixo, para a página ficar interativa sem recarregar."""
    conn = _get_conn()
    database = request.args.get("db") or (conn.default_database if conn else "master")
    status, error = None, None
    try:
        if conn:
            status = get_query_store_status(conn, database)
    except SqlClientError as e:
        error = str(e)
    return render_template(
        "query_store.html", status=status, error=error, database=database
    )


def _qs_hours():
    try:
        return max(1, min(int(request.args.get("hours", 24)), 24 * 30))
    except (TypeError, ValueError):
        return 24


def _qs_database(conn):
    return request.args.get("db") or (conn.default_database if conn else "master")


@bp.route("/query-store/api/regressed")
@login_required
def api_qs_regressed():
    conn = _get_conn()
    if not conn:
        return jsonify({"error": "Sem ligação configurada."}), 400
    try:
        rows = get_query_store_regressed(conn, _qs_database(conn))
        return jsonify({"rows": _rows_to_json(rows)})
    except SqlClientError as e:
        return jsonify({"error": str(e)}), 502


@bp.route("/query-store/api/top-resource")
@login_required
def api_qs_top_resource():
    conn = _get_conn()
    if not conn:
        return jsonify({"error": "Sem ligação configurada."}), 400
    metric = request.args.get("metric", "duration")
    statistic = request.args.get("statistic", "total")
    try:
        rows = get_query_store_top_resource(
            conn,
            _qs_database(conn),
            hours=_qs_hours(),
            metric=metric,
            statistic=statistic,
        )
        return jsonify({"rows": _rows_to_json(rows)})
    except (SqlClientError, ValueError) as e:
        return jsonify({"error": str(e)}), 502


@bp.route("/query-store/api/overall-consumption")
@login_required
def api_qs_overall_consumption():
    conn = _get_conn()
    if not conn:
        return jsonify({"error": "Sem ligação configurada."}), 400
    try:
        rows = get_query_store_overall_consumption(
            conn, _qs_database(conn), hours=_qs_hours()
        )
        return jsonify({"rows": _rows_to_json(rows)})
    except SqlClientError as e:
        return jsonify({"error": str(e)}), 502


@bp.route("/query-store/api/wait-stats")
@login_required
def api_qs_wait_stats():
    conn = _get_conn()
    if not conn:
        return jsonify({"error": "Sem ligação configurada."}), 400
    try:
        rows = get_query_store_wait_stats(conn, _qs_database(conn), hours=_qs_hours())
        return jsonify({"rows": _rows_to_json(rows)})
    except SqlClientError as e:
        return jsonify({"error": str(e)}), 502


@bp.route("/query-store/api/high-variation")
@login_required
def api_qs_high_variation():
    conn = _get_conn()
    if not conn:
        return jsonify({"error": "Sem ligação configurada."}), 400
    try:
        rows = get_query_store_high_variation(
            conn, _qs_database(conn), hours=_qs_hours()
        )
        return jsonify({"rows": _rows_to_json(rows)})
    except SqlClientError as e:
        return jsonify({"error": str(e)}), 502


@bp.route("/query-store/api/forced-plans")
@login_required
def api_qs_forced_plans():
    conn = _get_conn()
    if not conn:
        return jsonify({"error": "Sem ligação configurada."}), 400
    try:
        rows = get_query_store_forced_plans(conn, _qs_database(conn))
        return jsonify({"rows": _rows_to_json(rows)})
    except SqlClientError as e:
        return jsonify({"error": str(e)}), 502


@bp.route("/backups")
@login_required
def backups():
    conn = _get_conn()
    rows, error = [], None
    try:
        rows = (
            get_backup_status(conn, stale_full_days=conn.backup_stale_days or 7)
            if conn
            else []
        )
    except SqlClientError as e:
        error = str(e)
    return render_template("backups.html", rows=rows, error=error)


@bp.route("/capacity")
@login_required
def capacity():
    conn = _get_conn()
    waits, volumes, io_stats, memory, error = [], [], [], {}, None
    try:
        if conn:
            waits = get_wait_stats(conn)
            volumes = get_volume_space(conn, low_free_pct=conn.disk_low_pct or 15)
            io_stats = get_io_stats(conn)
            memory = get_memory_status(conn)
    except SqlClientError as e:
        error = str(e)
    return render_template(
        "capacity.html",
        waits=waits,
        volumes=volumes,
        io_stats=io_stats,
        memory=memory,
        error=error,
    )


@bp.route("/index-health")
@login_required
def index_health():
    conn = _get_conn()
    database = request.args.get("db") or (conn.default_database if conn else "master")
    rows, stats_rows, error = [], [], None
    try:
        if conn:
            rows = get_index_fragmentation(conn, database)
            stats_rows = get_stale_statistics(conn, database)
    except SqlClientError as e:
        error = str(e)
    return render_template(
        "index_health.html",
        rows=rows,
        stats_rows=stats_rows,
        error=error,
        database=database,
    )


@bp.route("/deadlocks")
@login_required
def deadlocks():
    conn = _get_conn()
    rows, error = [], None
    try:
        rows = get_recent_deadlocks(conn) if conn else []
    except SqlClientError as e:
        error = str(e)
    return render_template("deadlocks.html", rows=rows, error=error)


@bp.route("/integrity")
@login_required
def integrity():
    conn = _get_conn()
    checkdb_rows, suspect_rows, error = [], [], None
    try:
        if conn:
            checkdb_rows = get_checkdb_status(
                conn, stale_days=conn.checkdb_stale_days or 7
            )
            suspect_rows = get_suspect_pages(conn)
    except SqlClientError as e:
        error = str(e)
    return render_template(
        "integrity.html",
        checkdb_rows=checkdb_rows,
        suspect_rows=suspect_rows,
        error=error,
    )
