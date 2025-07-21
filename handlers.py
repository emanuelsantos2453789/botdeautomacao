import logging
import datetime
import pytz
import uuid
import re
import json
import os
import asyncio
import aiofiles
from anyio import to_thread # Usar anyio.to_thread para compatibilidade mais ampla
from collections import defaultdict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, JobQueue
)

# --- Configurações Iniciais ---
# Configuração de Logs
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Fuso horário de São Paulo
SAO_PAULO_TZ = pytz.timezone('America/Sao_Paulo')

# Caminho do arquivo de dados
DATA_FILE = 'dados.json'

# Mapeamento para o status do Pomodoro por chat_id
pomodoro_status_map = {}
pomodoro_timers = defaultdict(lambda: {
    "focus": 25,
    "short_break": 5,
    "long_break": 15,
    "cycles": 4
})

# --- Funções de Persistência de Dados (ASSÍNCRONAS) ---
async def load_data():
    """Carrega os dados do arquivo JSON de forma assíncrona."""
    if not os.path.exists(DATA_FILE):
        logger.info(f"Arquivo de dados '{DATA_FILE}' não encontrado. Criando um novo.")
        return {}
    try:
        async with aiofiles.open(DATA_FILE, 'r', encoding='utf-8') as f:
            content = await f.read()
            if not content:
                logger.warning(f"Arquivo de dados '{DATA_FILE}' está vazio. Retornando dicionário vazio.")
                return {}
            # Executa json.loads em um thread separado para não bloquear o loop de eventos
            data = await to_thread.run_sync(json.loads, content)
            return data
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"Erro ao carregar dados do arquivo '{DATA_FILE}': {e}", exc_info=True)
        return {}

async def save_data(data):
    """Salva os dados no arquivo JSON de forma assíncrona."""
    try:
        async with aiofiles.open(DATA_FILE, 'w', encoding='utf-8') as f:
            # Executa json.dumps e f.write em um thread separado para não bloquear o loop de eventos
            await to_thread.run_sync(lambda: f.write(json.dumps(data, indent=4, ensure_ascii=False)))
    except Exception as e:
        logger.error(f"Erro ao salvar dados no arquivo '{DATA_FILE}': {e}", exc_info=True)

# --- Funções Auxiliares ---
def get_user_data(db, chat_id: str):
    """Retorna os dados do usuário, inicializando se não existirem."""
    return db.setdefault(chat_id, {"tarefas": [], "score": 0, "weekly_goals": [], "pomodoro_config": {}})

def cancel_task_jobs(chat_id: str, job_names: list, job_queue: JobQueue):
    """Cancela jobs agendados para uma tarefa específica."""
    for job_name in job_names:
        current_jobs = job_queue.get_jobs_by_name(job_name)
        for job in current_jobs:
            if job.chat_id == int(chat_id):
                job.schedule_removal()
                logger.info(f"Job '{job_name}' cancelado para o chat {chat_id}.")

