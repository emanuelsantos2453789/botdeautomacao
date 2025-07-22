import json
import re
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

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
            return json.load(f)
    except FileNotFoundError:
        return {} # Retorna um dicionário vazio se o arquivo não existir

def salvar_rotinas(data):
    """Salva as rotinas agendadas em um arquivo JSON."""
    with open(ROTINAS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# Carrega as rotinas ao iniciar o módulo
rotinas_agendadas = carregar_rotinas()

# --- Helpers de Parse da Rotina ---
def parse_rotina_textual(texto_rotina):
    """
    Analisa o texto de uma rotina semanal e o converte em uma estrutura de dados.
    """
    rotina_parsed = {}
    dias_da_semana = {
        "segunda-feira": "Segunda-feira",
        "terça-feira": "Terça-feira",
        "quarta-feira": "Quarta-feira",
        "quinta-feira": "Quinta-feira",
        "sexta-feira": "Sexta-feira",
        "sábado": "Sábado",
        "domingo": "Domingo"
    }

    # Divide o texto em blocos por dia da semana
    blocos_dias = re.split(r'^(?:[🟡🟠🔴🔵🟢🟣🟤]\s*)?([A-Za-zçÇáàãâéêíóôõúüÁÀÃÂÉÊÍÓÔÕÚÜ\s-]+-feira|Sábado|Domingo)\n', texto_rotina, flags=re.MULTILINE)

    for i in range(1, len(blocos_dias), 2):
        dia_bruto = blocos_dias[i].strip()
        conteudo_dia = blocos_dias[i+1].strip()

        dia_normalizado = next((dias_da_semana[k] for k in dias_da_semana if k in dia_bruto.lower()), None)

        if dia_normalizado:
            tarefas_do_dia = []
            padrao_tarefa = re.compile(r'(\d{1,2}h\d{2})\s*–\s*(\d{1,2}h\d{2}):\s*(.*)')
            
            for linha in conteudo_dia.split('\n'):
                match = padrao_tarefa.match(linha.strip())
                if match:
                    inicio = match.group(1).replace('h', ':')
                    fim = match.group(2).replace('h', ':')
                    descricao = match.group(3).strip()
                    tarefas_do_dia.append({"inicio": inicio, "fim": fim, "descricao": descricao})
            
            if tarefas_do_dia:
                rotina_parsed[dia_normalizado] = tarefas_do_dia
    
    return rotina_parsed


class RotinasSemanais:
    def __init__(self, bot=None, chat_id=None):
        self.bot = bot
        self.chat_id = chat_id
        # A instância de RotinasSemanais não armazena os dados, o módulo faz isso globalmente

    # --- Métodos para interagir com o usuário ---
    async def start_rotinas_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Exibe o menu principal das rotinas semanais."""
        keyboard = [
            [InlineKeyboardButton("Gerenciar Rotinas", callback_data="rotinas_gerenciar")],
            [InlineKeyboardButton("Adicionar Nova Rotina", callback_data="rotinas_adicionar")],
            [InlineKeyboardButton("↩️ Voltar ao Menu Principal", callback_data="main_menu_return")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        if update.callback_query:
            await update.callback_query.edit_message_text(
                "Menu de Rotinas Semanais: Escolha uma opção:",
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                "Menu de Rotinas Semanais: Escolha uma opção:",
                reply_markup=reply_markup
            )
        return MENU_ROTINAS

    async def gerenciar_rotinas(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Exibe as rotinas agendadas e opções para gerenciá-las."""
        query = update.callback_query
        await query.answer()
        chat_id = str(query.message.chat_id)

        if chat_id not in rotinas_agendadas or not rotinas_agendadas[chat_id]:
            keyboard = [[InlineKeyboardButton("↩️ Voltar", callback_data="rotinas_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "Você ainda não tem rotinas semanais agendadas. Use 'Adicionar Nova Rotina' para começar.",
                reply_markup=reply_markup
            )
            return MENU_ROTINAS

        # Ordenar os dias da semana para exibição
        dias_ordem = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"]
        
        mensagem = "*Suas Rotinas Semanais:*\n\n"
        keyboard_botoes = []

        # Para cada dia da semana, listar as tarefas
        for dia in dias_ordem:
            if dia in rotinas_agendadas[chat_id] and rotinas_agendadas[chat_id][dia]:
                mensagem += f"*{dia}:*\n"
                for idx, tarefa in enumerate(rotinas_agendadas[chat_id][dia]):
                    mensagem += f"  `{tarefa['inicio']}-{tarefa['fim']}`: {tarefa['descricao']}\n"
                    # Adiciona um botão para apagar tarefa individual
                    keyboard_botoes.append(
                        [InlineKeyboardButton(f"🗑️ Apagar {dia} {tarefa['inicio']}", callback_data=f"rotinas_apagar_{dia}_{idx}")]
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
        context.user_data['aguardando_rotina_texto'] = True # Sinaliza que o bot espera o texto da rotina

        keyboard = [[InlineKeyboardButton("↩️ Cancelar e Voltar", callback_data="rotinas_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "Por favor, envie sua rotina semanal no formato abaixo (cole o texto completo de uma vez):\n\n"
            "```\n📆 Nova Rotina Semanal (Segunda a Domingo)\n"
            "🟡 Segunda-feira\n⏰ Manhã e Tarde | Produtividade\n\n"
            "10h30 – 11h00: Café + alongamento\n"
            "11h00 – 13h00: Limpeza do quintal + organização externa\n"
            "...\n"
            "```\n\n"
            "Para cancelar, clique no botão abaixo.",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        return AGUARDANDO_ROTINA_TEXTO

    async def adicionar_rotina_processar(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Processa o texto da rotina enviado pelo usuário e o salva."""
        if not context.user_data.get('aguardando_rotina_texto'):
            # Caso o usuário envie texto sem ter clicado no botão "Adicionar"
            await update.message.reply_text("Parece que você não está no modo de adicionar rotina. Use o menu principal para isso.")
            return MENU_ROTINAS # Ou o estado MAIN_MENU_STATE se for para voltar ao menu principal do bot

        chat_id = str(update.message.chat_id)
        texto_rotina = update.message.text
        
        try:
            rotina_processada = parse_rotina_textual(texto_rotina)
            if not rotina_processada:
                await update.message.reply_text(
                    "Não consegui identificar nenhuma rotina no texto que você enviou. "
                    "Por favor, verifique o formato e tente novamente, "
                    "ou clique em 'Cancelar' para voltar."
                )
                return AGUARDANDO_ROTINA_TEXTO # Permanece no estado de aguardando texto

            if chat_id not in rotinas_agendadas:
                rotinas_agendadas[chat_id] = {}
            
            # Adiciona as novas rotinas, mesclando com as existentes se houver
            for dia, tarefas in rotina_processada.items():
                if dia not in rotinas_agendadas[chat_id]:
                    rotinas_agendadas[chat_id][dia] = []
                
                # Adiciona apenas tarefas que ainda não existem para evitar duplicatas exatas
                for nova_tarefa in tarefas:
                    if nova_tarefa not in rotinas_agendadas[chat_id][dia]:
                        rotinas_agendadas[chat_id][dia].append(nova_tarefa)
            
            salvar_rotinas(rotinas_agendadas) # Salva as rotinas no arquivo

            # Limpa o estado
            del context.user_data['aguardando_rotina_texto'] 

            await update.message.reply_text(
                "🎉 Rotina semanal adicionada com sucesso! Você pode gerenciá-la no menu 'Gerenciar Rotinas'."
            )
            return await self.start_rotinas_menu(update, context) # Volta para o menu de rotinas

        except Exception as e:
            await update.message.reply_text(
                f"Ocorreu um erro ao processar sua rotina: `{e}`. "
                "Por favor, tente novamente ou verifique o formato.",
                parse_mode='Markdown'
            )
            # del context.user_data['aguardando_rotina_texto'] # Pode-se decidir se reseta ou não aqui
            return AGUARDANDO_ROTINA_TEXTO # Permanece no estado para uma nova tentativa

    async def apagar_tarefa(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Apaga uma tarefa específica da rotina do usuário."""
        query = update.callback_query
        await query.answer()
        chat_id = str(query.message.chat_id)

        # O callback_data será algo como "rotinas_apagar_DiaDaSemana_indice"
        _, _, dia, idx_str = query.data.split('_')
        idx = int(idx_str)

        if chat_id in rotinas_agendadas and dia in rotinas_agendadas[chat_id] and 0 <= idx < len(rotinas_agendadas[chat_id][dia]):
            tarefa_removida = rotinas_agendadas[chat_id][dia].pop(idx)
            
            # Se o dia ficar vazio, remove o dia
            if not rotinas_agendadas[chat_id][dia]:
                del rotinas_agendadas[chat_id][dia]
            
            # Se o chat_id não tiver mais rotinas, remove o chat_id
            if not rotinas_agendadas[chat_id]:
                del rotinas_agendadas[chat_id]

            salvar_rotinas(rotinas_agendadas)
            await query.edit_message_text(f"🗑️ Tarefa '{tarefa_removida['descricao']}' removida com sucesso!")
        else:
            await query.edit_message_text("Essa tarefa não foi encontrada ou já foi removida.")
        
        # Volta para o menu de gerenciar rotinas para ver o estado atualizado
        return await self.gerenciar_rotinas(update, context)


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
                    # Handler para voltar do sub-menu para o menu principal das rotinas
                    CallbackQueryHandler(self.start_rotinas_menu, pattern="^rotinas_menu$"),
                ],
                AGUARDANDO_ROTINA_TEXTO: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.adicionar_rotina_processar),
                    CallbackQueryHandler(self.start_rotinas_menu, pattern="^rotinas_menu$"), # Para cancelar
                ],
                GERENCIAR_ROTINAS: [
                    CallbackQueryHandler(self.apagar_tarefa, pattern=r"^rotinas_apagar_.*$"),
                    CallbackQueryHandler(self.start_rotinas_menu, pattern="^rotinas_menu$"), # Para voltar
                ]
            },
            fallbacks=[
                CallbackQueryHandler(self.start_rotinas_menu, pattern="^rotinas_menu$"), # Fallback para voltar ao menu de rotinas
                # Importante: O retorno para o menu principal do bot (`main_menu_return`)
                # deve ser tratado no ConversationHandler principal em `main.py`.
            ],
            map_to_parent={
                # Retorna ao MAIN_MENU_STATE do ConversationHandler principal
                ConversationHandler.END: ConversationHandler.END 
            }
        )
