import datetime

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db
from app.crypto_utils import encrypt, decrypt


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    # Último perfil que este utilizador tinha selecionado (dropdown de
    # perfis) — para reabrir sempre no mesmo, mesmo depois de reiniciar a app.
    active_profile_id = db.Column(
        db.Integer, db.ForeignKey("profile.id"), nullable=True
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Profile(db.Model):
    """Um 'perfil' representa uma instância SQL Server monitorizada de forma
    independente — a sua própria ligação, os seus próprios Custom Checks e o
    seu próprio histórico. Permite teres vários clientes/instâncias
    configurados na mesma instalação sem misturar dados entre eles."""

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, default="Principal")
    created_at = db.Column(
        db.DateTime, default=datetime.datetime.utcnow, nullable=False
    )
    # Só um perfil de cada vez pode ser o "principal para histórico" — é o
    # único de onde o scheduler em segundo plano vai gravando snapshots
    # periódicos, para não estar a bater em vários SQL Servers ao mesmo
    # tempo nem a acumular histórico (e espaço em disco) de todos.
    is_snapshot_primary = db.Column(db.Boolean, default=False, nullable=False)

    # Notificações por email — independentes do perfil ser ou não o
    # "principal para histórico". Cada perfil decide para si próprio se
    # quer avisos e para que email, mas todos usam o mesmo servidor de
    # envio (SMTP), configurado uma única vez em AppSetting.
    notify_enabled = db.Column(db.Boolean, default=False, nullable=False)
    notify_email = db.Column(db.String(255))
    # Estado do último check (True = havia algo mau) — usado só para saber
    # se algo "passou a mau" agora (e por isso vale a pena enviar email) ou
    # se já estava mau e por isso não vale repetir o aviso.
    notify_last_state = db.Column(db.Boolean, default=False, nullable=False)


class AppSetting(db.Model):
    """Configuração global da app (não pertence a nenhum perfil em
    concreto) — para já, só os dados do servidor de email (SMTP) usado
    para enviar notificações. Existe sempre uma única linha (singleton),
    criada automaticamente na primeira vez que é precisa — ver
    app.notifications.get_app_settings()."""

    id = db.Column(db.Integer, primary_key=True)
    smtp_host = db.Column(db.String(255))
    smtp_port = db.Column(db.Integer, default=587)
    smtp_username = db.Column(db.String(255))
    smtp_password_encrypted = db.Column(db.String(500))
    smtp_use_tls = db.Column(db.Boolean, default=True)
    smtp_from_address = db.Column(db.String(255))

    @property
    def smtp_password(self):
        return (
            decrypt(self.smtp_password_encrypted)
            if self.smtp_password_encrypted
            else ""
        )

    @smtp_password.setter
    def smtp_password(self, raw_password):
        self.smtp_password_encrypted = encrypt(raw_password) if raw_password else ""

    @property
    def is_configured(self):
        return bool(self.smtp_host and self.smtp_from_address)


class SqlConnection(db.Model):
    """Dados de ligação à instância SQL Server de UM perfil (ver Profile)."""

    id = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(db.Integer, db.ForeignKey("profile.id"), nullable=True)
    name = db.Column(db.String(120), default="Instância principal")
    server = db.Column(db.String(255), nullable=False)
    port = db.Column(db.Integer, default=1433)
    auth_type = db.Column(db.String(20), default="sql")  # "sql" or "windows"
    username = db.Column(db.String(255))
    password_encrypted = db.Column(db.String(500))
    default_database = db.Column(db.String(255), default="master")
    driver = db.Column(db.String(120), default="ODBC Driver 17 for SQL Server")
    trust_server_certificate = db.Column(db.Boolean, default=True)

    # Limiares configuráveis pela interface (Definições), usados para decidir
    # quando algo é sinalizado como "pendurado"/"longo"/"desatualizado".
    job_stuck_minutes = db.Column(db.Integer, default=60)
    query_long_seconds = db.Column(db.Integer, default=30)
    disk_low_pct = db.Column(db.Integer, default=15)
    backup_stale_days = db.Column(db.Integer, default=7)
    snapshot_interval_minutes = db.Column(db.Integer, default=15)

    @property
    def password(self):
        return decrypt(self.password_encrypted) if self.password_encrypted else ""

    @password.setter
    def password(self, raw_password):
        self.password_encrypted = encrypt(raw_password) if raw_password else ""


class CustomCheck(db.Model):
    """User-defined queries to monitor specific processes/tables
    (e.g. count of rows where tratado = 0). Pertence sempre a um perfil."""

    id = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(db.Integer, db.ForeignKey("profile.id"), nullable=True)
    name = db.Column(db.String(255), nullable=False)
    database_name = db.Column(db.String(255), nullable=False)
    # NOTA: chama-se "sql_query" e não "query" de propósito — uma coluna
    # chamada "query" colidiria com o atributo especial Model.query que o
    # Flask-SQLAlchemy usa para pesquisas (CustomCheck.query.filter_by(...)).
    sql_query = db.Column(db.Text, nullable=False)
    description = db.Column(db.String(500))
    warn_threshold = db.Column(db.Integer, nullable=True)
    # Como comparar o resultado (só faz sentido quando a query devolve um
    # único valor, ex: um COUNT(*)) com o warn_threshold para decidir alerta.
    comparison = db.Column(db.String(5), default="gt")  # gt, gte, lt, lte, eq
    active = db.Column(db.Boolean, default=True)

    def is_breached(self, value):
        if self.warn_threshold is None or value is None:
            return False
        try:
            value = float(value)
        except (TypeError, ValueError):
            return False
        ops = {
            "gt": value > self.warn_threshold,
            "gte": value >= self.warn_threshold,
            "lt": value < self.warn_threshold,
            "lte": value <= self.warn_threshold,
            "eq": value == self.warn_threshold,
        }
        return ops.get(self.comparison, False)


class MetricSnapshot(db.Model):
    """Fotografia periódica das métricas principais, para se poder ver a
    evolução ao longo do tempo (a app corre em segundo plano e vai gravando).
    Só é gravado para o perfil marcado como "principal para histórico"."""

    id = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(db.Integer, db.ForeignKey("profile.id"), nullable=True)
    taken_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)
    jobs_failed = db.Column(db.Integer, default=0)
    jobs_stuck = db.Column(db.Integer, default=0)
    sessions_blocked = db.Column(db.Integer, default=0)
    queries_long_running = db.Column(db.Integer, default=0)
    backups_stale = db.Column(db.Integer, default=0)
    disk_low = db.Column(db.Integer, default=0)
    custom_checks_breached = db.Column(db.Integer, default=0)
    had_error = db.Column(db.Boolean, default=False)
