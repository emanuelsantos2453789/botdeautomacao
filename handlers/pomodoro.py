# pomodoro.py
import time
import threading

class Pomodoro:
    def __init__(self, bot=None, chat_id=None):
        # Configurações padrão
        self.foco_tempo = 25 * 60
        self.pausa_curta_tempo = 5 * 60
        self.pausa_longa_tempo = 15 * 60
        self.ciclos_para_pausa_longa = 4

        # Estado atual do Pomodoro
        self.estado = "ocioso"
        self.tempo_restante = 0
        self.ciclos_completados = 0
        self.tipo_atual = None

        # Histórico de tempos
        self.historico_foco_total = 0
        self.historico_pausa_curta_total = 0
        self.historico_pausa_longa_total = 0
        self.historico_ciclos_completados = 0

        self._timer_thread = None
        self._parar_temporizador = threading.Event()

        # Adicionados para o bot do Telegram
        self.bot = bot
        self.chat_id = chat_id

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
        
        # Envia uma mensagem inicial para o usuário
        if self.bot and self.chat_id:
            await self.bot.send_message(self.chat_id, f"Iniciando {self.tipo_atual.capitalize()}! Tempo: {self._formatar_tempo(self.tempo_restante)}")

        while self.tempo_restante > 0 and not self._parar_temporizador.is_set():
            # Esta parte para o bot não precisa ficar atualizando o tempo a cada segundo
            # Isso poluiria o chat. O usuário pode pedir o status.
            # print(f"DEBUG: Tempo restante: {self.tempo_restante}, Estado: {self.estado}")
            time.sleep(1)
            self.tempo_restante -= 1

        if not self._parar_temporizador.is_set(): # Se o temporizador não foi parado manualmente
            await self._proximo_estado() # Usar await aqui porque _proximo_estado agora é async

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

        # Se o temporizador precisa continuar, inicia a próxima etapa
        if self.estado != "ocioso":
            self._timer_thread = threading.Thread(target=lambda: self.bot.loop.call_soon_threadsafe(self._rodar_temporizador))
            self._timer_thread.start()


    async def iniciar(self):
        """
        Inicia ou retoma o temporizador Pomodoro.
        """
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

            # Executa a função _rodar_temporizador em uma thread separada
            # Usa bot.loop.call_soon_threadsafe para agendar a corrotina no loop de eventos do bot
            self._timer_thread = threading.Thread(target=lambda: self.bot.loop.call_soon_threadsafe(self._rodar_temporizador))
            self._timer_thread.start()
            return response
        else:
            return "O Pomodoro já está em andamento. Use /pausar ou /parar."

    async def pausar(self):
        """
        Pausa o temporizador Pomodoro.
        """
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
        """
        Para o temporizador Pomodoro e reseta tudo, gerando um relatório.
        """
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
        
        # Limpa o histórico após gerar o relatório
        self.historico_foco_total = 0
        self.historico_pausa_curta_total = 0
        self.historico_pausa_longa_total = 0
        self.historico_ciclos_completados = 0

        return "Pomodoro parado e relatório gerado:\n" + report

    def status(self):
        """
        Retorna o status atual do Pomodoro.
        """
        if self.estado == "ocioso":
            return "O Pomodoro está ocioso. Use /iniciar para começar."
        elif self.estado == "pausado":
            return f"Pomodoro pausado. Faltam {self._formatar_tempo(self.tempo_restante)} para o fim do {self.tipo_atual}. Ciclos de foco completos: {self.ciclos_completados}"
        else:
            return (f"Status: {self.estado.capitalize()} | "
                    f"Tempo restante: {self._formatar_tempo(self.tempo_restante)} | "
                    f"Ciclos de foco completos: {self.ciclos_completados}")

    async def configurar(self, foco=None, pausa_curta=None, pausa_longa=None, ciclos_longa=None):
        """
        Permite configurar os tempos do Pomodoro.
        """
        if self.estado != "ocioso":
            return "Não é possível configurar enquanto o Pomodoro está ativo ou pausado. Por favor, pare-o primeiro."

        msg_retorno = []

        if foco is not None and foco > 0:
            self.foco_tempo = foco * 60
            msg_retorno.append(f"Foco: {foco} min")
        if pausa_curta is not None and pausa_curta > 0:
            self.pausa_curta_tempo = pausa_curta * 60
            msg_retorno.append(f"Pausa Curta: {pausa_curta} min")
        if pausa_longa is not None and pausa_longa > 0:
            self.pausa_longa_tempo = pausa_longa * 60
            msg_retorno.append(f"Pausa Longa: {pausa_longa} min")
        if ciclos_longa is not None and ciclos_longa > 0:
            self.ciclos_para_pausa_longa = ciclos_longa
            msg_retorno.append(f"Ciclos para Pausa Longa: {ciclos_longa}")
        
        if not msg_retorno:
            return ("Nenhuma configuração válida fornecida. "
                    "Use: /configurar foco <min> pausa_curta <min> pausa_longa <min> ciclos <num>")

        return "Configurações atualizadas:\n" + "\n".join(msg_retorno)


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
