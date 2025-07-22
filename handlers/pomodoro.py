import time
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
    ATUALIZACAO_STATUS_INTERVAL = 1 # Reduzido para 1 segundo para um feedback mais rápido

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

        self._timer_task = None # Para armazenar a tarefa assíncrona do temporizador
        self._current_status_message_id = None  # Store message_id for status updates

        # O bot e chat_id serão definidos pelo main.py quando a instância for criada/acessada
        self.bot = bot 
        self.chat_id = chat_id 

    def _formatar_tempo(self, segundos):
        """Formata segundos em MM:SS."""
        min = segundos // 60
        sec = segundos % 60
        return f"{min:02d}:{sec:02d}"

    async def _rodar_temporizador(self):
        """
        Função assíncrona interna para gerenciar a contagem regressiva e atualização da mensagem.
        Esta função roda diretamente no loop de eventos do bot como uma tarefa.
        """
        # Garante que _timer_task é a tarefa atual para permitir cancelamento externo
        # e que a flag de parada é limpa no início de um novo ciclo.
        
        while self.tempo_restante > 0:
            if self._current_status_message_id and self.bot and self.chat_id:
                try:
                    await self.bot.edit_message_text(
                        chat_id=self.chat_id,
                        message_id=self._current_status_message_id,
                        text=self.status(),
                        reply_markup=self._get_pomodoro_menu_keyboard(),
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    # Captura "Message is not modified" ou "message to edit not found"
                    # Se a mensagem não puder ser atualizada (e.g., usuário apagou), limpa o ID
                    if "message to edit not found" in str(e).lower():
                        print(f"Erro ao atualizar mensagem de status (não encontrada): {e}")
                        self._current_status_message_id = None
                    elif "message is not modified" not in str(e).lower():
                        print(f"Erro inesperado ao atualizar mensagem de status: {e}")
                    pass # Apenas suprime o erro para não travar o timer

            # Espera 1 segundo. Esta é uma pausa assíncrona que não bloqueia o bot.
            await asyncio.sleep(self.ATUALIZACAO_STATUS_INTERVAL) 
            self.tempo_restante -= self.ATUALIZACAO_STATUS_INTERVAL # Decrementa o tempo pelo intervalo de atualização

        # Garante que o tempo restante não seja negativo e atualiza para 00:00 ao final
        self.tempo_restante = 0

        # Envia a última atualização de status quando o tempo chega a zero
        if self._current_status_message_id and self.bot and self.chat_id:
            try:
                await self.bot.edit_message_text(
                    chat_id=self.chat_id,
                    message_id=self._current_status_message_id,
                    text=self.status(), # Mostrará 00:00
                    reply_markup=self._get_pomodoro_menu_keyboard(),
                    parse_mode='Markdown'
                )
            except Exception as e:
                pass # Ignora se a mensagem não puder ser atualizada no final
        
        # Passa para o próximo estado (foco -> pausa, pausa -> foco, ou ocioso)
        await self._proximo_estado()
        
        self._timer_task = None # Limpa a tarefa do temporizador quando ela termina o ciclo


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
                # IMPORTANTE: A nova mensagem de status é criada aqui, garantindo um novo message_id
                status_msg = await self.bot.send_message(
                    self.chat_id, 
                    self.status(), 
                    reply_markup=self._get_pomodoro_menu_keyboard(), 
                    parse_mode='Markdown'
                )
                self._current_status_message_id = status_msg.message_id
                
                # Inicia a tarefa assíncrona diretamente no loop de eventos
                self._timer_task = asyncio.create_task(self._rodar_temporizador())
            else:
                self._current_status_message_id = None # Nenhum timer ativo, limpa o ID do status

    async def iniciar(self):
        """Inicia ou retoma o temporizador Pomodoro."""
        # Garante que bot e chat_id estão definidos (importante para a primeira execução)
        if not self.bot or not self.chat_id:
            return "Ops! O bot não foi inicializado corretamente para o Pomodoro. Tente novamente mais tarde. 😢"

        # Verifica se o temporizador já está rodando (tarefa ativa e não finalizada)
        if self._timer_task and not self._timer_task.done():
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
            self.estado = self.tipo_atual # Volta para o estado anterior (foco, pausa curta, longa)
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
            
        # Inicia a tarefa assíncrona do temporizador
        self._timer_task = asyncio.create_task(self._rodar_temporizador())
        return response

    async def pausar(self):
        """Pausa o temporizador Pomodoro."""
        if self.estado in ["foco", "pausa_curta", "pausa_longa"]:
            if self._timer_task and not self._timer_task.done():
                self._timer_task.cancel() # Cancela a tarefa assíncrona
                try:
                    await self._timer_task # Aguarda a tarefa ser cancelada
                except asyncio.CancelledError:
                    pass # É esperado que uma tarefa cancelada levante CancelledError
                self._timer_task = None # Limpa a referência da tarefa
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

        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel() # Cancela a tarefa assíncrona
            try:
                await self._timer_task # Aguarda a tarefa ser cancelada
            except asyncio.CancelledError:
                pass # É esperado que uma tarefa cancelada levante CancelledError
            self._timer_task = None # Limpa a referência da tarefa

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
        await query.edit_message_text(
            "Bem-vindo ao seu assistente Pomodoro! 🍅 Escolha uma ação e vamos ser produtivos! ✨",
            reply_markup=self._get_pomodoro_menu_keyboard()
        )
        # NÂO limpa _current_status_message_id aqui, pois o timer pode estar ativo e precisa continuar atualizando
        return self.POMODORO_MENU_STATE

    async def _pomodoro_iniciar_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o botão 'Iniciar'."""
        query = update.callback_query
        await query.answer()

        if 'pomodoro_instance' not in context.user_data:
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
        # O método 'iniciar' agora envia ou edita a mensagem de status inicial.
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
        
        if 'pomodoro_instance' not in context.user_data:
            context.user_data['pomodoro_instance'] = Pomodoro(bot=context.bot, chat_id=update.effective_chat.id)
            await query.edit_message_text(
                "Ops! Tive que iniciar seu Pomodoro. Por favor, tente novamente a ação desejada. 🚀",
                reply_markup=self._get_pomodoro_menu_keyboard()
            )
            return self.POMODORO_MENU_STATE

        pomodoro_instance = context.user_data['pomodoro_instance']
        
        # Se o timer não estiver ativo, ou se já houver uma mensagem de status em andamento,
        # vamos usar o ID da mensagem da query para exibir o status.
        # Se o timer estiver ativo, o _rodar_temporizador já está atualizando.
        response = pomodoro_instance.status()
        try:
            # Sempre tenta editar a mensagem da query.
            message = await query.edit_message_text(
                response,
                reply_markup=pomodoro_instance._get_pomodoro_menu_keyboard(),
                parse_mode='Markdown'
            )
            # Ao clicar em "Status", queremos que esta seja a mensagem que o timer vai atualizar.
            pomodoro_instance._current_status_message_id = message.message_id
        except Exception as e:
            if "Message is not modified" not in str(e): 
                new_message = await query.message.reply_text(
                    "Não consegui atualizar a mensagem anterior. Aqui está o novo status:\n" + response,
                    reply_markup=pomodoro_instance._get_pomodoro_menu_keyboard(),
                    parse_mode='Markdown'
                )
                pomodoro_instance._current_status_message_id = new_message.message_id
            else:
                pass # Se for apenas "not modified", não faz nada

        return self.POMODORO_MENU_STATE


    async def _show_config_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o botão 'Configurar', mostrando o menu de configuração."""
        query = update.callback_query
        await query.answer()

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
        
        if 'pomodoro_instance' in context.user_data:
            pomodoro_instance = context.user_data['pomodoro_instance']
            if pomodoro_instance._timer_task and not pomodoro_instance._timer_task.done():
                pomodoro_instance._timer_task.cancel() # Cancela a tarefa
                try:
                    await pomodoro_instance._timer_task # Aguarda o cancelamento
                except asyncio.CancelledError:
                    pass
                pomodoro_instance._timer_task = None
            pomodoro_instance._current_status_message_id = None # Limpa o ID da mensagem de status ao sair
        return ConversationHandler.END 

    # --- Método para Obter o ConversationHandler do Pomodoro ---

    def get_pomodoro_conversation_handler(self):
        """
        Retorna o ConversationHandler completo para a funcionalidade do Pomodoro.
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
                ConversationHandler.END: ConversationHandler.END, 
            },
        )

    async def _fallback_pomodoro_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Lida com mensagens de texto inesperadas dentro do fluxo do Pomodoro."""
        if 'pomodoro_instance' not in context.user_data:
            context.user_data['pomodoro_instance'] = Pomodoro(bot=context.bot, chat_id=update.effective_chat.id)
            await update.message.reply_text(
                "Ops! Tive que iniciar seu Pomodoro. Por favor, tente novamente a ação desejada. 🚀",
                reply_markup=self._get_pomodoro_menu_keyboard()
            )
            return self.POMODORO_MENU_STATE 

        pomodoro_instance = context.user_data['pomodoro_instance'] 
        keyboard = pomodoro_instance._get_pomodoro_menu_keyboard() if hasattr(pomodoro_instance, '_get_pomodoro_menu_keyboard') else None

        if update.message:
            await update.message.reply_text(
                "Desculpe, não entendi. Por favor, use os botões ou siga as instruções. 🤷‍♀️",
                reply_markup=keyboard
            )
        elif update.callback_query:
            await update.callback_query.answer("Ação inválida para este momento. Por favor, use os botões! 🚫")
            # Tenta editar a mensagem, mas pode falhar se a mensagem já foi apagada
            try:
                await update.callback_query.edit_message_text(
                    "Ação inválida. Escolha uma opção:",
                    reply_markup=keyboard
                )
            except Exception as e:
                # Se não conseguir editar, envia uma nova mensagem
                await update.callback_query.message.reply_text(
                    "Ação inválida. Escolha uma opção:",
                    reply_markup=keyboard
                )
        
        # Limpa o ID da mensagem de status apenas se o timer não estiver rodando ativamente
        if 'pomodoro_instance' in context.user_data and (not pomodoro_instance._timer_task or pomodoro_instance._timer_task.done()):
            context.user_data['pomodoro_instance']._current_status_message_id = None
        return self.POMODORO_MENU_STATE
