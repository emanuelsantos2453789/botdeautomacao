import os
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters
)

from handlers.pomodoro import Pomodoro
from handlers.metas import get_metas_conversation_handler, start_metas_menu
from handlers.agenda import Agenda

# --- Importa a classe RotinasSemanais, o scheduler e a função de startup ---
from handlers.rotina_pr import RotinasSemanais, scheduler, start_all_scheduled_jobs

# --- Configuração do Logging (Nível Militar: Detalhamento Completo) ---
# O logging é essencial para auditoria e depuração em um ambiente de produção.
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO # INFO para operação normal, DEBUG para depuração profunda
)
logger = logging.getLogger(__name__)

# --- Validação de Variáveis de Ambiente (Nível Militar: Nenhuma Falha Silenciosa) ---
# Cada variável crítica é verificada rigorosamente.
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    logger.critical("ERRO CRÍTICO: Variável de ambiente 'BOT_TOKEN' não encontrada. O bot não pode ser inicializado sem autenticação. Encerrando operação.")
    exit(1) # Falha fatal se o token não estiver presente

# Para Railway, a PORTa é injetada automaticamente. Definimos um fallback seguro.
PORT = int(os.getenv("PORT", 8080))
if not (1024 <= PORT <= 65535): # Valida a faixa de portas válidas
    logger.critical(f"ERRO CRÍTICO: A porta '{PORT}' fornecida via variável de ambiente 'PORT' é inválida. Use uma porta entre 1024 e 65535. Encerrando operação.")
    exit(1)

# O URL do Webhook é crítico para a comunicação no Railway.
# Deve ser o URL público do seu serviço no Railway, sem o caminho '/webhook'.
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
if not WEBHOOK_URL or not WEBHOOK_URL.startswith("https://"):
    logger.critical("ERRO CRÍTICO: Variável de ambiente 'WEBHOOK_URL' não encontrada ou inválida (deve começar com 'https://'). O bot não pode operar via Webhook. Encerrando operação.")
    exit(1)

# Definimos um caminho padrão para o Webhook que será concatenado ao WEBHOOK_URL
WEBHOOK_PATH = '/webhook'

# --- Global Conversation States ---
MAIN_MENU_STATE = 0


# --- Helper Functions for the Main Bot ---

