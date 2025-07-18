import os
import json
import re
import datetime
import dateparser
import logging

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import ContextTypes

from google_calendar import create_event

DADOS_FILE = "dados.json"

logger = logging.getLogger(__name__)


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
        [InlineKeyboardButton("📈 Criar Meta", callback_data="menu_meta")],
        [InlineKeyboardButton("⏰ Agendar Tarefa", callback_data="menu_schedule")],
        [InlineKeyboardButton("📋 Minhas Metas", callback_data="menu_list_metas")],
        [InlineKeyboardButton("📝 Minhas Tarefas", callback_data="menu_list_tasks")],
    ]
    markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🔹 Bem-vindo à Rotina! Escolha uma opção:",
        reply_markup=markup
    )
    logger.info(f"Usuário {update.effective_user.id} abriu o menu /rotina.")


# 2) Trata clique no menu
async def rotina_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    cmd = query.data
    user_id = str(query.message.chat_id)
    db = load_data()
    user = db.setdefault(user_id, {})
    logger.info(f"Usuário {user_id} clicou em {cmd}.")

    # Criar Meta
    if cmd == "menu_meta":
        context.user_data["expecting"] = "meta"
        await query.edit_message_text(
            "✏️ Digite a descrição da meta semanal que deseja criar:"
        )
        return

    # Agendar Tarefa
    if cmd == "menu_schedule":
        # Muda para um novo estado para aguardar a data/hora
        context.user_data["expecting"] = "schedule_datetime"
        await query.edit_message_text(
            "✏️ Em que dia e horário quer agendar? (ex: Amanhã 14h, 20/07 15h)"
        )
        return

    # Listar Metas
    if cmd == "menu_list_metas":
        metas = user.get("metas", [])
        if metas:
            texto = "📈 Suas Metas Semanais:\n" + "\n".join(
                f"- {m['activity']}" for m in metas
            )
        else:
            texto = "📈 Você ainda não tem metas cadastradas."
        await query.edit_message_text(texto)
        return

    # Listar Tarefas
    if cmd == "menu_list_tasks":
        tarefas = user.get("tarefas", [])
        if tarefas:
            texto = "📝 Suas Tarefas Agendadas:\n" + "\n".join(
                f"- {t['activity']} em {t['when']}" for t in tarefas
            )
        else:
            texto = "📝 Você ainda não tem tarefas agendadas."
        await query.edit_message_text(texto)
        return


