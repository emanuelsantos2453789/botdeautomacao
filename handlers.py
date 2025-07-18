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
from telegram.ext import ContextTypes, JobQueue

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
    alert_type = task_data['alert_type'] # 'start' ou 'end'
    
    if alert_type == 'start':
        message = f"⏰ Lembrete: Sua tarefa '{task_text}' ESTÁ COMEÇANDO agora!"
    elif alert_type == 'end':
        message = f"✅ Lembrete: Sua tarefa '{task_text}' ESTÁ TERMINANDO agora!"
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
            if context.user_data.get('expecting') != 'task_completion_feedback':
                context.user_data['expecting'] = 'task_completion_feedback'
                context.user_data['current_task_for_feedback'] = task_text # Armazena a tarefa para feedback
                
                keyboard = [
                    [InlineKeyboardButton("Sim, concluí!", callback_data="feedback_yes")],
                    [InlineKeyboardButton("Não, não concluí.", callback_data="feedback_no")],
                ]
                markup = InlineKeyboardMarkup(keyboard)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"A tarefa '{task_text}' terminou. Você a concluiu?",
                    reply_markup=markup
                )
                logger.info(f"Pergunta de conclusão enviada para a tarefa '{task_text}' para o usuário {chat_id}.")
            else:
                logger.info(f"Já esperando feedback para outra tarefa. Pulando pergunta para '{task_text}'.")


    except Exception as e:
        logger.error(f"❌ [ALERTA] ERRO ao enviar alerta '{alert_type}' para chat_id: {chat_id}, tarefa: '{task_text}'. Erro: {e}", exc_info=True)


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

    # Agendar Tarefa (Primeiro passo: pedir data/hora)
    if cmd == "menu_schedule":
        context.user_data["expecting"] = "schedule_datetime"
        await query.edit_message_text(
            "✏️ Em que dia e horário quer agendar? (ex: Amanhã 14h, 20/07 15h, 08:30 às 12:00h)"
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
            # Envia uma mensagem inicial para evitar editar uma mensagem sem botões
            await query.edit_message_text("📝 Suas Tarefas Agendadas:")
            
            for i, t in enumerate(tarefas):
                start_when_str = ""
                end_when_str = ""
                
                # Processa a data/hora de início
                if isinstance(t.get('start_when'), str):
                    try:
                        start_dt_obj = datetime.datetime.fromisoformat(t['start_when'])
                        start_when_str = start_dt_obj.strftime("%d/%m/%Y às %H:%M")
                    except ValueError:
                        start_when_str = t['start_when']
                else:
                    start_when_str = str(t.get('start_when'))
                
                # Processa a data/hora de fim (se existir)
                if isinstance(t.get('end_when'), str) and t.get('end_when'): # Verifica se não é None ou string vazia
                    try:
                        end_dt_obj = datetime.datetime.fromisoformat(t['end_when'])
                        end_when_str = f" até {end_dt_obj.strftime('%H:%M')}"
                    except ValueError:
                        end_when_str = f" até {t['end_when']}"
                
                status = "✅ Concluída" if t.get('done') else "⏳ Pendente"
                task_display_text = f"- {t['activity']} em {start_when_str}{end_when_str} [{status}]"
                
                # Adiciona botão para marcar como concluída (apenas se pendente)
                if not t.get('done'):
                    keyboard = [[InlineKeyboardButton("Marcar como Concluída", callback_data=f"mark_done_{i}")]]
                    markup = InlineKeyboardMarkup(keyboard)
                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text=task_display_text,
                        reply_markup=markup
                    )
                else:
                    # Se já concluída, apenas envia o texto sem botão
                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text=task_display_text
                    )
            
            if not tarefas: # Se a lista de tarefas estiver vazia após o loop
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="📝 Você ainda não tem tarefas agendadas."
                )
        else:
            await query.edit_message_text("📝 Você ainda não tem tarefas agendadas.")
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

    # 3.2) Capturando APENAS a data e hora para agendamento (início e/ou fim)
    if state == "schedule_datetime":
        logger.info(f"Tentando parsear data/hora: '{text}'")
        try:
            processed_text = text.replace('H', '').strip()
            logger.info(f"Texto pré-processado para dateparser: '{processed_text}'")
            
            sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
            now_aware = datetime.datetime.now(sao_paulo_tz)

            start_dt_naive = None
            end_dt_naive = None

            # Tenta encontrar um padrão de intervalo de tempo (ex: "10:00 às 12:00" ou "10:00-12:00")
            # Isso é mais robusto para extrair os horários antes de passar para o dateparser
            time_range_match = re.search(r'(\d{1,2}:\d{2})\s*(?:às|-)\s*(\d{1,2}:\d{2})', processed_text, re.IGNORECASE)
            
            if time_range_match:
                start_time_str = time_range_match.group(1)
                end_time_str = time_range_match.group(2)
                
                # Remove a parte do horário da string original para parsear a data base
                text_without_time_range = processed_text.replace(time_range_match.group(0), '').strip()

                # Tenta parsear a data (dia, mês, ano) da string restante
                base_date_naive = dateparser.parse(
                    text_without_time_range,
                    settings={
                        "DATE_ORDER": "DMY",
                        "RELATIVE_BASE": now_aware,
                        "TIMEZONE": "America/Sao_Paulo",
                        "RETURN_AS_TIMEZONE_AWARE": False,
                        "PREFER_DATES_FROM": "future" # Ajuda a pegar o dia correto se a data for ambígua
                    }
                )
                
                if not base_date_naive: # Se não encontrou uma data explícita, usa a data de hoje
                    base_date_naive = now_aware.replace(tzinfo=None) # Garante que é naive para combinar com o parse

                # Agora, combina a data base com os horários extraídos
                start_dt_naive = dateparser.parse(
                    f"{base_date_naive.strftime('%Y-%m-%d')} {start_time_str}",
                    settings={
                        "DATE_ORDER": "DMY",
                        "RELATIVE_BASE": now_aware,
                        "TIMEZONE": "America/Sao_Paulo",
                        "RETURN_AS_TIMEZONE_AWARE": False,
                    }
                )
                end_dt_naive = dateparser.parse(
                    f"{base_date_naive.strftime('%Y-%m-%d')} {end_time_str}",
                    settings={
                        "DATE_ORDER": "DMY",
                        "RELATIVE_BASE": now_aware,
                        "TIMEZONE": "America/Sao_Paulo",
                        "RETURN_AS_TIMEZONE_AWARE": False,
                    }
                )
                
                # Ajusta o dia do end_dt_naive se o horário de fim for menor que o de início (ex: 23h às 02h do dia seguinte)
                if start_dt_naive and end_dt_naive and end_dt_naive < start_dt_naive:
                    end_dt_naive += datetime.timedelta(days=1)
                
                logger.info(f"Parse com intervalo: Start={start_dt_naive}, End={end_dt_naive} para '{processed_text}'")

            # Se não encontrou um intervalo, tenta parsear como uma única data/hora
            if not start_dt_naive:
                dt_parsed = dateparser.parse(
                    processed_text,
                    settings={
                        "DATE_ORDER": "DMY",
                        "TIMEZONE": "America/Sao_Paulo",
                        "RETURN_AS_TIMEZONE_AWARE": False,
                        "RELATIVE_BASE": now_aware,
                    },
                )
                start_dt_naive = dt_parsed
                logger.info(f"Parse como única data/hora (sem prefer future): {start_dt_naive} para '{processed_text}'")

            if not start_dt_naive or not isinstance(start_dt_naive, datetime.datetime):
                logger.warning(f"Data/hora não entendida para '{processed_text}'. dt: {start_dt_naive}")
                await update.message.reply_text(
                    "❌ Não entendi o dia e horário. Tente algo como:\n"
                    "- Amanhã às 14h\n"
                    "- 20/07 15h\n"
                    "- 08:30 às 12:00h\n"
                    "- Terça 10h"
                )
                return

            # Garantir que a data/hora de início esteja no futuro
            # Usamos uma pequena margem (e.g., 5 segundos) para evitar que um agendamento "agora" seja considerado passado
            if start_dt_naive <= now_aware.replace(tzinfo=None) - datetime.timedelta(seconds=5):
                logger.info(f"Data/hora de início parseada ({start_dt_naive}) está no passado. Tentando avançar para o futuro.")
                dt_future = dateparser.parse(
                    processed_text,
                    settings={
                        "DATE_ORDER": "DMY",
                        "PREFER_DATES_FROM": "future",
                        "TIMEZONE": "America/Sao_Paulo",
                        "RETURN_AS_TIMEZONE_AWARE": False,
                        "RELATIVE_BASE": now_aware,
                    },
                )
                if dt_future and isinstance(dt_future, datetime.datetime) and dt_future > now_aware.replace(tzinfo=None) - datetime.timedelta(seconds=5):
                    start_dt_naive = dt_future
                    # Se o start_dt_naive mudou para o futuro, o end_dt_naive também precisa ser ajustado para o mesmo dia
                    if end_dt_naive and end_dt_naive.date() < start_dt_naive.date():
                         end_dt_naive = end_dt_naive.replace(year=start_dt_naive.year, month=start_dt_naive.month, day=start_dt_naive.day)
                         if end_dt_naive < start_dt_naive: # Se ainda estiver antes, avança um dia
                             end_dt_naive += datetime.timedelta(days=1)

                    logger.info(f"Data/hora de início avançada para o futuro: {start_dt_naive}")
                else:
                    await update.message.reply_text(
                        "❌ A data/hora agendada já passou. Por favor, agende para o futuro."
                    )
                    return
            
            # Final check para start_dt_naive
            if start_dt_naive <= now_aware.replace(tzinfo=None):
                await update.message.reply_text(
                    "❌ A data/hora de início agendada já passou. Por favor, agende para o futuro."
                )
                return

            # Salva as datas/horas (início e fim) no user_data
            context.user_data["temp_schedule"] = {
                "start_datetime": start_dt_naive.isoformat(),
                "end_datetime": end_dt_naive.isoformat() if end_dt_naive else None
            }
            context.user_data["expecting"] = "schedule_description"

            start_display = start_dt_naive.strftime('%d/%m/%Y às %H:%M')
            end_display = ""
            if end_dt_naive:
                end_display = f" até {end_dt_naive.strftime('%H:%M')}"
                # Calcula a duração
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
                "Agora, qual a **descrição** da tarefa?"
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
        
        # Tornar o datetime de início "aware"
        task_start_datetime_aware = sao_paulo_tz.localize(start_dt_naive)
        
        # Tornar o datetime de fim "aware" se existir
        task_end_datetime_aware = None
        if end_dt_naive:
            task_end_datetime_aware = sao_paulo_tz.localize(end_dt_naive)

        # Obter o horário atual (aware) para a verificação final
        now_aware_for_job_check = datetime.datetime.now(sao_paulo_tz)

        # Verificação final de que a data/hora de início está no futuro
        if task_start_datetime_aware <= now_aware_for_job_check:
            await update.message.reply_text(
                "❌ A data/hora de início agendada já passou. Por favor, agende para o futuro."
            )
            context.user_data.pop("expecting", None)
            context.user_data.pop("temp_schedule", None)
            return

        # --- AGENDANDO O ALERTA DE INÍCIO ---
        logger.info(f"⏳ [AGENDAMENTO] Preparando para agendar job de INÍCIO. Horário do Job (Aware SP): {task_start_datetime_aware} | Horário atual (Aware SP): {now_aware_for_job_check}")
        context.job_queue.run_once(
            send_task_alert,
            when=task_start_datetime_aware,
            chat_id=chat_id,
            data={'description': text, 'alert_type': 'start'}, # Passa um dicionário com descrição e tipo de alerta
            name=f"task_alert_start_{chat_id}_{task_start_datetime_aware.timestamp()}"
        )
        logger.info(f"✅ [AGENDAMENTO] Alerta de INÍCIO agendado para '{text}' em '{task_start_datetime_aware}'.")

        # --- AGENDANDO O ALERTA DE FIM (SE HOUVER) ---
        if task_end_datetime_aware:
            # Garante que o alerta de fim não seja antes do alerta de início
            if task_end_datetime_aware <= task_start_datetime_aware:
                task_end_datetime_aware += datetime.timedelta(days=1) # Ajusta para o dia seguinte se for o caso de 23h as 02h

            logger.info(f"⏳ [AGENDAMENTO] Preparando para agendar job de FIM. Horário do Job (Aware SP): {task_end_datetime_aware}")
            context.job_queue.run_once(
                send_task_alert,
                when=task_end_datetime_aware,
                chat_id=chat_id,
                data={'description': text, 'alert_type': 'end'}, # Passa um dicionário com descrição e tipo de alerta
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
            # Calcula a duração para exibir na mensagem de confirmação
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
            f"📅 Tarefa “{text}” agendada para "
            f"{start_display}{end_display}!\n"
            "Eu te avisarei no Telegram quando for a hora!"
        )
        context.user_data.pop("expecting", None)
        context.user_data.pop("temp_schedule", None)
        logger.info(f"Mensagem de sucesso de agendamento enviada para o usuário {chat_id}.")
        return

    # 3.4) Trata feedback de conclusão da tarefa
    if state == "task_completion_feedback":
        # Este estado é tratado por callback_query, mas se o usuário digitar algo, informa.
        await update.message.reply_text("Por favor, use os botões 'Sim, concluí!' ou 'Não, não concluí.' para responder sobre a tarefa.")
        return

    # 3.5) Capturando o motivo de não conclusão (se o usuário digitar)
    if state == "reason_for_not_completion":
        task_idx = context.user_data.get("task_idx_for_reason")
        if task_idx is not None and 0 <= task_idx < len(tarefas):
            tarefas[task_idx]["reason_not_completed"] = text
            save_data(db)
            await update.message.reply_text(f"📝 Motivo registrado para a tarefa '{tarefas[task_idx]['activity']}': '{text}'.")
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
        "👉 Use /rotina para abrir o menu e escolher uma opção."
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

        logger.info(f"Usuário {chat_id} tentou marcar tarefa {idx} como concluída.")
        if 0 <= idx < len(tarefas):
            tarefas[idx]["done"] = True
            tarefas[idx]["completion_status"] = "completed_manually" # Registra como concluída manualmente
            save_data(db)
            await query.edit_message_text(
                f"✅ Tarefa “{tarefas[idx]['activity']}” marcada como concluída!"
            )
            logger.info(f"Tarefa '{tarefas[idx]['activity']}' marcada como concluída para o usuário {chat_id}.")
        else:
            await query.edit_message_text("❌ Índice inválido para marcar como concluída.")
            logger.warning(f"Tentativa de marcar tarefa com índice inválido {idx} para o usuário {chat_id}.")
        return
    
    # Lógica para o feedback de conclusão (após o alerta de fim da tarefa)
    if cmd == "feedback_yes":
        task_text = context.user_data.get('current_task_for_feedback')
        if task_text:
            # Encontra a tarefa mais recente com essa descrição que não foi concluída
            found_task_idx = -1
            for i in reversed(range(len(tarefas))): # Procura da mais recente para a mais antiga
                if tarefas[i]['activity'] == task_text and not tarefas[i].get('done'):
                    found_task_idx = i
                    break
            
            if found_task_idx != -1:
                tarefas[found_task_idx]["done"] = True
                tarefas[found_task_idx]["completion_status"] = "completed_on_time"
                tarefas[found_task_idx]["reason_not_completed"] = None
                save_data(db)
                await query.edit_message_text(f"🎉 Ótimo! A tarefa '{task_text}' foi marcada como concluída. Parabéns!")
                logger.info(f"Tarefa '{task_text}' marcada como concluída via feedback 'Sim'.")
            else:
                await query.edit_message_text("🤔 Não encontrei uma tarefa pendente com essa descrição para marcar como concluída.")
                logger.warning(f"Não encontrei tarefa '{task_text}' para marcar como concluída via feedback 'Sim'.")
        else:
            await query.edit_message_text("🤔 Não sei a qual tarefa você se refere. Por favor, tente novamente.")
            logger.warning("current_task_for_feedback não encontrado para feedback 'Sim'.")
        
        context.user_data.pop("expecting", None)
        context.user_data.pop("current_task_for_feedback", None)
        return

    if cmd == "feedback_no":
        task_text = context.user_data.get('current_task_for_feedback')
        if task_text:
            # Encontra a tarefa mais recente com essa descrição que não foi concluída
            found_task_idx = -1
            for i in reversed(range(len(tarefas))):
                if tarefas[i]['activity'] == task_text and not tarefas[i].get('done'):
                    found_task_idx = i
                    break
            
            if found_task_idx != -1:
                tarefas[found_task_idx]["completion_status"] = "not_completed"
                save_data(db) # Salva o status de não concluída
                context.user_data["expecting"] = "reason_for_not_completion"
                context.user_data["task_idx_for_reason"] = found_task_idx # Guarda o índice da tarefa
                await query.edit_message_text(f"😔 Entendido. Por favor, digite o motivo pelo qual a tarefa '{task_text}' não foi concluída:")
                logger.info(f"Solicitando motivo de não conclusão para a tarefa '{task_text}'.")
            else:
                await query.edit_message_text("🤔 Não encontrei uma tarefa pendente com essa descrição para registrar o motivo.")
                logger.warning(f"Não encontrei tarefa '{task_text}' para solicitar motivo de não conclusão via feedback 'Não'.")
        else:
            await query.edit_message_text("🤔 Não sei a qual tarefa você se refere. Por favor, tente novamente.")
            logger.warning("current_task_for_feedback não encontrado para feedback 'Não'.")

        context.user_data.pop("current_task_for_feedback", None) # Limpa, pois agora espera o motivo
        return
