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

# --- NOVO: Importa a classe RotinasSemanais, e AGORA TAMBÉM o scheduler e a função de startup ---
from handlers.rotina_pr import RotinasSemanais, scheduler, start_all_scheduled_jobs

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
        [InlineKeyboardButton("🗓️ Agenda", callback_data="open_agenda_menu")],
        # --- Botão para Rotinas Semanais ---
        [InlineKeyboardButton("📅 Rotinas Semanais", callback_data="open_rotinas_semanais_menu")], 
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


async def open_metas_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler para o botão 'Metas Semanais' no menu principal.
    Chama a função start_metas_menu do módulo metas.
    """
    query = update.callback_query
    await query.answer("Abrindo Metas Semanais... 🎯")
    return await start_metas_menu(update, context)


async def open_agenda_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler para o botão 'Agenda' no menu principal.
    Cria uma instância da classe Agenda e delega para seu handler de início.
    """
    query = update.callback_query
    await query.answer("Abrindo Agenda... 🗓️")
    
    if 'agenda_instance' not in context.user_data:
        context.user_data['agenda_instance'] = Agenda(bot=context.bot, chat_id=update.effective_chat.id)
    else:
        context.user_data['agenda_instance'].bot = context.bot
        context.user_data['agenda_instance'].chat_id = update.effective_chat.id

    agenda_instance = context.user_data['agenda_instance']
    return await agenda_instance.start_agenda_menu(update, context)

# --- Handler para abrir o menu de Rotinas Semanais ---
async def open_rotinas_semanais_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler para o botão 'Rotinas Semanais' no menu principal.
    Cria uma instância da classe RotinasSemanais e delega para seu handler de início.
    """
    query = update.callback_query
    await query.answer("Abrindo Rotinas Semanais... 📅")
    
    if 'rotinas_semanais_instance' not in context.user_data:
        context.user_data['rotinas_semanais_instance'] = RotinasSemanais(bot=context.bot, chat_id=update.effective_chat.id)
    else:
        context.user_data['rotinas_semanais_instance'].bot = context.bot
        context.user_data['rotinas_semanais_instance'].chat_id = update.effective_chat.id

    rotinas_instance = context.user_data['rotinas_semanais_instance']
    return await rotinas_instance.start_rotinas_menu(update, context)


async def return_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler para o callback 'main_menu_return'.
    Acionado quando o ConversationHandler do Pomodoro, Metas, Agenda ou Rotinas Semanais
    retorna ConversationHandler.END.
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

    temp_pomodoro_instance_for_handler_setup = Pomodoro() # Instância dummy para handler Pomodoro
    temp_agenda_instance_for_handler_setup = Agenda() # Instância dummy para handler Agenda
    # --- Instância dummy para handler de Rotinas Semanais ---
    temp_rotinas_semanais_instance_for_handler_setup = RotinasSemanais() 

    main_conversation_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={
            MAIN_MENU_STATE: [
                CallbackQueryHandler(open_pomodoro_menu, pattern="^open_pomodoro_menu$"),
                CallbackQueryHandler(open_metas_menu, pattern="^open_metas_menu$"),
                CallbackQueryHandler(open_agenda_menu, pattern="^open_agenda_menu$"),
                # --- Adiciona o CallbackQueryHandler para Rotinas Semanais ---
                CallbackQueryHandler(open_rotinas_semanais_menu, pattern="^open_rotinas_semanais_menu$"),

                # Aninha os ConversationHandlers de cada funcionalidade
                temp_pomodoro_instance_for_handler_setup.get_pomodoro_conversation_handler(),
                get_metas_conversation_handler(), 
                temp_agenda_instance_for_handler_setup.get_agenda_conversation_handler(),
                # --- Aninha o ConversationHandler de Rotinas Semanais ---
                temp_rotinas_semanais_instance_for_handler_setup.get_rotinas_semanais_conversation_handler(),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(return_to_main_menu, pattern="^main_menu_return$"),
            MessageHandler(filters.ALL & ~filters.COMMAND, fallback_global),
        ],
    )

    application.add_handler(main_conversation_handler)

    # --- NOVO: Handler para o botão "Concluída!" na notificação ---
    # Este handler precisa estar no nível da Application, pois as notificações podem vir a qualquer momento
    application.add_handler(CallbackQueryHandler(
        temp_rotinas_semanais_instance_for_handler_setup.concluir_tarefa_notificada, 
        pattern=r"^rotinas_concluir_.*$"
    ))

    print("Bot rodando... ✨")
    # --- NOVO: Use on_startup para agendar jobs ao iniciar o bot ---
    # `on_startup` recebe o objeto `Application` como argumento.
    application.run_polling(poll_interval=1.0, on_startup=start_all_scheduled_jobs)

if __name__ == "__main__":
    main()
