from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import uuid
import pytz

db = SQLAlchemy()

def get_brasilia_time():
    return datetime.now(pytz.timezone('America/Sao_Paulo'))

class BaseModel(db.Model):
    __abstract__ = True
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at = db.Column(db.DateTime, default=get_brasilia_time)
    updated_at = db.Column(db.DateTime, default=get_brasilia_time, onupdate=get_brasilia_time)

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class User(BaseModel):
    __tablename__ = 'users'
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    last_login = db.Column(db.DateTime)
    
    # Relacionamentos
    eventos = db.relationship('Evento', backref='user', lazy=True)
    metas = db.relationship('Meta', backref='user', lazy=True)
    pomodoros = db.relationship('Pomodoro', backref='user', lazy=True)
    rotinas = db.relationship('Rotina', backref='user', lazy=True)

class Evento(BaseModel):
    __tablename__ = 'eventos'
    titulo = db.Column(db.String(100), nullable=False)
    descricao = db.Column(db.Text)
    data_inicio = db.Column(db.DateTime, nullable=False)
    data_fim = db.Column(db.DateTime)
    local = db.Column(db.String(100))
    cor = db.Column(db.String(20), default='#3a87ad')  # Cor padrão azul
    notificar = db.Column(db.Boolean, default=True)
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)

    def duracao(self):
        return self.data_fim - self.data_inicio if self.data_fim else timedelta(0)

class Meta(BaseModel):
    __tablename__ = 'metas'
    titulo = db.Column(db.String(100), nullable=False)
    descricao = db.Column(db.Text)
    data_limite = db.Column(db.DateTime)
    concluida = db.Column(db.Boolean, default=False)
    prioridade = db.Column(db.Integer, default=1)  # 1 a 5
    progresso = db.Column(db.Integer, default=0)  # 0-100%
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)

    def atualizar_progresso(self, valor):
        self.progresso = max(0, min(100, valor))
        if self.progresso == 100:
            self.concluida = True

class Rotina(BaseModel):
    __tablename__ = 'rotinas'
    dia_semana = db.Column(db.Enum('segunda', 'terca', 'quarta', 'quinta', 'sexta', 'sabado', 'domingo'), nullable=False)
    hora = db.Column(db.Time, nullable=False)
    titulo = db.Column(db.String(100), nullable=False)
    descricao = db.Column(db.Text)
    ativo = db.Column(db.Boolean, default=True)
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)

    def proxima_ocorrencia(self):
        hoje = get_brasilia_time().date()
        dias_semana = ['segunda', 'terca', 'quarta', 'quinta', 'sexta', 'sabado', 'domingo']
        dia_index = dias_semana.index(self.dia_semana)
        delta_dias = (dia_index - hoje.weekday()) % 7
        if delta_dias == 0 and get_brasilia_time().time() > self.hora:
            delta_dias = 7
        return datetime.combine(hoje + timedelta(days=delta_dias), self.hora)

class Pomodoro(BaseModel):
    __tablename__ = 'pomodoros'
    tempo_foco = db.Column(db.Integer, default=25)  # em minutos
    tempo_pausa_curta = db.Column(db.Integer, default=5)
    tempo_pausa_longa = db.Column(db.Integer, default=15)
    ciclos_completos = db.Column(db.Integer, default=0)
    em_execucao = db.Column(db.Boolean, default=False)
    tempo_restante = db.Column(db.Integer)  # segundos restantes
    tipo = db.Column(db.Enum('foco', 'pausa_curta', 'pausa_longa'), default='foco')
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)

    def iniciar(self):
        self.em_execucao = True
        self.tempo_restante = self.tempo_foco * 60
        self.tipo = 'foco'

    def pausar(self):
        self.em_execucao = False

    def avancar_ciclo(self):
        if self.tipo == 'foco':
            self.ciclos_completos += 1
            if self.ciclos_completos % 4 == 0:
                self.tipo = 'pausa_longa'
                self.tempo_restante = self.tempo_pausa_longa * 60
            else:
                self.tipo = 'pausa_curta'
                self.tempo_restante = self.tempo_pausa_curta * 60
        else:
            self.tipo = 'foco'
            self.tempo_restante = self.tempo_foco * 60

# Função para inicializar o banco de dados
def init_app(app):
    db.init_app(app)
    with app.app_context():
        db.create_all()
        # Criar usuário admin padrão se não existir
        if not User.query.filter_by(username='admin').first():
            admin = User(
                id=str(uuid.uuid4()),
                username='admin',
                email='admin@example.com',
                password_hash=''  # Deve ser preenchido com hash real
            )
            db.session.add(admin)
            db.session.commit()
