import os
import logging
import datetime

from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
)

# Módulos a criar
from handlers import (
    start,
    help_command,
    handle_text,
    handle_callback,          # para botões interativos
)
from jobs import (
    daily_feedback_job,
    weekly_report_job,
    weekly_backup_job,
)
from google_calendar import init_calendar_service

def main():
    # 1. Configurações iniciais
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO
    )
    logger = logging.getLogger(__name__)

    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        logger.error("Variável BOT_TOKEN não configurada.")
        return

    # 2. Inicializa Google Calendar
    calendar_service = init_calendar_service()
    CALENDAR_ID = os.getenv("CALENDAR_ID")
    if not CALENDAR_ID:
        logger.warning("CALENDAR_ID não encontrado; agendamento ficará desativado.")

    # 3. Inicializa o bot e registra handlers
    updater = Updater(token=TOKEN, use_context=True)
    dp = updater.dispatcher
    
    dp.bot_data['calendar_service'] = calendar_service
    dp.bot_data['calendar_id']      = CALENDAR_ID


    # Comandos básicos
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_command))

    # Todas as mensagens de texto passarem por NLP
    dp.add_handler(
        MessageHandler(
            Filters.text & ~Filters.command,
            handle_text(calendar_service, CALENDAR_ID)
        )
    )

    # CallbackQueries (botões “Sim/Não”, metas, etc.)
    dp.add_handler(CallbackQueryHandler(handle_callback))

    # 4. Agendamento de jobs
    jq = updater.job_queue

    # Feedback diário todo dia às 20:00
    jq.run_daily(
        daily_feedback_job,
        time=datetime.time(hour=20, minute=0),
        context={"calendar": calendar_service, "calendar_id": CALENDAR_ID}
    )

    # Relatório semanal no domingo às 18:00
    jq.run_daily(
        weekly_report_job,
        time=datetime.time(hour=18, minute=0),
        days=(6,),  # domingo = 6
        context={"calendar": calendar_service, "calendar_id": CALENDAR_ID}
    )

    # Backup automático toda segunda às 08:00
    jq.run_daily(
        weekly_backup_job,
        time=datetime.time(hour=8, minute=0),
        context=None
    )

    # 5. Inicia polling
    updater.start_polling()
    logger.info("Bot de rotina iniciado com sucesso!")
    updater.idle()


if __name__ == "__main__":
    main()