# --- Funções de Manipulação de Tarefas ---
async def add_task_activity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Recebe a descrição da tarefa e pede a data/hora."""
    chat_id = str(update.effective_chat.id)
    activity = update.message.text.strip()

    if not activity:
        await update.message.reply_text("A descrição da tarefa não pode ser vazia. Por favor, digite a tarefa novamente.")
        return

    context.user_data["current_task"] = {"activity": activity}
    context.user_data["expecting"] = "add_task_datetime"

    keyboard = [[InlineKeyboardButton("⏰ Sem data/hora", callback_data="add_task_no_datetime")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"Ok, entendi: '{activity}'.\n\nQuando essa tarefa deve ser realizada? (Ex: 'hoje 14h', 'amanhã 10:30', '25/12 09:00', 'na próxima terça 18h', 'dia 20/07/2025 10:00')",
        reply_markup=reply_markup
    )
    logger.info(f"Usuário {chat_id} adicionou descrição da tarefa: '{activity}'.")

async def add_task_no_datetime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback para adicionar tarefa sem data/hora."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)

    task_data = context.user_data.get("current_task")
    if not task_data:
        await query.edit_message_text("Ops! Parece que não há uma tarefa em andamento. Comece novamente com /add_task.")
        return

    # Finaliza a adição da tarefa sem data/hora
    await finalize_add_task(update, context, None, None)
    logger.info(f"Usuário {chat_id} optou por adicionar tarefa sem data/hora.")

async def add_task_datetime_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processa a entrada de data/hora para a tarefa."""
    chat_id = str(update.effective_chat.id)
    datetime_str = update.message.text.strip().lower()
    task_data = context.user_data.get("current_task")

    if not task_data:
        await update.message.reply_text("Ops! Nenhuma tarefa em andamento. Use /add_task para começar.")
        return

    parsed_datetime = parse_datetime(datetime_str)

    if parsed_datetime:
        # Pede a duração
        context.user_data["current_task"]["start_when"] = parsed_datetime.isoformat()
        context.user_data["expecting"] = "add_task_duration"
        keyboard = [[InlineKeyboardButton("⏱️ Sem duração", callback_data="add_task_no_duration")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"Certo, agendado para *{parsed_datetime.strftime('%d/%m/%Y às %H:%M')}*.\n\n"
            "Essa tarefa tem uma duração específica? (Ex: '30min', '1h30', '2 horas'). Se não tiver, clique em 'Sem duração'.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        logger.info(f"Usuário {chat_id} definiu data/hora para a tarefa: '{datetime_str}'.")
    else:
        await update.message.reply_text(
            "Não consegui entender a data/hora. Por favor, tente um formato como 'hoje 14h', 'amanhã 10:30', '25/12 09:00', 'na próxima terça 18h'."
        )
        logger.warning(f"Usuário {chat_id} inseriu data/hora inválida: '{datetime_str}'.")

def parse_datetime(datetime_str: str) -> datetime.datetime | None:
    """Tenta parsear uma string de data/hora em um objeto datetime ciente do fuso horário."""
    now_aware = datetime.datetime.now(SAO_PAULO_TZ)
    today = now_aware.date()
    tomorrow = today + datetime.timedelta(days=1)

    # Formatos de data
    date_formats = {
        r"hoje": today,
        r"amanhã|amanha": tomorrow,
        r"depois de amanhã|depois de amanha": today + datetime.timedelta(days=2),
        r"domingo": today + datetime.timedelta(days=(6 - today.weekday() + 7) % 7),
        r"segunda-feira|segunda": today + datetime.timedelta(days=(0 - today.weekday() + 7) % 7),
        r"terça-feira|terca": today + datetime.timedelta(days=(1 - today.weekday() + 7) % 7),
        r"quarta-feira|quarta": today + datetime.timedelta(days=(2 - today.weekday() + 7) % 7),
        r"quinta-feira|quinta": today + datetime.timedelta(days=(3 - today.weekday() + 7) % 7),
        r"sexta-feira|sexta": today + datetime.timedelta(days=(4 - today.weekday() + 7) % 7),
        r"sábado|sabado": today + datetime.timedelta(days=(5 - today.weekday() + 7) % 7),
    }

    target_date = None
    # Prioriza datas específicas (dd/mm, dd/mm/yyyy)
    date_match = re.search(r'(\d{1,2})[/\.](\d{1,2})(?:[/\.](\d{2,4}))?', datetime_str)
    if date_match:
        day = int(date_match.group(1))
        month = int(date_match.group(2))
        year = int(date_match.group(3)) if date_match.group(3) else now_aware.year
        if len(str(year)) == 2: # Ex: 23 para 2023
            year += 2000 # Assume século 21
        try:
            target_date = datetime.date(year, month, day)
        except ValueError:
            return None

    # Tenta casar com nomes de dias da semana ou "hoje", "amanhã"
    if not target_date:
        for key, value in date_formats.items():
            if re.search(r'\b' + key + r'\b', datetime_str):
                target_date = value
                break

    if not target_date:
        target_date = today # Padrão para hoje se nenhuma data for especificada

    # Formatos de hora
    time_match = re.search(r'(\d{1,2})(?:[:h](\d{2}))?', datetime_str)
    target_time = None
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2)) if time_match.group(2) else 0
        try:
            target_time = datetime.time(hour, minute)
        except ValueError:
            return None

    if not target_time:
        target_time = datetime.time(9, 0) # Padrão para 9:00 se nenhuma hora for especificada

    combined_datetime = SAO_PAULO_TZ.localize(datetime.datetime.combine(target_date, target_time))

    # Se a data combinada for no passado (exceto para tasks sem hora exata, onde pode ser "hoje"),
    # tenta agendar para o mesmo dia/hora da semana seguinte se for um dia da semana.
    if combined_datetime <= now_aware and any(day in datetime_str for day in ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]):
        combined_datetime += datetime.timedelta(weeks=1)
    elif combined_datetime <= now_aware and "hoje" in datetime_str:
        # Se for "hoje" e a hora já passou, não tenta mudar para o dia seguinte, assume-se que é para o futuro.
        pass
    elif combined_datetime <= now_aware and "amanhã" not in datetime_str and "amanha" not in datetime_str:
        # Se for uma data/hora que já passou e não é "amanhã", pode ser para o ano que vem se for uma data específica.
        # Ou, se for apenas uma hora sem dia, tenta para o próximo dia.
        if not date_match and time_match and combined_datetime.date() == now_aware.date(): # Apenas hora
            combined_datetime = SAO_PAULO_TZ.localize(datetime.datetime.combine(tomorrow, target_time))
        elif date_match and combined_datetime.year == now_aware.year and combined_datetime <= now_aware:
             combined_datetime = SAO_PAULO_TZ.localize(datetime.datetime.combine(datetime.date(now_aware.year + 1, month, day), target_time))


    return combined_datetime

