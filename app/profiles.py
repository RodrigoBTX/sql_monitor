"""Gestão de perfis: cada perfil representa uma instância SQL Server
monitorizada de forma independente (a sua ligação, os seus Custom Checks,
o seu histórico). Isto permite ter várias instâncias/clientes configurados
na mesma instalação sem misturar dados entre eles.

get_active_profile() é o ponto único a partir do qual todo o resto da app
sabe "de que perfil estou a falar agora" — todas as rotas que antes faziam
SqlConnection.query.first() passam a usar este perfil para filtrar."""

from flask import Blueprint, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app import db
from app.models import Profile, SqlConnection, CustomCheck, MetricSnapshot

bp = Blueprint("profiles", __name__, url_prefix="/profiles")


def get_active_profile():
    """Devolve o perfil atualmente selecionado por este utilizador (guardado
    para sobreviver a reinícios da app), com fallback seguro: se ainda não
    tiver nenhum selecionado, ou o que tinha foi removido, usa o primeiro
    que existir; se não existir nenhum perfil (instalação nova), cria um
    "Principal" automaticamente."""
    profile = None
    if current_user.is_authenticated and current_user.active_profile_id:
        profile = db.session.get(Profile, current_user.active_profile_id)

    if profile is None:
        profile = Profile.query.order_by(Profile.id).first()

    if profile is None:
        profile = Profile(name="Principal", is_snapshot_primary=True)
        db.session.add(profile)
        db.session.commit()

    if current_user.is_authenticated and current_user.active_profile_id != profile.id:
        current_user.active_profile_id = profile.id
        db.session.commit()

    return profile


@bp.route("/new", methods=["POST"])
@login_required
def new():
    name = request.form.get("name", "").strip() or "Novo perfil"
    profile = Profile(name=name, is_snapshot_primary=False)
    db.session.add(profile)
    db.session.commit()
    # Troca já para o perfil recém-criado, para ires diretamente configurar
    # a ligação dele.
    current_user.active_profile_id = profile.id
    db.session.commit()
    flash(f"Perfil '{name}' criado — configura agora a ligação dele.", "success")
    return redirect(url_for("settings.setup"))


@bp.route("/<int:profile_id>/switch")
@login_required
def switch(profile_id):
    profile = db.session.get(Profile, profile_id)
    if profile is None:
        flash("Esse perfil já não existe.", "danger")
        return redirect(url_for("dashboard.index"))
    current_user.active_profile_id = profile.id
    db.session.commit()
    return redirect(url_for("dashboard.index"))


@bp.route("/<int:profile_id>/set-primary", methods=["POST"])
@login_required
def set_primary(profile_id):
    profile = db.session.get(Profile, profile_id)
    if profile is None:
        flash("Esse perfil já não existe.", "danger")
        return redirect(url_for("settings.setup"))
    # Só um perfil pode ser o principal para histórico de cada vez.
    Profile.query.update({Profile.is_snapshot_primary: False})
    profile.is_snapshot_primary = True
    db.session.commit()
    flash(
        f"'{profile.name}' passou a ser o perfil principal para histórico.", "success"
    )
    return redirect(url_for("settings.setup"))


@bp.route("/<int:profile_id>/rename", methods=["POST"])
@login_required
def rename(profile_id):
    profile = db.session.get(Profile, profile_id)
    if profile is None:
        flash("Esse perfil já não existe.", "danger")
        return redirect(url_for("settings.setup"))
    new_name = request.form.get("name", "").strip()
    if new_name:
        profile.name = new_name
        db.session.commit()
        flash("Perfil renomeado.", "success")
    return redirect(url_for("settings.setup"))


@bp.route("/<int:profile_id>/delete", methods=["POST"])
@login_required
def delete(profile_id):
    if Profile.query.count() <= 1:
        flash("Não é possível remover o único perfil que existe.", "danger")
        return redirect(url_for("settings.setup"))

    profile = db.session.get(Profile, profile_id)
    if profile is None:
        flash("Esse perfil já não existe.", "danger")
        return redirect(url_for("settings.setup"))

    was_primary = profile.is_snapshot_primary
    profile_name = profile.name

    SqlConnection.query.filter_by(profile_id=profile.id).delete()
    CustomCheck.query.filter_by(profile_id=profile.id).delete()
    MetricSnapshot.query.filter_by(profile_id=profile.id).delete()
    db.session.delete(profile)
    db.session.commit()

    # Se algum utilizador tinha este perfil ativo, ou este era o principal
    # para histórico, escolhe automaticamente outro para não ficar "órfão".
    from app.models import User

    remaining = Profile.query.order_by(Profile.id).first()
    if remaining:
        User.query.filter_by(active_profile_id=profile_id).update(
            {User.active_profile_id: remaining.id}
        )
        if was_primary:
            remaining.is_snapshot_primary = True
        db.session.commit()

    flash(f"Perfil '{profile_name}' removido.", "success")
    return redirect(url_for("settings.setup"))
