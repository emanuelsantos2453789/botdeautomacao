# bot_de_tel.py

import os
import logging
import datetime

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from handlers import (
    start,
    help_command,
    handle_text,
    handle_callback,
)
from jobs import (
    daily_feedback_job,
    weekly_report_job,
    weekly_backup_job,
)
from google_calendar import init_calendar_service

def main():
    # 1) Logging
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO
    )
    logger = logging.getLogger(__name__)

    # 2) Leitura de variáveis
    TOKEN = os.getenv("BOT_TOKEN")
    CALENDAR_ID = os.getenv("CALENDAR_ID")
    if not TOKEN:
        logger.error("BOT_TOKEN não configurado")
        return

    # 3) Inicializa Google Calendar
    calendar_service = init_calendar_service()
    
    # 4) Cria Application (substitui Updater)
    app = ApplicationBuilder().token(TOKEN).build()

    # 5) Armazena o serviço no bot_data pra handlers
    app.bot_data["calendar_service"] = calendar_service
    app.bot_data["calendar_id"]      = CALENDAR_ID

    # 6) Registra handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text(calendar_service, CALENDAR_ID)
        )
    )
    app.add_handler(CallbackQueryHandler(handle_callback))

    # 7) Agenda os jobs
    jq = app.job_queue
    jq.run_daily(
        daily_feedback_job,
        time=datetime.time(hour=20, minute=0),
        context=None
    )
    jq.run_daily(
        weekly_report_job,
        time=datetime.time(hour=18, minute=0),
        days=(6,),
        context=None
    )
    jq.run_daily(
        weekly_backup_job,
        time=datetime.time(hour=8, minute=0),
        context=None
    )

    # 8) Inicia polling
    app.run_polling()
    logger.info("Bot iniciado com ApplicationBuilder!")

if __name__ == "__main__":
    main()
