import os
import sys
from flask import Flask, redirect, url_for
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect


def _resolve_instance_path():
    """Onde fica a pasta instance/ (base de dados, chaves, etc).

    Quando a app corre normalmente (python run.py), fica ao lado da pasta
    app/, como sempre. Quando corre compilada com o PyInstaller
    (sys.frozen), tem de ficar ao lado do .exe — nunca dentro de
    sys._MEIPASS, que é uma pasta temporária apagada a cada arranque; se
    a base de dados fosse ali parar, perdias a configuração e o login
    sempre que fechasses a app."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "instance")


db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
csrf = CSRFProtect()


def _get_or_create_secret_key(instance_path):
    """Chave usada pelo Flask para assinar o cookie de sessão (login) e,
    se um dia ativarmos CSRF, os tokens dos formulários. Gerada uma única
    vez e guardada em instance/secret_key (tal como já fazemos com a chave
    de encriptação da password em instance/secret.key), para não mudar a
    cada arranque — se mudasse, todas as sessões abertas ficavam inválidas
    e obrigava a fazer login outra vez sempre que reiniciasses a app.

    Pode ser sobreposta com a variável de ambiente SECRET_KEY, se um dia
    quiseres controlar isto tu próprio (ex: numa instalação partilhada)."""
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key

    path = os.path.join(instance_path, "secret_key")
    if os.path.exists(path):
        with open(path, "rb") as f:
            key = f.read()
        if key:
            return key

    key = os.urandom(32)
    with open(path, "wb") as f:
        f.write(key)
    os.chmod(path, 0o600)
    return key


def _migrate_sqlite_schema(engine):
    """Migração leve para bases de dados locais (instance/app.db) criadas por
    versões anteriores da app, que ainda não têm as colunas/tabelas novas.
    Evita teres de apagar a configuração já guardada sempre que atualizo o
    esquema. Tabelas novas são criadas pelo db.create_all() acima; isto só
    trata colunas novas em tabelas que já existiam."""
    migrations = {
        "sql_connection": {
            "job_stuck_minutes": "INTEGER DEFAULT 60",
            "query_long_seconds": "INTEGER DEFAULT 30",
            "disk_low_pct": "INTEGER DEFAULT 15",
            "backup_stale_days": "INTEGER DEFAULT 7",
            "snapshot_interval_minutes": "INTEGER DEFAULT 15",
            "checkdb_stale_days": "INTEGER DEFAULT 7",
        },
        "custom_check": {
            "comparison": "VARCHAR(5) DEFAULT 'gt'",
        },
        "profile": {
            "notify_enabled": "BOOLEAN DEFAULT 0",
            "notify_email": "VARCHAR(255)",
            "notify_last_state": "BOOLEAN DEFAULT 0",
        },
    }
    with engine.connect() as conn:
        # A coluna "query" do custom_check foi renomeada para "sql_query"
        # (colidia com o atributo especial Model.query do Flask-SQLAlchemy).
        cc_cols = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(custom_check)")
        }
        if "query" in cc_cols and "sql_query" not in cc_cols:
            conn.exec_driver_sql(
                "ALTER TABLE custom_check RENAME COLUMN query TO sql_query"
            )

        for table, columns in migrations.items():
            existing_cols = {
                row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")
            }
            if not existing_cols:
                continue  # tabela não existe ainda nesta base (instalação nova)
            for col_name, col_def in columns.items():
                if col_name not in existing_cols:
                    conn.exec_driver_sql(
                        f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}"
                    )

        # --- Perfis (múltiplas instâncias/clientes na mesma instalação) ---
        # A tabela "profile" em si é nova e já é criada pelo db.create_all()
        # de cima; aqui só precisamos de acrescentar a coluna profile_id às
        # tabelas que já existiam antes dos perfis existirem.
        profile_fk_columns = {
            "sql_connection": "profile_id",
            "custom_check": "profile_id",
            "metric_snapshot": "profile_id",
            "user": "active_profile_id",
        }
        for table, col_name in profile_fk_columns.items():
            existing_cols = {
                row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")
            }
            if existing_cols and col_name not in existing_cols:
                conn.exec_driver_sql(
                    f"ALTER TABLE {table} ADD COLUMN {col_name} INTEGER"
                )
        conn.commit()

        # Se já havia uma ligação configurada de uma instalação anterior aos
        # perfis existirem, cria um perfil "Principal" automaticamente e
        # associa-lhe tudo o que já lá estava, para não perderes nada.
        profile_count = conn.exec_driver_sql("SELECT COUNT(*) FROM profile").scalar()
        sc_cols_now = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(sql_connection)")
        }
        sc_count = (
            conn.exec_driver_sql("SELECT COUNT(*) FROM sql_connection").scalar()
            if sc_cols_now
            else 0
        )
        if profile_count == 0 and sc_count > 0:
            conn.exec_driver_sql(
                "INSERT INTO profile (name, created_at, is_snapshot_primary) "
                "VALUES ('Principal', CURRENT_TIMESTAMP, 1)"
            )
            new_profile_id = conn.exec_driver_sql("SELECT last_insert_rowid()").scalar()
            conn.exec_driver_sql(
                f"UPDATE sql_connection SET profile_id = {new_profile_id} WHERE profile_id IS NULL"
            )
            conn.exec_driver_sql(
                f"UPDATE custom_check SET profile_id = {new_profile_id} WHERE profile_id IS NULL"
            )
            conn.exec_driver_sql(
                f"UPDATE metric_snapshot SET profile_id = {new_profile_id} WHERE profile_id IS NULL"
            )
            conn.exec_driver_sql(
                f"UPDATE user SET active_profile_id = {new_profile_id} WHERE active_profile_id IS NULL"
            )
            conn.commit()


def create_app():
    app = Flask(
        __name__,
        instance_relative_config=True,
        instance_path=_resolve_instance_path(),
    )

    os.makedirs(app.instance_path, exist_ok=True)

    from app.logging_setup import setup_logging

    logger = setup_logging(app)

    app.config.from_mapping(
        SECRET_KEY=_get_or_create_secret_key(app.instance_path),
        SQLALCHEMY_DATABASE_URI="sqlite:///"
        + os.path.join(app.instance_path, "app.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from app.sql_client import friendly_connection_error

    app.jinja_env.filters["friendly_error"] = friendly_connection_error

    from app.version import get_app_version

    app_version = get_app_version()

    @app.context_processor
    def inject_version():
        return {"app_version": app_version}

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from app.auth import bp as auth_bp
    from app.settings import bp as settings_bp
    from app.dashboard import bp as dashboard_bp
    from app.monitoring import bp as monitoring_bp
    from app.custom_checks import bp as custom_checks_bp
    from app.trends import bp as trends_bp
    from app.profiles import bp as profiles_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(monitoring_bp)
    app.register_blueprint(custom_checks_bp)
    app.register_blueprint(trends_bp)
    app.register_blueprint(profiles_bp)

    with app.app_context():
        db.create_all()
        _migrate_sqlite_schema(db.engine)

    from app.snapshot import setup_scheduler

    setup_scheduler(app)

    from app.cli import register_cli

    register_cli(app)

    logger.info("SQL Monitor (versão %s) arrancado.", app_version)

    from flask_wtf.csrf import CSRFError

    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        # Em vez do erro 400 genérico do Flask-WTF, mostra uma mensagem
        # percetível e volta para trás — acontece sobretudo se deixares um
        # formulário aberto numa aba muito tempo (o token expira ao fim de
        # 1h) e só depois submeteres.
        from flask import flash, request

        flash("O formulário expirou ou é inválido — tenta novamente.", "danger")
        return redirect(request.referrer or url_for("dashboard.index"))

    @app.context_processor
    def inject_profiles():
        # Disponível em todos os templates, para a barra de navegação poder
        # mostrar o dropdown de perfis sem cada rota ter de passar isto
        # explicitamente.
        from flask_login import current_user
        from app.models import Profile

        if not current_user.is_authenticated:
            return {}
        from app.profiles import get_active_profile

        return {
            "active_profile": get_active_profile(),
            "all_profiles": Profile.query.order_by(Profile.name).all(),
        }

    @app.before_request
    def require_setup():
        # Redirect to setup wizard on first run (perfil ativo ainda sem
        # ligação configurada), except for the setup/auth/static endpoints.
        from flask import request
        from flask_login import current_user
        from app.models import SqlConnection

        # As rotas de perfis ficam sempre acessíveis (mesmo sem ligação
        # configurada no perfil atual) — senão, ao criar um perfil novo por
        # configurar, ficarias "preso" nele sem conseguires trocar para
        # outro já configurado.
        exempt = {
            "settings.setup",
            "auth.login",
            "auth.logout",
            "static",
            "profiles.new",
            "profiles.switch",
            "profiles.delete",
            "profiles.rename",
            "profiles.set_primary",
            # O backup é da base de dados inteira (todos os perfis), e a
            # configuração de email (SMTP) também é global — nenhum dos
            # dois depende de o perfil atual já ter uma ligação configurada.
            "settings.backup_download",
            "settings.smtp_save",
        }
        if (
            request.endpoint
            and request.endpoint not in exempt
            and current_user.is_authenticated
        ):
            from app.profiles import get_active_profile

            profile = get_active_profile()
            has_connection = (
                SqlConnection.query.filter_by(profile_id=profile.id).first() is not None
            )
            if not has_connection and request.endpoint != "settings.setup":
                return redirect(url_for("settings.setup"))

    return app
