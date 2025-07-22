import datetime
from datetime import timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ConversationHandler,
    CallbackContext,
    CallbackQueryHandler,
    MessageHandler,
    filters
)
import re # Para expressões regulares no parsing de tempo
import pytz # Para lidar com fusos horários, importante para agendamentos precisos

# Definindo o fuso horário para consistência (ex: 'America/Sao_Paulo' para o Brasil)
# Ajuste para o seu fuso horário se for diferente.
TIMEZONE = pytz.timezone('America/Sao_Paulo')

# --- Estados da Conversa para a Agenda ---
ASK_DATE_TIME = 1
ASK_DESCRIPTION = 2
CONFIRM_TASK = 3 # Este estado agora é mais focado em ações pós-notificação
TASK_COMPLETION_FEEDBACK = 4 # Novo estado para feedback de conclusão

# Dicionário para armazenar as tarefas. Usaremos context.user_data['tasks'].
# Formato: {chat_id: [{id: 1, title: "Tarefa X", start_time: datetime_obj, end_time: datetime_obj, description: "...", job_ids: []}]}

class Agenda:
    def __init__(self, bot=None, chat_id=None):
        self.bot = bot
        self.chat_id = chat_id

    def get_agenda_conversation_handler(self):
        return ConversationHandler(
            entry_points=[
                CallbackQueryHandler(self.start_agenda_menu, pattern="^open_agenda_menu$")
            ],
            states={
                ASK_DATE_TIME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.ask_description),
                    CallbackQueryHandler(self.return_to_main_menu_from_agenda, pattern="^main_menu_return$")
                ],
                ASK_DESCRIPTION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.save_task_and_schedule),
                    CallbackQueryHandler(self.return_to_main_menu_from_agenda, pattern="^main_menu_return$")
                ],
                CONFIRM_TASK: [ # Este estado agora é para lidar com as respostas SIM/NÃO das notificações
                    CallbackQueryHandler(self.handle_task_completion, pattern=r"^task_completed_yes_(\d+)$"),
                    CallbackQueryHandler(self.handle_task_not_completed, pattern=r"^task_completed_no_(\d+)$"),
                    CallbackQueryHandler(self.return_to_main_menu_from_agenda, pattern="^main_menu_return$")
                ],
                TASK_COMPLETION_FEEDBACK: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_not_completed_reason),
                    CallbackQueryHandler(self.return_to_main_menu_from_agenda, pattern="^main_menu_return$")
                ]
            },
            fallbacks=[
                CallbackQueryHandler(self.return_to_main_menu_from_agenda, pattern="^main_menu_return$"),
                MessageHandler(filters.ALL, self.agenda_fallback) # Fallback genérico para a agenda
            ],
            map_to_parent={
                ConversationHandler.END: ConversationHandler.END # Retorna ao menu principal
            }
        )

    async def start_agenda_menu(self, update: Update, context: CallbackContext):
        query = update.callback_query
        await query.answer("Abrindo Agenda... 🗓️")
        await query.edit_message_text(
            "🗓️ Para criar uma nova tarefa, digite o **dia e o horário** no formato que preferir. Exemplos:\n"
            "➡️ `Hoje às 10h`\n"
            "➡️ `Amanhã 14:30`\n"
            "➡️ `Terça 9h as 11h`\n"
            "➡️ `25/12 às 20:00`\n"
            "➡️ `Daqui a 2 horas`\n"
            "➡️ `Em 30 minutos`\n\n"
            "Ou digite 'voltar' para o menu principal. ↩️",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Voltar", callback_data="main_menu_return")]])
        )
        return ASK_DATE_TIME

    async def agenda_fallback(self, update: Update, context: CallbackContext):
        # A mensagem do fallback global no main.py já é mais genérica.
        # Aqui, podemos ser mais específicos para a agenda.
        if update.message:
            await update.message.reply_text(
                "❌ Ops! Não entendi o que você digitou. Por favor, tente novamente com o dia e horário da tarefa (ex: 'Hoje às 10h') ou 'voltar'.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Voltar", callback_data="main_menu_return")]])
            )
        elif update.callback_query:
            await update.callback_query.answer("🚫 Ação inválida para a Agenda.")
            await update.callback_query.edit_message_text(
                "🚫 Ação inválida. Por favor, digite o dia e o horário da tarefa ou 'voltar'.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Voltar", callback_data="main_menu_return")]])
            )
        return ASK_DATE_TIME

    async def return_to_main_menu_from_agenda(self, update: Update, context: CallbackContext):
        query = update.callback_query
        await query.answer()
        # Limpa dados temporários da conversa da agenda
        if 'current_task_data' in context.user_data:
            del context.user_data['current_task_data']
        # Se houver um job de feedback pendente, cancela a transição de estado para evitar loop
        if 'current_task_id_for_feedback' in context.user_data:
            del context.user_data['current_task_id_for_feedback']
        return ConversationHandler.END # Sinaliza para o ConversationHandler pai retornar ao menu principal

    def _parse_datetime(self, text: str) -> tuple[datetime.datetime | None, datetime.datetime | None, str]:
        """
        Tenta extrair data, hora de início, hora de fim e uma string de duração do texto do usuário.
        Retorna (start_datetime, end_datetime, duration_str).
        """
        now = datetime.datetime.now(TIMEZONE) # Usar o fuso horário definido
        start_dt = None
        end_dt = None
        duration_str = ""
        
        current_date_obj = now.date() # Data base para inferência

        # 1. Parsing de Dia (hoje, amanhã, dias da semana, DD/MM, DD/MM/AAAA)
        date_match = None
        day_of_week_map = {
            "segunda": 0, "terça": 1, "quarta": 2, "quinta": 3, "sexta": 4, "sábado": 5, "domingo": 6,
            "seg": 0, "ter": 1, "qua": 2, "qui": 3, "sex": 4, "sab": 5, "dom": 6
        }

        # Hoje
        if re.search(r'\bhoje\b', text, re.IGNORECASE):
            date_match = current_date_obj
        # Amanhã
        elif re.search(r'\bamanhã\b', text, re.IGNORECASE):
            date_match = (current_date_obj + timedelta(days=1))
        # Dias da semana
        else:
            for day_name, day_num in day_of_week_map.items():
                if re.search(r'\b' + day_name + r'\b', text, re.IGNORECASE):
                    current_weekday = current_date_obj.weekday() # Monday is 0 and Sunday is 6
                    days_ahead = day_num - current_weekday
                    if days_ahead <= 0: # Se o dia da semana já passou nesta semana ou é hoje, assume a próxima semana
                        days_ahead += 7
                    date_match = (current_date_obj + timedelta(days=days_ahead))
                    break
        # DD/MM ou DD/MM/AAAA
        if not date_match:
            date_pattern = re.search(r'(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?', text)
            if date_pattern:
                day = int(date_pattern.group(1))
                month = int(date_pattern.group(2))
                year = int(date_pattern.group(3)) if date_pattern.group(3) else now.year
                if len(str(year)) == 2: # Ex: 23 para 2023
                    year += 2000 if year < 50 else 1900 # Lógica simples para anos 2 dígitos
                try:
                    parsed_date = datetime.date(year, month, day)
                    # Se a data já passou neste ano, assume o próximo ano (se não for explícito)
                    if date_pattern.group(3) is None and parsed_date < current_date_obj:
                        parsed_date = datetime.date(year + 1, month, day)
                    date_match = parsed_date
                except ValueError:
                    date_match = None # Data inválida
        
        # Se nenhuma data específica foi encontrada, assume hoje
        if not date_match:
            date_match = current_date_obj

        # 2. Parsing de Hora (HHh, HH:MM, HHh as HHh, HH:MM as HH:MM, daqui a X tempo, em X tempo)
        time_found = False

        # Daqui a X tempo (minutos ou horas) / Em X tempo
        relative_time_match = re.search(r'(?:daqui a|em)\s*(\d+)\s*(minutos?|horas?)', text, re.IGNORECASE)
        if relative_time_match:
            value = int(relative_time_match.group(1))
            unit = relative_time_match.group(2).lower()
            if 'minuto' in unit:
                start_dt = now + timedelta(minutes=value)
            elif 'hora' in unit:
                start_dt = now + timedelta(hours=value)
            start_dt = start_dt.replace(second=0, microsecond=0) # Zera segundos e microssegundos
            end_dt = None # Sem end_dt para tempo relativo simples
            time_found = True

        # Horários fixos ou intervalos (HHh, HH:MM, HHh as HHh, HH:MM as HH:MM)
        if not time_found:
            time_ranges = re.findall(r'(\d{1,2}(?:h|:\d{2})?)\s*(?:às|as|-)\s*(\d{1,2}(?:h|:\d{2})?)', text, re.IGNORECASE)
            single_times = re.findall(r'\b(\d{1,2}(?:h|:\d{2})?)\b', text, re.IGNORECASE) # Captura "10h", "14:30", "9"

            if time_ranges:
                start_time_str = time_ranges[0][0].replace('h', ':00')
                end_time_str = time_ranges[0][1].replace('h', ':00')

                try:
                    start_hour, start_minute = map(int, (start_time_str + ":00").split(':')[:2])
                    end_hour, end_minute = map(int, (end_time_str + ":00").split(':')[:2])

                    start_dt_candidate = TIMEZONE.localize(datetime.datetime.combine(date_match, datetime.time(start_hour, start_minute)))
                    end_dt_candidate = TIMEZONE.localize(datetime.datetime.combine(date_match, datetime.time(end_hour, end_minute)))

                    # Se o intervalo de tempo já passou para a data atual, tenta para o dia seguinte
                    if start_dt_candidate < now and date_match == current_date_obj:
                        start_dt_candidate += timedelta(days=1)
                        end_dt_candidate += timedelta(days=1)

                    # Se a hora final for anterior à inicial no mesmo dia, assume que termina no dia seguinte
                    if end_dt_candidate < start_dt_candidate:
                        end_dt_candidate += timedelta(days=1)
                    
                    start_dt = start_dt_candidate
                    end_dt = end_dt_candidate
                    time_found = True

                    duration = end_dt - start_dt
                    total_minutes = int(duration.total_seconds() // 60)
                    hours = total_minutes // 60
                    minutes = total_minutes % 60
                    if hours > 0 and minutes > 0:
                        duration_str = f"{hours}h e {minutes}min"
                    elif hours > 0:
                        duration_str = f"{hours}h"
                    elif minutes > 0:
                        duration_str = f"{minutes}min"


                except ValueError:
                    start_dt = None
                    end_dt = None
            elif single_times:
                time_str_raw = single_times[0]
                # Padroniza para HH:MM
                if 'h' in time_str_raw:
                    time_str = time_str_raw.replace('h', ':00')
                elif ':' not in time_str_raw:
                    time_str = time_str_raw + ':00' # Se for só "9", vira "9:00"
                else:
                    time_str = time_str_raw
                
                try:
                    hour, minute = map(int, (time_str + ":00").split(':')[:2]) # Garante que tem pelo menos HH:MM
                    start_dt_candidate = TIMEZONE.localize(datetime.datetime.combine(date_match, datetime.time(hour, minute)))

                    # Se a hora já passou hoje, tenta para o dia seguinte, a menos que a data já seja no futuro
                    if start_dt_candidate < now and date_match == current_date_obj:
                        start_dt_candidate += timedelta(days=1)
                    
                    start_dt = start_dt_candidate
                    time_found = True

                except ValueError:
                    start_dt = None
        
        # Validação final: se a tarefa for no passado, invalida
        if start_dt and start_dt < now:
            return None, None, "" # Retorna nulo se for no passado

        # Se nenhuma hora foi especificada, assume 00:00 do dia inferido
        if not start_dt and date_match:
            start_dt = TIMEZONE.localize(datetime.datetime.combine(date_match, datetime.time(0, 0)))

        return start_dt, end_dt, duration_str

    async def ask_description(self, update: Update, context: CallbackContext):
        user_text = update.message.text.strip()
        if user_text.lower() == 'voltar':
            return await self.return_to_main_menu_from_agenda(update, context)

        start_dt, end_dt, duration_str = self._parse_datetime(user_text)

        if not start_dt:
            await update.message.reply_text(
                "🤔 Não consegui entender a data/hora ou ela está no passado. Por favor, tente novamente com um formato válido (ex: 'Hoje às 10h', 'Amanhã às 14:30', 'Terça às 9h às 11h') ou 'voltar'.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Voltar", callback_data="main_menu_return")]])
            )
            return ASK_DATE_TIME

        context.user_data['current_task_data'] = {
            'start_datetime': start_dt,
            'end_datetime': end_dt,
            'duration_str': duration_str,
            'original_input': user_text # Para referência
        }

        time_info = ""
        if end_dt:
            time_info = f"das *{start_dt.strftime('%H:%M')}* às *{end_dt.strftime('%H:%M')}*"
        else:
            time_info = f"às *{start_dt.strftime('%H:%M')}*"

        await update.message.reply_text(
            f"📅 Para *{start_dt.strftime('%d/%m/%Y')}* {time_info}, qual a *descrição* da tarefa? ✨",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Voltar", callback_data="main_menu_return")]])
        )
        return ASK_DESCRIPTION

    async def save_task_and_schedule(self, update: Update, context: CallbackContext):
        description = update.message.text.strip()
        if description.lower() == 'voltar':
            return await self.return_to_main_menu_from_agenda(update, context)

        task_data = context.user_data.get('current_task_data')
        if not task_data:
            await update.message.reply_text("🚨 Ocorreu um erro. Por favor, comece novamente a agendar a tarefa.",
                                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Voltar", callback_data="main_menu_return")]])
            )
            return ASK_DATE_TIME

        start_dt = task_data['start_datetime']
        end_dt = task_data['end_datetime']
        duration_str = task_data['duration_str']

        # Inicializa a lista de tarefas para o usuário se não existir
        if 'tasks' not in context.user_data:
            context.user_data['tasks'] = []

        # Gera um ID simples para a tarefa
        task_id = len(context.user_data['tasks']) + 1

        new_task = {
            'id': task_id,
            'title': description, # A descrição será o título
            'start_datetime': start_dt,
            'end_datetime': end_dt,
            'description': description, # Mantém a descrição completa
            'duration_str': duration_str,
            'is_completed': False,
            'job_ids': [] # Para armazenar os IDs dos jobs agendados
        }
        context.user_data['tasks'].append(new_task)

        confirmation_message = (
            f"✅ Tarefa *'{description}'* agendada com sucesso para "
            f"*{start_dt.strftime('%d/%m/%Y')}* às *{start_dt.strftime('%H:%M')}*."
        )
        if duration_str:
            confirmation_message += f" Duração: *{duration_str}*."
        
        await update.message.reply_text(confirmation_message, parse_mode="Markdown")

        # --- Agendamento das Notificações ---
        # Garante que o bot e chat_id estão atualizados para os jobs
        self.bot = context.bot 
        self.chat_id = update.effective_chat.id 

        # Notificação no horário exato
        job_exact_time = context.job_queue.run_once(
            self._send_task_notification,
            start_dt,
            chat_id=self.chat_id,
            data={'task_id': task_id, 'type': 'start_time'},
            name=f"task_{task_id}_start"
        )
        new_task['job_ids'].append(job_exact_time.name)

        # Notificação 30 minutos antes (se a tarefa não for começar em menos de 30min)
        if start_dt - timedelta(minutes=30) > now:
            job_30min_before = context.job_queue.run_once(
                self._send_task_notification,
                start_dt - timedelta(minutes=30),
                chat_id=self.chat_id,
                data={'task_id': task_id, 'type': '30_min_before'},
                name=f"task_{task_id}_30min_before"
            )
            new_task['job_ids'].append(job_30min_before.name)

        # Notificação 1 hora antes (se não for muito próximo dos 30 minutos antes e se a tarefa não for começar em menos de 1h)
        if start_dt - timedelta(hours=1) > now and \
           (start_dt - timedelta(hours=1)).minute != (start_dt - timedelta(minutes=30)).minute: # Evita duplicidade se 30 min e 1h forem muito próximos
            job_1hr_before = context.job_queue.run_once(
                self._send_task_notification,
                start_dt - timedelta(hours=1),
                chat_id=self.chat_id,
                data={'task_id': task_id, 'type': '1_hr_before'},
                name=f"task_{task_id}_1hr_before"
            )
            new_task['job_ids'].append(job_1hr_before.name)

        # Notificação no horário final (se houver duração e o fim ainda não tiver passado)
        if end_dt and end_dt > now:
            job_end_time = context.job_queue.run_once(
                self._send_task_notification,
                end_dt,
                chat_id=self.chat_id,
                data={'task_id': task_id, 'type': 'end_time'},
                name=f"task_{task_id}_end"
            )
            new_task['job_ids'].append(job_end_time.name)

        del context.user_data['current_task_data'] # Limpa os dados temporários
        
        # Após agendar, oferece opções adicionais
        await self.show_agenda_options(update, context, send_new_message=True) 
        # Não retorna ConversationHandler.END aqui, pois show_agenda_options já define o estado
        return ASK_DATE_TIME # Permite adicionar outra tarefa ou voltar

    async def _send_task_notification(self, context: CallbackContext):
        job_data = context.job.data
        task_id = job_data['task_id']
        notification_type = job_data['type']
        chat_id = context.job.chat_id

        # Para acessar as tarefas, é necessário usar context.job.job_queue.dispatcher.user_data[chat_id]
        # ou, se o job foi agendado diretamente pelo `context.bot_data` como no exemplo anterior,
        # é preciso garantir que o `tasks` esteja corretamente mapeado para o `chat_id` lá.
        # A forma mais robusta é usar `context.application.user_data[chat_id]['tasks']` se for gravado lá.
        # No seu código, está sendo gravado em `context.user_data` (que para jobs é `context.bot_data[chat_id]`).
        user_data_for_chat = context.application.user_data.get(chat_id, {})
        tasks = user_data_for_chat.get('tasks', [])
        
        task = next((t for t in tasks if t['id'] == task_id), None)

        if not task or task['is_completed']:
            # Remove o job se a tarefa foi concluída manualmente ou não existe mais
            context.job.schedule_removal()
            return 

        message = ""
        keyboard = None
        current_time = datetime.datetime.now(TIMEZONE)

        if notification_type == 'start_time':
            message = f"🔔 *Lembrete*: Sua tarefa '{task['title']}' está começando *AGORA*! 🚀"
            # Se não houver end_dt, pergunta se concluiu logo após o início
            if not task['end_datetime'] or task['end_datetime'] <= current_time:
                message += "\n\nVocê a concluiu?"
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Sim, Concluí!", callback_data=f"task_completed_yes_{task_id}")],
                    [InlineKeyboardButton("❌ Não, não Concluí.", callback_data=f"task_completed_no_{task_id}")]
                ])
        elif notification_type == '30_min_before':
            message = f"⏰ *Atenção*! Sua tarefa '{task['title']}' começa em *30 minutos*."
        elif notification_type == '1_hr_before':
            message = f"⏳ *Aviso*: Sua tarefa '{task['title']}' começa em *1 hora*."
        elif notification_type == 'end_time':
            message = f"✅ Sua tarefa *'{task['title']}'* terminou. Você a concluiu? 🤔"
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Sim, Concluí!", callback_data=f"task_completed_yes_{task_id}")],
                [InlineKeyboardButton("❌ Não, não Concluí.", callback_data=f"task_completed_no_{task_id}")]
            ])
        
        if message:
            # Envia a mensagem com ou sem teclado
            await context.bot.send_message(chat_id=chat_id, text=message, reply_markup=keyboard, parse_mode="Markdown")
            
            # Para o fluxo de feedback de tarefas não concluídas, armazena o task_id
            if keyboard and (notification_type == 'start_time' or notification_type == 'end_time'):
                user_data_for_chat['current_task_id_for_feedback'] = task_id
                # Este job handler não pode mudar o estado da conversa diretamente,
                # mas o CallbackQueryHandler do botão SIM/NÃO irá fazê-lo.
                # A responsabilidade de transição de estado é do handler que recebe a interação.

    async def handle_task_completion(self, update: Update, context: CallbackContext):
        query = update.callback_query
        task_id = int(query.data.split('_')[-1])

        tasks = context.user_data.get('tasks', [])
        task = next((t for t in tasks if t['id'] == task_id), None)

        if task:
            task['is_completed'] = True
            await query.edit_message_text(f"🎉 Ótimo! Tarefa *'{task['title']}'* marcada como concluída! Parabéns! 🥳", parse_mode="Markdown")
            # Cancela os jobs restantes para esta tarefa
            for job_name in task['job_ids']:
                current_jobs = context.job_queue.get_jobs_by_name(job_name)
                for job in current_jobs:
                    job.schedule_removal()
            task['job_ids'] = [] # Limpa os IDs dos jobs
            
            # Limpa o ID da tarefa de feedback, se estiver definido
            if 'current_task_id_for_feedback' in context.user_data and context.user_data['current_task_id_for_feedback'] == task_id:
                del context.user_data['current_task_id_for_feedback']
        else:
            await query.edit_message_text("❌ Desculpe, não encontrei esta tarefa para concluir.")

        await self.show_agenda_options(update, context)
        return ConversationHandler.END # Retorna ao menu principal

    async def handle_task_not_completed(self, update: Update, context: CallbackContext):
        query = update.callback_query
        task_id = int(query.data.split('_')[-1])

        tasks = context.user_data.get('tasks', [])
        task = next((t for t in tasks if t['id'] == task_id), None)

        if task:
            context.user_data['current_task_id_for_feedback'] = task_id # Armazena para o próximo estado
            await query.edit_message_text(
                f"😔 Entendido. Por que você *não* conseguiu concluir a tarefa *'{task['title']}'*? (Digite o motivo ou 'ignorar')",
                parse_mode="Markdown"
            )
            return TASK_COMPLETION_FEEDBACK
        else:
            await query.edit_message_text("❌ Desculpe, não encontrei esta tarefa.")
            await self.show_agenda_options(update, context)
            return ConversationHandler.END

    async def process_not_completed_reason(self, update: Update, context: CallbackContext):
        reason = update.message.text.strip()
        task_id = context.user_data.get('current_task_id_for_feedback')

        tasks = context.user_data.get('tasks', [])
        task = next((t for t in tasks if t['id'] == task_id), None)

        if task:
            if reason.lower() != 'ignorar':
                task['not_completed_reason'] = reason
                await update.message.reply_text(f"📝 Motivo para *'{task['title']}'* registrado: _{reason}_. Foco na próxima! 💪", parse_mode="Markdown")
            else:
                await update.message.reply_text(f"👍 Motivo para *'{task['title']}'* ignorado. Vamos em frente! ✨", parse_mode="Markdown")

            # Cancela os jobs restantes para esta tarefa
            for job_name in task['job_ids']:
                current_jobs = context.job_queue.get_jobs_by_name(job_name)
                for job in current_jobs:
                    job.schedule_removal()
            task['job_ids'] = [] # Limpa os IDs dos jobs
        else:
            await update.message.reply_text("🚨 Ocorreu um erro ao processar o motivo. Tente novamente.")

        del context.user_data['current_task_id_for_feedback'] # Limpa o ID temporário
        await self.show_agenda_options(update, context)
        return ConversationHandler.END

    async def show_agenda_options(self, update: Update, context: CallbackContext, send_new_message: bool = False):
        tasks = context.user_data.get('tasks', [])
        
        message_text = "🗓️ *Suas próximas tarefas:*\n\n"
        has_upcoming_tasks = False
        
        # Filtra e ordena as tarefas que não foram concluídas e ainda estão no futuro ou no presente
        upcoming_tasks = sorted([
            t for t in tasks 
            if not t['is_completed'] and t['start_datetime'] >= datetime.datetime.now(TIMEZONE)
        ], key=lambda x: x['start_datetime'])

        if upcoming_tasks:
            has_upcoming_tasks = True
            for task in upcoming_tasks[:5]: # Mostra as próximas 5 tarefas
                time_info = task['start_datetime'].strftime('%H:%M')
                if task['end_datetime']:
                    time_info += f" - {task['end_datetime'].strftime('%H:%M')}"
                
                message_text += (
                    f"• *{task['title']}* em {task['start_datetime'].strftime('%d/%m')} às {time_info} "
                    f"({task['duration_str'] if task['duration_str'] else 'sem duração'})\n"
                )
        else:
            message_text += "Você não tem tarefas futuras agendadas. Que tal adicionar uma? ✨"
        
        keyboard = [
            [InlineKeyboardButton("➕ Adicionar Nova Tarefa", callback_data="add_new_task")],
            [InlineKeyboardButton("📋 Ver Todas as Tarefas", callback_data="list_all_tasks")],
            [InlineKeyboardButton("↩️ Voltar ao Menu Principal", callback_data="main_menu_return")]
        ]

        if send_new_message:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=message_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        else:
            # Se a atualização veio de um callback_query, edita a mensagem existente
            query = update.callback_query
            if query:
                await query.edit_message_text(
                    text=message_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
            else: # Fallback se não for callback nem send_new_message
                 await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=message_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
        
        # Adiciona um handler temporário para 'add_new_task' e 'list_all_tasks'
        # que retornarão ao estado inicial da agenda ou exibirão a lista
        context.dispatcher.add_handler(
            CallbackQueryHandler(self.start_agenda_menu, pattern="^add_new_task$"),
            group=0 # Garante que este handler seja verificado primeiro para este padrão
        )
        context.dispatcher.add_handler(
            CallbackQueryHandler(self.list_all_tasks, pattern="^list_all_tasks$"),
            group=0 # Garante que este handler seja verificado primeiro para este padrão
        )

        return ASK_DATE_TIME # Permite ao usuário continuar adicionando ou navegando


    async def list_all_tasks(self, update: Update, context: CallbackContext):
        query = update.callback_query
        tasks = context.user_data.get('tasks', [])
        
        if not tasks:
            message = "Você não tem nenhuma tarefa agendada. Que tal adicionar uma? ✨"
        else:
            message = "📋 *Suas Tarefas Agendadas:*\n\n"
            
            # Separa e ordena tarefas futuras/pendentes e concluídas
            upcoming_pending = sorted([t for t in tasks if not t['is_completed'] and t['start_datetime'] >= datetime.datetime.now(TIMEZONE)], key=lambda x: x['start_datetime'])
            completed_tasks = sorted([t for t in tasks if t['is_completed']], key=lambda x: x['start_datetime'], reverse=True)
            past_uncompleted = sorted([t for t in tasks if not t['is_completed'] and t['start_datetime'] < datetime.datetime.now(TIMEZONE)], key=lambda x: x['start_datetime'], reverse=True)

            if upcoming_pending:
                message += "*➡️ Próximas/Pendentes:*\n"
                for task in upcoming_pending:
                    time_info = task['start_datetime'].strftime('%H:%M')
                    if task['end_datetime']:
                        time_info += f" - {task['end_datetime'].strftime('%H:%M')}"
                    message += f"• `{task['title']}` em _{task['start_datetime'].strftime('%d/%m')}_ às _{time_info}_\n"

                message += "\n"

            if past_uncompleted:
                message += "*⏳ Não Concluídas no Prazo:*\n"
                for task in past_uncompleted:
                    time_info = task['start_datetime'].strftime('%H:%M')
                    if task['end_datetime']:
                        time_info += f" - {task['end_datetime'].strftime('%H:%M')}"
                    reason_info = f" (Motivo: {task.get('not_completed_reason', 'Não informado')})" if task.get('not_completed_reason') else ""
                    message += f"• `{task['title']}` em _{task['start_datetime'].strftime('%d/%m')}_ às _{time_info}_ {reason_info}\n"
                message += "\n"

            if completed_tasks:
                message += "*✅ Concluídas:*\n"
                for task in completed_tasks:
                    time_info = task['start_datetime'].strftime('%H:%M')
                    if task['end_datetime']:
                        time_info += f" - {task['end_datetime'].strftime('%H:%M')}"
                    message += f"• `{task['title']}` em _{task['start_datetime'].strftime('%d/%m')}_ às _{time_info}_\n"
                message += "\n"

        keyboard = [
            [InlineKeyboardButton("➕ Adicionar Nova Tarefa", callback_data="add_new_task")],
            [InlineKeyboardButton("↩️ Voltar ao Menu Principal", callback_data="main_menu_return")]
        ]
        
        await query.edit_message_text(
            text=message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return ASK_DATE_TIME # Mantém no estado da agenda para nova interação ou volta

