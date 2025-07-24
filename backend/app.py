# backend/app.py
from flask import Flask, jsonify, request, send_from_directory
from flask_socketio import SocketIO
from flask_cors import CORS
import os
import logging
import sys
from datetime import datetime

# Configuração básica de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('app.log')
    ]
)

app = Flask(__name__, static_folder='../frontend', static_url_path='/')
CORS(app, resources={r"/api/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*", logger=True, engineio_logger=True)

# Configurações
app.config['JSON_SORT_KEYS'] = False
app.config['ERROR_404_HELP'] = False

# --- Middleware de Tratamento de Erros ---
@app.errorhandler(400)
def bad_request(e):
    return jsonify({
        "error": "Requisição inválida",
        "message": str(e.description)
    }), 400

@app.errorhandler(404)
def not_found(e):
    return jsonify({
        "error": "Endpoint não encontrado",
        "message": "A rota solicitada não existe"
    }), 404

@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({
        "error": "Método não permitido",
        "message": "O método HTTP não é suportado neste endpoint"
    }), 405

@app.errorhandler(500)
def internal_error(e):
    return jsonify({
        "error": "Erro interno do servidor",
        "message": "Ocorreu um erro inesperado"
    }), 500

# --- Rotas Principais ---
@app.route('/')
def serve_index():
    return send_from_directory(app.static_folder, 'index.html')

# --- API Endpoints ---
@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "online",
        "timestamp": datetime.utcnow().isoformat(),
        "services": ["agenda", "metas", "rotina", "pomodoro"]
    })

# --- Integração das Funcionalidades ---
# 1. Sistema de Agenda
@app.route('/api/agenda', methods=['POST'])
def criar_evento():
    try:
        data = request.get_json()
        # Validação básica
        if not data or 'titulo' not in data:
            raise ValueError("Dados inválidos para evento")
        
        # Lógica de criação de evento (simulado)
        novo_evento = {
            "id": "event_123",
            "titulo": data['titulo'],
            "status": "criado"
        }
        
        # Notificação via WebSocket
        socketio.emit('novo_evento', novo_evento)
        
        return jsonify(novo_evento), 201
    
    except Exception as e:
        logging.error(f"Erro em criar_evento: {str(e)}")
        return jsonify({"error": "Falha ao criar evento", "details": str(e)}), 400

# 2. Sistema de Metas
@app.route('/api/metas', methods=['POST'])
def criar_meta():
    try:
        # Implementação real virá aqui
        return jsonify({"status": "em desenvolvimento"}), 501
    except Exception as e:
        logging.exception("Erro em criar_meta")
        return jsonify({"error": "Falha no sistema de metas"}), 500

# 3. Rotina Semanal
@app.route('/api/rotinas', methods=['GET'])
def listar_rotinas():
    try:
        # Implementação real virá aqui
        return jsonify([]), 200
    except Exception as e:
        logging.error(f"Erro em listar_rotinas: {str(e)}")
        return jsonify({"error": "Falha ao carregar rotinas"}), 500

# 4. Pomodoro
@app.route('/api/pomodoro/start', methods=['POST'])
def iniciar_pomodoro():
    try:
        # Implementação real virá aqui
        return jsonify({"session_id": "pomodoro_123", "status": "active"}), 200
    except Exception as e:
        logging.error(f"Erro em iniciar_pomodoro: {str(e)}")
        return jsonify({"error": "Falha ao iniciar sessão"}), 500

# --- WebSocket Events ---
@socketio.on('connect')
def handle_connect():
    logging.info(f"Cliente conectado: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    logging.info(f"Cliente desconectado: {request.sid}")

# --- Execução Principal ---
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    socketio.run(
        app,
        host='0.0.0.0',
        port=port,
        debug=os.environ.get('FLASK_DEBUG', 'false').lower() == 'true',
        use_reloader=False
    )
