import json
import re
from datetime import datetime, timedelta, date
from collections import defaultdict
import uuid
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    Application,
    JobQueue, # Importado para tipagem
)

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

# Configuração de logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Constantes de Estado da Conversa ---
MENU_ROTINAS = 0
AGUARDANDO_ROTINA_TEXTO = 1
GERENCIAR_ROTINAS = 2
LISTAR_TAREFAS_AVULSAS = 3
AGUARDANDO_MOTIVO_NAO_CONCLUIDA = 4
DELETAR_TAREFA_AVULSA = 5

# --- Helpers de persistência de Rotinas Semanais ---
ROTINAS_FILE = 'rotinas_semanais_data.json'
TASKS_FILE = 'tasks_data.json' # Novo arquivo para persistir tarefas avulsas se não usar PicklePersistence

def carregar_rotinas():
    """Carrega as rotinas agendadas de um arquivo JSON."""
    try:
        with open(ROTINAS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return defaultdict(dict, {k: defaultdict(list, v) for k, v in data.items()})
    except FileNotFoundError:
        logger.info(f"Arquivo {ROTINAS_FILE} não encontrado. Iniciando com rotinas vazias.")
        return defaultdict(dict)
    except json.JSONDecodeError as e:
        logger.error(f"Erro ao decodificar JSON do arquivo {ROTINAS_FILE}: {e}. Retornando rotinas vazias.")
        return defaultdict(dict)
    except Exception as e:
        logger.error(f"Erro inesperado ao carregar rotinas do arquivo {ROTINAS_FILE}: {e}. Retornando rotinas vazias.")
        return defaultdict(dict)

def salvar_rotinas(data):
    """Salva as rotinas agendadas em um arquivo JSON."""
    try:
        with open(ROTINAS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except IOError as e:
        logger.error(f"Erro de I/O ao salvar rotinas no arquivo {ROTINAS_FILE}: {e}")
    except Exception as e:
        logger.error(f"Erro inesperado ao salvar rotinas no arquivo {ROTINAS_FILE}: {e}")

# Carrega as rotinas ao iniciar o módulo
rotinas_agendadas = carregar_rotinas()

# Mapeamento para garantir a ordem dos dias da semana
DIAS_DA_SEMANA_ORDEM = [
    "Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira",
    "Sexta-feira", "Sábado", "Domingo"
]

# Objeto do APScheduler para gerenciar os jobs de rotina semanal
scheduler = AsyncIOScheduler()

# --- Helpers de Parse da Rotina ---
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
                        "id": uuid.uuid4().hex,
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
                        "id": uuid.uuid4().hex,
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
                        "id": uuid.uuid4().hex,
                        "tipo": "periodo_geral",
                        "periodo": periodo,
                        "descricao": desc
                    })
                    continue

                tarefas_do_dia.append({
                    "id": uuid.uuid4().hex,
                    "tipo": "descricao_simples",
                    "descricao": linha
                })

            if tarefas_do_dia:
                rotina_parsed[dia_normalizado] = tarefas_do_dia
                
    return rotina_parsed