async def add_task_duration_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processa a entrada de duração para a tarefa."""
    chat_id = str(update.effective_chat.id)
    duration_str = update.message.text.strip().lower()
    task_data = context.user_data.get("current_task")

    if not task_data or "start_when" not in task_data:
        await update.message.reply_text("Ops! Nenhuma tarefa em andamento. Use /add_task para começar.")
        return

    duration_minutes = parse_duration(duration_str)

    if duration_minutes is not None:
        start_dt_aware = datetime.datetime.fromisoformat(task_data["start_when"]).astimezone(SAO_PAULO_TZ)
        end_dt_aware = start_dt_aware + datetime.timedelta(minutes=duration_minutes)
        await finalize_add_task(update, context, start_dt_aware.isoformat(), end_dt_aware.isoformat())
        logger.info(f"Usuário {chat_id} definiu duração para a tarefa: '{duration_str}'.")
    else:
        await update.message.reply_text(
            "Não consegui entender a duração. Por favor, tente um formato como '30min', '1h30', '2 horas'."
        )
        logger.warning(f"Usuário {chat_id} inseriu duração inválida: '{duration_str}'.")

async def add_task_no_duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback para adicionar tarefa sem duração."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)

    task_data = context.user_data.get("current_task")
    if not task_data or "start_when" not in task_data:
        await query.edit_message_text("Ops! Nenhuma tarefa em andamento. Comece novamente com /add_task.")
        return

    # Finaliza a adição da tarefa sem duração
    start_when = task_data["start_when"]
    await finalize_add_task(update, context, start_when, None)
    logger.info(f"Usuário {chat_id} optou por adicionar tarefa sem duração.")

def parse_duration(duration_str: str) -> int | None:
    """Tenta parsear uma string de duração em minutos."""
    total_minutes = 0

    # Horas (ex: 1h, 2 horas)
    hour_match = re.search(r'(\d+)\s*(?:h|horas?)', duration_str)
    if hour_match:
        total_minutes += int(hour_match.group(1)) * 60

    # Minutos (ex: 30min, 45 minutos)
    min_match = re.search(r'(\d+)\s*(?:min|minutos?)', duration_str)
    if min_match:
        total_minutes += int(min_match.group(1))

    return total_minutes if total_minutes > 0 else None

async def finalize_add_task(update: Update, context: ContextTypes.DEFAULT_TYPE, start_when: str | None, end_when: str | None):
    """Finaliza a adição de uma tarefa."""
    chat_id = str(update.effective_chat.id)
    db = await load_data() # await
    user_data = get_user_data(db, chat_id)
    tarefas = user_data.setdefault("tarefas", [])

    task_data = context.user_data.get("current_task")
    activity = task_data["activity"]

    new_task = {
        "id": str(uuid.uuid4()),
        "activity": activity,
        "done": False,
        "start_when": start_when,
        "end_when": end_when,
        "completion_status": None,
        "reason_not_completed": None,
        "recurring": False,
        "priority": "media", # Padrão para média, pode ser alterado depois
        "job_names": []
    }
    tarefas.append(new_task)
    await save_data(db) # await

    if new_task["start_when"]:
        await schedule_single_task_jobs(chat_id, new_task, None, context.job_queue) # Novo job para o ID
        message = (
            f"🎉 Tarefa *'{activity}'* agendada com sucesso! "
            f"Para *{datetime.datetime.fromisoformat(new_task['start_when']).astimezone(SAO_PAULO_TZ).strftime('%d/%m/%Y às %H:%M')}*."
        )
        if new_task["end_when"]:
            message += f" Término previsto para *{datetime.datetime.fromisoformat(new_task['end_when']).astimezone(SAO_PAULO_TZ).strftime('%H:%M')}*."
    else:
        message = f"🎉 Tarefa *'{activity}'* adicionada com sucesso! "

    message += "\n\nMenos uma coisa para se preocupar! 😉"

    if update.callback_query:
        await update.callback_query.edit_message_text(message, parse_mode='Markdown')
    else:
        await update.message.reply_text(message, parse_mode='Markdown')

    context.user_data.pop("current_task", None)
    context.user_data.pop("expecting", None)
    context.user_data.pop("pomodoro_setting_type", None) # Limpa se houver
    logger.info(f"Tarefa '{activity}' finalizada e salva para o usuário {chat_id}.")

async def add_task_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inicia o processo de adição de tarefa."""
    chat_id = str(update.effective_chat.id)
    context.user_data["expecting"] = "add_task_activity"
    await update.message.reply_text("📝 O que você precisa fazer? Digite a descrição da nova tarefa:")
    logger.info(f"Usuário {chat_id} iniciou o processo de adição de tarefa.")