# 3) Trata texto livre após menu
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()
    state = context.user_data.get("expecting")
    chat_id = str(update.message.chat_id)
    db = load_data()
    user = db.setdefault(chat_id, {})
    logger.info(f"Usuário {chat_id} enviou texto: '{text}' no estado '{state}'.")

    # 3.1) Criando META
    if state == "meta":
        atividade = text
        metas = user.setdefault("metas", [])
        metas.append({"activity": atividade, "progress": 0, "target": None})
        save_data(db)
        await update.message.reply_text(
            f"✅ Meta “{atividade}” salva com sucesso!"
        )
        context.user_data.pop("expecting", None)
        logger.info(f"Meta '{atividade}' salva para o usuário {chat_id}.")
        return

    # 3.2) Capturando APENAS a data e hora para agendamento
    if state == "schedule_datetime":
        logger.info(f"Tentando parsear data/hora: '{text}'")
        try:
            dt = dateparser.parse(
                text,
                settings={
                    "PREFER_DATES_FROM": "future",
                    "TIMEZONE": "America/Sao_Paulo",
                    "RETURN_AS_TIMEZONE_AWARE": False,
                    "RELATIVE_BASE": datetime.datetime.now(),
                },
            )
            logger.info(f"dateparser.parse retornou: {dt} para o texto '{text}'")

            if not dt or not isinstance(dt, datetime.datetime):
                logger.warning(f"Data/hora não entendida para '{text}'. dt: {dt}")
                await update.message.reply_text(
                    "❌ Não entendi *apenas* o dia e horário. Tente algo como:\n"
                    "- Amanhã às 14h\n"
                    "- 20/07 15h\n"
                    "- Terça 10h"
                )
                # Permanece no estado 'schedule_datetime' para nova tentativa
                return

            # Se a data/hora for válida, guarda no user_data e pede a descrição
            context.user_data["temp_datetime"] = dt.isoformat() # Salva como string ISO
            context.user_data["expecting"] = "schedule_description"
            await update.message.reply_text(
                f"Certo, agendado para *{dt.strftime('%d/%m/%Y às %H:%M')}*.\n"
                "Agora, qual a **descrição** da tarefa?"
            )
            logger.info(f"Data/hora '{dt}' capturada. Pedindo descrição da tarefa.")
            return

        except Exception as e:
            logger.error(f"Erro ao parsear data/hora '{text}': {e}", exc_info=True)
            await update.message.reply_text(f"❌ Ocorreu um erro ao processar a data/hora: {e}")
            context.user_data.pop("expecting", None) # Sai do estado para evitar loop
            return

    # 3.3) Capturando a descrição da tarefa
    if state == "schedule_description":
        logger.info(f"Recebeu descrição da tarefa: '{text}'")
        temp_dt_str = context.user_data.get("temp_datetime")
        if not temp_dt_str:
            logger.error("Erro: temp_datetime não encontrado ao tentar agendar descrição.")
            await update.message.reply_text("❌ Ops, algo deu errado. Por favor, tente agendar novamente desde o início.")
            context.user_data.pop("expecting", None)
            return

        # Converte a string ISO de volta para datetime
        start_dt = datetime.datetime.fromisoformat(temp_dt_str)
        end_dt = start_dt + datetime.timedelta(hours=1) # Duração padrão de 1 hora

        try:
            # Agenda no Google Calendar
            srv = context.bot_data["calendar_service"]
            cal = context.bot_data["calendar_id"]
            logger.info(f"Chamando create_event para '{text}' em '{start_dt}' no calendar '{cal}'")
            create_event(srv, cal, text, start_dt, end_dt)
            logger.info("create_event concluído com sucesso.")

            # Persiste no JSON
            tarefas = user.setdefault("tarefas", [])
            tarefas.append({
                "activity": text,
                "done": False,
                "when": start_dt.strftime("%Y-%m-%dT%H:%M:%S")
            })
            save_data(db)
            logger.info(f"Tarefa '{text}' salva no DADOS_FILE para o usuário {chat_id}.")

            await update.message.reply_text(
                f"📅 Tarefa “{text}” agendada para "
                f"{start_dt:%d/%m} às {start_dt:%H:%M}!"
            )
            context.user_data.pop("expecting", None) # Finaliza o estado
            context.user_data.pop("temp_datetime", None) # Limpa a data temporária
            logger.info(f"Mensagem de sucesso de agendamento enviada para o usuário {chat_id}.")
            return

        except Exception as e:
            logger.error(f"Erro ao agendar tarefa final para '{text}': {e}", exc_info=True)
            await update.message.reply_text(
                f"❌ Ocorreu um erro ao agendar a tarefa. Por favor, tente novamente mais tarde. Erro: {e}"
            )
            context.user_data.pop("expecting", None)
            context.user_data.pop("temp_datetime", None) # Limpa mesmo com erro
            return

    # 3.4) Fallback quando ninguém está aguardando texto
    logger.info(f"Texto '{text}' recebido sem estado 'expecting'.")
    await update.message.reply_text(
        "👉 Use /rotina para abrir o menu e escolher uma opção."
    )


# 4) Marcar tarefa como concluída
async def mark_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    chat_id = str(query.message.chat_id)
    db = load_data()
    tarefas = db.setdefault(chat_id, {}).setdefault("tarefas", [])

    idx = int(query.data.split("_")[1])
    logger.info(f"Usuário {chat_id} tentou marcar tarefa {idx} como concluída.")
    if 0 <= idx < len(tarefas):
        tarefas[idx]["done"] = True
        save_data(db)
        await query.edit_message_text(
            f"✅ Tarefa “{tarefas[idx]['activity']}” marcada como concluída!"
        )
        logger.info(f"Tarefa '{tarefas[idx]['activity']}' marcada como concluída para o usuário {chat_id}.")
    else:
        await query.edit_message_text("❌ Índice inválido.")
        logger.warning(f"Tentativa de marcar tarefa com índice inválido {idx} para o usuário {chat_id}.")
