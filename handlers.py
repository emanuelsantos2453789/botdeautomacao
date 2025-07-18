# handlers.py

import re
import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Olá! Eu sou seu Bot de Rotina. "
        "Conte o que você quer fazer (por exemplo: “Esta semana quero estudar Python”) "
        "e eu ajudo você a organizar! 🚀"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✨ Mande frases livres como:\n"
        "- “Amanhã correr 7h”\n"
        "- “Quero estudar Python 5 vezes”\n\n"
        "Eu vou sugerir metas, agendar na sua Agenda Google e acompanhar o progresso."
    )

def handle_text(calendar_service, calendar_id):
    """
    Retorna um handler async que processa toda mensagem de texto.
    """
    async def _inner(update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text.lower()

        # 1. Proposta de Meta
        if any(kw in text for kw in ["quero", "vou", "desejo", "pretendo"]):
            verb_match = re.search(r"(estudar|correr)\s*(.*)", text)
            if verb_match:
                action = verb_match.group(1)
                target = verb_match.group(2).strip() or action
                context.user_data['proposed_meta'] = target

                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("Sim", callback_data="meta_yes"),
                    InlineKeyboardButton("Não", callback_data="meta_no")
                ]])
                await update.message.reply_text(
                    f"🐾 Que demais! Quer que eu salve “{target}” como meta semanal?",
                    reply_markup=keyboard
                )
                return

        # 2. Proposta de Agendamento
        time_match = re.search(r"(\d{1,2})(?:h|:)?(\d{0,2})", text)
        day_keyword = "amanhã" if "amanhã" in text else "hoje" if "hoje" in text else None
        if day_keyword and time_match and any(v in text for v in ["correr", "estudar"]):
            hour = int(time_match.group(1))
            minute = int(time_match.group(2) or 0)
            activity = context.user_data.get('proposed_meta', text)

            context.user_data['proposed_schedule'] = {
                "activity": activity,
                "day": day_keyword,
                "hour": hour,
                "minute": minute
            }

            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("Sim", callback_data="schedule_yes"),
                InlineKeyboardButton("Não", callback_data="schedule_no")
            ]])
            await update.message.reply_text(
                f"⏰ Posso agendar “{activity}” {day_keyword} às {hour:02d}:{minute:02d}?",
                reply_markup=keyboard
            )
            return

        # 3. Fallback
        await update.message.reply_text(
            "🤔 Desculpe, não entendi. Pode tentar escrever de outra forma?"
        )

    return _inner

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    # Meta?
    if data == "meta_yes":
        target = context.user_data.pop('proposed_meta', None)
        if target:
            metas = context.user_data.setdefault('metas', [])
            metas.append({"activity": target, "progress": 0, "target": None})
            await query.edit_message_text(f"✅ Meta “{target}” salva com sucesso!")
        else:
            await query.edit_message_text("❌ Ops, nada para salvar.")

    elif data == "meta_no":
        context.user_data.pop('proposed_meta', None)
        await query.edit_message_text("👌 Beleza, sem meta então!")

    # Agendamento?
    elif data == "schedule_yes":
        sched = context.user_data.pop('proposed_schedule', {})
        if sched:
            # calcula datas
            delta = 1 if sched['day']=="amanhã" else 0
            event_date = datetime.date.today() + datetime.timedelta(days=delta)
            start_dt = datetime.datetime.combine(event_date, datetime.time(sched['hour'], sched['minute']))
            end_dt   = start_dt + datetime.timedelta(hours=1)

            from google_calendar import create_event
            service = context.bot_data['calendar_service']
            cal_id  = context.bot_data['calendar_id']
            create_event(service, cal_id, sched['activity'], start_dt, end_dt)

            text = (f"📅 Tarefa “{sched['activity']}” agendada para "
                    f"{event_date.strftime('%d/%m')} às {sched['hour']:02d}:{sched['minute']:02d}!")
            await query.edit_message_text(text)

    elif data == "schedule_no":
        context.user_data.pop('proposed_schedule', None)
        await query.edit_message_text("👍 Tudo bem, sem agendamento!")

    await query.answer()