def get_main_menu_keyboard():
    """Retorna o teclado do menu principal do bot."""
    keyboard = [
        [InlineKeyboardButton("🍅 Pomodoro", callback_data="open_pomodoro_menu")],
        [InlineKeyboardButton("🎯 Metas Semanaais", callback_data="open_metas_menu")],
        [InlineKeyboardButton("🗓️ Agenda", callback_data="open_agenda_menu")],
        [InlineKeyboardButton("📅 Rotinas Semanaais", callback_data="open_rotinas_semanais_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Responde ao comando /start e exibe o menu principal do bot."""
    logger.info(f"Comando /start recebido do usuário {update.effective_user.id} no chat {update.effective_chat.id}")
    try:
        await update.message.reply_text(
            "Olá! Eu sou seu bot de produtividade. Escolha uma opção e vamos começar! ✨",
            reply_markup=get_main_menu_keyboard()
        )
        return MAIN_MENU_STATE
    except Exception as e:
        logger.error(
            f"ERRO CRÍTICO no start_command para usuário {update.effective_user.id}: {e}",
            exc_info=True # Garante o traceback completo
        )
        # Tenta enviar uma mensagem de erro mesmo no start_command, para o usuário não ficar sem resposta
        if update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Ops! Não consegui iniciar o bot. Por favor, tente novamente mais tarde. 🚨"
            )
        return ConversationHandler.END


async def open_pomodoro_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler para o botão 'Pomodoro' no menu principal.
    Responsável por inicializar a instância do Pomodoro para o usuário
    e passar o controle para o ConversationHandler do Pomodoro.
    """
    query = update.callback_query
    if not query: # Garante que é um callback_query para evitar erros
        logger.warning("open_pomodoro_menu acionado sem CallbackQuery.")
        return MAIN_MENU_STATE
    
    logger.info(f"Usuário {query.from_user.id} abriu o menu Pomodoro.")
    try:
        # Tenta responder ao callback o mais rápido possível para evitar timeouts do Telegram
        await query.answer("Abrindo Pomodoro... ⏳") 

        # Garante que a instância de Pomodoro exista e esteja atualizada com os dados do bot/chat
        if 'pomodoro_instance' not in context.user_data or not isinstance(context.user_data['pomodoro_instance'], Pomodoro):
            logger.info(f"Criando nova instância Pomodoro para chat_id: {update.effective_chat.id}")
            context.user_data['pomodoro_instance'] = Pomodoro(bot=context.bot, chat_id=update.effective_chat.id)
        else:
            logger.info(f"Reutilizando e atualizando instância Pomodoro para chat_id: {update.effective_chat.id}")
            context.user_data['pomodoro_instance'].bot = context.bot
            context.user_data['pomodoro_instance'].chat_id = update.effective_chat.id
            
        pomodoro_instance = context.user_data['pomodoro_instance']
        
        # Delega para a lógica específica do Pomodoro
        return await pomodoro_instance._show_pomodoro_menu(update, context)
    except Exception as e:
        logger.error(
            f"ERRO GRAVE ao abrir o menu Pomodoro para o usuário {query.from_user.id}: {e}", 
            exc_info=True # Essencial para depuração
        )
        # Tenta editar a mensagem existente ou enviar uma nova se a edição falhar
        try:
            await query.edit_message_text(
                "Não foi possível abrir o Pomodoro no momento. Por favor, tente novamente ou volte ao menu principal. 🚧",
                reply_markup=get_main_menu_keyboard()
            )
        except Exception as edit_e:
            logger.error(f"Falha ao editar mensagem de erro no Pomodoro para {query.from_user.id}: {edit_e}", exc_info=True)
            if update.effective_chat:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="Um erro ocorreu no Pomodoro. Voltando ao menu principal. 🚧",
                    reply_markup=get_main_menu_keyboard()
                )
        return MAIN_MENU_STATE # Tenta retornar ao menu principal em caso de falha


async def open_metas_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler para o botão 'Metas Semanais' no menu principal.
    Chama a função start_metas_menu do módulo metas.
    """
    query = update.callback_query
    if not query:
        logger.warning("open_metas_menu acionado sem CallbackQuery.")
        return MAIN_MENU_STATE

    logger.info(f"Usuário {query.from_user.id} abriu o menu Metas Semanais.")
    try:
        await query.answer("Abrindo Metas Semanais... 🎯")
        return await start_metas_menu(update, context)
    except Exception as e:
        logger.error(
            f"ERRO GRAVE ao abrir o menu Metas Semanais para o usuário {query.from_user.id}: {e}", 
            exc_info=True
        )
        try:
            await query.edit_message_text(
                "Não foi possível abrir Metas Semanais no momento. Por favor, tente novamente ou volte ao menu principal. 🚧",
                reply_markup=get_main_menu_keyboard()
            )
        except Exception as edit_e:
            logger.error(f"Falha ao editar mensagem de erro em Metas para {query.from_user.id}: {edit_e}", exc_info=True)
            if update.effective_chat:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="Um erro ocorreu em Metas. Voltando ao menu principal. 🚧",
                    reply_markup=get_main_menu_keyboard()
                )
        return MAIN_MENU_STATE


async def open_agenda_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler para o botão 'Agenda' no menu principal.
    Cria uma instância da classe Agenda e delega para seu handler de início.
    """
    query = update.callback_query
    if not query:
        logger.warning("open_agenda_menu acionado sem CallbackQuery.")
        return MAIN_MENU_STATE

    logger.info(f"Usuário {query.from_user.id} abriu o menu Agenda.")
    try:
        await query.answer("Abrindo Agenda... 🗓️")
        if 'agenda_instance' not in context.user_data or not isinstance(context.user_data['agenda_instance'], Agenda):
            logger.info(f"Criando nova instância Agenda para chat_id: {update.effective_chat.id}")
            context.user_data['agenda_instance'] = Agenda(bot=context.bot, chat_id=update.effective_chat.id)
        else:
            logger.info(f"Reutilizando e atualizando instância Agenda para chat_id: {update.effective_chat.id}")
            context.user_data['agenda_instance'].bot = context.bot
            context.user_data['agenda_instance'].chat_id = update.effective_chat.id

        agenda_instance = context.user_data['agenda_instance']
        return await agenda_instance.start_agenda_main_menu(update, context)
    except Exception as e:
        logger.error(
            f"ERRO GRAVE ao abrir o menu Agenda para o usuário {query.from_user.id}: {e}", 
            exc_info=True
        )
        try:
            await query.edit_message_text(
                "Não foi possível abrir a Agenda no momento. Por favor, tente novamente ou volte ao menu principal. 🚧",
                reply_markup=get_main_menu_keyboard()
            )
        except Exception as edit_e:
            logger.error(f"Falha ao editar mensagem de erro na Agenda para {query.from_user.id}: {edit_e}", exc_info=True)
            if update.effective_chat:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="Um erro ocorreu na Agenda. Voltando ao menu principal. 🚧",
                    reply_markup=get_main_menu_keyboard()
                )
        return MAIN_MENU_STATE

async def open_rotinas_semanais_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler para o botão 'Rotinas Semanaais' no menu principal.
    Cria uma instância da classe RotinasSemanais e delega para seu handler de início.
    """
    query = update.callback_query
    if not query:
        logger.warning("open_rotinas_semanais_menu acionado sem CallbackQuery.")
        return MAIN_MENU_STATE

    logger.info(f"Usuário {query.from_user.id} abriu o menu Rotinas Semanais.")
    try:
        await query.answer("Abrindo Rotinas Semanais... 📅")
        if 'rotinas_semanais_instance' not in context.user_data or not isinstance(context.user_data['rotinas_semanais_instance'], RotinasSemanais):
            logger.info(f"Criando nova instância RotinasSemanais para chat_id: {update.effective_chat.id}")
            context.user_data['rotinas_semanais_instance'] = RotinasSemanais(bot=context.bot, chat_id=update.effective_chat.id)
        else:
            logger.info(f"Reutilizando e atualizando instância RotinasSemanais para chat_id: {update.effective_chat.id}")
            context.user_data['rotinas_semanais_instance'].bot = context.bot
            context.user_data['rotinas_semanais_instance'].chat_id = update.effective_chat.id

        rotinas_instance = context.user_data['rotinas_semanais_instance']
        return await rotinas_instance.start_rotinas_menu(update, context)
    except Exception as e:
        logger.error(
            f"ERRO GRAVE ao abrir o menu Rotinas Semanais para o usuário {query.from_user.id}: {e}", 
            exc_info=True
        )
        try:
            await query.edit_message_text(
                "Não foi possível abrir Rotinas Semanais no momento. Por favor, tente novamente ou volte ao menu principal. 🚧",
                reply_markup=get_main_menu_keyboard()
            )
        except Exception as edit_e:
            logger.error(f"Falha ao editar mensagem de erro em Rotinas para {query.from_user.id}: {edit_e}", exc_info=True)
            if update.effective_chat:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="Um erro ocorreu em Rotinas. Voltando ao menu principal. 🚧",
                    reply_markup=get_main_menu_keyboard()
                )
        return MAIN_MENU_STATE


