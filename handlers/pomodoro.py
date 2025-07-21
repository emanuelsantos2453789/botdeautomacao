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
    # Usamos constantes de classe para evitar duplicidade e facilitar a leitura
    POMODORO_MENU_STATE = 0
    CONFIG_MENU_STATE = 1
    SET_FOCUS_TIME_STATE = 2
    SET_SHORT_BREAK_TIME_STATE = 3
    SET_LONG_BREAK_TIME_STATE = 4
    SET_CYCLES_STATE = 5

    def __init__(self, bot=None, chat_id=None):
        # Configurações padrão do Pomodoro
        self.foco_tempo = 25 * 60  # 25 minutos em segundos
        self.pausa_curta_tempo = 5 * 60 # 5 minutos em segundos
        self.pausa_longa_tempo = 15 * 60 # 15 minutos em segundos
        self.ciclos_para_pausa_longa = 4

        # Estado atual do ciclo do Pomodoro
        self.estado = "ocioso" # Pode ser: "ocioso", "foco", "pausa_curta", "pausa_longa", "pausado"
        self.tempo_restante = 0
        self.ciclos_completados = 0
        self.tipo_atual = None # Pode ser: "foco", "pausa_curta", "pausa_longa"

        # Histórico para relatórios (acumula ao longo de várias sessões se o bot não for reiniciado)
        self.historico_foco_total = 0
        self.historico_pausa_curta_total = 0
        self.historico_pausa_longa_total = 0
        self.historico_ciclos_completados = 0

        # Variáveis para controle do temporizador em background
        self._timer_thread = None # Armazena a thread do temporizador
        self._parar_temporizador = threading.Event() # Sinaliza para a thread parar

        # Referências do bot para enviar mensagens assíncronas
        self.bot = bot
        self.chat_id = chat_id

    def _formatar_tempo(self, segundos):
        """Formata segundos em MM:SS."""
        min = segundos // 60
        sec = segundos % 60
        return f"{min:02d}:{sec:02d}"

    async def _rodar_temporizador(self):
        """
        Função interna que gerencia a contagem regressiva do tempo.
        Executada em uma thread separada para não bloquear o bot principal.
        """
        self._parar_temporizador.clear() # Garante que o sinal de parada está limpo

        # Envia mensagem inicial apenas quando um novo ciclo começa (não ao retomar de pausa)
        if self.bot and self.chat_id and self.estado != "pausado":
            await self.bot.send_message(self.chat_id, f"Iniciando {self.tipo_atual.capitalize()}! Tempo: {self._formatar_tempo(self.tempo_restante)}")

        while self.tempo_restante > 0 and not self._parar_temporizador.is_set():
            time.sleep(1) # Espera 1 segundo
            self.tempo_restante -= 1 # Decrementa o tempo

        # Se o temporizador não foi parado manualmente, avança para o próximo estado
        if not self._parar_temporizador.is_set():
            await self._proximo_estado()

    async def _proximo_estado(self):
        """
        Determina e transiciona para o próximo estado do Pomodoro (foco, pausa curta, pausa longa).
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
        else: # Se por algum motivo não está em foco/pausa, volta para ocioso
            self.estado = "ocioso"
            self.tempo_restante = 0
            self.tipo_atual = None

        # Envia a notificação para o usuário
        if self.bot and self.chat_id and msg_notificacao:
            await self.bot.send_message(self.chat_id, msg_notificacao)

        # Inicia o próximo temporizador se o estado não for 'ocioso'
        if self.estado != "ocioso":
            # Agendamos a corrotina _rodar_temporizador no loop de eventos do bot
            # através de uma thread separada para não bloquear o loop principal.
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

            # Inicia a thread do temporizador
            self._timer_thread = threading.Thread(target=lambda: asyncio.run_coroutine_threadsafe(self._rodar_temporizador(), self.bot.loop))
            self._timer_thread.start()
            return response
        else:
            return "O Pomodoro já está em andamento. Use o botão 'Parar' para finalizar ou 'Pausar'."

    async def pausar(self):
        """Pausa o temporizador Pomodoro."""
        if self.estado in ["foco", "pausa_curta", "pausa_longa"]:
            self._parar_temporizador.set() # Sinaliza para a thread parar
            if self._timer_thread:
                self._timer_thread.join() # Espera a thread terminar
            self.estado = "pausado"
            return "Pomodoro pausado."
        elif self.estado == "pausado":
            return "O Pomodoro já está pausado."
        else:
            return "Não há Pomodoro ativo para pausar."

    async def parar(self):
        """Para o temporizador Pomodoro, reseta o estado e gera um relatório."""
        if self.estado == "ocioso":
            return "Não há Pomodoro ativo para parar."

        self._parar_temporizador.set() # Sinaliza para a thread parar
        if self._timer_thread:
            self._timer_thread.join() # Espera a thread terminar

        # Reseta o estado do Pomodoro para ocioso
        self.estado = "ocioso"
        self.tempo_restante = 0
        self.tipo_atual = None
        self.ciclos_completados = 0

        # Gera o relatório com os dados acumulados
        report = self.gerar_relatorio()
        
        # Limpa o histórico após gerar o relatório, preparando para um novo ciclo de uso
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
            return (f"Pomodoro pausado. Faltam {self._formatar_tempo(self.tempo_restante)} "
                    f"para o fim do {self.tipo_atual.replace('_', ' ')}. "
                    f"Ciclos de foco completos: {self.ciclos_completados}")
        else:
            return (f"Status: {self.estado.capitalize()} | "
                    f"Tempo restante: {self._formatar_tempo(self.tempo_restante)} | "
                    f"Ciclos de foco completos: {self.ciclos_completados}")

    async def configurar(self, tipo_config, valor):
        """
        Permite configurar os tempos do Pomodoro (foco, pausas, ciclos).
        Retorna uma tupla (sucesso_bool, mensagem)
        """
        if self.estado != "ocioso":
            return False, "Não é possível configurar enquanto o Pomodoro está ativo ou pausado. Por favor, pare-o primeiro."

        if not isinstance(valor, int) or valor <= 0:
            return False, "O valor deve ser um número inteiro positivo."

        # Atualiza a configuração conforme o tipo
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
        
        return True, (f"Configuração de {tipo_config.replace('_', ' ').capitalize()} "
                      f"atualizada para {valor} min (ou ciclos).")

    def get_config_status(self):
        """Retorna as configurações atuais do Pomodoro formatadas."""
        return (f"Configurações atuais:\n"
                f"Foco: {self.foco_tempo // 60} min\n"
                f"Pausa Curta: {self.pausa_curta_tempo // 60} min\n"
                f"Pausa Longa: {self.pausa_longa_tempo // 60} min\n"
                f"Ciclos para Pausa Longa: {self.ciclos_para_pausa_longa}")

    def gerar_relatorio(self):
        """
        Calcula e retorna o relatório final do tempo de foco, pausas e ciclos.
        """
        # Converte segundos para minutos para o relatório
        total_foco_min = self.historico_foco_total // 60
        total_pausa_curta_min = self.historico_pausa_curta_total // 60
        total_pausa_longa_min = self.historico_pausa_longa_total // 60
        
        total_geral_min = total_foco_min + total_pausa_curta_min + total_pausa_longa_min
        
        # Formata para horas e minutos
        horas_foco = total_foco_min // 60
        min_foco = total_foco_min % 60
        
        horas_pausa_curta = total_pausa_curta_min // 60
        min_pausa_curta = total_pausa_curta_min % 60

        horas_pausa_longa = total_pausa_longa_min // 60
        min_pausa_longa = total_pausa_longa_min % 60

        horas_geral = total_geral_min // 60
        min_geral = total_geral_min % 60

        # Constrói a string do relatório
        relatorio = (f"--- Relatório do Pomodoro ---\n"
                     f"**Foco total:** {horas_foco}h {min_foco}min\n"
                     f"**Pausa Curta total:** {horas_pausa_curta}h {min_pausa_curta}min\n"
                     f"**Pausa Longa total:** {horas_pausa_longa}h {min_pausa_longa}min\n"
                     f"**Ciclos de foco completos:** {self.historico_ciclos_completados}\n"
                     f"**Tempo total da sessão:** {horas_geral}h {min_geral}min")
        return relatorio

    # --- Métodos para Gerar Menus de Botões Inline ---

    def _get_pomodoro_menu_keyboard(self):
        """Retorna o teclado inline para o menu principal do Pomodoro."""
        keyboard = [
            [InlineKeyboardButton("▶️ Iniciar", callback_data="pomodoro_iniciar"),
             InlineKeyboardButton("⏸️ Pausar", callback_data="pomodoro_pausar")],
            [InlineKeyboardButton("⏹️ Parar", callback_data="pomodoro_parar"),
             InlineKeyboardButton("📊 Status", callback_data="pomodoro_status")],
            [InlineKeyboardButton("⚙️ Configurar", callback_data="pomodoro_configurar")],
            [InlineKeyboardButton("⬅️ Voltar ao Início", callback_data="main_menu_return")], # Callback para retornar ao menu principal do bot
        ]
        return InlineKeyboardMarkup(keyboard)

    def _get_config_menu_keyboard(self):
        """Retorna o teclado inline para o menu de configuração do Pomodoro."""
        keyboard = [
            [InlineKeyboardButton("Foco", callback_data="config_foco"),
             InlineKeyboardButton("Pausa Curta", callback_data="config_pausa_curta")],
            [InlineKeyboardButton("Pausa Longa", callback_data="config_pausa_longa"),
             InlineKeyboardButton("Ciclos", callback_data="config_ciclos")],
            [InlineKeyboardButton("⬅️ Voltar ao Pomodoro", callback_data="pomodoro_menu")], # Retorna para o menu principal do pomodoro
        ]
        return InlineKeyboardMarkup(keyboard)

    # --- Handlers de Callbacks do Pomodoro ---

    async def _show_pomodoro_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Mostra o menu principal do Pomodoro.
        Este handler é o ponto de entrada da sub-conversação do Pomodoro.
        """
        query = update.callback_query
        # A query já foi respondida pelo open_pomodoro_menu no main.py, então não precisamos chamar query.answer() aqui novamente.
        await query.edit_message_text(
            "Bem-vindo ao Pomodoro! Escolha uma ação:",
            reply_markup=self._get_pomodoro_menu_keyboard()
        )
        return self.POMODORO_MENU_STATE

    async def _pomodoro_iniciar_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o botão 'Iniciar' do Pomodoro."""
        query = update.callback_query
        await query.answer()
        response = await self.iniciar()
        await query.edit_message_text(response, reply_markup=self._get_pomodoro_menu_keyboard())
        return self.POMODORO_MENU_STATE

    async def _pomodoro_pausar_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o botão 'Pausar' do Pomodoro."""
        query = update.callback_query
        await query.answer()
        response = await self.pausar()
        await query.edit_message_text(response, reply_markup=self._get_pomodoro_menu_keyboard())
        return self.POMODORO_MENU_STATE

    async def _pomodoro_parar_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o botão 'Parar' do Pomodoro e exibição do relatório."""
        query = update.callback_query
        await query.answer()
        response = await self.parar()
        await query.edit_message_text(response, parse_mode='Markdown', reply_markup=self._get_pomodoro_menu_keyboard())
        return self.POMODORO_MENU_STATE

    async def _pomodoro_status_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o botão 'Status' do Pomodoro."""
        query = update.callback_query
        await query.answer()
        response = self.status()
        await query.edit_message_text(response, reply_markup=self._get_pomodoro_menu_keyboard())
        return self.POMODORO_MENU_STATE

    async def _show_config_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o botão 'Configurar' do Pomodoro, mostrando o menu de configuração."""
        query = update.callback_query
        await query.answer()
        current_config = self.get_config_status()
        await query.edit_message_text(
            f"Configurar Pomodoro:\n{current_config}\n\nEscolha o que deseja alterar:",
            reply_markup=self._get_config_menu_keyboard()
        )
        return self.CONFIG_MENU_STATE

    async def _request_config_value(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handler para os botões de configuração (Foco, Pausa Curta, etc.).
        Solicita ao usuário que envie o novo valor.
        """
        query = update.callback_query
        await query.answer()
        config_type = query.data.replace("config_", "") # Extrai o tipo de configuração do callback_data
        context.user_data['config_type'] = config_type # Armazena o tipo de configuração no user_data

        prompt_text = f"Por favor, envie o novo valor (número inteiro em minutos) para '{config_type.replace('_', ' ').capitalize()}':"
        await query.edit_message_text(prompt_text)

        # Retorna o estado apropriado para aguardar a mensagem do usuário com o valor
        if config_type == "foco":
            return self.SET_FOCUS_TIME_STATE
        elif config_type == "pausa_curta":
            return self.SET_SHORT_BREAK_TIME_STATE
        elif config_type == "pausa_longa":
            return self.SET_LONG_BREAK_TIME_STATE
        elif config_type == "ciclos":
            return self.SET_CYCLES_STATE
        else:
            # Fallback para um tipo de configuração inesperado (não deve acontecer com os patterns corretos)
            await query.edit_message_text("Erro interno: Tipo de configuração desconhecido.", reply_markup=self._get_config_menu_keyboard())
            return self.CONFIG_MENU_STATE


    async def _set_config_value(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handler para receber o valor de configuração digitado pelo usuário.
        Tenta aplicar a configuração e volta para o menu de configuração.
        """
        config_type = context.user_data.get('config_type')
        
        if not config_type:
            await update.message.reply_text("Erro: Tipo de configuração não encontrado. Por favor, tente novamente.", reply_markup=self._get_pomodoro_menu_keyboard())
            return self.POMODORO_MENU_STATE # Volta para o menu principal do pomodoro em caso de erro

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
        
        # Limpa o tipo de configuração do user_data após o uso
        if 'config_type' in context.user_data:
            del context.user_data['config_type']
        
        return self.CONFIG_MENU_STATE

    async def _exit_pomodoro_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handler para o botão 'Voltar ao Início' dentro do menu Pomodoro.
        Ele sinaliza ao ConversationHandler pai (em main.py) que esta sub-conversação terminou.
        """
        query = update.callback_query
        await query.answer()
        # Não enviamos ou editamos a mensagem aqui, pois o handler no main.py fará o retorno visual.
        
        # Retorna ConversationHandler.END para este ConversationHandler aninhado,
        # permitindo que o ConversationHandler pai retome o controle.
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
            # REMOVEMOS 'per_message=False' daqui, pois não é um argumento de CallbackQueryHandler.
            entry_points=[CallbackQueryHandler(self._show_pomodoro_menu, pattern="^open_pomodoro_menu$")],
            states={
                self.POMODORO_MENU_STATE: [
                    CallbackQueryHandler(self._pomodoro_iniciar_callback, pattern="^pomodoro_iniciar$"),
                    CallbackQueryHandler(self._pomodoro_pausar_callback, pattern="^pomodoro_pausar$"),
                    CallbackQueryHandler(self._pomodoro_parar_callback, pattern="^pomodoro_parar$"),
                    CallbackQueryHandler(self._pomodoro_status_callback, pattern="^pomodoro_status$"),
                    CallbackQueryHandler(self._show_config_menu, pattern="^pomodoro_configurar$"),
                    CallbackQueryHandler(self._exit_pomodoro_conversation, pattern="^main_menu_return$"), # Para sair da conversa do Pomodoro
                ],
                self.CONFIG_MENU_STATE: [
                    CallbackQueryHandler(self._request_config_value, pattern="^config_foco$"),
                    CallbackQueryHandler(self._request_config_value, pattern="^config_pausa_curta$"),
                    CallbackQueryHandler(self._request_config_value, pattern="^config_pausa_longa$"),
                    CallbackQueryHandler(self._request_config_value, pattern="^config_ciclos$"),
                    CallbackQueryHandler(self._show_pomodoro_menu, pattern="^pomodoro_menu$"), # Botão de voltar ao menu Pomodoro
                ],
                self.SET_FOCUS_TIME_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._set_config_value)],
                self.SET_SHORT_BREAK_TIME_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._set_config_value)],
                self.SET_LONG_BREAK_TIME_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._set_config_value)],
                self.SET_CYCLES_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._set_config_value)],
            },
            fallbacks=[
                # Um fallback para mensagens não esperadas dentro da conversa do Pomodoro
                MessageHandler(filters.ALL, self._fallback_pomodoro_message),
            ],
            # map_to_parent define o que acontece no ConversationHandler pai quando este ConversationHandler aninhado termina.
            # Quando _exit_pomodoro_conversation retorna ConversationHandler.END, o pai (main.py)
            # deve retornar ao MAIN_MENU_STATE.
            map_to_parent={
                ConversationHandler.END: ConversationHandler.END, # Sinaliza ao pai que o ConversationHandler aninhado terminou.
                                                                 # O pai então decide o que fazer com este END.
            },
            # per_user=True é o padrão e é o comportamento correto para gerenciar conversas por usuário.
        )

    async def _fallback_pomodoro_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Trata mensagens de texto ou callbacks inesperados dentro do fluxo Pomodoro,
        guiando o usuário de volta aos menus.
        """
        if update.message:
            await update.message.reply_text(
                "Desculpe, não entendi. Por favor, use os botões ou siga as instruções para configurar.",
                reply_markup=self._get_pomodoro_menu_keyboard() # Volta para o menu principal do Pomodoro
            )
        elif update.callback_query:
            await update.callback_query.answer("Ação inválida para este momento.")
            await update.callback_query.edit_message_text(
                "Ação inválida. Escolha uma opção:",
                reply_markup=self._get_pomodoro_menu_keyboard()
            )
        return self.POMODORO_MENU_STATE # Tenta retornar ao menu Pomodoro
