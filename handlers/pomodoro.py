# handlers/pomodoro.py
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
    # --- Estados da Conversa para o Pomodoro ---
    # Estes estados são específicos para a conversa do Pomodoro
    # Usamos constantes de classe para evitar duplicidade
    POMODORO_MENU_STATE = 0
    CONFIG_MENU_STATE = 1
    SET_FOCUS_TIME_STATE = 2
    SET_SHORT_BREAK_TIME_STATE = 3
    SET_LONG_BREAK_TIME_STATE = 4
    SET_CYCLES_STATE = 5

    def __init__(self, bot=None, chat_id=None):
        # Configurações padrão
        self.foco_tempo = 25 * 60  # 25 minutos em segundos
        self.pausa_curta_tempo = 5 * 60 # 5 minutos em segundos
        self.pausa_longa_tempo = 15 * 60 # 15 minutos em segundos
        self.ciclos_para_pausa_longa = 4

        # Estado atual do Pomodoro
        self.estado = "ocioso" # Pode ser: "ocioso", "foco", "pausa_curta", "pausa_longa", "pausado"
        self.tempo_restante = 0
        self.ciclos_completados = 0
        self.tipo_atual = None # Pode ser: "foco", "pausa_curta", "pausa_longa"

        # Histórico de tempos (para o relatório final)
        self.historico_foco_total = 0
        self.historico_pausa_curta_total = 0
        self.historico_pausa_longa_total = 0
        self.historico_ciclos_completados = 0

        self._timer_thread = None # Objeto da thread do temporizador
        self._parar_temporizador = threading.Event() # Sinal para parar a thread

        # Adicionados para o bot do Telegram
        self.bot = bot # O objeto `bot` é necessário para enviar mensagens
        self.chat_id = chat_id # O `chat_id` para onde enviar as mensagens

    def _formatar_tempo(self, segundos):
        min = segundos // 60
        sec = segundos % 60
        return f"{min:02d}:{sec:02d}"

    async def _rodar_temporizador(self):
        """
        Função interna que realmente conta o tempo.
        Rodará em uma thread separada para não bloquear o bot.
        """
        self._parar_temporizador.clear()
        
        # Envia uma mensagem inicial para o usuário (apenas no início de um ciclo)
        if self.bot and self.chat_id and self.estado != "pausado": # Não envia se estiver retomando de uma pausa
            await self.bot.send_message(self.chat_id, f"Iniciando {self.tipo_atual.capitalize()}! Tempo: {self._formatar_tempo(self.tempo_restante)}")

        while self.tempo_restante > 0 and not self._parar_temporizador.is_set():
            time.sleep(1)
            self.tempo_restante -= 1

        if not self._parar_temporizador.is_set(): # Se o temporizador não foi parado manualmente
            await self._proximo_estado()

    async def _proximo_estado(self):
        """
        Lógica para transicionar para o próximo estado (foco, pausa curta, pausa longa).
        """
        msg_notificacao = ""

        if self.estado == "foco":
            self.historico_foco_total += self.foco_tempo
            self.ciclos_completados += 1
            self.historico_ciclos_completados += 1

            if self.ciclos_completados % self.ciclos_para_pausa_longa == 0:
                self.estado = "pausa_longa"
                self.tempo_restante = self.pausa_longa_tempo
                self.tipo_atual = "pausa_longa"
                msg_notificacao = "🎉 Hora da Pausa Longa! Respire fundo e relaxe."
            else:
                self.estado = "pausa_curta"
                self.tempo_restante = self.pausa_curta_tempo
                self.tipo_atual = "pausa_curta"
                msg_notificacao = "☕ Hora da Pausa Curta! Estique as pernas."

        elif self.estado in ["pausa_curta", "pausa_longa"]:
            if self.estado == "pausa_curta":
                self.historico_pausa_curta_total += self.pausa_curta_tempo
            else:
                self.historico_pausa_longa_total += self.pausa_longa_tempo

            self.estado = "foco"
            self.tempo_restante = self.foco_tempo
            self.tipo_atual = "foco"
            msg_notificacao = "🚀 De volta ao Foco! Vamos lá!"
        else:
            self.estado = "ocioso"
            self.tempo_restante = 0
            self.tipo_atual = None

        if self.bot and self.chat_id and msg_notificacao:
            await self.bot.send_message(self.chat_id, msg_notificacao)

        if self.estado != "ocioso":
            # Usamos lambda e asyncio.run_coroutine_threadsafe para agendar a corrotina no loop de eventos do bot
            self._timer_thread = threading.Thread(target=lambda: asyncio.run_coroutine_threadsafe(self._rodar_temporizador(), self.bot.loop))
            self._timer_thread.start()

    async def iniciar(self):
        """Inicia ou retoma o temporizador Pomodoro."""
        if self._timer_thread and self._timer_thread.is_alive():
            return "O Pomodoro já está rodando!"

        if self.estado == "ocioso" or self.estado == "pausado":
            if self.estado == "ocioso":
                self.estado = "foco"
                self.tempo_restante = self.foco_tempo
                self.tipo_atual = "foco"
                response = "Pomodoro iniciado! Hora de focar!"
            elif self.estado == "pausado":
                response = "Pomodoro retomado!"

            self._timer_thread = threading.Thread(target=lambda: asyncio.run_coroutine_threadsafe(self._rodar_temporizador(), self.bot.loop))
            self._timer_thread.start()
            return response
        else:
            return "O Pomodoro já está em andamento. Use o botão 'Parar' para finalizar ou 'Pausar'."

    async def pausar(self):
        """Pausa o temporizador Pomodoro."""
        if self.estado in ["foco", "pausa_curta", "pausa_longa"]:
            self._parar_temporizador.set()
            if self._timer_thread:
                self._timer_thread.join()
            self.estado = "pausado"
            return "Pomodoro pausado."
        elif self.estado == "pausado":
            return "O Pomodoro já está pausado."
        else:
            return "Não há Pomodoro ativo para pausar."

    async def parar(self):
        """Para o temporizador Pomodoro e reseta tudo, gerando um relatório."""
        if self.estado == "ocioso":
            return "Não há Pomodoro ativo para parar."

        self._parar_temporizador.set()
        if self._timer_thread:
            self._timer_thread.join()

        # Reseta o estado
        self.estado = "ocioso"
        self.tempo_restante = 0
        self.tipo_atual = None
        self.ciclos_completados = 0

        # Gera o relatório
        report = self.gerar_relatorio()
        
        # Limpa o histórico após gerar o relatório para o próximo ciclo de uso
        self.historico_foco_total = 0
        self.historico_pausa_curta_total = 0
        self.historico_pausa_longa_total = 0
        self.historico_ciclos_completados = 0

        return "Pomodoro parado e relatório gerado:\n" + report

    def status(self):
        """Retorna o status atual do Pomodoro."""
        if self.estado == "ocioso":
            return "O Pomodoro está ocioso. Use o botão 'Iniciar' para começar."
        elif self.estado == "pausado":
            return f"Pomodoro pausado. Faltam {self._formatar_tempo(self.tempo_restante)} para o fim do {self.tipo_atual}. Ciclos de foco completos: {self.ciclos_completados}"
        else:
            return (f"Status: {self.estado.capitalize()} | "
                    f"Tempo restante: {self._formatar_tempo(self.tempo_restante)} | "
                    f"Ciclos de foco completos: {self.ciclos_completados}")

    async def configurar(self, tipo_config, valor):
        """
        Permite configurar os tempos do Pomodoro.
        Retorna uma tupla (sucesso_bool, mensagem)
        """
        if self.estado != "ocioso":
            return False, "Não é possível configurar enquanto o Pomodoro está ativo ou pausado. Por favor, pare-o primeiro."

        if valor <= 0:
            return False, "O valor deve ser um número inteiro positivo."

        if tipo_config == "foco":
            self.foco_tempo = valor * 60
        elif tipo_config == "pausa_curta":
            self.pausa_curta_tempo = valor * 60
        elif tipo_config == "pausa_longa":
            self.pausa_longa_tempo = valor * 60
        elif tipo_config == "ciclos":
            self.ciclos_para_pausa_longa = valor
        else:
            return False, "Tipo de configuração desconhecido."
        
        return True, (f"Configuração de {tipo_config.replace('_', ' ').capitalize()} atualizada para {valor} min (ou ciclos).")

    def get_config_status(self):
        """Retorna as configurações atuais do Pomodoro."""
        return (f"Configurações atuais:\n"
                f"Foco: {self.foco_tempo // 60} min\n"
                f"Pausa Curta: {self.pausa_curta_tempo // 60} min\n"
                f"Pausa Longa: {self.pausa_longa_tempo // 60} min\n"
                f"Ciclos para Pausa Longa: {self.ciclos_para_pausa_longa}")

    def gerar_relatorio(self):
        """
        Calcula e retorna o relatório final do tempo de foco, pausas e ciclos.
        """
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

        relatorio = (f"--- Relatório do Pomodoro ---\n"
                     f"**Foco total:** {horas_foco}h {min_foco}min\n"
                     f"**Pausa Curta total:** {horas_pausa_curta}h {min_pausa_curta}min\n"
                     f"**Pausa Longa total:** {horas_pausa_longa}h {min_pausa_longa}min\n"
                     f"**Ciclos de foco completos:** {self.historico_ciclos_completados}\n"
                     f"**Tempo total da sessão:** {horas_geral}h {min_geral}min")
        return relatorio

    # --- Métodos para Gerar Menus de Botões Inline ---

    def _get_pomodoro_menu_keyboard(self):
        keyboard = [
            [InlineKeyboardButton("▶️ Iniciar", callback_data="pomodoro_iniciar"),
             InlineKeyboardButton("⏸️ Pausar", callback_data="pomodoro_pausar")],
            [InlineKeyboardButton("⏹️ Parar", callback_data="pomodoro_parar"),
             InlineKeyboardButton("📊 Status", callback_data="pomodoro_status")],
            [InlineKeyboardButton("⚙️ Configurar", callback_data="pomodoro_configurar")],
            [InlineKeyboardButton("⬅️ Voltar ao Início", callback_data="main_menu_return")], # Novo callback para retornar
        ]
        return InlineKeyboardMarkup(keyboard)

    def _get_config_menu_keyboard(self):
        keyboard = [
            [InlineKeyboardButton("Foco", callback_data="config_foco"),
             InlineKeyboardButton("Pausa Curta", callback_data="config_pausa_curta")],
            [InlineKeyboardButton("Pausa Longa", callback_data="config_pausa_longa"),
             InlineKeyboardButton("Ciclos", callback_data="config_ciclos")],
            [InlineKeyboardButton("⬅️ Voltar ao Pomodoro", callback_data="pomodoro_menu")], # Retorna para o menu principal do pomodoro
        ]
        return InlineKeyboardMarkup(keyboard)

    # --- Handlers de Callbacks do Pomodoro (AGORA DENTRO DA CLASSE!) ---

    async def _show_pomodoro_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Mostra o menu do Pomodoro."""
        query = update.callback_query
        # await query.answer() # Já é respondido pelo open_pomodoro_menu no main.py, pode ser removido aqui
        await query.edit_message_text(
            "Bem-vindo ao Pomodoro! Escolha uma ação:",
            reply_markup=self._get_pomodoro_menu_keyboard()
        )
        return self.POMODORO_MENU_STATE

    async def _pomodoro_iniciar_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Inicia o Pomodoro via botão."""
        query = update.callback_query
        await query.answer()
        response = await self.iniciar()
        await query.edit_message_text(response, reply_markup=self._get_pomodoro_menu_keyboard())
        return self.POMODORO_MENU_STATE

    async def _pomodoro_pausar_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Pausa o Pomodoro via botão."""
        query = update.callback_query
        await query.answer()
        response = await self.pausar()
        await query.edit_message_text(response, reply_markup=self._get_pomodoro_menu_keyboard())
        return self.POMODORO_MENU_STATE

    async def _pomodoro_parar_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Para o Pomodoro via botão e mostra o relatório."""
        query = update.callback_query
        await query.answer()
        response = await self.parar()
        await query.edit_message_text(response, parse_mode='Markdown', reply_markup=self._get_pomodoro_menu_keyboard())
        return self.POMODORO_MENU_STATE

    async def _pomodoro_status_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Mostra o status do Pomodoro via botão."""
        query = update.callback_query
        await query.answer()
        response = self.status()
        await query.edit_message_text(response, reply_markup=self._get_pomodoro_menu_keyboard())
        return self.POMODORO_MENU_STATE

    async def _show_config_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Mostra o menu de configuração do Pomodoro."""
        query = update.callback_query
        await query.answer()
        current_config = self.get_config_status()
        await query.edit_message_text(
            f"Configurar Pomodoro:\n{current_config}\n\nEscolha o que deseja alterar:",
            reply_markup=self._get_config_menu_keyboard()
        )
        return self.CONFIG_MENU_STATE

    async def _request_config_value(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Solicita ao usuário o valor para a configuração selecionada."""
        query = update.callback_query
        await query.answer()
        config_type = query.data.replace("config_", "") # Ex: "foco", "pausa_curta"
        context.user_data['config_type'] = config_type # Armazena o tipo de config no user_data
        
        prompt_text = f"Por favor, envie o novo valor (número inteiro) para '{config_type.replace('_', ' ').capitalize()}':"
        await query.edit_message_text(prompt_text)

        # Retorna o estado apropriado para esperar a mensagem do usuário
        if config_type == "foco":
            return self.SET_FOCUS_TIME_STATE
        elif config_type == "pausa_curta":
            return self.SET_SHORT_BREAK_TIME_STATE
        elif config_type == "pausa_longa":
            return self.SET_LONG_BREAK_TIME_STATE
        elif config_type == "ciclos":
            return self.SET_CYCLES_STATE
        else:
            # Fallback em caso de tipo desconhecido, embora os patterns de callback evitem isso
            await query.edit_message_text("Erro interno: Tipo de configuração desconhecido.", reply_markup=self._get_config_menu_keyboard())
            return self.CONFIG_MENU_STATE


    async def _set_config_value(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Recebe o valor da configuração e o aplica."""
        config_type = context.user_data.get('config_type')
        
        if not config_type:
            await update.message.reply_text("Erro: Tipo de configuração não encontrado. Por favor, tente novamente.", reply_markup=self._get_pomodoro_menu_keyboard())
            return self.POMODORO_MENU_STATE # Volta para o menu do pomodoro

        try:
            value = int(update.message.text)
            success, message = await self.configurar(config_type, value)
            if success:
                await update.message.reply_text(message, reply_markup=self._get_config_menu_keyboard())
            else:
                await update.message.reply_text(message, reply_markup=self._get_config_menu_keyboard())
        except ValueError:
            await update.message.reply_text("Valor inválido. Por favor, envie um número inteiro.", reply_markup=self._get_config_menu_keyboard())
        except Exception as e:
            await update.message.reply_text(f"Ocorreu um erro ao configurar: {e}", reply_markup=self._get_config_menu_keyboard())
        
        # Limpa o tipo de configuração do user_data
        if 'config_type' in context.user_data:
            del context.user_data['config_type']
        
        return self.CONFIG_MENU_STATE

    async def _exit_pomodoro_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Este handler é acionado pelo botão 'Voltar ao Início' dentro do menu Pomodoro.
        Ele sinaliza ao ConversationHandler pai que a sub-conversa do Pomodoro terminou.
        """
        query = update.callback_query
        await query.answer()
        # Não edita a mensagem aqui, pois o handler no main.py fará isso
        # ou retornará ao menu principal.
        
        # O retorno é ConversationHandler.END para este ConversationHandler aninhado,
        # sinalizando que a conversa do Pomodoro terminou.
        return ConversationHandler.END 

    # --- Método para Obter o ConversationHandler do Pomodoro ---

    def get_pomodoro_conversation_handler(self):
        """
        Retorna o ConversationHandler completo para a funcionalidade Pomodoro.
        Este handler será aninhado no ConversationHandler principal do bot.
        """
        return ConversationHandler(
            # O entry_point para este ConversationHandler aninhado é o clique no botão "Pomodoro"
            # do menu principal. O 'open_pomodoro_menu' em main.py direciona para cá.
            # Adicionamos per_message=False para suprimir o aviso PTBUserWarning.
            entry_points=[CallbackQueryHandler(self._show_pomodoro_menu, pattern="^open_pomodoro_menu$", per_message=False)],
            states={
                self.POMODORO_MENU_STATE: [
                    CallbackQueryHandler(self._pomodoro_iniciar_callback, pattern="^pomodoro_iniciar$"),
                    CallbackQueryHandler(self._pomodoro_pausar_callback, pattern="^pomodoro_pausar$"),
                    CallbackQueryHandler(self._pomodoro_parar_callback, pattern="^pomodoro_parar$"),
                    CallbackQueryHandler(self._pomodoro_status_callback, pattern="^pomodoro_status$"),
                    CallbackQueryHandler(self._show_config_menu, pattern="^pomodoro_configurar$"),
                    CallbackQueryHandler(self._exit_pomodoro_conversation, pattern="^main_menu_return$"), # Sair desta conversa
                ],
                self.CONFIG_MENU_STATE: [
                    CallbackQueryHandler(self._request_config_value, pattern="^config_foco$"),
                    CallbackQueryHandler(self._request_config_value, pattern="^config_pausa_curta$"),
                    CallbackQueryHandler(self._request_config_value, pattern="^config_pausa_longa$"),
                    CallbackQueryHandler(self._request_config_value, pattern="^config_ciclos$"),
                    CallbackQueryHandler(self._show_pomodoro_menu, pattern="^pomodoro_menu$"), # Botão de voltar
                ],
                self.SET_FOCUS_TIME_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._set_config_value)],
                self.SET_SHORT_BREAK_TIME_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._set_config_value)],
                self.SET_LONG_BREAK_TIME_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._set_config_value)],
                self.SET_CYCLES_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._set_config_value)],
            },
            fallbacks=[
                MessageHandler(filters.ALL, self._fallback_pomodoro_message),
            ],
            # map_to_parent define o que acontece no ConversationHandler pai quando este ConversationHandler aninhado termina.
            # Aqui, quando _exit_pomodoro_conversation retorna ConversationHandler.END, o pai (main.py)
            # retornará ao MAIN_MENU_STATE.
            map_to_parent={
                ConversationHandler.END: self.POMODORO_MENU_STATE, # Use um estado que faça sentido no MAIN_MENU_STATE para reentrar
            },
            # per_user=True é o padrão e é o que queremos aqui.
            # per_chat=True, per_message=True são padrões para MessageHandler e CommandHandler,
            # mas CallbackQueryHandler tem per_message=False por padrão.
            # AVISO: A linha 396 do erro se refere ao CallbackQueryHandler no entry_points.
            # Adicionar `per_message=False` ao CallbackQueryHandler do entry_points pode remover o aviso.
        )

    async def _fallback_pomodoro_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Trata mensagens de texto inesperadas dentro do fluxo Pomodoro."""
        if update.message:
            await update.message.reply_text(
                "Desculpe, não entendi. Por favor, use os botões ou siga as instruções para configurar.",
                reply_markup=self._get_pomodoro_menu_keyboard() # Volta para o menu principal do Pomodoro
            )
        elif update.callback_query:
            await update.callback_query.answer("Ação inválida para este momento.")
            # Opcional: tentar editar a mensagem do callback_query para mostrar o menu do Pomodoro
            await update.callback_query.edit_message_text(
                "Ação inválida. Escolha uma opção:",
                reply_markup=self._get_pomodoro_menu_keyboard()
            )
        return self.POMODORO_MENU_STATE # Tenta retornar ao menu Pomodoro
