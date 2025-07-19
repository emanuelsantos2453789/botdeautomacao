import os
import json
import re
import datetime
import dateparser
import logging
import pytz
import asyncio 
from collections import defaultdict 

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    error # Importa o módulo de erro
)
from telegram.ext import ContextTypes, JobQueue

# Define o diretório da aplicação e o arquivo de dados
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DADOS_FILE = os.path.join(APP_DIR, "dados.json")

# Configura o logger para mostrar mais informações
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Fuso horário padrão para o bot
SAO_PAULO_TZ = pytz.timezone('America/Sao_Paulo')

# --- Funções de Dados ---
def load_data():
    if not os.path.exists(DADOS_FILE):
        return {}
    with open(DADOS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DADOS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# --- Gerenciamento de Tarefas e Jobs ---
async def send_task_alert(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.chat_id
    task_data = job.data # Agora job.data é um dicionário
    
    task_text = task_data['description']
    alert_type = task_data['alert_type'] # 'start', 'end', ou 'pre_start'
    task_idx = task_data.get('task_idx') # Índice da tarefa, se disponível

    message = ""
    if alert_type == 'pre_start':
        message = f"🔔 Oba! Lembrete: Sua tarefa *'{task_text}'* começa em 30 minutinhos! Bora se preparar! ✨"
    elif alert_type == 'start':
        message = f"⏰ É AGORA! Sua tarefa *'{task_text}'* está começando! Foco total e vamos lá! 💪"
    elif alert_type == 'end':
        message = f"🎉 Missão cumprida (ou quase)! O tempo para sua tarefa *'{task_text}'* acabou! Hora de dar um feedback! 👇"
    else:
        message = f"⏰ Lembrete: Sua tarefa *'{task_text}'* está marcada para agora! 😉" # Fallback

    logger.info(f"⏰ [ALERTA] Tentando enviar alerta '{alert_type}' para chat_id: {chat_id}, tarefa: '{task_text}'. Horário atual no job: {datetime.datetime.now()} (UTC).")
    
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode='Markdown'
        )
        logger.info(f"✅ [ALERTA] Alerta '{alert_type}' da tarefa '{task_text}' ENVIADO com sucesso para o usuário {chat_id}.")

        # Se for o alerta de fim, perguntar sobre a conclusão
        if alert_type == 'end':
            if task_idx is not None:
                # O estado 'expecting' aqui é menos importante, pois a resposta virá via callback_query.
                context.user_data['expecting'] = 'task_completion_feedback' 
                
                keyboard = [
                    [InlineKeyboardButton("Sim, concluí! 🎉", callback_data=f"feedback_yes_{task_idx}")],
                    [InlineKeyboardButton("Não, não concluí. 😔", callback_data=f"feedback_no_{task_idx}")],
                ]
                markup = InlineKeyboardMarkup(keyboard)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"A tarefa *'{task_text}'* terminou. Você a concluiu? 🤔",
                    reply_markup=markup,
                    parse_mode='Markdown'
                )
                logger.info(f"Pergunta de conclusão enviada para a tarefa '{task_text}' (índice {task_idx}) para o usuário {chat_id}.")
            else:
                logger.warning(f"Não há task_idx para enviar pergunta de conclusão para tarefa '{task_text}'. Usuário {chat_id}.")

    except error.TelegramError as e:
        logger.error(f"❌ [ALERTA] ERRO do Telegram ao enviar alerta '{alert_type}' para chat_id: {chat_id}, tarefa: '{task_text}'. Erro: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"❌ [ALERTA] ERRO geral ao enviar alerta '{alert_type}' para chat_id: {chat_id}, tarefa: '{task_text}'. Erro: {e}", exc_info=True)


# --- Menu Principal e Callbacks ---
async def rotina(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("📈 Criar Meta", callback_data="menu_meta")],
        [InlineKeyboardButton("⏰ Agendar Tarefa", callback_data="menu_schedule")],
        [InlineKeyboardButton("📋 Minhas Metas", callback_data="menu_list_metas")],
        [InlineKeyboardButton("📝 Minhas Tarefas", callback_data="menu_list_tasks")],
        [InlineKeyboardButton("🗓️ Agendar Rotina Semanal", callback_data="menu_weekly_routine")],
        [InlineKeyboardButton("📊 Feedback do Dia", callback_data="menu_daily_feedback")],
        [InlineKeyboardButton("🍅 Pomodoro", callback_data="menu_pomodoro")], # Novo botão Pomodoro
    ]
    markup = InlineKeyboardMarkup(keyboard)
    await (update.message or update.callback_query.message).reply_text(
        "👋 Olá! Sou seu assistente de rotina! Vamos organizar seu dia? Escolha uma opção para começarmos! ✨",
        reply_markup=markup
    )
    logger.info(f"Usuário {update.effective_user.id} abriu o menu /rotina.")


