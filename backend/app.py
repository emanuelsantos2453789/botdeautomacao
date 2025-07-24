# backend/app.py
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import os
import logging
import sys
from datetime import datetime
from .models import db, init_app as init_db, User, Evento, Meta, Rotina, Pomodoro
from .ws_manager import init_ws_events
import pytz

# Configuração avançada de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('app.log'),
        logging.handlers.RotatingFileHandler('app_debug.log', maxBytes=1000000, backupCount=5)
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='../frontend', static_url_path='/')

# Configurações de aplicação
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///app.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JSON_SORT_KEYS'] = False
app.config['ERROR_404_HELP'] = False
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') == 'production'
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Inicializações
CORS(app, resources={r"/api/*": {"origins": "*"}})
init_db(app)

# Importar após inicializar db para evitar circular imports
from flask_socketio import SocketIO
socketio = SocketIO(app, cors_allowed_origins="*", logger=True, engineio_logger=True)
init_ws_events(socketio, app)

# --- Middleware de Tratamento de Erros ---
@app.errorhandler(400)
def bad_request(e):
    logger.warning(f'Bad Request: {str(e)}')
    return jsonify({
        "error": "Requisição inválida",
        "message": str(e.description)
    }), 400

@app.errorhandler(401)
def unauthorized(e):
    logger.warning(f'Unauthorized: {str(e)}')
    return jsonify({
        "error": "Não autorizado",
        "message": "Autenticação necessária"
    }), 401

@app.errorhandler(404)
def not_found(e):
    logger.warning(f'Not Found: {str(e)}')
    return jsonify({
        "error": "Endpoint não encontrado",
        "message": "A rota solicitada não existe"
    }), 404

@app.errorhandler(405)
def method_not_allowed(e):
    logger.warning(f'Method Not Allowed: {str(e)}')
    return jsonify({
        "error": "Método não permitido",
        "message": "O método HTTP não é suportado neste endpoint"
    }), 405

@app.errorhandler(500)
def internal_error(e):
    logger.error(f'Internal Server Error: {str(e)}')
    return jsonify({
        "error": "Erro interno do servidor",
        "message": "Ocorreu um erro inesperado"
    }), 500

# Middleware de autenticação básica
@app.before_request
def authenticate_request():
    if request.path.startswith('/api/'):
        auth_token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not auth_token:
            return jsonify({"error": "Token de autenticação ausente"}), 401
        
        user = User.query.filter_by(id=auth_token).first()
        if not user:
            return jsonify({"error": "Token inválido"}), 401
        
        # Adiciona usuário ao contexto da requisição
        request.user = user

# --- Rotas Principais ---
@app.route('/')
def serve_index():
    return send_from_directory(app.static_folder, 'index.html')

# --- API Endpoints ---
@app.route('/api/health', methods=['GET'])
def health_check():
    db_status = "ok" if db.session.query(1).first() else "unavailable"
    return jsonify({
        "status": "online",
        "timestamp": datetime.now(pytz.timezone('America/Sao_Paulo')).isoformat(),
        "database": db_status,
        "services": ["agenda", "metas", "rotina", "pomodoro"]
    })

# --- Sistema de Agenda ---
@app.route('/api/agenda', methods=['GET'])
def listar_eventos():
    try:
        eventos = Evento.query.filter_by(user_id=request.user.id).all()
        return jsonify([e.to_dict() for e in eventos]), 200
    except Exception as e:
        logger.exception("Erro em listar_eventos")
        return jsonify({"error": "Falha ao listar eventos"}), 500

@app.route('/api/agenda', methods=['POST'])
def criar_evento():
    try:
        data = request.get_json()
        if not data or 'titulo' not in data or 'data_inicio' not in data:
            return jsonify({"error": "Campos obrigatórios faltando"}), 400
        
        novo_evento = Evento(
            titulo=data['titulo'],
            data_inicio=datetime.fromisoformat(data['data_inicio']),
            data_fim=datetime.fromisoformat(data['data_fim']) if data.get('data_fim') else None,
            descricao=data.get('descricao', ''),
            local=data.get('local', ''),
            user_id=request.user.id
        )
        
        db.session.add(novo_evento)
        db.session.commit()
        
        # Notificação via WebSocket
        socketio.emit('novo_evento', novo_evento.to_dict(), room=request.user.id)
        
        return jsonify(novo_evento.to_dict()), 201
    except ValueError as ve:
        return jsonify({"error": "Formato de data inválido", "details": str(ve)}), 400
    except Exception as e:
        db.session.rollback()
        logger.exception("Erro em criar_evento")
        return jsonify({"error": "Falha ao criar evento"}), 500

# --- Sistema de Metas ---
@app.route('/api/metas', methods=['GET'])
def listar_metas():
    try:
        metas = Meta.query.filter_by(user_id=request.user.id).all()
        return jsonify([m.to_dict() for m in metas]), 200
    except Exception as e:
        logger.exception("Erro em listar_metas")
        return jsonify({"error": "Falha ao listar metas"}), 500

@app.route('/api/metas', methods=['POST'])
def criar_meta():
    try:
        data = request.get_json()
        if not data or 'titulo' not in data:
            return jsonify({"error": "Título é obrigatório"}), 400
        
        nova_meta = Meta(
            titulo=data['titulo'],
            descricao=data.get('descricao', ''),
            data_limite=datetime.fromisoformat(data['data_limite']) if data.get('data_limite') else None,
            user_id=request.user.id
        )
        
        db.session.add(nova_meta)
        db.session.commit()
        
        return jsonify(nova_meta.to_dict()), 201
    except ValueError as ve:
        return jsonify({"error": "Formato de data inválido", "details": str(ve)}), 400
    except Exception as e:
        db.session.rollback()
        logger.exception("Erro em criar_meta")
        return jsonify({"error": "Falha ao criar meta"}), 500

