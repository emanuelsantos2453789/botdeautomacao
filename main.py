# main.py
import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
    PicklePersistence
)

# Importar os módulos das funcionalidades
from agenda import AgendaManager, start_all_scheduled_jobs
from pomodoro import Pomodoro

# Configuração de logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Estados do menu principal
MAIN_MENU = 0

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Inicia o bot e mostra o menu principal."""
    keyboard = [
        [
            InlineKeyboardButton("🗓️ Rotinas Semanais", callback_data="open_rotinas_semanais_menu"),
            InlineKeyboardButton("🍅 Pomodoro", callback_data="open_pomodoro_menu")
        ],
        [
            InlineKeyboardButton("📝 Tarefas Avulsas", callback_data="open_tasks_menu"),
            InlineKeyboardButton("⚙️ Configurações", callback_data="open_settings_menu")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(
            "🌟 *Bem-vindo ao seu Assistente de Produtividade!* 🌟\n"
            "Escolha uma das opções abaixo para começar:",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    else:
        await update.callback_query.edit_message_text(
            "🌟 *Menu Principal* 🌟\nEscolha uma opção:",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    return MAIN_MENU

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mostra a mensagem de ajuda."""
    help_text = (
        "🛠️ *Ajuda do Assistente de Produtividade*\n\n"
        "Eu posso te ajudar a organizar sua rotina e melhorar sua produtividade! "
        "Aqui estão os principais comandos:\n\n"
        "• /start - Mostra o menu principal\n"
        "• /ajuda - Exibe esta mensagem de ajuda\n\n"
        "Principais funcionalidades:\n"
        "🍅 *Pomodoro* - Técnica de gestão de tempo com períodos de foco e descanso\n"
        "🗓️ *Rotinas Semanais* - Agenda suas atividades recorrentes\n"
        "📝 *Tarefas Avulsas* - Lembretes para atividades pontuais\n\n"
        "Experimente clicar nos botões do menu para começar!"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def main_menu_return(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Volta ao menu principal."""
    query = update.callback_query
    await query.answer()
    return await start(update, context)

async def post_init(application: Application) -> None:
    """Executa após a inicialização da aplicação."""
    await start_all_scheduled_jobs(application)
    logger.info("Agendamentos de rotinas iniciados")

def main() -> None:
    """Inicia o bot."""
    # Configurar token (use variável de ambiente para segurança)
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("Por favor, defina a variável de ambiente TELEGRAM_BOT_TOKEN")

    # Configurar persistência de dados
    persistence = PicklePersistence(filepath="bot_persistence")
    
    # Criar aplicação
    application = Application.builder().token(token).persistence(persistence).post_init(post_init).build()

    # Inicializar managers
    agenda_manager = AgendaManager(application)
    pomodoro_manager = Pomodoro()

    # Obter handlers
    agenda_handler = agenda_manager.get_agenda_conversation_handler()
    pomodoro_handler = pomodoro_manager.get_pomodoro_conversation_handler()

    # Configurar handlers principais
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ajuda", help_command))
    application.add_handler(CommandHandler("help", help_command))
    
    # Handler para retornar ao menu principal
    application.add_handler(CallbackQueryHandler(main_menu_return, pattern="^main_menu_return$"))
    
    # Adicionar handlers específicos
    application.add_handler(agenda_handler)
    application.add_handler(pomodoro_handler)

    # Iniciar o bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
