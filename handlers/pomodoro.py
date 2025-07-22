import time
import asyncio
import logging # <-- Importar logging
import traceback # <-- Importar traceback para detalhes de erro

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
)

# --- Configuração do Logger para este módulo ---
# Garante que os logs de 'pomodoro' apareçam na saída padrão do Railway
logger = logging.getLogger(__name__)
# O nível de log pode ser ajustado no Railway via variável de ambiente LOG_LEVEL (ex: DEBUG, INFO, ERROR)
# Se não for definido, o padrão será INFO (definido no main.py)


class Pomodoro:
    # --- Conversation States for Pomodoro ---
    POMODORO_MENU_STATE = 0
    CONFIG_MENU_STATE = 1
    SET_FOCUS_TIME_STATE = 2
    SET_SHORT_BREAK_TIME_STATE = 3
    SET_LONG_BREAK_TIME_STATE = 4
    SET_CYCLES_STATE = 5

    # Intervalo para atualização da mensagem de status no Telegram (em segundos)
    ATUALIZACAO_STATUS_INTERVAL = 1

    def __init__(self, bot=None, chat_id=None):
        logger.info(f"Inicializando instância Pomodoro para chat_id: {chat_id}")
        try:
            self.foco_tempo = 25 * 60
            self.pausa_curta_tempo = 5 * 60
            self.pausa_longa_tempo = 15 * 60
            self.ciclos_para_pausa_longa = 4

            self.estado = "ocioso"
            self.tempo_restante = 0
            self.ciclos_completados = 0
            self.tipo_atual = None

            self.historico_foco_total = 0
            self.historico_pausa_curta_total = 0
            self.historico_pausa_longa_total = 0
            self.historico_ciclos_completados = 0

            self._timer_task = None
            self._current_status_message_id = None

            self.bot = bot
            self.chat_id = chat_id
            logger.info("Instância Pomodoro inicializada com sucesso.")
        except Exception as e:
            logger.error(f"Erro na inicialização da classe Pomodoro: {e}", exc_info=True)

    def _formatar_tempo(self, segundos):
        """Formata segundos em MM:SS."""
        try:
            min = segundos // 60
            sec = segundos % 60
            return f"{min:02d}:{sec:02d}"
        except Exception as e:
            logger.error(f"Erro ao formatar tempo ({segundos} segundos): {e}", exc_info=True)
            return "00:00" # Retorna um valor padrão em caso de erro

    async def _rodar_temporizador(self):
        """
        Função assíncrona interna para gerenciar a contagem regressiva e atualização da mensagem.
        Esta função roda diretamente no loop de eventos do bot como uma tarefa.
        """
        logger.info(f"Iniciando _rodar_temporizador para chat {self.chat_id} no estado {self.estado}")
        try:
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
                        logger.debug(f"Mensagem de status atualizada para chat {self.chat_id}. Tempo restante: {self._formatar_tempo(self.tempo_restante)}")
                    except Exception as e:
                        error_str = str(e).lower()
                        if "message to edit not found" in error_str or "message can't be edited" in error_str:
                            logger.warning(f"Mensagem de status não encontrada ou não pode ser editada para chat {self.chat_id}. Limpando ID: {e}")
                            self._current_status_message_id = None
                            # Se a mensagem foi perdida, podemos tentar enviar uma nova para continuar o feedback
                            try:
                                new_msg = await self.bot.send_message(
                                    chat_id=self.chat_id,
                                    text=self.status(),
                                    reply_markup=self._get_pomodoro_menu_keyboard(),
                                    parse_mode='Markdown'
                                )
                                self._current_status_message_id = new_msg.message_id
                                logger.info(f"Nova mensagem de status enviada após perda da anterior para chat {self.chat_id}.")
                            except Exception as new_e:
                                logger.error(f"Falha ao enviar nova mensagem de status para {self.chat_id}: {new_e}", exc_info=True)
                        elif "message is not modified" not in error_str:
                            logger.error(f"Erro inesperado ao atualizar mensagem de status para chat {self.chat_id}: {e}", exc_info=True)
                        # else: Apenas "message is not modified", é um comportamento esperado, não precisa de log.

                await asyncio.sleep(self.ATUALIZACAO_STATUS_INTERVAL)
                self.tempo_restante -= self.ATUALIZACAO_STATUS_INTERVAL

            self.tempo_restante = 0 # Garante que o tempo restante não seja negativo

            # Envia a última atualização de status quando o tempo chega a zero
            if self._current_status_message_id and self.bot and self.chat_id:
                try:
                    await self.bot.edit_message_text(
                        chat_id=self.chat_id,
                        message_id=self._current_status_message_id,
                        text=self.status(),
                        reply_markup=self._get_pomodoro_menu_keyboard(),
                        parse_mode='Markdown'
                    )
                    logger.info(f"Última atualização de status enviada (tempo zerado) para chat {self.chat_id}.")
                except Exception as e:
                    logger.warning(f"Erro ao enviar última atualização de status (tempo zerado) para chat {self.chat_id}: {e}")
            
            await self._proximo_estado()
            logger.info(f"Temporizador concluído e transição para o próximo estado para chat {self.chat_id}.")

        except asyncio.CancelledError:
            logger.info(f"Temporizador do Pomodoro cancelado para chat {self.chat_id}.")
        except Exception as e:
            logger.critical(f"Erro CRÍTICO no _rodar_temporizador para chat {self.chat_id}: {e}", exc_info=True)
        finally:
            self._timer_task = None # Limpa a tarefa do temporizador quando ela termina o ciclo ou é cancelada


    async def _proximo_estado(self):
        """Lógica para transição para o próximo estado do Pomodoro (foco, pausa curta, pausa longa)."""
        logger.info(f"Iniciando _proximo_estado para chat {self.chat_id}. Estado atual: {self.estado}")
        msg_notificacao = ""
        try:
            if self.estado == "foco":
                self.historico_foco_total += self.foco_tempo
                self.ciclos_completados += 1
                self.historico_ciclos_completados += 1

                if self.ciclos_completados % self.ciclos_para_pausa_longa == 0:
                    self.estado = "pausa_longa"
                    self.tempo_restante = self.pausa_longa_tempo
                    self.tipo_atual = "pausa_longa"
                    msg_notificacao = "🎉 UAU! Hora da Pausa Longa! Respire fundo, você mereceu essa pausa! 🧘‍♀️"
                    logger.info(f"Ciclo de foco completo. Transição para Pausa Longa para chat {self.chat_id}.")
                else:
                    self.estado = "pausa_curta"
                    self.tempo_restante = self.pausa_curta_tempo
                    self.tipo_atual = "pausa_curta"
                    msg_notificacao = "☕ Hora da Pausa Curta! Estique as pernas, tome uma água. Você está indo muito bem! ✨"
                    logger.info(f"Ciclo de foco completo. Transição para Pausa Curta para chat {self.chat_id}.")

            elif self.estado in ["pausa_curta", "pausa_longa"]:
                if self.estado == "pausa_curta":
                    self.historico_pausa_curta_total += self.pausa_curta_tempo
                else:
                    self.historico_pausa_longa_total += self.pausa_longa_tempo

                self.estado = "foco"
                self.tempo_restante = self.foco_tempo
                self.tipo_atual = "foco"
                msg_notificacao = "🚀 De volta ao Foco! Vamos lá, a produtividade te espera! 💪"
                logger.info(f"Período de pausa completo. Transição para Foco para chat {self.chat_id}.")
            else:
                self.estado = "ocioso"
                self.tempo_restante = 0
                self.tipo_atual = None
                msg_notificacao = "Pomodoro concluído! Pronto para o próximo ciclo? 🎉"
                logger.info(f"Estado Pomodoro resetado para ocioso para chat {self.chat_id}.")

            if self.bot and self.chat_id and msg_notificacao:
                try:
                    await self.bot.send_message(self.chat_id, msg_notificacao)
                    logger.info(f"Notificação de estado enviada para chat {self.chat_id}: {msg_notificacao}")
                except Exception as e:
                    logger.error(f"Erro ao enviar mensagem de notificação de próximo estado para {self.chat_id}: {e}", exc_info=True)

                if self.estado != "ocioso":
                    try:
                        status_msg = await self.bot.send_message(
                            self.chat_id,
                            self.status(),
                            reply_markup=self._get_pomodoro_menu_keyboard(),
                            parse_mode='Markdown'
                        )
                        self._current_status_message_id = status_msg.message_id
                        logger.info(f"Mensagem de status inicial do próximo ciclo enviada para chat {self.chat_id}. ID: {self._current_status_message_id}")

                        self._timer_task = asyncio.create_task(self._rodar_temporizador())
                        logger.info(f"Nova tarefa de temporizador criada para chat {self.chat_id}.")
                    except Exception as e:
                        logger.error(f"Erro ao enviar mensagem de status ou iniciar nova tarefa do timer para {self.chat_id}: {e}", exc_info=True)
                        self._current_status_message_id = None
                else:
                    self._current_status_message_id = None
                    logger.info(f"Pomodoro no estado ocioso. _current_status_message_id limpo para chat {self.chat_id}.")

        except Exception as e:
            logger.critical(f"Erro CRÍTICO na lógica de transição de _proximo_estado para chat {self.chat_id}: {e}", exc_info=True)


    async def iniciar(self):
        """Inicia ou retoma o temporizador Pomodoro."""
        logger.info(f"Chamada para iniciar/retomar Pomodoro para chat {self.chat_id}.")
        try:
            if not self.bot or not self.chat_id:
                logger.error(f"Bot ou chat_id não definidos para iniciar Pomodoro. Bot: {self.bot}, Chat ID: {self.chat_id}")
                return "Ops! O bot não foi inicializado corretamente para o Pomodoro. Tente novamente mais tarde. 😢"

            if self._timer_task and not self._timer_task.done():
                logger.info(f"Pomodoro já está rodando para chat {self.chat_id}.")
                return "O Pomodoro já está rodando! Mantenha o foco. 🎯"

            response = ""
            initial_status_msg_text = ""

            if self.estado == "ocioso":
                self.estado = "foco"
                self.tempo_restante = self.foco_tempo
                self.tipo_atual = "foco"
                response = "🎉 Pomodoro iniciado! Hora de focar e brilhar! ✨"
                initial_status_msg_text = f"🌟 Iniciando seu período de {self.tipo_atual.capitalize()}! Tempo: {self._formatar_tempo(self.foco_tempo)} 🎉"
                logger.info(f"Novo Pomodoro iniciado (estado ocioso -> foco) para chat {self.chat_id}.")
            elif self.estado == "pausado":
                self.estado = self.tipo_atual
                response = "▶️ Pomodoro retomado! Vamos continuar firme! 💪"
                initial_status_msg_text = f"🚀 Retomando seu período de {self.tipo_atual.capitalize()}! Tempo restante: {self._formatar_tempo(self.tempo_restante)} ⏳"
                logger.info(f"Pomodoro retomado (estado pausado -> {self.tipo_atual}) para chat {self.chat_id}.")
            else:
                logger.warning(f"Tentativa de iniciar Pomodoro em estado inesperado ({self.estado}) para chat {self.chat_id}.")
                return "O Pomodoro já está em andamento. Use o botão 'Parar' para finalizar ou 'Pausar'. ⏯️"
            
            # Envia a mensagem de status inicial e armazena seu ID
            try:
                if self._current_status_message_id:
                    status_message = await self.bot.edit_message_text(
                        chat_id=self.chat_id,
                        message_id=self._current_status_message_id,
                        text=initial_status_msg_text,
                        reply_markup=self._get_pomodoro_menu_keyboard(),
                        parse_mode='Markdown'
                    )
                    logger.info(f"Mensagem de status inicial editada para chat {self.chat_id}. ID: {self._current_status_message_id}")
                else:
                    status_message = await self.bot.send_message(
                        self.chat_id,
                        initial_status_msg_text,
                        reply_markup=self._get_pomodoro_menu_keyboard(),
                        parse_mode='Markdown'
                    )
                    logger.info(f"Nova mensagem de status inicial enviada para chat {self.chat_id}.")
                self._current_status_message_id = status_message.message_id
            except Exception as e:
                logger.error(f"Erro ao enviar/editar mensagem inicial do Pomodoro para {self.chat_id}: {e}", exc_info=True)
                # Tenta enviar uma nova mensagem sem rastreá-la se a edição falhar
                try:
                    await self.bot.send_message(
                        self.chat_id,
                        "Ops! Não consegui enviar a mensagem inicial do Pomodoro. Mas o timer foi iniciado! 😢"
                    )
                    self._current_status_message_id = None # Garante que não está rastreando uma mensagem inválida
                except Exception as send_e:
                    logger.critical(f"Erro FATAL: Não foi possível enviar nem a mensagem de fallback para {self.chat_id}: {send_e}", exc_info=True)
                    # Não há muito o que fazer aqui se nem a mensagem de fallback for...
                    return "Erro grave ao iniciar Pomodoro. Tente novamente mais tarde. 😭"

            self._timer_task = asyncio.create_task(self._rodar_temporizador())
            logger.info(f"Tarefa do temporizador iniciada para chat {self.chat_id}.")
            return response
        except Exception as e:
            logger.critical(f"Erro CRÍTICO na função iniciar() do Pomodoro para chat {self.chat_id}: {e}", exc_info=True)
            return "Ocorreu um erro inesperado ao tentar iniciar o Pomodoro. Por favor, tente novamente. 😭"

    async def pausar(self):
        """Pausa o temporizador Pomodoro."""
        logger.info(f"Chamada para pausar Pomodoro para chat {self.chat_id}. Estado atual: {self.estado}")
        try:
            if self.estado in ["foco", "pausa_curta", "pausa_longa"]:
                if self._timer_task and not self._timer_task.done():
                    self._timer_task.cancel()
                    try:
                        await self._timer_task
                    except asyncio.CancelledError:
                        logger.info(f"Tarefa do temporizador cancelada com sucesso para chat {self.chat_id}.")
                    except Exception as e:
                        logger.error(f"Erro inesperado ao aguardar cancelamento da tarefa para chat {self.chat_id}: {e}", exc_info=True)
                    self._timer_task = None
                else:
                    logger.warning(f"Tentativa de pausar Pomodoro, mas _timer_task não está ativo para chat {self.chat_id}.")
                self.estado = "pausado"
                logger.info(f"Pomodoro pausado para chat {self.chat_id}.")
                return "⏸️ Pomodoro pausado. Você pode retomar a qualquer momento! 😌"
            elif self.estado == "pausado":
                logger.info(f"Tentativa de pausar Pomodoro que já está pausado para chat {self.chat_id}.")
                return "O Pomodoro já está pausado. Que tal retomar? ▶️"
            else:
                logger.info(f"Tentativa de pausar Pomodoro que não está ativo para chat {self.chat_id}. Estado: {self.estado}")
                return "Não há Pomodoro ativo para pausar. Que tal começar um? 🚀"
        except Exception as e:
            logger.critical(f"Erro CRÍTICO na função pausar() do Pomodoro para chat {self.chat_id}: {e}", exc_info=True)
            return "Ocorreu um erro inesperado ao tentar pausar o Pomodoro. 😥"

    async def parar(self):
        """Para o temporizador Pomodoro, reseta o estado e gera um relatório."""
        logger.info(f"Chamada para parar Pomodoro para chat {self.chat_id}. Estado atual: {self.estado}")
        try:
            if self.estado == "ocioso":
                logger.info(f"Tentativa de parar Pomodoro que já está ocioso para chat {self.chat_id}.")
                return "Não há Pomodoro ativo para parar. Seu dia está livre! 🎉"

            if self._timer_task and not self._timer_task.done():
                self._timer_task.cancel()
                try:
                    await self._timer_task
                except asyncio.CancelledError:
                    logger.info(f"Tarefa do temporizador cancelada com sucesso ao parar para chat {self.chat_id}.")
                except Exception as e:
                    logger.error(f"Erro inesperado ao aguardar cancelamento da tarefa ao parar para chat {self.chat_id}: {e}", exc_info=True)
                self._timer_task = None
            else:
                logger.warning(f"Tentativa de parar Pomodoro, mas _timer_task não está ativo para chat {self.chat_id}.")

            report = self.gerar_relatorio()
            logger.info(f"Relatório gerado para chat {self.chat_id}.")

            self.estado = "ocioso"
            self.tempo_restante = 0
            self.tipo_atual = None
            self.ciclos_completados = 0

            self.historico_foco_total = 0
            self.historico_pausa_curta_total = 0
            self.historico_pausa_longa_total = 0
            self.historico_ciclos_completados = 0
            self._current_status_message_id = None
            logger.info(f"Pomodoro resetado e histórico limpo para chat {self.chat_id}.")

            return "⏹️ Pomodoro parado! Aqui está o resumo da sua sessão:\n\n" + report + "\n\nInicie um novo ciclo quando estiver pronto para arrasar de novo! ✨"
        except Exception as e:
            logger.critical(f"Erro CRÍTICO na função parar() do Pomodoro para chat {self.chat_id}: {e}", exc_info=True)
            return "Ocorreu um erro inesperado ao tentar parar o Pomodoro. 😥"

    def status(self):
        """Retorna o status atual do Pomodoro, incluindo o tempo restante."""
        try:
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
        except Exception as e:
            logger.error(f"Erro ao gerar status do Pomodoro para chat {self.chat_id}: {e}", exc_info=True)
            return "Ops! Não consegui carregar o status. 😟"

    async def configurar(self, tipo_config, valor):
        """Permite configurar os tempos do Pomodoro."""
        logger.info(f"Chamada para configurar Pomodoro para chat {self.chat_id}. Tipo: {tipo_config}, Valor: {valor}")
        try:
            if self.estado != "ocioso":
                logger.warning(f"Tentativa de configurar Pomodoro ativo/pausado para chat {self.chat_id}. Estado: {self.estado}")
                return False, "Ops! Não é possível configurar enquanto o Pomodoro está ativo ou pausado. Por favor, pare-o primeiro. 🛑"

            if not isinstance(valor, int) or valor <= 0:
                logger.warning(f"Valor de configuração inválido ({valor}) para chat {self.chat_id}. Tipo: {type(valor)}")
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
                logger.error(f"Tipo de configuração desconhecido ({tipo_config}) para chat {self.chat_id}.")
                return False, "Tipo de configuração desconhecido. 😕"
            
            logger.info(f"Configuração '{tipo_config}' atualizada para {valor} para chat {self.chat_id}.")
            return True, (f"✨ Configuração de *{tipo_config.replace('_', ' ').capitalize()}* "
                            f"atualizada para *{valor} min* (ou ciclos)! Perfeito! ✅")
        except Exception as e:
            logger.critical(f"Erro CRÍTICO na função configurar() do Pomodoro para chat {self.chat_id}: {e}", exc_info=True)
            return False, "Ocorreu um erro inesperado ao configurar o Pomodoro. 😥"

    def get_config_status(self):
        """Retorna as configurações atuais do Pomodoro formatadas."""
        try:
            return (f"Configurações atuais do seu Pomodoro:\n"
                    f"🍅 *Foco:* {self.foco_tempo // 60} min\n"
                    f"☕ *Pausa Curta:* {self.pausa_curta_tempo // 60} min\n"
                    f"🛋️ *Pausa Longa:* {self.pausa_longa_tempo // 60} min\n"
                    f"🔄 *Ciclos para Pausa Longa:* {self.ciclos_para_pausa_longa}")
        except Exception as e:
            logger.error(f"Erro ao obter status de configuração do Pomodoro para chat {self.chat_id}: {e}", exc_info=True)
            return "Ops! Não consegui carregar as configurações. 😟"

    def gerar_relatorio(self):
        """Calcula e retorna o relatório final de tempo de foco, pausas e ciclos."""
        logger.info(f"Gerando relatório Pomodoro para chat {self.chat_id}.")
        try:
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

            if self.historico_foco_total == 0 and self.historico_pausa_curta_total == 0 and \
               self.historico_pausa_longa_total == 0 and self.historico_ciclos_completados == 0:
                logger.info(f"Relatório vazio gerado para chat {self.chat_id}.")
                return "Parece que você ainda não completou nenhum ciclo ou período de foco. Que tal começar um? 🚀"

            relatorio = (f"--- 📊 Relatório da Sua Sessão de Produtividade! ---\n"
                         f"**Foco total:** {horas_foco}h {min_foco}min 🧠\n"
                         f"**Pausa Curta total:** {horas_pausa_curta}h {min_pausa_curta}min ☕\n"
                         f"**Pausa Longa total:** {horas_pausa_longa}h {min_pausa_longa}min 🧘‍♀️\n"
                         f"**Ciclos de foco completos:** {self.historico_ciclos_completados} 🏆\n"
                         f"**Tempo total da sessão:** {horas_geral}h {min_geral}min ✅")
            logger.info(f"Relatório gerado com sucesso para chat {self.chat_id}.")
            return relatorio
        except Exception as e:
            logger.critical(f"Erro CRÍTICO ao gerar relatório do Pomodoro para chat {self.chat_id}: {e}", exc_info=True)
            return "Ops! Ocorreu um erro ao gerar o relatório. 😥"

    # --- Métodos para Gerar Menus de Botões Inline ---

    def _get_pomodoro_menu_keyboard(self):
        """Retorna o teclado inline para o menu principal do Pomodoro."""
        try:
            keyboard = [
                [InlineKeyboardButton("▶️ Iniciar", callback_data="pomodoro_iniciar"),
                 InlineKeyboardButton("⏸️ Pausar", callback_data="pomodoro_pausar")],
                [InlineKeyboardButton("⏹️ Parar", callback_data="pomodoro_parar"),
                 InlineKeyboardButton("📊 Status", callback_data="pomodoro_status")],
                [InlineKeyboardButton("⚙️ Configurar", callback_data="pomodoro_configurar")],
                [InlineKeyboardButton("⬅️ Voltar ao Início", callback_data="main_menu_return")],
            ]
            return InlineKeyboardMarkup(keyboard)
        except Exception as e:
            logger.error(f"Erro ao gerar teclado do menu Pomodoro para chat {self.chat_id}: {e}", exc_info=True)
            return InlineKeyboardMarkup([]) # Retorna teclado vazio para evitar travamento

    def _get_config_menu_keyboard(self):
        """Retorna o teclado inline para o menu de configuração do Pomodoro."""
        try:
            keyboard = [
                [InlineKeyboardButton("Foco", callback_data="config_foco"),
                 InlineKeyboardButton("Pausa Curta", callback_data="config_pausa_curta")],
                [InlineKeyboardButton("Pausa Longa", callback_data="config_pausa_longa"),
                 InlineKeyboardButton("Ciclos", callback_data="config_ciclos")],
                [InlineKeyboardButton("⬅️ Voltar ao Pomodoro", callback_data="pomodoro_menu")],
            ]
            return InlineKeyboardMarkup(keyboard)
        except Exception as e:
            logger.error(f"Erro ao gerar teclado de configuração do Pomodoro para chat {self.chat_id}: {e}", exc_info=True)
            return InlineKeyboardMarkup([])

    # --- Handlers de Callback do Pomodoro ---

    async def _show_pomodoro_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Exibe o menu principal do Pomodoro."""
        logger.info(f"Exibindo menu Pomodoro para chat {update.effective_chat.id}.")
        try:
            query = update.callback_query
            if not query:
                logger.warning(f"CallbackQuery nulo em _show_pomodoro_menu para update {update}.")
                if update.message:
                    await update.message.reply_text("Ops! Não consegui exibir o menu Pomodoro. Tente usar os botões. 😅")
                return self.POMODORO_MENU_STATE

            await query.edit_message_text(
                "Bem-vindo ao seu assistente Pomodoro! 🍅 Escolha uma ação e vamos ser produtivos! ✨",
                reply_markup=self._get_pomodoro_menu_keyboard()
            )
            logger.info(f"Menu Pomodoro exibido com sucesso para chat {update.effective_chat.id}.")
            return self.POMODORO_MENU_STATE
        except Exception as e:
            logger.error(f"Erro em _show_pomodoro_menu para chat {update.effective_chat.id}: {e}", exc_info=True)
            if query:
                await query.answer("Ops! Não consegui exibir o menu Pomodoro. 😥")
                await query.edit_message_text("Ocorreu um erro ao carregar o menu. Por favor, tente novamente mais tarde. 😭")
            elif update.message:
                await update.message.reply_text("Ocorreu um erro ao carregar o menu. Por favor, tente novamente mais tarde. 😭")
            return self.POMODORO_MENU_STATE # Tenta manter o estado, mas o ideal é que seja capturado no main

    async def _pomodoro_iniciar_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o botão 'Iniciar'."""
        logger.info(f"Callback 'pomodoro_iniciar' recebido para chat {update.effective_chat.id}.")
        try:
            query = update.callback_query
            if not query:
                logger.warning(f"CallbackQuery nulo em _pomodoro_iniciar_callback para update {update}.")
                return self.POMODORO_MENU_STATE # Não tem query para responder, tenta voltar ao estado

            await query.answer()

            if 'pomodoro_instance' not in context.user_data:
                logger.warning(f"Instância Pomodoro não encontrada em user_data ao iniciar para chat {update.effective_chat.id}. Criando nova.")
                context.user_data['pomodoro_instance'] = Pomodoro(bot=context.bot, chat_id=update.effective_chat.id)
                await query.edit_message_text(
                    "Ops! Tive que reiniciar seu Pomodoro. Por favor, tente novamente a ação desejada. 🚀",
                    reply_markup=self._get_pomodoro_menu_keyboard()
                )
                return self.POMODORO_MENU_STATE

            pomodoro_instance = context.user_data['pomodoro_instance']
            
            # Garante que bot e chat_id estão atualizados na instância, caso haja uma nova sessão
            pomodoro_instance.bot = context.bot
            pomodoro_instance.chat_id = update.effective_chat.id
            logger.debug(f"Instância Pomodoro atualizada com bot e chat_id para chat {update.effective_chat.id}.")

            response = await pomodoro_instance.iniciar()
            await query.edit_message_text(
                response,
                reply_markup=self._get_pomodoro_menu_keyboard(),
                parse_mode='Markdown'
            )
            logger.info(f"Comando 'iniciar' processado com sucesso para chat {update.effective_chat.id}. Resposta: {response[:50]}...")
            return self.POMODORO_MENU_STATE
        except Exception as e:
            logger.error(f"Erro em _pomodoro_iniciar_callback para chat {update.effective_chat.id}: {e}", exc_info=True)
            if query:
                await query.answer("Ops! Ocorreu um erro ao iniciar o Pomodoro. 😥")
                await query.edit_message_text("Desculpe, não consegui iniciar o Pomodoro agora. Por favor, tente novamente. 😭", reply_markup=self._get_pomodoro_menu_keyboard())
            return self.POMODORO_MENU_STATE


    async def _pomodoro_pausar_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o botão 'Pausar'."""
        logger.info(f"Callback 'pomodoro_pausar' recebido para chat {update.effective_chat.id}.")
        try:
            query = update.callback_query
            if not query:
                logger.warning(f"CallbackQuery nulo em _pomodoro_pausar_callback para update {update}.")
                return self.POMODORO_MENU_STATE

            await query.answer()

            if 'pomodoro_instance' not in context.user_data:
                logger.warning(f"Instância Pomodoro não encontrada em user_data ao pausar para chat {update.effective_chat.id}. Criando nova.")
                context.user_data['pomodoro_instance'] = Pomodoro(bot=context.bot, chat_id=update.effective_chat.id)
                await query.edit_message_text(
                    "Ops! Tive que reiniciar seu Pomodoro. Por favor, tente novamente a ação desejada. 🚀",
                    reply_markup=self._get_pomodoro_menu_keyboard()
                )
                return self.POMODORO_MENU_STATE

            pomodoro_instance = context.user_data['pomodoro_instance']
            pomodoro_instance.bot = context.bot # Atualiza bot/chat_id também aqui
            pomodoro_instance.chat_id = update.effective_chat.id
            
            response = await pomodoro_instance.pausar()
            await query.edit_message_text(response, reply_markup=self._get_pomodoro_menu_keyboard(), parse_mode='Markdown')
            logger.info(f"Comando 'pausar' processado com sucesso para chat {update.effective_chat.id}. Resposta: {response[:50]}...")
            return self.POMODORO_MENU_STATE
        except Exception as e:
            logger.error(f"Erro em _pomodoro_pausar_callback para chat {update.effective_chat.id}: {e}", exc_info=True)
            if query:
                await query.answer("Ops! Ocorreu um erro ao pausar o Pomodoro. 😥")
                await query.edit_message_text("Desculpe, não consegui pausar o Pomodoro agora. Por favor, tente novamente. 😭", reply_markup=self._get_pomodoro_menu_keyboard())
            return self.POMODORO_MENU_STATE

    async def _pomodoro_parar_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o botão 'Parar' e exibição do relatório."""
        logger.info(f"Callback 'pomodoro_parar' recebido para chat {update.effective_chat.id}.")
        try:
            query = update.callback_query
            if not query:
                logger.warning(f"CallbackQuery nulo em _pomodoro_parar_callback para update {update}.")
                return self.POMODORO_MENU_STATE

            await query.answer()

            if 'pomodoro_instance' not in context.user_data:
                logger.warning(f"Instância Pomodoro não encontrada em user_data ao parar para chat {update.effective_chat.id}. Criando nova.")
                context.user_data['pomodoro_instance'] = Pomodoro(bot=context.bot, chat_id=update.effective_chat.id)
                await query.edit_message_text(
                    "Ops! Tive que reiniciar seu Pomodoro. Por favor, tente novamente a ação desejada. 🚀",
                    reply_markup=self._get_pomodoro_menu_keyboard()
                )
                return self.POMODORO_MENU_STATE

            pomodoro_instance = context.user_data['pomodoro_instance']
            pomodoro_instance.bot = context.bot # Atualiza bot/chat_id também aqui
            pomodoro_instance.chat_id = update.effective_chat.id
            
            response = await pomodoro_instance.parar()
            await query.edit_message_text(response, parse_mode='Markdown', reply_markup=self._get_pomodoro_menu_keyboard())
            logger.info(f"Comando 'parar' processado com sucesso para chat {update.effective_chat.id}. Resposta: {response[:50]}...")
            return self.POMODORO_MENU_STATE
        except Exception as e:
            logger.error(f"Erro em _pomodoro_parar_callback para chat {update.effective_chat.id}: {e}", exc_info=True)
            if query:
                await query.answer("Ops! Ocorreu um erro ao parar o Pomodoro. 😥")
                await query.edit_message_text("Desculpe, não consegui parar o Pomodoro agora. Por favor, tente novamente. 😭", reply_markup=self._get_pomodoro_menu_keyboard())
            return self.POMODORO_MENU_STATE

    async def _pomodoro_status_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o botão 'Status'. Atualiza com contagem regressiva em tempo real."""
        logger.info(f"Callback 'pomodoro_status' recebido para chat {update.effective_chat.id}.")
        try:
            query = update.callback_query
            if not query:
                logger.warning(f"CallbackQuery nulo em _pomodoro_status_callback para update {update}.")
                return self.POMODORO_MENU_STATE

            await query.answer("Atualizando status...")
            
            if 'pomodoro_instance' not in context.user_data:
                logger.warning(f"Instância Pomodoro não encontrada em user_data ao verificar status para chat {update.effective_chat.id}. Criando nova.")
                context.user_data['pomodoro_instance'] = Pomodoro(bot=context.bot, chat_id=update.effective_chat.id)
                await query.edit_message_text(
                    "Ops! Tive que reiniciar seu Pomodoro. Por favor, tente novamente a ação desejada. 🚀",
                    reply_markup=self._get_pomodoro_menu_keyboard()
                )
                return self.POMODORO_MENU_STATE

            pomodoro_instance = context.user_data['pomodoro_instance']
            pomodoro_instance.bot = context.bot # Atualiza bot/chat_id também aqui
            pomodoro_instance.chat_id = update.effective_chat.id
            
            response = pomodoro_instance.status()
            try:
                message = await query.edit_message_text(
                    response,
                    reply_markup=pomodoro_instance._get_pomodoro_menu_keyboard(),
                    parse_mode='Markdown'
                )
                # Ao clicar em "Status", queremos que esta seja a mensagem que o timer vai atualizar.
                pomodoro_instance._current_status_message_id = message.message_id
                logger.info(f"Status do Pomodoro exibido/atualizado para chat {update.effective_chat.id}. Mensagem ID: {message.message_id}")
            except Exception as e:
                error_str = str(e).lower()
                if "message is not modified" not in error_str:
                    logger.warning(f"Não conseguiu editar a mensagem de status para chat {update.effective_chat.id}. Tentando enviar nova: {e}", exc_info=True)
                    new_message = await query.message.reply_text( # Usa query.message.reply_text
                        "Não consegui atualizar a mensagem anterior. Aqui está o novo status:\n" + response,
                        reply_markup=pomodoro_instance._get_pomodoro_menu_keyboard(),
                        parse_mode='Markdown'
                    )
                    pomodoro_instance._current_status_message_id = new_message.message_id
                    logger.info(f"Nova mensagem de status enviada após falha na edição para chat {update.effective_chat.id}. ID: {new_message.message_id}")
                else:
                    logger.debug(f"Mensagem de status não modificada, ignorado para chat {update.effective_chat.id}.")
            return self.POMODORO_MENU_STATE
        except Exception as e:
            logger.error(f"Erro em _pomodoro_status_callback para chat {update.effective_chat.id}: {e}", exc_info=True)
            if query:
                await query.answer("Ops! Ocorreu um erro ao obter o status do Pomodoro. 😥")
                await query.edit_message_text("Desculpe, não consegui obter o status agora. Por favor, tente novamente. 😭", reply_markup=self._get_pomodoro_menu_keyboard())
            return self.POMODORO_MENU_STATE


    async def _show_config_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o botão 'Configurar', mostrando o menu de configuração."""
        logger.info(f"Callback 'pomodoro_configurar' recebido para chat {update.effective_chat.id}.")
        try:
            query = update.callback_query
            if not query:
                logger.warning(f"CallbackQuery nulo em _show_config_menu para update {update}.")
                return self.CONFIG_MENU_STATE

            await query.answer()

            if 'pomodoro_instance' not in context.user_data:
                logger.warning(f"Instância Pomodoro não encontrada em user_data ao configurar para chat {update.effective_chat.id}. Criando nova.")
                context.user_data['pomodoro_instance'] = Pomodoro(bot=context.bot, chat_id=update.effective_chat.id)
                await query.edit_message_text(
                    "Ops! Tive que reiniciar seu Pomodoro. Por favor, tente novamente a ação desejada. 🚀",
                    reply_markup=self._get_pomodoro_menu_keyboard()
                )
                return self.POMODORO_MENU_STATE

            pomodoro_instance = context.user_data['pomodoro_instance']
            pomodoro_instance.bot = context.bot # Atualiza bot/chat_id também aqui
            pomodoro_instance.chat_id = update.effective_chat.id

            current_config = pomodoro_instance.get_config_status()
            await query.edit_message_text(
                f"⚙️ Configurar Pomodoro:\n{current_config}\n\nEscolha o que deseja alterar: ✨",
                reply_markup=self._get_config_menu_keyboard(), parse_mode='Markdown'
            )
            logger.info(f"Menu de configuração Pomodoro exibido para chat {update.effective_chat.id}.")
            return self.CONFIG_MENU_STATE
        except Exception as e:
            logger.error(f"Erro em _show_config_menu para chat {update.effective_chat.id}: {e}", exc_info=True)
            if query:
                await query.answer("Ops! Ocorreu um erro ao abrir as configurações. 😥")
                await query.edit_message_text("Desculpe, não consegui abrir as configurações agora. Por favor, tente novamente. 😭", reply_markup=self._get_pomodoro_menu_keyboard())
            return self.POMODORO_MENU_STATE


    async def _request_config_value(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Solicita ao usuário que envie o novo valor para a configuração selecionada."""
        logger.info(f"Callback para solicitar valor de configuração para chat {update.effective_chat.id}.")
        try:
            query = update.callback_query
            if not query or not query.data:
                logger.warning(f"CallbackQuery ou query.data nulo em _request_config_value para update {update}.")
                return self.CONFIG_MENU_STATE

            await query.answer()
            config_type = query.data.replace("config_", "")
            context.user_data['config_type'] = config_type
            
            prompt_text = (f"Por favor, envie o novo valor (número inteiro em minutos) "
                            f"para '{config_type.replace('_', ' ').capitalize()}': 🔢")
            await query.edit_message_text(prompt_text)
            logger.info(f"Solicitação de valor para '{config_type}' enviada para chat {update.effective_chat.id}.")
            
            # Retorna o estado apropriado para aguardar a entrada do usuário
            state_map = {
                "foco": self.SET_FOCUS_TIME_STATE,
                "pausa_curta": self.SET_SHORT_BREAK_TIME_STATE,
                "pausa_longa": self.SET_LONG_BREAK_TIME_STATE,
                "ciclos": self.SET_CYCLES_STATE
            }
            return state_map.get(config_type, self.CONFIG_MENU_STATE) # Fallback para CONFIG_MENU_STATE
        except Exception as e:
            logger.error(f"Erro em _request_config_value para chat {update.effective_chat.id}: {e}", exc_info=True)
            if query:
                await query.answer("Ops! Ocorreu um erro ao solicitar a configuração. 😥")
                await query.edit_message_text("Desculpe, não consegui pedir a configuração agora. Tente novamente. 😭", reply_markup=self._get_config_menu_keyboard())
            return self.CONFIG_MENU_STATE

    async def _set_config_value(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Recebe o valor de configuração digitado pelo usuário e o aplica."""
        logger.info(f"Recebendo valor de configuração para chat {update.effective_chat.id}.")
        config_type = context.user_data.get('config_type')
        
        if not config_type:
            logger.warning(f"config_type não encontrado em user_data para chat {update.effective_chat.id}.")
            if update.message:
                await update.message.reply_text("Ops! O tipo de configuração não foi encontrado. Tente novamente! 🤔", reply_markup=self._get_pomodoro_menu_keyboard())
            return self.POMODORO_MENU_STATE

        try:
            if not update.message or not update.message.text:
                logger.warning(f"Mensagem ou texto da mensagem nulo em _set_config_value para update {update}.")
                if update.message:
                    await update.message.reply_text("Por favor, envie um número. 🔢", reply_markup=self._get_config_menu_keyboard())
                return self.CONFIG_MENU_STATE

            value = int(update.message.text)
            if 'pomodoro_instance' not in context.user_data:
                logger.warning(f"Instância Pomodoro não encontrada em user_data ao definir config para chat {update.effective_chat.id}. Criando nova.")
                context.user_data['pomodoro_instance'] = Pomodoro(bot=context.bot, chat_id=update.effective_chat.id)
                await update.message.reply_text(
                    "Ops! Tive que reiniciar seu Pomodoro. Por favor, tente novamente a ação desejada. 🚀",
                    reply_markup=self._get_pomodoro_menu_keyboard()
                )
                return self.POMODORO_MENU_STATE

            pomodoro_instance = context.user_data['pomodoro_instance']
            pomodoro_instance.bot = context.bot # Atualiza bot/chat_id também aqui
            pomodoro_instance.chat_id = update.effective_chat.id

            success, message = await pomodoro_instance.configurar(config_type, value)
            if success:
                await update.message.reply_text(message, reply_markup=self._get_config_menu_keyboard(), parse_mode='Markdown')
                logger.info(f"Configuração '{config_type}' definida para {value} para chat {update.effective_chat.id}.")
            else:
                await update.message.reply_text(message, reply_markup=self._get_config_menu_keyboard())
                logger.warning(f"Falha na configuração '{config_type}' com valor {value} para chat {update.effective_chat.id}. Mensagem: {message}")
        except ValueError:
            logger.warning(f"Valor de configuração não numérico recebido ('{update.message.text}') para chat {update.effective_chat.id}.")
            await update.message.reply_text("Isso não parece um número válido! Por favor, envie um número inteiro. 🔢", reply_markup=self._get_config_menu_keyboard())
        except Exception as e:
            logger.error(f"Erro em _set_config_value para chat {update.effective_chat.id}: {e}", exc_info=True)
            if update.message:
                await update.message.reply_text(f"Ocorreu um erro ao configurar: {e}. Por favor, tente novamente! 😥", reply_markup=self._get_config_menu_keyboard())
        
        # Limpa o tipo de configuração após o uso
        if 'config_type' in context.user_data:
            del context.user_data['config_type']
            logger.debug(f"config_type limpo do user_data para chat {update.effective_chat.id}.")
        
        return self.CONFIG_MENU_STATE

    async def _exit_pomodoro_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para o botão 'Voltar ao Início'."""
        logger.info(f"Callback 'main_menu_return' recebido para chat {update.effective_chat.id}. Saindo do Pomodoro.")
        try:
            query = update.callback_query
            if not query:
                logger.warning(f"CallbackQuery nulo em _exit_pomodoro_conversation para update {update}.")
                return ConversationHandler.END # Tenta encerrar mesmo sem query

            await query.answer("Saindo do Pomodoro. Voltando ao menu principal! 👋")
            
            if 'pomodoro_instance' in context.user_data:
                pomodoro_instance = context.user_data['pomodoro_instance']
                if pomodoro_instance._timer_task and not pomodoro_instance._timer_task.done():
                    pomodoro_instance._timer_task.cancel()
                    try:
                        await pomodoro_instance._timer_task
                    except asyncio.CancelledError:
                        logger.info(f"Tarefa do temporizador cancelada ao sair para chat {update.effective_chat.id}.")
                    except Exception as e:
                        logger.error(f"Erro inesperado ao aguardar cancelamento da tarefa ao sair para chat {update.effective_chat.id}: {e}", exc_info=True)
                    pomodoro_instance._timer_task = None
                pomodoro_instance._current_status_message_id = None
                logger.info(f"Instância Pomodoro limpa ao sair para chat {update.effective_chat.id}.")
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Erro em _exit_pomodoro_conversation para chat {update.effective_chat.id}: {e}", exc_info=True)
            if query:
                await query.answer("Ops! Ocorreu um erro ao sair do Pomodoro. 😥")
                await query.edit_message_text("Desculpe, não consegui voltar ao menu principal agora. Tente novamente. 😭")
            return ConversationHandler.END


    # --- Método para Obter o ConversationHandler do Pomodoro ---

    def get_pomodoro_conversation_handler(self):
        """
        Retorna o ConversationHandler completo para a funcionalidade do Pomodoro.
        Este handler será aninhado no ConversationHandler principal do bot.
        """
        logger.info("Configurando ConversationHandler para Pomodoro.")
        try:
            return ConversationHandler(
                entry_points=[CallbackQueryHandler(self._show_pomodoro_menu, pattern="^open_pomodoro_menu$")],
                states={
                    self.POMODORO_MENU_STATE: [
                        CallbackQueryHandler(self._pomodoro_iniciar_callback, pattern="^pomodoro_iniciar$"),
                        CallbackQueryHandler(self._pomodoro_pausar_callback, pattern="^pomodoro_pausar$"),
                        CallbackQueryHandler(self._pomodoro_parar_callback, pattern="^pomodoro_parar$"),
                        CallbackQueryHandler(self._pomodoro_status_callback, pattern="^pomodoro_status$"),
                        CallbackQueryHandler(self._show_config_menu, pattern="^pomodoro_configurar$"),
                        CallbackQueryHandler(self._show_pomodoro_menu, pattern="^pomodoro_menu$"), # Adicionado para 'Voltar ao Pomodoro' do menu de config
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
                    CallbackQueryHandler(self._exit_pomodoro_conversation, pattern="^main_menu_return$"),
                    MessageHandler(filters.COMMAND | filters.TEXT, self._show_pomodoro_menu) # Fallback para qualquer comando/texto não mapeado
                ],
                map_to_parent={
                    ConversationHandler.END: self.POMODORO_MENU_STATE # Garante que ao sair do pomodoro, volta para o menu principal
                }
            )
        except Exception as e:
            logger.critical(f"Erro CRÍTICO ao configurar ConversationHandler do Pomodoro: {e}", exc_info=True)
            # Retorna um ConversationHandler mínimo para não travar o bot principal
            return ConversationHandler(
                entry_points=[CallbackQueryHandler(self._show_pomodoro_menu, pattern="^open_pomodoro_menu$")],
                states={}, fallbacks=[CallbackQueryHandler(self._exit_pomodoro_conversation, pattern="^main_menu_return$")]
            )
