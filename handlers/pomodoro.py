import time
import threading
import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
)

class Pomodoro:
    # --- Conversation States for Pomodoro ---
    POMODORO_MENU_STATE = 0
    CONFIG_MENU_STATE = 1
    SET_FOCUS_TIME_STATE = 2
    SET_SHORT_BREAK_TIME_STATE = 3
    SET_LONG_BREAK_TIME_STATE = 4
    SET_CYCLES_STATE = 5

    # Intervalo para atualização da mensagem de status no Telegram (em segundos)
    ATUALIZACAO_STATUS_INTERVAL = 10 

    def __init__(self, bot=None, chat_id=None):
        self.foco_tempo = 25 * 60  # 25 minutes in seconds
        self.pausa_curta_tempo = 5 * 60  # 5 minutes in seconds
        self.pausa_longa_tempo = 15 * 60  # 15 minutes in seconds
        self.ciclos_para_pausa_longa = 4

        self.estado = "ocioso"  # States: "ocioso", "foco", "pausa_curta", "pausa_longa", "pausado"
        self.tempo_restante = 0
        self.ciclos_completados = 0  # Cycles completed in current session
        self.tipo_atual = None  # Current type: "foco", "pausa_curta", "pausa_longa"

        # History for final report (accumulates during the session)
        self.historico_foco_total = 0
        self.historico_pausa_curta_total = 0
        self.historico_pausa_longa_total = 0
        self.historico_ciclos_completados = 0

        self._timer_thread = None
        self._parar_temporizador = threading.Event()
        self._current_status_message_id = None  # Store message_id for status updates

        self.bot = bot # Bot instance from main.py
        self.chat_id = chat_id # Chat ID from main.py

    def _formatar_tempo(self, segundos):
        """Formats seconds into MM:SS."""
        min = segundos // 60
        sec = segundos % 60
        return f"{min:02d}:{sec:02d}"

    async def _rodar_temporizador(self, initial_message_id=None):
        """
        Internal function to manage the countdown.
        Runs in a separate thread.
        """
        self._parar_temporizador.clear() # Clear stop signal to start fresh

        self._current_status_message_id = initial_message_id # Set ID if passed

        last_update_time = time.time() # To control update frequency

        while self.tempo_restante > 0 and not self._parar_temporizador.is_set():
            # Update status message if a message ID is set and enough time has passed
            if self._current_status_message_id and (time.time() - last_update_time) >= self.ATUALIZACAO_STATUS_INTERVAL:
                try:
                    await self.bot.edit_message_text(
                        chat_id=self.chat_id,
                        message_id=self._current_status_message_id,
                        text=self.status(),
                        reply_markup=self._get_pomodoro_menu_keyboard(),
                        parse_mode='Markdown'
                    )
                    last_update_time = time.time() # Reset last update time
                except Exception as e:
                    # Catch "Message is not modified" or other errors if message was deleted/edited elsewhere
                    # print(f"Erro ao atualizar mensagem de status: {e}")
                    # If message no longer exists, clear ID to prevent further errors
                    if "message to edit not found" in str(e).lower() or "message is not modified" not in str(e):
                        self._current_status_message_id = None
                    pass # Just suppress the error, no need to stop the timer

            await asyncio.sleep(1) # Wait 1 second
            self.tempo_restante -= 1 # Decrement time

        if not self._parar_temporizador.is_set(): # If timer was not stopped manually
            # Send final status update before transitioning
            if self._current_status_message_id and self.bot and self.chat_id:
                try:
                    await self.bot.edit_message_text(
                        chat_id=self.chat_id,
                        message_id=self._current_status_message_id,
                        text=self.status(), # Show 00:00 or final status
                        reply_markup=self._get_pomodoro_menu_keyboard(),
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    pass # Ignore if message can't be updated at the very end
            
            await self._proximo_estado()
        # No else block here, as _parar_temporizador.set() is handled by the caller

    async def _proximo_estado(self):
        """Logic to transition to the next Pomodoro state (focus, short break, long break)."""
        msg_notificacao = ""

        if self.estado == "foco":
            self.historico_foco_total += self.foco_tempo
            self.ciclos_completados += 1
            self.historico_ciclos_completados += 1

            if self.ciclos_completados % self.ciclos_para_pausa_longa == 0:
                self.estado = "pausa_longa"
                self.tempo_restante = self.pausa_longa_tempo
                self.tipo_atual = "pausa_longa"
                msg_notificacao = "🎉 UAU! Hora da Pausa Longa! Respire fundo, você mereceu essa pausa! 🧘‍♀️"
            else:
                self.estado = "pausa_curta"
                self.tempo_restante = self.pausa_curta_tempo
                self.tipo_atual = "pausa_curta"
                msg_notificacao = "☕ Hora da Pausa Curta! Estique as pernas, tome uma água. Você está indo muito bem! ✨"

        elif self.estado in ["pausa_curta", "pausa_longa"]:
            if self.estado == "pausa_curta":
                self.historico_pausa_curta_total += self.pausa_curta_tempo
            else:
                self.historico_pausa_longa_total += self.pausa_longa_tempo

            self.estado = "foco"
            self.tempo_restante = self.foco_tempo
            self.tipo_atual = "foco"
            msg_notificacao = "🚀 De volta ao Foco! Vamos lá, a produtividade te espera! 💪"
        else: # Reset if in an unexpected state or stopping the last cycle
            self.estado = "ocioso"
            self.tempo_restante = 0
            self.tipo_atual = None
            msg_notificacao = "Pomodoro concluído! Pronto para o próximo ciclo? 🎉"


        if self.bot and self.chat_id and msg_notificacao:
            # Send the notification message
            await self.bot.send_message(self.chat_id, msg_notificacao)

            # If not going to ocioso, then start the next timer cycle and get its message_id
            if self.estado != "ocioso":
                # Send the initial status message for the next cycle
                status_msg = await self.bot.send_message(
                    self.chat_id, 
                    self.status(), 
                    reply_markup=self._get_pomodoro_menu_keyboard(), 
                    parse_mode='Markdown'
                )
                # Pass this message_id to the timer for updates
                self._current_status_message_id = status_msg.message_id
                
                if self.bot and hasattr(self.bot, 'loop'):
                    # Schedule _rodar_temporizador to run in the event loop
                    self._timer_thread = threading.Thread(
                        target=lambda: asyncio.run_coroutine_threadsafe(
                            self._rodar_temporizador(initial_message_id=self._current_status_message_id), self.bot.loop
                        ).result()
                    )
                    self._timer_thread.start()
                else:
                    print("ERRO: bot ou bot.loop não disponível para iniciar o temporizador. Falling back to ocioso.")
                    self.estado = "ocioso"
            else:
                self._current_status_message_id = None # No active timer, clear status ID

    async def iniciar(self):
        """Starts or resumes the Pomodoro timer."""
        # Ensure bot and chat_id are set (important for the first run)
        if not self.bot or not self.chat_id:
            return "Ops! O bot não foi inicializado corretamente para o Pomodoro. Tente novamente mais tarde. 😢"

        if self._timer_thread and self._timer_thread.is_alive():
            return "O Pomodoro já está rodando! Mantenha o foco. 🎯"

        response = ""
        initial_status_msg_text = ""

        if self.estado == "ocioso":
            self.estado = "foco"
            self.tempo_restante = self.foco_tempo
            self.tipo_atual = "foco"
            response = "🎉 Pomodoro iniciado! Hora de focar e brilhar! ✨"
            initial_status_msg_text = f"🌟 Iniciando seu período de {self.tipo_atual.capitalize()}! Tempo: {self._formatar_tempo(self.tempo_restante)} 🎉"
        elif self.estado == "pausado":
            response = "▶️ Pomodoro retomado! Vamos continuar firme! 💪"
            initial_status_msg_text = f"🚀 Retomando seu período de {self.tipo_atual.capitalize()}! Tempo restante: {self._formatar_tempo(self.tempo_restante)} ⏳"
        else:
            return "O Pomodoro já está em andamento. Use o botão 'Parar' para finalizar ou 'Pausar'. ⏯️"
        
        # Send initial status message and store its ID
        try:
            status_message = await self.bot.send_message(
                self.chat_id, 
                initial_status_msg_text,
                reply_markup=self._get_pomodoro_menu_keyboard(),
                parse_mode='Markdown'
            )
            self._current_status_message_id = status_message.message_id
        except Exception as e:
            print(f"Erro ao enviar mensagem inicial do Pomodoro: {e}")
            return "Ops! Não consegui enviar a mensagem inicial do Pomodoro. Tente novamente mais tarde. 😢"

        if self.bot and hasattr(self.bot, 'loop'):
            self._timer_thread = threading.Thread(
                target=lambda: asyncio.run_coroutine_threadsafe(
                    self._rodar_temporizador(initial_message_id=self._current_status_message_id), self.bot.loop
                ).result()
            )
            self._timer_thread.start()
            return response
        else:
            return "Ops! Não consegui iniciar o Pomodoro. Tente novamente mais tarde. 😢"

    async def pausar(self):
        """Pauses the Pomodoro timer."""
        if self.estado in ["foco", "pausa_curta", "pausa_longa"]:
            self._parar_temporizador.set()
            if self._timer_thread:
                self._timer_thread.join()
            self.estado = "pausado"
            # Keep _current_status_message_id so 'Status' button can update it
            return "⏸️ Pomodoro pausado. Você pode retomar a qualquer momento! 😌"
        elif self.estado == "pausado":
            return "O Pomodoro já está pausado. Que tal retomar? ▶️"
        else:
            return "Não há Pomodoro ativo para pausar. Que tal começar um? 🚀"

    async def parar(self):
        """Stops the Pomodoro timer, resets state, and generates a report."""
        if self.estado == "ocioso":
            return "Não há Pomodoro ativo para parar. Seu dia está livre! 🎉"

        self._parar_temporizador.set()
        if self._timer_thread and self._timer_thread.is_alive():
            self._timer_thread.join(timeout=2) # Wait a bit for thread to finish

        # Generate report before clearing history
        report = self.gerar_relatorio()
        
        # Reset state
        self.estado = "ocioso"
        self.tempo_restante = 0
        self.tipo_atual = None
        self.ciclos_completados = 0
        
        # Clear history after generating the report for the next full cycle
        self.historico_foco_total = 0
        self.historico_pausa_curta_total = 0
        self.historico_pausa_longa_total = 0
        self.historico_ciclos_completados = 0
        self._current_status_message_id = None # Clear status message ID on stop

        return "⏹️ Pomodoro parado! Aqui está o resumo da sua sessão:\n\n" + report + "\n\nInicie um novo ciclo quando estiver pronto para arrasar de novo! ✨"

    def status(self):
        """Returns the current status of the Pomodoro, including remaining time."""
        if self.estado == "ocioso":
            return "O Pomodoro está ocioso. Pronto para começar a focar? 🌟"
        elif self.estado == "pausado":
            return (f"Pomodoro pausado. Faltam *{self._formatar_tempo(self.tempo_restante)}* "
                    f"para o fim do seu período de *{self.tipo_atual.replace('_', ' ')}*. "
                    f"Ciclos de foco completos: *{self.ciclos_completados}*. Você está quase lá! ⏳")
        else:
            # Dynamic status update for active periods
            return (f"Status: *{self.estado.capitalize()}* | "
                    f"Tempo restante: *{self._formatar_tempo(self.tempo_restante)}* | "
                    f"Ciclos de foco completos: *{self.ciclos_completados}*. Continue firme! 🔥")

    async def configurar(self, tipo_config, valor):
        """Allows configuring Pomodoro times."""
        if self.estado != "ocioso":
            return False, "Ops! Não é possível configurar enquanto o Pomodoro está ativo ou pausado. Por favor, pare-o primeiro. 🛑"

        if not isinstance(valor, int) or valor <= 0:
            return False, "Por favor, insira um número inteiro positivo! 🙏"

        if tipo_config == "foco":
            self.foco_tempo = valor * 60
        elif tipo_config == "pausa_curta":
            self.pausa_curta_tempo = valor * 60
        elif tipo_config == "pausa_longa":
            self.pausa_longa_tempo = valor * 60
        elif tipo_config == "ciclos":
            self.ciclos_para_pausa_longa = valor
        else:
            return False, "Tipo de configuração desconhecido. 😕"
        
        return True, (f"✨ Configuração de *{tipo_config.replace('_', ' ').capitalize()}* "
                      f"atualizada para *{valor} min* (ou ciclos)! Perfeito! ✅")

    def get_config_status(self):
        """Returns the current Pomodoro configurations formatted."""
        return (f"Configurações atuais do seu Pomodoro:\n"
                f"🍅 *Foco:* {self.foco_tempo // 60} min\n"
                f"☕ *Pausa Curta:* {self.pausa_curta_tempo // 60} min\n"
                f"🛋️ *Pausa Longa:* {self.pausa_longa_tempo // 60} min\n"
                f"🔄 *Ciclos para Pausa Longa:* {self.ciclos_para_pausa_longa}")

    def gerar_relatorio(self):
        """Calculates and returns the final report of focus time, breaks, and cycles."""
        total_foco_min = self.historico_foco_total // 60
        total_pausa_curta_min = self.historico_pausa_curta_total // 60
        total_pausa_longa_min = self.historico_pausa_longa_total // 60
        
        total_geral_min = total_foco_min + total_pausa_curta_min + total_pausa_longa_min
        
        horas_foco = total_foco_min // 60
        min_foco = total_foco_min % 60
        
        horas_pausa_curta = total_pausa_curta_min // 60
        min_pausa_curta = total_pausa_curta_min % 60

        horas_pausa_longa = total_pausa_longa_min // 60
        min_pausa_longa = total_pausa_longa_min % 60

        horas_geral = total_geral_min // 60
        min_geral = total_geral_min % 60

        # Ensure the report always shows something, even if zero
        if self.historico_foco_total == 0 and self.historico_pausa_curta_total == 0 and \
           self.historico_pausa_longa_total == 0 and self.historico_ciclos_completados == 0:
            return "Parece que você ainda não completou nenhum ciclo ou período de foco. Que tal começar um? 🚀"


        relatorio = (f"--- 📊 Relatório da Sua Sessão de Produtividade! ---\n"
                     f"**Foco total:** {horas_foco}h {min_foco}min 🧠\n"
                     f"**Pausa Curta total:** {horas_pausa_curta}h {min_pausa_curta}min ☕\n"
                     f"**Pausa Longa total:** {horas_pausa_longa}h {min_pausa_longa}min 🧘‍♀️\n"
                     f"**Ciclos de foco completos:** {self.historico_ciclos_completados} 🏆\n"
                     f"**Tempo total da sessão:** {horas_geral}h {min_geral}min ✅")
        return relatorio

    # --- Methods to Generate Inline Button Menus ---

    def _get_pomodoro_menu_keyboard(self):
        """Returns the inline keyboard for the main Pomodoro menu."""
        keyboard = [
            [InlineKeyboardButton("▶️ Iniciar", callback_data="pomodoro_iniciar"),
             InlineKeyboardButton("⏸️ Pausar", callback_data="pomodoro_pausar")],
            [InlineKeyboardButton("⏹️ Parar", callback_data="pomodoro_parar"),
             InlineKeyboardButton("📊 Status", callback_data="pomodoro_status")],
            [InlineKeyboardButton("⚙️ Configurar", callback_data="pomodoro_configurar")],
            [InlineKeyboardButton("⬅️ Voltar ao Início", callback_data="main_menu_return")],
        ]
        return InlineKeyboardMarkup(keyboard)

    def _get_config_menu_keyboard(self):
        """Returns the inline keyboard for the Pomodoro configuration menu."""
        keyboard = [
            [InlineKeyboardButton("Foco", callback_data="config_foco"),
             InlineKeyboardButton("Pausa Curta", callback_data="config_pausa_curta")],
            [InlineKeyboardButton("Pausa Longa", callback_data="config_pausa_longa"),
             InlineKeyboardButton("Ciclos", callback_data="config_ciclos")],
            [InlineKeyboardButton("⬅️ Voltar ao Pomodoro", callback_data="pomodoro_menu")],
        ]
        return InlineKeyboardMarkup(keyboard)

    # --- Pomodoro Callback Handlers ---

    async def _show_pomodoro_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Displays the main Pomodoro menu."""
        query = update.callback_query
        # Ensure bot and chat_id are updated for this specific user's Pomodoro instance
        user_id = update.effective_user.id
        if user_id in user_pomodoros:
            user_pomodoros[user_id].bot = context.bot
            user_pomodoros[user_id].chat_id = update.effective_chat.id

        await query.edit_message_text(
            "Bem-vindo ao seu assistente Pomodoro! 🍅 Escolha uma ação e vamos ser produtivos! ✨",
            reply_markup=self._get_pomodoro_menu_keyboard()
        )
        # Clear status message ID when returning to main menu
        self._current_status_message_id = None
        return self.POMODORO_MENU_STATE

    async def _pomodoro_iniciar_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for the 'Start' button."""
        query = update.callback_query
        await query.answer()
        # Ensure bot and chat_id are correctly set here as well, although already done in open_pomodoro_menu
        self.bot = context.bot
        self.chat_id = update.effective_chat.id

        response = await self.iniciar()
        # The 'iniciar' method now sends the initial status message. 
        # Here we just update the original menu message.
        await query.edit_message_text(
            response, 
            reply_markup=self._get_pomodoro_menu_keyboard(), 
            parse_mode='Markdown'
        )
        return self.POMODORO_MENU_STATE

    async def _pomodoro_pausar_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for the 'Pause' button."""
        query = update.callback_query
        await query.answer()
        response = await self.pausar()
        await query.edit_message_text(response, reply_markup=self._get_pomodoro_menu_keyboard(), parse_mode='Markdown')
        return self.POMODORO_MENU_STATE

    async def _pomodoro_parar_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for the 'Stop' button and report display."""
        query = update.callback_query
        await query.answer()
        response = await self.parar()
        await query.edit_message_text(response, parse_mode='Markdown', reply_markup=self._get_pomodoro_menu_keyboard())
        return self.POMODORO_MENU_STATE

    async def _pomodoro_status_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for the 'Status' button. Updates with real-time countdown."""
        query = update.callback_query
        await query.answer("Atualizando status...") # Provide immediate feedback
        
        response = self.status()
        
        try:
            message = await query.edit_message_text(
                response,
                reply_markup=self._get_pomodoro_menu_keyboard(),
                parse_mode='Markdown'
            )
            # Only set _current_status_message_id if the timer is actually running
            if self.estado in ["foco", "pausa_curta", "pausa_longa"]:
                self._current_status_message_id = message.message_id
            else:
                self._current_status_message_id = None # Clear if not running
        except Exception as e:
            if "Message is not modified" not in str(e): 
                new_message = await query.message.reply_text(
                    "Não consegui atualizar a mensagem anterior. Aqui está o novo status:\n" + response,
                    reply_markup=self._get_pomodoro_menu_keyboard(),
                    parse_mode='Markdown'
                )
                if self.estado in ["foco", "pausa_curta", "pausa_longa"]:
                    self._current_status_message_id = new_message.message_id
                else:
                    self._current_status_message_id = None
            else:
                pass # If it's just "not modified", keep the current ID and the timer will keep trying. 

        return self.POMODORO_MENU_STATE

    async def _show_config_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for the 'Configure' button, showing the configuration menu."""
        query = update.callback_query
        await query.answer()
        current_config = self.get_config_status()
        await query.edit_message_text(
            f"⚙️ Configurar Pomodoro:\n{current_config}\n\nEscolha o que deseja alterar: ✨",
            reply_markup=self._get_config_menu_keyboard(), parse_mode='Markdown'
        )
        return self.CONFIG_MENU_STATE

    async def _request_config_value(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Requests the user to send the new value for the selected configuration."""
        query = update.callback_query
        await query.answer()
        config_type = query.data.replace("config_", "")
        context.user_data['config_type'] = config_type
        
        prompt_text = (f"Por favor, envie o novo valor (número inteiro em minutos) "
                       f"para '{config_type.replace('_', ' ').capitalize()}': 🔢")
        await query.edit_message_text(prompt_text)
        
        if config_type == "foco":
            return self.SET_FOCUS_TIME_STATE
        elif config_type == "pausa_curta":
            return self.SET_SHORT_BREAK_TIME_STATE
        elif config_type == "pausa_longa":
            return self.SET_LONG_BREAK_TIME_STATE
        elif config_type == "ciclos":
            return self.SET_CYCLES_STATE

    async def _set_config_value(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Receives the configuration value typed by the user and applies it."""
        config_type = context.user_data.get('config_type')
        
        if not config_type:
            await update.message.reply_text("Ops! O tipo de configuração não foi encontrado. Tente novamente! 🤔", reply_markup=self._get_pomodoro_menu_keyboard())
            return self.POMODORO_MENU_STATE

        try:
            value = int(update.message.text)
            success, message = await self.configurar(config_type, value)
            if success:
                await update.message.reply_text(message, reply_markup=self._get_config_menu_keyboard(), parse_mode='Markdown')
            else:
                await update.message.reply_text(message, reply_markup=self._get_config_menu_keyboard())
        except ValueError:
            await update.message.reply_text("Isso não parece um número válido! Por favor, envie um número inteiro. 🔢", reply_markup=self._get_config_menu_keyboard())
        except Exception as e:
            await update.message.reply_text(f"Ocorreu um erro ao configurar: {e}. Por favor, tente novamente! 😥", reply_markup=self._get_config_menu_keyboard())
        
        if 'config_type' in context.user_data:
            del context.user_data['config_type']
        
        return self.CONFIG_MENU_STATE

    async def _exit_pomodoro_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for the 'Back to Start' button."""
        query = update.callback_query
        await query.answer("Saindo do Pomodoro. Voltando ao menu principal! 👋")
        self._current_status_message_id = None
        return ConversationHandler.END 

    # --- Method to Get the Pomodoro ConversationHandler ---

    def get_pomodoro_conversation_handler(self):
        """
        Returns the complete ConversationHandler for the Pomodoro functionality.
        This handler will be nested in the bot's main ConversationHandler.
        """
        return ConversationHandler(
            entry_points=[CallbackQueryHandler(self._show_pomodoro_menu, pattern="^open_pomodoro_menu$")],
            states={
                self.POMODORO_MENU_STATE: [
                    CallbackQueryHandler(self._pomodoro_iniciar_callback, pattern="^pomodoro_iniciar$"),
                    CallbackQueryHandler(self._pomodoro_pausar_callback, pattern="^pomodoro_pausar$"),
                    CallbackQueryHandler(self._pomodoro_parar_callback, pattern="^pomodoro_parar$"),
                    CallbackQueryHandler(self._pomodoro_status_callback, pattern="^pomodoro_status$"),
                    CallbackQueryHandler(self._show_config_menu, pattern="^pomodoro_configurar$"),
                    CallbackQueryHandler(self._exit_pomodoro_conversation, pattern="^main_menu_return$"),
                ],
                self.CONFIG_MENU_STATE: [
                    CallbackQueryHandler(self._request_config_value, pattern="^config_foco$"),
                    CallbackQueryHandler(self._request_config_value, pattern="^config_pausa_curta$"),
                    CallbackQueryHandler(self._request_config_value, pattern="^config_pausa_longa$"),
                    CallbackQueryHandler(self._request_config_value, pattern="^config_ciclos$"),
                    CallbackQueryHandler(self._show_pomodoro_menu, pattern="^pomodoro_menu$"),
                ],
                self.SET_FOCUS_TIME_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._set_config_value)],
                self.SET_SHORT_BREAK_TIME_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._set_config_value)],
                self.SET_LONG_BREAK_TIME_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._set_config_value)],
                self.SET_CYCLES_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._set_config_value)],
            },
            fallbacks=[
                MessageHandler(filters.ALL & ~filters.COMMAND, self._fallback_pomodoro_message),
            ],
            map_to_parent={
                ConversationHandler.END: ConversationHandler.END, 
            },
        )

    async def _fallback_pomodoro_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handles unexpected text messages within the Pomodoro flow."""
        if update.message:
            await update.message.reply_text(
                "Desculpe, não entendi. Por favor, use os botões ou siga as instruções. 🤷‍♀️",
                reply_markup=self._get_pomodoro_menu_keyboard()
            )
        elif update.callback_query:
            await update.callback_query.answer("Ação inválida para este momento. Por favor, use os botões! 🚫")
            await update.callback_query.edit_message_text(
                "Ação inválida. Escolha uma opção:",
                reply_markup=self._get_pomodoro_menu_keyboard()
            )
        # Clear status message ID on unexpected input to prevent issues
        self._current_status_message_id = None 
        return self.POMODORO_MENU_STATE
