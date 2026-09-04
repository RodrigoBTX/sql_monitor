"""Connects to the monitored SQL Server instance and runs the diagnostic
queries (SQL Agent jobs, sessions, blocking/long-running queries).
"""

import datetime
import struct

import pyodbc

from app.models import SqlConnection
from app.sql_guard import validate_select_only


class SqlClientError(Exception):
    pass


# Pares (fragmentos a procurar no erro técnico, em minúsculas) -> frase
# simples a mostrar em destaque. O erro técnico completo (pyodbc/ODBC)
# continua sempre disponível, sem tradução, atrás do botão "Mais
# informações" nas páginas — isto é só para dar uma primeira leitura
# rápida do que se passou, sem teres de decifrar o texto do driver ODBC.
_FRIENDLY_ERROR_PATTERNS = [
    (
        (
            "wait operation timed out",
            "login timeout expired",
            "server is not found",
            "server is not accessible",
            "network-related",
            "target machine actively refused",
            "no connection could be made",
        ),
        "Não foi possível chegar à instância SQL Server. Verifica se está "
        "acessível na rede a partir deste computador (ex: VPN ligada) e se "
        "o SQL Server está configurado para aceitar ligações remotas.",
    ),
    (
        ("login failed for user",),
        "Falha de autenticação — confirma o utilizador e a password nas Definições.",
    ),
    (
        ("cannot open database", "database ... does not exist", "invalid object name"),
        "Não foi possível abrir a base de dados indicada — confirma o nome "
        "nas Definições.",
    ),
    (
        ("ssl provider", "certificate chain", "certificate verify failed"),
        "Problema com o certificado SSL do servidor — experimenta ativar "
        '"Confiar no certificado do servidor" nas Definições.',
    ),
    (
        (
            "permission was denied",
            "the server principal",
            "view server state permission",
        ),
        "O login usado não tem permissões suficientes para esta consulta "
        '(falta "VIEW SERVER STATE" ou acesso à base de dados).',
    ),
    (
        ("timeout expired", "timeout"),
        "A instância demorou demasiado tempo a responder (timeout).",
    ),
]


def friendly_connection_error(raw_error):
    """Traduz o erro técnico (pyodbc/ODBC) mais comum para uma frase curta
    e compreensível. Se não reconhecer o padrão, devolve uma mensagem
    genérica — o texto original nunca é perdido, fica sempre disponível
    à parte (ver templates: botão "Mais informações")."""
    if not raw_error:
        return "Erro desconhecido."
    lower = str(raw_error).lower()
    for needles, friendly in _FRIENDLY_ERROR_PATTERNS:
        if any(n in lower for n in needles):
            return friendly
    return "Não foi possível ligar à instância ou executar a consulta."


# O pyodbc não sabe descodificar o tipo DATETIMEOFFSET do SQL Server (ODBC
# SQL type -155) por omissão — é usado em várias colunas da Query Store
# (ex: rsi.start_time, sys.query_store_plan.last_execution_time). Sem este
# conversor, qualquer query que devolva essa coluna falha com
# "ODBC SQL type -155 is not yet supported".
SQL_SS_TIMESTAMPOFFSET = -155


def _handle_datetimeoffset(raw_value):
    tup = struct.unpack("<6hI2h", raw_value)  # (ano, mês, dia, h, m, s, ns, tz_h, tz_m)
    return datetime.datetime(
        tup[0],
        tup[1],
        tup[2],
        tup[3],
        tup[4],
        tup[5],
        tup[6] // 1000,
        datetime.timezone(datetime.timedelta(hours=tup[7], minutes=tup[8])),
    )


def get_connection_string(conn: SqlConnection, database: str | None = None):
    db_name = database or conn.default_database or "master"
    parts = [
        f"DRIVER={{{conn.driver}}}",
        f"SERVER={conn.server},{conn.port}",
        f"DATABASE={db_name}",
    ]
    if conn.auth_type == "windows":
        parts.append("Trusted_Connection=yes")
    else:
        parts.append(f"UID={conn.username}")
        parts.append(f"PWD={conn.password}")
    if conn.trust_server_certificate:
        parts.append("TrustServerCertificate=yes")
    return ";".join(parts)


def get_pyodbc_connection(
    conn: SqlConnection, database: str | None = None, timeout: int = 5
):
    connstr = get_connection_string(conn, database)
    try:
        cnxn = pyodbc.connect(connstr, timeout=timeout)
        cnxn.add_output_converter(SQL_SS_TIMESTAMPOFFSET, _handle_datetimeoffset)
        return cnxn
    except pyodbc.Error as e:
        raise SqlClientError(str(e)) from e


def test_connection(conn: SqlConnection):
    try:
        with get_pyodbc_connection(conn) as cnxn:
            cursor = cnxn.cursor()
            cursor.execute("SELECT @@VERSION")
            row = cursor.fetchone()
            return True, row[0] if row else "OK"
    except (SqlClientError, pyodbc.Error) as e:
        return False, str(e)


