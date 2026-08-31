from flask import Blueprint, render_template
from flask_login import login_required
from app.models import SqlConnection, CustomCheck
from app.sql_client import get_summary
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
    return render_template("dashboard.html", conn=conn, summary=summary)
