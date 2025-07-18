import os
import logging
import datetime

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from handlers import (
    rotina,          # mostra o menu
    rotina_callback, # trata cliques no menu
    handle_text,     # trata texto após menu
)
from google_calendar import init_calendar_service

def main():
    logging.basicConfig(
        format="%(asctime)s - %(levelname)s - %(message)s",
        level=logging.INFO
    )
    logger = logging.getLogger(__name__)

    TOKEN       = os.getenv("BOT_TOKEN")
    CALENDAR_ID = os.getenv("CALENDAR_ID")
    if not TOKEN:
        logger.error("BOT_TOKEN não configurado")
        return

    # Inicializa Google Calendar e Application
    calendar_service = init_calendar_service()
    app = ApplicationBuilder().token(TOKEN).build()

    # compartilha no context
    app.bot_data["calendar_service"] = calendar_service
    app.bot_data["calendar_id"]      = CALENDAR_ID

    # registra menu e handlers
    app.add_handler(CommandHandler("rotina", rotina))
    app.add_handler(CallbackQueryHandler(rotina_callback, pattern=r"^menu_"))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )

    # inicia polling
    app.run_polling()
    logger.info("Bot rodando – use /rotina para começar")

if __name__ == "__main__":
    main()
