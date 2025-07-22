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
from metas import get_metas_conversation_handler, start_metas_menu # Importe as funções e o handler de metas

# --- NOVO: Importa a classe Agenda do módulo 'handlers/agenda.py' ---
from handlers.agenda import Agenda

# --- 1. Your Bot Token ---
TOKEN = "7677783341:AAFiCgEdkcaV_V03y_CZo2L2_F_NHGwlN54" 

# --- Global Conversation States (of the main bot) ---
MAIN_MENU_STATE = 0


# --- Helper Functions for the Main Bot ---

def get_main_menu_keyboard():
    """Retorna o teclado do menu principal do bot."""
    keyboard = [
        [InlineKeyboardButton("🍅 Pomodoro", callback_data="open_pomodoro_menu")],
        [InlineKeyboardButton("🎯 Metas Semanaais", callback_data="open_metas_menu")], # Novo botão para Metas
        # --- NOVO: Adiciona o botão da Agenda ao menu principal ---
        [InlineKeyboardButton("🗓️ Agenda", callback_data="open_agenda_menu")], 
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

    # Obtém a instância do Pomodoro para este usuário, ou cria uma nova se não existir
    # A instância Pomodoro agora é armazenada diretamente em context.user_data
    if 'pomodoro_instance' not in context.user_data:
        # Passa o bot e o chat_id no momento da criação da instância
        context.user_data['pomodoro_instance'] = Pomodoro(bot=context.bot, chat_id=update.effective_chat.id)
    else:
        # Se a instância já existe, atualiza bot e chat_id caso tenham mudado
        context.user_data['pomodoro_instance'].bot = context.bot
        context.user_data['pomodoro_instance'].chat_id = update.effective_chat.id
    
    # Delega para o handler da instância Pomodoro para exibir seu menu
    pomodoro_instance = context.user_data['pomodoro_instance']
    return await pomodoro_instance._show_pomodoro_menu(update, context)


async def open_metas_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler para o botão 'Metas Semanais' no menu principal.
    Chama a função start_metas_menu do módulo metas.
    """
    query = update.callback_query
    await query.answer("Abrindo Metas Semanais... 🎯")
    return await start_metas_menu(update, context) # Mantido como estava no seu código original


# --- NOVO: Handler para abrir o menu da Agenda ---
async def open_agenda_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler para o botão 'Agenda' no menu principal.
    Cria uma instância da classe Agenda e delega para seu handler de início.
    """
    query = update.callback_query
    await query.answer("Abrindo Agenda... 🗓️")
    
    # Cria uma instância da classe Agenda, passando o bot e chat_id para notificações
    agenda_instance = Agenda(bot=context.bot, chat_id=update.effective_chat.id)
    # Chama o handler de entrada do ConversationHandler da Agenda
    return await agenda_instance.start_agenda_menu(update, context)


async def return_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler para o callback 'main_menu_return'.
    Acionado quando o ConversationHandler do Pomodoro, Metas ou Agenda retorna ConversationHandler.END.
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

    # Cria uma instância dummy da classe Pomodoro apenas para obter a estrutura do handler.
    temp_pomodoro_instance_for_handler_setup = Pomodoro() 

    # --- NOVO: Cria uma instância dummy da classe Agenda ---
    temp_agenda_instance_for_handler_setup = Agenda()

    main_conversation_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={
            MAIN_MENU_STATE: [
                # O ConversationHandler do Pomodoro é aninhado aqui
                temp_pomodoro_instance_for_handler_setup.get_pomodoro_conversation_handler(),
                # Novo: O ConversationHandler das Metas é aninhado aqui
                get_metas_conversation_handler(), # Chama a função que retorna o ConversationHandler de metas
                # --- NOVO: O ConversationHandler da Agenda é aninhado aqui ---
                temp_agenda_instance_for_handler_setup.get_agenda_conversation_handler(),
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
