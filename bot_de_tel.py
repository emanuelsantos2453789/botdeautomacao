# Seu bot_de_tel.py (ou o arquivo principal)
import os
import logging
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    JobQueue
)
import handlers
import jobs # Importe seu arquivo jobs.py

# Configuração de logs
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Token do seu bot do Telegram
TELEGRAM_BOT_TOKEN = os.getenv("BOT_TOKEN")

def main() -> None:
    # 1. Configurar o ApplicationBuilder com JobQueue
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # 2. Obter a instância do JobQueue
    job_queue: JobQueue = application.job_queue

    # 3. Agendar os jobs recorrentes (jobs.py)
    # Agendamento do resumo diário (semanal)
    # A função daily_feedback_job que você enviou é para um resumo diário, não semanal.
    # Vou renomeá-la para clarity, mas manterei o agendamento diário para as 20h, como você pediu.
    job_queue.run_daily(jobs.send_daily_summary_job, time=datetime.time(hour=20, minute=0, tzinfo=pytz.timezone('America/Sao_Paulo')), name="Daily Summary")
    
    # Agendamento do relatório semanal (domingo)
    # Usaremos WED para simular o domingo, pois WEEKLY é uma opção para um dia da semana específica na v20.
    # Ajustei para Sunday (0) e a hora do dia para a noite (20:00)
    job_queue.run_daily(jobs.weekly_report_job, time=datetime.time(hour=20, minute=0, tzinfo=pytz.timezone('America/Sao_Paulo')), days=(0,), name="Weekly Report")
    
    # Agendamento do backup semanal (domingo)
    job_queue.run_daily(jobs.weekly_backup_job, time=datetime.time(hour=23, minute=0, tzinfo=pytz.timezone('America/Sao_Paulo')), days=(0,), name="Weekly Backup")

    # Comandos
    application.add_handler(CommandHandler("start", handlers.rotina))
    application.add_handler(CommandHandler("rotina", handlers.rotina))
    application.add_handler(CommandHandler("rotina_semanal", handlers.handle_weekly_routine_input)) # Novo comando

    # Callback Queries (botões inline)
    application.add_handler(CallbackQueryHandler(handlers.rotina_callback, pattern=r"^menu_"))
    application.add_handler(CallbackQueryHandler(handlers.mark_done_callback, pattern=r"^(mark_done_|feedback_yes_|feedback_no_)"))
    application.add_handler(CallbackQueryHandler(handlers.delete_meta_callback, pattern=r"^delete_meta_")) # Novo handler para apagar metas

    # Mensagens de texto (geral)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_text))

    # Iniciar o bot
    logger.info("Bot iniciando polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
    logger.info("Bot finalizado.")

if __name__ == "__main__":
    import datetime
    import pytz # Importe pytz aqui para uso no main, se necessário para definir o timezone
    main()