async def mark_task_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Marca uma tarefa como concluída a partir de um callback (usando ID)."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)

    # Extrai o ID da tarefa do callback_data
    try:
        task_id = query.data.split("_id_")[1]
    except IndexError:
        logger.error(f"Erro ao parsear ID do callback_data: {query.data}")
        await query.edit_message_text("❌ Erro ao identificar a tarefa. Por favor, tente novamente!")
        return

    db = await load_data() # await
    user_data = get_user_data(db, chat_id)
    tarefas = user_data.setdefault("tarefas", [])

    found_task = None
    for task in tarefas:
        if task.get("id") == task_id:
            found_task = task
            break

    if found_task:
        if not found_task.get("done"):
            found_task["done"] = True
            found_task["completion_status"] = "completed_manually"
            # Cancelar jobs relacionados a esta tarefa se ela for concluída
            cancel_task_jobs(chat_id, found_task.get("job_names", []), context.job_queue)

            user_data["score"] = user_data.get("score", 0) + 10 # Adiciona pontos por concluir
            await save_data(db) # await

            await query.edit_message_text(f"✅ Tarefa *'{found_task['activity']}'* marcada como concluída! Mais 10 pontos pra você! 🎉", parse_mode='Markdown')
            logger.info(f"Tarefa '{found_task['activity']}' (ID: {task_id}) marcada como concluída para o usuário {chat_id}.")
            await list_tasks(update, context) # Atualiza a lista de tarefas
        else:
            await query.edit_message_text("🤔 Essa tarefa já está marcada como concluída! 😉")
    else:
        await query.edit_message_text("🤔 Essa tarefa não existe mais ou o ID está incorreto. Tente listar suas tarefas novamente!", parse_mode='Markdown')
        logger.warning(f"Tentativa de marcar tarefa com ID inválido {task_id} para o usuário {chat_id}.")

async def feedback_yes_id_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processa o feedback 'sim, concluí' de uma tarefa (usando ID)."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)

    try:
        task_id = query.data.split("_id_")[1]
    except IndexError:
        logger.error(f"Erro ao parsear ID do callback_data para feedback YES: {query.data}")
        await query.edit_message_text("❌ Erro ao identificar a tarefa para feedback. Por favor, tente novamente!")
        return

    db = await load_data() # await
    user_data = get_user_data(db, chat_id)
    tarefas = user_data.setdefault("tarefas", [])

    found_task = None
    for task in tarefas:
        if task.get("id") == task_id:
            found_task = task
            break

    if found_task:
        if not found_task.get("done"):
            found_task["done"] = True
            found_task["completion_status"] = "completed_on_time"
            # Cancelar jobs relacionados a esta tarefa se ela for concluída
            cancel_task_jobs(chat_id, found_task.get("job_names", []), context.job_queue)

            user_data["score"] = user_data.get("score", 0) + 10
            await save_data(db) # await
            await query.edit_message_text(f"🎉 Ótimo! Tarefa *'{found_task['activity']}'* concluída! Parabéns! Você ganhou 10 pontos! 🌟", parse_mode='Markdown')
            logger.info(f"Feedback POSITIVO para tarefa '{found_task['activity']}' (ID: {task_id}) do usuário {chat_id}.")
        else:
            await query.edit_message_text("Essa tarefa já foi marcada como concluída! 😉")
    else:
        await query.edit_message_text("Essa tarefa não existe mais ou o ID está incorreto. Tente listar suas tarefas novamente!", parse_mode='Markdown')
        logger.warning(f"Tentativa de feedback POSITIVO para tarefa com ID inválido {task_id} para o usuário {chat_id}.")

async def feedback_no_id_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processa o feedback 'não concluí' de uma tarefa (usando ID)."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)

    try:
        task_id = query.data.split("_id_")[1]
    except IndexError:
        logger.error(f"Erro ao parsear ID do callback_data para feedback NO: {query.data}")
        await query.edit_message_text("❌ Erro ao identificar a tarefa para feedback. Por favor, tente novamente!")
        return

    db = await load_data() # await
    user_data = get_user_data(db, chat_id)
    tarefas = user_data.setdefault("tarefas", [])

    found_task = None
    for task in tarefas: