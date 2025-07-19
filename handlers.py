import os
import json
import re
import datetime
import dateparser
import logging
import pytz
import asyncio # Adicionado para usar sleep se necessário

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

def load_data():
    if not os.path.exists(DADOS_FILE):
        return {}
    with open(DADOS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DADOS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# --- Função para enviar o alerta da tarefa ---
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
            # Para garantir que a pergunta seja sobre a tarefa correta,
            # vamos usar o task_idx que foi passado no job.data
            
            if task_idx is not None:
                # O estado 'expecting' aqui é menos importante, pois a resposta virá via callback_query.
                # No entanto, podemos usá-lo para evitar que o handle_text geral capture a resposta.
                context.user_data['expecting'] = 'task_completion_feedback' 
                # Não precisamos de 'current_task_idx_for_feedback' se o feedback vier com o idx no callback_data
                
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


# 1) Exibe menu principal
async def rotina(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("📈 Criar Meta", callback_data="menu_meta")],
        [InlineKeyboardButton("⏰ Agendar Tarefa", callback_data="menu_schedule")],
        [InlineKeyboardButton("📋 Minhas Metas", callback_data="menu_list_metas")],
        [InlineKeyboardButton("📝 Minhas Tarefas", callback_data="menu_list_tasks")],
        [InlineKeyboardButton("🗓️ Agendar Rotina Semanal", callback_data="menu_weekly_routine")], # Novo botão
        [InlineKeyboardButton("📊 Feedback do Dia", callback_data="menu_daily_feedback")],
    ]
    markup = InlineKeyboardMarkup(keyboard)
    await (update.message or update.callback_query.message).reply_text( # Responde à mensagem ou à query
        "👋 Olá! Sou seu assistente de rotina! Vamos organizar seu dia? Escolha uma opção para começarmos! ✨",
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
            "🎯 Que ótimo! Qual a descrição da meta que você quer alcançar? Seja específico e focado! 💪"
        )
        return

    # Agendar Tarefa (Primeiro passo: pedir data/hora)
    if cmd == "menu_schedule":
        context.user_data["expecting"] = "schedule_datetime"
        await query.edit_message_text(
            "📅 Certo! Para quando e que horas você quer agendar essa tarefa? "
            "Ex: 'Amanhã 14h', '20/07 15h', '08:30 às 12:00h', 'Quarta 9h'. Posso te ajudar com isso! ✨"
        )
        return

    # Listar Metas
    if cmd == "menu_list_metas":
        metas = user.get("metas", [])
        if metas:
            text_lines = ["📈 Suas Metas Incríveis:"]
            for i, m in enumerate(metas):
                text_lines.append(f"• {m['activity']}")
            
            # Adicionar botões para apagar metas
            keyboard_rows = []
            for i, m in enumerate(metas):
                keyboard_rows.append([InlineKeyboardButton(f"🗑️ Apagar '{m['activity']}'", callback_data=f"delete_meta_{i}")])
            
            markup = InlineKeyboardMarkup(keyboard_rows)
            text_lines.append("\nBora conquistar essas metas! Se precisar apagar alguma, é só clicar! 👇")
            await query.edit_message_text("\n".join(text_lines), reply_markup=markup)
        else:
            await query.edit_message_text("📈 Você ainda não definiu nenhuma meta. Que tal criar uma agora para impulsionar seus objetivos? 💪")
        return
    
    # Listar Tarefas
    if cmd == "menu_list_tasks":
        tarefas = user.get("tarefas", [])
        if not tarefas:
            await query.edit_message_text("📝 Você ainda não tem tarefas agendadas. Que tal agendar uma agora e dar um passo à frente? 🚀")
            return
        
        await query.edit_message_text("📝 Suas Tarefas Agendadas:") # Mensagem inicial
        
        # Filtra tarefas futuras ou tarefas do dia atual que ainda não foram concluídas
        now_aware = datetime.datetime.now(SAO_PAULO_TZ)
        
        # Ordena as tarefas por data de início para exibir de forma organizada
        tarefas_ordenadas = sorted(tarefas, key=lambda x: datetime.datetime.fromisoformat(x['start_when']))

        has_tasks_to_display = False
        for i, t in enumerate(tarefas_ordenadas):
            start_dt_obj_naive = datetime.datetime.fromisoformat(t['start_when'])
            start_dt_obj_aware = SAO_PAULO_TZ.localize(start_dt_obj_naive)
            
            # Considera a tarefa se for futura ou se for do dia atual e ainda não tiver terminado
            # ou se for uma tarefa do passado recente que ainda não foi marcada como concluída
            # Considerar tasks que começaram hoje ou estão no futuro E que não foram concluídas
            if start_dt_obj_aware.date() >= now_aware.date() or not t.get('done', False):
                has_tasks_to_display = True
                start_when_str = start_dt_obj_aware.strftime("%d/%m/%Y às %H:%M")
                end_when_str = ""
                
                if isinstance(t.get('end_when'), str) and t.get('end_when'):
                    try:
                        end_dt_obj_naive = datetime.datetime.fromisoformat(t['end_when'])
                        end_dt_obj_aware = SAO_PAULO_TZ.localize(end_dt_obj_naive)
                        end_when_str = f" até {end_dt_obj_aware.strftime('%H:%M')}"
                    except ValueError:
                        end_when_str = f" até {t['end_when']}"
                
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
                
                # Adiciona botão para marcar como concluída (apenas se pendente e não estiver atrasada)
                # ou se a tarefa já passou e não foi marcada
                if not t.get('done') and t.get('completion_status') != 'not_completed':
                    keyboard = [[InlineKeyboardButton("Marcar como Concluída ✅", callback_data=f"mark_done_{i}")]]
                    markup = InlineKeyboardMarkup(keyboard)
                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text=task_display_text,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                else:
                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text=task_display_text,
                        parse_mode='Markdown'
                    )
        
        if not has_tasks_to_display:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="🎉 Parabéns! Você não tem tarefas pendentes ou futuras no momento. Que organização! ✨"
            )
        return
    
    # Novo: Agendar Rotina Semanal
    if cmd == "menu_weekly_routine":
        await handle_weekly_routine_input(update, context) # Chama o handler para pedir a rotina
        return

    # Feedback Diário
    if cmd == "menu_daily_feedback":
        await send_daily_feedback(update, context) # Chama a função de feedback diário
        return


