import json
import re
from datetime import datetime, timedelta, date
from collections import defaultdict # Para lidar melhor com rotinas por chat_id

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

# Para o agendamento de notificações
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

# --- Estados da Conversa para Rotinas Semanais ---
MENU_ROTINAS = 0
AGUARDANDO_ROTINA_TEXTO = 1
GERENCIAR_ROTINAS = 2

# --- Helpers de persistência ---
ROTINAS_FILE = 'rotinas_semanais_data.json'

def carregar_rotinas():
    """Carrega as rotinas agendadas de um arquivo JSON."""
    try:
        with open(ROTINAS_FILE, 'r', encoding='utf-8') as f:
            # Usamos defaultdict para garantir que o chat_id sempre tenha um dicionário interno
            # Isso ajuda a evitar KeyErrors quando um chat_id novo é acessado.
            data = json.load(f)
            return defaultdict(dict, {k: defaultdict(list, v) for k, v in data.items()})
    except FileNotFoundError:
        return defaultdict(dict) # Retorna um defaultdict vazio se o arquivo não existir

def salvar_rotinas(data):
    """Salva as rotinas agendadas em um arquivo JSON."""
    # Convertemos defaultdict de volta para dict para salvar em JSON
    with open(ROTINAS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# Carrega as rotinas ao iniciar o módulo
rotinas_agendadas = carregar_rotinas()

# Mapeamento para garantir a ordem dos dias da semana e facilitar o cálculo da data
DIAS_DA_SEMANA_ORDEM = [
    "Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", 
    "Sexta-feira", "Sábado", "Domingo"
]

# Objeto do APScheduler para gerenciar os jobs
scheduler = AsyncIOScheduler()
# Inicializa o scheduler apenas uma vez
if not scheduler.running:
    scheduler.start()


# --- Helpers de Parse da Rotina (Melhorado e mais robusto) ---
def parse_rotina_textual(texto_rotina):
    """
    Analisa o texto de uma rotina semanal e o converte em uma estrutura de dados,
    incluindo duração e tipos de compromisso (horário fixo, dia livre, etc.).
    """
    rotina_parsed = {}
    dias_da_semana_map = {
        "segunda-feira": "Segunda-feira",
        "terça-feira": "Terça-feira",
        "quarta-feira": "Quarta-feira",
        "quinta-feira": "Quinta-feira",
        "sexta-feira": "Sexta-feira",
        "sábado": "Sábado",
        "domingo": "Domingo"
    }

    # Regex para capturar o dia da semana no início de uma linha
    # Adicionado "(?:Dia|Noite) " para capturar casos como "Noite: Relax"
    blocos_dias = re.split(
        r'^(?:[🟡🟠🔴🔵🟢🟣🟤]\s*)?([A-Za-zçÇáàãâéêíóôõúüÁÀÃÂÉÊÍÓÔÕÚÜ\s-]+-feira|Sábado|Domingo)\n', 
        texto_rotina, flags=re.MULTILINE
    )

    for i in range(1, len(blocos_dias), 2):
        dia_bruto = blocos_dias[i].strip()
        conteudo_dia = blocos_dias[i+1].strip()

        dia_normalizado = next((dias_da_semana_map[k] for k in dias_da_semana_map if k in dia_bruto.lower()), None)

        if dia_normalizado:
            tarefas_do_dia = []
            # Regex para horários (HHhMM – HHhMM: Descrição)
            padrao_tarefa_horario = re.compile(r'(\d{1,2}h\d{2})\s*–\s*(\d{1,2}h\d{2}):\s*(.*)')
            # Regex para "Livre" com possível horário (Ex: "Livre até 14h", "Noite livre")
            padrao_tarefa_livre_com_horario = re.compile(
                r'(.*(?:Livre|Descanso|Pausa|Tempo livre|Relax|Lazer)(?: completo| total)?.*?)'
                r'(?:até\s*(\d{1,2}h\d{2})|\s*(\d{1,2}h\d{2})\s*-\s*(\d{1,2}h\d{2})|)$', 
                re.IGNORECASE
            )
            # Regex para descrições de período (Ex: "Manhã leve", "Noite: relax")
            # Adicionado para pegar a descrição após o período
            padrao_tarefa_periodo = re.compile(r'^(Manhã|Tarde|Noite|Dia|Fim de Semana):\s*(.*)', re.IGNORECASE)

            for linha in conteudo_dia.split('\n'):
                linha = linha.strip()
                if not linha:
                    continue

                match_horario = padrao_tarefa_horario.match(linha)
                if match_horario:
                    inicio = match_horario.group(1).replace('h', ':')
                    fim = match_horario.group(2).replace('h', ':')
                    descricao = match_horario.group(3).strip()
                    try:
                        dt_inicio = datetime.strptime(inicio, "%H:%M")
                        dt_fim = datetime.strptime(fim, "%H:%M")
                        if dt_fim < dt_inicio: # Lida com horários que passam da meia-noite
                            dt_fim += timedelta(days=1)
                        duracao_minutos = int((dt_fim - dt_inicio).total_seconds() / 60)
                        duracao_str = f"{duracao_minutos // 60}h {duracao_minutos % 60}m" if duracao_minutos >= 60 else f"{duracao_minutos}m"
                    except ValueError:
                        duracao_str = "N/A"

                    tarefas_do_dia.append({
                        "id": str(datetime.now().timestamp()), # ID único para cada tarefa
                        "tipo": "horario_fixo",
                        "inicio": inicio,
                        "fim": fim,
                        "descricao": descricao,
                        "duracao": duracao_str
                    })
                    continue

                match_livre_com_horario = padrao_tarefa_livre_com_horario.match(linha)
                if match_livre_com_horario:
                    descricao_base = match_livre_com_horario.group(1).strip()
                    inicio_livre, fim_livre, duracao_str = None, None, None
                    
                    if match_livre_com_horario.group(2): # "Livre até HHhMM"
                        fim_livre = match_livre_com_horario.group(2).replace('h', ':')
                        descricao_final = f"{descricao_base} (até {fim_livre})"
                    elif match_livre_com_horario.group(3) and match_livre_com_horario.group(4): # "Livre HHhMM - HHhMM"
                        inicio_livre = match_livre_com_horario.group(3).replace('h', ':')
                        fim_livre = match_livre_com_horario.group(4).replace('h', ':')
                        try:
                            dt_inicio = datetime.strptime(inicio_livre, "%H:%M")
                            dt_fim = datetime.strptime(fim_livre, "%H:%M")
                            if dt_fim < dt_inicio:
                                dt_fim += timedelta(days=1)
                            duracao_minutos = int((dt_fim - dt_inicio).total_seconds() / 60)
                            duracao_str = f"{duracao_minutos // 60}h {duracao_minutos % 60}m" if duracao_minutos >= 60 else f"{duracao_minutos}m"
                        except ValueError:
                            duracao_str = "N/A"
                        descricao_final = f"{descricao_base} ({inicio_livre} - {fim_livre})"
                    else: # "Livre" ou "Noite livre total" sem horário específico
                        descricao_final = descricao_base

                    tarefas_do_dia.append({
                        "id": str(datetime.now().timestamp() + len(tarefas_do_dia)), # Garante ID único
                        "tipo": "periodo_livre",
                        "descricao": descricao_final,
                        "inicio_sugerido": inicio_livre,
                        "fim_sugerido": fim_livre,
                        "duracao": duracao_str
                    })
                    continue

                match_periodo = padrao_tarefa_periodo.match(linha)
                if match_periodo:
                    periodo = match_periodo.group(1).capitalize()
                    desc = match_periodo.group(2).strip()
                    tarefas_do_dia.append({
                        "id": str(datetime.now().timestamp() + len(tarefas_do_dia)),
                        "tipo": "periodo_geral",
                        "periodo": periodo,
                        "descricao": desc
                    })
                    continue

                # Se não encaixar em nenhum dos padrões acima, trate como uma descrição simples sem horário
                tarefas_do_dia.append({
                    "id": str(datetime.now().timestamp() + len(tarefas_do_dia)),
                    "tipo": "descricao_simples",
                    "descricao": linha # A linha completa como descrição
                })

            if tarefas_do_dia:
                rotina_parsed[dia_normalizado] = tarefas_do_dia
    
    return rotina_parsed


class RotinasSemanais:
    def __init__(self, bot=None, chat_id=None):
        self.bot = bot
        self.chat_id = chat_id

    # --- Métodos para interagir com o usuário ---
    async def start_rotinas_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Exibe o menu principal das rotinas semanais."""
        keyboard = [
            [InlineKeyboardButton("📝 Gerenciar Minhas Rotinas", callback_data="rotinas_gerenciar")],
            [InlineKeyboardButton("➕ Adicionar Nova Rotina", callback_data="rotinas_adicionar")],
            [InlineKeyboardButton("↩️ Voltar ao Menu Principal", callback_data="main_menu_return")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = "🗓️ *Menu de Rotinas Semanais*: organize seu tempo e seja mais produtivo! Escolha uma opção:"
        
        if update.callback_query:
            await update.callback_query.edit_message_text(text, parse_mode='Markdown', reply_markup=reply_markup)
        else:
            await update.message.reply_text(text, parse_mode='Markdown', reply_markup=reply_markup)
        return MENU_ROTINAS

    async def gerenciar_rotinas(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Exibe as rotinas agendadas e opções para gerenciá-las."""
        query = update.callback_query
        await query.answer()
        chat_id = str(query.message.chat_id)

        user_rotinas = rotinas_agendadas.get(chat_id, {})
        if not user_rotinas or all(not tarefas for tarefas in user_rotinas.values()):
            keyboard = [[InlineKeyboardButton("↩️ Voltar", callback_data="rotinas_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "Ops! Parece que você ainda não tem nenhuma rotina semanal agendada. "
                "Que tal adicionar uma agora mesmo? ✨",
                reply_markup=reply_markup
            )
            return MENU_ROTINAS

        mensagem = "✨ *Suas Rotinas Semanais Detalhadas:*\n\n"
        keyboard_botoes = []

        for dia in DIAS_DA_SEMANA_ORDEM:
            if dia in user_rotinas and user_rotinas[dia]:
                mensagem += f"*{dia}*\n"
                for idx, tarefa in enumerate(user_rotinas[dia]):
                    duracao_info = f" _({tarefa['duracao']})_" if tarefa.get('duracao') else ""
                    
                    if tarefa['tipo'] == "horario_fixo":
                        mensagem += f"  ⏰ `{tarefa['inicio']}-{tarefa['fim']}`: {tarefa['descricao']}{duracao_info}\n"
                    elif tarefa['tipo'] == "periodo_livre":
                        horario_livre_info = ""
                        if tarefa.get('inicio_sugerido') and tarefa.get('fim_sugerido'):
                             horario_livre_info = f"`{tarefa['inicio_sugerido']}-{tarefa['fim_sugerido']}`: "
                        mensagem += f"  🍃 {horario_livre_info}{tarefa['descricao']}{duracao_info}\n"
                    elif tarefa['tipo'] == "periodo_geral":
                        mensagem += f"  💡 *{tarefa['periodo']}*: {tarefa['descricao']}\n"
                    else: # tipo "descricao_simples"
                        mensagem += f"  - {tarefa['descricao']}\n"
                    
                    # Adiciona um botão para apagar tarefa individual. Usa o ID da tarefa.
                    keyboard_botoes.append(
                        [InlineKeyboardButton(f"🗑️ Apagar {dia} ({idx+1})", callback_data=f"rotinas_apagar_{dia}_{tarefa['id']}")]
                    )
                mensagem += "\n" # Adiciona uma linha em branco entre os dias

        keyboard_botoes.append([InlineKeyboardButton("↩️ Voltar ao Menu de Rotinas", callback_data="rotinas_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard_botoes)

        await query.edit_message_text(
            mensagem,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        return GERENCIAR_ROTINAS

    async def adicionar_rotina_preparar(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Prepara o bot para receber o texto da nova rotina."""
        query = update.callback_query
        await query.answer()
        context.user_data['aguardando_rotina_texto'] = True 

        keyboard = [[InlineKeyboardButton("❌ Cancelar e Voltar", callback_data="rotinas_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "✍️ Certo! Por favor, envie sua rotina semanal no formato abaixo (cole o texto completo de uma vez).\n\n"
            "Eu sou inteligente e consigo entender: \n"
            "✅ *Horários fixos*: `10h30 – 11h00: Café + alongamento`\n"
            "✅ *Períodos livres*: `Livre até 14h`, `Noite: Relax total`\n"
            "✅ *Descrições gerais de período*: `Manhã: Estudos focados`\n\n"
            "```\n📆 Minha Nova Rotina\n"
            "🟡 Segunda-feira\n"
            "10h30 – 11h00: Café + alongamento\n"
            "17h00 – 21h30: Estudo Python\n"
            "Noite: Lazer com limite de tela\n"
            "🟠 Terça-feira\n"
            "Livre até 14h\n"
            "14h00 – 15h30: Revisar caderno\n"
            "```\n\n"
            "Clique em 'Cancelar' se mudar de ideia. 👇",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        return AGUARDANDO_ROTINA_TEXTO

    async def adicionar_rotina_processar(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Processa o texto da rotina enviado pelo usuário e o salva."""
        if not context.user_data.get('aguardando_rotina_texto'):
            await update.message.reply_text("🤔 Não entendi. Por favor, use os botões do menu 'Rotinas Semanais' para adicionar ou gerenciar.")
            return MENU_ROTINAS 

        chat_id = str(update.message.chat_id)
        texto_rotina = update.message.text
        
        try:
            rotina_processada = parse_rotina_textual(texto_rotina)
            if not rotina_processada:
                await update.message.reply_text(
                    "❌ Ops! Não consegui identificar nenhuma rotina válida no texto que você enviou. "
                    "Por favor, verifique o formato com os exemplos e tente novamente, "
                    "ou clique em 'Cancelar' para voltar. 🧐"
                )
                return AGUARDANDO_ROTINA_TEXTO 

            # Garante que o chat_id tem uma estrutura para rotinas
            if chat_id not in rotinas_agendadas:
                rotinas_agendadas[chat_id] = defaultdict(list)
            
            # Adiciona as novas rotinas, mesclando com as existentes se houver
            # Rotinas da semana passada são automaticamente para a próxima semana.
            for dia, tarefas in rotina_processada.items():
                for nova_tarefa in tarefas:
                    # Verifica se a tarefa (descrição e horários) já existe para evitar duplicatas exatas
                    # Ignoramos o 'id' na comparação para verificar se a tarefa em si já está lá
                    tarefa_existe = any(
                        t.get('descricao') == nova_tarefa.get('descricao') and
                        t.get('inicio') == nova_tarefa.get('inicio') and
                        t.get('fim') == nova_tarefa.get('fim')
                        for t in rotinas_agendadas[chat_id][dia]
                    )
                    if not tarefa_existe:
                        rotinas_agendadas[chat_id][dia].append(nova_tarefa)
            
            salvar_rotinas(rotinas_agendadas) 
            del context.user_data['aguardando_rotina_texto'] 

            await update.message.reply_text(
                "🎉 *Rotina semanal adicionada com sucesso!* Ela será seu guia a cada semana. "
                "Prepare-se para receber os lembretes! 🔔"
                "\n\nUse 'Gerenciar Rotinas' para ver tudo que você agendou. 👀"
            , parse_mode='Markdown')
            
            # Após adicionar, reagenda todos os jobs para este usuário
            # Isso garante que novas tarefas sejam agendadas e antigas sejam atualizadas
            await self.reschedule_all_user_jobs(chat_id, context)

            return await self.start_rotinas_menu(update, context) 

        except Exception as e:
            await update.message.reply_text(
                f"❌ Algo deu errado ao processar sua rotina: `{e}`. "
                "Verifique se o formato está correto e tente novamente, por favor. 🙏",
                parse_mode='Markdown'
            )
            # del context.user_data['aguardando_rotina_texto'] # Pode-se decidir se reseta ou não aqui
            return AGUARDANDO_ROTINA_TEXTO 

    async def apagar_tarefa(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Apaga uma tarefa específica da rotina do usuário."""
        query = update.callback_query
        await query.answer()
        chat_id = str(query.message.chat_id)

        # O callback_data será algo como "rotinas_apagar_DiaDaSemana_IDdaTarefa"
        _, _, dia, tarefa_id = query.data.split('_')
        
        user_rotinas = rotinas_agendadas.get(chat_id, {})
        if dia in user_rotinas:
            tarefa_removida = None
            # Encontra e remove a tarefa pelo ID
            for i, tarefa in enumerate(user_rotinas[dia]):
                if tarefa.get('id') == tarefa_id:
                    tarefa_removida = user_rotinas[dia].pop(i)
                    break
            
            if tarefa_removida:
                # Se o dia ficar vazio, remove o dia
                if not user_rotinas[dia]:
                    del user_rotinas[dia]
                
                # Se o chat_id não tiver mais rotinas, remove o chat_id
                if not user_rotinas: # Verifica se o defaultdict está vazio
                    del rotinas_agendadas[chat_id]

                salvar_rotinas(rotinas_agendadas)
                await query.edit_message_text(f"🗑️ Tarefa removida: _{tarefa_removida.get('descricao', 'Tarefa')}_. Certo! ✅")
                # Remove o job agendado para esta tarefa específica
                job_id = f"notificacao_{chat_id}_{tarefa_id}"
                if scheduler.get_job(job_id):
                    scheduler.remove_job(job_id)
            else:
                await query.edit_message_text("Essa tarefa não foi encontrada ou já foi removida. Tente novamente listando as rotinas. 🤔")
        else:
            await query.edit_message_text("Essa tarefa não foi encontrada ou já foi removida. Tente novamente listando as rotinas. 🤔")
        
        # Volta para o menu de gerenciar rotinas para ver o estado atualizado
        return await self.gerenciar_rotinas(update, context)

    # --- Lógica de Agendamento (APScheduler) ---

    async def reschedule_all_user_jobs(self, chat_id: str, context: ContextTypes.DEFAULT_TYPE):
        """
        Remove todos os jobs agendados para um usuário e os reagenda com as rotinas atuais.
        Chamado após adicionar/remover rotinas.
        """
        # Remove todos os jobs antigos deste usuário
        for job in scheduler.get_jobs():
            if job.id.startswith(f"notificacao_{chat_id}_"):
                scheduler.remove_job(job.id)
        
        user_rotinas = rotinas_agendadas.get(chat_id)
        if not user_rotinas:
            return # Sem rotinas para agendar

        # Agendamento para cada tarefa com horário fixo
        today_weekday_idx = datetime.now().weekday() # 0=Segunda, 6=Domingo

        for dia_nome in DIAS_DA_SEMANA_ORDEM:
            if dia_nome in user_rotinas:
                dia_idx = DIAS_DA_SEMANA_ORDEM.index(dia_nome)
                
                for tarefa in user_rotinas[dia_nome]:
                    if tarefa['tipo'] == "horario_fixo":
                        inicio_str = tarefa['inicio'] # Ex: "10:30"
                        
                        # Calcula a data do próximo dia da semana
                        days_ahead = dia_idx - today_weekday_idx
                        if days_ahead < 0: # Se o dia já passou nesta semana, agenda para a próxima
                            days_ahead += 7
                        elif days_ahead == 0: # Se for hoje, verifica se o horário já passou
                            agora = datetime.now()
                            hora_tarefa = datetime.strptime(inicio_str, "%H:%M").time()
                            if agora.time() > hora_tarefa: # Se o horário já passou hoje, agenda para a próxima semana
                                days_ahead += 7

                        proxima_data = datetime.now() + timedelta(days=days_ahead)
                        
                        # Combina a data calculada com o horário da tarefa
                        agendamento_dt = datetime(
                            proxima_data.year, proxima_data.month, proxima_data.day,
                            int(inicio_str.split(':')[0]), int(inicio_str.split(':')[1]),
                            0 # Segundos
                        )

                        job_id = f"notificacao_{chat_id}_{tarefa['id']}"
                        
                        # Adiciona o job ao scheduler para rodar semanalmente
                        scheduler.add_job(
                            self._send_task_notification,
                            'date', # Tipo de gatilho: data e hora específicas
                            run_date=agendamento_dt,
                            id=job_id,
                            args=[chat_id, tarefa, context],
                            misfire_grace_time=60, # Permite um atraso de até 60 segundos
                            # Próximo passo para recorrência: usar 'cron' com dia da semana
                            # scheduler.add_job(self._send_task_notification, 'cron', day_of_week=dia_idx, hour=int(inicio_str.split(':')[0]), minute=int(inicio_str.split(':')[1]), id=job_id, args=[chat_id, tarefa, context])
                        )
                        # No futuro, se quiser semanal:
                        # scheduler.add_job(
                        #     self._send_task_notification,
                        #     'cron',
                        #     day_of_week=dia_idx,
                        #     hour=int(inicio_str.split(':')[0]),
                        #     minute=int(inicio_str.split(':')[1]),
                        #     id=job_id,
                        #     args=[chat_id, tarefa, context]
                        # )
        salvar_rotinas(rotinas_agendadas) # Salva qualquer atualização de IDs, etc.


    async def _send_task_notification(self, chat_id: str, tarefa: dict, context: ContextTypes.DEFAULT_TYPE):
        """Envia a notificação da tarefa ao usuário."""
        # Se o bot não estiver mais disponível (ex: restart), o contexto pode ser problemático.
        # É ideal ter o `bot` diretamente acessível ou usar `context.bot`.
        try:
            descricao = tarefa.get('descricao', 'Sua tarefa')
            duracao_info = f" ({tarefa['duracao']})" if tarefa.get('duracao') else ""
            
            keyboard = [
                [InlineKeyboardButton("✅ Concluída!", callback_data=f"rotinas_concluir_{tarefa['id']}")],
                # [InlineKeyboardButton(" snooze", callback_data=f"rotinas_snooze_{tarefa['id']}")], # Opção futura para adiar
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🔔 *Lembrete!* Sua tarefa começa agora: \n\n"
                     f"⏰ `{tarefa['inicio']}-{tarefa['fim']}`: _{descricao}_{duracao_info}\n\n"
                     f"Já concluiu? Avise-me! 👇",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        except Exception as e:
            print(f"Erro ao enviar notificação para {chat_id}: {e}")
            # Lidar com usuários que bloquearam o bot, etc.

    async def concluir_tarefa_notificada(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Marca uma tarefa notificada como concluída (e a remove da rotina semanal)."""
        query = update.callback_query
        await query.answer("Certo, anotado! ✅")
        chat_id = str(query.message.chat_id)
        
        # O callback_data será algo como "rotinas_concluir_IDdaTarefa"
        _, _, tarefa_id = query.data.split('_')

        user_rotinas = rotinas_agendadas.get(chat_id, {})
        tarefa_encontrada = False
        dia_da_tarefa = None
        
        # Percorre todas as rotinas para encontrar a tarefa pelo ID único
        for dia_nome in DIAS_DA_SEMANA_ORDEM:
            if dia_nome in user_rotinas:
                for i, tarefa in enumerate(user_rotinas[dia_nome]):
                    if tarefa.get('id') == tarefa_id:
                        user_rotinas[dia_nome].pop(i) # Remove a tarefa
                        tarefa_encontrada = True
                        dia_da_tarefa = dia_nome
                        break
            if tarefa_encontrada:
                break
        
        if tarefa_encontrada:
            # Limpa o dia se ele ficar vazio
            if dia_da_tarefa and not user_rotinas[dia_da_tarefa]:
                del user_rotinas[dia_da_tarefa]
            
            # Limpa o chat_id se não houver mais rotinas
            if not user_rotinas:
                del rotinas_agendadas[chat_id]

            salvar_rotinas(rotinas_agendadas)
            
            # Edita a mensagem da notificação para indicar que foi concluída
            await query.edit_message_text(f"🎉 Tarefa marcada como *concluída*! Manda ver! 💪", parse_mode='Markdown')
            
            # Remove o job do scheduler para evitar futuras notificações duplicadas desta instância
            job_id = f"notificacao_{chat_id}_{tarefa_id}"
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
        else:
            await query.edit_message_text("Essa tarefa já foi concluída ou não foi encontrada. Bom trabalho! 👍")

    def get_rotinas_semanais_conversation_handler(self) -> ConversationHandler:
        """
        Retorna o ConversationHandler para a funcionalidade de Rotinas Semanais.
        """
        return ConversationHandler(
            entry_points=[CallbackQueryHandler(self.start_rotinas_menu, pattern="^open_rotinas_semanais_menu$")],
            states={
                MENU_ROTINAS: [
                    CallbackQueryHandler(self.gerenciar_rotinas, pattern="^rotinas_gerenciar$"),
                    CallbackQueryHandler(self.adicionar_rotina_preparar, pattern="^rotinas_adicionar$"),
                    CallbackQueryHandler(self.start_rotinas_menu, pattern="^rotinas_menu$"), 
                ],
                AGUARDANDO_ROTINA_TEXTO: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.adicionar_rotina_processar),
                    CallbackQueryHandler(self.start_rotinas_menu, pattern="^rotinas_menu$"), 
                ],
                GERENCIAR_ROTINAS: [
                    CallbackQueryHandler(self.apagar_tarefa, pattern=r"^rotinas_apagar_.*$"),
                    CallbackQueryHandler(self.start_rotinas_menu, pattern="^rotinas_menu$"), 
                ]
            },
            fallbacks=[
                CallbackQueryHandler(self.start_rotinas_menu, pattern="^rotinas_menu$"),
            ],
            map_to_parent={
                ConversationHandler.END: ConversationHandler.END 
            }
        )

# Função para iniciar o agendamento de todas as rotinas existentes (ao iniciar o bot)
async def start_all_scheduled_jobs(application: Application):
    """
    Função chamada uma vez na inicialização do bot para agendar todas as rotinas salvas.
    """
    print("Agendando rotinas semanais existentes...")
    rotinas_instance_dummy = RotinasSemanais(bot=application.bot) # Instância dummy para usar o método reschedule
    
    for chat_id in rotinas_agendadas:
        # A API do `JobQueue` (context.job_queue) é a forma correta de agendar tarefas recorrentes
        # no python-telegram-bot, mas aqui estamos usando APScheduler diretamente.
        # Se você quiser que o `context` esteja disponível nas tarefas agendadas,
        # você precisaria passá-lo ou ter uma referência ao `Application` ou `bot`.
        
        # Para simplificar agora e manter o APScheduler direto:
        # Passamos o `context.bot` e `chat_id` diretamente para o método
        await rotinas_instance_dummy.reschedule_all_user_jobs(chat_id, application.bot) 

# Adicione esta função ao seu main.py no final da função main()
# application.run_polling(poll_interval=1.0, on_startup=start_all_scheduled_jobs)
# E o `concluir_tarefa_notificada` deve ser um handler na aplicação principal
