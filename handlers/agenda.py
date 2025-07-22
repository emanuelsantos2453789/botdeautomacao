
# agenda.py
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

# --- Estados da Conversa para a Agenda ---
ASK_DATE_TIME = 1
ASK_DESCRIPTION = 2
CONFIRM_TASK = 3
TASK_COMPLETION_FEEDBACK = 4 # Novo estado para feedback de conclusão

# Dicionário para armazenar as tarefas. Em um projeto real, isso seria um banco de dados.
# Usaremos context.user_data['tasks'] para persistência por usuário.
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
                CONFIRM_TASK: [
                    CallbackQueryHandler(self.handle_task_completion, pattern="^task_completed_yes_"),
                    CallbackQueryHandler(self.handle_task_not_completed, pattern="^task_completed_no_"),
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
            "Para criar uma nova tarefa, digite o dia e o horário. Exemplos:\n"
            "- Hoje às 10h\n"
            "- Amanhã às 14:30\n"
            "- Terça às 9h às 11h\n"
            "- 25/12 às 20h\n"
            "- Daqui a 2 horas\n"
            "- Em 30 minutos\n"
            "Ou digite 'voltar' para o menu principal.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Voltar", callback_data="main_menu_return")]])
        )
        return ASK_DATE_TIME

    async def agenda_fallback(self, update: Update, context: CallbackContext):
        if update.message:
            await update.message.reply_text(
                "Desculpe, não entendi. Por favor, digite o dia e o horário da tarefa ou 'voltar'.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Voltar", callback_data="main_menu_return")]])
            )
        elif update.callback_query:
            await update.callback_query.answer("Ação inválida para a Agenda.")
            await update.callback_query.edit_message_text(
                "Ação inválida. Por favor, digite o dia e o horário da tarefa ou 'voltar'.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Voltar", callback_data="main_menu_return")]])
            )
        return ASK_DATE_TIME

    async def return_to_main_menu_from_agenda(self, update: Update, context: CallbackContext):
        query = update.callback_query
        await query.answer()
        # Limpa dados temporários da conversa da agenda
        if 'current_task_data' in context.user_data:
            del context.user_data['current_task_data']
        return ConversationHandler.END # Sinaliza para o ConversationHandler pai retornar ao menu principal

    def _parse_datetime(self, text: str) -> tuple[datetime.datetime | None, datetime.datetime | None, str]:
        """
        Tenta extrair data, hora de início, hora de fim e uma string de duração do texto do usuário.
        Retorna (start_datetime, end_datetime, duration_str).
        """
        now = datetime.datetime.now()
        start_dt = None
        end_dt = None
        duration_str = ""

        # 1. Parsing de Dia (hoje, amanhã, dias da semana, DD/MM)
        date_match = None
        day_of_week_map = {
            "segunda": 0, "terça": 1, "quarta": 2, "quinta": 3, "sexta": 4, "sábado": 5, "domingo": 6
        }

        # Hoje
        if re.search(r'\bhoje\b', text, re.IGNORECASE):
            date_match = now.date()
        # Amanhã
        elif re.search(r'\bamanhã\b', text, re.IGNORECASE):
            date_match = (now + timedelta(days=1)).date()
        # Dias da semana
        else:
            for day_name, day_num in day_of_week_map.items():
                if re.search(r'\b' + day_name + r'\b', text, re.IGNORECASE):
                    current_day_num = now.weekday() # Monday is 0 and Sunday is 6
                    days_ahead = day_num - current_day_num
                    if days_ahead < 0: # Se o dia da semana já passou nesta semana, assume a próxima semana
                        days_ahead += 7
                    date_match = (now + timedelta(days=days_ahead)).date()
                    break
        # DD/MM
        if not date_match:
            date_pattern = re.search(r'(\d{1,2})[/-](\d{1,2})', text)
            if date_pattern:
                day = int(date_pattern.group(1))
                month = int(date_pattern.group(2))
                year = now.year
                try:
                    # Se a data já passou neste ano, assume o próximo ano
                    if datetime.date(year, month, day) < now.date():
                        year += 1
                    date_match = datetime.date(year, month, day)
                except ValueError:
                    date_match = None # Data inválida

        # Se nenhuma data específica foi encontrada, assume hoje
        if not date_match:
            date_match = now.date()

        # 2. Parsing de Hora (HHh, HH:MM, HHh as HHh, HH:MM as HH:MM, daqui a X tempo)
        time_ranges = re.findall(r'(\d{1,2}(?:h|:\d{2})?)\s*(?:às|as|-)\s*(\d{1,2}(?:h|:\d{2})?)', text, re.IGNORECASE)
        single_times = re.findall(r'\b(\d{1,2}(?:h|:\d{2})?)\b', text, re.IGNORECASE)
        
        # Daqui a X tempo (minutos ou horas)
        relative_time_match = re.search(r'daqui a (\d+)\s*(minutos?|horas?)', text, re.IGNORECASE)
        if relative_time_match:
            value = int(relative_time_match.group(1))
            unit = relative_time_match.group(2).lower()
            if 'minuto' in unit:
                start_dt = now + timedelta(minutes=value)
            elif 'hora' in unit:
                start_dt = now + timedelta(hours=value)
            # Ajusta a data para a data calculada
            date_match = start_dt.date()

        elif time_ranges:
            start_time_str = time_ranges[0][0].replace('h', ':00')
            end_time_str = time_ranges[0][1].replace('h', ':00')

            try:
                start_hour, start_minute = map(int, start_time_str.split(':'))
                end_hour, end_minute = map(int, end_time_str.split(':'))

                start_dt = datetime.datetime.combine(date_match, datetime.time(start_hour, start_minute))
                end_dt = datetime.datetime.combine(date_match, datetime.time(end_hour, end_minute))

                # Se a hora final for anterior à inicial, assume que é no dia seguinte
                if end_dt < start_dt:
                    end_dt += timedelta(days=1)

                duration = end_dt - start_dt
                hours, remainder = divmod(duration.total_seconds(), 3600)
                minutes = remainder // 60
                if hours > 0 and minutes > 0:
                    duration_str = f"{int(hours)}h e {int(minutes)}min"
                elif hours > 0:
                    duration_str = f"{int(hours)}h"
                elif minutes > 0:
                    duration_str = f"{int(minutes)}min"

            except ValueError:
                start_dt = None
                end_dt = None
        elif single_times:
            time_str = single_times[0].replace('h', ':00')
            try:
                hour, minute = map(int, time_str.split(':'))
                start_dt = datetime.datetime.combine(date_match, datetime.time(hour, minute))
                # Se a hora já passou hoje, assume a próxima ocorrência (ex: 8 AM, mas já são 9 AM, então 8 AM de amanhã)
                if start_dt < now and date_match == now.date():
                    start_dt += timedelta(days=1)
            except ValueError:
                start_dt = None

        # Ajusta a data para o start_dt final
        if start_dt and date_match != start_dt.date():
            # Se a data foi inferida como 'hoje' ou 'amanhã' inicialmente,
            # mas o horário empurrou para o dia seguinte, atualiza date_match
            date_match = start_dt.date()

        # Se start_dt ainda não foi definido, mas uma data foi, tenta combinar com 00:00
        if not start_dt and date_match:
            start_dt = datetime.datetime.combine(date_match, datetime.time(0, 0))

        # Validação final: se a tarefa for no passado, invalida
        if start_dt and start_dt < now:
            return None, None, "" # Retorna nulo se for no passado

        return start_dt, end_dt, duration_str

    async def ask_description(self, update: Update, context: CallbackContext):
        user_text = update.message.text.strip()
        if user_text.lower() == 'voltar':
            return await self.return_to_main_menu_from_agenda(update, context)

        start_dt, end_dt, duration_str = self._parse_datetime(user_text)

        if not start_dt:
            await update.message.reply_text(
                "Não consegui entender a data/hora. Por favor, tente novamente com um formato válido (ex: 'Hoje às 10h', 'Amanhã às 14:30', 'Terça às 9h às 11h').",
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
            time_info = f"das {start_dt.strftime('%H:%M')} às {end_dt.strftime('%H:%M')}"
        else:
            time_info = f"às {start_dt.strftime('%H:%M')}"

        await update.message.reply_text(
            f"Certo! Para {start_dt.strftime('%d/%m/%Y')} {time_info}, qual a descrição da tarefa?",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Voltar", callback_data="main_menu_return")]])
        )
        return ASK_DESCRIPTION

    async def save_task_and_schedule(self, update: Update, context: CallbackContext):
        description = update.message.text.strip()
        if description.lower() == 'voltar':
            return await self.return_to_main_menu_from_agenda(update, context)

        task_data = context.user_data.get('current_task_data')
        if not task_data:
            await update.message.reply_text("Ocorreu um erro. Por favor, comece novamente.",
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
            'description': description,
            'duration_str': duration_str,
            'is_completed': False,
            'job_ids': [] # Para armazenar os IDs dos jobs agendados
        }
        context.user_data['tasks'].append(new_task)

        confirmation_message = f"Tarefa agendada com sucesso para {start_dt.strftime('%d/%m/%Y')} às {start_dt.strftime('%H:%M')}. "
        if duration_str:
            confirmation_message += f"Duração: {duration_str}."
        await update.message.reply_text(confirmation_message)

        # --- Agendamento das Notificações ---
        self.bot = context.bot # Garante que o bot está atualizado
        self.chat_id = update.effective_chat.id # Garante que o chat_id está atualizado

        # Notificação no horário exato
        job_exact_time = context.job_queue.run_once(
            self._send_task_notification,
            start_dt,
            chat_id=self.chat_id,
            data={'task_id': task_id, 'type': 'start_time'},
            name=f"task_{task_id}_start"
        )
        new_task['job_ids'].append(job_exact_time.name)

        # Notificação 30 minutos antes
        if start_dt - timedelta(minutes=30) > datetime.datetime.now():
            job_30min_before = context.job_queue.run_once(
                self._send_task_notification,
                start_dt - timedelta(minutes=30),
                chat_id=self.chat_id,
                data={'task_id': task_id, 'type': '30_min_before'},
                name=f"task_{task_id}_30min_before"
            )
            new_task['job_ids'].append(job_30min_before.name)

        # Notificação 1 hora antes (se não for muito próximo dos 30 minutos antes)
        if start_dt - timedelta(hours=1) > datetime.datetime.now() and \
           (start_dt - timedelta(hours=1)).minute != (start_dt - timedelta(minutes=30)).minute: # Evita duplicidade se 30 min e 1h forem muito próximos
            job_1hr_before = context.job_queue.run_once(
                self._send_task_notification,
                start_dt - timedelta(hours=1),
                chat_id=self.chat_id,
                data={'task_id': task_id, 'type': '1_hr_before'},
                name=f"task_{task_id}_1hr_before"
            )
            new_task['job_ids'].append(job_1hr_before.name)

        # Notificação no horário final (se houver duração)
        if end_dt and end_dt > datetime.datetime.now():
            job_end_time = context.job_queue.run_once(
                self._send_task_notification,
                end_dt,
                chat_id=self.chat_id,
                data={'task_id': task_id, 'type': 'end_time'},
                name=f"task_{task_id}_end"
            )
            new_task['job_ids'].append(job_end_time.name)

        del context.user_data['current_task_data'] # Limpa os dados temporários
        await self.show_agenda_options(update, context)
        return ConversationHandler.END # Retorna ao menu principal

    async def _send_task_notification(self, context: CallbackContext):
        job_data = context.job.data
        task_id = job_data['task_id']
        notification_type = job_data['type']
        chat_id = context.job.chat_id

        tasks = context.bot_data.get(chat_id, {}).get('tasks', []) # Acessa as tarefas do chat_id específico
        task = next((t for t in tasks if t['id'] == task_id), None)

        if not task or task['is_completed']:
            return # Não notificar se a tarefa não existe ou já foi concluída

        message = ""
        if notification_type == 'start_time':
            message = f"🔔 Lembrete: Sua tarefa '{task['title']}' está começando AGORA!"
        elif notification_type == '30_min_before':
            message = f"⏰ Atenção! Sua tarefa '{task['title']}' começa em 30 minutos."
        elif notification_type == '1_hr_before':
            message = f"⏳ Aviso: Sua tarefa '{task['title']}' começa em 1 hora."
        elif notification_type == 'end_time':
            message = f"✅ Sua tarefa '{task['title']}' terminou. Você a concluiu?"
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Sim, Concluí!", callback_data=f"task_completed_yes_{task_id}")],
                [InlineKeyboardButton("Não, não Concluí.", callback_data=f"task_completed_no_{task_id}")]
            ])
            await context.bot.send_message(chat_id=chat_id, text=message, reply_markup=keyboard)
            return # Não envia a mensagem padrão, pois já enviou com botões

        await context.bot.send_message(chat_id=chat_id, text=message)

        # Para notificações de início de tarefa sem duração
        if notification_type == 'start_time' and not task['end_datetime']:
            message = f"✅ Sua tarefa '{task['title']}' está no horário. Você a concluiu?"
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Sim, Concluí!", callback_data=f"task_completed_yes_{task_id}")],
                [InlineKeyboardButton("Não, não Concluí.", callback_data=f"task_completed_no_{task_id}")]
            ])
            await context.bot.send_message(chat_id=chat_id, text=message, reply_markup=keyboard)
            context.user_data['current_task_id_for_feedback'] = task_id # Armazena para o próximo estado
            return TASK_COMPLETION_FEEDBACK # Transição para o estado de feedback

    async def handle_task_completion(self, update: Update, context: CallbackContext):
        query = update.callback_query
        task_id = int(query.data.split('_')[-1])

        # Acessa as tarefas do chat_id específico
        tasks = context.user_data.get('tasks', [])
        task = next((t for t in tasks if t['id'] == task_id), None)

        if task:
            task['is_completed'] = True
            await query.edit_message_text(f"Ótimo! Tarefa '{task['title']}' marcada como concluída. 🎉")
            # Cancela os jobs restantes para esta tarefa
            for job_name in task['job_ids']:
                current_jobs = context.job_queue.get_jobs_by_name(job_name)
                for job in current_jobs:
                    job.schedule_removal()
            task['job_ids'] = [] # Limpa os IDs dos jobs
        else:
            await query.edit_message_text("Desculpe, não encontrei esta tarefa.")
        
        await self.show_agenda_options(update, context)
        return ConversationHandler.END

    async def handle_task_not_completed(self, update: Update, context: CallbackContext):
        query = update.callback_query
        task_id = int(query.data.split('_')[-1])

        tasks = context.user_data.get('tasks', [])
        task = next((t for t in tasks if t['id'] == task_id), None)

        if task:
            context.user_data['current_task_id_for_feedback'] = task_id
            await query.edit_message_text(
                f"Entendido. Por que você não conseguiu concluir a tarefa '{task['title']}'? (Digite o motivo ou 'ignorar')"
            )
            return TASK_COMPLETION_FEEDBACK
        else:
            await query.edit_message_text("Desculpe, não encontrei esta tarefa.")
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
                await update.message.reply_text(f"Motivo para '{task['title']}' registrado: '{reason}'.")
            else:
                await update.message.reply_text(f"Motivo para '{task['title']}' ignorado.")
            
            # Cancela os jobs restantes para esta tarefa, pois o ciclo de feedback terminou
            for job_name in task['job_ids']:
                current_jobs = context.job_queue.get_jobs_by_name(job_name)
                for job in current_jobs:
                    job.schedule_removal()
            task['job_ids'] = [] # Limpa os IDs dos jobs
        else:
            await update.message.reply_text("Ocorreu um erro ao processar o motivo.")
        
        del context.user_data['current_task_id_for_feedback'] # Limpa o ID temporário
        await self.show_agenda_options(update, context)
        return ConversationHandler.END

    async def show_agenda_options(self, update: Update, context: CallbackContext):
        # Este método pode ser expandido para mostrar as tarefas existentes, etc.
        # Por enquanto, apenas retorna ao menu principal.
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="O que mais você gostaria de fazer com a agenda?",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Voltar ao Menu Principal", callback_data="main_menu_return")]])
        )

# Para usar no main.py, você precisará importar:
# from handlers.agenda import Agenda, ASK_DATE_TIME, ASK_DESCRIPTION, CONFIRM_TASK, TASK_COMPLETION_FEEDBACK
# E adicionar o handler da Agenda ao MAIN_MENU_STATE.