async def rotina_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    cmd = query.data
    user_id = str(query.message.chat_id)
    db = load_data()
    user = db.setdefault(user_id, {})
    logger.info(f"Usuário {user_id} clicou em {cmd}.")

    if cmd == "menu_meta":
        context.user_data["expecting"] = "meta"
        await query.edit_message_text(
            "🎯 Que ótimo! Qual a descrição da meta que você quer alcançar? Seja específico e focado! 💪"
        )
        return

    if cmd == "menu_schedule":
        context.user_data["expecting"] = "schedule_datetime"
        await query.edit_message_text(
            "📅 Certo! Para quando e que horas você quer agendar essa tarefa? "
            "Ex: 'Amanhã 14h', '20/07 15h', '08:30 às 12:00h', 'Quarta 9h'. Posso te ajudar com isso! ✨"
        )
        return

    if cmd == "menu_list_metas":
        metas = user.get("metas", [])
        if metas:
            text_lines = ["📈 Suas Metas Incríveis:"]
            keyboard_rows = []
            for i, m in enumerate(metas):
                text_lines.append(f"• {m['activity']}")
                keyboard_rows.append([InlineKeyboardButton(f"🗑️ Apagar '{m['activity']}'", callback_data=f"delete_meta_{i}")])
            
            markup = InlineKeyboardMarkup(keyboard_rows)
            text_lines.append("\nBora conquistar essas metas! Se precisar apagar alguma, é só clicar! 👇")
            await query.edit_message_text("\n".join(text_lines), reply_markup=markup)
        else:
            await query.edit_message_text("📈 Você ainda não definiu nenhuma meta. Que tal criar uma agora para impulsionar seus objetivos? 💪")
        return
    
    if cmd == "menu_list_tasks":
        tarefas = user.get("tarefas", [])
        if not tarefas:
            await query.edit_message_text("📝 Você ainda não tem tarefas agendadas. Que tal agendar uma agora e dar um passo à frente? 🚀")
            return
        
        await query.edit_message_text("📝 Suas Tarefas Agendadas:")
        
        now_aware = datetime.datetime.now(SAO_PAULO_TZ)
        
        # Filtra tarefas não concluídas e futuras
        filtered_tasks = [
            (i, t) for i, t in enumerate(tarefas) 
            if not t.get('done', False)
        ]
        
        # Ordena as tarefas por data de início
        tarefas_ordenadas = sorted(filtered_tasks, 
                                    key=lambda x: datetime.datetime.fromisoformat(x[1]['start_when']) 
                                    if isinstance(x[1].get('start_when'), str) else datetime.datetime.min)

        if not tarefas_ordenadas:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="🎉 Parabéns! Você não tem tarefas pendentes ou futuras no momento. Que organização! ✨"
            )
            return

        for original_idx, t in tarefas_ordenadas:
            start_dt_obj_naive = datetime.datetime.fromisoformat(t['start_when'])
            start_dt_obj_aware = SAO_PAULO_TZ.localize(start_dt_obj_naive)
            
            start_when_str = start_dt_obj_aware.strftime("%d/%m/%Y às %H:%M")
            end_when_str = ""
            
            if isinstance(t.get('end_when'), str) and t.get('end_when'):
                try:
                    end_dt_obj_naive = datetime.datetime.fromisoformat(t['end_when'])
                    end_dt_obj_aware = SAO_PAULO_TZ.localize(end_dt_obj_naive)
                    end_when_str = f" até {end_dt_obj_aware.strftime('%H:%M')}"
                except ValueError:
                    end_when_str = f" até {t['end_when']}" # Fallback
            
            status = ""
            if t.get('done'):
                status = "✅ Concluída!"
            elif t.get('completion_status') == 'not_completed':
                status = "❌ Não Concluída"
                if t.get('reason_not_completed'):
                    status += f" (Motivo: {t['reason_not_completed']})"
            elif start_dt_obj_aware < now_aware:
                 status = "⏳ Atrasada!"
            else:
                status = "⏳ Pendente"

            task_display_text = f"• *{t['activity']}* em {start_when_str}{end_when_str} [{status}]"
            
            keyboard_buttons = []
            if not t.get('done') and t.get('completion_status') != 'not_completed':
                keyboard_buttons.append(InlineKeyboardButton("Marcar como Concluída ✅", callback_data=f"mark_done_{original_idx}"))
            
            keyboard_buttons.append(InlineKeyboardButton("Apagar 🗑️", callback_data=f"delete_task_{original_idx}")) # NOVO: Botão Apagar Tarefa
            
            markup = InlineKeyboardMarkup([keyboard_buttons])
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=task_display_text,
                reply_markup=markup,
                parse_mode='Markdown'
            )
        return
    
    if cmd == "menu_weekly_routine":
        await handle_weekly_routine_input(update, context)
        return

    if cmd == "menu_daily_feedback":
        await send_daily_feedback(update, context)
        return
    
    # NOVO: Menu Pomodoro
    if cmd == "menu_pomodoro":
        await pomodoro_menu(update, context)
        return


