import os
import json
import re
import datetime
import dateparser
import logging
import pytz

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import ContextTypes, JobQueue # JobQueue já importado, ótimo!

DADOS_FILE = "dados.json"

# Configura o logger para mostrar mais informações
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


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
    
    message = ""
    if alert_type == 'pre_start':
        message = f"🔔 Lembrete! Sua tarefa '{task_text}' começa em 30 minutos. Prepare-se!"
    elif alert_type == 'start':
        message = f"⏰ É agora! Sua tarefa '{task_text}' ESTÁ COMEÇANDO. Foco total!"
    elif alert_type == 'end':
        message = f"✅ Tempo esgotado! Sua tarefa '{task_text}' chegou ao fim. Hora de revisar!"
    else:
        message = f"⏰ Lembrete: Sua tarefa '{task_text}' está marcada para agora!" # Fallback

    logger.info(f"⏰ [ALERTA] Tentando enviar alerta '{alert_type}' para chat_id: {chat_id}, tarefa: '{task_text}'. Horário atual no job: {datetime.datetime.now()} (UTC).")
    
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=message
        )
        logger.info(f"✅ [ALERTA] Alerta '{alert_type}' da tarefa '{task_text}' ENVIADO com sucesso para o usuário {chat_id}.")

        # Se for o alerta de fim, perguntar sobre a conclusão
        if alert_type == 'end':
            # Adicionar um estado para esperar a resposta sobre a conclusão
            # Verifica se já não está esperando feedback para evitar sobreposição
            # A lógica de `context.user_data.get('expecting') != 'task_completion_feedback'`
            # pode ser um pouco frágil se o usuário tiver várias tarefas terminando ao mesmo tempo.
            # Uma abordagem mais robusta seria usar um ID único para a tarefa na pergunta.
            # Por enquanto, manteremos sua lógica, mas é algo a se observar.
            # A pergunta de conclusão deve ser sempre enviada ao final da tarefa.
            
            # Para garantir que a pergunta seja sobre a tarefa correta,
            # vamos passar o ID da tarefa (ou o índice) para o callback_data
            # e armazenar no user_data para referência.
            
            # Primeiro, encontre a tarefa no banco de dados para obter seu índice ou ID
            # (Assumindo que `task_text` é único o suficiente para encontrar a tarefa recente)
            db = load_data()
            user_data = db.setdefault(str(chat_id), {})
            tarefas = user_data.setdefault("tarefas", [])
            
            current_task_idx = -1
            # Procura a tarefa mais recente que corresponde à descrição e não está concluída
            for i in reversed(range(len(tarefas))):
                if tarefas[i]['activity'] == task_text and not tarefas[i].get('done'):
                    current_task_idx = i
                    break
            
            if current_task_idx != -1:
                context.user_data['expecting'] = 'task_completion_feedback'
                context.user_data['current_task_idx_for_feedback'] = current_task_idx # Armazena o índice da tarefa
                
                keyboard = [
                    [InlineKeyboardButton("Sim, concluí! 🎉", callback_data=f"feedback_yes_{current_task_idx}")],
                    [InlineKeyboardButton("Não, não concluí. 😔", callback_data=f"feedback_no_{current_task_idx}")],
                ]
                markup = InlineKeyboardMarkup(keyboard)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"A tarefa '{task_text}' terminou. Você a concluiu?",
                    reply_markup=markup
                )
                logger.info(f"Pergunta de conclusão enviada para a tarefa '{task_text}' (índice {current_task_idx}) para o usuário {chat_id}.")
            else:
                logger.warning(f"Não encontrei tarefa pendente '{task_text}' para enviar pergunta de conclusão. Usuário {chat_id}.")


    except Exception as e:
        logger.error(f"❌ [ALERTA] ERRO ao enviar alerta '{alert_type}' para chat_id: {chat_id}, tarefa: '{task_text}'. Erro: {e}", exc_info=True)


