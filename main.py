# main.py
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
from handlers.agenda import Agenda # Importe a classe Agenda

# --- 1. Your Bot Token ---
TOKEN = "7677783341:AAFiCgEdkcaV_V03y_CZo2L2_F_NHGwlN54"

# --- Global Conversation States (of the main bot) ---
MAIN_MENU_STATE = 0


# --- Helper Functions for the Main Bot ---

def get_main_menu_keyboard():
    """Retorna o teclado do menu principal do bot."""
    keyboard = [
        [InlineKeyboardButton("🍅 Pomodoro", callback_data="open_pomodoro_menu")],
        [InlineKeyboardButton("🎯 Metas Semanais", callback_data="open_metas_menu")],
        [InlineKeyboardButton("🗓️ Agenda", callback_data="open_agenda_menu")], # Novo botão para Agenda
    ]
    return InlineKeyboardMarkup(keyboard)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Responde ao comando /start e exibe o menu principal do bot."""
    await update.message.reply_text(
        "Olá! Eu sou seu bot de produtividade. Escolha uma opção e vamos começar! ✨",
        reply_markup=get_main_menu_keyboard()
    )
    return MAIN_MENU_STATE

async def open_pomodoro_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler para o botão 'Pomodoro' no menu principal.
    Responsável por inicializar a instância do Pomodoro para o usuário
    e passar o controle para o ConversationHandler do Pomodoro.
    """
    query = update.callback_query
    await query.answer("Abrindo Pomodoro... ⏳")

    if 'pomodoro_instance' not in context.user_data:
        context.user_data['pomodoro_instance'] = Pomodoro(bot=context.bot, chat_id=update.effective_chat.id)
    else:
        context.user_data['pomodoro_instance'].bot = context.bot
        context.user_data['pomodoro_instance'].chat_id = update.effective_chat.id
    
    pomodoro_instance = context.user_data['pomodoro_instance']
    return await pomodoro_instance._show_pomodoro_menu(update, context)

# Novo: Handler para abrir o menu de Metas
async def open_metas_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler para o botão 'Metas Semanais' no menu principal.
    Delega para o handler da instância Metas para exibir seu menu.
    """
    query = update.callback_query
    await query.answer("Abrindo Metas Semanais... 🎯")
    
    # Cria uma instância da classe Metas (não precisa de bot/chat_id no init)
    metas_instance = Metas()
    # Chama o handler de entrada do ConversationHandler de Metas
    return await metas_instance.start_metas_menu(update, context)

# Novo: Handler para abrir o menu da Agenda
async def open_agenda_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler para o botão 'Agenda' no menu principal.
    Delega para o handler da instância Agenda para exibir seu menu.
    """
    query = update.callback_query
    await query.answer("Abrindo Agenda... 🗓️")
    
    # Cria uma instância da classe Agenda
    agenda_instance = Agenda(bot=context.bot, chat_id=update.effective_chat.id)
    # Chama o handler de entrada do ConversationHandler da Agenda
    return await agenda_instance.start_agenda_menu(update, context)


async def return_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler para o callback 'main_menu_return'.
    Acionado quando um ConversationHandler aninhado retorna ConversationHandler.END.
    """
    query = update.callback_query
    await query.edit_message_text(
        "De volta ao menu principal. Escolha uma opção: ✨",
        reply_markup=get_main_menu_keyboard()
    )
    return MAIN_MENU_STATE


async def fallback_global(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler de fallback global para mensagens ou callbacks inesperados
    em qualquer estado da conversa principal.
    """
    if update.message:
        await update.message.reply_text(
            "Desculpe, não entendi. Por favor, use os botões ou o comando /start. 🤔",
            reply_markup=get_main_menu_keyboard()
        )
    elif update.callback_query:
        await update.callback_query.answer("Ação inválida. Por favor, use os botões! 🚫")
        await update.callback_query.edit_message_text(
            "Ação inválida. Escolha uma opção: 🧐",
            reply_markup=get_main_menu_keyboard()
        )
    return MAIN_MENU_STATE


# --- Função Principal para Iniciar o Bot ---

def main():
    """Configura e inicia o bot."""
    application = Application.builder().token(TOKEN).build()

    # Cria instâncias dummy para configurar os ConversationHandlers aninhados.
    # Essas instâncias não serão usadas para o estado real da conversa,
    # que é gerenciado por instâncias criadas dentro dos handlers open_*.
    temp_pomodoro_instance_for_handler_setup = Pomodoro()
    temp_metas_instance_for_handler_setup = Metas()
    temp_agenda_instance_for_handler_setup = Agenda()

    main_conversation_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={
            MAIN_MENU_STATE: [
                temp_pomodoro_instance_for_handler_setup.get_pomodoro_conversation_handler(),
                temp_metas_instance_for_handler_setup.get_metas_conversation_handler(),
                temp_agenda_instance_for_handler_setup.get_agenda_conversation_handler(), # Novo: Handler da Agenda
            ],
        },
        fallbacks=[
            CallbackQueryHandler(return_to_main_menu, pattern="^main_menu_return$"),
            MessageHandler(filters.ALL & ~filters.COMMAND, fallback_global),
        ],
    )

    application.add_handler(main_conversation_handler)

    print("Bot rodando... ✨")
    application.run_polling(poll_interval=1.0)

if __name__ == "__main__":
    main()
