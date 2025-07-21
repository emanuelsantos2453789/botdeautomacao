import logging
import datetime
import pytz
import uuid
import re
import json
import os
import asyncio
import aiofiles
import traceback # ADICIONADO: Importar traceback
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
    db = await load_data() # await ADICIONADO AWAIT
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
    await save_data(db) # await ADICIONADO AWAIT

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

    db = await load_data() # await ADICIONADO AWAIT
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
            await save_data(db) # await ADICIONADO AWAIT

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

    db = await load_data() # await ADICIONADO AWAIT
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
            await save_data(db) # await ADICIONADO AWAIT
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

    db = await load_data() # await ADICIONADO AWAIT
    user_data = get_user_data(db, chat_id)
    tarefas = user_data.setdefault("tarefas", [])

    found_task = None
    for task in tarefas:
        if task.get("id") == task_id:
            found_task = task
            break

    if found_task:
        if not found_task.get("done"):
            found_task["done"] = False # Certifica que não está como done
            found_task["completion_status"] = "not_completed"
            # Não cancela o job se for recorrente, pois pode precisar no próximo ciclo
            # Apenas tarefas avulsas ou se o usuário explicitamente apagar
            await save_data(db) # await ADICIONADO AWAIT
            await query.edit_message_text(f"😔 Que pena! A tarefa *'{found_task['activity']}'* não foi concluída. Foco na próxima! 💪", parse_mode='Markdown')
            logger.info(f"Feedback NEGATIVO para tarefa '{found_task['activity']}' (ID: {task_id}) do usuário {chat_id}.")
        else:
            await query.edit_message_text("Essa tarefa já foi marcada como concluída! 😉")
    else:
        await query.edit_message_text("Essa tarefa não existe mais ou o ID está incorreto. Tente listar suas tarefas novamente!", parse_mode='Markdown')
        logger.warning(f"Tentativa de feedback NEGATIVO para tarefa com ID inválido {task_id} para o usuário {chat_id}.")

async def feedback_postpone_id_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processa o feedback 'adiar' de uma tarefa (usando ID)."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)

    try:
        task_id = query.data.split("_id_")[1]
    except IndexError:
        logger.error(f"Erro ao parsear ID do callback_data para feedback postpone: {query.data}")
        await query.edit_message_text("❌ Erro ao identificar a tarefa para feedback. Por favor, tente novamente!")
        return

    db = await load_data() # await ADICIONADO AWAIT
    user_data = get_user_data(db, chat_id)
    tarefas = user_data.setdefault("tarefas", [])

    found_task = None
    for task in tarefas:
        if task.get("id") == task_id:
            found_task = task
            break

    if found_task:
        if not found_task.get("done"):
            found_task["done"] = False
            found_task["completion_status"] = "postponed"
            # Adia a tarefa para o dia seguinte
            if found_task.get("start_when"):
                try:
                    original_start_dt = datetime.datetime.fromisoformat(found_task["start_when"]).astimezone(SAO_PAULO_TZ)
                    new_start_dt = original_start_dt + datetime.timedelta(days=1)
                    found_task["start_when"] = new_start_dt.isoformat()
                    if found_task.get("end_when"):
                        original_end_dt = datetime.datetime.fromisoformat(found_task["end_when"]).astimezone(SAO_PAULO_TZ)
                        new_end_dt = original_end_dt + datetime.timedelta(days=1)
                        found_task["end_when"] = new_end_dt.isoformat()

                    # Re-agenda os jobs para a nova data
                    cancel_task_jobs(chat_id, found_task.get("job_names", []), context.job_queue)
                    found_task["job_names"] = [] # Limpa antes de reagendar
                    await schedule_single_task_jobs(chat_id, found_task, None, context.job_queue)

                    await save_data(db) # await ADICIONADO AWAIT
                    await query.edit_message_text(f"↩️ Tarefa *'{found_task['activity']}'* adiada para amanhã. Vamos com tudo! 💪", parse_mode='Markdown')
                    logger.info(f"Tarefa '{found_task['activity']}' (ID: {task_id}) adiada para o usuário {chat_id}.")
                except (ValueError, TypeError) as e:
                    await query.edit_message_text("❌ Não foi possível adiar a tarefa devido a um erro na data. Verifique a data da tarefa.")
                    logger.error(f"Erro ao adiar tarefa {task_id}: {e}", exc_info=True)
            else:
                await query.edit_message_text("Essa tarefa não tem data/hora para ser adiada. Considere editar ou apagar.")
        else:
            await query.edit_message_text("Essa tarefa já foi marcada como concluída! 😉")
    else:
        await query.edit_message_text("Essa tarefa não existe mais ou o ID está incorreto. Tente listar suas tarefas novamente!", parse_mode='Markdown')
        logger.warning(f"Tentativa de feedback POSTPONE para tarefa com ID inválido {task_id} para o usuário {chat_id}.")

async def feedback_delete_id_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processa o feedback 'apagar' de uma tarefa (usando ID)."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)

    try:
        task_id = query.data.split("_id_")[1]
    except IndexError:
        logger.error(f"Erro ao parsear ID do callback_data para feedback DELETE: {query.data}")
        await query.edit_message_text("❌ Erro ao identificar a tarefa para feedback. Por favor, tente novamente!")
        return

    db = await load_data() # await ADICIONADO AWAIT
    user_data = get_user_data(db, chat_id)
    tarefas = user_data.setdefault("tarefas", [])

    deleted_task = None
    for idx, task in enumerate(tarefas):
        if task.get("id") == task_id:
            deleted_task = tarefas.pop(idx)
            break

    if deleted_task:
        cancel_task_jobs(chat_id, deleted_task.get("job_names", []), context.job_queue)

        await save_data(db) # await ADICIONADO AWAIT
        await query.edit_message_text(f"🗑️ Tarefa *'{deleted_task['activity']}'* apagada com sucesso! Menos uma preocupação! 😉", parse_mode='Markdown')
        logger.info(f"Tarefa '{deleted_task['activity']}' (ID: {task_id}) apagada para o usuário {chat_id}.")
    else:
        await query.edit_message_text("🤔 Essa tarefa não existe mais ou o ID está incorreto. Tente listar suas tarefas novamente!", parse_mode='Markdown')
        logger.warning(f"Tentativa de apagar tarefa com ID inválido {task_id} para o usuário {chat_id}.")
    return

