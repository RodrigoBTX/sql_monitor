from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required
from app import db
from app.models import SqlConnection, CustomCheck
from app.profiles import get_active_profile
from app.sql_client import run_all_custom_checks, SqlClientError
from app.sql_guard import validate_select_only

bp = Blueprint("custom_checks", __name__, url_prefix="/custom-checks")


def _get_conn():
    profile = get_active_profile()
    return SqlConnection.query.filter_by(profile_id=profile.id).first()


@bp.route("/")
@login_required
def index():
    conn = _get_conn()
    profile = get_active_profile()
    checks = (
        CustomCheck.query.filter_by(profile_id=profile.id)
        .order_by(CustomCheck.name)
        .all()
    )
    results_by_id = {}
    error = None
    if conn:
        try:
            for check, result in zip(
                [c for c in checks if c.active],
                run_all_custom_checks(conn, [c for c in checks if c.active]),
            ):
                results_by_id[check.id] = result
        except SqlClientError as e:
            error = str(e)
    return render_template(
        "custom_checks.html",
        checks=checks,
        results_by_id=results_by_id,
        error=error,
        conn=conn,
    )


def _fill_from_form(check: CustomCheck):
    check.name = request.form.get("name", "").strip()
    check.database_name = request.form.get("database_name", "").strip()
    check.sql_query = request.form.get("query", "").strip()
    check.description = request.form.get("description", "").strip()
    threshold = request.form.get("warn_threshold", "").strip()
    check.warn_threshold = int(threshold) if threshold else None
    check.comparison = request.form.get("comparison", "gt")
    check.active = bool(request.form.get("active"))


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    conn = _get_conn()
    profile = get_active_profile()
    if request.method == "POST":
        check = CustomCheck(profile_id=profile.id)
        _fill_from_form(check)
        if not check.name or not check.database_name or not check.sql_query:
            flash("Preenche pelo menos o nome, a base de dados e a query.", "danger")
            return render_template("custom_check_form.html", check=check, conn=conn)
        try:
            validate_select_only(check.sql_query)
        except ValueError as e:
            flash(str(e), "danger")
            return render_template("custom_check_form.html", check=check, conn=conn)
        db.session.add(check)
        db.session.commit()
        flash("Check criado.", "success")
        return redirect(url_for("custom_checks.index"))
    return render_template("custom_check_form.html", check=None, conn=conn)


@bp.route("/<int:check_id>/edit", methods=["GET", "POST"])
@login_required
def edit(check_id):
    conn = _get_conn()
    profile = get_active_profile()
    check = CustomCheck.query.filter_by(
        id=check_id, profile_id=profile.id
    ).first_or_404()
    if request.method == "POST":
        _fill_from_form(check)
        if not check.name or not check.database_name or not check.sql_query:
            flash("Preenche pelo menos o nome, a base de dados e a query.", "danger")
            return render_template("custom_check_form.html", check=check, conn=conn)
        try:
            validate_select_only(check.sql_query)
        except ValueError as e:
            flash(str(e), "danger")
            return render_template("custom_check_form.html", check=check, conn=conn)
        db.session.commit()
        flash("Check atualizado.", "success")
        return redirect(url_for("custom_checks.index"))
    return render_template("custom_check_form.html", check=check, conn=conn)


@bp.route("/<int:check_id>/delete", methods=["POST"])
@login_required
def delete(check_id):
    profile = get_active_profile()
    check = CustomCheck.query.filter_by(
        id=check_id, profile_id=profile.id
    ).first_or_404()
    db.session.delete(check)
    db.session.commit()
    flash("Check removido.", "success")
    return redirect(url_for("custom_checks.index"))


@bp.route("/<int:check_id>/toggle", methods=["POST"])
@login_required
def toggle(check_id):
    profile = get_active_profile()
    check = CustomCheck.query.filter_by(
        id=check_id, profile_id=profile.id
    ).first_or_404()
    check.active = not check.active
    db.session.commit()
    return redirect(url_for("custom_checks.index"))