# 1) Exibe menu principal
async def rotina(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("📈 Criar Meta", callback_data="menu_meta")],
        [InlineKeyboardButton("⏰ Agendar Tarefa", callback_data="menu_schedule")],
        [InlineKeyboardButton("📋 Minhas Metas", callback_data="menu_list_metas")],
        [InlineKeyboardButton("📝 Minhas Tarefas", callback_data="menu_list_tasks")],
        [InlineKeyboardButton("📊 Feedback do Dia", callback_data="menu_daily_feedback")], # Novo botão para feedback diário
    ]
    markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "👋 Olá! Sou seu assistente de rotina. Escolha uma opção para começarmos:",
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
            "🎯 Que ótimo! Qual a descrição da meta semanal que você quer alcançar? Seja específico!"
        )
        return

    # Agendar Tarefa (Primeiro passo: pedir data/hora)
    if cmd == "menu_schedule":
        context.user_data["expecting"] = "schedule_datetime"
        await query.edit_message_text(
            "📅 Certo! Para quando e que horas você quer agendar essa tarefa? "
            "(Ex: 'Amanhã 14h', '20/07 15h', '08:30 às 12:00h', 'Quarta 9h')"
        )
        return

    # Listar Metas
    if cmd == "menu_list_metas":
        metas = user.get("metas", [])
        if metas:
            texto = "📈 Suas Metas Semanais:\n\n" + "\n".join(
                f"• {m['activity']}" for m in metas
            ) + "\n\nBora conquistar essas metas!"
        else:
            texto = "📈 Você ainda não definiu nenhuma meta semanal. Que tal criar uma agora?"
        await query.edit_message_text(texto)
        return

    # Listar Tarefas
    if cmd == "menu_list_tasks":
        tarefas = user.get("tarefas", [])
        if tarefas:
            await query.edit_message_text("📝 Suas Tarefas Agendadas:") # Mensagem inicial
            
            # Filtra tarefas futuras ou tarefas do dia atual que ainda não foram concluídas
            now_naive = datetime.datetime.now(pytz.timezone('America/Sao_Paulo')).replace(tzinfo=None)
            
            # Ordena as tarefas por data de início para exibir de forma organizada
            tarefas_ordenadas = sorted(tarefas, key=lambda x: datetime.datetime.fromisoformat(x['start_when']))

            has_tasks_to_display = False
            for i, t in enumerate(tarefas_ordenadas):
                start_dt_obj = datetime.datetime.fromisoformat(t['start_when'])
                
                # Considera a tarefa se for futura ou se for do dia atual e ainda não tiver terminado
                # ou se for uma tarefa do passado recente que ainda não foi marcada como concluída
                is_future_task = start_dt_obj > now_naive - datetime.timedelta(minutes=5) # 5 min buffer para tarefas recém-passadas
                
                if is_future_task or not t.get('done'): # Exibe todas as tarefas pendentes ou futuras
                    has_tasks_to_display = True
                    start_when_str = start_dt_obj.strftime("%d/%m/%Y às %H:%M")
                    end_when_str = ""
                    
                    if isinstance(t.get('end_when'), str) and t.get('end_when'):
                        try:
                            end_dt_obj = datetime.datetime.fromisoformat(t['end_when'])
                            end_when_str = f" até {end_dt_obj.strftime('%H:%M')}"
                        except ValueError:
                            end_when_str = f" até {t['end_when']}"
                    
                    status = "✅ Concluída" if t.get('done') else "⏳ Pendente"
                    if t.get('completion_status') == 'not_completed':
                        status = "❌ Não Concluída"
                        if t.get('reason_not_completed'):
                            status += f" (Motivo: {t['reason_not_completed']})"

                    task_display_text = f"• {t['activity']} em {start_when_str}{end_when_str} [{status}]"
                    
                    # Adiciona botão para marcar como concluída (apenas se pendente)
                    if not t.get('done') and t.get('completion_status') != 'not_completed':
                        keyboard = [[InlineKeyboardButton("Marcar como Concluída ✅", callback_data=f"mark_done_{i}")]]
                        markup = InlineKeyboardMarkup(keyboard)
                        await context.bot.send_message(
                            chat_id=query.message.chat_id,
                            text=task_display_text,
                            reply_markup=markup
                        )
                    else:
                        await context.bot.send_message(
                            chat_id=query.message.chat_id,
                            text=task_display_text
                        )
            
            if not has_tasks_to_display:
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="🎉 Parabéns! Você não tem tarefas pendentes ou futuras no momento."
                )
        else:
            await query.edit_message_text("📝 Você ainda não tem tarefas agendadas. Que tal agendar uma agora?")
        return
    
    # Novo: Feedback Diário (ainda não implementado, apenas o esqueleto)
    if cmd == "menu_daily_feedback":
        await send_daily_feedback(update, context) # Chama a nova função de feedback diário
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
            f"✅ Meta “{atividade}” salva com sucesso! Agora, vamos trabalhar para alcançá-la! 💪"
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
            
            sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
            now_aware = datetime.datetime.now(sao_paulo_tz)
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
                    text_without_time_range or "hoje",
                    settings={
                        "DATE_ORDER": "DMY",
                        "RELATIVE_BASE": now_aware,
                        "TIMEZONE": "America/Sao_Paulo",
                        "RETURN_AS_TIMEZONE_AWARE": False,
                        "PREFER_DATES_FROM": "current_period",
                        "STRICT_PARSING": False
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

                if temp_start_dt < now_naive - datetime.timedelta(minutes=1):
                    if temp_start_dt.date() == now_naive.date():
                        temp_start_dt += datetime.timedelta(days=1)
                    elif temp_start_dt.date() < now_naive.date():
                        temp_start_dt = temp_start_dt.replace(year=now_naive.year + 1)
                        if temp_start_dt < now_naive - datetime.timedelta(minutes=1):
                            temp_start_dt += datetime.timedelta(days=1)
                
                start_dt_naive = temp_start_dt
                
                if temp_end_dt <= start_dt_naive:
                    temp_end_dt += datetime.timedelta(days=1)
                
                end_dt_naive = temp_end_dt
                
                logger.info(f"Parse com intervalo (regex): Start={start_dt_naive}, End={end_dt_naive} para '{processed_text}'")

            if not start_dt_naive:
                dt_parsed = dateparser.parse(
                    processed_text,
                    settings={
                        "DATE_ORDER": "DMY",
                        "TIMEZONE": "America/Sao_Paulo",
                        "RETURN_AS_TIMEZONE_AWARE": False,
                        "RELATIVE_BASE": now_aware,
                        "PREFER_DATES_FROM": "current_period",
                        "STRICT_PARSING": False
                    },
                )
                
                if dt_parsed and isinstance(dt_parsed, datetime.datetime):
                    if dt_parsed <= now_naive - datetime.timedelta(minutes=1):
                        dt_parsed_future = dateparser.parse(
                            processed_text,
                            settings={
                                "DATE_ORDER": "DMY",
                                "TIMEZONE": "America/Sao_Paulo",
                                "RETURN_AS_TIMEZONE_AWARE": False,
                                "RELATIVE_BASE": now_aware,
                                "PREFER_DATES_FROM": "future",
                                "STRICT_PARSING": False
                            },
                        )
                        if dt_parsed_future and dt_parsed_future > now_naive:
                            start_dt_naive = dt_parsed_future
                            logger.info(f"Data/hora ajustada para o futuro: {start_dt_naive} para '{processed_text}'")
                        else:
                            logger.warning(f"Data/hora '{processed_text}' ainda no passado após tentar preferir futuro. Original: {dt_parsed}, Future attempt: {dt_parsed_future}")
                            await update.message.reply_text(
                                "❌ A data/hora agendada já passou. Por favor, agende para o futuro."
                            )
                            return
                    else:
                        start_dt_naive = dt_parsed
                
                logger.info(f"Parse como única data/hora: {start_dt_naive} para '{processed_text}'")

            if not start_dt_naive or not isinstance(start_dt_naive, datetime.datetime):
                logger.warning(f"Não foi possível entender a data/hora para '{processed_text}'. Objeto: {start_dt_naive}")
                await update.message.reply_text(
                    "❌ Não entendi o dia e horário. Por favor, tente um formato claro como:\n"
                    "- Amanhã 14h\n"
                    "- 20/07 15h\n"
                    "- 08:30 às 12:00h\n"
                    "- Terça 10h"
                )
                return

            if start_dt_naive <= now_naive:
                await update.message.reply_text(
                    "❌ A data/hora de início agendada já passou. Por favor, agende para o futuro."
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
                f"Certo, agendado para *{start_display}{end_display}*.\n"
                "Agora, qual a **descrição** da tarefa? 🤔"
            )
            logger.info(f"Data/hora de início '{start_dt_naive}' e fim '{end_dt_naive}' (se houver) capturadas. Pedindo descrição da tarefa.")
            return

        except Exception as e:
            logger.error(f"Erro ao parsear data/hora '{text}': {e}", exc_info=True)
            await update.message.reply_text(f"❌ Ocorreu um erro ao processar a data/hora: {e}. Por favor, tente novamente com um formato claro como 'Amanhã 14h' ou '20/07 15h às 17h'.")
            context.user_data.pop("expecting", None)
            return

    # 3.3) Capturando a descrição da tarefa
    if state == "schedule_description":
        logger.info(f"Recebeu descrição da tarefa: '{text}'")
        temp_schedule_data = context.user_data.get("temp_schedule")
        if not temp_schedule_data:
            logger.error("Erro: temp_schedule não encontrado ao tentar agendar descrição.")
            await update.message.reply_text("❌ Ops, algo deu errado. Por favor, tente agendar novamente desde o início.")
            context.user_data.pop("expecting", None)
            return

        start_dt_naive = datetime.datetime.fromisoformat(temp_schedule_data["start_datetime"])
        end_dt_naive = None
        if temp_schedule_data["end_datetime"]:
            end_dt_naive = datetime.datetime.fromisoformat(temp_schedule_data["end_datetime"])

        sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
        
        task_start_datetime_aware = sao_paulo_tz.localize(start_dt_naive)
        
        task_end_datetime_aware = None
        if end_dt_naive:
            task_end_datetime_aware = sao_paulo_tz.localize(end_dt_naive)

        now_aware_for_job_check = datetime.datetime.now(sao_paulo_tz)

        if task_start_datetime_aware <= now_aware_for_job_check - datetime.timedelta(seconds=5): 
            await update.message.reply_text(
                "❌ A data/hora de início agendada já passou. Por favor, agende para o futuro."
            )
            context.user_data.pop("expecting", None)
            context.user_data.pop("temp_schedule", None)
            return

        # --- NOVO: AGENDANDO O ALERTA DE 30 MINUTOS ANTES ---
        pre_start_time = task_start_datetime_aware - datetime.timedelta(minutes=30)
        if pre_start_time > now_aware_for_job_check: # Apenas agenda se o lembrete ainda estiver no futuro
            logger.info(f"⏳ [AGENDAMENTO] Preparando para agendar job de PRÉ-INÍCIO (30 min antes). Horário do Job (Aware SP): {pre_start_time}")
            context.job_queue.run_once(
                send_task_alert,
                when=pre_start_time,
                chat_id=chat_id,
                data={'description': text, 'alert_type': 'pre_start'},
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
            data={'description': text, 'alert_type': 'start'},
            name=f"task_alert_start_{chat_id}_{task_start_datetime_aware.timestamp()}"
        )
        logger.info(f"✅ [AGENDAMENTO] Alerta de INÍCIO agendado para '{text}' em '{task_start_datetime_aware}'.")

        # --- AGENDANDO O ALERTA DE FIM (SE HOUVER) ---
        if task_end_datetime_aware:
            if task_end_datetime_aware <= task_start_datetime_aware:
                task_end_datetime_aware += datetime.timedelta(days=1)

            logger.info(f"⏳ [AGENDAMENTO] Preparando para agendar job de FIM. Horário do Job (Aware SP): {task_end_datetime_aware}")
            context.job_queue.run_once(
                send_task_alert,
                when=task_end_datetime_aware,
                chat_id=chat_id,
                data={'description': text, 'alert_type': 'end'},
                name=f"task_alert_end_{chat_id}_{task_end_datetime_aware.timestamp()}"
            )
            logger.info(f"✅ [AGENDAMENTO] Alerta de FIM agendado para '{text}' em '{task_end_datetime_aware}'.")
        
        # Salvando a tarefa no dados.json
        tarefas = user.setdefault("tarefas", [])
        tarefas.append({
            "activity": text,
            "done": False,
            "start_when": task_start_datetime_aware.isoformat(),
            "end_when": task_end_datetime_aware.isoformat() if task_end_datetime_aware else None,
            "completion_status": None, # Adiciona campo para feedback de conclusão
            "reason_not_completed": None # Adiciona campo para motivo de não conclusão
        })
        save_data(db)
        logger.info(f"Tarefa '{text}' salva no DADOS_FILE para o usuário {chat_id}.")

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
            f"🎉 Tarefa “{text}” agendada com sucesso para "
            f"*{start_display}{end_display}*!\n"
            "Eu te avisarei no Telegram quando for a hora, e também 30 minutos antes para você se preparar! 😉"
        )
        context.user_data.pop("expecting", None)
        context.user_data.pop("temp_schedule", None)
        logger.info(f"Mensagem de sucesso de agendamento enviada para o usuário {chat_id}.")
        return

    # 3.4) Trata feedback de conclusão da tarefa (agora via botões, não texto)
    if state == "task_completion_feedback":
        await update.message.reply_text("Por favor, use os botões 'Sim, concluí!' ou 'Não, não concluí.' para responder sobre a tarefa. 😉")
        return

    # 3.5) Capturando o motivo de não conclusão (se o usuário digitar)
    if state == "reason_for_not_completion":
        task_idx = context.user_data.get("task_idx_for_reason")
        
        db = load_data() # Recarrega para garantir dados mais recentes
        user_data = db.setdefault(chat_id, {})
        tarefas = user_data.setdefault("tarefas", [])

        if task_idx is not None and 0 <= task_idx < len(tarefas):
            tarefas[task_idx]["reason_not_completed"] = text
            # Define como 'not_completed' explicitamente aqui, caso não tenha sido antes
            tarefas[task_idx]["completion_status"] = "not_completed" 
            save_data(db)
            await update.message.reply_text(f"📝 Entendido! O motivo '{text}' foi registrado para a tarefa '{tarefas[task_idx]['activity']}'. Vamos aprender com isso! 💪")
            logger.info(f"Motivo de não conclusão registrado para tarefa {tarefas[task_idx]['activity']}.")
        else:
            await update.message.reply_text("❌ Ops, não consegui associar o motivo a uma tarefa. Por favor, tente novamente.")
            logger.warning(f"Não foi possível associar o motivo '{text}' à tarefa com índice {task_idx}.")

        context.user_data.pop("expecting", None)
        context.user_data.pop("task_idx_for_reason", None)
        return

    # 3.6) Fallback quando ninguém está aguardando texto
    logger.info(f"Texto '{text}' recebido sem estado 'expecting'.")
    await update.message.reply_text(
        "👉 Use /rotina para abrir o menu e escolher uma opção. Estou aqui para te ajudar a organizar seu dia! 😉"
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
            await query.edit_message_text("❌ Erro ao identificar a tarefa.")
            return

        logger.info(f"Usuário {chat_id} tentou marcar tarefa {idx} como concluída via botão 'Marcar como Concluída'.")
        if 0 <= idx < len(tarefas):
            tarefas[idx]["done"] = True
            tarefas[idx]["completion_status"] = "completed_manually" # Registra como concluída manualmente
            tarefas[idx]["reason_not_completed"] = None # Limpa o motivo se for marcado manualmente
            save_data(db)
            await query.edit_message_text(
                f"✅ Tarefa “{tarefas[idx]['activity']}” marcada como concluída! Mandou bem! ✨"
            )
            logger.info(f"Tarefa '{tarefas[idx]['activity']}' marcada como concluída para o usuário {chat_id}.")
        else:
            await query.edit_message_text("❌ Índice inválido para marcar como concluída.")
            logger.warning(f"Tentativa de marcar tarefa com índice inválido {idx} para o usuário {chat_id}.")
        return
    
    # Lógica para o feedback de conclusão (após o alerta de fim da tarefa)
    if cmd.startswith("feedback_yes_"):
        try:
            task_idx = int(cmd.split("_")[2]) # Pega o índice da tarefa
        except (IndexError, ValueError):
            logger.error(f"Erro ao parsear índice do callback_data: {cmd}")
            await query.edit_message_text("❌ Erro ao identificar a tarefa para feedback.")
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
            await query.edit_message_text(f"🎉 Ótimo! A tarefa '{tarefas[task_idx]['activity']}' foi marcada como concluída. Parabéns! Você ganhou 10 pontos! 🌟")
            logger.info(f"Tarefa '{tarefas[task_idx]['activity']}' marcada como concluída via feedback 'Sim'.")
        else:
            await query.edit_message_text("🤔 Não encontrei a tarefa para marcar como concluída. Por favor, tente novamente.")
            logger.warning(f"Não encontrei tarefa com índice {task_idx} para marcar como concluída via feedback 'Sim'.")
            
        context.user_data.pop("expecting", None)
        context.user_data.pop("current_task_idx_for_feedback", None)
        return

    if cmd.startswith("feedback_no_"):
        try:
            task_idx = int(cmd.split("_")[2]) # Pega o índice da tarefa
        except (IndexError, ValueError):
            logger.error(f"Erro ao parsear índice do callback_data: {cmd}")
            await query.edit_message_text("❌ Erro ao identificar a tarefa para feedback.")
            return

        if task_idx is not None and 0 <= task_idx < len(tarefas):
            tarefas[task_idx]["completion_status"] = "not_completed"
            tarefas[task_idx]["done"] = False # Garante que não está marcada como done
            save_data(db) # Salva o status de não concluída
            
            context.user_data["expecting"] = "reason_for_not_completion"
            context.user_data["task_idx_for_reason"] = task_idx # Guarda o índice da tarefa
            await query.edit_message_text(f"😔 Entendido. Por favor, digite o motivo pelo qual a tarefa '{tarefas[task_idx]['activity']}' não foi concluída:")
            logger.info(f"Solicitando motivo de não conclusão para a tarefa '{tarefas[task_idx]['activity']}'.")
        else:
            await query.edit_message_text("🤔 Não encontrei a tarefa para registrar o motivo. Por favor, tente novamente.")
            logger.warning(f"Não encontrei tarefa com índice {task_idx} para solicitar motivo de não conclusão via feedback 'Não'.")

        context.user_data.pop("current_task_idx_for_feedback", None) # Limpa, pois agora espera o motivo
        return

# --- NOVO: Função para enviar o feedback diário ---
async def send_daily_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    db = load_data()
    user_data = db.setdefault(chat_id, {})
    tarefas = user_data.setdefault("tarefas", [])
    
    sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
    today = datetime.datetime.now(sao_paulo_tz).date()

    completed_tasks_today = []
    not_completed_tasks_today = []
    imprevistos_today = []
    
    daily_score = 0

    for task in tarefas:
        task_start_dt = datetime.datetime.fromisoformat(task['start_when']).astimezone(sao_paulo_tz).date()
        
        if task_start_dt == today:
            if task.get('completion_status') == 'completed_on_time' or task.get('completion_status') == 'completed_manually':
                completed_tasks_today.append(task['activity'])
                # A pontuação já é adicionada no mark_done_callback, aqui apenas somamos para o feedback
                daily_score += 10 # Recontar para o feedback diário, ou pegar de um campo 'points_earned' na tarefa
            elif task.get('completion_status') == 'not_completed':
                not_completed_tasks_today.append(task['activity'])
                if task.get('reason_not_completed'):
                    imprevistos_today.append(f"- {task['activity']}: {task['reason_not_completed']}")
    
    feedback_message = f"✨ Seu Feedback Diário ({today.strftime('%d/%m/%Y')}):\n\n"
    
    if completed_tasks_today:
        feedback_message += "✅ Tarefas Concluídas:\n" + "\n".join(f"• {t}" for t in completed_tasks_today) + "\n\n"
    else:
        feedback_message += "😔 Nenhuma tarefa concluída hoje ainda. Bora pra cima! 💪\n\n"
        
    if not_completed_tasks_today:
        feedback_message += "❌ Tarefas Não Concluídas:\n" + "\n".join(f"• {t}" for t in not_completed_tasks_today) + "\n\n"
        
    if imprevistos_today:
        feedback_message += "⚠️ Imprevistos Registrados:\n" + "\n".join(imprevistos_today) + "\n\n"
        
    feedback_message += f"📊 Pontuação do Dia: {daily_score} pontos\n"
    feedback_message += f"🏆 Pontuação Total: {user_data.get('score', 0)} pontos\n\n"
    feedback_message += "Lembre-se: Cada esforço conta! Continue firme! ✨"
    
    await context.bot.send_message(chat_id=chat_id, text=feedback_message)
    logger.info(f"Feedback diário enviado para o usuário {chat_id}.")
