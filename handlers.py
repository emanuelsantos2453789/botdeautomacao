# handlers.py

import re
import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext

def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "👋 Olá! Eu sou seu Bot de Rotina. "
        "Conte o que você quer fazer (por exemplo: “Esta semana quero estudar Python”) "
        "e eu ajudo você a organizar! 🚀"
    )

def help_command(update: Update, context: CallbackContext):
    update.message.reply_text(
        "✨ Mande frases livres como:\n"
        "- “Amanhã correr 7h”\n"
        "- “Quero estudar Python 5 vezes”\n\n"
        "Eu vou sugerir metas, agendar na sua Agenda Google e acompanhar o progresso."
    )

def handle_text(calendar_service, calendar_id):
    """
    Retorna uma função que processa toda mensagem de texto.
    Detecta metas e agendamentos e propõe ações via botões.
    """
    def _inner(update: Update, context: CallbackContext):
        text = update.message.text.lower()

        # 1. Proposta de Meta (ex: “Quero estudar Python”)
        if any(kw in text for kw in ["quero", "vou", "desejo", "pretendo"]):
            verb_match = re.search(r"(estudar|correr)\s*(.*)", text)
            if verb_match:
                action = verb_match.group(1)
                target = verb_match.group(2).strip() or action
                context.user_data['proposed_meta'] = target

                buttons = [
                    [
                        InlineKeyboardButton("Sim", callback_data="meta_yes"),
                        InlineKeyboardButton("Não", callback_data="meta_no")
                    ]
                ]
                keyboard = InlineKeyboardMarkup(buttons)
                update.message.reply_text(
                    f"🐾 Que demais! Quer que eu salve “{target}” como meta semanal?",
                    reply_markup=keyboard
                )
                return

        # 2. Proposta de Agendamento (ex: “Amanhã correr 7h”)
        time_match = re.search(r"(\d{1,2})(?:h|:)?(\d{0,2})", text)
        day_keyword = "amanhã" if "amanhã" in text else "hoje" if "hoje" in text else None
        if day_keyword and time_match and any(v in text for v in ["correr", "estudar"]):
            hour = int(time_match.group(1))
            minute = int(time_match.group(2)) if time_match.group(2) else 0
            activity = context.user_data.get('proposed_meta', text)

            context.user_data['proposed_schedule'] = {
                "activity": activity,
                "day": day_keyword,
                "hour": hour,
                "minute": minute
            }

            buttons = [
                [
                    InlineKeyboardButton("Sim", callback_data="schedule_yes"),
                    InlineKeyboardButton("Não", callback_data="schedule_no")
                ]
            ]
            keyboard = InlineKeyboardMarkup(buttons)
            update.message.reply_text(
                f"⏰ Posso agendar “{activity}” {day_keyword} às {hour:02d}:{minute:02d}?",
                reply_markup=keyboard
            )
            return

        # 3. Fallback
        update.message.reply_text(
            "🤔 Desculpe, não entendi. Pode tentar escrever de outra forma?"
        )

    return _inner

def handle_callback(update: Update, context: CallbackContext):
    """
    Processa todas as interações via botões “Sim/Não”.
    Salva metas em user_data e cria eventos na Google Agenda.
    """
    query = update.callback_query
    data = query.data

    # Confirmação de Meta
    if data == "meta_yes":
        target = context.user_data.pop('proposed_meta', None)
        if target:
            metas = context.user_data.setdefault('metas', [])
            metas.append({"activity": target, "progress": 0, "target": None})
            query.edit_message_text(f"✅ Meta “{target}” salva com sucesso!")
    elif data == "meta_no":
        context.user_data.pop('proposed_meta', None)
        query.edit_message_text("👌 Beleza, sem meta então!")

    # Confirmação de Agendamento
    elif data == "schedule_yes":
        sched = context.user_data.pop('proposed_schedule', {})
        if sched:
            # calcula data de início e fim
            days_delta = 1 if sched['day'] == "amanhã" else 0
            event_date = datetime.date.today() + datetime.timedelta(days=days_delta)
            start_dt = datetime.datetime.combine(
                event_date,
                datetime.time(sched['hour'], sched['minute'])
            )
            end_dt = start_dt + datetime.timedelta(hours=1)

            # Cria evento usando o módulo google_calendar.py
            from google_calendar import create_event
            service = context.bot_data.get('calendar_service')
            cal_id = context.bot_data.get('calendar_id')
            create_event(service, cal_id, sched['activity'], start_dt, end_dt)

            query.edit_message_text(
                f"📅 Tarefa “{sched['activity']}” agendada para "
                f"{event_date.strftime('%d/%m')} às {sched['hour']:02d}:{sched['minute']:02d}!"
            )
    elif data == "schedule_no":
        context.user_data.pop('proposed_schedule', None)
        query.edit_message_text("👍 Tudo bem, sem agendamento!")

    # Importante: confirma que o callback foi processado
    query.answer()