async def return_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler para o callback 'main_menu_return'.
    Acionado quando o ConversationHandler do Pomodoro, Metas, Agenda ou Rotinas Semanais
    retorna ConversationHandler.END.
    """
    query = update.callback_query
    if not query:
        logger.warning("return_to_main_menu acionado sem CallbackQuery.")
        return MAIN_MENU_STATE

    logger.info(f"Usuário {query.from_user.id} retornou ao menu principal.")
    try:
        # Tenta responder ao callback o mais rápido possível para evitar timeouts
        await query.answer("Retornando ao menu principal...")
        await query.edit_message_text(
            "De volta ao menu principal. Escolha uma opção: ✨",
            reply_markup=get_main_menu_keyboard()
        )
        return MAIN_MENU_STATE
    except Exception as e:
        logger.error(
            f"ERRO GRAVE ao retornar ao menu principal para o usuário {query.from_user.id}: {e}", 
            exc_info=True
        )
        # Se falhar ao editar a mensagem, tenta enviar uma nova
        if update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Ocorreu um problema ao voltar ao menu. Por favor, tente novamente ou use /start. ⚠️",
                reply_markup=get_main_menu_keyboard()
            )
        return MAIN_MENU_STATE


async def fallback_global(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler de fallback global para mensagens ou callbacks inesperados
    em qualquer estado da conversa principal.
    """
    logger.warning(f"FALLBACK GLOBAL ACIONADO: Update: {update}")
    try:
        # Tenta identificar o tipo de update para dar feedback mais específico
        if update.message:
            logger.warning(f"Mensagem inesperada do usuário {update.effective_user.id}: '{update.message.text}'")
            await update.message.reply_text(
                "Desculpe, não entendi. Por favor, use os botões ou o comando /start. 🤔",
                reply_markup=get_main_menu_keyboard()
            )
        elif update.callback_query:
            query = update.callback_query
            logger.warning(f"Callback inesperado do usuário {query.from_user.id}: '{query.data}'")
            await query.answer("Ação inválida. Por favor, use os botões! 🚫")
            await query.edit_message_text(
                "Ação inválida. Escolha uma opção: 🧐",
                reply_markup=get_main_menu_keyboard()
            )
        else: # Outros tipos de update não tratados (ex: edits, channel posts)
            logger.warning(f"Update não tratado de tipo {type(update)} para o usuário {update.effective_user.id if update.effective_user else 'N/A'}.")
            if update.effective_chat:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="Desculpe, não consegui processar esta ação. Por favor, use os botões ou o comando /start. 🤷‍♂️"
                )
        return MAIN_MENU_STATE
    except Exception as e:
        logger.error(
            f"ERRO CRÍTICO no fallback_global para o usuário {update.effective_user.id if update.effective_user else 'N/A'}: {e}", 
            exc_info=True
        )
        if update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Ocorreu um erro inesperado no processamento de sua solicitação. Por favor, tente novamente ou use /start. 🆘"
            )
        return MAIN_MENU_STATE


