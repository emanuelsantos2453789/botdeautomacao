import os
import logging

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from google_calendar import init_calendar_service
from handlers import (
    rotina,
    rotina_callback,
    mark_done_callback,
    handle_text,
)


def main():
    # 1) Logging
    logging.basicConfig(
        format="%(asctime)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )
    logger = logging.getLogger(__name__)

    # 2) Variáveis de ambiente
    TOKEN = os.getenv("BOT_TOKEN")
    CALENDAR_ID = os.getenv("CALENDAR_ID")
    if not TOKEN:
        logger.error("BOT_TOKEN não configurado")
        return
    if not CALENDAR_ID: # Adicionado para verificar o CALENDAR_ID também
        logger.warning("CALENDAR_ID não configurado. Agendamento pode falhar.")


    # 3) Inicializa Google Calendar e Application
    try:
        calendar_service = init_calendar_service()
        logger.info("Google Calendar Service inicializado com sucesso.")
    except Exception as e:
        logger.error(f"Erro ao inicializar o serviço do Google Calendar: {e}")
        # Você pode decidir se quer parar o bot aqui ou continuar sem o calendar
        return # Para o bot se o calendar não puder ser inicializado

    app = ApplicationBuilder().token(TOKEN).build()

    # 4) Compartilha o serviço no bot_data
    app.bot_data["calendar_service"] = calendar_service
    app.bot_data["calendar_id"] = CALENDAR_ID
    logger.info(f"CALENDAR_ID configurado para: {CALENDAR_ID}")


    # 5) Registra handlers
    app.add_handler(CommandHandler("rotina", rotina))
    app.add_handler(CallbackQueryHandler(rotina_callback, pattern=r"^menu_"))
    app.add_handler(CallbackQueryHandler(mark_done_callback, pattern=r"^done_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    logger.info("Handlers registrados.")

    # 6) Inicia long polling
    logger.info("Bot rodando – use /rotina para começar")
    app.run_polling()


if __name__ == "__main__":
    main()