class AgendaManager:
    def __init__(self, application: Application):
        self.application = application
        self.bot = application.bot
        self.job_queue = application.job_queue

    # --- Métodos de Rotinas Semanais (APScheduler) ---

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
                        t.get('tipo') == nova_tarefa.get('tipo')
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
            
            await self.reschedule_all_user_jobs(chat_id, self.bot)

            return await self.start_rotinas_menu(update, context)

        except Exception as e:
            logger.error(f"Erro ao processar rotina para {chat_id}: {e}", exc_info=True)
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

        _, _, dia_str, tarefa_id = query.data.split('_')
        
        user_rotinas = rotinas_agendadas.get(chat_id, {})
        tarefa_encontrada = False
        dia_da_tarefa = None
        tarefa_removida_descricao = "Tarefa"

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
            if dia_da_tarefa and not user_rotinas[dia_da_tarefa]:
                del user_rotinas[dia_da_tarefa]
            
            if not user_rotinas:
                del rotinas_agendadas[chat_id]

            salvar_rotinas(rotinas_agendadas)
            
            # Remove o job agendado correspondente do APScheduler
            job_id = f"rotina_notificacao_{chat_id}_{tarefa_id}"
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
                logger.info(f"Job APScheduler {job_id} removido.")
            job_id_livre = f"rotina_livre_notificacao_{chat_id}_{tarefa_id}"
            if scheduler.get_job(job_id_livre):
                scheduler.remove_job(job_id_livre)
                logger.info(f"Job APScheduler {job_id_livre} removido.")

            await query.edit_message_text(f"🗑️ Tarefa removida: _{tarefa_removida_descricao}_. Certo! ✅")
            
            await self.reschedule_all_user_jobs(chat_id, self.bot)
        else:
            await query.edit_message_text("Essa tarefa não foi encontrada ou já foi removida. Tente novamente listando as rotinas. 🤔")
        
        return await self.gerenciar_rotinas(update, context)

    # --- Lógica de Agendamento de Rotinas (APScheduler) ---

    async def reschedule_all_user_jobs(self, chat_id: str, bot_instance: ContextTypes.DEFAULT_TYPE):
        """
        Remove todos os jobs de APScheduler agendados para um usuário e os reagenda com as rotinas atuais.
        Chamado após adicionar/remover rotinas.
        """
        logger.info(f"Reagendando jobs de rotina para o chat_id: {chat_id}")
        # Remove todos os jobs antigos deste usuário do APScheduler
        for job in scheduler.get_jobs():
            if job.id.startswith(f"rotina_notificacao_{chat_id}_") or job.id.startswith(f"rotina_livre_notificacao_{chat_id}_"):
                try:
                    scheduler.remove_job(job.id)
                    logger.info(f"Job APScheduler {job.id} removido durante reagendamento.")
                except Exception as e:
                    logger.error(f"Erro ao remover job {job.id}: {e}")
        
        user_rotinas = rotinas_agendadas.get(chat_id)
        if not user_rotinas:
            logger.info(f"Nenhuma rotina encontrada para {chat_id}. Nenhum job APScheduler agendado.")
            return

        for dia_nome in DIAS_DA_SEMANA_ORDEM:
            if dia_nome in user_rotinas:
                dia_idx = DIAS_DA_SEMANA_ORDEM.index(dia_nome)
                
                for tarefa in user_rotinas[dia_nome]:
                    if tarefa['tipo'] == "horario_fixo":
                        inicio_str = tarefa.get('inicio')
                        if not inicio_str:
                            logger.warning(f"Tarefa {tarefa.get('id', 'N/A')} para o chat {chat_id} não possui horário de início. Pulando agendamento APScheduler.")
                            continue

                        try:
                            hour = int(inicio_str.split(':')[0])
                            minute = int(inicio_str.split(':')[1])
                        except (ValueError, IndexError) as e:
                            logger.error(f"Erro ao parsear horário de início '{inicio_str}' da tarefa {tarefa.get('id', 'N/A')} para o chat {chat_id}: {e}. Pulando agendamento APScheduler.")
                            continue

                        job_id = f"rotina_notificacao_{chat_id}_{tarefa['id']}"
                        
                        scheduler.add_job(
                            self._send_routine_notification,
                            'cron',
                            day_of_week=dia_idx,
                            hour=hour,
                            minute=minute,
                            id=job_id,
                            args=[chat_id, tarefa, bot_instance],
                            misfire_grace_time=60
                        )
                        logger.info(f"APScheduler job '{job_id}' agendado para {dia_nome} às {hour:02d}:{minute:02d}.")
                    elif tarefa['tipo'] == "periodo_livre" and tarefa.get('fim_sugerido'):
                        fim_str = tarefa.get('fim_sugerido')
                        if not fim_str:
                            logger.warning(f"Período livre {tarefa.get('id', 'N/A')} para o chat {chat_id} não possui horário de fim sugerido. Pulando agendamento APScheduler.")
                            continue

                        try:
                            hour = int(fim_str.split(':')[0])
                            minute = int(fim_str.split(':')[1])
                        except (ValueError, IndexError) as e:
                            logger.error(f"Erro ao parsear horário de fim '{fim_str}' do período livre {tarefa.get('id', 'N/A')} para o chat {chat_id}: {e}. Pulando agendamento APScheduler.")
                            continue
                        
                        job_id_livre = f"rotina_livre_notificacao_{chat_id}_{tarefa['id']}"
                        
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
                        logger.info(f"APScheduler job '{job_id_livre}' agendado para {dia_nome} às {hour:02d}:{minute:02d} (fim período livre).")


    async def _send_routine_notification(self, chat_id: str, tarefa: dict, bot_instance: ContextTypes.DEFAULT_TYPE):
        """Envia a notificação da tarefa de rotina ao usuário (via APScheduler)."""
        try:
            descricao = tarefa.get('descricao', 'Sua tarefa de rotina')
            duracao_info = f" ({tarefa.get('duracao', 'N/A')})" if tarefa.get('duracao') else ""
            
            keyboard = [
                [InlineKeyboardButton("✅ Concluída!", callback_data=f"rotinas_concluir_{tarefa.get('id', 'unknown_id')}")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await bot_instance.send_message(
                chat_id=chat_id,
                text=f"🔔 *ATENÇÃO! Sua próxima tarefa de rotina começa AGORA:*\n\n"
                     f"⏰ `{tarefa.get('inicio', '??:??')}-{tarefa.get('fim', '??:??')}`: _{descricao}_{duracao_info}\n\n"
                     f"Já concluiu? Me avise para eu registrar! 👇",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            logger.info(f"Notificação de rotina enviada para {chat_id} para tarefa {tarefa.get('id')}")
        except Exception as e:
            logger.error(f"Erro ao enviar notificação de rotina para {chat_id}: {e}", exc_info=True)

    async def _send_free_period_notification(self, chat_id: str, tarefa: dict, bot_instance: ContextTypes.DEFAULT_TYPE):
        """Envia uma notificação informando que o usuário está livre (via APScheduler)."""
        try:
            await bot_instance.send_message(
                chat_id=chat_id,
                text=f"🥳 *Ótima notícia!* Seu período de _{tarefa.get('descricao', 'tempo livre')}_ termina agora. "
                     "Você está *livre* para o que quiser! Que tal um descanso? ☕",
                parse_mode='Markdown'
            )
            logger.info(f"Notificação de período livre enviada para {chat_id} para tarefa {tarefa.get('id')}")
        except Exception as e:
            logger.error(f"Erro ao enviar notificação de período livre para {chat_id}: {e}", exc_info=True)

    async def concluir_tarefa_notificada_rotina(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Marca uma tarefa de rotina notificada como concluída.
        Esta função apenas edita a mensagem de notificação, pois as rotinas são recorrentes
        e não são "removidas" após uma única conclusão.
        """
        query = update.callback_query
        chat_id = str(query.message.chat_id)
        
        try:
            _, _, tarefa_id = query.data.split('_')
        except ValueError:
            logger.error(f"Erro ao extrair tarefa_id do callback_data: {query.data}")
            await query.edit_message_text("Ops! Não consegui identificar a tarefa de rotina. Tente novamente! 😕")
            return

        try:
            await query.edit_message_text(
                f"🎉 Tarefa de rotina marcada como *concluída*! Mandou bem! 💪\n\n"
                f"Sua próxima notificação chegará no horário! 🔔",
                parse_mode='Markdown'
            )
            logger.info(f"Tarefa de rotina {tarefa_id} marcada como concluída para {chat_id}")
        except Exception as e:
            logger.error(f"Erro ao concluir tarefa de rotina notificada para {chat_id}: {e}", exc_info=True)
            await query.edit_message_text("Ops! Não consegui marcar como concluída agora. Tente novamente! 😕")


    # --- Métodos de Gerenciamento de Tarefas Avulsas (JobQueue) ---

    async def create_one_off_task(self, update: Update, context: ContextTypes.DEFAULT_TYPE, description: str, delay_minutes: int):
        """
        Cria uma tarefa avulsa e agenda um lembrete usando JobQueue.
        Para testes de "30 min e 1 hora".
        """
        chat_id = str(update.effective_chat.id)
        if 'tasks' not in context.user_data:
            context.user_data['tasks'] = []

        task_id = uuid.uuid4().hex
        
        # Calcula o horário de agendamento
        run_at = datetime.now() + timedelta(minutes=delay_minutes)

        task = {
            'id': task_id,
            'description': description,
            'scheduled_time': run_at.isoformat(),
            'completed': False,
            'not_completed_reason': None
        }
        context.user_data['tasks'].append(task)
        
        # Agenda o job com JobQueue
        self.job_queue.run_once(
            self._send_one_off_task_notification,
            run_at,
            chat_id=chat_id,
            data={'task_id': task_id, 'description': description},
            name=f"one_off_task_{chat_id}_{task_id}"
        )
        
        await update.message.reply_text(
            f"✅ Lembrete para '{description}' agendado para daqui a {delay_minutes} minutos ({run_at.strftime('%H:%M')})."
        )
        logger.info(f"Tarefa avulsa '{description}' agendada para {chat_id} em {delay_minutes} minutos.")


    async def _send_one_off_task_notification(self, context: ContextTypes.DEFAULT_TYPE):
        """
        Envia a notificação de uma tarefa avulsa (chamada por JobQueue).
        """
        job = context.job
        chat_id = job.chat_id
        task_id = job.data['task_id']
        description = job.data['description']

        user_tasks = context.application.user_data.get(chat_id, {}).get('tasks', [])
        task_found = False
        for task in user_tasks:
            if task['id'] == task_id:
                task_found = True
                if task['completed']:
                    logger.info(f"Tarefa {task_id} para {chat_id} já concluída. Não enviando notificação.")
                    return
                break
        
        if not task_found:
            logger.warning(f"Tarefa {task_id} não encontrada para {chat_id}. Possivelmente já foi removida.")
            return

        keyboard = [
            [InlineKeyboardButton("✅ Concluída!", callback_data=f"task_complete_{task_id}")],
            [InlineKeyboardButton("❌ Não Concluída", callback_data=f"task_not_complete_{task_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🔔 *Lembrete!* Hora de: _{description}_\n\n"
                     "Marque como concluída ou me diga o motivo se não conseguiu. 👇",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            logger.info(f"Notificação de tarefa avulsa enviada para {chat_id}: {description}")
        except Exception as e:
            logger.error(f"Erro ao enviar notificação de tarefa avulsa para {chat_id}: {e}", exc_info=True)


    async def handle_task_completion(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Processa a ação do usuário quando ele marca uma tarefa avulsa como concluída."""
        query = update.callback_query
        await query.answer()
        chat_id = str(query.message.chat_id)
        task_id = query.data.split('_')[2]

        user_tasks = context.user_data.get('tasks', [])
        task_found = False
        for task in user_tasks:
            if task['id'] == task_id:
                task['completed'] = True
                task_found = True
                break
        
        if task_found:
            await query.edit_message_text(f"🎉 Parabéns! Tarefa marcada como *concluída*: _{task['description']}_ 💪", parse_mode='Markdown')
            
            # Remove todos os jobs agendados para esta tarefa específica
            for job in context.job_queue.get_jobs_by_name(f"one_off_task_{chat_id}_{task_id}"):
                job.schedule_removal()
            logger.info(f"Tarefa avulsa {task_id} para {chat_id} marcada como concluída e jobs removidos.")
        else:
            await query.edit_message_text("Essa tarefa não foi encontrada ou já foi concluída/removida. 🤔")

    async def handle_task_not_completed(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Gerencia o fluxo quando um usuário indica que não conseguiu concluir uma tarefa avulsa."""
        query = update.callback_query
        await query.answer()
        chat_id = str(query.message.chat_id)
        task_id = query.data.split('_')[2]

        user_tasks = context.user_data.get('tasks', [])
        task_found = False
        for task in user_tasks:
            if task['id'] == task_id:
                context.user_data['current_task_for_reason'] = task_id
                task_found = True
                break
        
        if task_found:
            await query.edit_message_text(
                f"Entendido. Por favor, me diga por que você não conseguiu concluir a tarefa: _{task['description']}_",
                parse_mode='Markdown'
            )
            return AGUARDANDO_MOTIVO_NAO_CONCLUIDA
        else:
            await query.edit_message_text("Essa tarefa não foi encontrada ou já foi concluída/removida. 🤔")
            return ConversationHandler.END # Ou um estado apropriado para voltar ao menu principal

    async def process_not_completed_reason(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Recebe e registra o motivo pelo qual o usuário não concluiu uma tarefa avulsa."""
        chat_id = str(update.message.chat_id)
        reason = update.message.text
        task_id = context.user_data.pop('current_task_for_reason', None)

        if not task_id:
            await update.message.reply_text("Ops, não consegui associar o motivo a uma tarefa. Por favor, tente novamente.")
            return ConversationHandler.END
        
        user_tasks = context.user_data.get('tasks', [])
        task_found = False
        for task in user_tasks:
            if task['id'] == task_id:
                task['not_completed_reason'] = reason
                task['completed'] = False # Mantém como não concluída, mas com motivo
                task_found = True
                break
        
        if task_found:
            await update.message.reply_text(
                f"Motivo registrado para a tarefa _{task['description']}_. Obrigado pelo feedback!",
                parse_mode='Markdown'
            )
            # Remove todos os jobs agendados para esta tarefa específica
            for job in context.job_queue.get_jobs_by_name(f"one_off_task_{chat_id}_{task_id}"):
                job.schedule_removal()
            logger.info(f"Motivo de não conclusão registrado para tarefa avulsa {task_id} para {chat_id} e jobs removidos.")
        else:
            await update.message.reply_text("Essa tarefa não foi encontrada ou já foi concluída/removida. 🤔")
        
        return ConversationHandler.END # Ou um estado apropriado para voltar ao menu principal

    async def list_upcoming_tasks(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Lista as tarefas avulsas não concluídas e futuras."""
        chat_id = str(update.effective_chat.id)
        user_tasks = context.user_data.get('tasks', [])
        
        upcoming_tasks = [
            task for task in user_tasks 
            if not task['completed'] and datetime.fromisoformat(task['scheduled_time']) > datetime.now()
        ]
        upcoming_tasks.sort(key=lambda x: x['scheduled_time'])

        if not upcoming_tasks:
            text = "🎉 Você não tem tarefas avulsas futuras agendadas! Que tal adicionar uma? 👇"
        else:
            text = "🗓️ *Suas Próximas Tarefas Avulsas:*\n\n"
            for task in upcoming_tasks:
                scheduled_dt = datetime.fromisoformat(task['scheduled_time'])
                text += f"• _{task['description']}_ em *{scheduled_dt.strftime('%d/%m %H:%M')}*\n"
        
        keyboard = [
            [InlineKeyboardButton("➕ Adicionar Nova Tarefa Avulsa", callback_data="add_one_off_task")], # Implementar este fluxo
            [InlineKeyboardButton("↩️ Voltar ao Menu Principal", callback_data="main_menu_return")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if update.callback_query:
            await update.callback_query.edit_message_text(text, parse_mode='Markdown', reply_markup=reply_markup)
        else:
            await update.message.reply_text(text, parse_mode='Markdown', reply_markup=reply_markup)
        
        return LISTAR_TAREFAS_AVULSAS

    async def list_completed_tasks(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Lista as tarefas avulsas concluídas (ou com motivo de não conclusão)."""
        chat_id = str(update.effective_chat.id)
        user_tasks = context.user_data.get('tasks', [])
        
        completed_tasks = [task for task in user_tasks if task['completed'] or task['not_completed_reason']]
        completed_tasks.sort(key=lambda x: x['scheduled_time'], reverse=True) # Mais recentes primeiro

        if not completed_tasks:
            text = "Você ainda não concluiu ou registrou feedback para nenhuma tarefa avulsa. 🤷‍♀️"
        else:
            text = "✅ *Suas Tarefas Avulsas Concluídas/Revisadas:*\n\n"
            for task in completed_tasks:
                status = "✅ Concluída" if task['completed'] else "❌ Não Concluída"
                reason = f" (Motivo: _{task['not_completed_reason']}_)" if task['not_completed_reason'] else ""
                scheduled_dt = datetime.fromisoformat(task['scheduled_time'])
                text += f"• _{task['description']}_ ({scheduled_dt.strftime('%d/%m %H:%M')}) - *{status}*{reason}\n"
        
        keyboard = [[InlineKeyboardButton("↩️ Voltar ao Menu Principal", callback_data="main_menu_return")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if update.callback_query:
            await update.callback_query.edit_message_text(text, parse_mode='Markdown', reply_markup=reply_markup)
        else:
            await update.message.reply_text(text, parse_mode='Markdown', reply_markup=reply_markup)
        
        return ConversationHandler.END # Ou um estado apropriado

    async def initiate_delete_task(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Inicia o processo de exclusão de uma tarefa avulsa, listando as opções."""
        query = update.callback_query
        await query.answer()
        chat_id = str(query.message.chat_id)

        user_tasks = context.user_data.get('tasks', [])
        deletable_tasks = [task for task in user_tasks if not task['completed']] # Só permite apagar não concluídas
        deletable_tasks.sort(key=lambda x: x['scheduled_time'])

        if not deletable_tasks:
            keyboard = [[InlineKeyboardButton("↩️ Voltar", callback_data="main_menu_return")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "Você não tem tarefas avulsas ativas para apagar. ✨",
                reply_markup=reply_markup
            )
            return ConversationHandler.END

        text = "🗑️ *Qual tarefa avulsa você gostaria de apagar?*\n\n"
        keyboard = []
        for task in deletable_tasks:
            scheduled_dt = datetime.fromisoformat(task['scheduled_time'])
            keyboard.append([InlineKeyboardButton(
                f"❌ {task['description']} ({scheduled_dt.strftime('%d/%m %H:%M')})",
                callback_data=f"confirm_delete_task_{task['id']}"
            )])
        
        keyboard.append([InlineKeyboardButton("↩️ Voltar", callback_data="main_menu_return")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=reply_markup)
        return DELETAR_TAREFA_AVULSA

    async def confirm_delete_task(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Solicita confirmação antes de apagar uma tarefa avulsa."""
        query = update.callback_query
        await query.answer()
        task_id = query.data.split('_')[3] # confirm_delete_task_TASKID

        context.user_data['task_to_delete_id'] = task_id

        user_tasks = context.user_data.get('tasks', [])
        task_description = "tarefa desconhecida"
        for task in user_tasks:
            if task['id'] == task_id:
                task_description = task['description']
                break

        keyboard = [
            [InlineKeyboardButton("✅ Sim, Apagar", callback_data="execute_delete_task_yes")],
            [InlineKeyboardButton("❌ Não, Voltar", callback_data="execute_delete_task_no")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            f"Tem certeza que deseja apagar a tarefa: _{task_description}_?",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        return DELETAR_TAREFA_AVULSA

    async def execute_delete_task(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Executa a exclusão da tarefa avulsa após confirmação."""
        query = update.callback_query
        await query.answer()
        chat_id = str(query.message.chat_id)
        
        if query.data == "execute_delete_task_no":
            del context.user_data['task_to_delete_id']
            await query.edit_message_text("Exclusão cancelada. Voltando ao menu principal. ↩️")
            return ConversationHandler.END # Ou um estado apropriado

        task_id_to_delete = context.user_data.pop('task_to_delete_id', None)

        if not task_id_to_delete:
            await query.edit_message_text("Ops! Não consegui identificar a tarefa para apagar. Tente novamente. 🤔")
            return ConversationHandler.END
        
        user_tasks = context.user_data.get('tasks', [])
        initial_len = len(user_tasks)
        context.user_data['tasks'] = [task for task in user_tasks if task['id'] != task_id_to_delete]
        
        if len(context.user_data['tasks']) < initial_len:
            # Tarefa removida com sucesso
            await query.edit_message_text("🗑️ Tarefa avulsa apagada com sucesso! ✅")
            
            # Remove jobs do JobQueue associados a esta tarefa
            jobs = context.job_queue.get_jobs_by_name(f"one_off_task_{chat_id}_{task_id_to_delete}")
            for job in jobs:
                job.schedule_removal()
            logger.info(f"Tarefa avulsa {task_id_to_delete} para {chat_id} removida e jobs JobQueue cancelados.")
        else:
            await query.edit_message_text("Essa tarefa não foi encontrada ou já foi removida. 🤔")
        
        return ConversationHandler.END # Ou um estado apropriado

    # --- Configuração do ConversationHandler ---

    def get_agenda_conversation_handler(self) -> ConversationHandler:
        """
        Retorna o ConversationHandler para a funcionalidade de Agenda (Rotinas e Tarefas Avulsas).
        """
        return ConversationHandler(
            entry_points=[
                CallbackQueryHandler(self.start_rotinas_menu, pattern="^open_rotinas_semanais_menu$"),
                CallbackQueryHandler(self.list_upcoming_tasks, pattern="^open_tasks_menu$"), # Novo entry point para tarefas avulsas
            ],
            states={
                MENU_ROTINAS: [
                    CallbackQueryHandler(self.gerenciar_rotinas, pattern="^rotinas_gerenciar$"),
                    CallbackQueryHandler(self.adicionar_rotina_preparar, pattern="^rotinas_adicionar$"),
                    CallbackQueryHandler(self.start_rotinas_menu, pattern="^rotinas_menu$"),
                    # Handler para concluir tarefas de rotina (notificações do APScheduler)
                    CallbackQueryHandler(self.concluir_tarefa_notificada_rotina, pattern=r"^rotinas_concluir_.*$"),
                ],
                AGUARDANDO_ROTINA_TEXTO: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.adicionar_rotina_processar),
                    CallbackQueryHandler(self.start_rotinas_menu, pattern="^rotinas_menu$"),
                ],
                GERENCIAR_ROTINAS: [
                    CallbackQueryHandler(self.apagar_tarefa, pattern=r"^rotinas_apagar_.*$"),
                    CallbackQueryHandler(self.start_rotinas_menu, pattern="^rotinas_menu$"),
                ],
                LISTAR_TAREFAS_AVULSAS: [
                    # Handler para adicionar tarefa avulsa (ainda precisa de um fluxo de input)
                    # CallbackQueryHandler(self.add_one_off_task_preparar, pattern="^add_one_off_task$"), 
                    CallbackQueryHandler(self.list_completed_tasks, pattern="^list_completed_tasks$"), # Exemplo
                    CallbackQueryHandler(self.initiate_delete_task, pattern="^initiate_delete_task$"), # Exemplo
                    CallbackQueryHandler(self.list_upcoming_tasks, pattern="^list_upcoming_tasks$"),
                    CallbackQueryHandler(self.start_rotinas_menu, pattern="^rotinas_menu$"), # Voltar para menu de rotinas
                    CallbackQueryHandler(self.list_upcoming_tasks, pattern="^main_menu_return$"), # Para voltar ao próprio menu de tarefas
                ],
                AGUARDANDO_MOTIVO_NAO_CONCLUIDA: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_not_completed_reason),
                ],
                DELETAR_TAREFA_AVULSA: [
                    CallbackQueryHandler(self.confirm_delete_task, pattern=r"^confirm_delete_task_.*$"),
                    CallbackQueryHandler(self.execute_delete_task, pattern=r"^execute_delete_task_.*$"),
                    # Fallback para caso o usuário cancele ou queira voltar
                    CallbackQueryHandler(self.list_upcoming_tasks, pattern="^main_menu_return$"), 
                ]
            },
            fallbacks=[
                CallbackQueryHandler(self.start_rotinas_menu, pattern="^rotinas_menu$"),
                CallbackQueryHandler(self.list_upcoming_tasks, pattern="^main_menu_return$"), # Para o caso de estar no fluxo de tarefas avulsas
                # Adicione outros fallbacks gerais se necessário
            ],
            map_to_parent={
                ConversationHandler.END: ConversationHandler.END
            }
        )

# Função para iniciar o agendamento de todas as rotinas existentes (ao iniciar o bot)
async def start_all_scheduled_jobs(application: Application):
    """
    Função chamada uma vez na inicialização do bot para agendar todas as rotinas salvas
    com APScheduler.
    """
    if not scheduler.running:
        scheduler.start()
        logger.info("APScheduler iniciado.")

    logger.info("Agendando rotinas semanais existentes para todos os usuários...")
    # Criar uma instância dummy de AgendaManager para acessar reschedule_all_user_jobs
    # sem precisar de um Update/Context real
    agenda_manager_dummy = AgendaManager(application) 
    
    for chat_id in rotinas_agendadas.keys():
        await agenda_manager_dummy.reschedule_all_user_jobs(chat_id, application.bot)
    logger.info("Agendamento inicial de rotinas semanais concluído.")
