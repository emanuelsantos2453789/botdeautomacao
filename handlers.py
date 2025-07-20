import datetime
import pytz
import re
import json
from collections import defaultdict
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, JobQueue
import asyncio
import logging

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
            return json.load(f)
    except FileNotFoundError:
        logger.info("Arquivo 'dados.json' não encontrado. Criando um novo.")
        return {}
    except json.JSONDecodeError:
        logger.error("Erro ao decodificar JSON em dados.json. Retornando dados vazios.")
        return {}

def save_data(data):
    """Salva os dados no arquivo JSON."""
    with open('dados.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

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
    for job_name in job_names:
        # Usa um padrão mais flexível para capturar jobs criados com timestamps
        jobs_to_remove = job_queue.get_jobs_by_name(job_name)
        for job in jobs_to_remove:
            if job.chat_id == int(chat_id): # Garante que o job pertence a este chat_id
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

            # Atualiza o dicionário em memória também, para consistência
            pomodoro_timers[chat_id][setting_type] = value

            await update.message.reply_text(f"✅ Tempo de *{setting_type.replace('_', ' ')}* definido para *{value} minutos*! 🎉", parse_mode='Markdown')

            context.user_data.pop("expecting", None)
            context.user_data.pop("pomodoro_setting_type", None)
            await pomodoro_menu(update, context) # Reabre o menu do Pomodoro
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
        task_idx = context.user_data.get("task_idx_for_reason")
        db = load_data()
        user_data = db.setdefault(chat_id, {})
        tarefas = user_data.setdefault("tarefas", [])

        if task_idx is not None and 0 <= task_idx < len(tarefas):
            tarefas[task_idx]["reason_not_completed"] = text
            tarefas[task_idx]["completion_status"] = "not_completed_with_reason"
            tarefas[task_idx]["done"] = False
            save_data(db)
            await update.message.reply_text(
                f"✍️ Entendido! O motivo para a não conclusão de *'{tarefas[task_idx]['activity']}'* foi registrado. Obrigado pelo feedback! Vamos melhorar juntos! 💪",
                parse_mode='Markdown'
            )
            logger.info(f"Motivo de não conclusão registrado para tarefa {tarefas[task_idx]['activity']}: {text}")
        else:
            await update.message.reply_text("🤔 Não consegui vincular o motivo a uma tarefa. Por favor, tente novamente ou use o menu para marcar tarefas.")
            logger.warning(f"Motivo de não conclusão recebido sem task_idx válido ou tarefa não encontrada para {chat_id}. Texto: {text}")

        context.user_data.pop("expecting", None)
        context.user_data.pop("task_idx_for_reason", None)
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


    logger.info(f"Texto '{text}' recebido sem estado 'expecting'.")
    await update.message.reply_text(
        "👉 Use /rotina para abrir o menu e escolher uma opção. Estou aqui para te ajudar a organizar seu dia e alcançar seus objetivos! 😉"
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

    if cmd.startswith("mark_done_") or cmd.startswith("feedback_yes_"):
        try:
            # Extrai o índice da tarefa do callback_data
            idx = int(cmd.split("_")[-1]) # Pega o último elemento depois de splitar por '_'
        except (IndexError, ValueError):
            logger.error(f"Erro ao parsear índice do callback_data: {cmd}")
            await query.edit_message_text("❌ Erro ao identificar a tarefa. Por favor, tente novamente!")
            return

        if 0 <= idx < len(tarefas):
            if not tarefas[idx].get('done'):
                tarefas[idx]["done"] = True
                # Define o status de conclusão com base na origem
                tarefas[idx]["completion_status"] = "completed_manually" if cmd.startswith("mark_done_") else "completed_on_time"
                tarefas[idx]["reason_not_completed"] = None

                user_data["score"] = user_data.get("score", 0) + 10
                logger.info(f"Usuário {chat_id} ganhou 10 pontos. Pontuação atual: {user_data['score']}.")

                cancel_task_jobs(chat_id, tarefas[idx].get("job_names", []), context.job_queue)

                save_data(db)
                await query.edit_message_text(
                    f"✅ EBA! Tarefa *“{tarefas[idx]['activity']}”* marcada como concluída! Mandou muito bem! 🎉 Você ganhou 10 pontos! 🌟"
                )
                logger.info(f"Tarefa '{tarefas[idx]['activity']}' marcada como concluída para o usuário {chat_id}.")
            else:
                await query.edit_message_text(f"Esta tarefa já foi marcada como concluída! Que eficiência! 😉")
        else:
            await query.edit_message_text("❌ Não encontrei essa tarefa para marcar como concluída. Ela pode já ter sido concluída ou apagada. 🤔")
            logger.warning(f"Tentativa de marcar tarefa com índice inválido {idx} para o usuário {chat_id}.")
        context.user_data.pop("expecting", None) # Limpa o estado após feedback
        return

    if cmd.startswith("feedback_no_"):
        try:
            task_idx = int(cmd.split("_")[2])
        except (IndexError, ValueError):
            logger.error(f"Erro ao parsear índice do callback_data: {cmd}")
            await query.edit_message_text("❌ Erro ao identificar a tarefa para feedback. Que pena! 😔")
            return

        if task_idx is not None and 0 <= task_idx < len(tarefas):
            if not tarefas[task_idx].get('done'):
                tarefas[task_idx]["completion_status"] = "not_completed_awaiting_reason"
                tarefas[task_idx]["done"] = False
                save_data(db)

                cancel_task_jobs(chat_id, tarefas[task_idx].get("job_names", []), context.job_queue)

                context.user_data["expecting"] = "reason_for_not_completion"
                context.user_data["task_idx_for_reason"] = task_idx
                await query.edit_message_text(f"😔 Ah, que pena! A tarefa *'{tarefas[task_idx]['activity']}'* não foi concluída. Por favor, digite o motivo: foi um imprevisto, falta de tempo, ou algo mais? Me conta para aprendermos juntos! 👇", parse_mode='Markdown')
                logger.info(f"Solicitando motivo de não conclusão para a tarefa '{tarefas[task_idx]['activity']}'.")
            else:
                await query.edit_message_text(f"Esta tarefa já foi concluída! Que bom! 😊")
        else:
            await query.edit_message_text("🤔 Não encontrei a tarefa para registrar o motivo. Ela pode já ter sido concluída ou apagada. Por favor, tente novamente!")
            logger.warning(f"Não encontrei tarefa com índice {task_idx} para solicitar motivo de não conclusão via feedback 'Não'.")
        return
    
    if cmd.startswith("feedback_postpone_"):
        try:
            task_idx = int(cmd.split("_")[2])
        except (IndexError, ValueError):
            logger.error(f"Erro ao parsear índice do callback_data: {cmd}")
            await query.edit_message_text("❌ Erro ao identificar a tarefa para adiar. Que pena! 😔")
            return

        if task_idx is not None and 0 <= task_idx < len(tarefas):
            task = tarefas[task_idx]
            if not task.get('done'):
                now_aware = datetime.datetime.now(SAO_PAULO_TZ)
                
                if task.get('start_when'):
                    original_start_dt_naive = datetime.datetime.fromisoformat(task['start_when'])
                    original_time = original_start_dt_naive.time()
                    
                    new_start_dt_naive = datetime.datetime.combine(now_aware.date() + datetime.timedelta(days=1), original_time)
                    new_start_dt_aware = SAO_PAULO_TZ.localize(new_start_dt_naive)
                    
                    if task.get('end_when'):
                        original_end_dt_naive = datetime.datetime.fromisoformat(task['end_when'])
                        original_end_time = original_end_dt_naive.time()
                        new_end_dt_naive = datetime.datetime.combine(now_aware.date() + datetime.timedelta(days=1), original_end_time)
                        new_end_dt_aware = SAO_PAULO_TZ.localize(new_end_dt_naive)
                        if new_end_dt_aware < new_start_dt_aware:
                            new_end_dt_aware += datetime.timedelta(days=1)
                        task['end_when'] = new_end_dt_aware.isoformat()
                    else:
                        task['end_when'] = None
                else:
                    new_start_dt_naive = datetime.datetime.combine(now_aware.date() + datetime.timedelta(days=1), datetime.time(9,0)) # Adia para 9h do dia seguinte
                    new_start_dt_aware = SAO_PAULO_TZ.localize(new_start_dt_naive)
                    task['end_when'] = None

                task['start_when'] = new_start_dt_aware.isoformat()
                task["completion_status"] = "postponed"
                task["reason_not_completed"] = "Adiada pelo usuário"
                task["done"] = False

                cancel_task_jobs(chat_id, task.get("job_names", []), context.job_queue)
                task["job_names"] = [] # Limpa a lista de job_names antigos
                await schedule_single_task_jobs(chat_id, task, task_idx, context.job_queue)
                
                save_data(db)
                await query.edit_message_text(f"↩️ A tarefa *'{task['activity']}'* foi adiada para *amanhã às {new_start_dt_aware.strftime('%H:%M')}*! Sem problemas, vamos juntos! 💪", parse_mode='Markdown')
                logger.info(f"Tarefa '{task['activity']}' adiada para o usuário {chat_id}.")
            else:
                await query.edit_message_text(f"Esta tarefa já foi concluída! Ótimo trabalho! 😉")
        else:
            await query.edit_message_text("🤔 Não encontrei a tarefa para adiar. Ela pode já ter sido concluída ou apagada. Por favor, tente novamente!")
            logger.warning(f"Não encontrei tarefa com índice {task_idx} para adiar via feedback.")
        context.user_data.pop("expecting", None)
        return

    if cmd.startswith("feedback_delete_"):
        try:
            task_idx = int(cmd.split("_")[2])
        except (IndexError, ValueError):
            logger.error(f"Erro ao parsear índice do callback_data: {cmd}")
            await query.edit_message_text("❌ Erro ao identificar a tarefa para apagar. Que pena! 😔")
            return
        
        # Reutiliza a lógica de apagar tarefa existente
        update.callback_query.data = f"delete_task_{task_idx}"
        await delete_task_callback(update, context)
        context.user_data.pop("expecting", None)
        return

async def delete_meta_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler para apagar metas."""
    query = update.callback_query
    await query.answer()

    chat_id = str(query.message.chat_id)
    db = load_data()
    user_data = db.setdefault(chat_id, {})
    metas = user_data.setdefault("metas", [])

    cmd = query.data
    logger.info(f"Usuário {chat_id} clicou em callback: {cmd}.")

    if cmd.startswith("delete_meta_"):
        try:
            idx = int(cmd.split("_")[2])
        except (IndexError, ValueError):
            logger.error(f"Erro ao parsear índice do callback_data para apagar meta: {cmd}")
            await query.edit_message_text("❌ Erro ao identificar a meta para apagar. Que chato! 😔")
            return

        if 0 <= idx < len(metas):
            deleted_meta = metas.pop(idx)
            save_data(db)
            await query.edit_message_text(f"🗑️ Meta *'{deleted_meta['activity']}'* apagada com sucesso! Uma a menos para se preocupar! 😉", parse_mode='Markdown')
            logger.info(f"Meta '{deleted_meta['activity']}' apagada para o usuário {chat_id}.")
        else:
            await query.edit_message_text("🤔 Essa meta não existe mais ou o índice está incorreto. Tente listar suas metas novamente!")
            logger.warning(f"Tentativa de apagar meta com índice inválido {idx} para o usuário {chat_id}.")
        return

async def delete_task_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler para apagar tarefas (não recorrentes)."""
    query = update.callback_query
    await query.answer()

    chat_id = str(query.message.chat_id)
    db = load_data()
    user_data = db.setdefault(chat_id, {})
    tarefas = user_data.setdefault("tarefas", [])

    cmd = query.data
    logger.info(f"Usuário {chat_id} clicou em callback: {cmd}.")

    if cmd.startswith("delete_task_"):
        try:
            idx = int(cmd.split("_")[2])
        except (IndexError, ValueError):
            logger.error(f"Erro ao parsear índice do callback_data para apagar tarefa: {cmd}")
            await query.edit_message_text("❌ Erro ao identificar a tarefa para apagar. Que pena! 😔")
            return

        if 0 <= idx < len(tarefas):
            deleted_task = tarefas.pop(idx)

            cancel_task_jobs(chat_id, deleted_task.get("job_names", []), context.job_queue)

            save_data(db)
            await query.edit_message_text(f"🗑️ Tarefa *'{deleted_task['activity']}'* apagada com sucesso! Menos uma preocupação! 😉", parse_mode='Markdown')
            logger.info(f"Tarefa '{deleted_task['activity']}' apagada para o usuário {chat_id}.")
        else:
            await query.edit_message_text("🤔 Essa tarefa não existe mais ou o índice está incorreto. Tente listar suas tarefas novamente!", parse_mode='Markdown')
            logger.warning(f"Tentativa de apagar tarefa com índice inválido {idx} para o usuário {chat_id}.")
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
            task_start_dt_naive = datetime.datetime.fromisoformat(task['start_when'])
            task_start_dt_aware = SAO_PAULO_TZ.localize(task_start_dt_naive)
            task_date = task_start_dt_aware.date()
        except (ValueError, TypeError):
            logger.warning(f"Data de início inválida para a tarefa: {task.get('activity')}. Pulando.")
            continue

        if task_date == today:
            if task.get('completion_status') in ['completed_on_time', 'completed_manually']:
                completed_tasks_today.append(task['activity'])
                # A pontuação já é adicionada no callback de conclusão, aqui só contamos para o resumo
            elif task.get('completion_status') in ['not_completed', 'not_completed_with_reason', 'postponed']:
                not_completed_tasks_today.append(task['activity'])
                if task.get('reason_not_completed'):
                    imprevistos_today.append(f"- *{task['activity']}*: {task['reason_not_completed']}")
            elif not task.get('done'): # Tarefa para hoje que não foi concluída/adiada
                tasks_to_ask_feedback.append({'activity': task['activity'], 'idx': idx})
    
    # Recalcular a pontuação do dia com base nas tarefas que foram *marcadas* como concluídas hoje
    # Seria mais preciso ter um histórico de score diário. Por simplicidade, somamos os pontos atuais.
    # Para o `daily_score_this_feedback`, seria ideal que cada `mark_done` ou `handle_pomodoro_end`
    # registrasse os pontos ganhos para o dia corrente.
    # Por ora, a `user_data["score"]` é a pontuação total.
    # Vou ajustar para somar as tarefas concluídas hoje para o "Score do Dia"
    for task_name in completed_tasks_today:
        daily_score_this_feedback += 10 # Cada tarefa concluída vale 10 pontos

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
            idx = task_info['idx']
            keyboard = [
                [InlineKeyboardButton("✅ Sim", callback_data=f"feedback_yes_{idx}"),
                 InlineKeyboardButton("❌ Não", callback_data=f"feedback_no_{idx}")],
                [InlineKeyboardButton("↩️ Adiar para amanhã", callback_data=f"feedback_postpone_{idx}"),
                 InlineKeyboardButton("🗑️ Excluir", callback_data=f"feedback_delete_{idx}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🤔 A tarefa *'{activity}'* estava agendada para hoje. Você a realizou?",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            logger.info(f"Solicitando feedback para tarefa '{activity}' (índice {idx}) para o usuário {chat_id}.")

async def send_weekly_feedback(context: ContextTypes.DEFAULT_TYPE):
    """Envia o feedback semanal consolidado ao usuário."""
    chat_id = str(context.job.chat_id)
    db = load_data()
    user_data = db.setdefault(chat_id, {})
    tarefas = user_data.setdefault("tarefas", [])

    now_aware = datetime.datetime.now(SAO_PAULO_TZ)
    # Encontrar o início da semana (Domingo)
    start_of_week = now_aware.date() - datetime.timedelta(days=(now_aware.weekday() + 1) % 7) # Domingo da semana corrente ou passada
    
    end_of_week = start_of_week + datetime.timedelta(days=6)

    total_focused_minutes_week = 0
    total_completed_tasks_week = 0
    total_postponed_tasks_week = 0
    total_not_completed_tasks_week = 0
    
    daily_productivity = defaultdict(int)
    
    # Days for graph display: Mon, Tue, ..., Sun
    day_names = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    
    for task in tarefas:
        try:
            if task.get('start_when'):
                task_start_dt_naive = datetime.datetime.fromisoformat(task['start_when'])
                task_start_dt_aware = SAO_PAULO_TZ.localize(task_start_dt_naive)
                task_date = task_start_dt_aware.date()
            else:
                continue # Pula tarefas sem data de início

        except (ValueError, TypeError):
            logger.warning(f"Data de início inválida para a tarefa: {task.get('activity')}. Pulando na análise semanal.")
            continue

        if start_of_week <= task_date <= end_of_week:
            if task.get('completion_status') in ['completed_on_time', 'completed_manually']:
                total_completed_tasks_week += 1
                # Adiciona 10 pontos por tarefa concluída para o gráfico de produtividade diária
                daily_productivity[task_date.strftime('%a')] += 10 
            elif task.get('completion_status') == 'postponed':
                total_postponed_tasks_week += 1
            elif task.get('completion_status') in ['not_completed', 'not_completed_with_reason']:
                total_not_completed_tasks_week += 1
            
            # Estimativa de tempo focado das tarefas concluídas
            if task.get('start_when') and task.get('end_when') and task.get('completion_status') in ['completed_on_time', 'completed_manually']:
                try:
                    start_dt = datetime.datetime.fromisoformat(task['start_when']).astimezone(SAO_PAULO_TZ)
                    end_dt = datetime.datetime.fromisoformat(task['end_when']).astimezone(SAO_PAULO_TZ)
                    duration_minutes = (end_dt - start_dt).total_seconds() / 60
                    if duration_minutes > 0:
                        total_focused_minutes_week += duration_minutes
                except (ValueError, TypeError):
                    pass

    # No futuro, se você salvar um histórico de pomodoros concluídos (tempo e data),
    # você somaria esse tempo aqui para `total_focused_minutes_week`.
    # Ex: for record in user_data.get("pomodoro_history", []):
    #         record_date = datetime.datetime.fromisoformat(record["date"]).date()
    #         if start_of_week <= record_date <= end_of_week:
    #             total_focused_minutes_week += record["focused_minutes"]

    focused_h_week = int(total_focused_minutes_week // 60)
    focused_m_week = int(total_focused_minutes_week % 60)

    feedback_message = f"✨ *Seu Feedback Semanal ({start_of_week.strftime('%d/%m')} - {end_of_week.strftime('%d/%m')})* ✨\n\n"
    feedback_message += f"✅ *Tarefas Concluídas*: {total_completed_tasks_week}\n"
    feedback_message += f"⏳ *Tarefas Adiadas*: {total_postponed_tasks_week}\n"
    feedback_message += f"❌ *Tarefas Não Concluídas*: {total_not_completed_tasks_week}\n"
    feedback_message += f"⏱️ *Tempo Focado Estimado*: {focused_h_week}h {focused_m_week:02d}min\n\n"
    
    feedback_message += "📈 *Desempenho Diário (Pontos)*:\n"
    max_score = max(daily_productivity.values()) if daily_productivity else 1 # Evitar divisão por zero
    graph_lines = []
    
    # Garante a ordem correta dos dias da semana
    for i in range(7):
        day_abbrev = day_names[i]
        score = daily_productivity.get(day_abbrev, 0)
        # Calcula o número de blocos para a barra de progresso (máximo de 10 blocos)
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

    # Obtém o filtro do callback_data ou do argumento do comando
    filter_type = context.args[0] if context.args else "all"
    if update.callback_query and update.callback_query.data.startswith("list_tasks_"):
        filter_type = update.callback_query.data.replace("list_tasks_", "")

    now_aware = datetime.datetime.now(SAO_PAULO_TZ)
    today = now_aware.date()
    tomorrow = today + datetime.timedelta(days=1)

    filtered_tasks = []

    for idx, task in enumerate(tarefas):
        include_task = False
        task_date = None

        if task.get('start_when'):
            try:
                task_start_dt_naive = datetime.datetime.fromisoformat(task['start_when'])
                task_start_dt_aware = SAO_PAULO_TZ.localize(task_start_dt_naive)
                task_date = task_start_dt_aware.date()
            except (ValueError, TypeError):
                logger.warning(f"Data de início inválida para a tarefa: {task.get('activity')}. Ignorando data/hora para filtragem.")
                task_date = None # Anula a data se for inválida
        
        # Lógica de filtragem
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

    if not filtered_tasks:
        message = f"😔 Nenhuma tarefa encontrada para o filtro *'{filter_type.replace('_', ' ').capitalize()}'*.\nQue tal adicionar uma nova?"
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.edit_text(message, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(build_task_filter_keyboard()))
        else:
            await update.message.reply_text(message, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(build_task_filter_keyboard()))
        return

    tasks_display = []
    for idx, task in filtered_tasks:
        activity = task['activity']
        start_when = task.get('start_when')
        end_when = task.get('end_when')
        done = task.get('done', False)
        recurring = task.get('recurring', False)
        priority = task.get('priority', 'Não definida')

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
        
        tasks_display.append(f"{idx}. {task_info}")
        
    message_header = f"📋 *Suas Tarefas Agendadas ({filter_type.replace('_', ' ').capitalize()})*:\n\n"
    message_body = "\n".join(tasks_display)

    reply_markup = InlineKeyboardMarkup(build_task_filter_keyboard())

    if update.callback_query:
        await update.callback_query.edit_message_text(message_header + message_body, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(message_header + message_body, reply_markup=reply_markup, parse_mode='Markdown')
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

# --- Funções de Rotina Semanal ---
async def handle_weekly_routine_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inicia o processo de definição da rotina semanal pedindo o texto ao usuário."""
    context.user_data["expecting"] = "weekly_routine_text"
    await (update.message or update.callback_query.message).reply_text(
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

    # Cancelar e remover jobs antigos de tarefas recorrentes antes de processar as novas
    tasks_to_keep = []
    jobs_to_cancel = []
    for task in tarefas:
        if task.get("recurring", False):
            jobs_to_cancel.extend(task.get("job_names", []))
        else:
            tasks_to_keep.append(task)
    
    cancel_task_jobs(chat_id, jobs_to_cancel, job_queue)
    tarefas[:] = tasks_to_keep # Limpa as tarefas recorrentes antigas

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

                # Calcula a próxima ocorrência da tarefa (para agendamento inicial)
                target_date = now_aware.date()
                while target_date.weekday() != current_day: # Encontra o próximo dia da semana
                    target_date += datetime.timedelta(days=1)

                temp_start_dt_naive = datetime.datetime.combine(target_date, start_time_obj)
                # Se a tarefa já passou no dia da semana atual, agenda para a próxima semana
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
                    "activity": activity_description,
                    "done": False,
                    "start_when": start_dt_aware.isoformat(),
                    "end_when": end_dt_aware.isoformat() if end_dt_aware else None,
                    "completion_status": None,
                    "reason_not_completed": None,
                    "recurring": True,
                    "job_names": []
                }
                tarefas.append(new_task_data)
                current_task_idx = len(tarefas) - 1

                # Agendar os jobs para esta tarefa recorrente
                await schedule_single_task_jobs(chat_id, new_task_data, current_task_idx, job_queue)
                
                scheduled_tasks_count += 1
                logger.info(f"    Agendada tarefa recorrente: '{activity_description}' para {start_dt_aware} (índice {current_task_idx}).")
                
    save_data(db)
    return scheduled_tasks_count

async def schedule_single_task_jobs(chat_id: str, task_data: dict, task_idx: int, job_queue: JobQueue):
    """Agenda os jobs (pré-início, início, fim) para uma única tarefa recorrente."""
    start_dt_aware = datetime.datetime.fromisoformat(task_data['start_when']).astimezone(SAO_PAULO_TZ)
    end_dt_aware = datetime.datetime.fromisoformat(task_data['end_when']).astimezone(SAO_PAULO_TZ) if task_data['end_when'] else None
    activity_description = task_data['activity']
    
    # job_names devem ser únicos e persistentes para a tarefa, para poderem ser cancelados.
    # Usaremos um timestamp inicial para garantir unicidade, mas o name base precisa ser previsível.
    # O `task_idx` aqui é o índice NO MOMENTO DO AGENDAMENTO, pode mudar se a lista for alterada.
    # Para jobs recorrentes, um ID da tarefa mais estável seria melhor (UUID).
    # Por simplicidade, vamos depender do `task_idx` e revalidar no handler do job.

    job_names_for_task = []
    now_aware = datetime.datetime.now(SAO_PAULO_TZ)

    # Alerta de 30 minutos antes
    pre_start_time = start_dt_aware - datetime.timedelta(minutes=30)
    if pre_start_time > now_aware: # Apenas agenda se o alerta ainda não passou
        pre_start_job_name = f"recurring_task_pre_start_{chat_id}_{task_idx}_{start_dt_aware.timestamp()}"
        job_queue.run_daily(
            send_task_alert,
            time=pre_start_time.time(), # Agendamento diário para o horário específico
            days=(pre_start_time.weekday(),), # No dia da semana correto (0=seg, ..., 6=dom)
            chat_id=int(chat_id),
            data={'description': activity_description, 'alert_type': 'pre_start', 'task_idx': task_idx, 'original_start_when': task_data['start_when']},
            name=pre_start_job_name
        )
        job_names_for_task.append(pre_start_job_name)
        logger.info(f"Job pré-alerta para '{activity_description}' agendado para {pre_start_time.strftime('%H:%M')} no dia {pre_start_time.weekday()}.")

    # Alerta de início da tarefa
    start_job_name = f"recurring_task_start_{chat_id}_{task_idx}_{start_dt_aware.timestamp()}"
    job_queue.run_daily(
        send_task_alert,
        time=start_dt_aware.time(),
        days=(start_dt_aware.weekday(),),
        chat_id=int(chat_id),
        data={'description': activity_description, 'alert_type': 'start', 'task_idx': task_idx, 'original_start_when': task_data['start_when']},
        name=start_job_name
    )
    job_names_for_task.append(start_job_name)
    logger.info(f"Job de início para '{activity_description}' agendado para {start_dt_aware.strftime('%H:%M')} no dia {start_dt_aware.weekday()}.")

    # Alerta de fim da tarefa (se houver)
    if end_dt_aware:
        end_job_name = f"recurring_task_end_{chat_id}_{task_idx}_{end_dt_aware.timestamp()}"
        job_queue.run_daily(
            send_task_alert,
            time=end_dt_aware.time(),
            days=(end_dt_aware.weekday(),),
            chat_id=int(chat_id),
            data={'description': activity_description, 'alert_type': 'end', 'task_idx': task_idx, 'original_start_when': task_data['start_when']},
            name=end_job_name
        )
        job_names_for_task.append(end_job_name)
        logger.info(f"Job de fim para '{activity_description}' agendado para {end_dt_aware.strftime('%H:%M')} no dia {end_dt_aware.weekday()}.")

    # Atualiza a tarefa no dicionário `task_data` com os nomes dos jobs
    # Isso é importante para poder cancelar os jobs depois
    task_data["job_names"].extend(job_names_for_task)

async def send_task_alert(context: ContextTypes.DEFAULT_TYPE):
    """Envia alertas de tarefas agendadas."""
    chat_id = context.job.chat_id
    data = context.job.data
    description = data['description']
    alert_type = data['alert_type']
    task_idx = data['task_idx']
    original_start_when = data['original_start_when'] # Para validar se a tarefa ainda é a mesma

    db = load_data()
    user_data = db.setdefault(str(chat_id), {})
    tarefas = user_data.setdefault("tarefas", [])

    # Valida se a tarefa ainda existe no mesmo índice e se a data de início é a mesma
    # para evitar enviar alertas para tarefas que foram apagadas ou alteradas na rotina
    if task_idx >= len(tarefas) or tarefas[task_idx].get('activity') != description or tarefas[task_idx].get('start_when') != original_start_when:
        logger.warning(f"Alerta para tarefa '{description}' (idx {task_idx}) ignorado. Tarefa não corresponde mais ou foi removida/alterada.")
        return # Não envia o alerta se a tarefa não for mais válida

    message = ""
    keyboard = []

    if alert_type == 'pre_start':
        message = f"🔔 Preparar para: *{description}*! Começa em 30 minutos! 😉"
    elif alert_type == 'start':
        message = f"🚀 *HORA DE: {description.upper()}!* Vamos com tudo! 💪"
        keyboard = [
            [InlineKeyboardButton("✅ Concluída", callback_data=f"feedback_yes_{task_idx}"),
             InlineKeyboardButton("❌ Não Concluída", callback_data=f"feedback_no_{task_idx}")]
        ]
    elif alert_type == 'end':
        message = f"✅ Tempo para *{description}* acabou! Você conseguiu? 🎉"
        keyboard = [
            [InlineKeyboardButton("✅ Sim, concluí!", callback_data=f"feedback_yes_{task_idx}"),
             InlineKeyboardButton("❌ Não concluí", callback_data=f"feedback_no_{task_idx}")]
        ]

    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    await context.bot.send_message(chat_id=chat_id, text=message, reply_markup=reply_markup, parse_mode='Markdown')
    logger.info(f"Alerta '{alert_type}' enviado para a tarefa '{description}' (índice {task_idx}) no chat {chat_id}.")

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
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.edit_text(message, parse_mode='Markdown')
        else:
            await update.message.reply_text(message, parse_mode='Markdown')
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
                "idx": idx
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
        await update.callback_query.edit_message_text(weekly_routine_message, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(weekly_routine_message, reply_markup=reply_markup, parse_mode='Markdown')
    logger.info(f"Usuário {chat_id} visualizou a rotina semanal.")

async def show_weekly_routine_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando para exibir a rotina semanal."""
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
    
    # Cancela todos os jobs associados às tarefas recorrentes
    cancel_task_jobs(chat_id, jobs_to_cancel_for_routine_reset, context.job_queue)
    tarefas[:] = tasks_to_keep # Limpa a lista de tarefas recorrentes, mantendo as não recorrentes
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
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"delete_routine_task_confirm_{idx_original}")])
            else:
                button_text = f"[Sem Horário] {task['activity']}"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"delete_routine_task_confirm_{idx_original}")])
        except (ValueError, TypeError):
             button_text = f"[Data Inválida] {task['activity']}"
             keyboard.append([InlineKeyboardButton(button_text, callback_data=f"delete_routine_task_confirm_{idx_original}")])


    keyboard.append([InlineKeyboardButton("↩️ Voltar", callback_data="view_weekly_routine_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')
    logger.info(f"Usuário {chat_id} acessou o menu para apagar itens da rotina.")

async def delete_routine_task_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirma e apaga um item específico da rotina semanal."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)
    
    try:
        idx_to_delete = int(query.data.split("_")[4])
    except (IndexError, ValueError):
        logger.error(f"Erro ao parsear índice do callback_data para apagar item da rotina: {query.data}")
        await query.edit_message_text("❌ Erro ao identificar o item da rotina para apagar. Por favor, tente novamente!")
        return

    db = load_data()
    user_data = db.setdefault(chat_id, {})
    tarefas = user_data.setdefault("tarefas", [])

    if 0 <= idx_to_delete < len(tarefas) and tarefas[idx_to_delete].get("recurring"):
        deleted_task = tarefas.pop(idx_to_delete)
        cancel_task_jobs(chat_id, deleted_task.get("job_names", []), context.job_queue)
        save_data(db)
        await query.edit_message_text(f"🗑️ O item da rotina *'{deleted_task['activity']}'* foi apagado com sucesso! 😉", parse_mode='Markdown')
        logger.info(f"Item da rotina '{deleted_task['activity']}' (idx {idx_to_delete}) apagado para o usuário {chat_id}.")
        
        await view_weekly_routine(update, context)
    else:
        await query.edit_message_text("🤔 Não encontrei esse item na sua rotina semanal. Ele pode já ter sido apagado.", parse_mode='Markdown')
        logger.warning(f"Tentativa de apagar item da rotina com índice inválido {idx_to_delete} ou não recorrente para o usuário {chat_id}.")

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
    if current_status["state"] == "idle":
        status_text = "Nenhum Pomodoro em andamento. Que tal começar um agora? 💪"
    elif current_status["state"] == "focus":
        remaining_time_seconds = (current_status.get("end_time", datetime.datetime.now(SAO_PAULO_TZ)) - datetime.datetime.now(SAO_PAULO_TZ)).total_seconds()
        remaining_minutes = max(0, int(remaining_time_seconds / 60))
        remaining_seconds = max(0, int(remaining_time_seconds % 60))
        status_text = f"Foco total! 🧠 Você está no ciclo {current_status['current_cycle']} de Pomodoro. Restam: {remaining_minutes:02d}m {remaining_seconds:02d}s."
    elif current_status["state"] == "short_break":
        remaining_time_seconds = (current_status.get("end_time", datetime.datetime.now(SAO_PAULO_TZ)) - datetime.datetime.now(SAO_PAULO_TZ)).total_seconds()
        remaining_minutes = max(0, int(remaining_time_seconds / 60))
        remaining_seconds = max(0, int(remaining_time_seconds % 60))
        status_text = f"Pausa curta para recarregar as energias! ☕ Restam: {remaining_minutes:02d}m {remaining_seconds:02d}s."
    elif current_status["state"] == "long_break":
        remaining_time_seconds = (current_status.get("end_time", datetime.datetime.now(SAO_PAULO_TZ)) - datetime.datetime.now(SAO_PAULO_TZ)).total_seconds()
        remaining_minutes = max(0, int(remaining_time_seconds / 60))
        remaining_seconds = max(0, int(remaining_time_seconds % 60))
        status_text = f"Pausa longa, aproveite para relaxar de verdade! 🧘 Restam: {remaining_minutes:02d}m {remaining_seconds:02d}s."
    elif current_status["state"] == "paused":
        paused_remaining_time = current_status.get("paused_remaining_time", 0)
        remaining_minutes = max(0, int(paused_remaining_time / 60))
        remaining_seconds = max(0, int(paused_remaining_time % 60))
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
        
        # Garante que o tempo da fase atual seja acumulado antes de parar
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
            await pomodoro_menu(update, context)
        else:
            await update.message.reply_text(report_message, parse_mode='Markdown')
        
        logger.info(f"Usuário {chat_id} parou o Pomodoro. Relatório final exibido.")
    else:
        message = "🚫 Não há Pomodoro em andamento para parar. Use /pomodoro para começar um! 😉"
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(message)
            await pomodoro_menu(update, context)
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
                await handle_pomodoro_end_callback(context)
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
    
    def pomodoro_job_callback_wrapper(job_context: ContextTypes.DEFAULT_TYPE):
        asyncio.create_task(handle_pomodoro_end_callback(job_context))

    end_time = datetime.datetime.now(SAO_PAULO_TZ) + datetime.timedelta(seconds=duration_seconds)

    job = job_queue.run_once(
        pomodoro_job_callback_wrapper,
        duration_seconds,
        chat_id=int(chat_id),
        data={"timer_type": timer_type, "chat_id": chat_id},
        name=f"pomodoro_{chat_id}_{timer_type}_{datetime.datetime.now().timestamp()}"
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

    # Acumula o tempo da fase que acabou
    if current_status.get("start_time_of_phase"):
        elapsed_time_in_phase = (datetime.datetime.now(SAO_PAULO_TZ) - current_status["start_time_of_phase"]).total_seconds()
        if timer_type == "focus":
            current_status["focused_time_total"] += elapsed_time_in_phase
        elif timer_type == "short_break":
            current_status["short_break_time_total"] += elapsed_time_in_phase
        elif timer_type == "long_break":
            current_status["long_break_time_total"] += elapsed_time_in_phase
    
    # Prepara para a próxima fase
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
    await (update.message or update.callback_query.message).reply_text(
        "🎯 Qual meta semanal você quer definir? Pode ser '10 Pomodoros de Foco', 'Concluir 5 tarefas importantes', etc. Seja específico! ✨"
    )
    logger.info(f"Usuário {chat_id} iniciou a definição de uma meta semanal.")

async def handle_set_weekly_goal_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Recebe a descrição da meta semanal e a salva."""
    chat_id = str(update.effective_chat.id)
    goal_description = update.message.text.strip()

    db = load_data()
    user_data = db.setdefault(chat_id, {})
    weekly_goals = user_data.setdefault("weekly_goals", [])
    
    new_goal = {
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

            status_icon = "✅" if status == "completed" else "⏳" if status == "active" else "❌"
            progress_text = f"Progresso: {progress}%"
            if target:
                progress_text = f"Meta: {target} (Progresso: {progress}%)"
            
            message += f"{idx+1}. {status_icon} *{description}*\n   _{progress_text} - Status: {status.capitalize()}_\n\n"
        
        message += "Use o menu para gerenciar suas metas."
        
    keyboard = [
        [InlineKeyboardButton("➕ Definir Nova Meta", callback_data="set_weekly_goal_command_cb")],
        [InlineKeyboardButton("🗑️ Excluir Meta", callback_data="delete_weekly_goal_menu")],
        [InlineKeyboardButton("↩️ Voltar ao Menu Principal", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    logger.info(f"Usuário {chat_id} visualizou as metas semanais.")

async def set_weekly_goal_command_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback para iniciar a definição de meta a partir de um botão."""
    await update.callback_query.answer()
    await set_weekly_goal_command(update, context)

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
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"delete_weekly_goal_confirm_{idx}")])

    keyboard.append([InlineKeyboardButton("↩️ Voltar", callback_data="view_weekly_goals_command")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')
    logger.info(f"Usuário {chat_id} acessou o menu para apagar metas semanais.")

async def delete_weekly_goal_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirma e apaga uma meta semanal específica."""
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)
    
    try:
        idx_to_delete = int(query.data.split("_")[4])
    except (IndexError, ValueError):
        logger.error(f"Erro ao parsear índice do callback_data para apagar meta: {query.data}")
        await query.edit_message_text("❌ Erro ao identificar a meta para apagar. Por favor, tente novamente!")
        return

    db = load_data()
    user_data = db.setdefault(chat_id, {})
    weekly_goals = user_data.setdefault("weekly_goals", [])

    if 0 <= idx_to_delete < len(weekly_goals):
        deleted_goal = weekly_goals.pop(idx_to_delete)
        save_data(db)
        await query.edit_message_text(f"🗑️ A meta *'{deleted_goal['description']}'* foi apagada com sucesso! 😉", parse_mode='Markdown')
        logger.info(f"Meta '{deleted_goal['description']}' (idx {idx_to_delete}) apagada para o usuário {chat_id}.")
        await view_weekly_goals_command(update, context)
    else:
        await query.edit_message_text("🤔 Não encontrei essa meta. Ela pode já ter sido apagada.", parse_mode='Markdown')
        logger.warning(f"Tentativa de apagar meta com índice inválido {idx_to_delete} para o usuário {chat_id}.")

# --- Funções de Menu Principal e Relatórios ---
async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exibe o menu principal do bot."""
    keyboard = [
        [InlineKeyboardButton("📋 Minhas Tarefas", callback_data="list_tasks_all")],
        [InlineKeyboardButton("⏰ Pomodoro", callback_data="menu_pomodoro")],
        [InlineKeyboardButton("📚 Rotina Semanal", callback_data="show_weekly_routine_command")],
        [InlineKeyboardButton("🎯 Minhas Metas", callback_data="view_weekly_goals_command")],
        [InlineKeyboardButton("📊 Relatórios", callback_data="show_reports_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_text = "Olá! Como posso te ajudar hoje a ser mais produtivo? 😊"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')
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
    # Mock do job object para que send_daily_feedback possa usar context.job.chat_id
    context.job = type('obj', (object,), {'chat_id' : update.effective_chat.id})()
    await send_daily_feedback(context)

async def get_weekly_feedback_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback para gerar e enviar o feedback semanal manualmente."""
    await update.callback_query.answer("Gerando relatório semanal...")
    # Mock do job object
    context.job = type('obj', (object,), {'chat_id' : update.effective_chat.id})()
    await send_weekly_feedback(context)
