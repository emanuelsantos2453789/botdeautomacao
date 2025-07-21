import datetime
import pytz
import re
import json
from collections import defaultdict
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, JobQueue, Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
import asyncio
import logging
import uuid # Para gerar IDs únicos para tarefas

async def delete_weekly_goal_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Lida com a confirmação de exclusão de uma meta semanal.
    Esta função é chamada quando o usuário clica em um botão de confirmação de exclusão de meta.
    """
    query = update.callback_query
    await query.answer() # Importante: sempre responda à query de callback

    # O formato esperado do callback_data é "delete_weekly_goal_confirm_ID_DA_META"
    # Por exemplo: "delete_weekly_goal_confirm_123"
    try:
        goal_id_str = query.data.split('_')[-1] # Pega o último elemento após o split
        goal_id = int(goal_id_str)

        # --- Adicione sua lógica de exclusão da meta aqui ---
        # Por exemplo: chamar uma função do seu módulo de banco de dados para excluir a meta
        # if db_utils.delete_weekly_goal(goal_id): # Exemplo de função de exclusão
        #     await query.edit_message_text(f"Meta semanal com ID **{goal_id}** foi excluída com sucesso!")
        # else:
        #     await query.edit_message_text(f"Erro ao excluir a meta semanal com ID **{goal_id}**.")
        # --- Fim da lógica de exclusão ---

        await query.edit_message_text(f"Meta semanal com ID **{goal_id}** confirmada para exclusão (Lógica a ser implementada).")

        # Opcional: Voltar para o menu de metas ou para o menu principal
        keyboard = [
            [InlineKeyboardButton("Ver Metas Semanais", callback_data="view_weekly_goals_command")],
            [InlineKeyboardButton("Menu Principal", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("O que você gostaria de fazer agora?", reply_markup=reply_markup)

    except (ValueError, IndexError):
        # Certifique-se de que 'logger' esteja definido no seu handlers.py para registrar erros.
        # Caso contrário, remova a linha abaixo ou defina logger primeiro.
        # logger.error(f"Erro ao processar delete_weekly_goal_confirm_callback: {query.data}")
        await query.edit_message_text("Não foi possível identificar a meta para exclusão. Tente novamente.")

# Configuração de logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuração do fuso horário
SAO_PAULO_TZ = pytz.timezone('America/Sao_Paulo')

# --- Funções Auxiliares para Carregar/Salvar Dados ---
def load_data():
    """Carrega os dados do arquivo JSON."""
    try:
        with open('dados.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            logger.info("Arquivo 'dados.json' carregado com sucesso.")
            return data
    except FileNotFoundError:
        logger.info("Arquivo 'dados.json' não encontrado. Criando um novo.")
        return {}
    except json.JSONDecodeError:
        logger.error("Erro ao decodificar JSON em dados.json. Retornando dados vazios.", exc_info=True)
        return {}

def save_data(data):
    """Salva os dados no arquivo JSON."""
    try:
        with open('dados.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            logger.info("Dados salvos com sucesso em 'dados.json'.")
    except Exception as e:
        logger.error(f"Erro ao salvar dados em 'dados.json': {e}", exc_info=True)

# --- Variáveis Globais para o Estado do Pomodoro ---
# pomodoro_timers armazena as configurações de tempo para cada chat_id
pomodoro_timers = defaultdict(lambda: {"focus": 25, "short_break": 5, "long_break": 15, "cycles": 4})

# pomodoro_status_map armazena o estado atual de cada pomodoro em andamento por chat_id
# Inclui: estado, job agendado, ciclo atual, tempo de término, tempo acumulado por fase e início da sessão
pomodoro_status_map = {}

# --- Função Auxiliar para Cancelar Jobs ---
def cancel_task_jobs(chat_id: str, job_names: list, job_queue: JobQueue):
    """Cancela todos os jobs do JobQueue com os nomes fornecidos para um chat_id específico."""
    if not job_names:
        return

    jobs_cancelled_count = 0
    unique_job_names = set(job_names)

    for job_name in unique_job_names:
        jobs_to_remove = job_queue.get_jobs_by_name(job_name)
        for job in jobs_to_remove:
            # Importante: job.chat_id é um inteiro
            if job.chat_id == int(chat_id):
                if job.enabled:
                    job.schedule_removal()
                    jobs_cancelled_count += 1
                    logger.info(f"Job '{job.name}' cancelado para o chat {chat_id}.")
            else:
                logger.warning(f"Job '{job.name}' encontrado, mas não pertence ao chat {chat_id}. Não será removido.")
    if jobs_cancelled_count > 0:
        logger.info(f"Total de {jobs_cancelled_count} jobs cancelados para o chat {chat_id}.")
    else:
        logger.info(f"Nenhum job correspondente encontrado para cancelar para o chat {chat_id} com os nomes: {job_names}.")

# --- Handler para Entrada de Texto Genérico ---
async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processa entradas de texto do usuário que não são comandos, baseando-se no estado 'expecting'."""
    chat_id = str(update.effective_chat.id)
    text = update.message.text.strip()
    logger.info(f"handle_text_input: chat_id={chat_id}, text='{text}', expecting='{context.user_data.get('expecting')}'")

    # Lógica para configurar tempos do Pomodoro
    if "expecting" in context.user_data and context.user_data["expecting"].startswith("pomodoro_set_"):
        setting_type = context.user_data["pomodoro_setting_type"]
        try:
            value = int(text)
            if value <= 0:
                raise ValueError("O valor deve ser um número positivo.")

            db = load_data()
            user_data = db.setdefault(chat_id, {})
            pomodoro_config = user_data.setdefault("pomodoro_config", {})
            pomodoro_config[setting_type] = value
            save_data(db)

            pomodoro_timers[chat_id][setting_type] = value

            await update.message.reply_text(f"✅ Tempo de *{setting_type.replace('_', ' ')}* definido para *{value} minutos*! 🎉", parse_mode='Markdown')

            context.user_data.pop("expecting", None)
            context.user_data.pop("pomodoro_setting_type", None)
            await pomodoro_menu(update, context)
            return
        except ValueError as ve:
            logger.error(f"Erro de valor ao configurar Pomodoro para {chat_id}: {ve}", exc_info=True)
            await update.message.reply_text("Ops! Por favor, digite um *número válido*. Ex: '25'.", parse_mode='Markdown')
            return
        except Exception as e:
            logger.error(f"Erro inesperado ao configurar Pomodoro para {chat_id}: {e}", exc_info=True)
            await update.message.reply_text("❌ Houve um erro ao salvar sua configuração. Por favor, tente novamente.")
            return

    # Lógica para coletar motivo de não conclusão da tarefa (feedback diário)
    if context.user_data.get("expecting") == "reason_for_not_completion":
        # Usamos o ID da tarefa agora, não o índice
        task_id = context.user_data.get("task_id_for_reason")
        db = load_data()
        user_data = db.setdefault(chat_id, {})
        tarefas = user_data.setdefault("tarefas", [])

        found_task = None
        for t in tarefas:
            if t.get('id') == task_id:
                found_task = t
                break

        if found_task:
            found_task["reason_not_completed"] = text
            found_task["completion_status"] = "not_completed_with_reason"
            found_task["done"] = False
            save_data(db)
            await update.message.reply_text(
                f"✍️ Entendido! O motivo para a não conclusão de *'{found_task['activity']}'* foi registrado. Obrigado pelo feedback! Vamos melhorar juntos! 💪",
                parse_mode='Markdown'
            )
            logger.info(f"Motivo de não conclusão registrado para tarefa {found_task['activity']}: {text}")
        else:
            await update.message.reply_text("🤔 Não consegui vincular o motivo a uma tarefa. Por favor, tente novamente ou use o menu para marcar tarefas.")
            logger.warning(f"Motivo de não conclusão recebido sem task_id válido ou tarefa não encontrada para {chat_id}. Texto: {text}")

        context.user_data.pop("expecting", None)
        context.user_data.pop("task_id_for_reason", None)
        return

    # Lógica para entrada da rotina semanal
    if context.user_data.get("expecting") == "weekly_routine_text":
        scheduled_count = await parse_and_schedule_weekly_routine(chat_id, text, context.job_queue)
        if scheduled_count > 0:
            await update.message.reply_text(
                f"✅ Sua rotina semanal foi salva com sucesso! 🎉 Agendei *{scheduled_count} tarefas* para você. Fique de olho nos lembretes! 👀",
                parse_mode='Markdown'
            )
            await view_weekly_routine(update, context) # Chamar a função para mostrar a rotina semanal após salvar
        else:
            await update.message.reply_text(
                "😔 Não consegui identificar nenhuma tarefa na sua rotina. Por favor, tente novamente seguindo o formato: `Dia da semana: HHhMM - Atividade` ou `HHhMM - HHhMM: Atividade`."
            )
        context.user_data.pop("expecting", None)
        return

    # Lógica para definir descrição da meta semanal
    if context.user_data.get("expecting") == "set_weekly_goal_description":
        await handle_set_weekly_goal_description(update, context)
        return

    # Lógica para adicionar nova tarefa avulsa
    if context.user_data.get("expecting") == "add_task_activity":
        context.user_data["new_task_activity"] = text
        context.user_data["expecting"] = "add_task_datetime"
        await update.message.reply_text("🗓️ Ótimo! Agora me diga a *data e hora* para esta tarefa. Use o formato `DD/MM HH:MM` (ex: `25/12 10:00`). Se não tiver data/hora, digite 'Não'.", parse_mode='Markdown')
        return

    if context.user_data.get("expecting") == "add_task_datetime":
        activity = context.user_data.get("new_task_activity")
        datetime_str = text.strip()

        start_dt_aware = None
        if datetime_str.lower() != 'não':
            try:
                # Tenta parsear com o ano atual
                current_year = datetime.datetime.now(SAO_PAULO_TZ).year
                dt_obj_naive = datetime.datetime.strptime(f"{datetime_str} {current_year}", "%d/%m %H:%M %Y")
                start_dt_aware = SAO_PAULO_TZ.localize(dt_obj_naive)

                # Se a data já passou no ano atual, tenta para o próximo ano
                if start_dt_aware < datetime.datetime.now(SAO_PAULO_TZ):
                    dt_obj_naive = datetime.datetime.strptime(f"{datetime_str} {current_year + 1}", "%d/%m %H:%M %Y")
                    start_dt_aware = SAO_PAULO_TZ.localize(dt_obj_naive)

            except ValueError:
                await update.message.reply_text("Formato de data/hora inválido. Por favor, use `DD/MM HH:MM` ou digite 'Não'.")
                return

        db = load_data()
        user_data = db.setdefault(chat_id, {})
        tarefas = user_data.setdefault("tarefas", [])

        new_task_data = {
            "id": str(uuid.uuid4()), # ID único para a tarefa
            "activity": activity,
            "done": False,
            "start_when": start_dt_aware.isoformat() if start_dt_aware else None,
            "end_when": None, # Tarefas avulsas não têm end_when padrão
            "completion_status": None,
            "reason_not_completed": None,
            "recurring": False,
            "priority": "media", # Prioridade padrão
            "job_names": []
        }
        tarefas.append(new_task_data)
        
        # Agendar jobs para esta tarefa avulsa, se tiver data/hora
        if start_dt_aware:
            await schedule_single_task_jobs(chat_id, new_task_data, None, context.job_queue) # Não passamos mais o idx

        save_data(db)

        await update.message.reply_text(
            f"✅ Tarefa *'{activity}'* adicionada com sucesso! 💪\n\n" +
            (f"Lembrete agendado para *{start_dt_aware.strftime('%d/%m/%Y às %H:%M')}*." if start_dt_aware else "Ela ficará na sua lista de tarefas pendentes."),
            parse_mode='Markdown'
        )
        context.user_data.pop("expecting", None)
        context.user_data.pop("new_task_activity", None)
        return

    logger.info(f"Texto '{text}' recebido sem estado 'expecting'.")
    await update.message.reply_text(
        "👉 Use /start para abrir o menu e escolher uma opção. Estou aqui para te ajudar a organizar seu dia e alcançar seus objetivos! 😉"
    )

