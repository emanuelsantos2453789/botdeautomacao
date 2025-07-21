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
    POMODORO_MENU_STATE = 0
    CONFIG_MENU_STATE = 1
    SET_FOCUS_TIME_STATE = 2
    SET_SHORT_BREAK_TIME_STATE = 3
    SET_LONG_BREAK_TIME_STATE = 4
    SET_CYCLES_STATE = 5

    def __init__(self, bot=None, chat_id=None):
        self.foco_tempo = 25 * 60  # 25 minutos em segundos
        self.pausa_curta_tempo = 5 * 60 # 5 minutos em segundos
        self.pausa_longa_tempo = 15 * 60 # 15 minutos em segundos
        self.ciclos_para_pausa_longa = 4

        self.estado = "ocioso" # Pode ser: "ocioso", "foco", "pausa_curta", "pausa_longa", "pausado"
        self.tempo_restante = 0
        self.ciclos_completados = 0 # Ciclos completados na sessão atual
        self.tipo_atual = None # Pode ser: "foco", "pausa_curta", "pausa_longa"

        # Histórico de tempos para o relatório final (acumula por sessão)
        self.historico_foco_total = 0
        self.historico_pausa_curta_total = 0
        self.historico_pausa_longa_total = 0
        self.historico_ciclos_completados = 0

        self._timer_thread = None
        self._parar_temporizador = threading.Event()

        # O bot e chat_id são essenciais para enviar mensagens
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
        Rodará em uma thread separada.
        """
        self._parar_temporizador.clear() # Limpa o sinal de parada para começar

        # Verifica se o bot e chat_id estão disponíveis antes de enviar mensagens
        if self.bot and self.chat_id and self.estado != "pausado":
            await self.bot.send_message(self.chat_id, f"🌟 Iniciando seu período de {self.tipo_atual.capitalize()}! Vamos lá! Tempo: {self._formatar_tempo(self.tempo_restante)}")

        while self.tempo_restante > 0 and not self._parar_temporizador.is_set():
            await asyncio.sleep(1) # Usa asyncio.sleep para ser compatível com o loop do bot
            self.tempo_restante -= 1
            
            # ATUALIZAÇÃO DE STATUS: Enviar um status a cada X segundos ou minutos.
            # CUIDADO: Isso pode gerar muitas mensagens. Ajuste a frequência.
            # Por exemplo, a cada 30 segundos se for foco/pausa, ou a cada minuto.
            # Ou apenas atualizar a mensagem existente do status se for aberta.
            # Para evitar flood, vou manter simples aqui, só a notificação de fim de ciclo.
            # Se quiser status em tempo real com edição de mensagem, precisamos de um mecanismo mais complexo.

        if not self._parar_temporizador.is_set(): # Se o temporizador não foi parado manualmente
            await self._proximo_estado()

    async def _proximo_estado(self):
        """Lógica para transicionar para o próximo estado (foco, pausa curta, pausa longa)."""
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
        else: # Reseta se estiver em um estado inesperado
            self.estado = "ocioso"
            self.tempo_restante = 0
            self.tipo_atual = None

        if self.bot and self.chat_id and msg_notificacao:
            await self.bot.send_message(self.chat_id, msg_notificacao)

        if self.estado != "ocioso":
            # Chame _rodar_temporizador diretamente como uma corrotina se a thread estiver ligada ao loop
            # Ou use run_coroutine_threadsafe APENAS se self.bot.loop for garantido.
            # Para garantir que self.bot.loop seja acessível, precisamos da application context
            # A forma mais robusta é passar o loop para a instância do Pomodoro, ou garantir que
            # a chamada seja feita de dentro do ambiente do bot.
            
            # SOLUÇÃO PARA 'AttributeError: 'NoneType' object has no attribute 'loop'':
            # A instância de Pomodoro que usa o temporizador deve ter o bot.loop disponível.
            # O `self.bot` (que é `context.bot`) já deve conter o loop.
            # O problema é a `temp_pomodoro_instance` no main, que não tem.
            # Para o temporizador em si, o acesso `self.bot.loop` está correto.
            # O `RuntimeWarning: coroutine 'Pomodoro._rodar_temporizador' was never awaited`
            # significa que a corrotina `_rodar_temporizador` foi chamada como uma função normal,
            # mas ela precisa ser `await`ed. No `threading.Thread`, `asyncio.run_coroutine_threadsafe`
            # é a forma correta de fazer isso.
            
            # Vamos garantir que `self.bot` e `self.bot.loop` existam antes de criar a thread.
            if self.bot and hasattr(self.bot, 'loop'):
                self._timer_thread = threading.Thread(
                    target=lambda: asyncio.run_coroutine_threadsafe(
                        self._rodar_temporizador(), self.bot.loop
                    ).result() # .result() para pegar exceções da corrotina na thread principal
                )
                self._timer_thread.start()
            else:
                print("ERRO: bot ou bot.loop não disponível para iniciar o temporizador. Isso não deveria acontecer na instância de usuário.")
                self.estado = "ocioso" # Volta para ocioso se não puder iniciar

    async def iniciar(self):
        """Inicia ou retoma o temporizador Pomodoro."""
        if self._timer_thread and self._timer_thread.is_alive():
            return "O Pomodoro já está rodando! Mantenha o foco. 🎯"

        if self.estado == "ocioso" or self.estado == "pausado":
            if self.estado == "ocioso":
                self.estado = "foco"
                self.tempo_restante = self.foco_tempo
                self.tipo_atual = "foco"
                response = "🎉 Pomodoro iniciado! Hora de focar e brilhar! ✨"
            elif self.estado == "pausado":
                response = "▶️ Pomodoro retomado! Vamos continuar firme! 💪"
            
            # Garante que bot e loop existam antes de tentar iniciar o timer
            if self.bot and hasattr(self.bot, 'loop'):
                self._timer_thread = threading.Thread(
                    target=lambda: asyncio.run_coroutine_threadsafe(
                        self._rodar_temporizador(), self.bot.loop
                    ).result()
                )
                self._timer_thread.start()
                return response
            else:
                return "Ops! Não consegui iniciar o Pomodoro. Tente novamente mais tarde. 😢"
        else:
            return "O Pomodoro já está em andamento. Use o botão 'Parar' para finalizar ou 'Pausar'. ⏯️"

    async def pausar(self):
        """Pausa o temporizador Pomodoro."""
        if self.estado in ["foco", "pausa_curta", "pausa_longa"]:
            self._parar_temporizador.set()
            if self._timer_thread:
                self._timer_thread.join() # Espera a thread terminar de forma limpa
            self.estado = "pausado"
            return "⏸️ Pomodoro pausado. Você pode retomar a qualquer momento! 😌"
        elif self.estado == "pausado":
            return "O Pomodoro já está pausado. Que tal retomar? ▶️"
        else:
            return "Não há Pomodoro ativo para pausar. Que tal começar um? 🚀"

    async def parar(self):
        """Para o temporizador Pomodoro, reseta o estado e gera um relatório."""
        if self.estado == "ocioso":
            return "Não há Pomodoro ativo para parar. Seu dia está livre! 🎉"

        self._parar_temporizador.set()
        if self._timer_thread:
            self._timer_thread.join()

        # Reseta o estado
        self.estado = "ocioso"
        self.tempo_restante = 0
        self.tipo_atual = None
        self.ciclos_completados = 0 # Reinicia ciclos para a próxima sessão

        # Gera o relatório antes de limpar o histórico
        report = self.gerar_relatorio()
        
        # Limpa o histórico após gerar o relatório para o próximo ciclo de uso completo
        self.historico_foco_total = 0
        self.historico_pausa_curta_total = 0
        self.historico_pausa_longa_total = 0
        self.historico_ciclos_completados = 0

        return "⏹️ Pomodoro parado! Aqui está o resumo da sua sessão:\n\n" + report + "\n\nInicie um novo ciclo quando estiver pronto para arrasar de novo! ✨"

    def status(self):
        """Retorna o status atual do Pomodoro."""
        if self.estado == "ocioso":
            return "O Pomodoro está ocioso. Pronto para começar a focar? 🌟"
        elif self.estado == "pausado":
            return (f"Pomodoro pausado. Faltam *{self._formatar_tempo(self.tempo_restante)}* "
                    f"para o fim do seu período de *{self.tipo_atual.replace('_', ' ')}*. "
                    f"Ciclos de foco completos: *{self.ciclos_completados}*. Você está quase lá! ⏳")
        else:
            return (f"Status: *{self.estado.capitalize()}* | "
                    f"Tempo restante: *{self._formatar_tempo(self.tempo_restante)}* | "
                    f"Ciclos de foco completos: *{self.ciclos_completados}*. Continue firme! 🔥")

    async def configurar(self, tipo_config, valor):
        """Permite configurar os tempos do Pomodoro."""
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
        """Retorna as configurações atuais do Pomodoro formatadas."""
        return (f"Configurações atuais do seu Pomodoro:\n"
                f"🍅 *Foco:* {self.foco_tempo // 60} min\n"
                f"☕ *Pausa Curta:* {self.pausa_curta_tempo // 60} min\n"
                f"🛋️ *Pausa Longa:* {self.pausa_longa_tempo // 60} min\n"
                f"🔄 *Ciclos para Pausa Longa:* {self.ciclos_para_pausa_longa}")

    def gerar_relatorio(self):
        """Calcula e retorna o relatório final do tempo de foco, pausas e ciclos."""
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

        relatorio = (f"--- 📊 Relatório da Sua Sessão de Produtividade! ---\n"
                     f"**Foco total:** {horas_foco}h {min_foco}min 🧠\n"
                     f"**Pausa Curta total:** {horas_pausa_curta}h {min_pausa_curta}min ☕\n"
                     f"**Pausa Longa total:** {horas_pausa_longa}h {min_pausa_longa}min 🧘‍♀️\n"
                     f"**Ciclos de foco completos:** {self.historico_ciclos_completados} 🏆\n"
                     f"**Tempo total da sessão:** {horas_geral}h {min_geral}min ✅")
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
            [InlineKeyboardButton("⬅️ Voltar ao Início", callback_data="main_menu_return")],
        ]
        return InlineKeyboardMarkup(keyboard)

    def _get_config_menu_keyboard(self):
        """Retorna o teclado inline para o menu de configuração do Pomodoro."""
        keyboard = [
            [InlineKeyboardButton("Foco", callback_data="config_foco"),
             InlineKeyboardButton("Pausa Curta", callback_data="config_pausa_curta")],
            [InlineKeyboardButton("Pausa Longa", callback_data="config_pausa_longa"),
             InlineKeyboardButton("Ciclos", callback_data="config_ciclos")],
            [InlineKeyboardButton("⬅️ Voltar ao Pomodoro", callback_data="pomodoro_menu")],
        ]
        return InlineKeyboardMarkup(keyboard)

    # --- Handlers de Callbacks do Pomodoro ---

    async def _show_pomodoro_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Mostra o menu principal do Pomodoro."""
        query = update.callback_query
        # A query já foi respondida pelo open_pomodoro_menu no main.py
        await query.edit_message_text(
            "Bem-vindo ao seu assistente Pomodoro! 🍅 Escolha uma ação e vamos ser produtivos! ✨",
            reply_markup=self._get_pomodoro_menu_keyboard()
        )
        return self.POMODORO_MENU_STATE

    async def _pomodoro_iniciar_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o botão 'Iniciar' do Pomodoro."""
        query = update.callback_query
        await query.answer()
        response = await self.iniciar()
        # Se a mensagem não mudou, evite editar. Ou force a edição com uma pequena mudança (tipo um espaço invisível)
        # ou envie uma nova mensagem se for o caso. Para evitar o "Message is not modified", vou checar.
        if query.message.text != response:
            await query.edit_message_text(response, reply_markup=self._get_pomodoro_menu_keyboard(), parse_mode='Markdown')
        else: # Se a mensagem é a mesma (ex: "Pomodoro já está rodando"), apenas notifique.
            await query.answer(response) # Aparece como um pop-up.
        return self.POMODORO_MENU_STATE

    async def _pomodoro_pausar_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o botão 'Pausar' do Pomodoro."""
        query = update.callback_query
        await query.answer()
        response = await self.pausar()
        if query.message.text != response:
            await query.edit_message_text(response, reply_markup=self._get_pomodoro_menu_keyboard(), parse_mode='Markdown')
        else:
            await query.answer(response)
        return self.POMODORO_MENU_STATE

    async def _pomodoro_parar_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o botão 'Parar' do Pomodoro e exibição do relatório."""
        query = update.callback_query
        await query.answer()
        response = await self.parar()
        # O relatório é sempre diferente, então edita sem medo.
        await query.edit_message_text(response, parse_mode='Markdown', reply_markup=self._get_pomodoro_menu_keyboard())
        return self.POMODORO_MENU_STATE

    async def _pomodoro_status_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o botão 'Status' do Pomodoro."""
        query = update.callback_query
        await query.answer()
        response = self.status()
        # Sempre atualizamos o status para mostrar o tempo restante
        await query.edit_message_text(response, reply_markup=self._get_pomodoro_menu_keyboard(), parse_mode='Markdown')
        return self.POMODORO_MENU_STATE

    async def _show_config_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o botão 'Configurar' do Pomodoro."""
        query = update.callback_query
        await query.answer()
        current_config = self.get_config_status()
        await query.edit_message_text(
            f"⚙️ Configurar Pomodoro:\n{current_config}\n\nEscolha o que deseja alterar: ✨",
            reply_markup=self._get_config_menu_keyboard(), parse_mode='Markdown'
        )
        return self.CONFIG_MENU_STATE

    async def _request_config_value(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Solicita ao usuário que envie o valor para a configuração selecionada."""
        query = update.callback_query
        await query.answer()
        config_type = query.data.replace("config_", "")
        context.user_data['config_type'] = config_type
        
        prompt_text = (f"Por favor, envie o novo valor (número inteiro em minutos) "
                       f"para '{config_type.replace('_', ' ').capitalize()}': 🔢")
        await query.edit_message_text(prompt_text) # Edita a mensagem para o prompt
        
        # Retorna o estado apropriado para aguardar a mensagem do usuário
        if config_type == "foco":
            return self.SET_FOCUS_TIME_STATE
        elif config_type == "pausa_curta":
            return self.SET_SHORT_BREAK_TIME_STATE
        elif config_type == "pausa_longa":
            return self.SET_LONG_BREAK_TIME_STATE
        elif config_type == "ciclos":
            return self.SET_CYCLES_STATE
        # Não precisamos de um 'else' aqui, pois os padrões dos callbacks já nos guiaram.

    async def _set_config_value(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Recebe o valor da configuração digitado pelo usuário e o aplica."""
        config_type = context.user_data.get('config_type')
        
        if not config_type: # Caso o tipo de configuração não esteja no user_data (erro)
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
        
        # Limpa o tipo de configuração do user_data
        if 'config_type' in context.user_data:
            del context.user_data['config_type']
        
        return self.CONFIG_MENU_STATE

    async def _exit_pomodoro_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o botão 'Voltar ao Início'."""
        query = update.callback_query
        await query.answer("Saindo do Pomodoro. Voltando ao menu principal! 👋")
        # Este handler apenas sinaliza o fim da sub-conversação.
        # O main.py cuida da edição da mensagem para o menu principal.
        return ConversationHandler.END 

    # --- Método para Obter o ConversationHandler do Pomodoro ---

    def get_pomodoro_conversation_handler(self):
        """
        Retorna o ConversationHandler completo para a funcionalidade Pomodoro.
        Este handler será aninhado no ConversationHandler principal do bot.
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
                # Quando esta conversa aninhada termina (_exit_pomodoro_conversation retorna END),
                # o controle é passado de volta ao ConversationHandler pai.
                # O pai (main.py) irá capturar o `main_menu_return` callback e lidar com o retorno.
                ConversationHandler.END: ConversationHandler.END, 
            },
        )

    async def _fallback_pomodoro_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Trata mensagens de texto inesperadas dentro do fluxo Pomodoro."""
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
        return self.POMODORO_MENU_STATE # Retorna ao menu Pomodoro
