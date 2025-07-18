import os
import json
import re
import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import ContextTypes

from google_calendar import create_event

DADOS_FILE = "dados.json"

def load_data():
    if not os.path.exists(DADOS_FILE):
        return {}
    with open(DADOS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DADOS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# 1) Exibe menu principal
async def rotina(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("📈 Criar Meta",      callback_data="menu_meta")],
        [InlineKeyboardButton("⏰ Agendar Tarefa", callback_data="menu_schedule")],
        [InlineKeyboardButton("📋 Minhas Metas",   callback_data="menu_list_metas")],
        [InlineKeyboardButton("📝 Minhas Tarefas", callback_data="menu_list_tasks")],
    ]
    markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🔹 Bem-vindo à Rotina! Escolha uma opção:", reply_markup=markup)


# 2) Trata clique no menu
async def rotina_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    cmd = query.data  # ex: 'menu_meta'
    user_id = str(query.message.chat_id)
    db = load_data()
    user = db.setdefault(user_id, {})

    # Criar Meta
    if cmd == "menu_meta":
        context.user_data["expecting"] = "meta"
        await query.edit_message_text("✏️ Digite a descrição da meta semanal que deseja criar:")

    # Agendar Tarefa
    elif cmd == "menu_schedule":
        context.user_data["expecting"] = "schedule"
        await query.edit_message_text("✏️ Em que dia e horário quer agendar? (ex: Amanhã 14h)")

    # Listar Metas
    elif cmd == "menu_list_metas":
        metas = user.get("metas", [])
        if metas:
            texto = "📈 Suas Metas Semanais:\n" + "\n".join(f"- {m['activity']}" for m in metas)
        else:
            texto = "📈 Você ainda não tem metas cadastradas."
        await query.edit_message_text(texto)

    # Listar Tarefas
    elif cmd == "menu_list_tasks":
        tarefas = user.get("tarefas", [])
        if tarefas:
            texto = "📝 Suas Tarefas Agendadas:\n" + "\n".join(
                f"- {t['activity']} em {t['when']}" for t in tarefas
            )
        else:
            texto = "📝 Você ainda não tem tarefas agendadas."
        await query.edit_message_text(texto)


# 3) Trata texto livre após menu
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()
    state = context.user_data.get("expecting")
    chat_id = str(update.message.chat_id)
    db = load_data()
    user = db.setdefault(chat_id, {})

    # 3.1) Criando META
    if state == "meta":
        atividade = text
        metas = user.setdefault("metas", [])
        metas.append({"activity": atividade, "progress": 0, "target": None})
        save_data(db)
        await update.message.reply_text(f"✅ Meta “{atividade}” salva com sucesso!")
        context.user_data.pop("expecting", None)
        return

    # 3.2) Criando AGENDAMENTO
    if state == "schedule":
        m_day  = "amanhã" if "amanhã" in text.lower() else "hoje" if "hoje" in text.lower() else None
        m_time = re.search(r"(\d{1,2})(?:h|:)?(\d{0,2})", text)
        if not m_day or not m_time:
            return await update.message.reply_text(
                "❌ Não entendi. Use algo como “Amanhã 14h” ou “Hoje 9:30”."
            )

        h = int(m_time.group(1))
        m = int(m_time.group(2) or 0)
        # calcula datas
        delta = 1 if m_day == "amanhã" else 0
        ev_date = datetime.date.today() + datetime.timedelta(days=delta)
        start_dt = datetime.datetime.combine(ev_date, datetime.time(h, m))
        end_dt   = start_dt + datetime.timedelta(hours=1)

        # agenda no Google Calendar
        srv = context.bot_data["calendar_service"]
        cal = context.bot_data["calendar_id"]
        create_event(srv, cal, text, start_dt, end_dt)

        # persiste como tarefa
        tarefas = user.setdefault("tarefas", [])
        tarefas.append({
            "activity": text,
            "done": False,
            "when": ev_date.strftime("%Y-%m-%dT%H:%M:%S")
        })
        save_data(db)

        await update.message.reply_text(
            f"📅 Tarefa “{text}” agendada para {ev_date:%d/%m} às {h:02d}:{m:02d}!"
        )
        context.user_data.pop("expecting", None)
        return

    # 3.3) Fallback quando ninguém está aguardando texto
    await update.message.reply_text(
        "👉 Use /rotina para abrir o menu e escolher uma opção."
    )
