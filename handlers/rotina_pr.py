import json
import re
from datetime import datetime, timedelta, date
from collections import defaultdict
import uuid # Importado para geração de IDs únicos

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    Application,
)

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
            data = json.load(f)
            return defaultdict(dict, {k: defaultdict(list, v) for k, v in data.items()})
    except FileNotFoundError:
        return defaultdict(dict)
    except json.JSONDecodeError as e:
        print(f"Erro ao decodificar JSON do arquivo {ROTINAS_FILE}: {e}. Retornando rotinas vazias.")
        return defaultdict(dict)
    except Exception as e:
        print(f"Erro inesperado ao carregar rotinas do arquivo {ROTINAS_FILE}: {e}. Retornando rotinas vazias.")
        return defaultdict(dict)

def salvar_rotinas(data):
    """Salva as rotinas agendadas em um arquivo JSON."""
    try:
        with open(ROTINAS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except IOError as e:
        print(f"Erro de I/O ao salvar rotinas no arquivo {ROTINAS_FILE}: {e}")
    except Exception as e:
        print(f"Erro inesperado ao salvar rotinas no arquivo {ROTINAS_FILE}: {e}")

# Carrega as rotinas ao iniciar o módulo
rotinas_agendadas = carregar_rotinas()

# Mapeamento para garantir a ordem dos dias da semana
DIAS_DA_SEMANA_ORDEM = [
    "Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira",
    "Sexta-feira", "Sábado", "Domingo"
]

# Objeto do APScheduler para gerenciar os jobs
scheduler = AsyncIOScheduler()
# REMOVIDO: scheduler.start() daqui. Será iniciado em main.py na função on_startup.


# --- Helpers de Parse da Rotina (Melhorado) ---
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
            padrao_tarefa_horario = re.compile(r'(\d{1,2}h\d{2})\s*–\s*(\d{1,2}h\d{2}):\s*(.*)')
            padrao_tarefa_livre_com_horario = re.compile(
                r'(.*(?:Livre|Descanso|Pausa|Tempo livre|Relax|Lazer)(?: completo| total)?.*?)'
                r'(?:até\s*(\d{1,2}h\d{2})|\s*(\d{1,2}h\d{2})\s*-\s*(\d{1,2}h\d{2})|)$',
                re.IGNORECASE
            )
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
                        if dt_fim < dt_inicio:
                            dt_fim += timedelta(days=1)
                        duracao_minutos = int((dt_fim - dt_inicio).total_seconds() / 60)
                        duracao_str = f"{duracao_minutos // 60}h {duracao_minutos % 60}m" if duracao_minutos >= 60 else f"{duracao_minutos}m"
                    except ValueError:
                        duracao_str = "N/A"

                    tarefas_do_dia.append({
                        "id": uuid.uuid4().hex, # ID único e robusto
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
                    
                    if match_livre_com_horario.group(2):
                        fim_livre = match_livre_com_horario.group(2).replace('h', ':')
                        descricao_final = f"{descricao_base} (até {fim_livre})"
                    elif match_livre_com_horario.group(3) and match_livre_com_horario.group(4):
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
                    else:
                        descricao_final = descricao_base

                    tarefas_do_dia.append({
                        "id": uuid.uuid4().hex, # ID único e robusto
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
                        "id": uuid.uuid4().hex, # ID único e robusto
                        "tipo": "periodo_geral",
                        "periodo": periodo,
                        "descricao": desc
                    })
                    continue

                tarefas_do_dia.append({
                    "id": uuid.uuid4().hex, # ID único e robusto
                    "tipo": "descricao_simples",
                    "descricao": linha
                })

            if tarefas_do_dia:
                rotina_parsed[dia_normalizado] = tarefas_do_dia
            
    return rotina_parsed


class RotinasSemanais:
    def __init__(self, bot=None, chat_id=None):
        self.bot = bot
        self.chat_id = chat_id

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
                    duracao_info = f" _({tarefa.get('duracao', 'N/A')})_" if tarefa.get('duracao') else ""
                    
                    if tarefa['tipo'] == "horario_fixo":
                        mensagem += f"  ⏰ `{tarefa.get('inicio', '??:??')}-{tarefa.get('fim', '??:??')}`: {tarefa.get('descricao', 'Tarefa sem descrição')}{duracao_info}\n"
                    elif tarefa['tipo'] == "periodo_livre":
                        horario_livre_info = ""
                        if tarefa.get('inicio_sugerido') and tarefa.get('fim_sugerido'):
                             horario_livre_info = f"`{tarefa.get('inicio_sugerido', '??:??')}-{tarefa.get('fim_sugerido', '??:??')}`: "
                        mensagem += f"  🍃 {horario_livre_info}{tarefa.get('descricao', 'Período livre')}{duracao_info}\n"
                    elif tarefa['tipo'] == "periodo_geral":
                        mensagem += f"  💡 *{tarefa.get('periodo', 'Período')}*: {tarefa.get('descricao', 'Descrição geral')}\n"
                    else:
                        mensagem += f"  - {tarefa.get('descricao', 'Tarefa sem descrição')}\n"
                    
                    # Adiciona um botão de apagar para cada tarefa individualmente
                    # O ID da tarefa é usado para identificar qual tarefa apagar
                    keyboard_botoes.append(
                        [InlineKeyboardButton(f"🗑️ Apagar {dia} ({idx+1})", callback_data=f"rotinas_apagar_{dia}_{tarefa['id']}")]
                    )
                mensagem += "\n"

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

            if chat_id not in rotinas_agendadas:
                rotinas_agendadas[chat_id] = defaultdict(list)
            
            for dia, tarefas in rotina_processada.items():
                for nova_tarefa in tarefas:
                    # Verifica se uma tarefa idêntica já existe (ignora o ID para esta verificação)
                    tarefa_existe = any(
                        t.get('descricao') == nova_tarefa.get('descricao') and
                        t.get('inicio') == nova_tarefa.get('inicio') and
                        t.get('fim') == nova_tarefa.get('fim') and
                        t.get('tipo') == nova_tarefa.get('tipo') # Incluir tipo na verificação
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
            
            await self.reschedule_all_user_jobs(chat_id, context.bot) # Passa context.bot aqui

            return await self.start_rotinas_menu(update, context)

        except Exception as e:
            await update.message.reply_text(
                f"❌ Algo deu errado ao processar sua rotina: `{e}`. "
                "Verifique se o formato está correto e tente novamente, por favor. 🙏",
                parse_mode='Markdown'
            )
            return AGUARDANDO_ROTINA_TEXTO

    async def apagar_tarefa(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Apaga uma tarefa específica da rotina do usuário."""
        query = update.callback_query
        await query.answer()
        chat_id = str(query.message.chat_id)

        _, _, dia_str, tarefa_id = query.data.split('_') # dia_str é o nome do dia recebido do callback_data
        
        user_rotinas = rotinas_agendadas.get(chat_id, {})
        tarefa_encontrada = False
        dia_da_tarefa = None
        tarefa_removida_descricao = "Tarefa" # Default description

        # Itera sobre os dias da semana para encontrar a tarefa
        for dia_nome in DIAS_DA_SEMANA_ORDEM:
            if dia_nome in user_rotinas:
                for i, tarefa in enumerate(user_rotinas[dia_nome]):
                    if tarefa.get('id') == tarefa_id:
                        tarefa_removida_descricao = tarefa.get('descricao', 'Tarefa')
                        user_rotinas[dia_nome].pop(i)
                        tarefa_encontrada = True
                        dia_da_tarefa = dia_nome
                        break
                if tarefa_encontrada:
                    break
        
        if tarefa_encontrada:
            # Se o dia ficar sem tarefas, remove a entrada do dia
            if dia_da_tarefa and not user_rotinas[dia_da_tarefa]:
                del user_rotinas[dia_da_tarefa]
            
            # Se o usuário não tiver mais rotinas, remove a entrada do chat_id
            if not user_rotinas:
                del rotinas_agendadas[chat_id]

            salvar_rotinas(rotinas_agendadas)
            
            # Remove o job agendado correspondente (se existir)
            job_id = f"notificacao_{chat_id}_{tarefa_id}"
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
            job_id_livre = f"livre_notificacao_{chat_id}_{tarefa_id}"
            if scheduler.get_job(job_id_livre):
                scheduler.remove_job(job_id_livre)

            await query.edit_message_text(f"🗑️ Tarefa removida: _{tarefa_removida_descricao}_. Certo! ✅")
            
            # Reagendar todos os jobs do usuário para garantir consistência
            await self.reschedule_all_user_jobs(chat_id, context.bot)
        else:
            await query.edit_message_text("Essa tarefa não foi encontrada ou já foi removida. Tente novamente listando as rotinas. 🤔")
        
        # Volta para o menu de gerenciar rotinas para atualizar a lista
        return await self.gerenciar_rotinas(update, context)

    # --- Lógica de Agendamento (APScheduler) ---

    async def reschedule_all_user_jobs(self, chat_id: str, bot_instance: ContextTypes.DEFAULT_TYPE):
        """
        Remove todos os jobs agendados para um usuário e os reagenda com as rotinas atuais.
        Chamado após adicionar/remover rotinas.
        """
        # Remove todos os jobs antigos deste usuário
        for job in scheduler.get_jobs():
            if job.id.startswith(f"notificacao_{chat_id}_") or job.id.startswith(f"livre_notificacao_{chat_id}_"):
                try:
                    scheduler.remove_job(job.id)
                except Exception as e:
                    print(f"Erro ao remover job {job.id}: {e}")
        
        user_rotinas = rotinas_agendadas.get(chat_id)
        if not user_rotinas:
            return

        today_weekday_idx = datetime.now().weekday() # 0=Segunda, 6=Domingo

        for dia_nome in DIAS_DA_SEMANA_ORDEM:
            if dia_nome in user_rotinas:
                dia_idx = DIAS_DA_SEMANA_ORDEM.index(dia_nome)
                
                for tarefa in user_rotinas[dia_nome]:
                    if tarefa['tipo'] == "horario_fixo":
                        inicio_str = tarefa.get('inicio')
                        if not inicio_str:
                            print(f"Tarefa {tarefa.get('id', 'N/A')} para o chat {chat_id} não possui horário de início. Pulando agendamento.")
                            continue

                        try:
                            tarefa_time = datetime.strptime(inicio_str, "%H:%M").time()
                            hour = int(inicio_str.split(':')[0])
                            minute = int(inicio_str.split(':')[1])
                        except (ValueError, IndexError) as e:
                            print(f"Erro ao parsear horário de início '{inicio_str}' da tarefa {tarefa.get('id', 'N/A')} para o chat {chat_id}: {e}. Pulando agendamento.")
                            continue # Pula esta tarefa se o horário for inválido

                        days_ahead = dia_idx - today_weekday_idx
                        agora_time = datetime.now().time()
                        
                        if days_ahead < 0: # Dia já passou nesta semana
                            days_ahead += 7
                        elif days_ahead == 0 and agora_time > tarefa_time: # É hoje, mas o horário já passou
                            days_ahead += 7

                        # proxima_data = datetime.now() + timedelta(days=days_ahead) # Não é necessário para 'cron'
                        
                        job_id = f"notificacao_{chat_id}_{tarefa['id']}"
                        
                        # Adiciona o job ao scheduler para rodar semanalmente
                        scheduler.add_job(
                            self._send_task_notification,
                            'cron',
                            day_of_week=dia_idx, # Dia da semana (0=Seg, 6=Dom)
                            hour=hour,
                            minute=minute,
                            id=job_id,
                            args=[chat_id, tarefa, bot_instance], # Passa a instância do bot para a função
                            misfire_grace_time=60 # Permite um atraso de até 60 segundos
                        )
                    elif tarefa['tipo'] == "periodo_livre" and tarefa.get('fim_sugerido'):
                        # Agendar uma mensagem de "você está livre" para o fim de um período livre
                        fim_str = tarefa.get('fim_sugerido')
                        if not fim_str:
                            print(f"Período livre {tarefa.get('id', 'N/A')} para o chat {chat_id} não possui horário de fim sugerido. Pulando agendamento.")
                            continue

                        try:
                            tarefa_time = datetime.strptime(fim_str, "%H:%M").time()
                            hour = int(fim_str.split(':')[0])
                            minute = int(fim_str.split(':')[1])
                        except (ValueError, IndexError) as e:
                            print(f"Erro ao parsear horário de fim '{fim_str}' do período livre {tarefa.get('id', 'N/A')} para o chat {chat_id}: {e}. Pulando agendamento.")
                            continue # Pula esta tarefa se o horário for inválido
                        
                        days_ahead = dia_idx - today_weekday_idx
                        agora_time = datetime.now().time()
                        
                        if days_ahead < 0:
                            days_ahead += 7
                        elif days_ahead == 0 and agora_time > tarefa_time:
                            days_ahead += 7

                        # proxima_data = datetime.now() + timedelta(days=days_ahead) # Não é necessário para 'cron'
                        
                        job_id_livre = f"livre_notificacao_{chat_id}_{tarefa['id']}"
                        
                        scheduler.add_job(
                            self._send_free_period_notification,
                            'cron',
                            day_of_week=dia_idx,
                            hour=hour,
                            minute=minute,
                            id=job_id_livre,
                            args=[chat_id, tarefa, bot_instance],
                            misfire_grace_time=60
                        )
        # A chamada a salvar_rotinas(rotinas_agendadas) foi removida daqui,
        # pois esta função apenas reagenda jobs, não modifica os dados persistidos.
        # A persistência ocorre em adicionar_rotina_processar e apagar_tarefa.


    async def _send_task_notification(self, chat_id: str, tarefa: dict, bot_instance: ContextTypes.DEFAULT_TYPE):
        """Envia a notificação da tarefa ao usuário."""
        try:
            descricao = tarefa.get('descricao', 'Sua tarefa')
            duracao_info = f" ({tarefa.get('duracao', 'N/A')})" if tarefa.get('duracao') else ""
            
            keyboard = [
                [InlineKeyboardButton("✅ Concluída!", callback_data=f"rotinas_concluir_{tarefa.get('id', 'unknown_id')}")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await bot_instance.send_message(
                chat_id=chat_id,
                text=f"🔔 *ATENÇÃO! Sua próxima tarefa começa AGORA:*\n\n"
                     f"⏰ `{tarefa.get('inicio', '??:??')}-{tarefa.get('fim', '??:??')}`: _{descricao}_{duracao_info}\n\n"
                     f"Já concluiu? Me avise para eu registrar! 👇",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        except Exception as e:
            print(f"Erro ao enviar notificação da tarefa para {chat_id}: {e}")

    async def _send_free_period_notification(self, chat_id: str, tarefa: dict, bot_instance: ContextTypes.DEFAULT_TYPE):
        """Envia uma notificação informando que o usuário está livre."""
        try:
            await bot_instance.send_message(
                chat_id=chat_id,
                text=f"🥳 *Ótima notícia!* Seu período de _{tarefa.get('descricao', 'tempo livre')}_ termina agora. "
                     "Você está *livre* para o que quiser! Que tal um descanso? ☕",
                parse_mode='Markdown'
            )
        except Exception as e:
            print(f"Erro ao enviar notificação de período livre para {chat_id}: {e}")


    async def concluir_tarefa_notificada(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Marca uma tarefa notificada como concluída (e a remove da rotina semanal para aquela instância)."""
        query = update.callback_query
        chat_id = str(query.message.chat_id)
        
        # O ID da tarefa é extraído do callback_data
        # A notificação é do tipo 'rotinas_concluir_IDDAREFA'
        try:
            _, _, tarefa_id = query.data.split('_')
        except ValueError:
            print(f"Erro ao extrair tarefa_id do callback_data: {query.data}")
            await query.edit_message_text("Ops! Não consegui identificar a tarefa. Tente novamente! 😕")
            return

        try:
            # Edita a mensagem original da notificação
            await query.edit_message_text(
                f"🎉 Tarefa marcada como *concluída*! Mandou bem! 💪\n\n"
                f"Sua próxima notificação chegará no horário! 🔔",
                parse_mode='Markdown'
            )
        except Exception as e:
            print(f"Erro ao concluir tarefa notificada para {chat_id}: {e}")
            await query.edit_message_text("Ops! Não consegui marcar como concluída agora. Tente novamente! 😕")


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
    # INICIAR O SCHEDULER AQUI!
    if not scheduler.running:
        scheduler.start()
        print("APScheduler iniciado.")

    print("Agendando rotinas semanais existentes para todos os usuários...")
    rotinas_instance_dummy = RotinasSemanais(bot=application.bot)
    
    # Itera sobre todos os chat_ids que possuem rotinas salvas
    for chat_id in rotinas_agendadas.keys():
        # Passa a instância do bot para a função de reagendamento
        await rotinas_instance_dummy.reschedule_all_user_jobs(chat_id, application.bot)
