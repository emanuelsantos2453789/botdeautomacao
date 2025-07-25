import asyncio
import logging
import os
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ConversationHandler
from agenda import AgendaManager
from pomodoro import Pomodoro

# Configuração básica de logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Estados da conversa principal
MAIN_MENU, AGENDA_MENU, POMODORO_MENU = range(3)

# Carregar variáveis de ambiente
load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')

async def start(update, context):
    """Inicia a conversa e mostra o menu principal"""
    keyboard = [
        [InlineKeyboardButton("📅 Agenda", callback_data="open_agenda_menu")],
        [InlineKeyboardButton("🍅 Pomodoro", callback_data="open_pomodoro_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🌟 *Bem-vindo ao seu Assistente de Produtividade!* 🌟\n\n"
        "Como posso te ajudar hoje? Escolha uma opção: 👇",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
    return MAIN_MENU

async def main_menu(update, context):
    """Retorna ao menu principal"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("📅 Agenda", callback_data="open_agenda_menu")],
        [InlineKeyboardButton("🍅 Pomodoro", callback_data="open_pomodoro_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "🌟 *Menu Principal* 🌟\nEscolha uma opção:",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
    return MAIN_MENU

async def agenda_menu(update, context):
    """Menu da Agenda"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("🗓️ Rotinas Semanais", callback_data="open_rotinas_semanais_menu")],
        [InlineKeyboardButton("📝 Tarefas Avulsas", callback_data="open_tasks_menu")],
        [InlineKeyboardButton("⬅️ Voltar", callback_data="main_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "📅 *Menu da Agenda*: organize seu tempo e tarefas!",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
    return AGENDA_MENU

async def pomodoro_menu(update, context):
    """Menu do Pomodoro"""
    query = update.callback_query
    await query.answer()
    
    # Inicializa a instância do Pomodoro se não existir
    if 'pomodoro_instance' not in context.user_data:
        context.user_data['pomodoro_instance'] = Pomodoro()
    
    pomodoro_instance = context.user_data['pomodoro_instance']
    return await pomodoro_instance._show_pomodoro_menu(update, context)

async def end(update, context):
    """Encerra a conversa"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Até logo! 👋")
    return ConversationHandler.END

def main():
    # Criar a aplicação do Telegram
    application = Application.builder().token(TOKEN).build()
    
    # Inicializar os módulos
    agenda_manager = AgendaManager(application)
    pomodoro = Pomodoro()
    
    # Obter os handlers de conversa
    agenda_handler = agenda_manager.get_agenda_conversation_handler()
    pomodoro_handler = pomodoro.get_pomodoro_conversation_handler()
    
    # Configurar o ConversationHandler principal
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(agenda_menu, pattern='^open_agenda_menu$'),
                CallbackQueryHandler(pomodoro_menu, pattern='^open_pomodoro_menu$'),
                CallbackQueryHandler(end, pattern='^end$'),
            ],
            AGENDA_MENU: [
                agenda_handler,
                CallbackQueryHandler(main_menu, pattern='^main_menu$'),
            ],
            POMODORO_MENU: [
                pomodoro_handler,
                CallbackQueryHandler(main_menu, pattern='^main_menu$'),
            ],
        },
        fallbacks=[CallbackQueryHandler(end, pattern='^end$')],
    )
    
    application.add_handler(conv_handler)
    
    # Iniciar o scheduler para rotinas
    scheduler = AsyncIOScheduler()
    scheduler.start()
    
    logger.info("Bot iniciado. Pressione Ctrl+C para parar.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