# --- Handlers de Texto ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()
    state = context.user_data.get("expecting")
    chat_id = str(update.message.chat_id)
    db = load_data()
    user = db.setdefault(chat_id, {})
    logger.info(f"Usuário {chat_id} enviou texto: '{text}' no estado '{state}'.")

    # Criando META
    if state == "meta":
        atividade = text
        metas = user.setdefault("metas", [])
        metas.append({"activity": atividade, "progress": 0, "target": 1})
        save_data(db)
        await update.message.reply_text(
            f"✅ Meta *“{atividade}”* salva com sucesso! Agora, vamos trabalhar para alcançá-la! 💪 Que energia! ✨"
        )
        context.user_data.pop("expecting", None)
        logger.info(f"Meta '{atividade}' salva para o usuário {chat_id}.")
        return

    # Capturando APENAS a data e hora para agendamento (início e/ou fim)
    if state == "schedule_datetime":
        logger.info(f"Tentando parsear data/hora: '{text}'")
        try:
            processed_text = text.replace('h', '').strip()
            logger.info(f"Texto pré-processado para dateparser: '{processed_text}'")
            
            now_aware = datetime.datetime.now(SAO_PAULO_TZ)
            now_naive = now_aware.replace(tzinfo=None)

            start_dt_naive = None
            end_dt_naive = None

            time_range_match = re.search(
                r'(\d{1,2}:\d{2})\s*(?:às|-)\s*(\d{1,2}:\d{2})',
                processed_text,
                re.IGNORECASE
            )
            
            if time_range_match:
                start_time_str = time_range_match.group(1)
                end_time_str = time_range_match.group(2)
                
                text_without_time_range = processed_text.replace(time_range_match.group(0), '').strip()

                parsed_date_only = dateparser.parse(
                    text_without_time_range or "hoje",
                    settings={
                        "DATE_ORDER": "DMY",
                        "RELATIVE_BASE": now_aware,
                        "TIMEZONE": SAO_PAULO_TZ.zone,
                        "RETURN_AS_TIMEZONE_AWARE": False,
                        "PREFER_DATES_FROM": "current_period",
                        "STRICT_PARSING": False,
                    },
                    languages=['pt'] # CORREÇÃO: LANGUAGES passado como argumento separado
                )
                
                if not parsed_date_only or not isinstance(parsed_date_only, datetime.datetime):
                    base_date_naive = now_naive.date()
                    logger.info(f"Não foi possível parsear data explícita. Usando data base: {base_date_naive}")
                else:
                    base_date_naive = parsed_date_only.date()
                    logger.info(f"Data base parseada: {base_date_naive} de '{text_without_time_range}'")
                
                temp_start_dt = datetime.datetime.combine(base_date_naive, datetime.datetime.strptime(start_time_str, '%H:%M').time())
                temp_end_dt = datetime.datetime.combine(base_date_naive, datetime.datetime.strptime(end_time_str, '%H:%M').time())

                if temp_start_dt < now_naive - datetime.timedelta(minutes=1):
                    temp_start_dt += datetime.timedelta(days=1)
                    if temp_end_dt <= temp_start_dt.replace(hour=temp_start_dt.hour, minute=temp_start_dt.minute, second=0, microsecond=0):
                        temp_end_dt += datetime.timedelta(days=1)
                
                start_dt_naive = temp_start_dt
                end_dt_naive = temp_end_dt
                
                logger.info(f"Parse com intervalo (regex): Start={start_dt_naive}, End={end_dt_naive} para '{processed_text}'")

            if not start_dt_naive:
                dt_parsed = dateparser.parse(
                    processed_text,
                    settings={
                        "DATE_ORDER": "DMY",
                        "TIMEZONE": SAO_PAULO_TZ.zone,
                        "RETURN_AS_TIMEZONE_AWARE": False,
                        "RELATIVE_BASE": now_aware,
                        "PREFER_DATES_FROM": "current_period",
                        "STRICT_PARSING": False,
                    },
                    languages=['pt'] # CORREÇÃO: LANGUAGES passado como argumento separado
                )
                
                if dt_parsed and isinstance(dt_parsed, datetime.datetime):
                    if dt_parsed <= now_naive - datetime.timedelta(minutes=1):
                        dt_parsed_future = dateparser.parse(
                            processed_text,
                            settings={
                                "DATE_ORDER": "DMY",
                                "TIMEZONE": SAO_PAULO_TZ.zone,
                                "RETURN_AS_TIMEZONE_AWARE": False,
                                "RELATIVE_BASE": now_aware,
                                "PREFER_DATES_FROM": "future",
                                "STRICT_PARSING": False,
                            },
                            languages=['pt'] # CORREÇÃO: LANGUAGES passado como argumento separado
                        )
                        if dt_parsed_future and dt_parsed_future > now_naive:
                            start_dt_naive = dt_parsed_future
                            logger.info(f"Data/hora ajustada para o futuro: {start_dt_naive} para '{processed_text}'")
                        else:
                            logger.warning(f"Data/hora '{processed_text}' ainda no passado após tentar preferir futuro. Original: {dt_parsed}, Future attempt: {dt_parsed_future}")
                            await update.message.reply_text(
                                "❌ Opa! A data/hora agendada já passou. Por favor, agende para o futuro. Vamos tentar de novo? 😉"
                            )
                            return
                    else:
                        start_dt_naive = dt_parsed
                
                logger.info(f"Parse como única data/hora: {start_dt_naive} para '{processed_text}'")

            if not start_dt_naive or not isinstance(start_dt_naive, datetime.datetime):
                logger.warning(f"Não foi possível entender a data/hora para '{processed_text}'. Objeto: {start_dt_naive}")
                await update.message.reply_text(
                    "❌ Puxa, não entendi o dia e horário. Por favor, tente um formato claro como:\n"
                    "- *Amanhã 14h*\n"
                    "- *20/07 15h*\n"
                    "- *08:30 às 12:00h* (para um intervalo)\n"
                    "- *Terça 10h*\n"
                    "Vamos tentar de novo? Estou aqui para ajudar! ✨"
                )
                return

            if start_dt_naive <= now_naive:
                await update.message.reply_text(
                    "❌ A data/hora de início agendada já passou. Por favor, agende para o futuro. Que tal tentarmos novamente? 😉"
                )
                return

            context.user_data["temp_schedule"] = {
                "start_datetime": start_dt_naive.isoformat(),
                "end_datetime": end_dt_naive.isoformat() if end_dt_naive else None
            }
            context.user_data["expecting"] = "schedule_description"

            start_display = start_dt_naive.strftime('%d/%m/%Y às %H:%M')
            end_display = ""
            if end_dt_naive:
                end_display = f" até {end_dt_naive.strftime('%H:%M')}"
                duration = end_dt_naive - start_dt_naive
                hours, remainder = divmod(duration.total_seconds(), 3600)
                minutes = remainder // 60
                duration_str = ""
                if hours > 0:
                    duration_str += f"{int(hours)}h"
                if minutes > 0:
                    duration_str += f"{int(minutes)}min"
                if duration_str:
                    end_display += f" (Duração: {duration_str})"

            await update.message.reply_text(
                f"🎉 Entendi! Agendado para *{start_display}{end_display}*.\n"
                "Agora, qual a **descrição** dessa tarefa incrível? Conta pra mim! 🤔"
            )
            logger.info(f"Data/hora de início '{start_dt_naive}' e fim '{end_dt_naive}' (se houver) capturadas. Pedindo descrição da tarefa.")
            return

        except Exception as e:
            logger.error(f"Erro ao parsear data/hora '{text}': {e}", exc_info=True)
            await update.message.reply_text(f"❌ Ah, não consegui processar a data/hora: {e}. Por favor, tente novamente com um formato claro como 'Amanhã 14h' ou '20/07 15h às 17h'. Vamos juntos! 😉")
            context.user_data.pop("expecting", None)
            return

    # Capturando a descrição da tarefa
    if state == "schedule_description":
        logger.info(f"Recebeu descrição da tarefa: '{text}'")
        temp_schedule_data = context.user_data.get("temp_schedule")
        if not temp_schedule_data:
            logger.error("Erro: temp_schedule não encontrado ao tentar agendar descrição.")
            await update.message.reply_text("❌ Ops, algo deu errado com o agendamento. Por favor, tente agendar novamente desde o início. Conte comigo! 💪")
            context.user_data.pop("expecting", None)
            return

        start_dt_naive = datetime.datetime.fromisoformat(temp_schedule_data["start_datetime"])
        end_dt_naive = None
        if temp_schedule_data["end_datetime"]:
            end_dt_naive = datetime.datetime.fromisoformat(temp_schedule_data["end_datetime"])

        task_start_datetime_aware = SAO_PAULO_TZ.localize(start_dt_naive)
        task_end_datetime_aware = None
        if end_dt_naive:
            task_end_datetime_aware = SAO_PAULO_TZ.localize(end_dt_naive)

        now_aware_for_job_check = datetime.datetime.now(SAO_PAULO_TZ)

        if task_start_datetime_aware <= now_aware_for_job_check - datetime.timedelta(seconds=5): 
            await update.message.reply_text(
                "❌ A data/hora de início agendada já passou. Que tal agendar para o futuro e brilharmos juntos? ✨"
            )
            context.user_data.pop("expecting", None)
            context.user_data.pop("temp_schedule", None)
            return
        
        tarefas = user.setdefault("tarefas", [])
        new_task_data = {
            "activity": text,
            "done": False,
            "start_when": task_start_datetime_aware.isoformat(),
            "end_when": task_end_datetime_aware.isoformat() if task_end_datetime_aware else None,
            "completion_status": None,
            "reason_not_completed": None,
            "job_names": [] # Para armazenar os nomes dos jobs para esta tarefa
        }
        tarefas.append(new_task_data)
        current_task_idx = len(tarefas) - 1
        logger.info(f"Tarefa '{text}' salva no DADOS_FILE com índice {current_task_idx} para o usuário {chat_id}.")

        # --- Agendando Alertas ---
        job_names_for_task = []

        # Alerta de 30 minutos antes
        pre_start_time = task_start_datetime_aware - datetime.timedelta(minutes=30)
        if pre_start_time > now_aware_for_job_check:
            pre_start_job_name = f"task_alert_pre_start_{chat_id}_{task_start_datetime_aware.timestamp()}_{current_task_idx}"
            context.job_queue.run_once(
                send_task_alert,
                when=pre_start_time,
                chat_id=chat_id,
                data={'description': text, 'alert_type': 'pre_start', 'task_idx': current_task_idx},
                name=pre_start_job_name
            )
            job_names_for_task.append(pre_start_job_name)
            logger.info(f"✅ [AGENDAMENTO] Alerta de PRÉ-INÍCIO agendado para '{text}' em '{pre_start_time}'.")
        else:
            logger.info(f"🚫 [AGENDAMENTO] Alerta de PRÉ-INÍCIO para '{text}' no passado, não agendado.")

        # Alerta de Início
        start_job_name = f"task_alert_start_{chat_id}_{task_start_datetime_aware.timestamp()}_{current_task_idx}"
        context.job_queue.run_once(
            send_task_alert,
            when=task_start_datetime_aware,
            chat_id=chat_id,
            data={'description': text, 'alert_type': 'start', 'task_idx': current_task_idx},
            name=start_job_name
        )
        job_names_for_task.append(start_job_name)
        logger.info(f"✅ [AGENDAMENTO] Alerta de INÍCIO agendado para '{text}' em '{task_start_datetime_aware}'.")

        # Alerta de Fim (se houver)
        if task_end_datetime_aware:
            if task_end_datetime_aware <= task_start_datetime_aware:
                task_end_datetime_aware += datetime.timedelta(days=1)
            
            end_job_name = f"task_alert_end_{chat_id}_{task_end_datetime_aware.timestamp()}_{current_task_idx}"
            context.job_queue.run_once(
                send_task_alert,
                when=task_end_datetime_aware,
                chat_id=chat_id,
                data={'description': text, 'alert_type': 'end', 'task_idx': current_task_idx},
                name=end_job_name
            )
            job_names_for_task.append(end_job_name)
            logger.info(f"✅ [AGENDAMENTO] Alerta de FIM agendado para '{text}' em '{task_end_datetime_aware}'.")
        
        tarefas[current_task_idx]["job_names"] = job_names_for_task # Salva os nomes dos jobs na tarefa
        save_data(db) # Salva os dados novamente com os nomes dos jobs

        start_display = task_start_datetime_aware.strftime('%d/%m/%Y às %H:%M')
        end_display = ""
        if task_end_datetime_aware:
            end_display = f" até {task_end_datetime_aware.strftime('%H:%M')}"
            duration = task_end_datetime_aware - task_start_datetime_aware
            hours, remainder = divmod(duration.total_seconds(), 3600)
            minutes = remainder // 60
            duration_str = ""
            if hours > 0:
                duration_str += f"{int(hours)}h"
            if minutes > 0:
                duration_str += f"{int(minutes)}min"
            if duration_str:
                end_display += f" (Duração: {duration_str})"

        await update.message.reply_text(
            f"🎉 UHUL! Tarefa *“{text}”* agendada com sucesso para "
            f"*{start_display}{end_display}*!\n"
            "Eu te avisarei no Telegram quando for a hora, e também 30 minutos antes para você se preparar! Conte comigo! 😉"
        )
        context.user_data.pop("expecting", None)
        context.user_data.pop("temp_schedule", None)
        logger.info(f"Mensagem de sucesso de agendamento enviada para o usuário {chat_id}.")
        return

    # Tratando a entrada da Rotina Semanal
    if state == "weekly_routine_text":
        logger.info(f"Recebeu texto da rotina semanal: '{text}'")
        await update.message.reply_text("✨ Certo! Analisando sua rotina... Isso pode levar um instante! 😉")
        try:
            scheduled_count = await parse_and_schedule_weekly_routine(chat_id, text, context.job_queue)
            if scheduled_count > 0:
                await update.message.reply_text(
                    f"🎉 Incrível! Consegui agendar *{scheduled_count}* tarefas da sua rotina semanal! "
                    "Agora é só focar e arrasar! Eu te avisarei de cada uma! ✨"
                )
                logger.info(f"Agendadas {scheduled_count} tarefas da rotina semanal para o usuário {chat_id}.")
            else:
                await update.message.reply_text(
                    "🤔 Não consegui identificar tarefas claras para agendar na sua rotina. "
                    "Tente formatar com dias da semana, horários (ex: '10h30 – 11h00') e a descrição da tarefa. "
                    "Vamos tentar de novo? 😉"
                )
                logger.warning(f"Nenhuma tarefa agendada da rotina semanal para o usuário {chat_id}.")
        except Exception as e:
            logger.error(f"Erro ao processar rotina semanal para {chat_id}: {e}", exc_info=True)
            await update.message.reply_text(
                "❌ Puxa, houve um erro ao processar sua rotina semanal. "
                "Por favor, verifique o formato e tente novamente. Estou aqui para ajudar! 🙏"
            )
        finally:
            context.user_data.pop("expecting", None)
        return

    # Capturando o motivo de não conclusão (se o usuário digitar)
    if state == "reason_for_not_completion":
        task_idx = context.user_data.get("task_idx_for_reason")
        
        db = load_data()
        user_data = db.setdefault(chat_id, {})
        tarefas = user_data.setdefault("tarefas", [])

        if task_idx is not None and 0 <= task_idx < len(tarefas):
            tarefas[task_idx]["reason_not_completed"] = text
            tarefas[task_idx]["completion_status"] = "not_completed"
            tarefas[task_idx]["done"] = False
            save_data(db)
            await update.message.reply_text(f"📝 Entendido! O motivo *'{text}'* foi registrado para a tarefa *'{tarefas[task_idx]['activity']}'*. Vamos aprender com isso e seguir em frente! 💪")
            logger.info(f"Motivo de não conclusão registrado para tarefa {tarefas[task_idx]['activity']}.")
        else:
            await update.message.reply_text("❌ Ops, não consegui associar o motivo a uma tarefa. Por favor, tente novamente. Qual é a tarefa? 🤔")
            logger.warning(f"Não foi possível associar o motivo '{text}' à tarefa com índice {task_idx}.")

        context.user_data.pop("expecting", None)
        context.user_data.pop("task_idx_for_reason", None)
        return
    
    # Tratamento de input para Pomodoro (se estiver configurando tempos)
    if state and state.startswith("pomodoro_set_"):
        try:
            value = int(text)
            if setting_type == "cycles":
                if not (1 <= value <= 10): # Limite razoável para ciclos
                    await update.message.reply_text("Por favor, digite um número de ciclos entre 1 e 10.")
                    return
            else: # tempos de foco/descanso
                if not (1 <= value <= 120): # Limite razoável para minutos
                    await update.message.reply_text("Por favor, digite um número entre 1 e 120 minutos.")
                    return

            setting_type = state.replace("pomodoro_set_", "")
            
            # Aqui atualizamos o dicionário pomodoro_timers diretamente
            pomodoro_timers[chat_id][setting_type] = value
            save_data(db) # Salva a configuração atualizada

            await update.message.reply_text(f"✅ Tempo de *{setting_type.replace('_', ' ')}* definido para *{value} minutos*! 🎉", parse_mode='Markdown')
            
            context.user_data.pop("expecting", None)
            await pomodoro_menu(update, context) # Volta ao menu do Pomodoro
            return
        except ValueError:
            await update.message.reply_text("Ops! Por favor, digite um *número válido*. Ex: '25'.", parse_mode='Markdown')
            return


    logger.info(f"Texto '{text}' recebido sem estado 'expecting'.")
    await update.message.reply_text(
        "👉 Use /rotina para abrir o menu e escolher uma opção. Estou aqui para te ajudar a organizar seu dia e alcançar seus objetivos! 😉"
    )