@app.route('/api/metas/<string:meta_id>/progresso', methods=['PUT'])
def atualizar_progresso_meta(meta_id):
    try:
        data = request.get_json()
        meta = Meta.query.filter_by(id=meta_id, user_id=request.user.id).first()
        
        if not meta:
            return jsonify({"error": "Meta não encontrada"}), 404
        
        if 'progresso' not in data:
            return jsonify({"error": "Progresso é obrigatório"}), 400
            
        progresso = int(data['progresso'])
        if progresso < 0 or progresso > 100:
            return jsonify({"error": "Progresso deve ser entre 0 e 100"}), 400
            
        meta.atualizar_progresso(progresso)
        db.session.commit()
        
        return jsonify(meta.to_dict()), 200
    except Exception as e:
        db.session.rollback()
        logger.exception("Erro em atualizar_progresso_meta")
        return jsonify({"error": "Falha ao atualizar progresso"}), 500

# --- Sistema de Rotina Semanal ---
@app.route('/api/rotinas', methods=['GET'])
def listar_rotinas():
    try:
        rotinas = Rotina.query.filter_by(user_id=request.user.id).all()
        return jsonify([r.to_dict() for r in rotinas]), 200
    except Exception as e:
        logger.exception("Erro em listar_rotinas")
        return jsonify({"error": "Falha ao listar rotinas"}), 500

@app.route('/api/rotinas', methods=['POST'])
def criar_rotina():
    try:
        data = request.get_json()
        required_fields = ['dia_semana', 'hora', 'titulo']
        if not all(field in data for field in required_fields):
            return jsonify({"error": "Campos obrigatórios faltando"}), 400
        
        nova_rotina = Rotina(
            dia_semana=data['dia_semana'],
            hora=datetime.strptime(data['hora'], '%H:%M').time(),
            titulo=data['titulo'],
            descricao=data.get('descricao', ''),
            user_id=request.user.id
        )
        
        db.session.add(nova_rotina)
        db.session.commit()
        
        return jsonify(nova_rotina.to_dict()), 201
    except ValueError as ve:
        return jsonify({"error": "Formato de hora inválido", "details": str(ve)}), 400
    except Exception as e:
        db.session.rollback()
        logger.exception("Erro em criar_rotina")
        return jsonify({"error": "Falha ao criar rotina"}), 500

# --- Sistema Pomodoro ---
@app.route('/api/pomodoro', methods=['GET'])
def obter_pomodoro_ativo():
    try:
        pomodoro = Pomodoro.query.filter_by(
            user_id=request.user.id, 
            em_execucao=True
        ).first()
        
        if not pomodoro:
            return jsonify({"status": "inactive"}), 200
            
        return jsonify(pomodoro.to_dict()), 200
    except Exception as e:
        logger.exception("Erro em obter_pomodoro_ativo")
        return jsonify({"error": "Falha ao obter sessão Pomodoro"}), 500

@app.route('/api/pomodoro/start', methods=['POST'])
def iniciar_pomodoro():
    try:
        data = request.get_json()
        pomodoro = Pomodoro.query.filter_by(
            user_id=request.user.id, 
            em_execucao=True
        ).first()
        
        if pomodoro:
            return jsonify({
                "error": "Sessão já em andamento",
                "session": pomodoro.to_dict()
            }), 409
            
        novo_pomodoro = Pomodoro(
            tempo_foco=data.get('tempo_foco', 25),
            tempo_pausa_curta=data.get('tempo_pausa_curta', 5),
            tempo_pausa_longa=data.get('tempo_pausa_longa', 15),
            user_id=request.user.id
        )
        novo_pomodoro.iniciar()
        
        db.session.add(novo_pomodoro)
        db.session.commit()
        
        # Notificar via WebSocket
        socketio.emit('pomodoro_iniciado', novo_pomodoro.to_dict(), room=request.user.id)
        
        return jsonify(novo_pomodoro.to_dict()), 200
    except Exception as e:
        db.session.rollback()
        logger.exception("Erro em iniciar_pomodoro")
        return jsonify({"error": "Falha ao iniciar sessão Pomodoro"}), 500

@app.route('/api/pomodoro/<string:session_id>/pause', methods=['PUT'])
def pausar_pomodoro(session_id):
    try:
        pomodoro = Pomodoro.query.filter_by(
            id=session_id, 
            user_id=request.user.id
        ).first()
        
        if not pomodoro:
            return jsonify({"error": "Sessão não encontrada"}), 404
            
        pomodoro.pausar()
        db.session.commit()
        
        # Notificar via WebSocket
        socketio.emit('pomodoro_pausado', pomodoro.to_dict(), room=request.user.id)
        
        return jsonify(pomodoro.to_dict()), 200
    except Exception as e:
        db.session.rollback()
        logger.exception("Erro em pausar_pomodoro")
        return jsonify({"error": "Falha ao pausar sessão Pomodoro"}), 500

# --- Execução Principal ---
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    
    if os.environ.get('DATABASE_URL'):
        # Execução em produção
        socketio.run(
            app,
            host='0.0.0.0',
            port=port,
            debug=debug_mode,
            use_reloader=False
        )
    else:
        # Execução em desenvolvimento
        app.run(host='0.0.0.0', port=port, debug=debug_mode)
