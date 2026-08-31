"""Comandos de linha de comandos da app (flask CLI), para tarefas de
manutenção que não fazem sentido ter na interface web — hoje só a
recuperação de password, se te esqueceres da conta de acesso à app."""
import click

from app import db
from app.models import User


def register_cli(app):
    @app.cli.command("reset-password")
    @click.argument("username")
    @click.password_option(help="Nova password (se não indicares, é pedida de forma escondida).")
    def reset_password(username, password):
        """Repõe a password de um utilizador existente, ou cria um novo se
        o utilizador indicado não existir (útil se te esqueceres da tua
        password de acesso à app)."""
        user = User.query.filter_by(username=username).first()
        if user is None:
            user = User(username=username)
            db.session.add(user)
            click.echo(f"Utilizador '{username}' não existia — vai ser criado.")
        user.set_password(password)
        db.session.commit()
        click.echo(f"Password de '{username}' atualizada com sucesso.")