# --- Callbacks de Ação (Concluir, Apagar) ---
async def mark_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    chat_id = str(query.message.chat_id)
    db = load_data()
    user_data = db.setdefault(chat_id, {})
    tarefas = user_data.setdefault("tarefas", [])

    cmd = query.data
    logger.info(f"Usuário {chat_id} clicou em callback: {cmd}.")

    if cmd.startswith("mark_done_"):
        try:
            idx = int(cmd.split("_")[2])
        except (IndexError, ValueError):
            logger.error(f"Erro ao parsear índice do callback_data: {cmd}")
            await query.edit_message_text("❌ Erro ao identificar a tarefa. Por favor, tente novamente!")
            return

        logger.info(f"Usuário {chat_id} tentou marcar tarefa {idx} como concluída via botão 'Marcar como Concluída'.")
        if 0 <= idx < len(tarefas):
            if not tarefas[idx].get('done'): # Só marca se não estiver concluída
                tarefas[idx]["done"] = True
                tarefas[idx]["completion_status"] = "completed_manually"
                tarefas[idx]["reason_not_completed"] = None
                
                user_data["score"] = user_data.get("score", 0) + 10
                logger.info(f"Usuário {chat_id} ganhou 10 pontos. Pontuação atual: {user_data['score']}.")

                # Cancela os jobs pendentes para esta tarefa
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
        return
    
    if cmd.startswith("feedback_yes_"):
        try:
            task_idx = int(cmd.split("_")[2])
        except (IndexError, ValueError):
            logger.error(f"Erro ao parsear índice do callback_data: {cmd}")
            await query.edit_message_text("❌ Erro ao identificar a tarefa para feedback. Que pena! 😔")
            return

        if task_idx is not None and 0 <= task_idx < len(tarefas):
            if not tarefas[task_idx].get('done'): # Só marca se não estiver concluída
                tarefas[task_idx]["done"] = True
                tarefas[task_idx]["completion_status"] = "completed_on_time"
                tarefas[task_idx]["reason_not_completed"] = None
                
                user_data["score"] = user_data.get("score", 0) + 10
                logger.info(f"Usuário {chat_id} ganhou 10 pontos. Pontuação atual: {user_data['score']}.")

                cancel_task_jobs(chat_id, tarefas[task_idx].get("job_names", []), context.job_queue)

                save_data(db)
                await query.edit_message_text(f"🎉 PARABÉNS! A tarefa *'{tarefas[task_idx]['activity']}'* foi marcada como concluída! Que orgulho! Você ganhou 10 pontos! 🌟 Continue assim! 💪")
                logger.info(f"Tarefa '{tarefas[task_idx]['activity']}' marcada como concluída via feedback 'Sim'.")
            else:
                await query.edit_message_text(f"Esta tarefa já foi marcada como concluída! Ótimo trabalho! 😉")
        else:
            await query.edit_message_text("🤔 Não encontrei a tarefa para marcar como concluída. Ela pode já ter sido concluída ou apagada. Por favor, tente novamente!")
            logger.warning(f"Não encontrei tarefa com índice {task_idx} para marcar como concluída via feedback 'Sim'.")
            
        context.user_data.pop("expecting", None)
        return

    if cmd.startswith("feedback_no_"):
        try:
            task_idx = int(cmd.split("_")[2])
        except (IndexError, ValueError):
            logger.error(f"Erro ao parsear índice do callback_data: {cmd}")
            await query.edit_message_text("❌ Erro ao identificar a tarefa para feedback. Oops! 😔")
            return

        if task_idx is not None and 0 <= task_idx < len(tarefas):
            if not tarefas[task_idx].get('done'): # Só marca se não estiver concluída
                tarefas[task_idx]["completion_status"] = "not_completed"
                tarefas[task_idx]["done"] = False
                save_data(db) # Salva o status de não concluída
                
                cancel_task_jobs(chat_id, tarefas[task_idx].get("job_names", []), context.job_queue) # Cancela para evitar mais alertas
                
                context.user_data["expecting"] = "reason_for_not_completion"
                context.user_data["task_idx_for_reason"] = task_idx # Guarda o índice da tarefa
                await query.edit_message_text(f"😔 Ah, que pena! A tarefa *'{tarefas[task_idx]['activity']}'* não foi concluída. Por favor, digite o motivo: foi um imprevisto, falta de tempo, ou algo mais? Me conta para aprendermos juntos! 👇")
                logger.info(f"Solicitando motivo de não conclusão para a tarefa '{tarefas[task_idx]['activity']}'.")
            else:
                await query.edit_message_text(f"Esta tarefa já foi concluída! Que bom! 😊")
        else:
            await query.edit_message_text("🤔 Não encontrei a tarefa para registrar o motivo. Ela pode já ter sido concluída ou apagada. Por favor, tente novamente!")
            logger.warning(f"Não encontrei tarefa com índice {task_idx} para solicitar motivo de não conclusão via feedback 'Não'.")
        return

