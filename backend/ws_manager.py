import time
from threading import Lock
from flask import request
from flask_socketio import SocketIO, emit, join_room, leave_room
from models import db, Evento, Pomodoro, User

# Variáveis globais
socketio = None
active_sessions = {}
active_timers = {}
thread_lock = Lock()

def init_ws_events(sio, app):
    global socketio
    socketio = sio

    @socketio.on('connect')
    def handle_connect():
        print(f'Cliente conectado: {request.sid}')

    @socketio.on('disconnect')
    def handle_disconnect():
        user_id = next((uid for uid, sid in active_sessions.items() if sid == request.sid), None)
        if user_id:
            active_sessions.pop(user_id, None)
        print(f'Cliente desconectado: {request.sid}')

    @socketio.on('authenticate')
    def handle_authentication(data):
        token = data.get('token')
        user = User.query.filter_by(id=token).first()
        if user:
            active_sessions[user.id] = request.sid
            join_room(user.id)
            emit('authenticated', {'user_id': user.id, 'username': user.username})
        else:
            emit('authentication_failed', {'message': 'Token inválido'})

    @socketio.on('join_user_room')
    def on_join_user_room(data):
        user_id = data.get('user_id')
        if user_id:
            join_room(user_id)
            emit('room_joined', {'room': user_id})

    @socketio.on('create_event')
    def handle_create_event(data):
        try:
            user_id = data['user_id']
            evento = Evento(
                titulo=data['titulo'],
                data_inicio=datetime.fromisoformat(data['data_inicio']),
                data_fim=datetime.fromisoformat(data['data_fim']) if data.get('data_fim') else None,
                user_id=user_id
            )
            db.session.add(evento)
            db.session.commit()
            
            # Notificar o usuário específico
            emit('event_created', evento.to_dict(), room=user_id)
        except Exception as e:
            emit('error', {'message': str(e)})

    @socketio.on('start_pomodoro')
    def handle_start_pomodoro(data):
        user_id = data['user_id']
        pomodoro = Pomodoro.query.filter_by(user_id=user_id, em_execucao=True).first()
        if not pomodoro:
            pomodoro = Pomodoro(
                tempo_foco=data.get('tempo_foco', 25),
                user_id=user_id
            )
            pomodoro.iniciar()
            db.session.add(pomodoro)
        else:
            pomodoro.iniciar()
        
        db.session.commit()
        emit('pomodoro_started', pomodoro.to_dict(), room=user_id)
        start_pomodoro_timer(app, user_id, pomodoro.id)

    @socketio.on('pause_pomodoro')
    def handle_pause_pomodoro(data):
        user_id = data['user_id']
        pomodoro = Pomodoro.query.filter_by(user_id=user_id, em_execucao=True).first()
        if pomodoro:
            pomodoro.pausar()
            db.session.commit()
            emit('pomodoro_paused', pomodoro.to_dict(), room=user_id)

# Sistema de temporizador em segundo plano
def start_pomodoro_timer(app, user_id, pomodoro_id):
    def pomodoro_timer():
        with app.app_context():
            while True:
                time.sleep(1)
                with thread_lock:
                    pomodoro = Pomodoro.query.get(pomodoro_id)
                    if not pomodoro or not pomodoro.em_execucao:
                        break
                    
                    pomodoro.tempo_restante -= 1
                    if pomodoro.tempo_restante <= 0:
                        pomodoro.avancar_ciclo()
                        if pomodoro.tipo == 'foco':
                            emit('pomodoro_cycle_complete', {
                                'cycles': pomodoro.ciclos_completos
                            }, room=user_id)
                    
                    db.session.commit()
                    emit('pomodoro_update', {
                        'tempo_restante': pomodoro.tempo_restante,
                        'tipo': pomodoro.tipo,
                        'ciclos_completos': pomodoro.ciclos_completos
                    }, room=user_id)
    
    # Iniciar thread apenas se não existir uma para este pomodoro
    if pomodoro_id not in active_timers:
        active_timers[pomodoro_id] = True
        socketio.start_background_task(pomodoro_timer)

# Funções utilitárias
def notify_user(user_id, event, data):
    if user_id in active_sessions:
        emit(event, data, room=active_sessions[user_id])

def broadcast_event(event, data):
    emit(event, data, broadcast=True)