# Novo: Handler para receber a rotina semanal completa
async def handle_weekly_routine_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["expecting"] = "weekly_routine_text"
    await (update.message or update.callback_query.message).reply_text(
        "📚 Me envie sua rotina semanal completa, dia a dia e com horários, como no exemplo que você me deu! "
        "Vou te ajudar a transformá-la em tarefas agendadas. Capricha nos detalhes! ✨"
    )
    logger.info(f"Usuário {update.effective_user.id} solicitou input de rotina semanal.")

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
        metas.append({"activity": atividade, "progress": 0, "target": 1}) # target 1 por padrão para metas semanais
        save_data(db)
        await update.message.reply_text(
            f"✅ Meta *“{atividade}”* salva com sucesso! Agora, vamos trabalhar para alcançá-la! 💪 Que energia! ✨"
        )
        context.user_data.pop("expecting", None)
        logger.info(f"Meta '{atividade}' salva para o usuário {chat_id}.")
        return

    # 3.2) Capturando APENAS a data e hora para agendamento (início e/ou fim)
    if state == "schedule_datetime":
        logger.info(f"Tentando parsear data/hora: '{text}'")
        try:
            processed_text = text.replace('h', '').strip()
            logger.info(f"Texto pré-processado para dateparser: '{processed_text}'")
            
            now_aware = datetime.datetime.now(SAO_PAULO_TZ)
            now_naive = now_aware.replace(tzinfo=None) # Current datetime without timezone for comparisons

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
                    text_without_time_range or "hoje", # Se não houver data, assume "hoje"
                    settings={
                        "DATE_ORDER": "DMY",
                        "RELATIVE_BASE": now_aware,
                        "TIMEZONE": SAO_PAULO_TZ.zone,
                        "RETURN_AS_TIMEZONE_AWARE": False,
                        "PREFER_DATES_FROM": "current_period",
                        "STRICT_PARSING": False,
                        "LANGUAGES": ['pt']
                    }
                )
                
                if not parsed_date_only or not isinstance(parsed_date_only, datetime.datetime):
                    base_date_naive = now_naive.date()
                    logger.info(f"Não foi possível parsear data explícita. Usando data base: {base_date_naive}")
                else:
                    base_date_naive = parsed_date_only.date()
                    logger.info(f"Data base parseada: {base_date_naive} de '{text_without_time_range}'")
                
                temp_start_dt = datetime.datetime.combine(base_date_naive, datetime.datetime.strptime(start_time_str, '%H:%M').time())
                temp_end_dt = datetime.datetime.combine(base_date_naive, datetime.datetime.strptime(end_time_str, '%H:%M').time())

                # Ajusta para o dia seguinte se a hora de início for no passado no dia de hoje
                if temp_start_dt < now_naive - datetime.timedelta(minutes=1):
                    temp_start_dt += datetime.timedelta(days=1)
                    if temp_end_dt <= temp_start_dt.replace(hour=temp_start_dt.hour, minute=temp_start_dt.minute, second=0, microsecond=0): # Se o fim for antes ou igual ao novo início, ajusta o fim
                        temp_end_dt += datetime.timedelta(days=1)
                
                start_dt_naive = temp_start_dt
                end_dt_naive = temp_end_dt
                
                logger.info(f"Parse com intervalo (regex): Start={start_dt_naive}, End={end_dt_naive} para '{processed_text}'")

            if not start_dt_naive: # Se não encontrou intervalo, tenta parsear como uma única data/hora
                dt_parsed = dateparser.parse(
                    processed_text,
                    settings={
                        "DATE_ORDER": "DMY",
                        "TIMEZONE": SAO_PAULO_TZ.zone,
                        "RETURN_AS_TIMEZONE_AWARE": False,
                        "RELATIVE_BASE": now_aware,
                        "PREFER_DATES_FROM": "current_period", # Prefere o período atual, mas pode ser ajustado
                        "STRICT_PARSING": False,
                        "LANGUAGES": ['pt']
                    },
                )
                
                if dt_parsed and isinstance(dt_parsed, datetime.datetime):
                    # Se a data/hora parseada for no passado, tenta preferir o futuro
                    if dt_parsed <= now_naive - datetime.timedelta(minutes=1):
                        dt_parsed_future = dateparser.parse(
                            processed_text,
                            settings={
                                "DATE_ORDER": "DMY",
                                "TIMEZONE": SAO_PAULO_TZ.zone,
                                "RETURN_AS_TIMEZONE_AWARE": False,
                                "RELATIVE_BASE": now_aware,
                                "PREFER_DATES_FROM": "future", # Tenta forçar para o futuro
                                "STRICT_PARSING": False,
                                "LANGUAGES": ['pt']
                            },
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

    # 3.3) Capturando a descrição da tarefa
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
        
        # Salvando a tarefa no dados.json ANTES de agendar os jobs
        # Isso garante que o índice da tarefa seja estável
        tarefas = user.setdefault("tarefas", [])
        new_task_data = {
            "activity": text,
            "done": False,
            "start_when": task_start_datetime_aware.isoformat(),
            "end_when": task_end_datetime_aware.isoformat() if task_end_datetime_aware else None,
            "completion_status": None,
            "reason_not_completed": None
        }
        tarefas.append(new_task_data)
        save_data(db)
        # O índice da tarefa recém-adicionada é (len(tarefas) - 1)
        current_task_idx = len(tarefas) - 1
        logger.info(f"Tarefa '{text}' salva no DADOS_FILE com índice {current_task_idx} para o usuário {chat_id}.")


        # --- NOVO: AGENDANDO O ALERTA DE 30 MINUTOS ANTES ---
        pre_start_time = task_start_datetime_aware - datetime.timedelta(minutes=30)
        if pre_start_time > now_aware_for_job_check: # Apenas agenda se o lembrete ainda estiver no futuro
            logger.info(f"⏳ [AGENDAMENTO] Preparando para agendar job de PRÉ-INÍCIO (30 min antes). Horário do Job (Aware SP): {pre_start_time}")
            context.job_queue.run_once(
                send_task_alert,
                when=pre_start_time,
                chat_id=chat_id,
                data={'description': text, 'alert_type': 'pre_start', 'task_idx': current_task_idx},
                name=f"task_alert_pre_start_{chat_id}_{task_start_datetime_aware.timestamp()}"
            )
            logger.info(f"✅ [AGENDAMENTO] Alerta de PRÉ-INÍCIO agendado para '{text}' em '{pre_start_time}'.")
        else:
            logger.info(f"🚫 [AGENDAMENTO] Alerta de PRÉ-INÍCIO para '{text}' no passado, não agendado.")

        # --- AGENDANDO O ALERTA DE INÍCIO ---
        logger.info(f"⏳ [AGENDAMENTO] Preparando para agendar job de INÍCIO. Horário do Job (Aware SP): {task_start_datetime_aware} | Horário atual (Aware SP): {now_aware_for_job_check}")
        context.job_queue.run_once(
            send_task_alert,
            when=task_start_datetime_aware,
            chat_id=chat_id,
            data={'description': text, 'alert_type': 'start', 'task_idx': current_task_idx},
            name=f"task_alert_start_{chat_id}_{task_start_datetime_aware.timestamp()}"
        )
        logger.info(f"✅ [AGENDAMENTO] Alerta de INÍCIO agendado para '{text}' em '{task_start_datetime_aware}'.")

        # --- AGENDANDO O ALERTA DE FIM (SE HOUVER) ---
        if task_end_datetime_aware:
            # Garante que o fim seja no futuro ou após o início (evita fim antes do início se data/hora forem iguais)
            if task_end_datetime_aware <= task_start_datetime_aware:
                task_end_datetime_aware += datetime.timedelta(days=1)

            logger.info(f"⏳ [AGENDAMENTO] Preparando para agendar job de FIM. Horário do Job (Aware SP): {task_end_datetime_aware}")
            context.job_queue.run_once(
                send_task_alert,
                when=task_end_datetime_aware,
                chat_id=chat_id,
                data={'description': text, 'alert_type': 'end', 'task_idx': current_task_idx},
                name=f"task_alert_end_{chat_id}_{task_end_datetime_aware.timestamp()}"
            )
            logger.info(f"✅ [AGENDAMENTO] Alerta de FIM agendado para '{text}' em '{task_end_datetime_aware}'.")
        
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

    # 3.4) Tratando a entrada da Rotina Semanal
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

    # 3.5) Capturando o motivo de não conclusão (se o usuário digitar)
    if state == "reason_for_not_completion":
        task_idx = context.user_data.get("task_idx_for_reason")
        
        db = load_data() # Recarrega para garantir dados mais recentes
        user_data = db.setdefault(chat_id, {})
        tarefas = user_data.setdefault("tarefas", [])

        if task_idx is not None and 0 <= task_idx < len(tarefas):
            tarefas[task_idx]["reason_not_completed"] = text
            tarefas[task_idx]["completion_status"] = "not_completed" # Define como 'not_completed' explicitamente
            tarefas[task_idx]["done"] = False # Garante que não está marcada como done
            save_data(db)
            await update.message.reply_text(f"📝 Entendido! O motivo *'{text}'* foi registrado para a tarefa *'{tarefas[task_idx]['activity']}'*. Vamos aprender com isso e seguir em frente! 💪")
            logger.info(f"Motivo de não conclusão registrado para tarefa {tarefas[task_idx]['activity']}.")
        else:
            await update.message.reply_text("❌ Ops, não consegui associar o motivo a uma tarefa. Por favor, tente novamente. Qual é a tarefa? 🤔")
            logger.warning(f"Não foi possível associar o motivo '{text}' à tarefa com índice {task_idx}.")

        context.user_data.pop("expecting", None)
        context.user_data.pop("task_idx_for_reason", None)
        return

    # 3.6) Fallback quando ninguém está aguardando texto
    logger.info(f"Texto '{text}' recebido sem estado 'expecting'.")
    await update.message.reply_text(
        "👉 Use /rotina para abrir o menu e escolher uma opção. Estou aqui para te ajudar a organizar seu dia e alcançar seus objetivos! 😉"
    )

# 4) Marcar tarefa como concluída (agora também lida com feedback de conclusão)
async def mark_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    chat_id = str(query.message.chat_id)
    db = load_data()
    user_data = db.setdefault(chat_id, {})
    tarefas = user_data.setdefault("tarefas", [])

    cmd = query.data
    logger.info(f"Usuário {chat_id} clicou em callback: {cmd}.")

    # Lógica para marcar tarefa como concluída (do menu "Minhas Tarefas")
    if cmd.startswith("mark_done_"):
        try:
            idx = int(cmd.split("_")[2]) # Pega o índice após "mark_done_"
        except (IndexError, ValueError):
            logger.error(f"Erro ao parsear índice do callback_data: {cmd}")
            await query.edit_message_text("❌ Erro ao identificar a tarefa. Por favor, tente novamente!")
            return

        logger.info(f"Usuário {chat_id} tentou marcar tarefa {idx} como concluída via botão 'Marcar como Concluída'.")
        if 0 <= idx < len(tarefas):
            tarefas[idx]["done"] = True
            tarefas[idx]["completion_status"] = "completed_manually" # Registra como concluída manualmente
            tarefas[idx]["reason_not_completed"] = None # Limpa o motivo se for marcado manualmente
            
            # Adiciona pontos pela conclusão da tarefa
            user_data["score"] = user_data.get("score", 0) + 10 # Exemplo: 10 pontos por tarefa concluída
            logger.info(f"Usuário {chat_id} ganhou 10 pontos. Pontuação atual: {user_data['score']}.")

            save_data(db)
            await query.edit_message_text(
                f"✅ EBA! Tarefa *“{tarefas[idx]['activity']}”* marcada como concluída! Mandou muito bem! 🎉 Você ganhou 10 pontos! 🌟"
            )
            logger.info(f"Tarefa '{tarefas[idx]['activity']}' marcada como concluída para o usuário {chat_id}.")
        else:
            await query.edit_message_text("❌ Não encontrei essa tarefa para marcar como concluída. Ela pode já ter sido concluída ou apagada. 🤔")
            logger.warning(f"Tentativa de marcar tarefa com índice inválido {idx} para o usuário {chat_id}.")
        return
    
    # Lógica para o feedback de conclusão (após o alerta de fim da tarefa)
    if cmd.startswith("feedback_yes_"):
        try:
            task_idx = int(cmd.split("_")[2]) # Pega o índice da tarefa
        except (IndexError, ValueError):
            logger.error(f"Erro ao parsear índice do callback_data: {cmd}")
            await query.edit_message_text("❌ Erro ao identificar a tarefa para feedback. Que pena! 😔")
            return

        if task_idx is not None and 0 <= task_idx < len(tarefas):
            tarefas[task_idx]["done"] = True
            tarefas[task_idx]["completion_status"] = "completed_on_time"
            tarefas[task_idx]["reason_not_completed"] = None # Limpa o motivo se for concluída
            
            # --- NOVO: Lógica de Pontuação ---
            # Adiciona pontos pela conclusão da tarefa
            user_data["score"] = user_data.get("score", 0) + 10 # Exemplo: 10 pontos por tarefa concluída
            logger.info(f"Usuário {chat_id} ganhou 10 pontos. Pontuação atual: {user_data['score']}.")

            save_data(db)
            await query.edit_message_text(f"🎉 PARABÉNS! A tarefa *'{tarefas[task_idx]['activity']}'* foi marcada como concluída! Que orgulho! Você ganhou 10 pontos! 🌟 Continue assim! 💪")
            logger.info(f"Tarefa '{tarefas[task_idx]['activity']}' marcada como concluída via feedback 'Sim'.")
        else:
            await query.edit_message_text("🤔 Não encontrei a tarefa para marcar como concluída. Ela pode já ter sido concluída ou apagada. Por favor, tente novamente!")
            logger.warning(f"Não encontrei tarefa com índice {task_idx} para marcar como concluída via feedback 'Sim'.")
            
        context.user_data.pop("expecting", None)
        # context.user_data.pop("current_task_idx_for_feedback", None) # Não necessário se o índice for passado pelo callback
        return

    if cmd.startswith("feedback_no_"):
        try:
            task_idx = int(cmd.split("_")[2]) # Pega o índice da tarefa
        except (IndexError, ValueError):
            logger.error(f"Erro ao parsear índice do callback_data: {cmd}")
            await query.edit_message_text("❌ Erro ao identificar a tarefa para feedback. Oops! 😔")
            return

        if task_idx is not None and 0 <= task_idx < len(tarefas):
            tarefas[task_idx]["completion_status"] = "not_completed"
            tarefas[task_idx]["done"] = False # Garante que não está marcada como done
            save_data(db) # Salva o status de não concluída
            
            context.user_data["expecting"] = "reason_for_not_completion"
            context.user_data["task_idx_for_reason"] = task_idx # Guarda o índice da tarefa
            await query.edit_message_text(f"😔 Ah, que pena! A tarefa *'{tarefas[task_idx]['activity']}'* não foi concluída. Por favor, digite o motivo: foi um imprevisto, falta de tempo, ou algo mais? Me conta para aprendermos juntos! 👇")
            logger.info(f"Solicitando motivo de não conclusão para a tarefa '{tarefas[task_idx]['activity']}'.")
        else:
            await query.edit_message_text("🤔 Não encontrei a tarefa para registrar o motivo. Ela pode já ter sido concluída ou apagada. Por favor, tente novamente!")
            logger.warning(f"Não encontrei tarefa com índice {task_idx} para solicitar motivo de não conclusão via feedback 'Não'.")

        # context.user_data.pop("current_task_idx_for_feedback", None) # Não necessário se o índice for passado pelo callback
        return

# Novo: Handler para apagar metas
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

# --- NOVO: Função para enviar o feedback diário (chamada pelo jobs.py e pelo menu) ---
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
    
    daily_score = 0

    for task in tarefas:
        try:
            task_start_dt_naive = datetime.datetime.fromisoformat(task['start_when'])
            task_start_dt_aware = SAO_PAULO_TZ.localize(task_start_dt_naive)
            task_date = task_start_dt_aware.date()
        except ValueError:
            logger.warning(f"Data de início inválida para a tarefa: {task.get('activity')}. Pulando.")
            continue # Pula esta tarefa se a data for inválida
            
        if task_date == today:
            if task.get('completion_status') == 'completed_on_time' or task.get('completion_status') == 'completed_manually':
                completed_tasks_today.append(task['activity'])
                # A pontuação já é adicionada no mark_done_callback, aqui apenas somamos para o feedback
                daily_score += 10 # Recontar para o feedback diário, ou pegar de um campo 'points_earned' na tarefa
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
        
    feedback_message += f"📊 Pontuação do Dia: *{daily_score}* pontos\n"
    feedback_message += f"🏆 Pontuação Total: *{user_data.get('score', 0)}* pontos\n\n"
    feedback_message += "Lembre-se: Cada esforço conta! Continue firme! Você é incrível! ✨"
    
    # Decidir se edita a mensagem (se veio de callback) ou envia nova (se veio de comando ou job)
    if update.callback_query:
        await update.callback_query.edit_message_text(text=feedback_message, parse_mode='Markdown')
    else:
        await context.bot.send_message(chat_id=chat_id, text=feedback_message, parse_mode='Markdown')
    logger.info(f"Feedback diário enviado para o usuário {chat_id}.")


# --- NOVO: Função para parsing de rotina semanal ---
async def parse_and_schedule_weekly_routine(chat_id: str, routine_text: str, job_queue: JobQueue) -> int:
    lines = routine_text.split('\n')
    current_day = None
    scheduled_tasks_count = 0
    
    now_aware = datetime.datetime.now(SAO_PAULO_TZ)

    # Mapeamento de nomes de dias em português para números (0=Segunda, 6=Domingo)
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
            # Tenta detectar horário e atividade
            time_activity_match = re.search(r'(\d{1,2}h(?:(\d{2}))?)\s*(?:[-–—]\s*(\d{1,2}h(?:(\d{2}))?))?:\s*(.+)', line, re.IGNORECASE)
            
            if time_activity_match:
                start_time_str = time_activity_match.group(1)
                end_time_str = time_activity_match.group(3)
                activity_description = time_activity_match.group(5).strip()
                
                # Formata os horários para 'HH:MM'
                start_h = int(re.search(r'(\d{1,2})h', start_time_str).group(1))
                start_m = int(re.search(r'h(\d{2})', start_time_str).group(1)) if re.search(r'h(\d{2})', start_time_str) else 0
                formatted_start_time = f"{start_h:02d}:{start_m:02d}"

                formatted_end_time = None
                if end_time_str:
                    end_h = int(re.search(r'(\d{1,2})h', end_time_str).group(1))
                    end_m = int(re.search(r'h(\d{2})', end_time_str).group(1)) if re.search(r'h(\d{2})', end_time_str) else 0
                    formatted_end_time = f"{end_h:02d}:{end_m:02d}"

                logger.info(f"   Detectado: Dia={current_day}, Início={formatted_start_time}, Fim={formatted_end_time}, Atividade='{activity_description}'")

                # Calcula a próxima ocorrência da tarefa
                target_date = now_aware.date()
                while target_date.weekday() != current_day: # weekday() retorna 0 para segunda, 6 para domingo
                    target_date += datetime.timedelta(days=1)
                
                # Se a data alvo já passou na semana atual, avança para a próxima semana
                if target_date.weekday() == now_aware.weekday() and \
                   datetime.datetime.strptime(formatted_start_time, '%H:%M').time() < now_aware.time():
                    target_date += datetime.timedelta(weeks=1)

                start_dt_naive = datetime.datetime.combine(target_date, datetime.datetime.strptime(formatted_start_time, '%H:%M').time())
                start_dt_aware = SAO_PAULO_TZ.localize(start_dt_naive)

                end_dt_aware = None
                if formatted_end_time:
                    end_dt_naive = datetime.datetime.combine(target_date, datetime.datetime.strptime(formatted_end_time, '%H:%M').time())
                    # Se a hora de fim for antes da hora de início no mesmo dia, significa que termina no dia seguinte
                    if end_dt_naive <= start_dt_naive:
                        end_dt_naive += datetime.timedelta(days=1)
                    end_dt_aware = SAO_PAULO_TZ.localize(end_dt_naive)

                # Agenda a tarefa e salva no dados.json
                new_task_data = {
                    "activity": activity_description,
                    "done": False,
                    "start_when": start_dt_aware.isoformat(),
                    "end_when": end_dt_aware.isoformat() if end_dt_aware else None,
                    "completion_status": None,
                    "reason_not_completed": None,
                    "recurring": True # Marca como tarefa recorrente
                }
                tarefas.append(new_task_data)
                
                # O índice da tarefa recém-adicionada
                current_task_idx = len(tarefas) - 1

                # Agendar job para esta ocorrência da tarefa (com repetição para próximas semanas)
                # IMPORTANTE: run_repeating não é ideal para agendamento semanal complexo de rotinas.
                # A melhor abordagem para rotinas semanais é agendar a próxima ocorrência ao concluir/passar a atual.
                # Para simplificar aqui e agendar pelo menos a primeira ocorrência:
                
                if start_dt_aware > now_aware:
                    logger.info(f"   Agendando primeira ocorrência de '{activity_description}' para {start_dt_aware} (Aware)")
                    job_queue.run_once(
                        send_task_alert,
                        when=start_dt_aware,
                        chat_id=chat_id,
                        data={'description': activity_description, 'alert_type': 'start', 'task_idx': current_task_idx},
                        name=f"recurring_task_start_{chat_id}_{start_dt_aware.timestamp()}"
                    )
                    scheduled_tasks_count += 1

                    if end_dt_aware and end_dt_aware > now_aware:
                        logger.info(f"   Agendando alerta de fim para '{activity_description}' em {end_dt_aware} (Aware)")
                        job_queue.run_once(
                            send_task_alert,
                            when=end_dt_aware,
                            chat_id=chat_id,
                            data={'description': activity_description, 'alert_type': 'end', 'task_idx': current_task_idx},
                            name=f"recurring_task_end_{chat_id}_{end_dt_aware.timestamp()}"
                        )

                    pre_start_time = start_dt_aware - datetime.timedelta(minutes=30)
                    if pre_start_time > now_aware:
                        logger.info(f"   Agendando alerta de pré-início para '{activity_description}' em {pre_start_time} (Aware)")
                        job_queue.run_once(
                            send_task_alert,
                            when=pre_start_time,
                            chat_id=chat_id,
                            data={'description': activity_description, 'alert_type': 'pre_start', 'task_idx': current_task_idx},
                            name=f"recurring_task_pre_start_{chat_id}_{start_dt_aware.timestamp()}"
                        )
                else:
                    logger.warning(f"   Tarefa '{activity_description}' no passado, não agendada: {start_dt_aware}")

    save_data(db)
    return scheduled_tasks_count
