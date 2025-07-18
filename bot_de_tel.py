# Seu bot_de_tel.py (ou o arquivo principal)
import os
import logging
from telegram import Update # Importe Update aqui
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    JobQueue # Importe JobQueue
)
import handlers # Importe seu arquivo handlers.py

# Configuração de logs
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Token do seu bot do Telegram
TELEGRAM_BOT_TOKEN = os.getenv("BOT_TOKEN")

def main() -> None:
    # 1. Configurar o ApplicationBuilder com JobQueue
    # Passamos o job_queue aqui
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # 2. Obter a instância do JobQueue
    job_queue: JobQueue = application.job_queue # Pegar a instância do JobQueue

    # Comandos
    application.add_handler(CommandHandler("start", handlers.rotina))
    application.add_handler(CommandHandler("rotina", handlers.rotina))

    # Callback Queries (botões inline)
    application.add_handler(CallbackQueryHandler(handlers.rotina_callback, pattern=r"^menu_"))
    application.add_handler(CallbackQueryHandler(handlers.mark_done_callback, pattern=r"^mark_done_"))

    # Mensagens de texto (geral)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_text))

    # Iniciar o bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
