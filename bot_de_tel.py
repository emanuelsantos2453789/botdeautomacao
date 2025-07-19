import os
import logging
import datetime
import pytz
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

# Token do seu bot do Telegram (Lembre-se de configurar como variável de ambiente!)
TELEGRAM_BOT_TOKEN = os.getenv("BOT_TOKEN")

# Define o fuso horário padrão para o bot
SAO_PAULO_TZ = pytz.timezone('America/Sao_Paulo')

def main() -> None:
    # 1. Configurar o ApplicationBuilder com JobQueue
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # 2. Obter a instância do JobQueue
    job_queue: JobQueue = application.job_queue

    # 3. Agendar os jobs recorrentes (jobs.py)
    # Agendamento do resumo noturno diário (tarefas do dia e para amanhã)
    job_queue.run_daily(jobs.send_daily_summary_job, 
                        time=datetime.time(hour=20, minute=0, tzinfo=SAO_PAULO_TZ), 
                        name="Daily Summary")
    
    # Agendamento do relatório semanal (domingo à noite)
    job_queue.run_daily(jobs.weekly_report_job, 
                        time=datetime.time(hour=20, minute=0, tzinfo=SAO_PAULO_TZ), 
                        days=(0,), # 0 = Domingo
                        name="Weekly Report")
    
    # Agendamento do backup semanal (domingo à noite)
    job_queue.run_daily(jobs.weekly_backup_job, 
                        time=datetime.time(hour=23, minute=0, tzinfo=SAO_PAULO_TZ), 
                        days=(0,), # 0 = Domingo
                        name="Weekly Backup")

    # Adicionar job para limpar tarefas expiradas/concluídas (uma vez ao dia, por exemplo)
    job_queue.run_daily(jobs.clean_up_old_tasks_job,
                        time=datetime.time(hour=2, minute=0, tzinfo=SAO_PAULO_TZ),
                        name="Clean Up Old Tasks")


    # Comandos
    application.add_handler(CommandHandler("start", handlers.rotina))
    application.add_handler(CommandHandler("rotina", handlers.rotina))
    application.add_handler(CommandHandler("rotina_semanal", handlers.handle_weekly_routine_input)) # Novo comando

    # Comandos para Pomodoro
    application.add_handler(CommandHandler("pomodoro", handlers.pomodoro_menu))
    application.add_handler(CommandHandler("pomodoro_status", handlers.pomodoro_status))
    application.add_handler(CommandHandler("pomodoro_stop", handlers.pomodoro_stop))


    # Callback Queries (botões inline)
    application.add_handler(CallbackQueryHandler(handlers.rotina_callback, pattern=r"^menu_"))
    application.add_handler(CallbackQueryHandler(handlers.mark_done_callback, pattern=r"^(mark_done_|feedback_yes_|feedback_no_)"))
    application.add_handler(CallbackQueryHandler(handlers.delete_meta_callback, pattern=r"^delete_meta_"))
    application.add_handler(CallbackQueryHandler(handlers.delete_task_callback, pattern=r"^delete_task_")) # NOVO: Apagar Tarefas
    
    # Callbacks para Pomodoro
    application.add_handler(CallbackQueryHandler(handlers.pomodoro_callback, pattern=r"^pomodoro_"))
    application.add_handler(CallbackQueryHandler(handlers.pomodoro_set_time_callback, pattern=r"^set_pomodoro_"))


    # Mensagens de texto (geral)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_text))

    # Iniciar o bot
    logger.info("Bot iniciando polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
    logger.info("Bot finalizado.")

if __name__ == "__main__":
    main()