async def delete_meta_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
            await query.edit_message_text(f"🗑️ Meta *'{deleted_meta['activity']}'* apagada com sucesso! Uma a menos para se preocupar! 😉")
            logger.info(f"Meta '{deleted_meta['activity']}' apagada para o usuário {chat_id}.")
        else:
            await query.edit_message_text("🤔 Essa meta não existe mais ou o índice está incorreto. Tente listar suas metas novamente!")
            logger.warning(f"Tentativa de apagar meta com índice inválido {idx} para o usuário {chat_id}.")
        return

# NOVO: Apagar Tarefas
async def delete_task_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
            
            # Cancela os jobs associados a essa tarefa
            cancel_task_jobs(chat_id, deleted_task.get("job_names", []), context.job_queue)
            
            save_data(db)
            await query.edit_message_text(f"🗑️ Tarefa *'{deleted_task['activity']}'* apagada com sucesso! Menos uma preocupação! 😉")
            logger.info(f"Tarefa '{deleted_task['activity']}' apagada para o usuário {chat_id}.")
        else:
            await query.edit_message_text("🤔 Essa tarefa não existe mais ou o índice está incorreto. Tente listar suas tarefas novamente!")
            logger.warning(f"Tentativa de apagar tarefa com índice inválido {idx} para o usuário {chat_id}.")
        return

# Helper para cancelar jobs de uma tarefa
def cancel_task_jobs(chat_id: str, job_names: list, job_queue: JobQueue):
    """Cancela todos os jobs do JobQueue com os nomes fornecidos para um chat_id específico."""
    jobs_to_remove_from_list = []
    for job_name in job_names:
        current_jobs = job_queue.get_jobs_by_name(job_name)
        for job in current_jobs:
            # Verifica se o job pertence a este chat_id específico
            if job.chat_id == int(chat_id):
                job.schedule_removal()
                jobs_to_remove_from_list.append(job.name) # Marca para remoção da lista
                logger.info(f"Job '{job.name}' cancelado para o chat {chat_id}.")
            else:
                logger.warning(f"Job '{job.name}' encontrado, mas não pertence ao chat {chat_id}. Não será removido.")

    # Opcional: remover os nomes dos jobs da lista na tarefa (já feito ao remover a tarefa, mas importante para consistência se a tarefa não for removida)
    # Exemplo: se estivéssemos limpando apenas jobs, não a tarefa toda.