# --- Callbacks de Ação (Concluir, Apagar, Feedback) ---
async def mark_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler para marcar tarefas como concluídas via botão."""
    query = update.callback_query
    await query.answer()

    chat_id = str(query.message.chat_id)
    db = load_data()
    user_data = db.setdefault(chat_id, {})
    tarefas = user_data.setdefault("tarefas", [])

    cmd = query.data
    logger.info(f"Usuário {chat_id} clicou em callback: {cmd}.")

    if cmd.startswith("mark_done_id_") or cmd.startswith("feedback_yes_id_"):
        try:
            task_id = cmd.split("_id_")[-1]
        except IndexError:
            logger.error(f"Erro ao parsear ID da tarefa do callback_data: {cmd}")
            await query.edit_message_text("❌ Erro ao identificar a tarefa. Por favor, tente novamente!")
            return

        found_task = None
        for task in tarefas:
            if task.get('id') == task_id:
                found_task = task
                break

        if found_task:
            if not found_task.get('done'):
                found_task["done"] = True
                found_task["completion_status"] = "completed_manually" if cmd.startswith("mark_done_") else "completed_on_time"
                found_task["reason_not_completed"] = None

                user_data["score"] = user_data.get("score", 0) + 10
                logger.info(f"Usuário {chat_id} ganhou 10 pontos. Pontuação atual: {user_data['score']}.")

                cancel_task_jobs(chat_id, found_task.get("job_names", []), context.job_queue)

                save_data(db)
                # Adicionar verificação para evitar BadRequest: message not modified
                new_message_text = f"✅ EBA! Tarefa *“{found_task['activity']}”* marcada como concluída! Mandou muito bem! 🎉 Você ganhou 10 pontos! 🌟"
                if query.message.text != new_message_text:
                    await query.edit_message_text(new_message_text, parse_mode='Markdown')
                else:
                    await query.answer("Esta tarefa já está concluída!") # Apenas um feedback para o usuário
                logger.info(f"Tarefa '{found_task['activity']}' marcada como concluída para o usuário {chat_id}.")
            else:
                await query.edit_message_text(f"Esta tarefa já foi marcada como concluída! Que eficiência! 😉")
        else:
            await query.edit_message_text("❌ Não encontrei essa tarefa para marcar como concluída. Ela pode já ter sido concluída ou apagada. 🤔")
            logger.warning(f"Tentativa de marcar tarefa com ID inválido {task_id} para o usuário {chat_id}.")
        context.user_data.pop("expecting", None)
        return

    if cmd.startswith("feedback_no_id_"):
        try:
            task_id = cmd.split("_id_")[1]
        except IndexError:
            logger.error(f"Erro ao parsear ID da tarefa do callback_data: {cmd}")
            await query.edit_message_text("❌ Erro ao identificar a tarefa para feedback. Que pena! 😔")
            return

        found_task = None
        for task in tarefas:
            if task.get('id') == task_id:
                found_task = task
                break

        if found_task:
            if not found_task.get('done'):
                found_task["completion_status"] = "not_completed_awaiting_reason"
                found_task["done"] = False
                save_data(db)

                cancel_task_jobs(chat_id, found_task.get("job_names", []), context.job_queue)

                context.user_data["expecting"] = "reason_for_not_completion"
                context.user_data["task_id_for_reason"] = task_id # Armazena o ID
                await query.edit_message_text(f"😔 Ah, que pena! A tarefa *'{found_task['activity']}'* não foi concluída. Por favor, digite o motivo: foi um imprevisto, falta de tempo, ou algo mais? Me conta para aprendermos juntos! 👇", parse_mode='Markdown')
                logger.info(f"Solicitando motivo de não conclusão para a tarefa '{found_task['activity']}'.")
            else:
                await query.edit_message_text(f"Esta tarefa já foi concluída! Que bom! 😊")
        else:
            await query.edit_message_text("🤔 Não encontrei a tarefa para registrar o motivo. Ela pode já ter sido concluída ou apagada. Por favor, tente novamente!")
            logger.warning(f"Não encontrei tarefa com ID {task_id} para solicitar motivo de não conclusão via feedback 'Não'.")
        return

    if cmd.startswith("feedback_postpone_id_"):
        try:
            task_id = cmd.split("_id_")[1]
        except IndexError:
            logger.error(f"Erro ao parsear ID da tarefa do callback_data: {cmd}")
            await query.edit_message_text("❌ Erro ao identificar a tarefa para adiar. Que pena! 😔")
            return

        found_task = None
        for task in tarefas:
            if task.get('id') == task_id:
                found_task = task
                break

        if found_task:
            if not found_task.get('done'):
                now_aware = datetime.datetime.now(SAO_PAULO_TZ)

                if found_task.get('start_when'):
                    original_start_dt_naive = datetime.datetime.fromisoformat(found_task['start_when'])
                    original_time = original_start_dt_naive.time()

                    new_start_dt_naive = datetime.datetime.combine(now_aware.date() + datetime.timedelta(days=1), original_time)
                    new_start_dt_aware = SAO_PAULO_TZ.localize(new_start_dt_naive)

                    if found_task.get('end_when'):
                        original_end_dt_naive = datetime.datetime.fromisoformat(found_task['end_when'])
                        original_end_time = original_end_dt_naive.time()
                        new_end_dt_naive = datetime.datetime.combine(now_aware.date() + datetime.timedelta(days=1), original_end_time)
                        new_end_dt_aware = SAO_PAULO_TZ.localize(new_end_dt_naive)
                        if new_end_dt_aware < new_start_dt_aware:
                            new_end_dt_aware += datetime.timedelta(days=1)
                        found_task['end_when'] = new_end_dt_aware.isoformat()
                    else:
                        found_task['end_when'] = None
                else:
                    new_start_dt_naive = datetime.datetime.combine(now_aware.date() + datetime.timedelta(days=1), datetime.time(9,0)) # Adia para 9h do dia seguinte
                    new_start_dt_aware = SAO_PAULO_TZ.localize(new_start_dt_naive)
                    found_task['end_when'] = None

                found_task['start_when'] = new_start_dt_aware.isoformat()
                found_task["completion_status"] = "postponed"
                found_task["reason_not_completed"] = "Adiada pelo usuário"
                found_task["done"] = False

                cancel_task_jobs(chat_id, found_task.get("job_names", []), context.job_queue)
                found_task["job_names"] = [] # Limpa a lista de job_names antigos
                await schedule_single_task_jobs(chat_id, found_task, None, context.job_queue) # Não passamos o idx

                save_data(db)
                await query.edit_message_text(f"↩️ A tarefa *'{found_task['activity']}'* foi adiada para *amanhã às {new_start_dt_aware.strftime('%H:%M')}*! Sem problemas, vamos juntos! 💪", parse_mode='Markdown')
                logger.info(f"Tarefa '{found_task['activity']}' adiada para o usuário {chat_id}.")
            else:
                await query.edit_message_text(f"Esta tarefa já foi concluída! Ótimo trabalho! 😉")
        else:
            await query.edit_message_text("🤔 Não encontrei a tarefa para adiar. Ela pode já ter sido concluída ou apagada. Por favor, tente novamente!")
            logger.warning(f"Não encontrei tarefa com ID {task_id} para adiar via feedback.")
        context.user_data.pop("expecting", None)
        return

    if cmd.startswith("feedback_delete_id_"):
        try:
            task_id = cmd.split("_id_")[1]
        except IndexError:
            logger.error(f"Erro ao parsear ID da tarefa do callback_data: {cmd}")
            await query.edit_message_text("❌ Erro ao identificar a tarefa para apagar. Que pena! 😔")
            return

        # Reutiliza a lógica de apagar tarefa existente (agora baseada em ID)
        # Cria um update mock para chamar a função delete_task_callback
        mock_update = Update(update_id=update.update_id, callback_query=query)
        mock_update.callback_query.data = f"delete_task_id_{task_id}"
        await delete_task_callback(mock_update, context)
        context.user_data.pop("expecting", None)
        return

async def delete_meta_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler para apagar metas (agora usando ID)."""
    query = update.callback_query
    await query.answer()

    chat_id = str(query.message.chat_id)
    db = load_data()
    user_data = db.setdefault(chat_id, {})
    metas = user_data.setdefault("weekly_goals", []) # Corrigido para "weekly_goals"

    cmd = query.data
    logger.info(f"Usuário {chat_id} clicou em callback: {cmd}.")

    if cmd.startswith("delete_weekly_goal_confirm_id_"): # Mudança para usar ID
        try:
            meta_id = cmd.split("_id_")[1]
        except IndexError:
            logger.error(f"Erro ao parsear ID do callback_data para apagar meta: {cmd}")
            await query.edit_message_text("❌ Erro ao identificar a meta para apagar. Que chato! 😔")
            return

        deleted_meta = None
        # Encontrar a meta pelo ID
        for idx, meta in enumerate(metas):
            if meta.get('id') == meta_id:
                deleted_meta = metas.pop(idx)
                break

        if deleted_meta:
            save_data(db)
            await query.edit_message_text(f"🗑️ Meta *'{deleted_meta['description']}'* apagada com sucesso! Uma a menos para se preocupar! 😉", parse_mode='Markdown')
            logger.info(f"Meta '{deleted_meta['description']}' (ID: {meta_id}) apagada para o usuário {chat_id}.")
            await view_weekly_goals_command(update, context) # Atualiza a lista de metas
        else:
            await query.edit_message_text("🤔 Essa meta não existe mais ou o ID está incorreto. Tente listar suas metas novamente!")
            logger.warning(f"Tentativa de apagar meta com ID inválido {meta_id} para o usuário {chat_id}.")
        return

