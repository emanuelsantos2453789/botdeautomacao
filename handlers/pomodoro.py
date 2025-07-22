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

        # O bot e chat_id serão definidos pelo main.py quando a instância for criada/acessada
        self.bot = bot 
        self.chat_id = chat_id 

    def _formatar_tempo(self, segundos):
        """Formata segundos em MM:SS."""
        min = segundos // 60
        sec = segundos % 60
        return f"{min:02d}:{sec:02d}"

    async def _rodar_temporizador(self, initial_message_id=None):
        """
        Função interna para gerenciar a contagem regressiva.
        Executada em uma thread separada.
        """
        self._parar_temporizador.clear() # Limpa o sinal de parada para começar do zero

        self._current_status_message_id = initial_message_id # Define o ID da mensagem se passado

        last_update_time = time.time() # Para controlar a frequência de atualização

        while self.tempo_restante > 0 and not self._parar_temporizador.is_set():
            # Atualiza a mensagem de status se um ID de mensagem estiver definido e tempo suficiente tiver passado
            if self._current_status_message_id and (time.time() - last_update_time) >= self.ATUALIZACAO_STATUS_INTERVAL:
                try:
                    await self.bot.edit_message_text(
                        chat_id=self.chat_id,
                        message_id=self._current_status_message_id,
                        text=self.status(),
                        reply_markup=self._get_pomodoro_menu_keyboard(),
                        parse_mode='Markdown'
                    )
                    last_update_time = time.time() # Reseta o tempo da última atualização
                except Exception as e:
                    # Captura "Message is not modified" ou outros erros se a mensagem foi deletada/editada em outro lugar
                    # print(f"Erro ao atualizar mensagem de status: {e}")
                    # Se a mensagem não existir mais, limpa o ID para evitar mais erros
                    if "message to edit not found" in str(e).lower() or "message is not modified" not in str(e):
                        self._current_status_message_id = None
                    pass # Apenas suprime o erro, não precisa parar o temporizador

            await asyncio.sleep(1) # Espera 1 segundo
            self.tempo_restante -= 1 # Decrementa o tempo

        if not self._parar_temporizador.is_set(): # Se o temporizador não foi parado manualmente
            # Envia a última atualização de status antes da transição
            if self._current_status_message_id and self.bot and self.chat_id:
                try:
                    await self.bot.edit_message_text(
                        chat_id=self.chat_id,
                        message_id=self._current_status_message_id,
                        text=self.status(), # Mostra 00:00 ou o status final
                        reply_markup=self._get_pomodoro_menu_keyboard(),
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    pass # Ignora se a mensagem não puder ser atualizada no final
            
            await self._proximo_estado()
        # Sem bloco else aqui, pois _parar_temporizador.set() é tratado pelo chamador

    async def _proximo_estado(self):
        """Lógica para transição para o próximo estado do Pomodoro (foco, pausa curta, pausa longa)."""
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
        else: # Reseta se estiver em um estado inesperado ou parando o último ciclo
            self.estado = "ocioso"
            self.tempo_restante = 0
            self.tipo_atual = None
            msg_notificacao = "Pomodoro concluído! Pronto para o próximo ciclo? 🎉"


        if self.bot and self.chat_id and msg_notificacao:
            # Envia a mensagem de notificação
            await self.bot.send_message(self.chat_id, msg_notificacao)

            # Se não estiver indo para "ocioso", então inicia o próximo ciclo do timer e obtém seu message_id
            if self.estado != "ocioso":
                # Envia a mensagem de status inicial para o próximo ciclo
                status_msg = await self.bot.send_message(
                    self.chat_id, 
                    self.status(), 
                    reply_markup=self._get_pomodoro_menu_keyboard(), 
                    parse_mode='Markdown'
                )
                # Passa este message_id para o timer para atualizações
                self._current_status_message_id = status_msg.message_id
                
                if self.bot and hasattr(self.bot, 'loop'):
                    # Agenda _rodar_temporizador para rodar no loop de eventos
                    self._timer_thread = threading.Thread(
                        target=lambda: asyncio.run_coroutine_threadsafe(
                            self._rodar_temporizador(initial_message_id=self._current_status_message_id), self.bot.loop
                        ).result()
                    )
                    self._timer_thread.start()
                else:
                    print("ERRO: bot ou bot.loop não disponível para iniciar o temporizador. Caindo para ocioso.")
                    self.estado = "ocioso"
            else:
                self._current_status_message_id = None # Nenhum timer ativo, limpa o ID do status

    async def iniciar(self):
        """Inicia ou retoma o temporizador Pomodoro."""
        # Garante que bot e chat_id estão definidos (importante para a primeira execução)
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
            initial_status_msg_text = f"🌟 Iniciando seu período de {self.tipo_atual.capitalize()}! Tempo: {self._formatar_tempo(self.foco_tempo)} 🎉"
        elif self.estado == "pausado":
            # Ao retomar, o tempo_restante já está correto do estado pausado
            response = "▶️ Pomodoro retomado! Vamos continuar firme! 💪"
            initial_status_msg_text = f"🚀 Retomando seu período de {self.tipo_atual.capitalize()}! Tempo restante: {self._formatar_tempo(self.tempo_restante)} ⏳"
        else:
            return "O Pomodoro já está em andamento. Use o botão 'Parar' para finalizar ou 'Pausar'. ⏯️"
        
        # Envia a mensagem de status inicial e armazena seu ID
        try:
            # Se já houver um ID de mensagem de status (por exemplo, após uma pausa), edite-o.
            # Caso contrário, envie uma nova mensagem.
            if self._current_status_message_id:
                status_message = await self.bot.edit_message_text(
                    chat_id=self.chat_id,
                    message_id=self._current_status_message_id,
                    text=initial_status_msg_text,
                    reply_markup=self._get_pomodoro_menu_keyboard(),
                    parse_mode='Markdown'
                )
            else:
                status_message = await self.bot.send_message(
                    self.chat_id, 
                    initial_status_msg_text,
                    reply_markup=self._get_pomodoro_menu_keyboard(),
                    parse_mode='Markdown'
                )
            self._current_status_message_id = status_message.message_id
        except Exception as e:
            print(f"Erro ao enviar/editar mensagem inicial do Pomodoro: {e}")
            # Se não conseguiu editar/enviar, tenta enviar uma nova mensagem sem rastreá-la
            await self.bot.send_message(
                self.chat_id, 
                "Ops! Não consegui enviar a mensagem inicial do Pomodoro. Mas o timer foi iniciado! 😢"
            )
            self._current_status_message_id = None # Garante que não está rastreando uma mensagem inválida
            # Não retorne aqui, continue para iniciar a thread do timer
            # return "Ops! Não consegui enviar a mensagem inicial do Pomodoro. Tente novamente mais tarde. 😢"

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
        """Pausa o temporizador Pomodoro."""
        if self.estado in ["foco", "pausa_curta", "pausa_longa"]:
            self._parar_temporizador.set()
            if self._timer_thread:
                self._timer_thread.join() # Espera a thread terminar
            self.estado = "pausado"
            # Mantém _current_status_message_id para que o botão 'Status' possa atualizá-lo
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
        if self._timer_thread and self._timer_thread.is_alive():
            self._timer_thread.join(timeout=2) # Espera um pouco pela thread terminar

        # Gera relatório antes de limpar o histórico
        report = self.gerar_relatorio()
        
        # Reseta o estado
        self.estado = "ocioso"
        self.tempo_restante = 0
        self.tipo_atual = None
        self.ciclos_completados = 0
        
        # Limpa o histórico após gerar o relatório para o próximo ciclo completo
        self.historico_foco_total = 0
        self.historico_pausa_curta_total = 0
        self.historico_pausa_longa_total = 0
        self.historico_ciclos_completados = 0
        self._current_status_message_id = None # Limpa o ID da mensagem de status ao parar

        return "⏹️ Pomodoro parado! Aqui está o resumo da sua sessão:\n\n" + report + "\n\nInicie um novo ciclo quando estiver pronto para arrasar de novo! ✨"

    def status(self):
        """Retorna o status atual do Pomodoro, incluindo o tempo restante."""
        if self.estado == "ocioso":
            return "O Pomodoro está ocioso. Pronto para começar a focar? 🌟"
        elif self.estado == "pausado":
            return (f"Pomodoro pausado. Faltam *{self._formatar_tempo(self.tempo_restante)}* "
                    f"para o fim do seu período de *{self.tipo_atual.replace('_', ' ')}*. "
                    f"Ciclos de foco completos: *{self.ciclos_completados}*. Você está quase lá! ⏳")
        else:
            # Atualização de status dinâmica para períodos ativos
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
        """Calcula e retorna o relatório final de tempo de foco, pausas e ciclos."""
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

        # Garante que o relatório sempre mostre algo, mesmo que zero
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

    # --- Handlers de Callback do Pomodoro ---

    async def _show_pomodoro_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Exibe o menu principal do Pomodoro."""
        query = update.callback_query
        # A instância Pomodoro para o usuário atual já está em context.user_data['pomodoro_instance']
        # e tem o bot e chat_id atualizados pelo main.py antes de chamar este método.

        await query.edit_message_text(
            "Bem-vindo ao seu assistente Pomodoro! 🍅 Escolha uma ação e vamos ser produtivos! ✨",
            reply_markup=self._get_pomodoro_menu_keyboard()
        )
        # Limpa o ID da mensagem de status ao retornar ao menu principal
        self._current_status_message_id = None
        return self.POMODORO_MENU_STATE

    async def _pomodoro_iniciar_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o botão 'Iniciar'."""
        query = update.callback_query
        await query.answer()

        # Adicione esta verificação aqui!
        if 'pomodoro_instance' not in context.user_data:
            # Se por algum motivo a instância não existir, crie-a aqui também
            context.user_data['pomodoro_instance'] = Pomodoro(bot=context.bot, chat_id=update.effective_chat.id)
            await query.edit_message_text(
                "Ops! Tive que iniciar seu Pomodoro. Por favor, tente novamente a ação desejada. 🚀",
                reply_markup=self._get_pomodoro_menu_keyboard()
            )
            return self.POMODORO_MENU_STATE

        pomodoro_instance = context.user_data['pomodoro_instance']
        
        # Garante que bot e chat_id estão atualizados na instância
        pomodoro_instance.bot = context.bot
        pomodoro_instance.chat_id = update.effective_chat.id

        response = await pomodoro_instance.iniciar()
        # O método 'iniciar' agora envia a mensagem de status inicial.
        # Aqui, apenas atualizamos a mensagem do menu original.
        await query.edit_message_text(
            response, 
            reply_markup=self._get_pomodoro_menu_keyboard(), 
            parse_mode='Markdown'
        )
        return self.POMODORO_MENU_STATE

    async def _pomodoro_pausar_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o botão 'Pausar'."""
        query = update.callback_query
        await query.answer()

        # Adicione esta verificação aqui!
        if 'pomodoro_instance' not in context.user_data:
            context.user_data['pomodoro_instance'] = Pomodoro(bot=context.bot, chat_id=update.effective_chat.id)
            await query.edit_message_text(
                "Ops! Tive que iniciar seu Pomodoro. Por favor, tente novamente a ação desejada. 🚀",
                reply_markup=self._get_pomodoro_menu_keyboard()
            )
            return self.POMODORO_MENU_STATE

        pomodoro_instance = context.user_data['pomodoro_instance']
        response = await pomodoro_instance.pausar()
        await query.edit_message_text(response, reply_markup=self._get_pomodoro_menu_keyboard(), parse_mode='Markdown')
        return self.POMODORO_MENU_STATE

    async def _pomodoro_parar_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o botão 'Parar' e exibição do relatório."""
        query = update.callback_query
        await query.answer()

        # Adicione esta verificação aqui!
        if 'pomodoro_instance' not in context.user_data:
            context.user_data['pomodoro_instance'] = Pomodoro(bot=context.bot, chat_id=update.effective_chat.id)
            await query.edit_message_text(
                "Ops! Tive que iniciar seu Pomodoro. Por favor, tente novamente a ação desejada. 🚀",
                reply_markup=self._get_pomodoro_menu_keyboard()
            )
            return self.POMODORO_MENU_STATE

        pomodoro_instance = context.user_data['pomodoro_instance']
        response = await pomodoro_instance.parar()
        await query.edit_message_text(response, parse_mode='Markdown', reply_markup=self._get_pomodoro_menu_keyboard())
        return self.POMODORO_MENU_STATE

    async def _pomodoro_status_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o botão 'Status'. Atualiza com contagem regressiva em tempo real."""
        query = update.callback_query
        await query.answer("Atualizando status...") # Fornece feedback imediato
        
        # Adicione esta verificação aqui!
        if 'pomodoro_instance' not in context.user_data:
            context.user_data['pomodoro_instance'] = Pomodoro(bot=context.bot, chat_id=update.effective_chat.id)
            await query.edit_message_text(
                "Ops! Tive que iniciar seu Pomodoro. Por favor, tente novamente a ação desejada. 🚀",
                reply_markup=self._get_pomodoro_menu_keyboard()
            )
            return self.POMODORO_MENU_STATE

        pomodoro_instance = context.user_data['pomodoro_instance']
        response = pomodoro_instance.status()
        
        try:
            message = await query.edit_message_text(
                response,
                reply_markup=self._get_pomodoro_menu_keyboard(),
                parse_mode='Markdown'
            )
            # Apenas define _current_status_message_id se o timer estiver realmente rodando
            if pomodoro_instance.estado in ["foco", "pausa_curta", "pausa_longa"]:
                pomodoro_instance._current_status_message_id = message.message_id
            else:
                pomodoro_instance._current_status_message_id = None # Limpa se não estiver rodando
        except Exception as e:
            if "Message is not modified" not in str(e): 
                new_message = await query.message.reply_text(
                    "Não consegui atualizar a mensagem anterior. Aqui está o novo status:\n" + response,
                    reply_markup=self._get_pomodoro_menu_keyboard(),
                    parse_mode='Markdown'
                )
                if pomodoro_instance.estado in ["foco", "pausa_curta", "pausa_longa"]:
                    pomodoro_instance._current_status_message_id = new_message.message_id
                else:
                    pomodoro_instance._current_status_message_id = None
            else:
                pass # Se for apenas "not modified", mantém o ID atual e o timer continuará tentando. 

        return self.POMODORO_MENU_STATE

    async def _show_config_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o botão 'Configurar', mostrando o menu de configuração."""
        query = update.callback_query
        await query.answer()

        # Adicione esta verificação aqui!
        if 'pomodoro_instance' not in context.user_data:
            context.user_data['pomodoro_instance'] = Pomodoro(bot=context.bot, chat_id=update.effective_chat.id)
            await query.edit_message_text(
                "Ops! Tive que iniciar seu Pomodoro. Por favor, tente novamente a ação desejada. 🚀",
                reply_markup=self._get_pomodoro_menu_keyboard()
            )
            return self.POMODORO_MENU_STATE


        pomodoro_instance = context.user_data['pomodoro_instance']
        current_config = pomodoro_instance.get_config_status()
        await query.edit_message_text(
            f"⚙️ Configurar Pomodoro:\n{current_config}\n\nEscolha o que deseja alterar: ✨",
            reply_markup=self._get_config_menu_keyboard(), parse_mode='Markdown'
        )
        return self.CONFIG_MENU_STATE

    async def _request_config_value(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Solicita ao usuário que envie o novo valor para a configuração selecionada."""
        query = update.callback_query
        await query.answer()
        config_type = query.data.replace("config_", "")
        context.user_data['config_type'] = config_type # Armazena o tipo de configuração no user_data
        
        prompt_text = (f"Por favor, envie o novo valor (número inteiro em minutos) "
                       f"para '{config_type.replace('_', ' ').capitalize()}': 🔢")
        await query.edit_message_text(prompt_text)
        
        # Retorna o estado apropriado para aguardar a entrada do usuário
        if config_type == "foco":
            return self.SET_FOCUS_TIME_STATE
        elif config_type == "pausa_curta":
            return self.SET_SHORT_BREAK_TIME_STATE
        elif config_type == "pausa_longa":
            return self.SET_LONG_BREAK_TIME_STATE
        elif config_type == "ciclos":
            return self.SET_CYCLES_STATE

    async def _set_config_value(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Recebe o valor de configuração digitado pelo usuário e o aplica."""
        config_type = context.user_data.get('config_type')
        
        if not config_type:
            await update.message.reply_text("Ops! O tipo de configuração não foi encontrado. Tente novamente! 🤔", reply_markup=self._get_pomodoro_menu_keyboard())
            return self.POMODORO_MENU_STATE

        try:
            value = int(update.message.text)
            # Adicione esta verificação aqui!
            if 'pomodoro_instance' not in context.user_data:
                context.user_data['pomodoro_instance'] = Pomodoro(bot=context.bot, chat_id=update.effective_chat.id)
                await update.message.reply_text(
                    "Ops! Tive que iniciar seu Pomodoro. Por favor, tente novamente a ação desejada. 🚀",
                    reply_markup=self._get_pomodoro_menu_keyboard()
                )
                return self.POMODORO_MENU_STATE

            pomodoro_instance = context.user_data['pomodoro_instance'] # Obtém a instância do Pomodoro
            success, message = await pomodoro_instance.configurar(config_type, value)
            if success:
                await update.message.reply_text(message, reply_markup=self._get_config_menu_keyboard(), parse_mode='Markdown')
            else:
                await update.message.reply_text(message, reply_markup=self._get_config_menu_keyboard())
        except ValueError:
            await update.message.reply_text("Isso não parece um número válido! Por favor, envie um número inteiro. 🔢", reply_markup=self._get_config_menu_keyboard())
        except Exception as e:
            await update.message.reply_text(f"Ocorreu um erro ao configurar: {e}. Por favor, tente novamente! 😥", reply_markup=self._get_config_menu_keyboard())
        
        # Limpa o tipo de configuração após o uso
        if 'config_type' in context.user_data:
            del context.user_data['config_type']
        
        return self.CONFIG_MENU_STATE

    async def _exit_pomodoro_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o botão 'Voltar ao Início'."""
        query = update.callback_query
        await query.answer("Saindo do Pomodoro. Voltando ao menu principal! 👋")
        # Limpa o ID da mensagem de status ao sair
        if 'pomodoro_instance' in context.user_data:
            context.user_data['pomodoro_instance']._current_status_message_id = None
        return ConversationHandler.END 

    # --- Método para Obter o ConversationHandler do Pomodoro ---

    def get_pomodoro_conversation_handler(self):
        """
        Retorna o ConversationHandler completo para a funcionalidade do Pomodoro.
        Este handler será aninhado no ConversationHandler principal do bot.
        """
        return ConversationHandler(
            # O entry_point agora chama _show_pomodoro_menu diretamente nesta instância.
            # É importante que 'open_pomodoro_menu' em main.py configure o context.user_data
            # com a instância correta do Pomodoro antes que este handler seja ativado.
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
        """Lida com mensagens de texto inesperadas dentro do fluxo do Pomodoro."""
        # Adicione esta verificação aqui!
        if 'pomodoro_instance' not in context.user_data:
            context.user_data['pomodoro_instance'] = Pomodoro(bot=context.bot, chat_id=update.effective_chat.id)
            # Ao invés de retornar, continuamos para tentar exibir o teclado.
            await update.message.reply_text(
                "Ops! Tive que iniciar seu Pomodoro. Por favor, tente novamente a ação desejada. 🚀",
                reply_markup=self._get_pomodoro_menu_keyboard()
            )
            return self.POMODORO_MENU_STATE # Volta ao menu Pomodoro

        # Tenta obter a instância do Pomodoro para pegar o teclado correto
        pomodoro_instance = context.user_data.get('pomodoro_instance', self) # fallback para self se não encontrar
        keyboard = pomodoro_instance._get_pomodoro_menu_keyboard() if hasattr(pomodoro_instance, '_get_pomodoro_menu_keyboard') else None

        if update.message:
            await update.message.reply_text(
                "Desculpe, não entendi. Por favor, use os botões ou siga as instruções. 🤷‍♀️",
                reply_markup=keyboard
            )
        elif update.callback_query:
            await update.callback_query.answer("Ação inválida para este momento. Por favor, use os botões! 🚫")
            await update.callback_query.edit_message_text(
                "Ação inválida. Escolha uma opção:",
                reply_markup=keyboard
            )
        
        # Limpa o ID da mensagem de status em entrada inesperada para evitar problemas
        if 'pomodoro_instance' in context.user_data:
            context.user_data['pomodoro_instance']._current_status_message_id = None
        return self.POMODORO_MENU_STATE