# --- Funções de Feedback e Relatórios ---
async def send_daily_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    db = load_data()
    user_data = db.setdefault(chat_id, {})
    tarefas = user_data.setdefault("tarefas", [])
    
    now_aware = datetime.datetime.now(SAO_PAULO_TZ)
    today = now_aware.date()

    completed_tasks_today = []
    not_completed_tasks_today = []
    imprevistos_today = []
    
    daily_score_this_feedback = 0 # Score gerado para o dia especificamente

    for task in tarefas:
        try:
            task_start_dt_naive = datetime.datetime.fromisoformat(task['start_when'])
            task_start_dt_aware = SAO_PAULO_TZ.localize(task_start_dt_naive)
            task_date = task_start_dt_aware.date()
        except (ValueError, TypeError): # Adicionado TypeError caso start_when não seja string
            logger.warning(f"Data de início inválida para a tarefa: {task.get('activity')}. Pulando.")
            continue
            
        if task_date == today:
            if task.get('completion_status') == 'completed_on_time' or task.get('completion_status') == 'completed_manually':
                completed_tasks_today.append(task['activity'])
                # Considera que 10 pontos são por tarefa concluída, já somados ao score geral
                # Este é o score *do dia* para o feedback, não adiciona novamente ao total
                daily_score_this_feedback += 10 
            elif task.get('completion_status') == 'not_completed':
                not_completed_tasks_today.append(task['activity'])
                if task.get('reason_not_completed'):
                    imprevistos_today.append(f"- *{task['activity']}*: {task['reason_not_completed']}")
    
    feedback_message = f"✨ Seu Feedback Diário ({today.strftime('%d/%m/%Y')}):\n\n"
    
    if completed_tasks_today:
        feedback_message += "✅ Tarefas Concluídas HOJE:\n" + "\n".join(f"• {t}" for t in completed_tasks_today) + "\n\n"
    else:
        feedback_message += "😔 Nenhuma tarefa concluída hoje ainda. Bora pra cima! Você consegue! 💪\n\n"
        
    if not_completed_tasks_today:
        feedback_message += "❌ Tarefas Não Concluídas HOJE:\n" + "\n".join(f"• {t}" for t in not_completed_tasks_today) + "\n\n"
        
    if imprevistos_today:
        feedback_message += "⚠️ Imprevistos e Desafios de Hoje:\n" + "\n".join(imprevistos_today) + "\n\n"
        
    feedback_message += f"📊 Pontuação do Dia: *{daily_score_this_feedback}* pontos\n"
    feedback_message += f"🏆 Pontuação Total Acumulada: *{user_data.get('score', 0)}* pontos\n\n"
    feedback_message += "Lembre-se: Cada esforço conta! Continue firme! Você é incrível! ✨"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text=feedback_message, parse_mode='Markdown')
    else:
        await context.bot.send_message(chat_id=chat_id, text=feedback_message, parse_mode='Markdown')
    logger.info(f"Feedback diário enviado para o usuário {chat_id}.")


# --- Parsing de Rotina Semanal ---
async def handle_weekly_routine_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["expecting"] = "weekly_routine_text"
    await (update.message or update.callback_query.message).reply_text(
        "📚 Me envie sua rotina semanal completa, dia a dia e com horários, como no exemplo que você me deu! "
        "Vou te ajudar a transformá-la em tarefas agendadas. Capricha nos detalhes! ✨"
    )
    logger.info(f"Usuário {update.effective_user.id} solicitou input de rotina semanal.")

async def parse_and_schedule_weekly_routine(chat_id: str, routine_text: str, job_queue: JobQueue) -> int:
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

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Tenta detectar o dia da semana
        for day_name, day_num in day_mapping.items():
            if day_name in line.lower():
                current_day = day_num
                logger.info(f"Detectado dia: {day_name} (Índice: {current_day})")
                break
        
        if current_day is not None:
            time_activity_match = re.search(r'(\d{1,2}h(?:(\d{2}))?)\s*(?:[-–—]\s*(\d{1,2}h(?:(\d{2}))?))?:\s*(.+)', line, re.IGNORECASE)
            
            if time_activity_match:
                start_time_str_raw = time_activity_match.group(1)
                end_time_str_raw = time_activity_match.group(3)
                activity_description = time_activity_match.group(5).strip()
                
                # Funções auxiliares para formatar horas
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

                logger.info(f"   Detectado: Dia={current_day}, Início={start_time_obj.strftime('%H:%M')}, Fim={end_time_obj.strftime('%H:%M') if end_time_obj else 'N/A'}, Atividade='{activity_description}'")

                # Calcula a próxima ocorrência da tarefa
                # Encontrar a próxima data que seja 'current_day'
                target_date = now_aware.date()
                while target_date.weekday() != current_day:
                    target_date += datetime.timedelta(days=1)
                
                # Se a data alvo já passou na *semana atual* e o *horário* também já passou, avança para a próxima semana
                # Ex: se hoje é terça 10h e a tarefa é terça 9h, agenda para a próxima terça.
                # Se hoje é segunda 10h e a tarefa é terça 9h, agenda para amanhã.
                if target_date.weekday() == now_aware.weekday() and start_time_obj < now_aware.time():
                    target_date += datetime.timedelta(weeks=1)

                start_dt_naive = datetime.datetime.combine(target_date, start_time_obj)
                start_dt_aware = SAO_PAULO_TZ.localize(start_dt_naive)

                end_dt_aware = None
                if end_time_obj:
                    end_dt_naive = datetime.datetime.combine(target_date, end_time_obj)
                    if end_dt_naive < start_dt_naive: # Se o fim for antes do início (ex: 23h-01h), avança 1 dia
                        end_dt_naive += datetime.timedelta(days=1)
                    end_dt_aware = SAO_PAULO_TZ.localize(end_dt_naive)

                if start_dt_aware <= now_aware:
                    logger.warning(f"   Tarefa '{activity_description}' para {start_dt_aware} está no passado ou muito próxima, não agendada. Será necessário adicionar manualmente se quiser que ela apareça na lista de hoje.")
                    continue # Não agenda tarefas que já passaram ou estão começando agora

                # Agenda a tarefa e salva no dados.json
                new_task_data = {
                    "activity": activity_description,
                    "done": False,
                    "start_when": start_dt_aware.isoformat(),
                    "end_when": end_dt_aware.isoformat() if end_dt_aware else None,
                    "completion_status": None,
                    "reason_not_completed": None,
                    "recurring": True, # Marca como tarefa recorrente
                    "job_names": [] # Para armazenar os nomes dos jobs
                }
                tarefas.append(new_task_data)
                current_task_idx = len(tarefas) - 1
                
                job_names_for_task = []

                pre_start_time = start_dt_aware - datetime.timedelta(minutes=30)
                if pre_start_time > now_aware:
                    pre_start_job_name = f"recurring_task_pre_start_{chat_id}_{start_dt_aware.timestamp()}_{current_task_idx}"
                    job_queue.run_once(
                        send_task_alert,
                        when=pre_start_time,
                        chat_id=int(chat_id),
                        data={'description': activity_description, 'alert_type': 'pre_start', 'task_idx': current_task_idx},
                        name=pre_start_job_name
                    )
                    job_names_for_task.append(pre_start_job_name)

                start_job_name = f"recurring_task_start_{chat_id}_{start_dt_aware.timestamp()}_{current_task_idx}"
                job_queue.run_once(
                    send_task_alert,
                    when=start_dt_aware,
                    chat_id=int(chat_id),
                    data={'description': activity_description, 'alert_type': 'start', 'task_idx': current_task_idx},
                    name=start_job_name
                )
                job_names_for_task.append(start_job_name)
                scheduled_tasks_count += 1

                if end_dt_aware:
                    end_job_name = f"recurring_task_end_{chat_id}_{end_dt_aware.timestamp()}_{current_task_idx}"
                    job_queue.run_once(
                        send_task_alert,
                        when=end_dt_aware,
                        chat_id=int(chat_id),
                        data={'description': activity_description, 'alert_type': 'end', 'task_idx': current_task_idx},
                        name=end_job_name
                    )
                    job_names_for_task.append(end_job_name)

                new_task_data["job_names"] = job_names_for_task # Atualiza a tarefa com os nomes dos jobs
                logger.info(f"   Agendada tarefa recorrente: '{activity_description}' para {start_dt_aware} (índice {current_task_idx}).")

    save_data(db)
    return scheduled_tasks_count