async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler de erro global que captura QUALQUER exceção não tratada.
    É a sua blindagem 1000% (nível militar).
    """
    # Registra o erro completo no log, incluindo o traceback para depuração rigorosa
    logger.critical(f"EXCEÇÃO NÃO TRATADA! Update '{update}' causou erro: {context.error}", exc_info=True)

    # Tenta informar o usuário de forma amigável, indicando a gravidade
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="🚨 ATENÇÃO! Um erro crítico e inesperado ocorreu! Sua ação não pôde ser concluída. Nossos engenheiros foram alertados e já estão investigando. Por favor, tente novamente usando o comando /start. Sentimos o inconveniente. 🚨"
            )
        except Exception as e:
            # Se nem mesmo a mensagem de erro puder ser enviada, registra um erro crítico
            logger.critical(f"ERRO CRÍTICO DUPLO: Falha ao enviar mensagem de erro para o usuário {update.effective_chat.id}: {e}", exc_info=True)

# --- Função Principal para Iniciar o Bot ---

def main():
    """Configura e inicia o bot."""
    application = Application.builder().token(TOKEN).post_init(start_all_scheduled_jobs).build()

    # Instâncias temporárias para configurar os handlers
    temp_pomodoro_instance_for_handler_setup = Pomodoro()
    temp_agenda_instance_for_handler_setup = Agenda()
    temp_rotinas_semanais_instance_for_handler_setup = RotinasSemanais()

    main_conversation_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={
            MAIN_MENU_STATE: [
                CallbackQueryHandler(open_pomodoro_menu, pattern="^open_pomodoro_menu$"),
                CallbackQueryHandler(open_metas_menu, pattern="^open_metas_menu$"),
                CallbackQueryHandler(open_agenda_menu, pattern="^open_agenda_menu$"),
                CallbackQueryHandler(open_rotinas_semanais_menu, pattern="^open_rotinas_semanais_menu$"),

                # Integra os ConversationHandlers dos módulos de recursos
                temp_pomodoro_instance_for_handler_setup.get_pomodoro_conversation_handler(),
                get_metas_conversation_handler(),
                temp_agenda_instance_for_handler_setup.get_agenda_conversation_handler(),
                temp_rotinas_semanais_instance_for_handler_setup.get_rotinas_semanais_conversation_handler(),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(return_to_main_menu, pattern="^main_menu_return$"),
            MessageHandler(filters.ALL & ~filters.COMMAND, fallback_global),
            # O ConversationHandler em si pode ter um fallback mais específico se necessário
        ],
        # Garante que a conversa termine se o bot for reiniciado ou o estado for perdido
        map_to_parent={
            ConversationHandler.END: MAIN_MENU_STATE
        },
        # Nível de debug para o ConversationHandler, útil para ver transições de estado
        allow_reentry=True # Permite reentrar na conversa do Pomodoro, Metas, etc., se já estiver nela.
    )

    application.add_handler(main_conversation_handler)

    # --- Handler para o botão "Concluída!" na notificação (fora do ConversationHandler principal) ---
    application.add_handler(CallbackQueryHandler(
        temp_rotinas_semanais_instance_for_handler_setup.concluir_tarefa_notificada,
        pattern=r"^rotinas_concluir_.*$"
    ))

    # --- ADICIONA O HANDLER DE ERRO GLOBAL (A SUA BLINDAGEM NÍVEL MILITAR) ---
    application.add_error_handler(global_error_handler)

    logger.info("Configuração do bot concluída. Iniciando em modo Webhook... ✨")

    # --- INICIALIZAÇÃO DO BOT VIA WEBHOOK (CRÍTICO PARA RAILWAY) ---
    # Ouve em 0.0.0.0 para aceitar conexões de qualquer IP (padrão em contêineres)
    # na porta fornecida pelo Railway.
    # Define o url_path para onde o Telegram enviará as atualizações.
    # Define o webhook_url completo para que o bot registre isso na API do Telegram.
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=WEBHOOK_PATH,
        webhook_url=f"{WEBHOOK_URL}{WEBHOOK_PATH}"
    )

    logger.info("Bot rodando via Webhook no Railway com blindagem de nível militar! ✅")

if __name__ == "__main__":
    main()