def run_query(
    conn: SqlConnection, query: str, database: str | None = None, params=None
):
    # Qualquer falha de comunicação com o SQL Server (ao ligar OU a meio da
    # query, ex: VPN/rede a cair) deve chegar às páginas como SqlClientError,
    # para ser mostrada como um alerta tratado em vez de um erro 500.
    try:
        with get_pyodbc_connection(conn, database) as cnxn:
            cursor = cnxn.cursor()
            cursor.execute(query, params or [])
            columns = [c[0] for c in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return rows
    except SqlClientError:
        raise
    except pyodbc.Error as e:
        raise SqlClientError(str(e)) from e


# ---------------------------------------------------------------------------
# SQL Agent jobs
# ---------------------------------------------------------------------------

JOBS_QUERY = """
SELECT
    j.name AS job_name,
    j.enabled,
    ja.start_execution_date,
    ja.stop_execution_date,
    CASE WHEN ja.stop_execution_date IS NULL AND ja.start_execution_date IS NOT NULL
         THEN DATEDIFF(MINUTE, ja.start_execution_date, GETDATE())
         ELSE NULL END AS running_minutes,
    jh.run_status,
    jh.run_date,
    jh.run_time,
    jh.message
FROM msdb.dbo.sysjobs j
LEFT JOIN msdb.dbo.sysjobactivity ja
    ON ja.job_id = j.job_id
    AND ja.session_id = (SELECT MAX(session_id) FROM msdb.dbo.sysjobactivity WHERE job_id = j.job_id)
OUTER APPLY (
    SELECT TOP 1 run_status, run_date, run_time, message
    FROM msdb.dbo.sysjobhistory h
    WHERE h.job_id = j.job_id AND h.step_id = 0
    ORDER BY h.run_date DESC, h.run_time DESC
) jh
ORDER BY j.name;
"""


def get_jobs_status(conn: SqlConnection, stuck_minutes: int = 60):
    rows = run_query(conn, JOBS_QUERY, database="msdb")
    for r in rows:
        running = r.get("running_minutes")
        r["is_running"] = (
            r.get("start_execution_date") is not None
            and r.get("stop_execution_date") is None
        )
        r["is_stuck"] = bool(running and running > stuck_minutes)
        # run_status: 0=Failed, 1=Succeeded, 2=Retry, 3=Canceled, 4=In progress
        r["last_status_label"] = {
            0: "Falhou",
            1: "Sucesso",
            2: "Repetição",
            3: "Cancelado",
            4: "Em curso",
            None: "Sem histórico",
        }.get(r.get("run_status"), "Desconhecido")
    return rows


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

SESSIONS_QUERY = """
SELECT
    s.session_id,
    s.login_name,
    s.host_name,
    s.program_name,
    s.status,
    s.last_request_start_time,
    DATEDIFF(SECOND, s.last_request_start_time, GETDATE()) AS seconds_since_last_request,
    r.blocking_session_id,
    r.wait_type,
    r.wait_time,
    r.command,
    r.total_elapsed_time
FROM sys.dm_exec_sessions s
LEFT JOIN sys.dm_exec_requests r ON r.session_id = s.session_id
WHERE s.is_user_process = 1
ORDER BY r.blocking_session_id DESC, s.last_request_start_time DESC;
"""


def get_sessions(conn: SqlConnection):
    rows = run_query(conn, SESSIONS_QUERY, database="master")
    for r in rows:
        r["is_blocked"] = bool(r.get("blocking_session_id"))
    return rows


# ---------------------------------------------------------------------------
# Running / blocking queries
# ---------------------------------------------------------------------------

QUERIES_QUERY = """
SELECT
    r.session_id,
    r.blocking_session_id,
    r.status,
    r.command,
    r.wait_type,
    r.wait_time,
    r.total_elapsed_time,
    r.cpu_time,
    r.start_time,
    DB_NAME(r.database_id) AS database_name,
    t.text AS query_text
FROM sys.dm_exec_requests r
CROSS APPLY sys.dm_exec_sql_text(r.sql_handle) t
WHERE r.session_id > 50
ORDER BY r.total_elapsed_time DESC;
"""


def get_running_queries(conn: SqlConnection, long_seconds: int = 30):
    rows = run_query(conn, QUERIES_QUERY, database="master")
    for r in rows:
        elapsed = r.get("total_elapsed_time") or 0
        r["is_long_running"] = elapsed > (long_seconds * 1000)
        r["is_blocked"] = bool(r.get("blocking_session_id"))
    return rows


# ---------------------------------------------------------------------------
# Query Store (regressed queries + top resource consumers)
# ---------------------------------------------------------------------------

QUERY_STORE_STATUS_QUERY = """
SELECT actual_state_desc, readonly_reason, current_storage_size_mb, max_storage_size_mb,
       interval_length_minutes
FROM sys.database_query_store_options;
"""


def get_query_store_status(conn: SqlConnection, database: str):
    rows = run_query(conn, QUERY_STORE_STATUS_QUERY, database=database)
    if not rows:
        return {
            "enabled": False,
            "state": "N/A (versão do SQL Server não suporta Query Store)",
        }
    row = rows[0]
    state = row.get("actual_state_desc")
    return {
        "enabled": state not in (None, "OFF"),
        "state": state,
        "readonly_reason": row.get("readonly_reason"),
        "storage_mb": row.get("current_storage_size_mb"),
        "max_storage_mb": row.get("max_storage_size_mb"),
        "interval_minutes": row.get("interval_length_minutes"),
    }


QUERY_STORE_REGRESSED_QUERY = """
WITH recent AS (
    SELECT q.query_id,
           AVG(rs.avg_duration) AS recent_avg_duration_us,
           SUM(rs.count_executions) AS recent_executions
    FROM sys.query_store_query q
    JOIN sys.query_store_plan p ON p.query_id = q.query_id
    JOIN sys.query_store_runtime_stats rs ON rs.plan_id = p.plan_id
    JOIN sys.query_store_runtime_stats_interval rsi
        ON rsi.runtime_stats_interval_id = rs.runtime_stats_interval_id
    WHERE rsi.start_time >= DATEADD(HOUR, -?, GETUTCDATE())
    GROUP BY q.query_id
),
historical AS (
    SELECT q.query_id,
           AVG(rs.avg_duration) AS hist_avg_duration_us,
           SUM(rs.count_executions) AS hist_executions
    FROM sys.query_store_query q
    JOIN sys.query_store_plan p ON p.query_id = q.query_id
    JOIN sys.query_store_runtime_stats rs ON rs.plan_id = p.plan_id
    JOIN sys.query_store_runtime_stats_interval rsi
        ON rsi.runtime_stats_interval_id = rs.runtime_stats_interval_id
    WHERE rsi.start_time < DATEADD(HOUR, -?, GETUTCDATE())
      AND rsi.start_time >= DATEADD(DAY, -7, GETUTCDATE())
    GROUP BY q.query_id
)
SELECT TOP 25
    r.query_id,
    qt.query_sql_text,
    r.recent_avg_duration_us / 1000.0 AS recent_avg_ms,
    h.hist_avg_duration_us / 1000.0 AS hist_avg_ms,
    r.recent_executions,
    h.hist_executions,
    (r.recent_avg_duration_us * 1.0 / NULLIF(h.hist_avg_duration_us, 0)) AS regression_factor
FROM recent r
JOIN historical h ON h.query_id = r.query_id
JOIN sys.query_store_query q ON q.query_id = r.query_id
JOIN sys.query_store_query_text qt ON qt.query_text_id = q.query_text_id
WHERE r.recent_executions >= 5
  AND h.hist_executions >= 5
  AND r.recent_avg_duration_us > h.hist_avg_duration_us * 1.5
ORDER BY regression_factor DESC;
"""


def get_query_store_regressed(
    conn: SqlConnection, database: str, recent_hours: int = 2
):
    rows = run_query(
        conn,
        QUERY_STORE_REGRESSED_QUERY,
        database=database,
        params=[recent_hours, recent_hours],
    )
    return rows


# Colunas válidas para cada métrica/estatística (whitelist fechada — nunca vem
# diretamente do utilizador para dentro do SQL, só através destes dicionários).
_QS_METRIC_COLUMNS = {
    "duration": {"avg": "avg_duration", "min": "min_duration", "max": "max_duration"},
    "cpu": {"avg": "avg_cpu_time", "min": "min_cpu_time", "max": "max_cpu_time"},
    "reads": {
        "avg": "avg_logical_io_reads",
        "min": "min_logical_io_reads",
        "max": "max_logical_io_reads",
    },
}
_QS_VALID_STATISTICS = {"total", "avg", "min", "max"}


def get_query_store_top_resource(
    conn: SqlConnection,
    database: str,
    hours: int = 24,
    metric: str = "duration",
    statistic: str = "total",
):
    """Top 25 queries por métrica/estatística à escolha, tal como o relatório
    'Top Resource Consuming Queries' do SSMS."""
    if metric == "executions":
        value_expr = "SUM(rs.count_executions)"
    else:
        cols = _QS_METRIC_COLUMNS.get(metric)
        if not cols:
            raise ValueError(f"Métrica desconhecida: {metric}")
        if statistic not in _QS_VALID_STATISTICS:
            raise ValueError(f"Estatística desconhecida: {statistic}")
        if statistic == "total":
            value_expr = f"SUM(rs.{cols['avg']} * rs.count_executions)"
        elif statistic == "avg":
            value_expr = f"SUM(rs.{cols['avg']} * rs.count_executions) / NULLIF(SUM(rs.count_executions), 0)"
        elif statistic == "min":
            value_expr = f"MIN(rs.{cols['min']})"
        else:
            value_expr = f"MAX(rs.{cols['max']})"

    query = f"""
    SELECT TOP 25
        q.query_id,
        qt.query_sql_text,
        SUM(rs.count_executions) AS total_executions,
        {value_expr} AS metric_value
    FROM sys.query_store_query q
    JOIN sys.query_store_query_text qt ON qt.query_text_id = q.query_text_id
    JOIN sys.query_store_plan p ON p.query_id = q.query_id
    JOIN sys.query_store_runtime_stats rs ON rs.plan_id = p.plan_id
    JOIN sys.query_store_runtime_stats_interval rsi
        ON rsi.runtime_stats_interval_id = rs.runtime_stats_interval_id
    WHERE rsi.start_time >= DATEADD(HOUR, -?, GETUTCDATE())
    GROUP BY q.query_id, qt.query_sql_text
    ORDER BY metric_value DESC;
    """
    return run_query(conn, query, database=database, params=[hours])


OVERALL_CONSUMPTION_QUERY = """
SELECT
    rsi.start_time,
    SUM(rs.count_executions) AS total_executions,
    SUM(rs.avg_duration * rs.count_executions) / 1000.0 AS total_duration_ms,
    SUM(rs.avg_cpu_time * rs.count_executions) / 1000.0 AS total_cpu_ms,
    SUM(rs.avg_logical_io_reads * rs.count_executions) AS total_logical_reads
FROM sys.query_store_runtime_stats rs
JOIN sys.query_store_runtime_stats_interval rsi
    ON rsi.runtime_stats_interval_id = rs.runtime_stats_interval_id
WHERE rsi.start_time >= DATEADD(HOUR, -?, GETUTCDATE())
GROUP BY rsi.start_time
ORDER BY rsi.start_time;
"""


def get_query_store_overall_consumption(
    conn: SqlConnection, database: str, hours: int = 24
):
    """Consumo total (execuções/duração/CPU/leituras) por intervalo de tempo —
    equivalente ao relatório 'Overall Resource Consumption' do SSMS."""
    return run_query(conn, OVERALL_CONSUMPTION_QUERY, database=database, params=[hours])


QUERY_WAIT_STATS_QUERY = """
SELECT TOP 25
    q.query_id,
    qt.query_sql_text,
    ws.wait_category_desc,
    SUM(ws.total_query_wait_time_ms) AS total_wait_ms
FROM sys.query_store_wait_stats ws
JOIN sys.query_store_plan p ON p.plan_id = ws.plan_id
JOIN sys.query_store_query q ON q.query_id = p.query_id
JOIN sys.query_store_query_text qt ON qt.query_text_id = q.query_text_id
JOIN sys.query_store_runtime_stats_interval rsi
    ON rsi.runtime_stats_interval_id = ws.runtime_stats_interval_id
WHERE rsi.start_time >= DATEADD(HOUR, -?, GETUTCDATE())
GROUP BY q.query_id, qt.query_sql_text, ws.wait_category_desc
ORDER BY total_wait_ms DESC;
"""


def get_query_store_wait_stats(conn: SqlConnection, database: str, hours: int = 24):
    """Tipos de espera por query (equivalente a 'Query Wait Statistics' do SSMS).
    Requer SQL Server 2017+ (sys.query_store_wait_stats)."""
    return run_query(conn, QUERY_WAIT_STATS_QUERY, database=database, params=[hours])


HIGH_VARIATION_QUERY = """
SELECT TOP 25
    q.query_id,
    qt.query_sql_text,
    SUM(rs.count_executions) AS total_executions,
    AVG(rs.avg_duration) / 1000.0 AS avg_duration_ms,
    AVG(rs.stdev_duration) / 1000.0 AS stdev_duration_ms,
    CASE WHEN AVG(rs.avg_duration) > 0
         THEN AVG(rs.stdev_duration) / AVG(rs.avg_duration)
         ELSE 0 END AS variation_ratio
FROM sys.query_store_query q
JOIN sys.query_store_query_text qt ON qt.query_text_id = q.query_text_id
JOIN sys.query_store_plan p ON p.query_id = q.query_id
JOIN sys.query_store_runtime_stats rs ON rs.plan_id = p.plan_id
JOIN sys.query_store_runtime_stats_interval rsi
    ON rsi.runtime_stats_interval_id = rs.runtime_stats_interval_id
WHERE rsi.start_time >= DATEADD(HOUR, -?, GETUTCDATE())
GROUP BY q.query_id, qt.query_sql_text
HAVING SUM(rs.count_executions) >= 5
ORDER BY variation_ratio DESC;
"""


def get_query_store_high_variation(conn: SqlConnection, database: str, hours: int = 24):
    """Queries cuja duração varia muito entre execuções (desvio padrão / média)."""
    return run_query(conn, HIGH_VARIATION_QUERY, database=database, params=[hours])


FORCED_PLANS_QUERY = """
SELECT
    q.query_id,
    qt.query_sql_text,
    p.plan_id,
    p.plan_forcing_type_desc,
    p.last_execution_time,
    p.count_compiles
FROM sys.query_store_plan p
JOIN sys.query_store_query q ON q.query_id = p.query_id
JOIN sys.query_store_query_text qt ON qt.query_text_id = q.query_text_id
WHERE p.is_forced_plan = 1
ORDER BY p.last_execution_time DESC;
"""


def get_query_store_forced_plans(conn: SqlConnection, database: str):
    """Queries com um plano forçado manualmente (equivalente a 'Queries With Forced Plans')."""
    return run_query(conn, FORCED_PLANS_QUERY, database=database)


# ---------------------------------------------------------------------------
# Backups
# ---------------------------------------------------------------------------

BACKUP_STATUS_QUERY = """
SELECT
    d.name AS database_name,
    d.recovery_model_desc,
    d.state_desc,
    MAX(CASE WHEN b.type = 'D' THEN b.backup_finish_date END) AS last_full_backup,
    MAX(CASE WHEN b.type = 'I' THEN b.backup_finish_date END) AS last_diff_backup,
    MAX(CASE WHEN b.type = 'L' THEN b.backup_finish_date END) AS last_log_backup
FROM sys.databases d
LEFT JOIN msdb.dbo.backupset b ON b.database_name = d.name
WHERE d.name NOT IN ('tempdb')
GROUP BY d.name, d.recovery_model_desc, d.state_desc
ORDER BY d.name;
"""


def get_backup_status(conn: SqlConnection, stale_full_days: int = 7):
    import datetime

    rows = run_query(conn, BACKUP_STATUS_QUERY, database="master")
    now = datetime.datetime.utcnow()
    for r in rows:
        last_full = r.get("last_full_backup")
        if last_full is None:
            r["full_backup_age_days"] = None
            r["is_stale"] = True
        else:
            age = (now - last_full).days
            r["full_backup_age_days"] = age
            r["is_stale"] = age > stale_full_days
        # Bases de sistema geridas de outra forma / normalmente sem backups próprios
        r["is_system_db"] = r["database_name"] in ("master", "model", "msdb")
    return rows


# ---------------------------------------------------------------------------
# Wait stats
# ---------------------------------------------------------------------------

WAIT_STATS_QUERY = """
SELECT TOP 15
    wait_type,
    wait_time_ms,
    waiting_tasks_count,
    signal_wait_time_ms,
    wait_time_ms - signal_wait_time_ms AS resource_wait_time_ms
FROM sys.dm_os_wait_stats
WHERE wait_time_ms > 0
  AND wait_type NOT IN (
    'CLR_SEMAPHORE','LAZYWRITER_SLEEP','RESOURCE_QUEUE','SLEEP_TASK','SLEEP_SYSTEMTASK',
    'SQLTRACE_BUFFER_FLUSH','WAITFOR','LOGMGR_QUEUE','CHECKPOINT_QUEUE',
    'REQUEST_FOR_DEADLOCK_SEARCH','XE_TIMER_EVENT','BROKER_TO_FLUSH','BROKER_TASK_STOP',
    'CLR_MANUAL_EVENT','CLR_AUTO_EVENT','DISPATCHER_QUEUE_SEMAPHORE',
    'FT_IFTS_SCHEDULER_IDLE_WAIT','XE_DISPATCHER_WAIT','XE_DISPATCHER_JOIN',
    'BROKER_EVENTHANDLER','TRACEWRITE','FT_IFTSHC_MUTEX','SQLTRACE_INCREMENTAL_FLUSH_SLEEP',
    'BROKER_RECEIVE_WAITFOR','ONDEMAND_TASK_QUEUE','DBMIRROR_EVENTS_QUEUE','DBMIRRORING_CMD',
    'BROKER_TRANSMITTER','SQLTRACE_WAIT_ENTRIES','SLEEP_BPOOL_FLUSH','SQLTRACE_FILE_BUFFER',
    'DIRTY_PAGE_POLL','HADR_FILESTREAM_IOMGR_IOCOMPLETION','SP_SERVER_DIAGNOSTICS_SLEEP'
  )
ORDER BY wait_time_ms DESC;
"""


def get_wait_stats(conn: SqlConnection):
    return run_query(conn, WAIT_STATS_QUERY, database="master")


# ---------------------------------------------------------------------------
# Disk / volume space
# ---------------------------------------------------------------------------

VOLUME_SPACE_QUERY = """
SELECT DISTINCT
    vs.volume_mount_point,
    CAST(vs.total_bytes / 1073741824.0 AS DECIMAL(10,2)) AS total_gb,
    CAST(vs.available_bytes / 1073741824.0 AS DECIMAL(10,2)) AS free_gb,
    CAST(100.0 * vs.available_bytes / NULLIF(vs.total_bytes, 0) AS DECIMAL(5,1)) AS free_pct
FROM sys.master_files mf
CROSS APPLY sys.dm_os_volume_stats(mf.database_id, mf.file_id) vs
ORDER BY free_pct ASC;
"""


def get_volume_space(conn: SqlConnection, low_free_pct: int = 15):
    rows = run_query(conn, VOLUME_SPACE_QUERY, database="master")
    for r in rows:
        pct = r.get("free_pct")
        r["is_low"] = pct is not None and pct < low_free_pct
    return rows


# ---------------------------------------------------------------------------
# I/O por ficheiro
# ---------------------------------------------------------------------------

IO_STATS_QUERY = """
SELECT
    DB_NAME(vfs.database_id) AS database_name,
    mf.name AS logical_name,
    mf.type_desc,
    vfs.num_of_reads,
    vfs.num_of_writes,
    CAST(vfs.io_stall_read_ms * 1.0 / NULLIF(vfs.num_of_reads, 0) AS DECIMAL(10,2)) AS avg_read_stall_ms,
    CAST(vfs.io_stall_write_ms * 1.0 / NULLIF(vfs.num_of_writes, 0) AS DECIMAL(10,2)) AS avg_write_stall_ms,
    CAST((vfs.size_on_disk_bytes) / 1048576.0 AS DECIMAL(12,1)) AS size_mb
FROM sys.dm_io_virtual_file_stats(NULL, NULL) vfs
JOIN sys.master_files mf ON mf.database_id = vfs.database_id AND mf.file_id = vfs.file_id
ORDER BY avg_read_stall_ms DESC;
"""


def get_io_stats(conn: SqlConnection, high_stall_ms: int = 20):
    """Latência média de leitura/escrita por ficheiro de dados/log — mais
    direto que os wait stats gerais para apontar a um disco lento em concreto."""
    rows = run_query(conn, IO_STATS_QUERY, database="master")
    for r in rows:
        read_stall = r.get("avg_read_stall_ms") or 0
        write_stall = r.get("avg_write_stall_ms") or 0
        r["is_slow"] = read_stall > high_stall_ms or write_stall > high_stall_ms
    return rows


# ---------------------------------------------------------------------------
# Memória
# ---------------------------------------------------------------------------

MEMORY_QUERY = """
SELECT
    (SELECT cntr_value FROM sys.dm_os_performance_counters
     WHERE counter_name = 'Page life expectancy' AND object_name LIKE '%Buffer Manager%') AS page_life_expectancy,
    (SELECT cntr_value FROM sys.dm_os_performance_counters
     WHERE counter_name = 'Buffer cache hit ratio' AND object_name LIKE '%Buffer Manager%') AS buffer_cache_hit_ratio,
    (SELECT total_physical_memory_kb / 1024 FROM sys.dm_os_sys_memory) AS total_physical_memory_mb,
    (SELECT available_physical_memory_kb / 1024 FROM sys.dm_os_sys_memory) AS available_physical_memory_mb,
    (SELECT physical_memory_in_use_kb / 1024 FROM sys.dm_os_process_memory) AS sql_server_memory_used_mb;
"""


def get_memory_status(conn: SqlConnection, low_ple_seconds: int = 300):
    """Page Life Expectancy e memória disponível — sinal clássico de pressão
    de memória na instância (PLE baixo = o buffer pool está a "andar à roda")."""
    rows = run_query(conn, MEMORY_QUERY, database="master")
    if not rows:
        return {}
    row = rows[0]
    ple = row.get("page_life_expectancy")
    row["ple_low"] = ple is not None and ple < low_ple_seconds
    return row


# ---------------------------------------------------------------------------
# Fragmentação de índices
# ---------------------------------------------------------------------------

INDEX_FRAGMENTATION_QUERY = """
SELECT TOP 25
    OBJECT_SCHEMA_NAME(ips.object_id) AS schema_name,
    OBJECT_NAME(ips.object_id) AS table_name,
    i.name AS index_name,
    ips.index_type_desc,
    ips.avg_fragmentation_in_percent,
    ips.page_count
FROM sys.dm_db_index_physical_stats(DB_ID(), NULL, NULL, NULL, 'LIMITED') ips
JOIN sys.indexes i ON i.object_id = ips.object_id AND i.index_id = ips.index_id
WHERE ips.page_count > 500
  AND ips.avg_fragmentation_in_percent > 10
  AND i.name IS NOT NULL
ORDER BY ips.avg_fragmentation_in_percent DESC;
"""


def get_index_fragmentation(
    conn: SqlConnection, database: str, high_frag_pct: int = 30
):
    """Índices mais fragmentados (modo 'LIMITED', leve — não faz scan completo
    das páginas). Só considera índices com alguma dimensão (>500 páginas)."""
    rows = run_query(conn, INDEX_FRAGMENTATION_QUERY, database=database)
    for r in rows:
        pct = r.get("avg_fragmentation_in_percent") or 0
        r["is_high"] = pct > high_frag_pct
    return rows


# ---------------------------------------------------------------------------
# Deadlocks recentes (via extended event "system_health", ativa por omissão)
# ---------------------------------------------------------------------------

DEADLOCKS_QUERY = """
;WITH xevents AS (
    SELECT
        xed.value('@timestamp', 'datetime2') AS event_time,
        xed.query('.') AS event_xml
    FROM (
        SELECT CAST(target_data AS XML) AS target_data
        FROM sys.dm_xe_session_targets st
        JOIN sys.dm_xe_sessions s ON s.address = st.event_session_address
        WHERE s.name = 'system_health' AND st.target_name = 'ring_buffer'
    ) AS t
    CROSS APPLY t.target_data.nodes('RingBufferTarget/event[@name="xml_deadlock_report"]') AS x(xed)
)
SELECT TOP 20
    x.event_time,
    dl.value('(victim-list/victimProcess/@id)[1]', 'nvarchar(100)') AS victim_process_id,
    CAST(dl.query('.') AS NVARCHAR(MAX)) AS deadlock_xml
FROM xevents x
-- "//deadlock" (em vez de um caminho fixo tipo data[@name=...]/value/deadlock)
-- procura o elemento <deadlock> em qualquer profundidade dentro do evento —
-- mais robusto a pequenas diferenças na estrutura do XML entre versões do
-- SQL Server do que assumir um caminho exato.
CROSS APPLY x.event_xml.nodes('//deadlock') AS d(dl)
ORDER BY x.event_time DESC;
"""


def _parse_deadlock_processes(deadlock_xml, victim_id):
    """Lê o grafo do deadlock (XML) e devolve um resumo de cada processo
    envolvido — SPID, login, aplicação, o que estava a correr, e se foi a
    vítima escolhida pelo SQL Server para terminar. Se o XML vier
    vazio/num formato inesperado, devolve uma lista vazia em vez de
    rebentar — o XML completo continua sempre disponível à parte (botão
    "Ver XML completo"), para abrires no SSMS como .xdl se precisares do
    grafo visual."""
    if not deadlock_xml:
        return []
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(deadlock_xml)
    except ET.ParseError:
        return []
    processes = []
    for proc in root.findall(".//process"):
        inputbuf = (proc.findtext("inputbuf") or "").strip()
        processes.append(
            {
                "process_id": proc.get("id"),
                "spid": proc.get("spid"),
                "login": proc.get("loginname"),
                "hostname": proc.get("hostname"),
                "program": proc.get("clientapp"),
                "isolation_level": proc.get("isolationlevel"),
                "wait_resource": proc.get("waitresource"),
                "query_text": inputbuf,
                "is_victim": proc.get("id") == victim_id,
            }
        )
    return processes


def get_recent_deadlocks(conn: SqlConnection):
    """Lê a extended event 'system_health' (que corre sempre por omissão) à
    procura de relatórios de deadlock recentes — não precisa de nenhuma
    configuração extra na instância. Para cada evento, devolve também o
    XML completo do deadlock graph e um resumo já interpretado de cada
    processo envolvido (login, aplicação, query, vítima ou não)."""
    rows = run_query(conn, DEADLOCKS_QUERY, database="master")
    for r in rows:
        r["processes"] = _parse_deadlock_processes(
            r.get("deadlock_xml"), r.get("victim_process_id")
        )
    return rows


# ---------------------------------------------------------------------------
# Corrupção — último CHECKDB conhecido por base de dados
# ---------------------------------------------------------------------------

DATABASE_LIST_QUERY = """
SELECT name AS database_name
FROM sys.databases
WHERE name NOT IN ('tempdb')
  AND state_desc = 'ONLINE'
ORDER BY name;
"""


def get_checkdb_status(conn: SqlConnection, stale_days: int = 7):
    """Para cada base de dados online, lê a data do último CHECKDB "limpo"
    conhecido pelo motor (DBCC DBINFO) — NÃO corre um CHECKDB novo aqui
    (é uma operação pesada, só deve correr agendada, ex: num SQL Agent
    job); isto só relata o que o SQL Server já sabe."""
    dbs = run_query(conn, DATABASE_LIST_QUERY, database="master")
    results = []
    for db_row in dbs:
        name = db_row["database_name"]
        last_checkdb = None
        error = None
        try:
            safe_name = name.replace("'", "''")
            info_rows = run_query(
                conn,
                f"DBCC DBINFO(N'{safe_name}') WITH TABLERESULTS;",
                database=name,
            )
            for r in info_rows:
                if r.get("Field") == "dbi_dbccLastKnownGood":
                    last_checkdb = r.get("Value")
                    break
        except SqlClientError as e:
            error = str(e)

        age_days = None
        never_run = True
        if isinstance(last_checkdb, datetime.datetime) and last_checkdb.year > 1900:
            age_days = (datetime.datetime.utcnow() - last_checkdb).days
            never_run = False

        results.append(
            {
                "database_name": name,
                "last_checkdb": last_checkdb if not never_run else None,
                "age_days": age_days,
                "never_run": never_run,
                "is_stale": error is not None
                or never_run
                or (age_days is not None and age_days > stale_days),
                "error": error,
            }
        )
    return results


# ---------------------------------------------------------------------------
# Corrupção — páginas suspeitas já detetadas pelo motor
# ---------------------------------------------------------------------------

SUSPECT_PAGES_QUERY = """
SELECT
    sp.database_id,
    DB_NAME(sp.database_id) AS database_name,
    sp.file_id,
    sp.page_id,
    sp.event_type,
    sp.error_count,
    sp.last_update_date
FROM msdb.dbo.suspect_pages sp
ORDER BY sp.last_update_date DESC;
"""

# event_type: https://learn.microsoft.com/sql/relational-databases/system-tables/suspect-pages-transact-sql
_SUSPECT_EVENT_LABELS = {
    1: "Erro de E/S (823/824/829)",
    2: "Falha de checksum",
    3: "Página rasgada (torn page)",
    4: "Reparado — restauro",
    5: "Reparado — DBCC",
    7: "Falha de checksum (memória)",
}
# 4 e 5 significam que já foi reparada; as restantes ainda estão por resolver.
_SUSPECT_RESOLVED_TYPES = {4, 5}


def get_suspect_pages(conn: SqlConnection):
    """Páginas que o próprio SQL Server já marcou como corrompidas (via
    verificação de checksum nas leituras/escritas normais) — não precisa
    de nenhum CHECKDB para aparecer aqui; é o sinal mais direto que existe
    de corrupção real de dados."""
    rows = run_query(conn, SUSPECT_PAGES_QUERY, database="msdb")
    for r in rows:
        event_type = r.get("event_type")
        r["event_label"] = _SUSPECT_EVENT_LABELS.get(event_type, f"Tipo {event_type}")
        r["is_active"] = event_type not in _SUSPECT_RESOLVED_TYPES
    return rows


# ---------------------------------------------------------------------------
# Estatísticas desatualizadas
# ---------------------------------------------------------------------------

STALE_STATISTICS_QUERY = """
SELECT TOP 50
    OBJECT_SCHEMA_NAME(s.object_id) AS schema_name,
    OBJECT_NAME(s.object_id) AS table_name,
    s.name AS stats_name,
    sp.last_updated,
    sp.rows,
    sp.rows_sampled,
    sp.modification_counter
FROM sys.stats s
CROSS APPLY sys.dm_db_stats_properties(s.object_id, s.stats_id) sp
JOIN sys.tables t ON t.object_id = s.object_id
WHERE t.is_ms_shipped = 0
ORDER BY sp.modification_counter DESC;
"""


def get_stale_statistics(conn: SqlConnection, database: str, high_pct: float = 20.0):
    """Estatísticas com uma percentagem elevada de linhas alteradas desde a
    última atualização — sinal de que o otimizador de queries pode estar a
    decidir planos de execução com base em dados desatualizados. Mostra as
    50 estatísticas mais alteradas da base de dados indicada."""
    rows = run_query(conn, STALE_STATISTICS_QUERY, database=database)
    for r in rows:
        rows_count = r.get("rows") or 0
        mods = r.get("modification_counter") or 0
        pct = (mods / rows_count * 100) if rows_count else (100.0 if mods else 0.0)
        r["modified_pct"] = pct
        r["is_stale"] = pct > high_pct and rows_count > 0
    return rows


# ---------------------------------------------------------------------------
# Custom checks (queries de negócio definidas pelo utilizador)
# ---------------------------------------------------------------------------


def run_custom_check(conn: SqlConnection, check):
    """Corre a query de um CustomCheck. Se devolver exatamente uma linha e
    uma coluna, trata-a como um valor escalar (ex: um COUNT) e compara com o
    limiar definido; caso contrário devolve as linhas tal e qual, como uma
    mini-listagem."""
    result = {
        "check": check,
        "error": None,
        "rows": [],
        "value": None,
        "breached": False,
    }
    try:
        # Defesa em profundidade: valida sempre no momento de correr, mesmo
        # que o check já esteja gravado (ex: criado antes desta validação
        # existir, ou editado diretamente na base de dados local).
        validate_select_only(check.sql_query)
        rows = run_query(conn, check.sql_query, database=check.database_name)
        result["rows"] = rows
        if len(rows) == 1 and len(rows[0]) == 1:
            value = list(rows[0].values())[0]
            result["value"] = value
            result["breached"] = check.is_breached(value)
    except (SqlClientError, ValueError) as e:
        result["error"] = str(e)
    return result


def run_all_custom_checks(conn: SqlConnection, checks):
    return [run_custom_check(conn, c) for c in checks if c.active]


# ---------------------------------------------------------------------------
# Dashboard summary
# ---------------------------------------------------------------------------


def get_summary(conn: SqlConnection, custom_checks=None):
    summary = {
        "jobs_failed": 0,
        "jobs_stuck": 0,
        "sessions_blocked": 0,
        "queries_long_running": 0,
        "backups_stale": 0,
        "disk_low": 0,
        "custom_checks_breached": 0,
        "error": None,
    }
    try:
        jobs = get_jobs_status(conn, stuck_minutes=conn.job_stuck_minutes or 60)
        summary["jobs_failed"] = sum(1 for j in jobs if j.get("run_status") == 0)
        summary["jobs_stuck"] = sum(1 for j in jobs if j.get("is_stuck"))

        sessions = get_sessions(conn)
        summary["sessions_blocked"] = sum(1 for s in sessions if s.get("is_blocked"))

        queries = get_running_queries(conn, long_seconds=conn.query_long_seconds or 30)
        summary["queries_long_running"] = sum(
            1 for q in queries if q.get("is_long_running")
        )

        backups = get_backup_status(conn, stale_full_days=conn.backup_stale_days or 7)
        summary["backups_stale"] = sum(
            1 for b in backups if b.get("is_stale") and not b.get("is_system_db")
        )

        volumes = get_volume_space(conn, low_free_pct=conn.disk_low_pct or 15)
        summary["disk_low"] = sum(1 for v in volumes if v.get("is_low"))

        if custom_checks:
            results = run_all_custom_checks(conn, custom_checks)
            summary["custom_checks_breached"] = sum(1 for r in results if r["breached"])
    except SqlClientError as e:
        summary["error"] = str(e)
    return summary