# --- Funções do Pomodoro ---
pomodoro_timers = defaultdict(lambda: {"focus": 25, "short_break": 5, "long_break": 15, "cycles": 4})
# Armazena a data de fim agendada para calcular o tempo restante
pomodoro_status_map = {} # chat_id -> {"state": "idle/focus/short_break/long_break", "job": None, "current_cycle": 0, "end_time": None}

async def pomodoro_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    current_status = pomodoro_status_map.get(chat_id, {"state": "idle"})
    user_timers = pomodoro_timers[chat_id]

    # Carrega as configurações do Pomodoro do dados.json, se existirem
    db = load_data()
    user_data = db.setdefault(chat_id, {})
    pomodoro_config = user_data.setdefault("pomodoro_config", {})
    user_timers['focus'] = pomodoro_config.get('focus', 25)
    user_timers['short_break'] = pomodoro_config.get('short_break', 5)
    user_timers['long_break'] = pomodoro_config.get('long_break', 15)
    user_timers['cycles'] = pomodoro_config.get('cycles', 4)

    status_text = ""
    if current_status["state"] == "idle":
        status_text = "Nenhum Pomodoro em andamento. Que tal começar um agora? 💪"
    elif current_status["state"] == "focus":
        status_text = f"Foco total! 🧠 Você está no ciclo {current_status['current_cycle']} de Pomodoro."
    elif current_status["state"] == "short_break":
        status_text = "Pausa curta para recarregar as energias! ☕"
    elif current_status["state"] == "long_break":
        status_text = "Pausa longa, aproveite para relaxar de verdade! 🧘"
    
    keyboard = [
        [InlineKeyboardButton("▶️ Iniciar Pomodoro", callback_data="pomodoro_start")],
        [InlineKeyboardButton("⏸️ Pausar", callback_data="pomodoro_pause"),
         InlineKeyboardButton("▶️ Retomar", callback_data="pomodoro_resume")],
        [InlineKeyboardButton("⏹️ Parar Pomodoro", callback_data="pomodoro_stop_command")], # Callback diferente para não conflitar com o comando
        [InlineKeyboardButton("⚙️ Configurar Tempos", callback_data="pomodoro_config_times")],
        [InlineKeyboardButton("📊 Status Atual", callback_data="pomodoro_status_command")],
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
    chat_id = str(update.effective_chat.id)
    current_status = pomodoro_status_map.get(chat_id)

    if not current_status or current_status["state"] == "idle":
        message = "😌 Nenhum Pomodoro em andamento. Use /pomodoro para começar a focar! 💪"
    else:
        state = current_status["state"]
        # CORREÇÃO: Usar current_status["end_time"] para calcular o tempo restante
        if current_status.get("end_time"):
            remaining_time_seconds = (current_status["end_time"] - datetime.datetime.now(SAO_PAULO_TZ)).total_seconds()
            remaining_minutes = max(0, int(remaining_time_seconds / 60))
            remaining_seconds = max(0, int(remaining_time_seconds % 60))
        else:
            remaining_minutes = 0
            remaining_seconds = 0
            logger.warning(f"end_time não encontrado para o Pomodoro de {chat_id} no estado '{state}'.")


        message = (
            f"🚀 *Status do Pomodoro:*\n"
            f"Estado: *{state.replace('_', ' ').capitalize()}*\n"
            f"Ciclo Atual: *{current_status['current_cycle']}*\n"
            f"Tempo Restante: *{remaining_minutes:02d}m {remaining_seconds:02d}s*\n\n"
            "Mantenha o ritmo! Você está no caminho certo! ✨"
        )
    
    if update.callback_query:
        await update.callback_query.answer() # Fecha a notificação do botão
        await update.callback_query.message.reply_text(message, parse_mode='Markdown')
    else:
        await update.message.reply_text(message, parse_mode='Markdown')
    logger.info(f"Usuário {chat_id} solicitou status do Pomodoro.")

async def pomodoro_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    current_status = pomodoro_status_map.get(chat_id)

    if current_status and current_status["state"] != "idle" and current_status["job"]:
        current_status["job"].schedule_removal()
        pomodoro_status_map[chat_id] = {"state": "idle", "job": None, "current_cycle": 0, "end_time": None}
        message = "⏹️ Pomodoro parado. Que pena! Mas está tudo bem. Quando estiver pronto para retomar, me avise! 💪"
    else:
        message = "🚫 Não há Pomodoro em andamento para parar. Use /pomodoro para começar um! 😉"
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(message)
        await pomodoro_menu(update, context) # Volta ao menu principal do Pomodoro
    else:
        await update.message.reply_text(message)
    logger.info(f"Usuário {chat_id} parou o Pomodoro.")

async def pomodoro_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)
    
    user_timers = pomodoro_timers[chat_id]
    current_status = pomodoro_status_map.get(chat_id, {"state": "idle", "current_cycle": 0})

    if query.data == "pomodoro_start":
        if current_status["state"] != "idle" and current_status["job"]:
            await query.edit_message_text("🔄 Já existe um Pomodoro em andamento! Se quiser reiniciar, pare o atual primeiro com /pomodoro_stop. 😉")
            return
        
        pomodoro_status_map[chat_id] = {"state": "focus", "current_cycle": 1, "start_time": datetime.datetime.now(SAO_PAULO_TZ)}
        await start_pomodoro_timer(chat_id, "focus", user_timers["focus"], context.job_queue)
        await query.edit_message_text(f"🚀 Pomodoro Iniciado! Foco total por *{user_timers['focus']} minutos*! Você consegue! 💪", parse_mode='Markdown')
        logger.info(f"Usuário {chat_id} iniciou o Pomodoro (Ciclo 1).")

    elif query.data == "pomodoro_pause":
        if current_status["state"] not in ["idle", "paused"] and current_status["job"]:
            # CORREÇÃO: Cálculo correto do tempo restante para pausa
            if current_status.get("end_time"):
                remaining_time_seconds = (current_status["end_time"] - datetime.datetime.now(SAO_PAULO_TZ)).total_seconds()
                pomodoro_status_map[chat_id]["paused_remaining_time"] = remaining_time_seconds
                current_status["job"].schedule_removal() # Cancela o job atual
                pomodoro_status_map[chat_id]["state"] = "paused"
                await query.edit_message_text(f"⏸️ Pomodoro pausado! Tempo restante: *{int(remaining_time_seconds/60):02d}m {int(remaining_time_seconds%60):02d}s*.\n\n"
                                              "Quando estiver pronto, clique em Retomar!", parse_mode='Markdown')
                logger.info(f"Usuário {chat_id} pausou o Pomodoro.")
            else:
                await query.edit_message_text("❌ Ops, não consegui calcular o tempo restante para pausar. Tente novamente ou pare o Pomodoro.")
                logger.error(f"Erro ao pausar Pomodoro para {chat_id}: end_time não encontrado.")

        else:
            await query.edit_message_text("🤔 Não há Pomodoro ativo para pausar. Que tal começar um novo? 😉")
    
    elif query.data == "pomodoro_resume":
        if current_status["state"] == "paused" and "paused_remaining_time" in current_status:
            remaining_time = current_status["paused_remaining_time"]
            
            # Recupera o tipo de timer que estava rodando antes da pausa
            # É necessário verificar o `current_cycle` e `cycles` para saber se era foco, short_break ou long_break
            previous_state = "focus"
            if current_status["current_cycle"] > 0: # Se já passou pelo menos um ciclo
                if current_status["current_cycle"] % user_timers["cycles"] == 0:
                    previous_state = "long_break" # Era um descanso longo
                else:
                    previous_state = "short_break" # Era um descanso curto

            pomodoro_status_map[chat_id]["state"] = previous_state # Retorna ao estado anterior
            # Passa o tempo restante em segundos para a função de agendamento
            await start_pomodoro_timer(chat_id, previous_state, remaining_time / 60, context.job_queue, is_resume=True) 
            await query.edit_message_text(f"▶️ Pomodoro retomado! Foco e energia total! 💪", parse_mode='Markdown')
            logger.info(f"Usuário {chat_id} retomou o Pomodoro com {remaining_time} segundos restantes.")
        else:
            await query.edit_message_text("🤔 Não há Pomodoro pausado para retomar. Que tal iniciar um novo ciclo? 😉")

    elif query.data == "pomodoro_stop_command": # Este é para o botão no menu
        await pomodoro_stop(update, context) # Chama a função de parada
        
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

    elif query.data == "pomodoro_status_command": # Este é para o botão no menu
        await pomodoro_status(update, context)


