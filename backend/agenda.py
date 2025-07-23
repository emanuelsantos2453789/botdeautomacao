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
import logging

# Configuração do logger para este módulo
logger = logging.getLogger(__name__)

# Definindo o fuso horário para consistência (ex: 'America/Sao_Paulo' para o Brasil)
# Certifique-se de que esta variável global esteja acessível ou seja passada para a classe.
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
        try:
            user_id = update.effective_user.id
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
            logger.info(f"Usuário {user_id} entrou no menu principal da agenda.")
            return AGENDA_MAIN_MENU
        except Exception as e:
            logger.error(f"Erro ao iniciar o menu principal da agenda para o usuário {update.effective_user.id}: {e}", exc_info=True)
            if update.callback_query:
                await update.callback_query.message.reply_text("Ops! Ocorreu um erro ao carregar o menu da agenda. Tente novamente mais tarde.")
            else:
                await update.message.reply_text("Ops! Ocorreu um erro ao carregar o menu da agenda. Tente novamente mais tarde.")
            return ConversationHandler.END

    def _get_agenda_main_menu_keyboard(self):
        keyboard = [
            [InlineKeyboardButton("➕ Adicionar Nova Tarefa", callback_data="add_new_task")],
            [InlineKeyboardButton("📋 Gerenciar Tarefas", callback_data="manage_tasks")],
            [InlineKeyboardButton("↩️ Voltar ao Menu Principal", callback_data="main_menu_return")]
        ]
        return InlineKeyboardMarkup(keyboard)

    async def start_add_task_flow(self, update: Update, context: CallbackContext):
        try:
            query = update.callback_query
            user_id = update.effective_user.id
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
            logger.info(f"Usuário {user_id} iniciou o fluxo de adição de tarefa.")
            return ASK_DATE_TIME
        except Exception as e:
            logger.error(f"Erro ao iniciar fluxo de adição de tarefa para o usuário {update.effective_user.id}: {e}", exc_info=True)
            await query.message.reply_text("Ops! Ocorreu um erro ao iniciar a adição de tarefa. Por favor, tente novamente.")
            return AGENDA_MAIN_MENU

    async def open_manage_tasks_menu(self, update: Update, context: CallbackContext):
        try:
            query = update.callback_query
            user_id = update.effective_user.id
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
            logger.info(f"Usuário {user_id} abriu o menu de gerenciamento de tarefas.")
            return MANAGE_TASKS_MENU
        except Exception as e:
            logger.error(f"Erro ao abrir o menu de gerenciamento de tarefas para o usuário {update.effective_user.id}: {e}", exc_info=True)
            await query.message.reply_text("Ops! Ocorreu um erro ao carregar o gerenciador de tarefas. Por favor, tente novamente.")
            return AGENDA_MAIN_MENU

    async def agenda_fallback(self, update: Update, context: CallbackContext):
        try:
            user_id = update.effective_user.id
            if update.message:
                logger.warning(f"Fallback da agenda ativado para mensagem do usuário {user_id}: '{update.message.text}'")
                await update.message.reply_text(
                    "❌ Ops! Não entendi o que você digitou. Por favor, tente novamente com um formato válido ou use os botões. 🤔",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Voltar à Agenda", callback_data="agenda_main_menu_return")]])
                )
            elif update.callback_query:
                logger.warning(f"Fallback da agenda ativado para callback do usuário {user_id}: '{update.callback_query.data}'")
                await update.callback_query.answer("🚫 Ação inválida para a Agenda.")
                await update.callback_query.edit_message_text(
                    "🚫 Ação inválida. Por favor, use os botões. 🧐",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Voltar à Agenda", callback_data="agenda_main_menu_return")]])
                )
            return AGENDA_MAIN_MENU
        except Exception as e:
            logger.critical(f"Erro CRÍTICO no fallback da agenda para o usuário {update.effective_user.id}: {e}", exc_info=True)
            # Em caso de erro no fallback, tentar finalizar a conversa para evitar loop
            if update.message:
                await update.message.reply_text("Um erro inesperado ocorreu. Por favor, tente /start novamente.")
            elif update.callback_query:
                await update.callback_query.message.reply_text("Um erro inesperado ocorreu. Por favor, tente /start novamente.")
            return ConversationHandler.END

    async def return_to_main_menu_from_agenda(self, update: Update, context: CallbackContext):
        try:
            user_id = update.effective_user.id
            query = update.callback_query
            if query:
                await query.answer()
            
            # Limpa dados temporários do usuário ao sair da agenda
            if 'current_task_data' in context.user_data:
                del context.user_data['current_task_data']
            if 'current_task_id_for_feedback' in context.user_data:
                del context.user_data['current_task_id_for_feedback']
            
            logger.info(f"Usuário {user_id} retornou do menu da agenda para o menu principal.")
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Erro ao retornar do menu da agenda para o principal para o usuário {update.effective_user.id}: {e}", exc_info=True)
            if update.callback_query:
                await update.callback_query.message.reply_text("Ops! Ocorreu um erro ao voltar. Por favor, tente novamente.")
            return ConversationHandler.END


    def _parse_datetime(self, text: str) -> tuple[datetime.datetime | None, datetime.datetime | None, str]:
        """
        Tenta extrair data, hora de início, hora de fim e uma string de duração do texto do usuário.
        Retorna (start_datetime, end_datetime, duration_str).
        """
        try:
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
                date_match = current_date_obj # Se nenhuma data explícita, usa a data atual

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

                        # Se a hora de início for no passado HOJE, tenta para o dia seguinte
                        if start_dt_candidate < now and date_match == current_date_obj.date(): # Comparar apenas as datas para evitar loop
                            start_dt_candidate += timedelta(days=1)
                            end_dt_candidate += timedelta(days=1)

                        if end_dt_candidate < start_dt_candidate: # Se o fim for antes do início, assume que é no dia seguinte
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

                    except ValueError as ve:
                        logger.warning(f"Erro de valor ao parsear intervalo de tempo '{text}': {ve}")
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

                        # Se a hora for no passado HOJE, tenta para o dia seguinte
                        if start_dt_candidate < now and date_match == current_date_obj.date():
                            start_dt_candidate += timedelta(days=1)
                        
                        start_dt = start_dt_candidate
                        time_found = True

                    except ValueError as ve:
                        logger.warning(f"Erro de valor ao parsear tempo único '{text}': {ve}")
                        start_dt = None
            
            # Se a data/hora inicial ainda estiver no passado, retorna None
            if start_dt and start_dt < now:
                logger.info(f"Data/hora parseada '{start_dt}' está no passado para '{text}'.")
                return None, None, ""

            if not start_dt and date_match:
                # Se só tiver data, assume meia-noite do dia
                start_dt = TIMEZONE.localize(datetime.datetime.combine(date_match, datetime.time(0, 0)))

            return start_dt, end_dt, duration_str
        except Exception as e:
            logger.error(f"Erro inesperado no parser de data/hora para o texto '{text}': {e}", exc_info=True)
            return None, None, ""

    async def ask_description(self, update: Update, context: CallbackContext):
        try:
            user_id = update.effective_user.id
            user_text = update.message.text.strip()
            
            if user_text.lower() == 'voltar':
                logger.info(f"Usuário {user_id} cancelou adição de tarefa (pedindo descrição).")
                return await self.start_agenda_main_menu(update, context)

            start_dt, end_dt, duration_str = self._parse_datetime(user_text)

            if not start_dt:
                logger.warning(f"Usuário {user_id} forneceu data/hora inválida: '{user_text}'.")
                await update.message.reply_text(
                    "🤔 Não consegui entender a data/hora ou ela está no passado. Por favor, tente novamente com um formato válido (ex: 'Hoje às 10h', 'Amanhã às 14:30', 'Terça às 9h às 11h') ou 'voltar'.",
                    parse_mode="Markdown",
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
            logger.info(f"Usuário {user_id} solicitou descrição para tarefa agendada para {start_dt.strftime('%d/%m/%Y %H:%M')}.")
            return ASK_DESCRIPTION
        except Exception as e:
            logger.error(f"Erro ao pedir descrição da tarefa para o usuário {update.effective_user.id}: {e}", exc_info=True)
            await update.message.reply_text("Ops! Ocorreu um erro ao processar a data/hora. Por favor, tente novamente.")
            return AGENDA_MAIN_MENU


    async def save_task_and_schedule(self, update: Update, context: CallbackContext):
        try:
            user_id = update.effective_user.id
            description = update.message.text.strip()
            if description.lower() == 'voltar':
                logger.info(f"Usuário {user_id} cancelou adição de tarefa (pedindo descrição).")
                return await self.start_agenda_main_menu(update, context)

            task_data = context.user_data.get('current_task_data')
            if not task_data:
                logger.error(f"Erro: current_task_data ausente para o usuário {user_id} ao salvar tarefa.")
                await update.message.reply_text("🚨 Ocorreu um erro. Por favor, comece novamente a agendar a tarefa.",
                                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Voltar à Agenda", callback_data="agenda_main_menu_return")]])
                )
                return ASK_DATE_TIME

            start_dt = task_data['start_datetime']
            end_dt = task_data['end_datetime']
            duration_str = task_data['duration_str']

            if 'tasks' not in context.user_data:
                context.user_data['tasks'] = []

            # Gerar um ID único para a tarefa
            task_id = 0
            if context.user_data['tasks']:
                task_id = max(t['id'] for t in context.user_data['tasks']) + 1
            else:
                task_id = 1

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
            logger.info(f"Usuário {user_id} salvou a tarefa '{description}' (ID: {task_id}).")

            self.bot = context.bot # Certifica que o bot está configurado
            self.chat_id = update.effective_chat.id # Certifica que o chat_id está configurado

            now = datetime.datetime.now(TIMEZONE)

            # Agendar notificação de horário exato
            if start_dt > now:
                job_exact_time = context.job_queue.run_once(
                    self._send_task_notification,
                    start_dt,
                    chat_id=self.chat_id,
                    data={'task_id': task_id, 'type': 'start_time'},
                    name=f"task_{task_id}_start"
                )
                new_task['job_ids'].append(job_exact_time.name)
                logger.info(f"Agendada notificação de início para tarefa {task_id} em {start_dt}.")
            else:
                logger.warning(f"Tarefa {task_id} (início: {start_dt}) está no passado, notificação de início não agendada.")


            # Agendar notificação 30 minutos antes
            if start_dt - timedelta(minutes=30) > now:
                job_30min_before = context.job_queue.run_once(
                    self._send_task_notification,
                    start_dt - timedelta(minutes=30),
                    chat_id=self.chat_id,
                    data={'task_id': task_id, 'type': '30_min_before'},
                    name=f"task_{task_id}_30min_before"
                )
                new_task['job_ids'].append(job_30min_before.name)
                logger.info(f"Agendada notificação de 30min antes para tarefa {task_id}.")

            # Agendar notificação 1 hora antes (apenas se não for sobreposto pela de 30min)
            # A condição (start_dt - timedelta(hours=1)).minute != (start_dt - timedelta(minutes=30)).minute
            # é para evitar agendar duas notificações muito próximas se a hora exata menos 1h cair
            # muito perto dos 30 minutos antes.
            if start_dt - timedelta(hours=1) > now and \
               (start_dt - timedelta(hours=1)).replace(second=0, microsecond=0) != \
               (start_dt - timedelta(minutes=30)).replace(second=0, microsecond=0):
                job_1hr_before = context.job_queue.run_once(
                    self._send_task_notification,
                    start_dt - timedelta(hours=1),
                    chat_id=self.chat_id,
                    data={'task_id': task_id, 'type': '1_hr_before'},
                    name=f"task_{task_id}_1hr_before"
                )
                new_task['job_ids'].append(job_1hr_before.name)
                logger.info(f"Agendada notificação de 1hr antes para tarefa {task_id}.")


            # Agendar notificação de horário final
            if end_dt and end_dt > now:
                job_end_time = context.job_queue.run_once(
                    self._send_task_notification,
                    end_dt,
                    chat_id=self.chat_id,
                    data={'task_id': task_id, 'type': 'end_time'},
                    name=f"task_{task_id}_end"
                )
                new_task['job_ids'].append(job_end_time.name)
                logger.info(f"Agendada notificação de fim para tarefa {task_id} em {end_dt}.")


            del context.user_data['current_task_data']
            
            await self.start_agenda_main_menu(update, context) # Volta para o menu principal da agenda
            return AGENDA_MAIN_MENU
        except Exception as e:
            logger.error(f"Erro ao salvar e agendar tarefa para o usuário {update.effective_user.id}: {e}", exc_info=True)
            await update.message.reply_text("Ops! Ocorreu um erro ao salvar sua tarefa. Por favor, tente novamente.")
            return AGENDA_MAIN_MENU

    async def _send_task_notification(self, context: CallbackContext):
        try:
            job_data = context.job.data
            task_id = job_data['task_id']
            notification_type = job_data['type']
            chat_id = context.job.chat_id

            # É CRÍTICO que user_data seja acessado via context.application.user_data.get(chat_id)
            # quando a função é chamada pelo JobQueue, pois context.user_data não estará disponível
            # no mesmo contexto da conversa original.
            user_data_for_chat = context.application.user_data.get(chat_id, {})
            tasks = user_data_for_chat.get('tasks', [])
            
            task = next((t for t in tasks if t['id'] == task_id), None)

            if not task:
                logger.warning(f"Tentativa de notificar tarefa {task_id} para chat {chat_id}, mas tarefa não encontrada. Removendo job.")
                context.job.schedule_removal() # Remove o job se a tarefa não existe mais
                return
            
            if task['is_completed']:
                logger.info(f"Tentativa de notificar tarefa {task_id} (já concluída) para chat {chat_id}. Removendo job.")
                context.job.schedule_removal() # Remove o job se a tarefa já foi concluída
                return

            message = ""
            keyboard = None
            now = datetime.datetime.now(TIMEZONE)
            
            if notification_type == 'start_time':
                message = f"🔔 *Lembrete*: Sua tarefa '{task['title']}' está começando *AGORA*! 🚀"
                # Apenas pede feedback se não há end_time ou se end_time já passou
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
                logger.info(f"Notificação '{notification_type}' enviada para tarefa {task_id} no chat {chat_id}.")
                
                if keyboard and (notification_type == 'start_time' or notification_type == 'end_time'):
                    user_data_for_chat['current_task_id_for_feedback'] = task_id
            
            context.job.schedule_removal() # Remove o job após a notificação ser enviada
        except Exception as e:
            logger.error(f"Erro ao enviar notificação de tarefa (ID: {task_id}, Tipo: {notification_type}) para chat {chat_id}: {e}", exc_info=True)
            # Não é possível enviar mensagem para o usuário diretamente daqui, pois não há um `update`

    async def handle_task_completion(self, update: Update, context: CallbackContext):
        try:
            query = update.callback_query
            user_id = update.effective_user.id
            await query.answer() # Sempre responda ao callback query
            task_id = int(query.data.split('_')[-1])

            tasks = context.user_data.get('tasks', [])
            task = next((t for t in tasks if t['id'] == task_id), None)

            if task:
                if task['is_completed']:
                    await query.edit_message_text(f"✨ A tarefa *'{task['title']}'* já estava marcada como concluída!.", parse_mode="Markdown")
                    logger.info(f"Usuário {user_id} tentou concluir tarefa {task_id}, mas já estava concluída.")
                else:
                    task['is_completed'] = True
                    await query.edit_message_text(f"🎉 Ótimo! Tarefa *'{task['title']}'* marcada como concluída! Parabéns! 🥳", parse_mode="Markdown")
                    logger.info(f"Usuário {user_id} concluiu a tarefa {task_id}: '{task['title']}'.")

                    # Remove todos os jobs restantes para esta tarefa
                    for job_name in list(task['job_ids']): # Itera sobre uma cópia para permitir modificação
                        current_jobs = context.job_queue.get_jobs_by_name(job_name)
                        for job in current_jobs:
                            job.schedule_removal()
                            logger.info(f"Job '{job.name}' removido para tarefa {task_id}.")
                        task['job_ids'].remove(job_name) # Remove do array de job_ids

                # Limpa o ID da tarefa para feedback se for o caso
                if 'current_task_id_for_feedback' in context.user_data and context.user_data['current_task_id_for_feedback'] == task_id:
                    del context.user_data['current_task_id_for_feedback']
            else:
                await query.edit_message_text("❌ Desculpe, não encontrei esta tarefa para concluir ou ela já foi removida.")
                logger.warning(f"Usuário {user_id} tentou concluir tarefa {task_id}, mas não foi encontrada.")

            # Sempre retorna ao menu principal da agenda após a ação
            await self.start_agenda_main_menu(update, context)
            return AGENDA_MAIN_MENU
        except Exception as e:
            logger.error(f"Erro ao lidar com a conclusão da tarefa para o usuário {update.effective_user.id} (task_id: {task_id}): {e}", exc_info=True)
            if query:
                await query.message.reply_text("Ops! Ocorreu um erro ao processar a conclusão da sua tarefa. Por favor, tente novamente.")
            return AGENDA_MAIN_MENU

    async def handle_task_not_completed(self, update: Update, context: CallbackContext):
        try:
            query = update.callback_query
            user_id = update.effective_user.id
            await query.answer()
            task_id = int(query.data.split('_')[-1])

            tasks = context.user_data.get('tasks', [])
            task = next((t for t in tasks if t['id'] == task_id), None)

            if task:
                context.user_data['current_task_id_for_feedback'] = task_id
                await query.edit_message_text(
                    f"😔 Entendido. Por que você *não* conseguiu concluir a tarefa *'{task['title']}'*? (Digite o motivo ou 'ignorar')",
                    parse_mode="Markdown"
                )
                logger.info(f"Usuário {user_id} indicou não ter concluído a tarefa {task_id}. Solicitando motivo.")
                return TASK_COMPLETION_FEEDBACK
            else:
                await query.edit_message_text("❌ Desculpe, não encontrei esta tarefa.")
                logger.warning(f"Usuário {user_id} tentou marcar como não concluída tarefa {task_id}, mas não foi encontrada.")
                await self.start_agenda_main_menu(update, context)
                return AGENDA_MAIN_MENU
        except Exception as e:
            logger.error(f"Erro ao lidar com a não conclusão da tarefa para o usuário {update.effective_user.id} (task_id: {task_id}): {e}", exc_info=True)
            if query:
                await query.message.reply_text("Ops! Ocorreu um erro ao processar. Por favor, tente novamente.")
            return AGENDA_MAIN_MENU


    async def process_not_completed_reason(self, update: Update, context: CallbackContext):
        try:
            user_id = update.effective_user.id
            reason = update.message.text.strip()
            task_id = context.user_data.get('current_task_id_for_feedback')

            if task_id is None:
                logger.error(f"Erro: current_task_id_for_feedback ausente para o usuário {user_id} ao processar motivo.")
                await update.message.reply_text("🚨 Ocorreu um erro. Por favor, tente novamente no menu da Agenda.",
                                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Voltar à Agenda", callback_data="agenda_main_menu_return")]])
                )
                return AGENDA_MAIN_MENU

            tasks = context.user_data.get('tasks', [])
            task = next((t for t in tasks if t['id'] == task_id), None)

            if task:
                if reason.lower() != 'ignorar':
                    task['not_completed_reason'] = reason
                    await update.message.reply_text(f"📝 Motivo para *'{task['title']}'* registrado: _{reason}_. Foco na próxima! 💪", parse_mode="Markdown")
                    logger.info(f"Usuário {user_id} registrou motivo para tarefa {task_id}: '{reason}'.")
                else:
                    await update.message.reply_text(f"👍 Motivo para *'{task['title']}'* ignorado. Vamos em frente! ✨", parse_mode="Markdown")
                    logger.info(f"Usuário {user_id} ignorou motivo para tarefa {task_id}.")

                # Remove todos os jobs restantes para esta tarefa (mesmo se não concluída, para não notificar novamente)
                for job_name in list(task['job_ids']):
                    current_jobs = context.job_queue.get_jobs_by_name(job_name)
                    for job in current_jobs:
                        job.schedule_removal()
                        logger.info(f"Job '{job.name}' removido após feedback de não conclusão para tarefa {task_id}.")
                    task['job_ids'].remove(job_name)
            else:
                await update.message.reply_text("🚨 Ocorreu um erro ao processar o motivo. A tarefa não foi encontrada.")
                logger.warning(f"Usuário {user_id} tentou processar motivo para tarefa {task_id}, mas não foi encontrada.")

            del context.user_data['current_task_id_for_feedback']
            await self.start_agenda_main_menu(update, context) # Volta para o menu principal da agenda
            return AGENDA_MAIN_MENU
        except Exception as e:
            logger.error(f"Erro ao processar o motivo de não conclusão da tarefa para o usuário {update.effective_user.id} (task_id: {task_id}): {e}", exc_info=True)
            await update.message.reply_text("Ops! Ocorreu um erro ao registrar o motivo. Por favor, tente novamente.")
            return AGENDA_MAIN_MENU

    async def list_upcoming_tasks(self, update: Update, context: CallbackContext):
        try:
            query = update.callback_query
            user_id = update.effective_user.id
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
                        f"   _Em {task['start_datetime'].strftime('%d/%m/%Y')} às {time_info} "
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
            logger.info(f"Usuário {user_id} listou tarefas agendadas.")
            return MANAGE_TASKS_MENU # Retorna ao menu de gerenciamento
        except Exception as e:
            logger.error(f"Erro ao listar tarefas agendadas para o usuário {update.effective_user.id}: {e}", exc_info=True)
            if query:
                await query.message.reply_text("Ops! Ocorreu um erro ao listar suas tarefas agendadas. Por favor, tente novamente.")
            return MANAGE_TASKS_MENU

    async def list_completed_tasks(self, update: Update, context: CallbackContext):
        try:
            query = update.callback_query
            user_id = update.effective_user.id
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
                        f"   _Concluída em {task['start_datetime'].strftime('%d/%m/%Y')} às {time_info}_\n"
                    )
                    if 'not_completed_reason' in task and task['not_completed_reason']:
                         message_text += f"   _Motivo: {task['not_completed_reason']}_\n"
                    message_text += "\n"
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
            logger.info(f"Usuário {user_id} listou tarefas concluídas.")
            return MANAGE_TASKS_MENU # Retorna ao menu de gerenciamento
        except Exception as e:
            logger.error(f"Erro ao listar tarefas concluídas para o usuário {update.effective_user.id}: {e}", exc_info=True)
            if query:
                await query.message.reply_text("Ops! Ocorreu um erro ao listar suas tarefas concluídas. Por favor, tente novamente.")
            return MANAGE_TASKS_MENU

    async def initiate_delete_task(self, update: Update, context: CallbackContext):
        try:
            query = update.callback_query
            user_id = update.effective_user.id
            await query.answer("Escolha uma tarefa para apagar... 🗑️")
            tasks = context.user_data.get('tasks', [])
            
            # Filtra tarefas não concluídas e futuras ou passadas não concluídas para exclusão
            now = datetime.datetime.now(TIMEZONE)
            deletable_tasks = sorted([
                t for t in tasks
                # Permite apagar não concluídas (futuras ou passadas) ou concluídas (no passado)
                if not t['is_completed'] or (t['is_completed'] and t['start_datetime'] < now)
            ], key=lambda x: x['start_datetime'])

            if not deletable_tasks:
                await query.edit_message_text(
                    "Você não tem tarefas para apagar. ✨",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("↩️ Voltar ao Gerenciamento", callback_data="manage_tasks_return")],
                        [InlineKeyboardButton("⬅️ Voltar ao Menu Principal", callback_data="main_menu_return")]
                    ])
                )
                logger.info(f"Usuário {user_id} tentou iniciar exclusão, mas não há tarefas para apagar.")
                return MANAGE_TASKS_MENU
            
            message_text = "🗑️ *Selecione a tarefa que deseja apagar:*\n\n"
            keyboard_rows = []
            
            for i, task in enumerate(deletable_tasks):
                time_info = task['start_datetime'].strftime('%d/%m %H:%M')
                status_emoji = "✅" if task['is_completed'] else ("⏳" if task['start_datetime'] > now else "⚠️") # ⚠️ para tarefas atrasadas
                task_display = f"{status_emoji} {task['title']} ({time_info})"
                keyboard_rows.append([InlineKeyboardButton(task_display, callback_data=f"delete_task_id_{task['id']}")])
            
            keyboard_rows.append([InlineKeyboardButton("↩️ Voltar ao Gerenciamento", callback_data="manage_tasks_return")])
            keyboard_rows.append([InlineKeyboardButton("⬅️ Voltar ao Menu Principal", callback_data="main_menu_return")])

            await query.edit_message_text(
                text=message_text,
                reply_markup=InlineKeyboardMarkup(keyboard_rows),
                parse_mode="Markdown"
            )
            logger.info(f"Usuário {user_id} iniciou o processo de exclusão de tarefas.")
            return DELETE_TASK_SELECTION
        except Exception as e:
            logger.error(f"Erro ao iniciar exclusão de tarefa para o usuário {update.effective_user.id}: {e}", exc_info=True)
            if query:
                await query.message.reply_text("Ops! Ocorreu um erro ao preparar a exclusão de tarefas. Por favor, tente novamente.")
            return MANAGE_TASKS_MENU

    async def confirm_delete_task(self, update: Update, context: CallbackContext):
        try:
            query = update.callback_query
            user_id = update.effective_user.id
            await query.answer()
            task_id = int(query.data.split('_')[-1])

            tasks = context.user_data.get('tasks', [])
            task = next((t for t in tasks if t['id'] == task_id), None)

            if not task:
                await query.edit_message_text("❌ Desculpe, esta tarefa não foi encontrada ou já foi apagada.",
                                              reply_markup=InlineKeyboardMarkup([
                                                  [InlineKeyboardButton("↩️ Voltar ao Gerenciamento", callback_data="manage_tasks_return")]
                                              ]))
                logger.warning(f"Usuário {user_id} tentou confirmar exclusão da tarefa {task_id}, mas não foi encontrada.")
                return MANAGE_TASKS_MENU

            context.user_data['task_to_delete_id'] = task_id # Armazena o ID para confirmação

            message_text = f"Tem certeza que deseja apagar a tarefa:\n\n*'{task['title']}'* (ID: {task['id']})?"
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Sim, Apagar", callback_data=f"confirm_delete_yes_{task_id}")],
                [InlineKeyboardButton("❌ Não, Manter", callback_data=f"confirm_delete_no_{task_id}")]
            ])
            
            await query.edit_message_text(
                text=message_text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            logger.info(f"Usuário {user_id} solicitou confirmação para apagar tarefa {task_id}.")
            return CONFIRM_DELETE_TASK
        except Exception as e:
            logger.error(f"Erro ao confirmar exclusão de tarefa para o usuário {update.effective_user.id} (task_id: {task_id}): {e}", exc_info=True)
            if query:
                await query.message.reply_text("Ops! Ocorreu um erro ao confirmar a exclusão. Por favor, tente novamente.")
            return DELETE_TASK_SELECTION

    async def execute_delete_task(self, update: Update, context: CallbackContext):
        try:
            query = update.callback_query
            user_id = update.effective_user.id
            await query.answer()
            task_id_to_delete = int(query.data.split('_')[-1])

            # Opcional: Validar se o ID em query.data corresponde ao armazenado em context.user_data
            # if context.user_data.get('task_to_delete_id') != task_id_to_delete:
            #     await query.edit_message_text("🚨 Erro de segurança ou tarefa inválida. Por favor, tente novamente.")
            #     logger.error(f"Inconsistência no ID da tarefa para exclusão para o usuário {user_id}.")
            #     return await self.open_manage_tasks_menu(update, context)


            tasks = context.user_data.get('tasks', [])
            original_len = len(tasks)
            
            # Filtra a tarefa a ser removida
            tasks_after_delete = [t for t in tasks if t['id'] != task_id_to_delete]
            
            if len(tasks_after_delete) < original_len:
                # Remove os jobs agendados para a tarefa antes de removê-la da lista
                deleted_task = next((t for t in tasks if t['id'] == task_id_to_delete), None)
                if deleted_task:
                    for job_name in list(deleted_task['job_ids']):
                        current_jobs = context.job_queue.get_jobs_by_name(job_name)
                        for job in current_jobs:
                            job.schedule_removal()
                            logger.info(f"Job '{job.name}' removido para a tarefa {task_id_to_delete} durante a exclusão.")
                        deleted_task['job_ids'].remove(job_name) # Atualiza a lista de job_ids

                context.user_data['tasks'] = tasks_after_delete
                await query.edit_message_text(f"🗑️ Tarefa (ID: {task_id_to_delete}) apagada com sucesso!")
                logger.info(f"Usuário {user_id} apagou a tarefa {task_id_to_delete}.")
            else:
                await query.edit_message_text("❌ Tarefa não encontrada para apagar.")
                logger.warning(f"Usuário {user_id} tentou apagar tarefa {task_id_to_delete}, mas não foi encontrada na lista.")
            
            if 'task_to_delete_id' in context.user_data:
                del context.user_data['task_to_delete_id']

            await self.open_manage_tasks_menu(update, context) # Volta para o menu de gerenciamento de tarefas
            return MANAGE_TASKS_MENU
        except Exception as e:
            logger.error(f"Erro ao executar exclusão de tarefa para o usuário {update.effective_user.id} (task_id: {task_id_to_delete}): {e}", exc_info=True)
            if query:
                await query.message.reply_text("Ops! Ocorreu um erro inesperado ao apagar a tarefa. Por favor, tente novamente.")
            return MANAGE_TASKS_MENU # Tenta retornar a um estado seguro