async def delete_task_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler para apagar tarefas (não recorrentes), agora usando ID."""
    query = update.callback_query
    await query.answer()

    chat_id = str(query.message.chat_id)
    db = load_data()
    user_data = db.setdefault(chat_id, {})
    tarefas = user_data.setdefault("tarefas", [])

    cmd = query.data
    logger.info(f"Usuário {chat_id} clicou em callback: {cmd}.")

    if cmd.startswith("delete_task_id_"): # Mudança para usar ID
        try:
            task_id = cmd.split("_id_")[1]
        except IndexError:
            logger.error(f"Erro ao parsear ID do callback_data para apagar tarefa: {cmd}")
            await query.edit_message_text("❌ Erro ao identificar a tarefa para apagar. Que pena! 😔")
            return

        deleted_task = None
        # Encontrar a tarefa pelo ID
        for idx, task in enumerate(tarefas):
            if task.get('id') == task_id:
                deleted_task = tarefas.pop(idx)
                break

        if deleted_task:
            cancel_task_jobs(chat_id, deleted_task.get("job_names", []), context.job_queue)

            save_data(db)
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
    db = load_data()
    user_data = db.setdefault(chat_id, {})
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
    db = load_data()
    user_data = db.setdefault(chat_id, {})
    tarefas = user_data.setdefault("tarefas", [])

    now_aware = datetime.datetime.now(SAO_PAULO_TZ)
    start_of_week = now_aware.date() - datetime.timedelta(days=(now_aware.weekday() + 1) % 7)
    end_of_week = start_of_week + datetime.timedelta(days=6)

    total_focused_minutes_week = 0
    total_completed_tasks_week = 0
    total_postponed_tasks_week = 0
    total_not_completed_tasks_week = 0

    daily_productivity = defaultdict(int)

    day_names_abbrev = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

    for task in tarefas:
        try:
            if task.get('start_when'):
                task_start_dt_naive = datetime.datetime.fromisoformat(task['start_when'])
                task_start_dt_aware = SAO_PAULO_TZ.localize(task_start_dt_naive)
                task_date = task_start_dt_aware.date()
            else:
                continue

        except (ValueError, TypeError):
            logger.warning(f"Data de início inválida para a tarefa: {task.get('activity')}. Pulando na análise semanal.")
            continue

        if start_of_week <= task_date <= end_of_week:
            if task.get('completion_status') in ['completed_on_time', 'completed_manually']:
                total_completed_tasks_week += 1
                daily_productivity[task_date.weekday()] += 10
            elif task.get('completion_status') == 'postponed':
                total_postponed_tasks_week += 1
            elif task.get('completion_status') in ['not_completed', 'not_completed_with_reason']:
                total_not_completed_tasks_week += 1

            if task.get('start_when') and task.get('end_when') and task.get('completion_status') in ['completed_on_time', 'completed_manually']:
                try:
                    start_dt = datetime.datetime.fromisoformat(task['start_when']).astimezone(SAO_PAULO_TZ)
                    end_dt = datetime.datetime.fromisoformat(task['end_when']).astimezone(SAO_PAULO_TZ)
                    duration_minutes = (end_dt - start_dt).total_seconds() / 60
                    if duration_minutes > 0:
                        total_focused_minutes_week += duration_minutes
                except (ValueError, TypeError):
                    pass

    focused_h_week = int(total_focused_minutes_week // 60)
    focused_m_week = int(total_focused_minutes_week % 60)

    feedback_message = f"✨ *Seu Feedback Semanal ({start_of_week.strftime('%d/%m')} - {end_of_week.strftime('%d/%m')})* ✨\n\n"
    feedback_message += f"✅ *Tarefas Concluídas*: {total_completed_tasks_week}\n"
    feedback_message += f"⏳ *Tarefas Adiadas*: {total_postponed_tasks_week}\n"
    feedback_message += f"❌ *Tarefas Não Concluídas*: {total_not_completed_tasks_week}\n"
    feedback_message += f"⏱️ *Tempo Focado Estimado*: {focused_h_week}h {focused_m_week:02d}min\n\n"

    feedback_message += "📈 *Desempenho Diário (Pontos)*:\n"
    max_score = max(daily_productivity.values()) if daily_productivity else 1
    graph_lines = []

    for i in range(7):
        day_abbrev = day_names_abbrev[i]
        score = daily_productivity.get(i, 0)
        num_blocks = int((score / max_score) * 10) if max_score > 0 else 0
        graph_lines.append(f"{day_abbrev}: {'█' * num_blocks}{'░' * (10 - num_blocks)} ({score} pts)")

    feedback_message += "```\n" + "\n".join(graph_lines) + "\n```\n\n"

    if total_not_completed_tasks_week > total_completed_tasks_week:
        feedback_message += "💡 *Sugestão da Semana*: Parece que muitas tarefas não foram concluídas. Que tal revisar suas metas ou priorizar menos tarefas por dia? Pequenos passos levam a grandes conquistas! 💪\n"
    elif total_postponed_tasks_week > 0:
        feedback_message += "💡 *Sugestão da Semana*: Algumas tarefas foram adiadas. Considere adicionar um tempo extra para imprevistos em sua rotina ou revisar o volume de tarefas para o dia seguinte! 😉\n"
    elif total_completed_tasks_week > 0:
        feedback_message += "🎉 *Parabéns pela sua semana!* Você está mandando muito bem! Continue assim! 🌟\n"
    else:
        feedback_message += "🤔 Que tal um novo objetivo? Comece com pequenas tarefas e sinta a satisfação da conclusão! ✨\n"

    await context.bot.send_message(chat_id=chat_id, text=feedback_message, parse_mode='Markdown')
    logger.info(f"Feedback semanal enviado para o usuário {chat_id}.")

# --- Funções de Tarefas Agendadas ---
async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lista as tarefas do usuário com opções de filtragem."""
    chat_id = str(update.effective_chat.id)
    db = load_data()
    user_data = db.setdefault(chat_id, {})
    tarefas = user_data.setdefault("tarefas", [])

    filter_type = context.args[0] if context.args else "all"
    if update.callback_query and update.callback_query.data.startswith("list_tasks_"):
        filter_type = update.callback_query.data.replace("list_tasks_", "")

    now_aware = datetime.datetime.now(SAO_PAULO_TZ)
    today = now_aware.date()
    tomorrow = today + datetime.timedelta(days=1)

    filtered_tasks = []

    for idx, task in enumerate(tarefas): # Ainda usamos idx aqui para compatibilidade com a exibição, mas actions usam ID
        include_task = False
        task_date = None

        if task.get('start_when'):
            try:
                task_start_dt_naive = datetime.datetime.fromisoformat(task['start_when'])
                task_start_dt_aware = SAO_PAULO_TZ.localize(task_start_dt_naive)
                task_date = task_start_dt_aware.date()
            except (ValueError, TypeError):
                logger.warning(f"Data de início inválida para a tarefa: {task.get('activity')}. Ignorando data/hora para filtragem.")
                task_date = None

        if filter_type == "all":
            include_task = True
        elif filter_type == "today":
            if task_date == today:
                include_task = True
        elif filter_type == "tomorrow":
            if task_date == tomorrow:
                include_task = True
        elif filter_type == "completed":
            if task.get('done'):
                include_task = True
        elif filter_type == "pending":
            if not task.get('done'):
                include_task = True
        elif filter_type.startswith("priority_"):
            priority_level = filter_type.split("_")[1]
            if task.get('priority') and task['priority'].lower() == priority_level and not task.get('done'):
                include_task = True

        if include_task:
            filtered_tasks.append((idx, task))

    tasks_display = []
    for idx_display, task in filtered_tasks:
        activity = task['activity']
        start_when = task.get('start_when')
        end_when = task.get('end_when')
        done = task.get('done', False)
        recurring = task.get('recurring', False)
        priority = task.get('priority', 'Não definida')
        task_id = task.get('id', 'N/A') # Obtenha o ID

        status_icon = "✅" if done else "⏳"

        task_info = f"{status_icon} *{activity}*"
        if start_when:
            try:
                start_dt = datetime.datetime.fromisoformat(start_when).astimezone(SAO_PAULO_TZ)
                task_info += f" em *{start_dt.strftime('%d/%m/%Y')}* às *{start_dt.strftime('%H:%M')}*"
                if end_when:
                    end_dt = datetime.datetime.fromisoformat(end_when).astimezone(SAO_PAULO_TZ)
                    task_info += f" - *{end_dt.strftime('%H:%M')}*"
            except (ValueError, TypeError):
                task_info += f" (Data/Hora inválida)"

        if recurring:
            task_info += " (🔁 Semanal)"
        if priority != 'Não definida':
            task_info += f" _(Prioridade: {priority.capitalize()})_"

        # Adiciona o ID da tarefa para referência, útil para depuração
        tasks_display.append(f"{idx_display+1}. {task_info} `ID:{task_id}`")

    message_header = f"📋 *Suas Tarefas Agendadas ({filter_type.replace('_', ' ').capitalize()})*:\n\n"
    message_body = "\n".join(tasks_display) if tasks_display else "😔 Nenhuma tarefa encontrada para este filtro.\nQue tal adicionar uma nova?"

    task_management_keyboard = build_task_filter_keyboard()
    task_management_keyboard.insert(0, [InlineKeyboardButton("➕ Adicionar Nova Tarefa", callback_data="add_new_task_menu")])
    if filtered_tasks: # Adiciona botões de ação se houver tarefas para agir
        task_management_keyboard.insert(1, [
            InlineKeyboardButton("✅ Concluir", callback_data="select_task_to_mark_done"),
            InlineKeyboardButton("🗑️ Apagar", callback_data="select_task_to_delete")
        ])

    reply_markup = InlineKeyboardMarkup(task_management_keyboard)

    new_text = message_header + message_body

    if update.callback_query:
        current_message_text = update.callback_query.message.text
        current_message_markup = update.callback_query.message.reply_markup

        current_buttons = [[b.to_dict() for b in row] for row in current_message_markup.inline_keyboard] if current_message_markup else []
        new_buttons = [[b.to_dict() for b in row] for row in reply_markup.inline_keyboard] if reply_markup else []

        if current_message_text == new_text and current_buttons == new_buttons:
            logger.info(f"Mensagem de tarefas para {chat_id} não modificada. Evitando re-edição.")
            await update.callback_query.answer("A lista de tarefas já está atualizada! 😉")
            return
        else:
            try:
                await update.callback_query.edit_message_text(new_text, reply_markup=reply_markup, parse_mode='Markdown')
            except Exception as e: # Captura exceções para evitar travamento
                logger.error(f"Erro ao editar mensagem de tarefas para {chat_id}: {e}", exc_info=True)
                await update.callback_query.message.reply_text(new_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(new_text, reply_markup=reply_markup, parse_mode='Markdown')
    logger.info(f"Usuário {chat_id} solicitou lista de tarefas com filtro '{filter_type}'.")

def build_task_filter_keyboard():
    """Constrói o teclado inline para os filtros de tarefas."""
    return [
        [InlineKeyboardButton("🗓️ Todas", callback_data="list_tasks_all"),
         InlineKeyboardButton("☀️ Hoje", callback_data="list_tasks_today"),
         InlineKeyboardButton("➡️ Amanhã", callback_data="list_tasks_tomorrow")],
        [InlineKeyboardButton("✅ Concluídas", callback_data="list_tasks_completed"),
         InlineKeyboardButton("⏳ Pendentes", callback_data="list_tasks_pending")],
        [InlineKeyboardButton("⬆️ Prioridade Alta", callback_data="list_tasks_priority_alta"),
         InlineKeyboardButton("➡️ Prioridade Média", callback_data="list_tasks_priority_media"),
         InlineKeyboardButton("⬇️ Prioridade Baixa", callback_data="list_tasks_priority_baixa")],
        [InlineKeyboardButton("↩️ Voltar ao Menu Principal", callback_data="main_menu")]
    ]

async def show_tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando para exibir as tarefas, chamando a função de listagem."""
    await list_tasks(update, context)

async def select_task_to_mark_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Apresenta uma lista de tarefas pendentes para o usuário marcar como concluída."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)

    db = load_data()
    user_data = db.setdefault(chat_id, {})
    tarefas = user_data.setdefault("tarefas", [])

    pending_tasks = [task for task in tarefas if not task.get("done")]

    if not pending_tasks:
        await query.edit_message_text("🎉 Todas as suas tarefas estão concluídas! Que maravilha! 😊", parse_mode='Markdown')
        return

    message_text = "✅ *Qual tarefa você deseja marcar como concluída?*\n\n"
    keyboard = []

    for idx, task in enumerate(pending_tasks): # Use idx para exibição no botão
        button_text = f"{idx+1}. {task['activity']}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"mark_done_id_{task['id']}")]) # Passa o ID

    keyboard.append([InlineKeyboardButton("↩️ Voltar", callback_data="list_tasks_all")]) # Volta para a lista de tarefas
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')
    logger.info(f"Usuário {chat_id} acessou o menu para marcar tarefas como concluídas.")

async def select_task_to_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Apresenta uma lista de tarefas para o usuário apagar."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)

    db = load_data()
    user_data = db.setdefault(chat_id, {})
    tarefas = user_data.setdefault("tarefas", [])

    if not tarefas:
        await query.edit_message_text("😔 Você não tem tarefas para apagar no momento.", parse_mode='Markdown')
        return

    message_text = "🗑️ *Selecione qual tarefa você deseja apagar:*\n\n"
    keyboard = []

    for idx, task in enumerate(tarefas): # Use idx para exibição no botão
        status_icon = "✅" if task.get('done') else "⏳"
        button_text = f"{idx+1}. {status_icon} {task['activity']}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"delete_task_id_{task['id']}")]) # Passa o ID

    keyboard.append([InlineKeyboardButton("↩️ Voltar", callback_data="list_tasks_all")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')
    logger.info(f"Usuário {chat_id} acessou o menu para apagar tarefas.")

# --- Nova Funcionalidade: Adicionar Tarefa Avulsa ---
async def add_new_task_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inicia o fluxo para adicionar uma nova tarefa avulsa."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)
    context.user_data["expecting"] = "add_task_activity"
    await query.edit_message_text(
        "📝 O que você precisa fazer? Digite a descrição da nova tarefa:",
        parse_mode='Markdown'
    )
    logger.info(f"Usuário {chat_id} iniciou o fluxo para adicionar nova tarefa.")

# --- Funções de Rotina Semanal ---
async def handle_weekly_routine_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inicia o processo de definição da rotina semanal pedindo o texto ao usuário."""
    # Garante que seja update.message.reply_text ou update.callback_query.message.reply_text
    # Depende de como essa função é chamada (comando /setroutine ou callback)
    source_message = update.message if update.message else update.callback_query.message
    
    context.user_data["expecting"] = "weekly_routine_text"
    await source_message.reply_text(
        "📚 Me envie sua rotina semanal completa, dia a dia e com horários, como no exemplo que você me deu! "
        "Vou te ajudar a transformá-la em tarefas agendadas. Capricha nos detalhes! ✨\n\n"
        "Exemplo:\n"
        "Segunda-feira:\n"
        "08h00 - 09h00: Reunião de Equipe\n"
        "10h00: Estudar Inglês\n"
        "Terça-feira:\n"
        "14h00 - 15h30: Desenvolver Projeto X"
    )
    logger.info(f"Usuário {update.effective_user.id} solicitou input de rotina semanal.")

async def parse_and_schedule_weekly_routine(chat_id: str, routine_text: str, job_queue: JobQueue) -> int:
    """Parses the weekly routine text and schedules tasks."""
    lines = routine_text.split('\n')
    current_day = None
    scheduled_tasks_count = 0

    now_aware = datetime.datetime.now(SAO_PAULO_TZ)

    day_mapping = {
        "segunda-feira": 0, "segunda": 0,
        "terça-feira": 1, "terça": 1,
        "quarta-feira": 2, "quarta": 2,
        "quinta-feira": 3, "quinta": 3,
        "sexta-feira": 4, "sexta": 4,
        "sábado": 5, "sabado": 5,
        "domingo": 6
    }

    db = load_data()
    user_data = db.setdefault(chat_id, {})
    tarefas = user_data.setdefault("tarefas", [])

    tasks_to_keep = []
    jobs_to_cancel = []
    for task in tarefas:
        if task.get("recurring", False):
            jobs_to_cancel.extend(task.get("job_names", []))
        else:
            tasks_to_keep.append(task)

    cancel_task_jobs(chat_id, jobs_to_cancel, job_queue)
    tarefas[:] = tasks_to_keep

    for line in lines:
        line = line.strip()
        if not line:
            continue

        day_found = False
        for day_name, day_num in day_mapping.items():
            if day_name in line.lower():
                current_day = day_num
                logger.info(f"Detectado dia: {day_name} (Índice: {current_day})")
                day_found = True
                break

        if day_found:
            continue

        if current_day is not None:
            time_activity_match = re.search(r'(\d{1,2}h(?:(\d{2}))?)\s*(?:[-–—]\s*(\d{1,2}h(?:(\d{2}))?))?:\s*(.+)', line, re.IGNORECASE)

            if time_activity_match:
                start_time_str_raw = time_activity_match.group(1)
                end_time_str_raw = time_activity_match.group(3)
                activity_description = time_activity_match.group(5).strip()

                def parse_time_str(time_str):
                    if not time_str: return None
                    match = re.match(r'(\d{1,2})h(?:(\d{2}))?', time_str)
                    if match:
                        h = int(match.group(1))
                        m = int(match.group(2)) if match.group(2) else 0
                        return datetime.time(h, m)
                    return None

                start_time_obj = parse_time_str(start_time_str_raw)
                end_time_obj = parse_time_str(end_time_str_raw)

                if not start_time_obj:
                    logger.warning(f"Não foi possível parsear hora de início da linha: {line}")
                    continue

                logger.info(f"    Detectado: Dia={current_day}, Início={start_time_obj.strftime('%H:%M')}, Fim={end_time_obj.strftime('%H:%M') if end_time_obj else 'N/A'}, Atividade='{activity_description}'")

                target_date = now_aware.date()
                while target_date.weekday() != current_day:
                    target_date += datetime.timedelta(days=1)

                temp_start_dt_naive = datetime.datetime.combine(target_date, start_time_obj)
                if SAO_PAULO_TZ.localize(temp_start_dt_naive) <= now_aware:
                    target_date += datetime.timedelta(weeks=1)

                start_dt_naive = datetime.datetime.combine(target_date, start_time_obj)
                start_dt_aware = SAO_PAULO_TZ.localize(start_dt_naive)

                end_dt_aware = None
                if end_time_obj:
                    end_dt_naive = datetime.datetime.combine(target_date, end_time_obj)
                    if end_dt_naive < start_dt_naive:
                        end_dt_naive += datetime.timedelta(days=1)
                    end_dt_aware = SAO_PAULO_TZ.localize(end_dt_naive)

                new_task_data = {
                    "id": str(uuid.uuid4()),
                    "activity": activity_description,
                    "done": False,
                    "start_when": start_dt_aware.isoformat(),
                    "end_when": end_dt_aware.isoformat() if end_dt_aware else None,
                    "completion_status": None,
                    "reason_not_completed": None,
                    "recurring": True,
                    "priority": "media",
                    "job_names": []
                }
                tarefas.append(new_task_data)
                
                await schedule_single_task_jobs(chat_id, new_task_data, None, job_queue)

                scheduled_tasks_count += 1
                logger.info(f"    Agendada tarefa recorrente: '{activity_description}' para {start_dt_aware}.")

    save_data(db)
    return scheduled_tasks_count

async def schedule_single_task_jobs(chat_id: str, task_data: dict, task_idx: int | None, job_queue: JobQueue):
    """Agenda os jobs (pré-início, início, fim) para uma única tarefa (recorrente ou avulsa).
    task_idx é usado APENAS para compatibilidade LEGADO com alerts existentes, mas o task_id é o preferencial."""
    if not task_data.get('start_when'):
        logger.info(f"Tarefa '{task_data.get('activity')}' não tem data/hora de início, não agendando jobs.")
        return

    start_dt_aware = datetime.datetime.fromisoformat(task_data['start_when']).astimezone(SAO_PAULO_TZ)
    end_dt_aware = datetime.datetime.fromisoformat(task_data['end_when']).astimezone(SAO_PAULO_TZ) if task_data['end_when'] else None
    activity_description = task_data['activity']
    task_is_recurring = task_data.get('recurring', False)
    task_unique_id = task_data.get('id', str(uuid.uuid4()))

    job_names_for_task = []
    now_aware = datetime.datetime.now(SAO_PAULO_TZ)

    def create_job(time_to_run, job_type, message_data):
        job_name = f"task_{job_type}_{chat_id}_{task_unique_id}" # Simplificado o nome do job, ID já é único
        if task_is_recurring:
            job_queue.run_daily(
                send_task_alert,
                time=time_to_run.time(),
                days=(time_to_run.weekday(),),
                chat_id=int(chat_id),
                data=message_data,
                name=job_name
            )
            logger.info(f"Job recorrente '{job_type}' para '{activity_description}' agendado para {time_to_run.strftime('%H:%M')} no dia {time_to_run.weekday()}.")
        else:
            job_queue.run_at(
                send_task_alert,
                time_to_run,
                chat_id=int(chat_id),
                data=message_data,
                name=job_name
            )
            logger.info(f"Job avulso '{job_type}' para '{activity_description}' agendado para {time_to_run.strftime('%d/%m/%Y %H:%M')}.")
        return job_name

    pre_start_time = start_dt_aware - datetime.timedelta(minutes=30)
    if pre_start_time > now_aware:
        job_names_for_task.append(
            create_job(
                pre_start_time,
                "pre_start",
                {'description': activity_description, 'alert_type': 'pre_start', 'task_id': task_unique_id, 'original_start_when': task_data['start_when']}
            )
        )

    job_names_for_task.append(
        create_job(
            start_dt_aware,
            "start",
            {'description': activity_description, 'alert_type': 'start', 'task_id': task_unique_id, 'original_start_when': task_data['start_when']}
        )
    )

    if end_dt_aware and end_dt_aware > now_aware:
        job_names_for_task.append(
            create_job(
                end_dt_aware,
                "end",
                {'description': activity_description, 'alert_type': 'end', 'task_id': task_unique_id, 'original_start_when': task_data['start_when']}
            )
        )

    if "job_names" not in task_data:
        task_data["job_names"] = []
    task_data["job_names"].extend(job_names_for_task)

async def send_task_alert(context: ContextTypes.DEFAULT_TYPE):
    """Envia alertas de tarefas agendadas."""
    chat_id = context.job.chat_id
    data = context.job.data
    description = data['description']
    alert_type = data['alert_type']
    task_id = data['task_id']
    original_start_when = data['original_start_when']

    db = load_data()
    user_data = db.setdefault(str(chat_id), {})
    tarefas = user_data.setdefault("tarefas", [])

    found_task = None
    found_task_idx = -1 # Ainda para compatibilidade de feedback de botoes antigos
    for idx, task in enumerate(tarefas):
        if task.get('id') == task_id:
            found_task = task
            found_task_idx = idx # Mantém o índice para os callbacks de botões
            break

    if not found_task or found_task.get('activity') != description or found_task.get('start_when') != original_start_when:
        logger.warning(f"Alerta para tarefa '{description}' (ID {task_id}) ignorado. Tarefa não corresponde mais ou foi removida/alterada.")
        return

    if found_task.get('done'):
        logger.info(f"Alerta para tarefa '{description}' (ID {task_id}) ignorado. Tarefa já concluída.")
        return

    message = ""
    keyboard = []

    if alert_type == 'pre_start':
        message = f"🔔 Preparar para: *{description}*! Começa em 30 minutos! 😉"
    elif alert_type == 'start':
        message = f"🚀 *HORA DE: {description.upper()}!* Vamos com tudo! 💪"
        # Usamos o ID para os callbacks agora
        keyboard = [
            [InlineKeyboardButton("✅ Concluída", callback_data=f"feedback_yes_id_{task_id}"),
             InlineKeyboardButton("❌ Não Concluída", callback_data=f"feedback_no_id_{task_id}")]
        ]
    elif alert_type == 'end':
        message = f"✅ Tempo para *{description}* acabou! Você conseguiu? 🎉"
        # Usamos o ID para os callbacks agora
        keyboard = [
            [InlineKeyboardButton("✅ Sim, concluí!", callback_data=f"feedback_yes_id_{task_id}"),
             InlineKeyboardButton("❌ Não concluí", callback_data=f"feedback_no_id_{task_id}")]
        ]

    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    await context.bot.send_message(chat_id=chat_id, text=message, reply_markup=reply_markup, parse_mode='Markdown')
    logger.info(f"Alerta '{alert_type}' enviado para a tarefa '{description}' (ID {task_id}) no chat {chat_id}.")

async def view_weekly_routine(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exibe a rotina semanal agendada com opções para editar/excluir."""
    chat_id = str(update.effective_chat.id)
    db = load_data()
    user_data = db.setdefault(chat_id, {})
    tarefas = user_data.setdefault("tarefas", [])

    weekly_routine_message = "📚 *Sua Rotina Semanal Agendada* 📚\n\n"

    tasks_by_day = defaultdict(list)

    day_names_map = {
        0: "Segunda-feira", 1: "Terça-feira", 2: "Quarta-feira", 3: "Quinta-feira",
        4: "Sexta-feira", 5: "Sábado", 6: "Domingo"
    }

    recurring_tasks = [(idx, task) for idx, task in enumerate(tarefas) if task.get("recurring", False)]

    if not recurring_tasks:
        message = "😔 Você ainda não tem uma rotina semanal definida. Use o menu para adicionar sua rotina! ✨"
        keyboard = [[InlineKeyboardButton("✏️ Adicionar Rotina Semanal", callback_data="edit_full_weekly_routine")],
                    [InlineKeyboardButton("↩️ Voltar ao Menu Principal", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if update.callback_query:
            await update.callback_query.answer()
            # Verifica se a mensagem já é a mesma para evitar BadRequest
            current_message_text = update.callback_query.message.text
            if current_message_text != message:
                await update.callback_query.message.edit_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            else:
                await update.callback_query.answer("A rotina semanal já está vazia ou não definida.")
        else:
            await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
        logger.info(f"Usuário {chat_id} visualizou a rotina semanal (vazia).")
        return

    for idx, task in recurring_tasks:
        try:
            start_dt_naive = datetime.datetime.fromisoformat(task['start_when'])
            start_dt_aware = SAO_PAULO_TZ.localize(start_dt_naive)
            day_of_week = start_dt_aware.weekday()

            task_time_str = start_dt_aware.strftime('%H:%M')
            if task.get('end_when'):
                end_dt_naive = datetime.datetime.fromisoformat(task['end_when'])
                end_dt_aware = SAO_PAULO_TZ.localize(end_dt_naive)
                task_time_str += f"-{end_dt_aware.strftime('%H:%M')}"

            tasks_by_day[day_of_week].append({
                "activity": task['activity'],
                "time": task_time_str,
                "idx": idx, # Mantém para exibir, mas para ação usa 'id'
                "id": task.get("id")
            })
        except (ValueError, TypeError):
            logger.warning(f"Tarefa recorrente com data inválida ao exibir rotina: {task.get('activity')}")
            continue

    for day_num in sorted(tasks_by_day.keys()):
        day_name = day_names_map.get(day_num, "Dia Desconhecido")
        weekly_routine_message += f"*{day_name}*:\n"
        for task_info in tasks_by_day[day_num]:
            weekly_routine_message += f"  • {task_info['time']}: {task_info['activity']}\n"

    keyboard = [
        [InlineKeyboardButton("✏️ Editar Rotina Completa", callback_data="edit_full_weekly_routine")],
        [InlineKeyboardButton("🗑️ Apagar Item da Rotina", callback_data="delete_item_weekly_routine")],
        [InlineKeyboardButton("↩️ Voltar ao Menu Principal", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.answer()
        # Verificar antes de editar
        current_message_text = update.callback_query.message.text
        current_message_markup = update.callback_query.message.reply_markup

        current_buttons = [[b.to_dict() for b in row] for row in current_message_markup.inline_keyboard] if current_message_markup else []
        new_buttons = [[b.to_dict() for b in row] for row in reply_markup.inline_keyboard] if reply_markup else []

        if current_message_text == weekly_routine_message and current_buttons == new_buttons:
            logger.info(f"Mensagem da rotina semanal para {chat_id} não modificada. Evitando re-edição.")
            return # Sai da função, já que a mensagem está atualizada
        else:
            await update.callback_query.edit_message_text(weekly_routine_message, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(weekly_routine_message, reply_markup=reply_markup, parse_mode='Markdown')
    logger.info(f"Usuário {chat_id} visualizou a rotina semanal.")

async def show_weekly_routine_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando ou callback para exibir a rotina semanal."""
    if update.callback_query:
        await update.callback_query.answer() # Responde à query para evitar "loading"
    await view_weekly_routine(update, context)

async def edit_full_weekly_routine_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inicia o processo para editar (reescrever) a rotina semanal completa."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)

    db = load_data()
    user_data = db.setdefault(chat_id, {})
    tarefas = user_data.setdefault("tarefas", [])

    tasks_to_keep = []
    jobs_to_cancel_for_routine_reset = []
    for idx, task in enumerate(tarefas):
        if task.get("recurring"):
            jobs_to_cancel_for_routine_reset.extend(task.get("job_names", []))
        else:
            tasks_to_keep.append(task)

    cancel_task_jobs(chat_id, jobs_to_cancel_for_routine_reset, context.job_queue)
    tarefas[:] = tasks_to_keep
    save_data(db)

    context.user_data["expecting"] = "weekly_routine_text"
    await query.edit_message_text(
        "📝 Ok! Estou pronto para receber sua *nova rotina semanal completa*. Envie-a no formato usual (Dia: HHhMM - Atividade). As tarefas da rotina anterior foram removidas para evitar duplicatas. 😉",
        parse_mode='Markdown'
    )
    logger.info(f"Usuário {chat_id} iniciou o processo de edição da rotina semanal.")

async def delete_item_weekly_routine_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Apresenta uma lista de itens da rotina para o usuário apagar."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)

    db = load_data()
    user_data = db.setdefault(chat_id, {})
    tarefas = user_data.setdefault("tarefas", [])

    recurring_tasks = [(idx, task) for idx, task in enumerate(tarefas) if task.get("recurring", False)]

    if not recurring_tasks:
        await query.edit_message_text("🤔 Não há itens na sua rotina semanal para apagar.", parse_mode='Markdown')
        return

    message_text = "🗑️ *Selecione qual item da rotina você deseja apagar:*\n\n"
    keyboard = []

    for idx_original, task in recurring_tasks:
        task_time_str = ""
        try:
            if task.get('start_when'):
                start_dt_naive = datetime.datetime.fromisoformat(task['start_when'])
                start_dt_aware = SAO_PAULO_TZ.localize(start_dt_naive)
                task_time_str = start_dt_aware.strftime('%H:%M')
                if task.get('end_when'):
                    end_dt_naive = datetime.datetime.fromisoformat(task['end_when'])
                    end_dt_aware = SAO_PAULO_TZ.localize(end_dt_naive)
                    task_time_str += f"-{end_dt_aware.strftime('%H:%M')}"

                day_name = {0: "Seg", 1: "Ter", 2: "Qua", 3: "Qui", 4: "Sex", 5: "Sáb", 6: "Dom"}.get(start_dt_aware.weekday())

                button_text = f"[{day_name} {task_time_str}] {task['activity']}"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"delete_routine_task_by_id_{task.get('id')}")])
            else:
                button_text = f"[Sem Horário] {task['activity']}"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"delete_routine_task_by_id_{task.get('id')}")])
        except (ValueError, TypeError):
             button_text = f"[Data Inválida] {task['activity']}"
             keyboard.append([InlineKeyboardButton(button_text, callback_data=f"delete_routine_task_by_id_{task.get('id')}")])


    keyboard.append([InlineKeyboardButton("↩️ Voltar", callback_data="view_weekly_routine_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')
    logger.info(f"Usuário {chat_id} acessou o menu para apagar itens da rotina.")

async def delete_routine_task_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirma e apaga um item específico da rotina semanal (usando ID agora)."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)

    try:
        task_id_to_delete = query.data.split("_id_")[1] # Pega o ID após "delete_routine_task_by_id_"
    except IndexError:
        logger.error(f"Erro ao parsear ID do callback_data para apagar item da rotina: {query.data}")
        await query.edit_message_text("❌ Erro ao identificar o item da rotina para apagar. Por favor, tente novamente!")
        return

    db = load_data()
    user_data = db.setdefault(chat_id, {})
    tarefas = user_data.setdefault("tarefas", [])

    deleted_task = None
    for idx, task in enumerate(tarefas):
        if task.get("id") == task_id_to_delete and task.get("recurring"):
            deleted_task = tarefas.pop(idx)
            break

    if deleted_task:
        cancel_task_jobs(chat_id, deleted_task.get("job_names", []), context.job_queue)
        save_data(db)
        await query.edit_message_text(f"🗑️ O item da rotina *'{deleted_task['activity']}'* foi apagado com sucesso! 😉", parse_mode='Markdown')
        logger.info(f"Item da rotina '{deleted_task['activity']}' (ID {task_id_to_delete}) apagado para o usuário {chat_id}.")

        await view_weekly_routine(update, context) # Atualiza a lista de rotina
    else:
        await query.edit_message_text("🤔 Não encontrei esse item na sua rotina semanal ou ele não é recorrente. Ele pode já ter sido apagado.", parse_mode='Markdown')
        logger.warning(f"Tentativa de apagar item da rotina com ID inválido {task_id_to_delete} ou não recorrente para o usuário {chat_id}.")

async def view_weekly_routine_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Volta para o menu de visualização da rotina semanal."""
    query = update.callback_query
    await query.answer()
    await view_weekly_routine(update, context)

# --- Funções do Pomodoro ---
async def pomodoro_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exibe o menu principal do Pomodoro com status e opções."""
    chat_id = str(update.effective_chat.id)
    current_status = pomodoro_status_map.get(chat_id, {"state": "idle", "current_cycle": 0})

    db = load_data()
    user_data = db.setdefault(chat_id, {})
    pomodoro_config = user_data.setdefault("pomodoro_config", {})

    pomodoro_timers[chat_id]['focus'] = pomodoro_config.get('focus', 25)
    pomodoro_timers[chat_id]['short_break'] = pomodoro_config.get('short_break', 5)
    pomodoro_timers[chat_id]['long_break'] = pomodoro_config.get('long_break', 15)
    pomodoro_timers[chat_id]['cycles'] = pomodoro_config.get('cycles', 4)

    user_timers = pomodoro_timers[chat_id]

    status_text = ""
    remaining_minutes = 0
    remaining_seconds = 0

    if current_status["state"] not in ["idle", "paused"] and current_status.get("end_time"):
        remaining_time_seconds = (current_status["end_time"] - datetime.datetime.now(SAO_PAULO_TZ)).total_seconds()
        remaining_minutes = max(0, int(remaining_time_seconds / 60))
        remaining_seconds = max(0, int(remaining_time_seconds % 60))
    elif current_status["state"] == "paused":
        paused_remaining_time = current_status.get("paused_remaining_time", 0)
        remaining_minutes = max(0, int(paused_remaining_time / 60))
        remaining_seconds = max(0, int(paused_remaining_time % 60))

    if current_status["state"] == "idle":
        status_text = "Nenhum Pomodoro em andamento. Que tal começar um agora? 💪"
    elif current_status["state"] == "focus":
        status_text = f"Foco total! 🧠 Você está no ciclo {current_status['current_cycle']} de Pomodoro. Restam: {remaining_minutes:02d}m {remaining_seconds:02d}s."
    elif current_status["state"] == "short_break":
        status_text = f"Pausa curta para recarregar as energias! ☕ Restam: {remaining_minutes:02d}m {remaining_seconds:02d}s."
    elif current_status["state"] == "long_break":
        status_text = f"Pausa longa, aproveite para relaxar de verdade! 🧘 Restam: {remaining_minutes:02d}m {remaining_seconds:02d}s."
    elif current_status["state"] == "paused":
        status_text = f"Pomodoro PAUSADO. Tempo restante: {remaining_minutes:02d}m {remaining_seconds:02d}s. Clique em Retomar para continuar! ⏸️"


    keyboard = [
        [InlineKeyboardButton("▶️ Iniciar Pomodoro", callback_data="pomodoro_start")],
        [InlineKeyboardButton("⏸️ Pausar", callback_data="pomodoro_pause"),
         InlineKeyboardButton("▶️ Retomar", callback_data="pomodoro_resume")],
        [InlineKeyboardButton("⏹️ Parar Pomodoro", callback_data="pomodoro_stop_command")],
        [InlineKeyboardButton("⚙️ Configurar Tempos", callback_data="pomodoro_config_times")],
        [InlineKeyboardButton("📊 Status Atual", callback_data="pomodoro_status_command")],
        [InlineKeyboardButton("↩️ Voltar ao Menu Principal", callback_data="main_menu")]
    ]
    markup = InlineKeyboardMarkup(keyboard)

    message_text = (
        f"🍅 *Seu Assistente Pomodoro* 🍅\n\n"
        f"Tempo de Foco: *{user_timers['focus']} min*\n"
        f"Descanso Curto: *{user_timers['short_break']} min*\n"
        f"Descanso Longo: *{user_timers['long_break']} min*\n"
        f"Ciclos por Longo Descanso: *{user_timers['cycles']}*\n\n"
        f"Status: {status_text}\n\n"
        "Vamos focar e ser superprodutivos! Escolha uma opção:"
    )

    if update.callback_query:
        await update.callback_query.answer()
        # Verificar antes de editar
        current_message_text = update.callback_query.message.text
        current_message_markup = update.callback_query.message.reply_markup

        current_buttons = [[b.to_dict() for b in row] for row in current_message_markup.inline_keyboard] if current_message_markup else []
        new_buttons = [[b.to_dict() for b in row] for row in markup.inline_keyboard] if markup else []

        if current_message_text == message_text and current_buttons == new_buttons:
            logger.info(f"Mensagem do Pomodoro para {chat_id} não modificada. Evitando re-edição.")
            return
        else:
            await update.callback_query.edit_message_text(message_text, reply_markup=markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(message_text, reply_markup=markup, parse_mode='Markdown')
    logger.info(f"Usuário {chat_id} abriu o menu Pomodoro.")

async def pomodoro_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exibe o status detalhado do Pomodoro atual."""
    chat_id = str(update.effective_chat.id)
    current_status = pomodoro_status_map.get(chat_id)

    if not current_status or current_status["state"] == "idle":
        message = "😌 Nenhum Pomodoro em andamento. Use /pomodoro para começar a focar! 💪"
    elif current_status["state"] == "paused":
        paused_remaining_time = current_status.get("paused_remaining_time", 0)
        remaining_minutes = max(0, int(paused_remaining_time / 60))
        remaining_seconds = max(0, int(paused_remaining_time % 60))
        message = (
            f"🚀 *Status do Pomodoro:*\n"
            f"Estado: *PAUSADO* ⏸️\n"
            f"Tempo Restante (pausado): *{remaining_minutes:02d}m {remaining_seconds:02d}s*\n\n"
            "Quando estiver pronto, clique em 'Retomar' para continuar a produtividade! ✨"
        )
    else:
        state = current_status["state"]
        remaining_time_seconds = 0
        if current_status.get("end_time"):
            remaining_time_seconds = (current_status["end_time"] - datetime.datetime.now(SAO_PAULO_TZ)).total_seconds()
            remaining_time_seconds = max(0, remaining_time_seconds)

        remaining_minutes = int(remaining_time_seconds / 60)
        remaining_seconds = int(remaining_time_seconds % 60)

        message = (
            f"🚀 *Status do Pomodoro:*\n"
            f"Estado: *{state.replace('_', ' ').capitalize()}*\n"
            f"Ciclo Atual: *{current_status['current_cycle']}*\n"
            f"Tempo Restante: *{remaining_minutes:02d}m {remaining_seconds:02d}s*\n\n"
            "Mantenha o ritmo! Você está no caminho certo! ✨"
        )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(message, parse_mode='Markdown')
    else:
        await update.message.reply_text(message, parse_mode='Markdown')
    logger.info(f"Usuário {chat_id} solicitou status do Pomodoro.")

async def pomodoro_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Para o Pomodoro e exibe o relatório final da sessão."""
    chat_id = str(update.effective_chat.id)
    current_status = pomodoro_status_map.get(chat_id)

    if current_status and current_status["state"] != "idle":
        if current_status.get("job"):
            current_status["job"].schedule_removal()

        if current_status.get("start_time_of_phase") and current_status["state"] not in ["idle", "paused"]:
            elapsed_time_in_phase = (datetime.datetime.now(SAO_PAULO_TZ) - current_status["start_time_of_phase"]).total_seconds()
            if current_status["state"] == "focus":
                current_status["focused_time_total"] += elapsed_time_in_phase
            elif current_status["state"] == "short_break":
                current_status["short_break_time_total"] += elapsed_time_in_phase
            elif current_status["state"] == "long_break":
                current_status["long_break_time_total"] += elapsed_time_in_phase

        total_focused_seconds = current_status.get("focused_time_total", 0)
        total_short_break_seconds = current_status.get("short_break_time_total", 0)
        total_long_break_seconds = current_status.get("long_break_time_total", 0)
        session_start_time = current_status.get("session_start_time")

        focused_h = int(total_focused_seconds // 3600)
        focused_m = int((total_focused_seconds % 3600) // 60)

        short_break_m = int(total_short_break_seconds // 60)
        long_break_m = int(total_long_break_seconds // 60)

        completed_cycles = current_status.get("current_cycle", 0)

        total_session_seconds = 0
        if session_start_time:
            total_session_seconds = (datetime.datetime.now(SAO_PAULO_TZ) - session_start_time).total_seconds()
        total_session_h = int(total_session_seconds // 3600)
        total_session_m = int((total_session_seconds % 3600) // 60)

        report_message = (
            f"🧾 *Relatório Final do Pomodoro* 🧾\n"
            f"---------------------------\n"
            f"⏱️ *Tempo Focado Total*: {focused_h}h {focused_m:02d}min\n"
            f"    _(Ciclos concluídos: {completed_cycles})_\n"
            f"☕ *Pausas Curtas*: {short_break_m} min\n"
            f"💤 *Pausa Longa*: {long_break_m} min\n"
            f"---------------------------\n"
            f"⏳ *Sessão Total*: {total_session_h}h {total_session_m:02d}min\n\n"
            f"Mandou muito bem! 👏 Continue assim para alcançar seus objetivos! ✨"
        )

        pomodoro_status_map[chat_id] = {
            "state": "idle",
            "job": None,
            "current_cycle": 0,
            "end_time": None,
            "focused_time_total": 0,
            "short_break_time_total": 0,
            "long_break_time_total": 0,
            "session_start_time": None
        }

        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(report_message, parse_mode='Markdown')
            await pomodoro_menu(update, context) # Volta ao menu do pomodoro
        else:
            await update.message.reply_text(report_message, parse_mode='Markdown')

        logger.info(f"Usuário {chat_id} parou o Pomodoro. Relatório final exibido.")
    else:
        message = "🚫 Não há Pomodoro em andamento para parar. Use /pomodoro para começar um! 😉"
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(message)
            await pomodoro_menu(update, context) # Volta ao menu do pomodoro
        else:
            await update.message.reply_text(message)
        logger.info(f"Usuário {chat_id} tentou parar Pomodoro, mas nenhum estava ativo.")

async def pomodoro_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler para os botões inline do menu do Pomodoro."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)

    user_timers = pomodoro_timers[chat_id]
    current_status = pomodoro_status_map.get(chat_id, {
        "state": "idle",
        "current_cycle": 0,
        "focused_time_total": 0,
        "short_break_time_total": 0,
        "long_break_time_total": 0,
        "session_start_time": None
    })

    if query.data == "pomodoro_start":
        if current_status["state"] != "idle":
            await query.edit_message_text("🔄 Já existe um Pomodoro em andamento! Se quiser reiniciar, pare o atual primeiro com o botão 'Parar Pomodoro'. 😉")
            return

        pomodoro_status_map[chat_id] = {
            "state": "focus",
            "current_cycle": 1,
            "start_time_of_phase": datetime.datetime.now(SAO_PAULO_TZ),
            "focused_time_total": 0,
            "short_break_time_total": 0,
            "long_break_time_total": 0,
            "session_start_time": datetime.datetime.now(SAO_PAULO_TZ)
        }
        await start_pomodoro_timer(chat_id, "focus", user_timers["focus"], context.job_queue)
        await query.edit_message_text(f"🚀 Pomodoro Iniciado! Foco total por *{user_timers['focus']} minutos*! Você consegue! 💪", parse_mode='Markdown')
        logger.info(f"Usuário {chat_id} iniciou o Pomodoro (Ciclo 1).")

    elif query.data == "pomodoro_pause":
        if current_status["state"] not in ["idle", "paused"] and current_status.get("job"):
            if current_status.get("end_time") and current_status.get("start_time_of_phase"):
                remaining_time_seconds = (current_status["end_time"] - datetime.datetime.now(SAO_PAULO_TZ)).total_seconds()
                remaining_time_seconds = max(0, remaining_time_seconds)

                elapsed_time_in_phase = (datetime.datetime.now(SAO_PAULO_TZ) - current_status["start_time_of_phase"]).total_seconds()
                current_timer_type = current_status["state"]
                if current_timer_type == "focus":
                    current_status["focused_time_total"] += elapsed_time_in_phase
                elif current_timer_type == "short_break":
                    current_status["short_break_time_total"] += elapsed_time_in_phase
                elif current_timer_type == "long_break":
                    current_status["long_break_time_total"] += elapsed_time_in_phase

                pomodoro_status_map[chat_id]["paused_remaining_time"] = remaining_time_seconds
                pomodoro_status_map[chat_id]["previous_timer_type"] = current_status["state"]

                current_status["job"].schedule_removal()
                pomodoro_status_map[chat_id]["state"] = "paused"
                pomodoro_status_map[chat_id]["job"] = None

                await query.edit_message_text(f"⏸️ Pomodoro pausado! Tempo restante: *{int(remaining_time_seconds/60):02d}m {int(remaining_time_seconds%60):02d}s*.\n\n"
                                             "Quando estiver pronto, clique em Retomar!", parse_mode='Markdown')
                logger.info(f"Usuário {chat_id} pausou o Pomodoro com {remaining_time_seconds} segundos restantes.")
            else:
                await query.edit_message_text("❌ Ops, não consegui calcular o tempo restante para pausar. Tente novamente ou pare o Pomodoro.")
                logger.error(f"Erro ao pausar Pomodoro para {chat_id}: end_time ou start_time_of_phase não encontrado.")
        else:
            await query.edit_message_text("🤔 Não há Pomodoro ativo para pausar. Que tal começar um novo? 😉")

    elif query.data == "pomodoro_resume":
        if current_status["state"] == "paused" and "paused_remaining_time" in current_status:
            remaining_time_seconds = current_status["paused_remaining_time"]
            inferred_timer_type = current_status.get("previous_timer_type", "focus")

            if remaining_time_seconds < 5:
                await handle_pomodoro_end_callback(context) # Chama diretamente o fim
                await query.edit_message_text("⌛ Tempo muito baixo para retomar, avançando para o próximo ciclo!", parse_mode='Markdown')
                logger.info(f"Usuário {chat_id} tentou retomar Pomodoro com tempo mínimo. Avançando para o próximo ciclo.")
                return

            pomodoro_status_map[chat_id]["start_time_of_phase"] = datetime.datetime.now(SAO_PAULO_TZ)
            pomodoro_status_map[chat_id]["state"] = inferred_timer_type

            await start_pomodoro_timer(chat_id, inferred_timer_type, remaining_time_seconds / 60, context.job_queue, is_resume=True)
            await query.edit_message_text(f"▶️ Pomodoro retomado! Foco e energia total! 💪", parse_mode='Markdown')
            logger.info(f"Usuário {chat_id} retomou o Pomodoro com {remaining_time_seconds} segundos restantes (tipo: {inferred_timer_type}).")
        else:
            await query.edit_message_text("🤔 Não há Pomodoro pausado para retomar. Que tal iniciar um novo ciclo? 😉")

    elif query.data == "pomodoro_stop_command":
        await pomodoro_stop(update, context)

    elif query.data == "pomodoro_config_times":
        keyboard = [
            [InlineKeyboardButton(f"Foco: {user_timers['focus']} min", callback_data="set_pomodoro_focus")],
            [InlineKeyboardButton(f"Descanso Curto: {user_timers['short_break']} min", callback_data="set_pomodoro_short_break")],
            [InlineKeyboardButton(f"Descanso Longo: {user_timers['long_break']} min", callback_data="set_pomodoro_long_break")],
            [InlineKeyboardButton(f"Ciclos p/ Descanso Longo: {user_timers['cycles']}", callback_data="set_pomodoro_cycles")],
            [InlineKeyboardButton("↩️ Voltar ao Pomodoro", callback_data="menu_pomodoro")],
        ]
        markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("⚙️ *Configurar Tempos do Pomodoro*\n\n"
                                     "Clique para alterar:", reply_markup=markup, parse_mode='Markdown')
        logger.info(f"Usuário {chat_id} acessou configurações do Pomodoro.")

    elif query.data == "pomodoro_status_command":
        await pomodoro_status(update, context)

    elif query.data == "menu_pomodoro":
        await pomodoro_menu(update, context)

async def pomodoro_set_time_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prepara o bot para receber a nova duração de uma fase do Pomodoro."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)

    setting_type = query.data.replace("set_pomodoro_", "")

    context.user_data["expecting"] = f"pomodoro_set_{setting_type}"
    context.user_data["pomodoro_setting_type"] = setting_type

    if setting_type == "cycles":
        await query.edit_message_text("🔢 Por favor, digite quantos ciclos de foco você quer fazer antes de um descanso longo (ex: '4').")
    else:
        await query.edit_message_text(f"⏱️ Digite o novo tempo em minutos para o *{setting_type.replace('_', ' ')}* (ex: '25').", parse_mode='Markdown')
    logger.info(f"Usuário {chat_id} iniciou configuração de '{setting_type}' para Pomodoro.")

async def start_pomodoro_timer(chat_id: str, timer_type: str, duration_minutes: float, job_queue: JobQueue, is_resume: bool = False):
    """Inicia o timer de Pomodoro para a fase e duração especificadas."""
    duration_seconds = int(duration_minutes * 60)

    if duration_seconds <= 0:
        logger.warning(f"Duração inválida ({duration_seconds}s) para o timer Pomodoro '{timer_type}' no chat {chat_id}. Não agendando. Simula fim.")
        job_context = type('obj', (object,), {'job': type('obj', (object,), {'chat_id' : int(chat_id), 'data': {"timer_type": timer_type}})()})()
        asyncio.create_task(handle_pomodoro_end_callback(job_context))
        return

    def pomodoro_job_callback_wrapper(job_context: ContextTypes.DEFAULT_TYPE):
        asyncio.create_task(handle_pomodoro_end_callback(job_context))

    end_time = datetime.datetime.now(SAO_PAULO_TZ) + datetime.timedelta(seconds=duration_seconds)

    job = job_queue.run_once(
        pomodoro_job_callback_wrapper,
        duration_seconds,
        chat_id=int(chat_id),
        data={"timer_type": timer_type, "chat_id": chat_id},
        name=f"pomodoro_timer_{chat_id}_{timer_type}_{datetime.datetime.now().timestamp()}" # Nome único
    )

    pomodoro_status_map[chat_id]["job"] = job
    pomodoro_status_map[chat_id]["state"] = timer_type
    pomodoro_status_map[chat_id]["end_time"] = end_time
    if not is_resume:
        pomodoro_status_map[chat_id]["start_time_of_phase"] = datetime.datetime.now(SAO_PAULO_TZ)

    logger.info(f"Job Pomodoro '{timer_type}' agendado para {duration_seconds} segundos para o chat {chat_id}. (Resume: {is_resume})")

async def handle_pomodoro_end_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback executado quando uma fase do Pomodoro termina."""
    chat_id = str(context.job.chat_id)
    timer_type = context.job.data["timer_type"]
    user_timers = pomodoro_timers[chat_id]
    current_status = pomodoro_status_map.get(chat_id)

    if not current_status or current_status["state"] == "idle":
        logger.warning(f"Pomodoro terminou para {chat_id} mas estado já é 'idle'. Ignorando.")
        return

    if current_status["state"] == "paused":
        logger.warning(f"Pomodoro para {chat_id} estava pausado e terminou. Ignorando a transição de estado automática.")
        return

    if current_status.get("start_time_of_phase"):
        elapsed_time_in_phase = (datetime.datetime.now(SAO_PAULO_TZ) - current_status["start_time_of_phase"]).total_seconds()
        if timer_type == "focus":
            current_status["focused_time_total"] += elapsed_time_in_phase
        elif timer_type == "short_break":
            current_status["short_break_time_total"] += elapsed_time_in_phase
        elif timer_type == "long_break":
            current_status["long_break_time_total"] += elapsed_time_in_phase

    current_status["start_time_of_phase"] = datetime.datetime.now(SAO_PAULO_TZ)

    message = ""
    next_state = "idle"
    next_duration = 0

    if timer_type == "focus":
        current_status["current_cycle"] += 1
        message = f"🔔 *Tempo de FOCO ACABOU!* 🎉 Você completou o ciclo {current_status['current_cycle']}! "

        db = load_data()
        user_data = db.setdefault(str(chat_id), {})
        user_data["score"] = user_data.get("score", 0) + 5
        save_data(db)
        message += f"\n\nVocê ganhou *5 pontos* por este ciclo! Pontuação total: *{user_data['score']}* 🌟"

        if current_status["current_cycle"] % user_timers["cycles"] == 0:
            message += f"\n\nAgora, é hora de um *Descanso LONGO* de *{user_timers['long_break']} minutos*! Você merece! 🧘"
            next_state = "long_break"
            next_duration = user_timers["long_break"]
        else:
            message += f"\n\nAgora, um *Descanso CURTO* de *{user_timers['short_break']} minutos* para recarregar! ☕"
            next_state = "short_break"
            next_duration = user_timers["short_break"]

    elif timer_type == "short_break":
        message = f"🚀 *Descanso CURTO ACABOU!* Hora de voltar para o foco! Mais *{user_timers['focus']} minutos*! 💪"
        next_state = "focus"
        next_duration = user_timers["focus"]

    elif timer_type == "long_break":
        message = f"🎉 *Descanso LONGO ACABOU!* Preparado para mais *{user_timers['focus']} minutos* de produtividade? Vamos lá! 🤩"
        current_status["current_cycle"] = 0
        next_state = "focus"
        next_duration = user_timers["focus"]

    await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
    logger.info(f"Pomodoro {timer_type} terminou para {chat_id}. Próximo estado: {next_state}.")

    if next_state != "idle":
        await start_pomodoro_timer(chat_id, next_state, next_duration, context.job_queue)
    else:
        pomodoro_status_map[chat_id] = {
            "state": "idle",
            "job": None,
            "current_cycle": 0,
            "end_time": None,
            "focused_time_total": 0,
            "short_break_time_total": 0,
            "long_break_time_total": 0,
            "session_start_time": None
        }
        await context.bot.send_message(chat_id=chat_id, text="🥳 Ciclo de Pomodoro completo! Parabéns pela dedicação! Use /pomodoro para iniciar um novo ciclo quando quiser. Você é um arraso! ✨", parse_mode='Markdown')


# --- Funções de Metas Semanais ---
async def set_weekly_goal_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando para iniciar a definição de uma meta semanal."""
    chat_id = str(update.effective_chat.id)
    context.user_data["expecting"] = "set_weekly_goal_description"
    # Decide se é para editar a mensagem existente ou enviar uma nova
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.edit_text(
            "🎯 Qual meta semanal você quer definir? Pode ser '10 Pomodoros de Foco', 'Concluir 5 tarefas importantes', etc. Seja específico! ✨"
        )
    else:
        await update.message.reply_text(
            "🎯 Qual meta semanal você quer definir? Pode ser '10 Pomodoros de Foco', 'Concluir 5 tarefas importantes', etc. Seja específico! ✨"
        )
    logger.info(f"Usuário {chat_id} iniciou a definição de uma meta semanal.")

async def handle_set_weekly_goal_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Recebe a descrição da meta semanal e a salva."""
    chat_id = str(update.effective_chat.id)
    goal_description = update.message.text.strip()

    if not goal_description:
        await update.message.reply_text("Ops! A descrição da meta não pode ser vazia. Por favor, digite sua meta novamente.")
        return

    db = load_data()
    user_data = db.setdefault(chat_id, {})
    weekly_goals = user_data.setdefault("weekly_goals", [])

    new_goal = {
        "id": str(uuid.uuid4()), # ID único para a meta
        "description": goal_description,
        "set_date": datetime.datetime.now(SAO_PAULO_TZ).isoformat(),
        "status": "active",
        "progress": 0,
        "target_value": None
    }

    num_match = re.search(r'(\d+)\s*(?:pomodoros?|tarefas?)', goal_description, re.IGNORECASE)
    if num_match:
        new_goal["target_value"] = int(num_match.group(1))

    weekly_goals.append(new_goal)
    save_data(db)

    await update.message.reply_text(
        f"🎯 Meta semanal *'{goal_description}'* definida! Vamos juntos nessa! 💪",
        parse_mode='Markdown'
    )
    context.user_data.pop("expecting", None)
    logger.info(f"Usuário {chat_id} definiu meta semanal: '{goal_description}'.")

async def view_weekly_goals_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exibe as metas semanais do usuário."""
    chat_id = str(update.effective_chat.id)
    db = load_data()
    user_data = db.setdefault(chat_id, {})
    weekly_goals = user_data.setdefault("weekly_goals", [])

    message = "🎯 *Suas Metas Semanais:*\n\n"

    if not weekly_goals:
        message += "Você ainda não definiu nenhuma meta semanal. Que tal criar uma agora? 😉"
    else:
        for idx, goal in enumerate(weekly_goals):
            description = goal['description']
            status = goal['status']
            progress = goal['progress']
            target = goal['target_value']
            goal_id = goal.get('id', 'N/A') # Pega o ID da meta

            status_icon = "✅" if status == "completed" else "⏳" if status == "active" else "❌"
            progress_text = f"Progresso: {progress}%"
            if target:
                progress_text = f"Meta: {target} (Progresso: {progress}%)"

            message += f"{idx+1}. {status_icon} *{description}*\n   _{progress_text} - Status: {status.capitalize()}_ `ID:{goal_id}`\n\n"

        message += "Use o menu para gerenciar suas metas."

    keyboard = [
        [InlineKeyboardButton("➕ Definir Nova Meta", callback_data="set_weekly_goal_command_cb")],
        [InlineKeyboardButton("✅ Marcar Meta Concluída", callback_data="select_goal_to_mark_done")], # Novo botão
        [InlineKeyboardButton("🗑️ Excluir Meta", callback_data="delete_weekly_goal_menu")],
        [InlineKeyboardButton("↩️ Voltar ao Menu Principal", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    new_text = message

    if update.callback_query:
        await update.callback_query.answer()
        current_message_text = update.callback_query.message.text
        current_message_markup = update.callback_query.message.reply_markup

        current_buttons = [[b.to_dict() for b in row] for row in current_message_markup.inline_keyboard] if current_message_markup else []
        new_buttons = [[b.to_dict() for b in row] for row in reply_markup.inline_keyboard] if reply_markup else []

        if current_message_text == new_text and current_buttons == new_buttons:
            logger.info(f"Mensagem de metas para {chat_id} não modificada. Evitando re-edição.")
            return
        else:
            await update.callback_query.edit_message_text(new_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(new_text, reply_markup=reply_markup, parse_mode='Markdown')
    logger.info(f"Usuário {chat_id} visualizou as metas semanais.")

async def set_weekly_goal_command_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback para iniciar a definição de meta a partir de um botão."""
    await update.callback_query.answer()
    await set_weekly_goal_command(update, context)

async def select_goal_to_mark_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Apresenta uma lista de metas ativas para o usuário marcar como concluída."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)

    db = load_data()
    user_data = db.setdefault(chat_id, {})
    weekly_goals = user_data.setdefault("weekly_goals", [])

    active_goals = [goal for goal in weekly_goals if goal.get("status") == "active"]

    if not active_goals:
        await query.edit_message_text("🎉 Todas as suas metas ativas já foram concluídas ou não há metas! 😊", parse_mode='Markdown')
        return

    message_text = "✅ *Qual meta você deseja marcar como concluída?*\n\n"
    keyboard = []

    for idx, goal in enumerate(active_goals):
        button_text = f"{idx+1}. {goal['description']}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"mark_goal_done_id_{goal['id']}")]) # Passa o ID

    keyboard.append([InlineKeyboardButton("↩️ Voltar", callback_data="view_weekly_goals_command")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')
    logger.info(f"Usuário {chat_id} acessou o menu para marcar metas como concluídas.")

async def mark_goal_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Marca uma meta específica como concluída (usando ID)."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)

    try:
        goal_id_to_mark = query.data.split("_id_")[1] # Pega o ID
    except IndexError:
        logger.error(f"Erro ao parsear ID do callback_data para marcar meta: {query.data}")
        await query.edit_message_text("❌ Erro ao identificar a meta para marcar como concluída. Por favor, tente novamente!")
        return

    db = load_data()
    user_data = db.setdefault(chat_id, {})
    weekly_goals = user_data.setdefault("weekly_goals", [])

    found_goal = None
    for goal in weekly_goals:
        if goal.get('id') == goal_id_to_mark:
            found_goal = goal
            break

    if found_goal:
        if found_goal.get('status') == 'active':
            found_goal['status'] = 'completed'
            found_goal['progress'] = 100 # Assume 100% ao marcar manualmente
            save_data(db)
            await query.edit_message_text(f"✅ Meta *'{found_goal['description']}'* marcada como concluída! Parabéns, você é incrível! 🎉", parse_mode='Markdown')
            logger.info(f"Meta '{found_goal['description']}' (ID: {goal_id_to_mark}) marcada como concluída para o usuário {chat_id}.")
            await view_weekly_goals_command(update, context) # Atualiza a lista de metas
        else:
            await query.edit_message_text(f"Esta meta já foi concluída ou não está ativa! 😉")
    else:
        await query.edit_message_text("🤔 Não encontrei essa meta para marcar como concluída. Ela pode já ter sido apagada ou não existe.")
        logger.warning(f"Tentativa de marcar meta com ID inválido {goal_id_to_mark} para o usuário {chat_id}.")

async def delete_weekly_goal_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Apresenta uma lista de metas semanais para o usuário apagar."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)

    db = load_data()
    user_data = db.setdefault(chat_id, {})
    weekly_goals = user_data.setdefault("weekly_goals", [])

    if not weekly_goals:
        await query.edit_message_text("😔 Não há metas semanais para apagar.", parse_mode='Markdown')
        return

    message_text = "🗑️ *Selecione qual meta você deseja apagar:*\n\n"
    keyboard = []

    for idx, goal in enumerate(weekly_goals):
        button_text = f"{idx+1}. {goal['description']}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"delete_weekly_goal_confirm_id_{goal['id']}")]) # Passa o ID

    keyboard.append([InlineKeyboardButton("↩️ Voltar", callback_data="view_weekly_goals_command")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')
    logger.info(f"Usuário {chat_id} acessou o menu para apagar metas semanais.")

# NOTE: A função `delete_meta_callback` foi renomeada para `delete_weekly_goal_confirm_callback`
# para refletir a mudança no `callback_data` e no escopo de "metas semanais".
# Verifique se o handler está registrando esta função com o padrão correto.

# --- Funções de Menu Principal e Relatórios ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inicia a conversa e exibe o menu principal."""
    await main_menu(update, context)

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exibe o menu principal do bot."""
    keyboard = [
        [InlineKeyboardButton("📋 Minhas Tarefas", callback_data="list_tasks_all")],
        [InlineKeyboardButton("⏰ Pomodoro", callback_data="menu_pomodoro")],
        [InlineKeyboardButton("📚 Rotina Semanal", callback_data="show_weekly_routine_command")], # Callback Data ajustado
        [InlineKeyboardButton("🎯 Minhas Metas", callback_data="view_weekly_goals_command")],
        [InlineKeyboardButton("📊 Relatórios", callback_data="show_reports_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_text = "Olá! Como posso te ajudar hoje a ser mais produtivo? 😊"

    if update.callback_query:
        await update.callback_query.answer() # Importante para callbacks
        # Compara texto e markup antes de editar
        current_message_text = update.callback_query.message.text
        current_message_markup = update.callback_query.message.reply_markup

        current_buttons = [[b.to_dict() for b in row] for row in current_message_markup.inline_keyboard] if current_message_markup else []
        new_buttons = [[b.to_dict() for b in row] for row in reply_markup.inline_keyboard] if reply_markup else []

        if current_message_text == message_text and current_buttons == new_buttons:
            logger.info(f"Mensagem do menu principal para {update.effective_chat.id} não modificada. Evitando re-edição.")
            return
        else:
            await update.callback_query.message.edit_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_reports_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exibe o menu de relatórios de produtividade."""
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("✨ Feedback Diário", callback_data="get_daily_feedback")],
        [InlineKeyboardButton("📈 Feedback Semanal", callback_data="get_weekly_feedback")],
        [InlineKeyboardButton("↩️ Voltar ao Menu Principal", callback_data="main_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("📊 *Relatórios de Produtividade*\n\nEscolha um relatório para visualizar seu progresso!", reply_markup=reply_markup, parse_mode='Markdown')

async def get_daily_feedback_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback para gerar e enviar o feedback diário manualmente."""
    await update.callback_query.answer("Gerando relatório diário...")
    context.job = type('obj', (object,), {'chat_id' : update.effective_chat.id})()
    await send_daily_feedback(context)

async def get_weekly_feedback_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback para gerar e enviar o feedback semanal manualmente."""
    await update.callback_query.answer("Gerando relatório semanal...")
    context.job = type('obj', (object,), {'chat_id' : update.effective_chat.id})()
    await send_weekly_feedback(context)

async def post_init(application: Application):
    """Executado após a inicialização do bot para carregar dados e re-agendar jobs."""
    logger.info("Função post_init sendo executada.")
    db = load_data()
    for chat_id_str, user_data in db.items():
        chat_id = int(chat_id_str)
        tarefas = user_data.get("tarefas", [])
        
        # Re-agenda tarefas recorrentes e avulsas (se tiverem data/hora futura e não estiverem concluídas)
        for task in tarefas:
            if not task.get('done') and task.get('start_when'):
                try:
                    start_dt_aware = datetime.datetime.fromisoformat(task['start_when']).astimezone(SAO_PAULO_TZ)
                    if task.get('recurring') or start_dt_aware > datetime.datetime.now(SAO_PAULO_TZ):
                        # Importante: o job_names na tarefa deve ser limpo antes de reagendar para evitar duplicatas
                        # e ser populado pela função schedule_single_task_jobs
                        task["job_names"] = [] 
                        await schedule_single_task_jobs(chat_id_str, task, None, application.job_queue)
                except (ValueError, TypeError) as e:
                    logger.error(f"Erro ao re-agendar tarefa '{task.get('activity')}' para {chat_id_str}: {e}")
    logger.info("Re-agendamento de jobs concluído durante post_init.")


def main() -> None:
    """Inicia o bot."""
    # Substitua 'YOUR_BOT_TOKEN' pelo token real do seu bot
    token = "YOUR_BOT_TOKEN" 
    
    application = Application.builder().token(token).post_init(post_init).build()

    # Handlers de Comandos
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("pomodoro", pomodoro_menu))
    application.add_handler(CommandHandler("listtasks", show_tasks_command))
    application.add_handler(CommandHandler("setroutine", handle_weekly_routine_input))
    application.add_handler(CommandHandler("viewroutine", show_weekly_routine_command))
    application.add_handler(CommandHandler("setgoal", set_weekly_goal_command))
    application.add_handler(CommandHandler("viewgoals", view_weekly_goals_command))


    # Handlers de Callbacks de Botões
    application.add_handler(CallbackQueryHandler(main_menu, pattern="^main_menu$"))
    application.add_handler(CallbackQueryHandler(pomodoro_menu, pattern="^menu_pomodoro$"))
    application.add_handler(CallbackQueryHandler(pomodoro_callback, pattern="^pomodoro_"))
    application.add_handler(CallbackQueryHandler(pomodoro_set_time_callback, pattern="^set_pomodoro_"))
    
    # Tarefas
    application.add_handler(CallbackQueryHandler(list_tasks, pattern="^list_tasks_"))
    application.add_handler(CallbackQueryHandler(add_new_task_menu, pattern="^add_new_task_menu$"))
    application.add_handler(CallbackQueryHandler(select_task_to_mark_done, pattern="^select_task_to_mark_done$"))
    application.add_handler(CallbackQueryHandler(select_task_to_delete, pattern="^select_task_to_delete$"))
    
    # Callback para ações de tarefa (agora usam ID)
    application.add_handler(CallbackQueryHandler(mark_done_callback, pattern="^(mark_done_id_|feedback_yes_id_|feedback_no_id_|feedback_postpone_id_|feedback_delete_id_).*"))
    application.add_handler(CallbackQueryHandler(delete_task_callback, pattern="^delete_task_id_.*"))
    
    # Rotina Semanal
    application.add_handler(CallbackQueryHandler(show_weekly_routine_command, pattern="^show_weekly_routine_command$")) # Correção de padrão
    application.add_handler(CallbackQueryHandler(edit_full_weekly_routine_callback, pattern="^edit_full_weekly_routine$"))
    application.add_handler(CallbackQueryHandler(delete_item_weekly_routine_callback, pattern="^delete_item_weekly_routine$"))
    application.add_handler(CallbackQueryHandler(delete_routine_task_confirm_callback, pattern="^delete_routine_task_by_id_.*")) # Usando ID
    application.add_handler(CallbackQueryHandler(view_weekly_routine_menu_callback, pattern="^view_weekly_routine_menu$"))

    # Metas Semanais
    application.add_handler(CallbackQueryHandler(view_weekly_goals_command, pattern="^view_weekly_goals_command$"))
    application.add_handler(CallbackQueryHandler(set_weekly_goal_command_cb, pattern="^set_weekly_goal_command_cb$"))
    application.add_handler(CallbackQueryHandler(delete_weekly_goal_menu, pattern="^delete_weekly_goal_menu$"))
    application.add_handler(CallbackQueryHandler(delete_weekly_goal_confirm_callback, pattern="^delete_weekly_goal_confirm_id_.*")) # Usando ID
    application.add_handler(CallbackQueryHandler(select_goal_to_mark_done, pattern="^select_goal_to_mark_done$")) # Novo
    application.add_handler(CallbackQueryHandler(mark_goal_done_callback, pattern="^mark_goal_done_id_.*")) # Novo

    # Relatórios
    application.add_handler(CallbackQueryHandler(show_reports_menu, pattern="^show_reports_menu$"))
    application.add_handler(CallbackQueryHandler(get_daily_feedback_callback, pattern="^get_daily_feedback$"))
    application.add_handler(CallbackQueryHandler(get_weekly_feedback_callback, pattern="^get_weekly_feedback$"))


    # Handler para entradas de texto genéricas
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))

    # Iniciar o bot
    logger.info("Bot iniciando polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