async def pomodoro_set_time_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)
    
    setting_type = query.data.replace("set_pomodoro_", "")
    
    # Armazena o tipo de configuração esperado no user_data para ser usado em handle_text
    context.user_data["expecting"] = f"pomodoro_set_{setting_type}" 
    context.user_data["pomodoro_setting_type"] = setting_type # Guarda o tipo de configuração

    if setting_type == "cycles":
        await query.edit_message_text("🔢 Por favor, digite quantos ciclos de foco você quer fazer antes de um descanso longo (ex: '4').")
    else:
        await query.edit_message_text(f"⏱️ Digite o novo tempo em minutos para o *{setting_type.replace('_', ' ')}* (ex: '25').", parse_mode='Markdown')
    logger.info(f"Usuário {chat_id} iniciou configuração de '{setting_type}' para Pomodoro.")


async def start_pomodoro_timer(chat_id: str, timer_type: str, duration_minutes: float, job_queue: JobQueue, is_resume: bool = False):
    duration_seconds = int(duration_minutes * 60)
    
    def pomodoro_job_callback(context: ContextTypes.DEFAULT_TYPE):
        asyncio.create_task(handle_pomodoro_end(context)) # Chama a função assíncrona

    # Calcula o end_time para armazenamento
    end_time = datetime.datetime.now(SAO_PAULO_TZ) + datetime.timedelta(seconds=duration_seconds)

    job = job_queue.run_once(
        pomodoro_job_callback,
        duration_seconds,
        chat_id=int(chat_id),
        data={"timer_type": timer_type, "chat_id": chat_id},
        name=f"pomodoro_{chat_id}_{timer_type}_{datetime.datetime.now().timestamp()}"
    )
    
    # Atualiza o status map
    pomodoro_status_map[chat_id]["job"] = job
    pomodoro_status_map[chat_id]["state"] = timer_type
    pomodoro_status_map[chat_id]["end_time"] = end_time # Armazena o tempo de término

    logger.info(f"Job Pomodoro '{timer_type}' agendado para {duration_seconds} segundos para o chat {chat_id}. (Resume: {is_resume})")

async def handle_pomodoro_end(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = context.job.chat_id
    timer_type = context.job.data["timer_type"]
    user_timers = pomodoro_timers[str(chat_id)]
    current_status = pomodoro_status_map.get(str(chat_id))

    if not current_status or current_status["state"] == "idle":
        logger.warning(f"Pomodoro terminou para {chat_id} mas estado já é 'idle'. Ignorando.")
        return

    message = ""
    next_state = "idle"
    next_duration = 0
    
    if timer_type == "focus":
        current_status["current_cycle"] += 1
        message = f"🔔 *Tempo de FOCO ACABOU!* 🎉 Você completou o ciclo {current_status['current_cycle']}! "
        
        # Adicionar 5 pontos por ciclo de foco concluído
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
        current_status["current_cycle"] = 0 # Reinicia os ciclos após descanso longo
        next_state = "focus"
        next_duration = user_timers["focus"]

    await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
    logger.info(f"Pomodoro {timer_type} terminou para {chat_id}. Próximo estado: {next_state}.")

    if next_state != "idle":
        await start_pomodoro_timer(str(chat_id), next_state, next_duration, context.job_queue)
    else:
        pomodoro_status_map[str(chat_id)] = {"state": "idle", "job": None, "current_cycle": 0, "end_time": None}
        await context.bot.send_message(chat_id=chat_id, text="🥳 Ciclo de Pomodoro completo! Parabéns pela dedicação! Use /pomodoro para iniciar um novo ciclo quando quiser. Você é um arraso! ✨")
