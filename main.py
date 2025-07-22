import os
import logging # Importa o módulo de logging
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

# --- Configuração do Logging (Primeira Linha de Defesa) ---
# Isso garante que qualquer erro, mesmo antes do bot iniciar completamente, seja registrado
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO # Use logging.DEBUG para ver mais detalhes (ideal para desenvolvimento)
)
logger = logging.getLogger(__name__)

# --- 1. Seu Bot Token agora vem das variáveis de ambiente ---
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    logger.critical("ERRO CRÍTICO: A variável de ambiente BOT_TOKEN não foi encontrada! O bot não poderá iniciar.")
    exit(1) # Sai do programa se o token não for encontrado

# --- Global Conversation States (of the main bot) ---
MAIN_MENU_STATE = 0


# --- Helper Functions for the Main Bot ---

def get_main_menu_keyboard():
    """Retorna o teclado do menu principal do bot."""
    keyboard = [
        [InlineKeyboardButton("🍅 Pomodoro", callback_data="open_pomodoro_menu")],
        [InlineKeyboardButton("🎯 Metas Semanais", callback_data="open_metas_menu")],
        [InlineKeyboardButton("🗓️ Agenda", callback_data="open_agenda_menu")],
        # --- Botão para Rotinas Semanais ---
        [InlineKeyboardButton("📅 Rotinas Semanais", callback_data="open_rotinas_semanais_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Responde ao comando /start e exibe o menu principal do bot."""
    logger.info(f"Comando /start recebido do usuário {update.effective_user.id}")
    try:
        await update.message.reply_text(
            "Olá! Eu sou seu bot de produtividade. Escolha uma opção e vamos começar! ✨",
            reply_markup=get_main_menu_keyboard()
        )
        return MAIN_MENU_STATE
    except Exception as e:
        logger.error(f"Erro ao responder ao comando /start para o usuário {update.effective_user.id}: {e}", exc_info=True)
        # Em caso de erro aqui, como é o início, não há muito o que fazer além de logar.
        # O error_handler global pode pegar isso também.
        return ConversationHandler.END


async def open_pomodoro_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler para o botão 'Pomodoro' no menu principal.
    Responsável por inicializar a instância do Pomodoro para o usuário
    e passar o controle para o ConversationHandler do Pomodoro.
    """
    query = update.callback_query
    await query.answer("Abrindo Pomodoro... ⏳")
    logger.info(f"Usuário {query.from_user.id} abriu o menu Pomodoro.")
    try:
        if 'pomodoro_instance' not in context.user_data:
            context.user_data['pomodoro_instance'] = Pomodoro(bot=context.bot, chat_id=update.effective_chat.id)
        else:
            context.user_data['pomodoro_instance'].bot = context.bot
            context.user_data['pomodoro_instance'].chat_id = update.effective_chat.id
            
        pomodoro_instance = context.user_data['pomodoro_instance']
        return await pomodoro_instance._show_pomodoro_menu(update, context)
    except Exception as e:
        logger.error(f"Erro ao abrir o menu Pomodoro para o usuário {query.from_user.id}: {e}", exc_info=True)
        await query.edit_message_text(
            "Não foi possível abrir o Pomodoro no momento. Por favor, tente novamente ou volte ao menu principal.",
            reply_markup=get_main_menu_keyboard()
        )
        return MAIN_MENU_STATE # Tenta retornar ao menu principal em caso de falha


async def open_metas_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler para o botão 'Metas Semanais' no menu principal.
    Chama a função start_metas_menu do módulo metas.
    """
    query = update.callback_query
    await query.answer("Abrindo Metas Semanais... 🎯")
    logger.info(f"Usuário {query.from_user.id} abriu o menu Metas Semanais.")
    try:
        return await start_metas_menu(update, context)
    except Exception as e:
        logger.error(f"Erro ao abrir o menu Metas Semanais para o usuário {query.from_user.id}: {e}", exc_info=True)
        await query.edit_message_text(
            "Não foi possível abrir Metas Semanais no momento. Por favor, tente novamente ou volte ao menu principal.",
            reply_markup=get_main_menu_keyboard()
        )
        return MAIN_MENU_STATE


async def open_agenda_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler para o botão 'Agenda' no menu principal.
    Cria uma instância da classe Agenda e delega para seu handler de início.
    """
    query = update.callback_query
    await query.answer("Abrindo Agenda... 🗓️")
    logger.info(f"Usuário {query.from_user.id} abriu o menu Agenda.")
    try:
        if 'agenda_instance' not in context.user_data:
            context.user_data['agenda_instance'] = Agenda(bot=context.bot, chat_id=update.effective_chat.id)
        else:
            context.user_data['agenda_instance'].bot = context.bot
            context.user_data['agenda_instance'].chat_id = update.effective_chat.id

        agenda_instance = context.user_data['agenda_instance']
        return await agenda_instance.start_agenda_main_menu(update, context)
    except Exception as e:
        logger.error(f"Erro ao abrir o menu Agenda para o usuário {query.from_user.id}: {e}", exc_info=True)
        await query.edit_message_text(
            "Não foi possível abrir a Agenda no momento. Por favor, tente novamente ou volte ao menu principal.",
            reply_markup=get_main_menu_keyboard()
        )
        return MAIN_MENU_STATE

# --- Handler para abrir o menu de Rotinas Semanais ---
async def open_rotinas_semanais_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler para o botão 'Rotinas Semanais' no menu principal.
    Cria uma instância da classe RotinasSemanais e delega para seu handler de início.
    """
    query = update.callback_query
    await query.answer("Abrindo Rotinas Semanais... 📅")
    logger.info(f"Usuário {query.from_user.id} abriu o menu Rotinas Semanais.")
    try:
        if 'rotinas_semanais_instance' not in context.user_data:
            context.user_data['rotinas_semanais_instance'] = RotinasSemanais(bot=context.bot, chat_id=update.effective_chat.id)
        else:
            context.user_data['rotinas_semanais_instance'].bot = context.bot
            context.user_data['rotinas_semanais_instance'].chat_id = update.effective_chat.id

        rotinas_instance = context.user_data['rotinas_semanais_instance']
        return await rotinas_instance.start_rotinas_menu(update, context)
    except Exception as e:
        logger.error(f"Erro ao abrir o menu Rotinas Semanais para o usuário {query.from_user.id}: {e}", exc_info=True)
        await query.edit_message_text(
            "Não foi possível abrir Rotinas Semanais no momento. Por favor, tente novamente ou volte ao menu principal.",
            reply_markup=get_main_menu_keyboard()
        )
        return MAIN_MENU_STATE


async def return_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler para o callback 'main_menu_return'.
    Acionado quando o ConversationHandler do Pomodoro, Metas, Agenda ou Rotinas Semanaais
    retorna ConversationHandler.END.
    """
    query = update.callback_query
    logger.info(f"Usuário {query.from_user.id} retornou ao menu principal.")
    try:
        await query.edit_message_text(
            "De volta ao menu principal. Escolha uma opção: ✨",
            reply_markup=get_main_menu_keyboard()
        )
        return MAIN_MENU_STATE
    except Exception as e:
        logger.error(f"Erro ao retornar ao menu principal para o usuário {query.from_user.id}: {e}", exc_info=True)
        # Se falhar ao editar a mensagem, tenta enviar uma nova
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Ocorreu um problema ao voltar ao menu. Por favor, tente novamente ou use /start.",
            reply_markup=get_main_menu_keyboard()
        )
        return MAIN_MENU_STATE


async def fallback_global(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler de fallback global para mensagens ou callbacks inesperados
    em qualquer estado da conversa principal.
    """
    logger.warning(f"Fallback global acionado. Update: {update}")
    try:
        if update.message:
            await update.message.reply_text(
                "Desculpe, não entendi. Por favor, use os botões ou o comando /start. 🤔",
                reply_markup=get_main_menu_keyboard()
            )
        elif update.callback_query:
            query = update.callback_query
            await query.answer("Ação inválida. Por favor, use os botões! 🚫")
            await query.edit_message_text(
                "Ação inválida. Escolha uma opção: 🧐",
                reply_markup=get_main_menu_keyboard()
            )
        return MAIN_MENU_STATE
    except Exception as e:
        logger.error(f"Erro no fallback_global para o usuário {update.effective_user.id if update.effective_user else 'N/A'}: {e}", exc_info=True)
        if update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Ocorreu um erro inesperado. Por favor, tente novamente ou use /start."
            )
        return MAIN_MENU_STATE


async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler de erro global que captura QUALQUER exceção não tratada.
    É a sua blindagem 1000%.
    """
    # Registra o erro completo no log, incluindo o traceback
    logger.error(f"Exceção não tratada! Update {update} causou erro: {context.error}", exc_info=True)

    # Tenta informar o usuário de forma amigável
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Ops! Parece que um erro inesperado e grave aconteceu. Nossos desenvolvedores já foram notificados! Por favor, use o comando /start para tentar novamente. 🚨"
            )
        except Exception as e:
            # Se nem mesmo a mensagem de erro puder ser enviada, loga novamente
            logger.critical(f"ERRO CRÍTICO: Falha ao enviar mensagem de erro para o usuário {update.effective_chat.id}: {e}", exc_info=True)

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
    )

    application.add_handler(main_conversation_handler)

    # --- Handler para o botão "Concluída!" na notificação (fora do ConversationHandler principal) ---
    application.add_handler(CallbackQueryHandler(
        temp_rotinas_semanais_instance_for_handler_setup.concluir_tarefa_notificada,
        pattern=r"^rotinas_concluir_.*$"
    ))

    # --- ADICIONA O HANDLER DE ERRO GLOBAL (A SUA BLINDAGEM 1000%) ---
    application.add_error_handler(global_error_handler)

    logger.info("Bot rodando... ✨")
    application.run_polling(poll_interval=1.0)

if __name__ == "__main__":
    main()
