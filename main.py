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

# --- 1. Your Bot Token ---
TOKEN = "7677783341:AAFiCgEdkcaV_V03y_CZo2L2_F_NHGwlN54" 

# Dictionary to store a Pomodoro instance for each user
user_pomodoros = {}

# --- Global Conversation States (of the main bot) ---
MAIN_MENU_STATE = 0


# --- Helper Functions for the Main Bot ---

def get_main_menu_keyboard():
    """Returns the main bot menu keyboard."""
    keyboard = [
        [InlineKeyboardButton("🍅 Pomodoro", callback_data="open_pomodoro_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Responds to the /start command and displays the main bot menu."""
    await update.message.reply_text(
        "Olá! Eu sou seu bot de produtividade. Escolha uma opção e vamos começar! ✨",
        reply_markup=get_main_menu_keyboard()
    )
    return MAIN_MENU_STATE

async def open_pomodoro_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for the 'Pomodoro' button in the main menu.
    Responsible for initializing the Pomodoro instance for the user
    and passing control to the Pomodoro ConversationHandler.
    """
    query = update.callback_query
    await query.answer("Abrindo Pomodoro... ⏳")

    user_id = update.effective_user.id
    # Pass bot and chat_id when creating or accessing the user's Pomodoro instance
    if user_id not in user_pomodoros:
        user_pomodoros[user_id] = Pomodoro(bot=context.bot, chat_id=update.effective_chat.id)
    else:
        # If instance already exists, update bot and chat_id in case they changed
        user_pomodoros[user_id].bot = context.bot
        user_pomodoros[user_id].chat_id = update.effective_chat.id
    
    # Delegate to the Pomodoro instance's handler to display its menu
    return await user_pomodoros[user_id]._show_pomodoro_menu(update, context)


async def return_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for the 'main_menu_return' callback.
    Triggered when the Pomodoro ConversationHandler returns ConversationHandler.END.
    """
    query = update.callback_query
    await query.edit_message_text(
        "De volta ao menu principal. Escolha uma opção: ✨",
        reply_markup=get_main_menu_keyboard()
    )
    return MAIN_MENU_STATE


async def fallback_global(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Global fallback handler for unexpected messages or callbacks
    in any state of the main conversation.
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


# --- Main Function to Start the Bot ---

def main():
    """Configures and starts the bot."""
    application = Application.builder().token(TOKEN).build()

    # Create a dummy Pomodoro instance just to get the handler structure
    # The actual user-specific instances will be created/accessed in open_pomodoro_menu
    temp_pomodoro_instance = Pomodoro() 

    main_conversation_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={
            MAIN_MENU_STATE: [
                # The Pomodoro ConversationHandler is nested here
                # It will use the open_pomodoro_menu as its entry point
                temp_pomodoro_instance.get_pomodoro_conversation_handler(),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(return_to_main_menu, pattern="^main_menu_return$"),
            MessageHandler(filters.ALL & ~filters.COMMAND, fallback_global),
        ],
    )

    application.add_handler(main_conversation_handler)

    print("Bot rodando... Porraa")
    application.run_polling(poll_interval=1.0)

if __name__ == "__main__":
    main()