# --- Funções de Feedback e Relatórios ---
async def send_daily_feedback(context: ContextTypes.DEFAULT_TYPE):
    """Envia o feedback diário ao usuário, incluindo tarefas e pontuação."""
    chat_id = str(context.job.chat_id)
    db = await load_data() # await ADICIONADO AWAIT
    user_data = get_user_data(db, chat_id)
    tarefas = user_data.setdefault("tarefas", [])

    now_aware = datetime.datetime.now(SAO_PAULO_TZ)
    today = now_aware.date()

    completed_tasks_today = []
    not_completed_tasks_today = []
    imprevistos_today = []
    tasks_to_ask_feedback = []

    daily_score_this_feedback = 0

    for idx, task in enumerate(tarefas):
        try:
            if task.get('start_when'):
                task_start_dt_naive = datetime.datetime.fromisoformat(task['start_when'])
                task_start_dt_aware = SAO_PAULO_TZ.localize(task_start_dt_naive)
                task_date = task_start_dt_aware.date()
            else:
                task_date = None
        except (ValueError, TypeError):
            logger.warning(f"Data de início inválida para a tarefa: {task.get('activity')}. Pulando no feedback diário.")
            task_date = None

        # Incluir tarefas sem data de início se não forem recorrentes e não concluídas,
        # para que possam ser questionadas, ou se forem para hoje
        if task_date == today or (task_date is None and not task.get('recurring')):
            if task.get('completion_status') in ['completed_on_time', 'completed_manually']:
                completed_tasks_today.append(task['activity'])
                daily_score_this_feedback += 10
            elif task.get('completion_status') in ['not_completed', 'not_completed_with_reason', 'postponed']:
                not_completed_tasks_today.append(task['activity'])
                if task.get('reason_not_completed'):
                    imprevistos_today.append(f"- *{task['activity']}*: {task['reason_not_completed']}")
            elif not task.get('done'):
                tasks_to_ask_feedback.append({'activity': task['activity'], 'id': task['id']}) # Passa o ID

    feedback_message = f"✨ Seu Feedback Diário ({today.strftime('%d/%m/%Y')}):\n\n"

    if completed_tasks_today:
        feedback_message += "✅ *Tarefas Concluídas HOJE*:\n" + "\n".join(f"• {t}" for t in completed_tasks_today) + "\n\n"
    else:
        feedback_message += "😔 Nenhuma tarefa concluída hoje ainda. Bora pra cima! Você consegue! 💪\n\n"

    if not_completed_tasks_today:
        feedback_message += "❌ *Tarefas Não Concluídas HOJE*:\n" + "\n".join(f"• {t}" for t in not_completed_tasks_today) + "\n\n"

    if imprevistos_today:
        feedback_message += "⚠️ *Imprevistos e Desafios de Hoje*:\n" + "\n".join(imprevistos_today) + "\n\n"

    feedback_message += f"📊 *Pontuação do Dia*: *{daily_score_this_feedback}* pontos\n"
    feedback_message += f"🏆 *Pontuação Total Acumulada*: *{user_data.get('score', 0)}* pontos\n\n"
    feedback_message += "Lembre-se: Cada esforço conta! Continue firme! Você é incrível! ✨"

    await context.bot.send_message(chat_id=chat_id, text=feedback_message, parse_mode='Markdown')
    logger.info(f"Feedback diário enviado para o usuário {chat_id}.")

    if tasks_to_ask_feedback:
        for task_info in tasks_to_ask_feedback:
            activity = task_info['activity']
            task_id = task_info['id'] # Pega o ID
            keyboard = [
                [InlineKeyboardButton("✅ Sim", callback_data=f"feedback_yes_id_{task_id}"), # Usa ID
                 InlineKeyboardButton("❌ Não", callback_data=f"feedback_no_id_{task_id}")], # Usa ID
                [InlineKeyboardButton("↩️ Adiar para amanhã", callback_data=f"feedback_postpone_id_{task_id}"), # Usa ID
                 InlineKeyboardButton("🗑️ Excluir", callback_data=f"feedback_delete_id_{task_id}")] # Usa ID
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🤔 A tarefa *'{activity}'* estava agendada para hoje. Você a realizou?",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            logger.info(f"Solicitando feedback para tarefa '{activity}' (ID {task_id}) para o usuário {chat_id}.")

async def send_weekly_feedback(context: ContextTypes.DEFAULT_TYPE):
    """Envia o feedback semanal consolidado ao usuário."""
    chat_id = str(context.job.chat_id)
    db = await load_data() # await ADICIONADO AWAIT
    user_data = get_user_data(db, chat_id)
    tarefas = user_data.setdefault("tarefas", [])
    weekly_goals = user_data.setdefault("weekly_goals", [])

    now_aware = datetime.datetime.now(SAO_PAULO_TZ)
    # Define o início e fim da semana (domingo a sábado)
    start_of_week = now_aware.date() - datetime.timedelta(days=(now_aware.weekday() + 1) % 7)
    end_of_week = start_of_week + datetime.timedelta(days=6)

    completed_tasks_week = []
    not_completed_tasks_week = []
    imprevistos_week = []
    completed_goals_week = []
    total_score_week = 0

    for task in tarefas:
        try:
            if task.get('start_when'):
                task_start_dt_naive = datetime.datetime.fromisoformat(task['start_when'])
                task_start_dt_aware = SAO_PAULO_TZ.localize(task_start_dt_naive)
                task_date = task_start_dt_aware.date()
            else:
                task_date = None
        except (ValueError, TypeError):
            logger.warning(f"Data de início inválida para a tarefa: {task.get('activity')}. Pulando no feedback semanal.")
            task_date = None

        if task_date and start_of_week <= task_date <= end_of_week:
            if task.get('completion_status') in ['completed_on_time', 'completed_manually']:
                completed_tasks_week.append(task['activity'])
                total_score_week += 10
            elif task.get('completion_status') in ['not_completed', 'not_completed_with_reason', 'postponed']:
                not_completed_tasks_week.append(task['activity'])
                if task.get('reason_not_completed'):
                    imprevistos_week.append(f"- *{task['activity']}*: {task['reason_not_completed']}")

    for goal in weekly_goals:
        if goal.get('done') and start_of_week <= datetime.datetime.fromisoformat(goal.get('date_added')).astimezone(SAO_PAULO_TZ).date() <= end_of_week:
            completed_goals_week.append(goal['goal_text'])
            total_score_week += 20 # Pontos extra por meta concluída

    feedback_message = f"🌟 *Seu Relatório Semanal ({start_of_week.strftime('%d/%m/%Y')} - {end_of_week.strftime('%d/%m/%Y')})* 🌟\n\n"

    feedback_message += "✅ *Tarefas Concluídas esta semana*:\n"
    if completed_tasks_week:
        feedback_message += "\n".join(f"• {t}" for t in completed_tasks_week) + "\n\n"
    else:
        feedback_message += "Nenhuma tarefa concluída esta semana. 😔\n\n"

    feedback_message += "🎯 *Metas Semanais Atingidas*:\n"
    if completed_goals_week:
        feedback_message += "\n".join(f"• {g}" for g in completed_goals_week) + "\n\n"
    else:
        feedback_message += "Nenhuma meta semanal atingida. 😔\n\n"

    feedback_message += "❌ *Tarefas Não Concluídas esta semana*:\n"
    if not_completed_tasks_week:
        feedback_message += "\n".join(f"• {t}" for t in not_completed_tasks_week) + "\n\n"
    else:
        feedback_message += "Todas as tarefas agendadas foram concluídas! 🎉\n\n"

    if imprevistos_week:
        feedback_message += "⚠️ *Principais Imprevistos/Desafios*:\n" + "\n".join(imprevistos_week) + "\n\n"

    feedback_message += f"📊 *Pontuação Semanal*: *{total_score_week}* pontos\n"
    feedback_message += f"🏆 *Pontuação Total Acumulada*: *{user_data.get('score', 0)}* pontos\n\n"
    feedback_message += (
        "Avalie sua semana: O que funcionou bem? O que pode ser melhorado?\n"
        "Use essas informações para planejar uma semana ainda mais produtiva! ✨"
    )

    await context.bot.send_message(chat_id=chat_id, text=feedback_message, parse_mode='Markdown')
    logger.info(f"Relatório semanal enviado para o usuário {chat_id}.")

async def show_reports_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mostra um menu para visualização de relatórios."""
    query = update.callback_query
    if query:
        await query.answer()

    keyboard = [
        [InlineKeyboardButton("📊 Relatório Diário", callback_data="get_daily_feedback")],
        [InlineKeyboardButton("📈 Relatório Semanal", callback_data="get_weekly_feedback")],
        [InlineKeyboardButton("↩️ Voltar ao Menu Principal", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message_text = "Selecione o tipo de relatório que você deseja visualizar:"

    if query:
        await query.edit_message_text(message_text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message_text, reply_markup=reply_markup)
    logger.info(f"Menu de relatórios exibido para o chat {update.effective_chat.id}.")

async def get_daily_feedback_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback para acionar o envio de feedback diário manualmente."""
    query = update.callback_query
    await query.answer("Gerando seu relatório diário...")
    context.job_queue.run_once(send_daily_feedback, when=0, chat_id=query.message.chat_id)
    await query.edit_message_text("Seu relatório diário será enviado em instantes!")
    logger.info(f"Solicitação de relatório diário manual para o chat {query.message.chat_id}.")

async def get_weekly_feedback_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback para acionar o envio de feedback semanal manualmente."""
    query = update.callback_query
    await query.answer("Gerando seu relatório semanal...")
    context.job_queue.run_once(send_weekly_feedback, when=0, chat_id=query.message.chat_id)
    await query.edit_message_text("Seu relatório semanal será enviado em instantes!")
    logger.info(f"Solicitação de relatório semanal manual para o chat {query.message.chat_id}.")

# --- Manipulação de Comandos e Menu Principal ---
async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exibe o menu principal do bot."""
    keyboard = [
        [InlineKeyboardButton("➕ Adicionar Tarefa", callback_data="add_new_task_menu")],
        [InlineKeyboardButton("✅ Listar/Concluir Tarefas", callback_data="list_tasks_menu")],
        [InlineKeyboardButton("⏰ Pomodoro", callback_data="menu_pomodoro")],
        [InlineKeyboardButton("🗓️ Rotina Semanal", callback_data="show_weekly_routine_command")],
        [InlineKeyboardButton("🎯 Metas Semanais", callback_data="view_weekly_goals_command")],
        [InlineKeyboardButton("📊 Relatórios", callback_data="show_reports_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message_text = "Olá! 👋 Eu sou seu assistente de produtividade. Escolha uma opção:"

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(message_text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message_text, reply_markup=reply_markup)
    logger.info(f"Menu principal exibido para o chat {update.effective_chat.id}.")

async def add_new_task_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mostra um menu para adicionar tarefa com ou sem data/hora."""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("📅 Adicionar com data/hora", callback_data="add_task_with_datetime")],
        [InlineKeyboardButton("📝 Adicionar sem data/hora", callback_data="add_task_no_datetime")],
        [InlineKeyboardButton("↩️ Voltar ao Menu Principal", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "Como você gostaria de adicionar a nova tarefa?",
        reply_markup=reply_markup
    )
    logger.info(f"Menu de adição de tarefa exibido para o chat {query.message.chat_id}.")

async def show_tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando para mostrar a lista de tarefas."""
    await list_tasks(update, context) # Chama a função principal de listagem
    logger.info(f"Comando /tasks executado no chat {update.effective_chat.id}.")

async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lista as tarefas do usuário com opções de ação."""
    chat_id = str(update.effective_chat.id)
    db = await load_data() # await ADICIONADO AWAIT
    user_data = get_user_data(db, chat_id)
    tarefas = user_data.setdefault("tarefas", [])

    now_aware = datetime.datetime.now(SAO_PAULO_TZ)

    # Filtrar tarefas pendentes e ordená-las
    pending_tasks = [task for task in tarefas if not task.get("done")]

    # Sort tasks: tasks with 'start_when' first, then by datetime, then by priority
    def sort_key(task):
        start_when = task.get("start_when")
        if start_when:
            try:
                dt_obj = datetime.datetime.fromisoformat(start_when).astimezone(SAO_PAULO_TZ)
                return (0, dt_obj, task.get("priority", "media")) # 0 indicates it has a datetime
            except ValueError:
                return (1, datetime.datetime.max.replace(tzinfo=SAO_PAULO_TZ), task.get("priority", "media")) # Invalid datetime, treat as no datetime
        else:
            return (1, datetime.datetime.max.replace(tzinfo=SAO_PAULO_TZ), task.get("priority", "media")) # 1 indicates no datetime

    pending_tasks.sort(key=sort_key)


    message_text = "📝 *Suas Tarefas Pendentes:*\n\n"
    if not pending_tasks:
        message_text += "🎉 Nenhuma tarefa pendente! Você está em dia! 👍\n\n"
    else:
        for i, task in enumerate(pending_tasks):
            activity = task["activity"]
            start_when_str = ""
            if task.get("start_when"):
                try:
                    start_dt = datetime.datetime.fromisoformat(task["start_when"]).astimezone(SAO_PAULO_TZ)
                    # Formato inteligente de data
                    if start_dt.date() == now_aware.date():
                        start_when_str = f" (hoje às {start_dt.strftime('%H:%M')})"
                    elif start_dt.date() == (now_aware + datetime.timedelta(days=1)).date():
                        start_when_str = f" (amanhã às {start_dt.strftime('%H:%M')})"
                    elif start_dt.year == now_aware.year:
                        start_when_str = f" ({start_dt.strftime('%d/%m às %H:%M')})"
                    else:
                        start_when_str = f" ({start_dt.strftime('%d/%m/%Y às %H:%M')})"
                except ValueError:
                    start_when_str = " (data inválida)"

            end_when_str = ""
            if task.get("end_when"):
                try:
                    end_dt = datetime.datetime.fromisoformat(task["end_when"]).astimezone(SAO_PAULO_TZ)
                    end_when_str = f" - {end_dt.strftime('%H:%M')}"
                except ValueError:
                    pass

            message_text += f"*{i+1}.* {activity}{start_when_str}{end_when_str}\n"
        message_text += "\n"

    keyboard = [
        [InlineKeyboardButton("✅ Marcar como Concluída", callback_data="select_task_to_mark_done")],
        [InlineKeyboardButton("🗑️ Apagar Tarefa", callback_data="select_task_to_delete")],
        [InlineKeyboardButton("➕ Adicionar Nova Tarefa", callback_data="add_new_task_menu")],
        [InlineKeyboardButton("↩️ Voltar ao Menu Principal", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')
    logger.info(f"Tarefas listadas para o chat {chat_id}.")

async def select_task_to_mark_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Apresenta a lista de tarefas para o usuário selecionar qual marcar como concluída."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)
    db = await load_data() # await ADICIONADO AWAIT
    user_data = get_user_data(db, chat_id)
    tarefas = user_data.setdefault("tarefas", [])

    pending_tasks = [task for task in tarefas if not task.get("done")]

    if not pending_tasks:
        await query.edit_message_text("🎉 Nenhuma tarefa pendente para marcar como concluída! 👍")
        return

    keyboard = []
    for i, task in enumerate(pending_tasks):
        keyboard.append([InlineKeyboardButton(f"{i+1}. {task['activity']}", callback_data=f"mark_done_id_{task['id']}")]) # Usa ID

    keyboard.append([InlineKeyboardButton("↩️ Voltar à Lista", callback_data="list_tasks_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text("Selecione a tarefa que você deseja marcar como concluída:", reply_markup=reply_markup)
    logger.info(f"Exibindo seleção de tarefa para marcar como concluída para o chat {chat_id}.")

async def select_task_to_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Apresenta a lista de tarefas para o usuário selecionar qual apagar."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)
    db = await load_data() # await ADICIONADO AWAIT
    user_data = get_user_data(db, chat_id)
    tarefas = user_data.setdefault("tarefas", [])

    pending_tasks = [task for task in tarefas if not task.get("done")]

    if not pending_tasks:
        await query.edit_message_text("🎉 Nenhuma tarefa pendente para apagar! 👍")
        return

    keyboard = []
    for i, task in enumerate(pending_tasks):
        keyboard.append([InlineKeyboardButton(f"{i+1}. {task['activity']}", callback_data=f"feedback_delete_id_{task['id']}")]) # Reusa o callback de delete

    keyboard.append([InlineKeyboardButton("↩️ Voltar à Lista", callback_data="list_tasks_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text("Selecione a tarefa que você deseja *apagar*:", reply_markup=reply_markup, parse_mode='Markdown')
    logger.info(f"Exibindo seleção de tarefa para apagar para o chat {chat_id}.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manipula mensagens de texto baseadas no estado atual do usuário."""
    chat_id = str(update.effective_chat.id)
    expected_input = context.user_data.get("expecting")

    if expected_input == "add_task_activity":
        await add_task_activity(update, context)
    elif expected_input == "add_task_datetime":
        await add_task_datetime_input(update, context)
    elif expected_input == "add_task_duration":
        await add_task_duration_input(update, context)
    elif expected_input == "set_pomodoro_time_focus":
        await set_pomodoro_time(update, context, "focus")
    elif expected_input == "set_pomodoro_time_short_break":
        await set_pomodoro_time(update, context, "short_break")
    elif expected_input == "set_pomodoro_time_long_break":
        await set_pomodoro_time(update, context, "long_break")
    elif expected_input == "set_pomodoro_time_cycles":
        await set_pomodoro_time(update, context, "cycles")
    elif expected_input == "set_weekly_goal":
        await process_set_weekly_goal(update, context)
    elif expected_input == "set_weekly_routine":
        await process_weekly_routine_input(update, context)
    else:
        await update.message.reply_text("Desculpe, não entendi. Use /start para ver as opções do menu principal.")
        logger.info(f"Mensagem não esperada de {chat_id}: '{update.message.text}'.")

# --- Funções de Agendamento ---
async def create_job(job_queue: JobQueue, name: str, run_datetime: datetime.datetime, chat_id: int, data: dict, job_func) -> str:
    """Cria e agenda um job único."""
    job = job_queue.run_once( # CORRIGIDO: era run_at, agora run_once
        callback=job_func,
        when=run_datetime, # VERIFICADO: deve ser datetime.datetime
        chat_id=chat_id,
        data=data,
        name=name
    )
    logger.info(f"Job '{name}' agendado para {run_datetime.strftime('%d/%m/%Y %H:%M:%S')} para o chat {chat_id}.")
    return name

async def schedule_single_task_jobs(chat_id: int, task: dict, feedback_message_id: int | None, job_queue: JobQueue) -> None:
    """Agenda os jobs para uma única tarefa (notificação e feedback)."""
    if task.get("start_when"):
        try:
            start_dt_iso = task["start_when"]
            start_dt_aware = datetime.datetime.fromisoformat(start_dt_iso).astimezone(SAO_PAULO_TZ)

            job_names = []

            # Job de notificação da tarefa (10 minutos antes)
            notification_time = start_dt_aware - datetime.timedelta(minutes=10)
            if notification_time > datetime.datetime.now(SAO_PAULO_TZ):
                notification_job_name = f"task_notification_{task['id']}"
                await create_job(job_queue, notification_job_name, notification_time, chat_id, {"task_id": task["id"], "activity": task["activity"]}, send_task_notification)
                job_names.append(notification_job_name)

            # Job de feedback (na hora da tarefa)
            if start_dt_aware > datetime.datetime.now(SAO_PAULO_TZ):
                feedback_job_name = f"task_feedback_{task['id']}"
                await create_job(job_queue, feedback_job_name, start_dt_aware, chat_id, {"task_id": task["id"], "activity": task["activity"]}, send_task_feedback)
                job_names.append(feedback_job_name)

            # Salva os nomes dos jobs na tarefa
            db = await load_data() # await ADICIONADO AWAIT
            user_data = get_user_data(db, str(chat_id))
            for t in user_data["tarefas"]:
                if t["id"] == task["id"]:
                    t["job_names"] = job_names
                    break
            await save_data(db) # await ADICIONADO AWAIT

        except (ValueError, TypeError) as e:
            logger.error(f"Erro ao agendar jobs para a tarefa {task.get('activity')} (ID: {task['id']}): {e}", exc_info=True)
            # Pode-se enviar uma mensagem ao usuário que houve um problema com o agendamento
    else:
        logger.info(f"Tarefa {task.get('activity')} (ID: {task['id']}) não tem data/hora de início, jobs não agendados.")

async def send_task_notification(context: ContextTypes.DEFAULT_TYPE):
    """Envia uma notificação sobre a tarefa iminente."""
    job_data = context.job.data
    task_id = job_data["task_id"]
    activity = job_data["activity"]
    chat_id = context.job.chat_id

    db = await load_data() # await ADICIONADO AWAIT
    user_data = get_user_data(db, str(chat_id))
    task = next((t for t in user_data["tarefas"] if t["id"] == task_id and not t["done"]), None)

    if task:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🔔 Lembrete: Sua tarefa *'{activity}'* começa em 10 minutos! Prepare-se para ser produtivo! 💪",
            parse_mode='Markdown'
        )
        logger.info(f"Notificação enviada para a tarefa '{activity}' (ID: {task_id}) para o chat {chat_id}.")
    else:
        logger.info(f"Notificação para tarefa {task_id} não enviada: Tarefa não encontrada ou já concluída.")

async def send_task_feedback(context: ContextTypes.DEFAULT_TYPE):
    """Envia um botão de feedback para a tarefa agendada."""
    job_data = context.job.data
    task_id = job_data["task_id"]
    activity = job_data["activity"]
    chat_id = context.job.chat_id

    db = await load_data() # await ADICIONADO AWAIT
    user_data = get_user_data(db, str(chat_id))
    task = next((t for t in user_data["tarefas"] if t["id"] == task_id and not t["done"]), None)

    if task:
        keyboard = [
            [InlineKeyboardButton("✅ Sim", callback_data=f"feedback_yes_id_{task_id}"),
             InlineKeyboardButton("❌ Não", callback_data=f"feedback_no_id_{task_id}")],
            [InlineKeyboardButton("↩️ Adiar para amanhã", callback_data=f"feedback_postpone_id_{task_id}"),
             InlineKeyboardButton("🗑️ Excluir", callback_data=f"feedback_delete_id_{task_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"✨ Hora de checar! Você realizou a tarefa *'{activity}'*?",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        logger.info(f"Feedback solicitado para a tarefa '{activity}' (ID: {task_id}) para o chat {chat_id}.")
    else:
        logger.info(f"Feedback para tarefa {task_id} não enviado: Tarefa não encontrada ou já concluída.")


# --- Funções do Pomodoro ---
async def pomodoro_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exibe o menu do Pomodoro."""
    chat_id = str(update.effective_chat.id)
    query = update.callback_query
    if query:
        await query.answer()

    db = await load_data() # await ADICIONADO AWAIT
    user_data = get_user_data(db, chat_id)
    config = user_data.setdefault("pomodoro_config", pomodoro_timers[chat_id])

    current_status = pomodoro_status_map.get(chat_id, {}).get("status", "stopped")
    current_time_left = pomodoro_status_map.get(chat_id, {}).get("time_left", 0)

    # Formata o tempo restante
    minutes, seconds = divmod(current_time_left, 60)
    time_display = f"{minutes:02d}:{seconds:02d}" if current_time_left > 0 else "00:00"

    message_text = (
        f"🍅 *Menu Pomodoro* 🍅\n\n"
        f"Status atual: *{current_status.capitalize()}*\n"
        f"Tempo restante: *{time_display}*\n\n"
        f"Configurações:\n"
        f"  Foco: *{config.get('focus', 25)} min*\n"
        f"  Pausa Curta: *{config.get('short_break', 5)} min*\n"
        f"  Pausa Longa: *{config.get('long_break', 15)} min*\n"
        f"  Ciclos: *{config.get('cycles', 4)}*\n\n"
    )

    keyboard_buttons = []
    if current_status == "stopped":
        keyboard_buttons.append([InlineKeyboardButton("▶️ Iniciar Pomodoro", callback_data="pomodoro_start")])
    elif current_status == "running":
        keyboard_buttons.append([InlineKeyboardButton("⏸️ Pausar Pomodoro", callback_data="pomodoro_pause")])
        keyboard_buttons.append([InlineKeyboardButton("⏹️ Parar Pomodoro", callback_data="pomodoro_stop_command")])
    elif current_status == "paused":
        keyboard_buttons.append([InlineKeyboardButton("▶️ Continuar Pomodoro", callback_data="pomodoro_resume")])
        keyboard_buttons.append([InlineKeyboardButton("⏹️ Parar Pomodoro", callback_data="pomodoro_stop_command")])
    elif current_status == "break":
        keyboard_buttons.append([InlineKeyboardButton("⏹️ Parar Pomodoro", callback_data="pomodoro_stop_command")])


    keyboard_buttons.extend([
        [InlineKeyboardButton("⚙️ Configurar Tempos", callback_data="pomodoro_config_times")],
        [InlineKeyboardButton("🔄 Status Atual", callback_data="pomodoro_status_command")],
        [InlineKeyboardButton("↩️ Voltar ao Menu Principal", callback_data="main_menu")]
    ])

    reply_markup = InlineKeyboardMarkup(keyboard_buttons)

    if query:
        await query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')
    logger.info(f"Menu Pomodoro exibido para o chat {chat_id}.")

async def pomodoro_config_times(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Permite configurar os tempos do Pomodoro."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)

    db = await load_data() # await ADICIONADO AWAIT
    user_data = get_user_data(db, chat_id)
    config = user_data.setdefault("pomodoro_config", pomodoro_timers[chat_id])

    message_text = (
        "⚙️ *Configurar Tempos do Pomodoro*\n\n"
        f"Tempos atuais:\n"
        f"  Foco: *{config.get('focus', 25)} min*\n"
        f"  Pausa Curta: *{config.get('short_break', 5)} min*\n"
        f"  Pausa Longa: *{config.get('long_break', 15)} min*\n"
        f"  Ciclos: *{config.get('cycles', 4)}*\n\n"
        "Selecione qual tempo deseja alterar:"
    )

    keyboard = [
        [InlineKeyboardButton("Foco", callback_data="set_pomodoro_focus")],
        [InlineKeyboardButton("Pausa Curta", callback_data="set_pomodoro_short_break")],
        [InlineKeyboardButton("Pausa Longa", callback_data="set_pomodoro_long_break")],
        [InlineKeyboardButton("Ciclos", callback_data="set_pomodoro_cycles")],
        [InlineKeyboardButton("↩️ Voltar ao Menu Pomodoro", callback_data="menu_pomodoro")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')
    logger.info(f"Menu de configuração de tempos do Pomodoro exibido para o chat {chat_id}.")

async def pomodoro_set_time_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback para iniciar o processo de configuração de um tempo específico do Pomodoro."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)
    setting_type = query.data.replace("set_pomodoro_", "") # focus, short_break, long_break, cycles

    context.user_data["expecting"] = f"set_pomodoro_time_{setting_type}"
    context.user_data["pomodoro_setting_type"] = setting_type

    if setting_type == "cycles":
        await query.edit_message_text(f"🔢 Digite o novo número de ciclos do Pomodoro (ex: 4):")
    else:
        await query.edit_message_text(f"⏱️ Digite o novo tempo em minutos para '{setting_type.replace('_', ' ').capitalize()}' (ex: 25):")
    logger.info(f"Usuário {chat_id} selecionou configurar tempo de Pomodoro: {setting_type}.")

async def set_pomodoro_time(update: Update, context: ContextTypes.DEFAULT_TYPE, setting_type: str) -> None:
    """Define o tempo ou número de ciclos do Pomodoro."""
    chat_id = str(update.effective_chat.id)
    value_str = update.message.text.strip()

    try:
        value = int(value_str)
        if value <= 0:
            raise ValueError("Valor deve ser positivo.")
    except ValueError:
        await update.message.reply_text("Por favor, digite um número inteiro positivo válido.")
        return

    db = await load_data() # await ADICIONADO AWAIT
    user_data = get_user_data(db, chat_id)
    config = user_data.setdefault("pomodoro_config", pomodoro_timers[chat_id])

    config[setting_type] = value
    await save_data(db) # await ADICIONADO AWAIT

    context.user_data.pop("expecting", None)
    context.user_data.pop("pomodoro_setting_type", None)

    await update.message.reply_text(f"✅ Tempo de '{setting_type.replace('_', ' ').capitalize()}' atualizado para *{value} {'minutos' if setting_type != 'cycles' else 'ciclos'}*.", parse_mode='Markdown')
    logger.info(f"Usuário {chat_id} atualizou {setting_type} do Pomodoro para {value}.")
    await pomodoro_menu(update, context) # Volta ao menu do Pomodoro

async def pomodoro_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inicia, pausa ou resume o timer do Pomodoro."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)
    action = query.data.replace("pomodoro_", "") # start, pause, resume

    db = await load_data() # await ADICIONADO AWAIT
    user_data = get_user_data(db, chat_id)
    config = user_data.setdefault("pomodoro_config", pomodoro_timers[chat_id])

    status_data = pomodoro_status_map.setdefault(chat_id, {
        "status": "stopped",
        "current_phase": "focus", # focus, short_break, long_break
        "cycle_count": 0,
        "job_name": None,
        "time_left": 0, # Tempo restante em segundos
        "last_update_time": None # Para calcular tempo decorrido ao retomar
    })

    message_text = ""

    if action == "start":
        if status_data["status"] == "stopped":
            status_data["status"] = "running"
            status_data["current_phase"] = "focus"
            status_data["cycle_count"] = 1
            status_data["time_left"] = config["focus"] * 60
            status_data["last_update_time"] = datetime.datetime.now(SAO_PAULO_TZ)

            job_name = f"pomodoro_timer_{chat_id}"
            status_data["job_name"] = job_name
            context.job_queue.run_repeating(
                pomodoro_timer_callback,
                interval=1, # Executa a cada segundo
                first=0,
                data={"chat_id": chat_id},
                chat_id=chat_id,
                name=job_name
            )
            message_text = f"▶️ Pomodoro iniciado! Foco por *{config['focus']} minutos*."
        else:
            message_text = f"Pomodoro já está {status_data['status']}. Use 'Pausar' ou 'Parar'."
    elif action == "pause":
        if status_data["status"] == "running":
            status_data["status"] = "paused"
            if status_data["job_name"]:
                job = context.job_queue.get_jobs_by_name(status_data["job_name"])
                if job:
                    job[0].schedule_removal() # Cancela o job de repetição
            message_text = "⏸️ Pomodoro pausado."
        else:
            message_text = "Pomodoro não está rodando para ser pausado."
    elif action == "resume":
        if status_data["status"] == "paused":
            status_data["status"] = "running"
            status_data["last_update_time"] = datetime.datetime.now(SAO_PAULO_TZ) # Atualiza tempo de início
            job_name = f"pomodoro_timer_{chat_id}"
            status_data["job_name"] = job_name
            context.job_queue.run_repeating(
                pomodoro_timer_callback,
                interval=1,
                first=0,
                data={"chat_id": chat_id},
                chat_id=chat_id,
                name=job_name
            )
            message_text = f"▶️ Pomodoro retomado! Tempo restante: *{status_data['time_left'] // 60:02d}:{(status_data['time_left'] % 60):02d}*."
        else:
            message_text = "Pomodoro não está pausado para ser retomado."

    await query.edit_message_text(message_text, parse_mode='Markdown')
    logger.info(f"Pomodoro no chat {chat_id}: Ação '{action}', Status '{status_data['status']}'.")
    # Atualiza o menu após a ação
    await pomodoro_menu(update, context)

async def pomodoro_timer_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback executado a cada segundo para o timer do Pomodoro."""
    chat_id = str(context.job.chat_id)
    status_data = pomodoro_status_map.get(chat_id)

    if not status_data or status_data["status"] != "running":
        return

    db = await load_data() # await ADICIONADO AWAIT
    user_data = get_user_data(db, chat_id)
    config = user_data.setdefault("pomodoro_config", pomodoro_timers[chat_id])

    now_aware = datetime.datetime.now(SAO_PAULO_TZ)
    if status_data["last_update_time"]:
        elapsed_time = (now_aware - status_data["last_update_time"]).total_seconds()
        status_data["time_left"] -= int(elapsed_time)
    status_data["last_update_time"] = now_aware

    if status_data["time_left"] <= 0:
        # Fim da fase atual
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"DING! DONG! Fim da fase de *{status_data['current_phase'].capitalize()}*!",
            parse_mode='Markdown'
        )
        logger.info(f"Fim da fase de {status_data['current_phase']} para o chat {chat_id}.")

        if status_data["current_phase"] == "focus":
            status_data["cycle_count"] += 1
            if status_data["cycle_count"] <= config["cycles"]:
                # Pausa curta
                status_data["current_phase"] = "short_break"
                status_data["time_left"] = config["short_break"] * 60
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"☕ Hora da Pausa Curta! Relaxe por *{config['short_break']} minutos*.",
                    parse_mode='Markdown'
                )
            else:
                # Pausa longa
                status_data["current_phase"] = "long_break"
                status_data["time_left"] = config["long_break"] * 60
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"🏖️ Pausa Longa Merecida! Aproveite por *{config['long_break']} minutos*!",
                    parse_mode='Markdown'
                )
                status_data["cycle_count"] = 0 # Reinicia ciclos após pausa longa
        elif status_data["current_phase"] in ["short_break", "long_break"]:
            # Volta para o foco
            status_data["current_phase"] = "focus"
            status_data["time_left"] = config["focus"] * 60
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"💪 De volta ao Foco! Mais *{config['focus']} minutos* de produtividade!",
                parse_mode='Markdown'
            )
        
        # Envia atualização do menu Pomodoro após a transição de fase
        await pomodoro_menu_update_message(context.bot, chat_id, status_data)

    # Opcional: Enviar atualizações a cada X segundos para o status no chat (se quiser)
    # Atualmente, só atualiza no fim da fase ou quando o menu é acessado.

async def pomodoro_menu_update_message(bot, chat_id: str, status_data: dict) -> None:
    """Atualiza a mensagem do menu Pomodoro no chat do usuário."""
    db = await load_data() # await ADICIONADO AWAIT
    user_data = get_user_data(db, chat_id)
    config = user_data.setdefault("pomodoro_config", pomodoro_timers[chat_id])

    current_status = status_data.get("status", "stopped")
    current_time_left = status_data.get("time_left", 0)

    minutes, seconds = divmod(current_time_left, 60)
    time_display = f"{minutes:02d}:{seconds:02d}" if current_time_left > 0 else "00:00"

    message_text = (
        f"🍅 *Menu Pomodoro* 🍅\n\n"
        f"Status atual: *{current_status.capitalize()}*\n"
        f"Tempo restante: *{time_display}*\n\n"
        f"Configurações:\n"
        f"  Foco: *{config.get('focus', 25)} min*\n"
        f"  Pausa Curta: *{config.get('short_break', 5)} min*\n"
        f"  Pausa Longa: *{config.get('long_break', 15)} min*\n"
        f"  Ciclos: *{config.get('cycles', 4)}*\n\n"
    )

    keyboard_buttons = []
    if current_status == "stopped":
        keyboard_buttons.append([InlineKeyboardButton("▶️ Iniciar Pomodoro", callback_data="pomodoro_start")])
    elif current_status == "running":
        keyboard_buttons.append([InlineKeyboardButton("⏸️ Pausar Pomodoro", callback_data="pomodoro_pause")])
        keyboard_buttons.append([InlineKeyboardButton("⏹️ Parar Pomodoro", callback_data="pomodoro_stop_command")])
    elif current_status == "paused":
        keyboard_buttons.append([InlineKeyboardButton("▶️ Continuar Pomodoro", callback_data="pomodoro_resume")])
        keyboard_buttons.append([InlineKeyboardButton("⏹️ Parar Pomodoro", callback_data="pomodoro_stop_command")])
    elif current_status == "break":
        keyboard_buttons.append([InlineKeyboardButton("⏹️ Parar Pomodoro", callback_data="pomodoro_stop_command")])

    keyboard_buttons.extend([
        [InlineKeyboardButton("⚙️ Configurar Tempos", callback_data="pomodoro_config_times")],
        [InlineKeyboardButton("🔄 Status Atual", callback_data="pomodoro_status_command")],
        [InlineKeyboardButton("↩️ Voltar ao Menu Principal", callback_data="main_menu")]
    ])
    reply_markup = InlineKeyboardMarkup(keyboard_buttons)

    # Tenta editar a última mensagem do menu Pomodoro se ela existir
    if status_data.get("last_pomodoro_message_id"):
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_data["last_pomodoro_message_id"],
                text=message_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.warning(f"Não foi possível editar mensagem do Pomodoro para {chat_id}: {e}. Enviando nova.")
            new_message = await bot.send_message(
                chat_id=chat_id,
                text=message_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            status_data["last_pomodoro_message_id"] = new_message.message_id
    else:
        new_message = await bot.send_message(
            chat_id=chat_id,
            text=message_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        status_data["last_pomodoro_message_id"] = new_message.message_id

async def pomodoro_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Para o timer do Pomodoro."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)

    status_data = pomodoro_status_map.get(chat_id)
    if status_data and status_data["job_name"]:
        job = context.job_queue.get_jobs_by_name(status_data["job_name"])
        if job:
            job[0].schedule_removal()
        pomodoro_status_map.pop(chat_id, None) # Remove do mapa
        await query.edit_message_text("⏹️ Pomodoro parado. Você é incrível por ter chegado até aqui! ✨", parse_mode='Markdown')
        logger.info(f"Pomodoro parado para o chat {chat_id}.")
    else:
        await query.edit_message_text("🤔 O Pomodoro não está rodando.", parse_mode='Markdown')
        logger.warning(f"Tentativa de parar Pomodoro não rodando no chat {chat_id}.")
    await pomodoro_menu(update, context) # Atualiza o menu

async def pomodoro_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mostra o status atual do Pomodoro."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)

    status_data = pomodoro_status_map.get(chat_id)

    if not status_data or status_data["status"] == "stopped":
        message_text = "😴 O Pomodoro não está ativo no momento. Use 'Iniciar Pomodoro' para começar!"
    else:
        minutes, seconds = divmod(status_data["time_left"], 60)
        message_text = (
            f"🔄 *Status Atual do Pomodoro*:\n"
            f"  Fase: *{status_data['current_phase'].capitalize()}*\n"
            f"  Ciclo: *{status_data['cycle_count']} / {pomodoro_timers[chat_id]['cycles']}*\n"
            f"  Tempo Restante: *{minutes:02d}:{seconds:02d}*\n"
            f"  Status: *{status_data['status'].capitalize()}*"
        )
    await query.edit_message_text(message_text, parse_mode='Markdown')
    await pomodoro_menu(update, context) # Volta para o menu após mostrar status

# --- Funções da Rotina Semanal ---
async def show_weekly_routine_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exibe a rotina semanal do usuário."""
    chat_id = str(update.effective_chat.id)
    query = update.callback_query
    if query:
        await query.answer()

    db = await load_data() # await ADICIONADO AWAIT
    user_data = get_user_data(db, chat_id)
    routine = user_data.setdefault("weekly_routine", {})

    message_text = "🗓️ *Sua Rotina Semanal:*\n\n"
    if not routine:
        message_text += "Ainda não há itens na sua rotina semanal. Que tal adicionar alguns? 😉\n\n"
    else:
        days_order = ["domingo", "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado"]
        for day in days_order:
            tasks_on_day = routine.get(day, [])
            if tasks_on_day:
                message_text += f"*{day.capitalize()}*:\n"
                for task in tasks_on_day:
                    time_str = task.get('time', 'Não especificado')
                    activity = task.get('activity', 'Sem descrição')
                    message_text += f"  • {time_str} - {activity}\n"
                message_text += "\n"
        if not any(routine.values()): # Caso exista a chave routine mas esteja vazia
             message_text = "🗓️ *Sua Rotina Semanal:*\n\n"
             message_text += "Ainda não há itens na sua rotina semanal. Que tal adicionar alguns? 😉\n\n"

    keyboard = [
        [InlineKeyboardButton("✍️ Definir Rotina", callback_data="set_weekly_routine_menu")],
        [InlineKeyboardButton("✏️ Editar Rotina Completa", callback_data="edit_full_weekly_routine")],
        [InlineKeyboardButton("🗑️ Excluir Item da Rotina", callback_data="delete_item_weekly_routine")],
        [InlineKeyboardButton("↩️ Voltar ao Menu Principal", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')
    logger.info(f"Rotina semanal exibida para o chat {chat_id}.")

async def handle_weekly_routine_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inicia o processo de definição da rotina semanal."""
    chat_id = str(update.effective_chat.id)
    query = update.callback_query
    if query:
        await query.answer()
        # Remove a mensagem antiga se for um callback
        await query.edit_message_text(
            "✍️ Para definir ou atualizar sua rotina semanal, me diga o dia, hora e o que fazer.\n"
            "Exemplos:\n"
            "  `segunda 08:00 reunião de equipe`\n"
            "  `terça 19:30 academia`\n"
            "  `quarta 22:00 ler livro`\n"
            "  `quinta 10h planejar projetos`\n\n"
            "Você pode enviar um item de cada vez ou vários, um por linha.\n\n"
            "Quando terminar, envie `/rotina` para ver a rotina atualizada.",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "✍️ Para definir ou atualizar sua rotina semanal, me diga o dia, hora e o que fazer.\n"
            "Exemplos:\n"
            "  `segunda 08:00 reunião de equipe`\n"
            "  `terça 19:30 academia`\n"
            "  `quarta 22:00 ler livro`\n"
            "  `quinta 10h planejar projetos`\n\n"
            "Você pode enviar um item de cada vez ou vários, um por linha.\n\n"
            "Quando terminar, envie `/rotina` para ver a rotina atualizada.",
            parse_mode='Markdown'
        )

    context.user_data["expecting"] = "set_weekly_routine"
    logger.info(f"Usuário {chat_id} iniciou definição da rotina semanal.")

async def process_weekly_routine_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processa a entrada de rotina semanal."""
    chat_id = str(update.effective_chat.id)
    input_text = update.message.text.strip()
    
    db = await load_data() # await ADICIONADO AWAIT
    user_data = get_user_data(db, chat_id)
    routine = user_data.setdefault("weekly_routine", {})

    lines = input_text.split('\n')
    added_count = 0
    failed_count = 0

    for line in lines:
        line = line.strip().lower()
        if not line:
            continue

        # Regex para capturar dia, hora (opcional) e atividade
        match = re.match(r'^(segunda|terça|terca|quarta|quinta|sexta|sábado|sabado|domingo)\s*(\d{1,2}(?::\d{2})?h?)?\s*(.*)$', line)
        if match:
            day_raw = match.group(1).replace('terca', 'terça').replace('sabado', 'sábado')
            time_raw = match.group(2)
            activity = match.group(3).strip()

            if not activity:
                failed_count += 1
                logger.warning(f"Linha de rotina sem atividade: '{line}' para {chat_id}.")
                continue
            
            # Formata a hora para HH:MM se presente
            time_formatted = "Não especificado"
            if time_raw:
                time_match = re.match(r'(\d{1,2})(?:[:h](\d{2}))?', time_raw)
                if time_match:
                    hour = int(time_match.group(1))
                    minute = int(time_match.group(2)) if time_match.group(2) else 0
                    time_formatted = f"{hour:02d}:{minute:02d}"

            # Adiciona um ID único para cada item da rotina para facilitar a remoção
            item_id = str(uuid.uuid4())
            
            if day_raw not in routine:
                routine[day_raw] = []
            
            # Adiciona o item à lista do dia
            routine[day_raw].append({"id": item_id, "time": time_formatted, "activity": activity})
            added_count += 1
            logger.info(f"Item de rotina adicionado para {chat_id}: {day_raw} - {time_formatted} - {activity}")
        else:
            failed_count += 1
            logger.warning(f"Formato de rotina inválido: '{line}' para {chat_id}.")

    await save_data(db) # await ADICIONADO AWAIT

    response_message = ""
    if added_count > 0:
        response_message += f"✅ Adicionado {added_count} item(s) à sua rotina semanal!\n"
    if failed_count > 0:
        response_message += f"❌ Falha ao adicionar {failed_count} item(s) devido a formato inválido. Lembre-se: `dia hora atividade`.\n"
    
    if added_count == 0 and failed_count == 0:
        response_message = "Nenhum item válido foi encontrado para adicionar à sua rotina."
    elif added_count > 0:
        response_message += "Envie `/routine` para ver a rotina atualizada ou continue enviando mais itens."
    
    await update.message.reply_text(response_message, parse_mode='Markdown')
    context.user_data.pop("expecting", None) # Limpa o estado após processar a entrada
    logger.info(f"Processamento de rotina semanal concluído para {chat_id}. Adicionados: {added_count}, Falhas: {failed_count}.")

async def edit_full_weekly_routine_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Permite editar a rotina semanal completa (re-definindo)."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)

    db = await load_data() # await ADICIONADO AWAIT
    user_data = get_user_data(db, chat_id)
    routine = user_data.setdefault("weekly_routine", {})

    # Limpa a rotina existente antes de pedir nova entrada
    user_data["weekly_routine"] = {}
    await save_data(db) # await ADICIONADO AWAIT

    await query.edit_message_text(
        "Você está re-definindo sua rotina semanal.\n"
        "Por favor, envie sua rotina completa novamente, um item por linha, no formato `dia hora atividade`.\n"
        "Exemplo:\n"
        "`segunda 08:00 reunião de equipe`\n"
        "`terça 19:30 academia`\n"
        "Quando terminar, envie `/routine` para ver a rotina atualizada.",
        parse_mode='Markdown'
    )
    context.user_data["expecting"] = "set_weekly_routine"
    logger.info(f"Usuário {chat_id} iniciou edição completa da rotina semanal.")

async def delete_item_weekly_routine_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exibe um menu para deletar um item específico da rotina semanal."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)

    db = await load_data() # await ADICIONADO AWAIT
    user_data = get_user_data(db, chat_id)
    routine = user_data.setdefault("weekly_routine", {})

    all_routine_items = []
    days_order = ["domingo", "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado"]
    for day in days_order:
        tasks_on_day = routine.get(day, [])
        for task in tasks_on_day:
            all_routine_items.append({"day": day, "task": task})

    if not all_routine_items:
        await query.edit_message_text("Ainda não há itens na sua rotina semanal para excluir. 😉")
        return

    keyboard = []
    for item in all_routine_items:
        day_name = item["day"].capitalize()
        time_str = item["task"].get('time', 'Não especificado')
        activity = item["task"].get('activity', 'Sem descrição')
        item_id = item["task"]["id"]
        keyboard.append([InlineKeyboardButton(f"{day_name} {time_str} - {activity}", callback_data=f"delete_routine_task_confirm_id_{item_id}")])

    keyboard.append([InlineKeyboardButton("↩️ Voltar à Rotina Semanal", callback_data="show_weekly_routine_command")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text("Selecione qual item da rotina você deseja *excluir*:", reply_markup=reply_markup, parse_mode='Markdown')
    logger.info(f"Menu de exclusão de item da rotina semanal exibido para o chat {chat_id}.")

async def delete_routine_task_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirma e exclui um item da rotina semanal."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)

    try:
        item_id_to_delete = query.data.split("_id_")[1]
    except IndexError:
        logger.error(f"Erro ao parsear ID do callback_data para deletar rotina: {query.data}")
        await query.edit_message_text("❌ Erro ao identificar o item da rotina. Por favor, tente novamente!")
        return

    db = await load_data() # await ADICIONADO AWAIT
    user_data = get_user_data(db, chat_id)
    routine = user_data.setdefault("weekly_routine", {})

    deleted_activity = None
    for day in routine:
        # Cria uma nova lista sem o item a ser deletado
        routine[day] = [task for task in routine[day] if task.get("id") != item_id_to_delete]
        if len(routine[day]) < len(user_data["weekly_routine"].get(day, [])): # Se o tamanho diminuiu
            deleted_activity = next((task.get("activity") for task in user_data["weekly_routine"].get(day, []) if task.get("id") == item_id_to_delete), None)
            break
    
    # Remove dias vazios
    user_data["weekly_routine"] = {day: tasks for day, tasks in routine.items() if tasks}

    if deleted_activity:
        await save_data(db) # await ADICIONADO AWAIT
        await query.edit_message_text(f"🗑️ Item *'{deleted_activity}'* removido da sua rotina semanal!", parse_mode='Markdown')
        logger.info(f"Item de rotina '{deleted_activity}' (ID: {item_id_to_delete}) removido para o chat {chat_id}.")
        await show_weekly_routine_command(update, context) # Atualiza a exibição da rotina
    else:
        await query.edit_message_text("🤔 Item da rotina não encontrado. Já pode ter sido excluído.", parse_mode='Markdown')
        logger.warning(f"Tentativa de remover item de rotina com ID inválido {item_id_to_delete} para o chat {chat_id}.")

async def view_weekly_routine_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback para voltar para o menu de rotina semanal."""
    await show_weekly_routine_command(update, context) # Simplesmente chama a função para exibir o menu
    logger.info(f"Menu de rotina semanal reexibido para o chat {update.effective_chat.id}.")

# --- Funções de Metas Semanais ---
async def view_weekly_goals_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exibe as metas semanais do usuário."""
    chat_id = str(update.effective_chat.id)
    query = update.callback_query
    if query:
        await query.answer()

    db = await load_data() # await ADICIONADO AWAIT
    user_data = get_user_data(db, chat_id)
    weekly_goals = user_data.setdefault("weekly_goals", [])

    message_text = "🎯 *Suas Metas Semanais:*\n\n"
    if not weekly_goals:
        message_text += "Ainda não há metas semanais definidas. Que tal adicionar uma? 😉\n\n"
    else:
        for i, goal in enumerate(weekly_goals):
            status = "✅" if goal.get("done") else "⏳"
            message_text += f"{status} *{i+1}.* {goal['goal_text']}\n"
        message_text += "\n"

    keyboard = [
        [InlineKeyboardButton("➕ Definir Nova Meta", callback_data="set_weekly_goal_command_cb")],
        [InlineKeyboardButton("✅ Marcar Meta como Concluída", callback_data="select_goal_to_mark_done")],
        [InlineKeyboardButton("🗑️ Apagar Meta", callback_data="delete_weekly_goal_menu")],
        [InlineKeyboardButton("↩️ Voltar ao Menu Principal", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')
    logger.info(f"Metas semanais exibidas para o chat {chat_id}.")

async def set_weekly_goal_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inicia o processo de definição de uma meta semanal."""
    chat_id = str(update.effective_chat.id)
    context.user_data["expecting"] = "set_weekly_goal"
    await update.message.reply_text("🎯 Qual é a sua nova meta semanal? Seja específico e mensurável! (Ex: 'Estudar 10 horas de Python', 'Ir à academia 3 vezes')")
    logger.info(f"Usuário {chat_id} iniciou definição de meta semanal.")

async def set_weekly_goal_command_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback para iniciar o processo de definição de meta semanal."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)
    context.user_data["expecting"] = "set_weekly_goal"
    await query.edit_message_text("🎯 Qual é a sua nova meta semanal? Seja específico e mensurável! (Ex: 'Estudar 10 horas de Python', 'Ir à academia 3 vezes')")
    logger.info(f"Usuário {chat_id} iniciou definição de meta semanal (via callback).")

async def process_set_weekly_goal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processa a meta semanal digitada pelo usuário."""
    chat_id = str(update.effective_chat.id)
    goal_text = update.message.text.strip()

    if not goal_text:
        await update.message.reply_text("A meta não pode ser vazia. Por favor, digite sua meta novamente.")
        return

    db = await load_data() # await ADICIONADO AWAIT
    user_data = get_user_data(db, chat_id)
    weekly_goals = user_data.setdefault("weekly_goals", [])

    new_goal = {
        "id": str(uuid.uuid4()),
        "goal_text": goal_text,
        "done": False,
        "date_added": datetime.datetime.now(SAO_PAULO_TZ).isoformat()
    }
    weekly_goals.append(new_goal)
    await save_data(db) # await ADICIONADO AWAIT

    await update.message.reply_text(f"🎉 Meta *'{goal_text}'* adicionada com sucesso! Foco nela! 💪", parse_mode='Markdown')
    context.user_data.pop("expecting", None)
    logger.info(f"Meta '{goal_text}' adicionada para o usuário {chat_id}.")
    await view_weekly_goals_command(update, context) # Volta para o menu de metas

async def select_goal_to_mark_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Apresenta a lista de metas para o usuário selecionar qual marcar como concluída."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)
    db = await load_data() # await ADICIONADO AWAIT
    user_data = get_user_data(db, chat_id)
    weekly_goals = user_data.setdefault("weekly_goals", [])

    pending_goals = [goal for goal in weekly_goals if not goal.get("done")]

    if not pending_goals:
        await query.edit_message_text("🎉 Nenhuma meta pendente para marcar como concluída! Continue assim! 👍")
        return

    keyboard = []
    for i, goal in enumerate(pending_goals):
        keyboard.append([InlineKeyboardButton(f"{i+1}. {goal['goal_text']}", callback_data=f"mark_goal_done_id_{goal['id']}")]) # Usa ID

    keyboard.append([InlineKeyboardButton("↩️ Voltar às Metas", callback_data="view_weekly_goals_command")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text("Selecione a meta que você deseja marcar como concluída:", reply_markup=reply_markup)
    logger.info(f"Exibindo seleção de meta para marcar como concluída para o chat {chat_id}.")

async def mark_goal_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Marca uma meta como concluída a partir de um callback (usando ID)."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)

    try:
        goal_id = query.data.split("_id_")[1]
    except IndexError:
        logger.error(f"Erro ao parsear ID do callback_data: {query.data}")
        await query.edit_message_text("❌ Erro ao identificar a meta. Por favor, tente novamente!")
        return

    db = await load_data() # await ADICIONADO AWAIT
    user_data = get_user_data(db, chat_id)
    weekly_goals = user_data.setdefault("weekly_goals", [])

    found_goal = None
    for goal in weekly_goals:
        if goal.get("id") == goal_id:
            found_goal = goal
            break

    if found_goal:
        if not found_goal.get("done"):
            found_goal["done"] = True
            user_data["score"] = user_data.get("score", 0) + 20 # Adiciona pontos por meta concluída
            await save_data(db) # await ADICIONADO AWAIT

            await query.edit_message_text(f"✅ Meta *'{found_goal['goal_text']}'* marcada como concluída! Mais 20 pontos pra você! 🎉", parse_mode='Markdown')
            logger.info(f"Meta '{found_goal['goal_text']}' (ID: {goal_id}) marcada como concluída para o usuário {chat_id}.")
            await view_weekly_goals_command(update, context) # Atualiza a lista de metas
        else:
            await query.edit_message_text("🤔 Essa meta já está marcada como concluída! 😉")
    else:
        await query.edit_message_text("🤔 Essa meta não existe mais ou o ID está incorreto. Tente listar suas metas novamente!", parse_mode='Markdown')
        logger.warning(f"Tentativa de marcar meta com ID inválido {goal_id} para o usuário {chat_id}.")

async def delete_weekly_goal_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Apresenta a lista de metas para o usuário selecionar qual apagar."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)
    db = await load_data() # await ADICIONADO AWAIT
    user_data = get_user_data(db, chat_id)
    weekly_goals = user_data.setdefault("weekly_goals", [])

    if not weekly_goals:
        await query.edit_message_text("🎉 Nenhuma meta para apagar! 👍")
        return

    keyboard = []
    for i, goal in enumerate(weekly_goals):
        status_prefix = "✅ " if goal.get("done") else "⏳ "
        keyboard.append([InlineKeyboardButton(f"{status_prefix}{i+1}. {goal['goal_text']}", callback_data=f"delete_weekly_goal_confirm_id_{goal['id']}")]) # Usa ID

    keyboard.append([InlineKeyboardButton("↩️ Voltar às Metas", callback_data="view_weekly_goals_command")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text("Selecione a meta que você deseja *apagar*:", reply_markup=reply_markup, parse_mode='Markdown')
    logger.info(f"Exibindo seleção de meta para apagar para o chat {chat_id}.")

async def delete_weekly_goal_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirma e exclui uma meta semanal."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)

    try:
        goal_id_to_delete = query.data.split("_id_")[1]
    except IndexError:
        logger.error(f"Erro ao parsear ID do callback_data para deletar meta: {query.data}")
        await query.edit_message_text("❌ Erro ao identificar a meta. Por favor, tente novamente!")
        return

    db = await load_data() # await ADICIONADO AWAIT
    user_data = get_user_data(db, chat_id)
    weekly_goals = user_data.setdefault("weekly_goals", [])

    deleted_goal_text = None
    # Remove a meta da lista
    user_data["weekly_goals"] = [goal for goal in weekly_goals if goal.get("id") != goal_id_to_delete]
    
    # Verifica se a meta foi realmente removida
    if len(user_data["weekly_goals"]) < len(weekly_goals):
        deleted_goal_text = next((goal.get("goal_text") for goal in weekly_goals if goal.get("id") == goal_id_to_delete), None)


    if deleted_goal_text:
        await save_data(db) # await ADICIONADO AWAIT
        await query.edit_message_text(f"🗑️ Meta *'{deleted_goal_text}'* apagada com sucesso! 😉", parse_mode='Markdown')
        logger.info(f"Meta '{deleted_goal_text}' (ID: {goal_id_to_delete}) apagada para o usuário {chat_id}.")
        await view_weekly_goals_command(update, context) # Atualiza a exibição das metas
    else:
        await query.edit_message_text("🤔 Meta não encontrada. Já pode ter sido excluída.", parse_mode='Markdown')
        logger.warning(f"Tentativa de remover meta com ID inválido {goal_id_to_delete} para o chat {chat_id}.")

# --- Manipulador de Erros Global (ADICIONADO) ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Loga o erro e envia um traceback ao usuário."""
    logger.error("Exceção enquanto manipulava uma atualização:", exc_info=context.error)
    
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)
    update_str = update.to_dict() if isinstance(update, Update) else str(update)
    
    message = (
        f"Ops! Um erro inesperado ocorreu. 😔\n"
        "A equipe técnica foi notificada. Por favor, tente novamente mais tarde.\n\n"
        "Detalhes do erro (apenas para debug):"
        f"```\n{tb_string[:1000]}...\n```" # Limita o tamanho para não poluir
    )
    if update.effective_message:
        await update.effective_message.reply_text(message)
    elif update.callback_query:
        await update.callback_query.message.reply_text(message)
    else:
        logger.warning(f"Não foi possível enviar mensagem de erro para o usuário. Update: {update_str}")
