import datetime

from flask import Blueprint, render_template, request
from flask_login import login_required
from app.models import MetricSnapshot
from app.profiles import get_active_profile

bp = Blueprint("trends", __name__, url_prefix="/trends")

_PERIODS = {
    "24h": ("Últimas 24h", 1),
    "7d": ("Últimos 7 dias", 7),
    "30d": ("Últimos 30 dias", 30),
}


@bp.route("/")
@login_required
def index():
    profile = get_active_profile()
    period = request.args.get("period", "24h")
    label, days = _PERIODS.get(period, _PERIODS["24h"])
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    snapshots = (
        MetricSnapshot.query.filter(
            MetricSnapshot.profile_id == profile.id, MetricSnapshot.taken_at >= since
        )
        .order_by(MetricSnapshot.taken_at.asc())
        .all()
    )
    chart_data = [
        {
            "taken_at": s.taken_at.isoformat(),
            "jobs_failed": s.jobs_failed,
            "jobs_stuck": s.jobs_stuck,
            "sessions_blocked": s.sessions_blocked,
            "queries_long_running": s.queries_long_running,
            "backups_stale": s.backups_stale,
            "disk_low": s.disk_low,
            "custom_checks_breached": s.custom_checks_breached,
        }
        for s in snapshots
    ]
    return render_template(
        "trends.html",
        snapshots_count=len(snapshots),
        chart_data=chart_data,
        period=period,
        period_label=label,
        has_data=len(snapshots) > 0,
        is_snapshot_primary=profile.is_snapshot_primary,
    )
