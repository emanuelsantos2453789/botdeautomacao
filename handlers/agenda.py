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
import re
import pytz

# Definindo o fuso horário para consistência (ex: 'America/Sao_Paulo' para o Brasil)
TIMEZONE = pytz.timezone('America/Sao_Paulo')

# --- Estados da Conversa para a Agenda ---
AGENDA_MAIN_MENU = 1 # Novo estado para o menu principal da agenda
ASK_DATE_TIME = 2
ASK_DESCRIPTION = 3
CONFIRM_TASK = 4 # Para ações pós-notificação
TASK_COMPLETION_FEEDBACK = 5
MANAGE_TASKS_MENU = 6 # Novo estado para o menu de gerenciamento de tarefas
DELETE_TASK_SELECTION = 7 # Novo estado para seleção de tarefas a apagar
CONFIRM_DELETE_TASK = 8 # Novo estado para confirmar exclusão

class Agenda:
    def __init__(self, bot=None, chat_id=None):
        self.bot = bot
        self.chat_id = chat_id

    def get_agenda_conversation_handler(self):
        return ConversationHandler(
            entry_points=[
                CallbackQueryHandler(self.start_agenda_main_menu, pattern="^open_agenda_menu$")
            ],
            states={
                AGENDA_MAIN_MENU: [
                    CallbackQueryHandler(self.start_add_task_flow, pattern="^add_new_task$"),
                    CallbackQueryHandler(self.open_manage_tasks_menu, pattern="^manage_tasks$"),
                    CallbackQueryHandler(self.return_to_main_menu_from_agenda, pattern="^main_menu_return$")
                ],
                ASK_DATE_TIME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.ask_description),
                    CallbackQueryHandler(self.start_agenda_main_menu, pattern="^agenda_main_menu_return$"), # Voltar para o menu principal da agenda
                    CallbackQueryHandler(self.return_to_main_menu_from_agenda, pattern="^main_menu_return$")
                ],
                ASK_DESCRIPTION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.save_task_and_schedule),
                    CallbackQueryHandler(self.start_add_task_flow, pattern="^agenda_main_menu_return$"), # Voltar para o início do fluxo de adicionar
                    CallbackQueryHandler(self.return_to_main_menu_from_agenda, pattern="^main_menu_return$")
                ],
                CONFIRM_TASK: [ # Respostas dos botões de notificação
                    CallbackQueryHandler(self.handle_task_completion, pattern=r"^task_completed_yes_(\d+)$"),
                    CallbackQueryHandler(self.handle_task_not_completed, pattern=r"^task_completed_no_(\d+)$"),
                    CallbackQueryHandler(self.return_to_main_menu_from_agenda, pattern="^main_menu_return$") # Caso notificação seja antiga e clique
                ],
                TASK_COMPLETION_FEEDBACK: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_not_completed_reason),
                    CallbackQueryHandler(self.start_agenda_main_menu, pattern="^agenda_main_menu_return$"), # Retorna ao menu da agenda
                    CallbackQueryHandler(self.return_to_main_menu_from_agenda, pattern="^main_menu_return$")
                ],
                MANAGE_TASKS_MENU: [
                    CallbackQueryHandler(self.list_upcoming_tasks, pattern="^list_upcoming_tasks$"),
                    CallbackQueryHandler(self.list_completed_tasks, pattern="^list_completed_tasks$"),
                    CallbackQueryHandler(self.initiate_delete_task, pattern="^initiate_delete_task$"),
                    CallbackQueryHandler(self.start_agenda_main_menu, pattern="^agenda_main_menu_return$"), # Voltar para o menu principal da agenda
                    CallbackQueryHandler(self.return_to_main_menu_from_agenda, pattern="^main_menu_return$")
                ],
                DELETE_TASK_SELECTION: [
                    CallbackQueryHandler(self.confirm_delete_task, pattern=r"^delete_task_id_(\d+)$"),
                    CallbackQueryHandler(self.open_manage_tasks_menu, pattern="^manage_tasks_return$"), # Voltar ao menu de gerenciar tarefas
                    CallbackQueryHandler(self.start_agenda_main_menu, pattern="^agenda_main_menu_return$"),
                    CallbackQueryHandler(self.return_to_main_menu_from_agenda, pattern="^main_menu_return$")
                ],
                CONFIRM_DELETE_TASK: [
                    CallbackQueryHandler(self.execute_delete_task, pattern=r"^confirm_delete_yes_(\d+)$"),
                    CallbackQueryHandler(self.open_manage_tasks_menu, pattern=r"^confirm_delete_no_(\d+)$"),
                    CallbackQueryHandler(self.start_agenda_main_menu, pattern="^agenda_main_menu_return$"),
                    CallbackQueryHandler(self.return_to_main_menu_from_agenda, pattern="^main_menu_return$")
                ]
            },
            fallbacks=[
                CallbackQueryHandler(self.return_to_main_menu_from_agenda, pattern="^main_menu_return$"),
                MessageHandler(filters.ALL, self.agenda_fallback)
            ],
            map_to_parent={
                ConversationHandler.END: ConversationHandler.END
            }
        )

    async def start_agenda_main_menu(self, update: Update, context: CallbackContext):
        # Garante que é um callback_query ou um comando
        if update.callback_query:
            query = update.callback_query
            await query.answer("Abrindo Agenda... 🗓️")
            # Se a mensagem atual não for do menu principal, edita
            if query.message.text and "Bem-vindo à sua Agenda Pessoal" not in query.message.text:
                await query.edit_message_text(
                    "🎉 *Bem-vindo à sua Agenda Pessoal!* Escolha uma opção: ✨",
                    parse_mode="Markdown",
                    reply_markup=self._get_agenda_main_menu_keyboard()
                )
            else: # Se já estiver no menu principal, apenas atualiza o teclado (evita erro de edição)
                await query.edit_message_reply_markup(
                    reply_markup=self._get_agenda_main_menu_keyboard()
                )
        else: # Se for chamado internamente (ex: após salvar tarefa) e não tiver query
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="🎉 *Bem-vindo à sua Agenda Pessoal!* Escolha uma opção: ✨",
                parse_mode="Markdown",
                reply_markup=self._get_agenda_main_menu_keyboard()
            )
        return AGENDA_MAIN_MENU

    def _get_agenda_main_menu_keyboard(self):
        keyboard = [
            [InlineKeyboardButton("➕ Adicionar Nova Tarefa", callback_data="add_new_task")],
            [InlineKeyboardButton("📋 Gerenciar Tarefas", callback_data="manage_tasks")],
            [InlineKeyboardButton("↩️ Voltar ao Menu Principal", callback_data="main_menu_return")]
        ]
        return InlineKeyboardMarkup(keyboard)

    async def start_add_task_flow(self, update: Update, context: CallbackContext):
        query = update.callback_query
        await query.answer("Iniciando adição de tarefa... ✍️")
        await query.edit_message_text(
            "🗓️ Para criar uma nova tarefa, digite o **dia e o horário** no formato que preferir. Exemplos:\n"
            "➡️ `Hoje às 10h`\n"
            "➡️ `Amanhã 14:30`\n"
            "➡️ `Terça 9h as 11h`\n"
            "➡️ `25/12 às 20:00`\n"
            "➡️ `Daqui a 2 horas`\n"
            "➡️ `Em 30 minutos`\n\n"
            "Ou 'voltar' para o menu principal da Agenda. ↩️",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Voltar à Agenda", callback_data="agenda_main_menu_return")]])
        )
        return ASK_DATE_TIME

    async def open_manage_tasks_menu(self, update: Update, context: CallbackContext):
        query = update.callback_query
        await query.answer("Abrindo Gerenciador de Tarefas... 🗂️")
        
        keyboard = [
            [InlineKeyboardButton("🗓️ Ver Tarefas Agendadas", callback_data="list_upcoming_tasks")],
            [InlineKeyboardButton("✅ Ver Tarefas Concluídas", callback_data="list_completed_tasks")],
            [InlineKeyboardButton("🗑️ Apagar Tarefas", callback_data="initiate_delete_task")],
            [InlineKeyboardButton("↩️ Voltar ao Menu da Agenda", callback_data="agenda_main_menu_return")],
            [InlineKeyboardButton("⬅️ Voltar ao Menu Principal", callback_data="main_menu_return")]
        ]
        await query.edit_message_text(
            "🗂️ *Gerenciar Tarefas:* Escolha uma opção:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return MANAGE_TASKS_MENU

    async def agenda_fallback(self, update: Update, context: CallbackContext):
        if update.message:
            await update.message.reply_text(
                "❌ Ops! Não entendi o que você digitou. Por favor, tente novamente com um formato válido ou use os botões. 🤔",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Voltar à Agenda", callback_data="agenda_main_menu_return")]])
            )
        elif update.callback_query:
            await update.callback_query.answer("🚫 Ação inválida para a Agenda.")
            await update.callback_query.edit_message_text(
                "🚫 Ação inválida. Por favor, use os botões. 🧐",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Voltar à Agenda", callback_data="agenda_main_menu_return")]])
            )
        # Tenta retornar ao menu principal da agenda, se possível
        return AGENDA_MAIN_MENU

    async def return_to_main_menu_from_agenda(self, update: Update, context: CallbackContext):
        query = update.callback_query
        await query.answer()
        if 'current_task_data' in context.user_data:
            del context.user_data['current_task_data']
        if 'current_task_id_for_feedback' in context.user_data:
            del context.user_data['current_task_id_for_feedback']
        
        return ConversationHandler.END

    def _parse_datetime(self, text: str) -> tuple[datetime.datetime | None, datetime.datetime | None, str]:
        """
        Tenta extrair data, hora de início, hora de fim e uma string de duração do texto do usuário.
        Retorna (start_datetime, end_datetime, duration_str).
        """
        now = datetime.datetime.now(TIMEZONE)
        start_dt = None
        end_dt = None
        duration_str = ""
        
        current_date_obj = now.date()

        date_match = None
        day_of_week_map = {
            "segunda": 0, "terça": 1, "quarta": 2, "quinta": 3, "sexta": 4, "sábado": 5, "domingo": 6,
            "seg": 0, "ter": 1, "qua": 2, "qui": 3, "sex": 4, "sab": 5, "dom": 6
        }

        if re.search(r'\bhoje\b', text, re.IGNORECASE):
            date_match = current_date_obj
        elif re.search(r'\bamanhã\b', text, re.IGNORECASE):
            date_match = (current_date_obj + timedelta(days=1))
        else:
            for day_name, day_num in day_of_week_map.items():
                if re.search(r'\b' + day_name + r'\b', text, re.IGNORECASE):
                    current_weekday = current_date_obj.weekday()
                    days_ahead = day_num - current_weekday
                    if days_ahead <= 0:
                        days_ahead += 7
                    date_match = (current_date_obj + timedelta(days=days_ahead))
                    break
        
        if not date_match:
            date_pattern = re.search(r'(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?', text)
            if date_pattern:
                day = int(date_pattern.group(1))
                month = int(date_pattern.group(2))
                year = int(date_pattern.group(3)) if date_pattern.group(3) else now.year
                if len(str(year)) == 2:
                    year += 2000 if year < 50 else 1900
                try:
                    parsed_date = datetime.date(year, month, day)
                    if date_pattern.group(3) is None and parsed_date < current_date_obj:
                        parsed_date = datetime.date(year + 1, month, day)
                    date_match = parsed_date
                except ValueError:
                    date_match = None
        
        if not date_match:
            date_match = current_date_obj

        time_found = False

        relative_time_match = re.search(r'(?:daqui a|em)\s*(\d+)\s*(minutos?|horas?)', text, re.IGNORECASE)
        if relative_time_match:
            value = int(relative_time_match.group(1))
            unit = relative_time_match.group(2).lower()
            if 'minuto' in unit:
                start_dt = now + timedelta(minutes=value)
            elif 'hora' in unit:
                start_dt = now + timedelta(hours=value)
            start_dt = start_dt.replace(second=0, microsecond=0)
            end_dt = None
            time_found = True

        if not time_found:
            time_ranges = re.findall(r'(\d{1,2}(?:h|:\d{2})?)\s*(?:às|as|-)\s*(\d{1,2}(?:h|:\d{2})?)', text, re.IGNORECASE)
            single_times = re.findall(r'\b(\d{1,2}(?:h|:\d{2})?)\b', text, re.IGNORECASE)

            if time_ranges:
                start_time_str = time_ranges[0][0].replace('h', ':00')
                end_time_str = time_ranges[0][1].replace('h', ':00')

                try:
                    start_hour, start_minute = map(int, (start_time_str + ":00").split(':')[:2])
                    end_hour, end_minute = map(int, (end_time_str + ":00").split(':')[:2])

                    start_dt_candidate = TIMEZONE.localize(datetime.datetime.combine(date_match, datetime.time(start_hour, start_minute)))
                    end_dt_candidate = TIMEZONE.localize(datetime.datetime.combine(date_match, datetime.time(end_hour, end_minute)))

                    if start_dt_candidate < now and date_match == current_date_obj:
                        start_dt_candidate += timedelta(days=1)
                        end_dt_candidate += timedelta(days=1)

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
                if 'h' in time_str_raw:
                    time_str = time_str_raw.replace('h', ':00')
                elif ':' not in time_str_raw:
                    time_str = time_str_raw + ':00'
                else:
                    time_str = time_str_raw
                
                try:
                    hour, minute = map(int, (time_str + ":00").split(':')[:2])
                    start_dt_candidate = TIMEZONE.localize(datetime.datetime.combine(date_match, datetime.time(hour, minute)))

                    if start_dt_candidate < now and date_match == current_date_obj:
                        start_dt_candidate += timedelta(days=1)
                    
                    start_dt = start_dt_candidate
                    time_found = True

                except ValueError:
                    start_dt = None
        
        if start_dt and start_dt < now:
            return None, None, ""

        if not start_dt and date_match:
            start_dt = TIMEZONE.localize(datetime.datetime.combine(date_match, datetime.time(0, 0)))

        return start_dt, end_dt, duration_str

    async def ask_description(self, update: Update, context: CallbackContext):
        user_text = update.message.text.strip()
        if user_text.lower() == 'voltar':
            return await self.start_agenda_main_menu(update, context) # Voltar para o menu principal da Agenda

        start_dt, end_dt, duration_str = self._parse_datetime(user_text)

        if not start_dt:
            await update.message.reply_text(
                "🤔 Não consegui entender a data/hora ou ela está no passado. Por favor, tente novamente com um formato válido (ex: 'Hoje às 10h', 'Amanhã às 14:30', 'Terça às 9h às 11h') ou 'voltar'.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Voltar à Agenda", callback_data="agenda_main_menu_return")]])
            )
            return ASK_DATE_TIME

        context.user_data['current_task_data'] = {
            'start_datetime': start_dt,
            'end_datetime': end_dt,
            'duration_str': duration_str,
            'original_input': user_text
        }

        time_info = ""
        if end_dt:
            time_info = f"das *{start_dt.strftime('%H:%M')}* às *{end_dt.strftime('%H:%M')}*"
        else:
            time_info = f"às *{start_dt.strftime('%H:%M')}*"

        await update.message.reply_text(
            f"📅 Para *{start_dt.strftime('%d/%m/%Y')}* {time_info}, qual a *descrição* da tarefa? ✨",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Voltar à Agenda", callback_data="agenda_main_menu_return")]])
        )
        return ASK_DESCRIPTION

    async def save_task_and_schedule(self, update: Update, context: CallbackContext):
        description = update.message.text.strip()
        if description.lower() == 'voltar':
            return await self.start_agenda_main_menu(update, context)

        task_data = context.user_data.get('current_task_data')
        if not task_data:
            await update.message.reply_text("🚨 Ocorreu um erro. Por favor, comece novamente a agendar a tarefa.",
                                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Voltar à Agenda", callback_data="agenda_main_menu_return")]])
            )
            return ASK_DATE_TIME

        start_dt = task_data['start_datetime']
        end_dt = task_data['end_datetime']
        duration_str = task_data['duration_str']

        if 'tasks' not in context.user_data:
            context.user_data['tasks'] = []

        task_id = len(context.user_data['tasks']) + 1

        new_task = {
            'id': task_id,
            'title': description,
            'start_datetime': start_dt,
            'end_datetime': end_dt,
            'description': description,
            'duration_str': duration_str,
            'is_completed': False,
            'job_ids': []
        }
        context.user_data['tasks'].append(new_task)

        confirmation_message = (
            f"✅ Tarefa *'{description}'* agendada com sucesso para "
            f"*{start_dt.strftime('%d/%m/%Y')}* às *{start_dt.strftime('%H:%M')}*."
        )
        if duration_str:
            confirmation_message += f" Duração: *{duration_str}*."
        
        await update.message.reply_text(confirmation_message, parse_mode="Markdown")

        self.bot = context.bot 
        self.chat_id = update.effective_chat.id 

        now = datetime.datetime.now(TIMEZONE) 

        job_exact_time = context.job_queue.run_once(
            self._send_task_notification,
            start_dt,
            chat_id=self.chat_id,
            data={'task_id': task_id, 'type': 'start_time'},
            name=f"task_{task_id}_start"
        )
        new_task['job_ids'].append(job_exact_time.name)

        if start_dt - timedelta(minutes=30) > now: 
            job_30min_before = context.job_queue.run_once(
                self._send_task_notification,
                start_dt - timedelta(minutes=30),
                chat_id=self.chat_id,
                data={'task_id': task_id, 'type': '30_min_before'},
                name=f"task_{task_id}_30min_before"
            )
            new_task['job_ids'].append(job_30min_before.name)

        if start_dt - timedelta(hours=1) > now and \
           (start_dt - timedelta(hours=1)).minute != (start_dt - timedelta(minutes=30)).minute:
            job_1hr_before = context.job_queue.run_once(
                self._send_task_notification,
                start_dt - timedelta(hours=1),
                chat_id=self.chat_id,
                data={'task_id': task_id, 'type': '1_hr_before'},
                name=f"task_{task_id}_1hr_before"
            )
            new_task['job_ids'].append(job_1hr_before.name)

        if end_dt and end_dt > now: 
            job_end_time = context.job_queue.run_once(
                self._send_task_notification,
                end_dt,
                chat_id=self.chat_id,
                data={'task_id': task_id, 'type': 'end_time'},
                name=f"task_{task_id}_end"
            )
            new_task['job_ids'].append(job_end_time.name)

        del context.user_data['current_task_data']
        
        await self.start_agenda_main_menu(update, context) # Volta para o menu principal da agenda
        return AGENDA_MAIN_MENU 

    async def _send_task_notification(self, context: CallbackContext):
        job_data = context.job.data
        task_id = job_data['task_id']
        notification_type = job_data['type']
        chat_id = context.job.chat_id

        user_data_for_chat = context.application.user_data.get(chat_id, {})
        tasks = user_data_for_chat.get('tasks', [])
        
        task = next((t for t in tasks if t['id'] == task_id), None)

        if not task or task['is_completed']:
            context.job.schedule_removal()
            return 

        message = ""
        keyboard = None
        now = datetime.datetime.now(TIMEZONE) 
        
        if notification_type == 'start_time':
            message = f"🔔 *Lembrete*: Sua tarefa '{task['title']}' está começando *AGORA*! 🚀"
            if not task['end_datetime'] or task['end_datetime'] <= now:
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
            await context.bot.send_message(chat_id=chat_id, text=message, reply_markup=keyboard, parse_mode="Markdown")
            
            if keyboard and (notification_type == 'start_time' or notification_type == 'end_time'):
                user_data_for_chat['current_task_id_for_feedback'] = task_id

    async def handle_task_completion(self, update: Update, context: CallbackContext):
        query = update.callback_query
        task_id = int(query.data.split('_')[-1])

        tasks = context.user_data.get('tasks', [])
        task = next((t for t in tasks if t['id'] == task_id), None)

        if task:
            task['is_completed'] = True
            await query.edit_message_text(f"🎉 Ótimo! Tarefa *'{task['title']}'* marcada como concluída! Parabéns! 🥳", parse_mode="Markdown")
            for job_name in task['job_ids']:
                current_jobs = context.job_queue.get_jobs_by_name(job_name)
                for job in current_jobs:
                    job.schedule_removal()
            task['job_ids'] = []
            
            if 'current_task_id_for_feedback' in context.user_data and context.user_data['current_task_id_for_feedback'] == task_id:
                del context.user_data['current_task_id_for_feedback']
        else:
            await query.edit_message_text("❌ Desculpe, não encontrei esta tarefa para concluir.")

        await self.start_agenda_main_menu(update, context) # Volta para o menu principal da agenda
        return AGENDA_MAIN_MENU

    async def handle_task_not_completed(self, update: Update, context: CallbackContext):
        query = update.callback_query
        task_id = int(query.data.split('_')[-1])

        tasks = context.user_data.get('tasks', [])
        task = next((t for t in tasks if t['id'] == task_id), None)

        if task:
            context.user_data['current_task_id_for_feedback'] = task_id
            await query.edit_message_text(
                f"😔 Entendido. Por que você *não* conseguiu concluir a tarefa *'{task['title']}'*? (Digite o motivo ou 'ignorar')",
                parse_mode="Markdown"
            )
            return TASK_COMPLETION_FEEDBACK
        else:
            await query.edit_message_text("❌ Desculpe, não encontrei esta tarefa.")
            await self.start_agenda_main_menu(update, context)
            return AGENDA_MAIN_MENU

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

            for job_name in task['job_ids']:
                current_jobs = context.job_queue.get_jobs_by_name(job_name)
                for job in current_jobs:
                    job.schedule_removal()
            task['job_ids'] = []
        else:
            await update.message.reply_text("🚨 Ocorreu um erro ao processar o motivo. Tente novamente.")

        del context.user_data['current_task_id_for_feedback']
        await self.start_agenda_main_menu(update, context) # Volta para o menu principal da agenda
        return AGENDA_MAIN_MENU

    async def list_upcoming_tasks(self, update: Update, context: CallbackContext):
        query = update.callback_query
        await query.answer("Listando tarefas agendadas... 🗓️")
        tasks = context.user_data.get('tasks', [])
        
        message_text = "🗓️ *Suas Tarefas Agendadas (Próximas/Pendentes):*\n\n"
        
        now = datetime.datetime.now(TIMEZONE)
        upcoming_tasks = sorted([
            t for t in tasks 
            if not t['is_completed'] and t['start_datetime'] >= now
        ], key=lambda x: x['start_datetime'])

        if upcoming_tasks:
            for i, task in enumerate(upcoming_tasks):
                time_info = task['start_datetime'].strftime('%H:%M')
                if task['end_datetime']:
                    time_info += f" - {task['end_datetime'].strftime('%H:%M')}"
                
                message_text += (
                    f"*{i+1}. {task['title']}*\n"
                    f"   _Em {task['start_datetime'].strftime('%d/%m/%Y')} às {time_info} "
                    f"({task['duration_str'] if task['duration_str'] else 'sem duração'})_\n\n"
                )
        else:
            message_text += "Você não tem tarefas agendadas futuras. Que tal adicionar uma? ✨"
        
        keyboard = [
            [InlineKeyboardButton("➕ Adicionar Nova Tarefa", callback_data="add_new_task")],
            [InlineKeyboardButton("↩️ Voltar ao Gerenciamento", callback_data="manage_tasks_return")],
            [InlineKeyboardButton("⬅️ Voltar ao Menu Principal", callback_data="main_menu_return")]
        ]
        
        await query.edit_message_text(
            text=message_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return MANAGE_TASKS_MENU # Retorna ao menu de gerenciamento

    async def list_completed_tasks(self, update: Update, context: CallbackContext):
        query = update.callback_query
        await query.answer("Listando tarefas concluídas... ✅")
        tasks = context.user_data.get('tasks', [])
        
        message_text = "✅ *Suas Tarefas Concluídas:*\n\n"
        
        completed_tasks = sorted([t for t in tasks if t['is_completed']], key=lambda x: x['start_datetime'], reverse=True)

        if completed_tasks:
            for i, task in enumerate(completed_tasks):
                time_info = task['start_datetime'].strftime('%H:%M')
                if task['end_datetime']:
                    time_info += f" - {task['end_datetime'].strftime('%H:%M')}"
                
                message_text += (
                    f"*{i+1}. {task['title']}*\n"
                    f"   _Concluída em {task['start_datetime'].strftime('%d/%m/%Y')} às {time_info}_\n\n"
                )
        else:
            message_text += "Você ainda não concluiu nenhuma tarefa. Bora começar! 💪"
        
        keyboard = [
            [InlineKeyboardButton("➕ Adicionar Nova Tarefa", callback_data="add_new_task")],
            [InlineKeyboardButton("↩️ Voltar ao Gerenciamento", callback_data="manage_tasks_return")],
            [InlineKeyboardButton("⬅️ Voltar ao Menu Principal", callback_data="main_menu_return")]
        ]
        
        await query.edit_message_text(
            text=message_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return MANAGE_TASKS_MENU # Retorna ao menu de gerenciamento

    async def initiate_delete_task(self, update: Update, context: CallbackContext):
        query = update.callback_query
        await query.answer("Escolha uma tarefa para apagar... 🗑️")
        tasks = context.user_data.get('tasks', [])
        
        # Filtra tarefas não concluídas e futuras ou passadas não concluídas para exclusão
        now = datetime.datetime.now(TIMEZONE)
        deletable_tasks = sorted([
            t for t in tasks 
            if not t['is_completed'] or (t['is_completed'] and t['start_datetime'] < now) # Concluídas no passado também podem ser apagadas
        ], key=lambda x: x['start_datetime'])

        if not deletable_tasks:
            await query.edit_message_text(
                "Você não tem tarefas para apagar. ✨",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("↩️ Voltar ao Gerenciamento", callback_data="manage_tasks_return")],
                    [InlineKeyboardButton("⬅️ Voltar ao Menu Principal", callback_data="main_menu_return")]
                ])
            )
            return MANAGE_TASKS_MENU
        
        message_text = "🗑️ *Selecione a tarefa que deseja apagar:*\n\n"
        keyboard_rows = []
        
        for i, task in enumerate(deletable_tasks):
            time_info = task['start_datetime'].strftime('%d/%m %H:%M')
            status_emoji = "✅" if task['is_completed'] else ("⏳" if task['start_datetime'] >= now else "❗")
            task_title = task['title']
            
            message_text += f"{status_emoji} {i+1}. {task_title} ({time_info})\n"
            keyboard_rows.append([InlineKeyboardButton(f"{i+1}. {task_title}", callback_data=f"delete_task_id_{task['id']}")])
        
        keyboard_rows.append([InlineKeyboardButton("↩️ Voltar ao Gerenciamento", callback_data="manage_tasks_return")])
        keyboard_rows.append([InlineKeyboardButton("⬅️ Voltar ao Menu Principal", callback_data="main_menu_return")])

        await query.edit_message_text(
            text=message_text,
            reply_markup=InlineKeyboardMarkup(keyboard_rows),
            parse_mode="Markdown"
        )
        return DELETE_TASK_SELECTION

    async def confirm_delete_task(self, update: Update, context: CallbackContext):
        query = update.callback_query
        task_id = int(query.data.split('_')[-1])
        
        tasks = context.user_data.get('tasks', [])
        task_to_delete = next((t for t in tasks if t['id'] == task_id), None)

        if not task_to_delete:
            await query.edit_message_text("❌ Tarefa não encontrada.",
                                            reply_markup=InlineKeyboardMarkup([
                                                [InlineKeyboardButton("↩️ Voltar ao Gerenciamento", callback_data="manage_tasks_return")],
                                                [InlineKeyboardButton("⬅️ Voltar ao Menu Principal", callback_data="main_menu_return")]
                                            ]))
            return MANAGE_TASKS_MENU
        
        context.user_data['task_id_to_delete'] = task_id # Armazena para a próxima etapa

        keyboard = [
            [InlineKeyboardButton("Sim, APAGAR!", callback_data=f"confirm_delete_yes_{task_id}")],
            [InlineKeyboardButton("Não, Cancelar.", callback_data=f"confirm_delete_no_{task_id}")]
        ]

        await query.edit_message_text(
            f"⚠️ Tem certeza que deseja apagar a tarefa: *'{task_to_delete['title']}'* (ID: {task_id})?\n"
            f"Isso não poderá ser desfeito.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return CONFIRM_DELETE_TASK

    async def execute_delete_task(self, update: Update, context: CallbackContext):
        query = update.callback_query
        task_id = int(query.data.split('_')[-1])

        # Garante que é a tarefa que o usuário confirmou na etapa anterior
        if context.user_data.get('task_id_to_delete') != task_id:
            await query.edit_message_text("❌ Erro de confirmação. Por favor, tente novamente.",
                                            reply_markup=InlineKeyboardMarkup([
                                                [InlineKeyboardButton("↩️ Voltar ao Gerenciamento", callback_data="manage_tasks_return")],
                                                [InlineKeyboardButton("⬅️ Voltar ao Menu Principal", callback_data="main_menu_return")]
                                            ]))
            return MANAGE_TASKS_MENU

        tasks = context.user_data.get('tasks', [])
        original_len = len(tasks)
        
        # Filtra a tarefa a ser removida
        context.user_data['tasks'] = [t for t in tasks if t['id'] != task_id]
        
        if len(context.user_data['tasks']) < original_len:
            # Cancela jobs relacionados a esta tarefa
            for job_name in next((t for t in tasks if t['id'] == task_id), {}).get('job_ids', []):
                current_jobs = context.job_queue.get_jobs_by_name(job_name)
                for job in current_jobs:
                    job.schedule_removal()
            
            await query.edit_message_text(f"🗑️ Tarefa *'{next((t for t in tasks if t['id'] == task_id), {}).get('title', '...')}'* apagada com sucesso!", parse_mode="Markdown")
        else:
            await query.edit_message_text("❌ Tarefa não encontrada ou já apagada.")
        
        del context.user_data['task_id_to_delete'] # Limpa o ID temporário
        await self.open_manage_tasks_menu(update, context) # Retorna ao menu de gerenciamento
        return MANAGE_TASKS_MENU

    async def cancel_delete_task(self, update: Update, context: CallbackContext):
        query = update.callback_query
        # O ID da tarefa não importa muito aqui, é só para voltar
        if 'task_id_to_delete' in context.user_data:
            del context.user_data['task_id_to_delete']
        
        await query.edit_message_text("🚫 Exclusão de tarefa cancelada.",
                                        reply_markup=InlineKeyboardMarkup([
                                            [InlineKeyboardButton("↩️ Voltar ao Gerenciamento", callback_data="manage_tasks_return")],
                                            [InlineKeyboardButton("⬅️ Voltar ao Menu Principal", callback_data="main_menu_return")]
                                        ]))
        return MANAGE_TASKS_MENU
