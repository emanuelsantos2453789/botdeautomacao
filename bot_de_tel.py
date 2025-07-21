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
    # AGORA APONTANDO PARA AS FUNÇÕES CORRETAS EM JOBS.PY
    
    # Agendamento do resumo noturno diário (tarefas do dia e para amanhã)
    job_queue.run_daily(jobs.send_daily_summary_job, # Aponta para jobs.py
                        time=datetime.time(hour=20, minute=0, tzinfo=SAO_PAULO_TZ), 
                        name="Daily Summary")
    
    # Agendamento do relatório semanal (domingo à noite)
    job_queue.run_daily(jobs.weekly_report_job, # Aponta para jobs.py
                        time=datetime.time(hour=20, minute=0, tzinfo=SAO_PAULO_TZ), 
                        days=(6,), # 6 = Domingo (Python's weekday: Monday is 0 and Sunday is 6)
                        name="Weekly Report")
    
    # Agendamento do backup semanal (domingo à noite)
    job_queue.run_daily(jobs.weekly_backup_job, # Aponta para jobs.py
                        time=datetime.time(hour=23, minute=0, tzinfo=SAO_PAULO_TZ), 
                        days=(6,), # 6 = Domingo
                        name="Weekly Backup")

    # Adicionar job para limpar tarefas expiradas/concluídas (uma vez ao dia, por exemplo)
    job_queue.run_daily(jobs.clean_up_old_tasks_job, # Aponta para jobs.py
                        time=datetime.time(hour=2, minute=0, tzinfo=SAO_PAULO_TZ),
                        name="Clean Up Old Tasks")


    # --- Comandos ---
    application.add_handler(CommandHandler("start", handlers.main_menu))
    application.add_handler(CommandHandler("menu", handlers.main_menu))
    application.add_handler(CommandHandler("tarefas", handlers.list_tasks))

    application.add_handler(CommandHandler("rotina_semanal", handlers.handle_weekly_routine_input))
    application.add_handler(CommandHandler("ver_rotina", handlers.view_weekly_routine))
    
    # Comandos para Pomodoro
    application.add_handler(CommandHandler("pomodoro", handlers.pomodoro_menu))
    application.add_handler(CommandHandler("pomodoro_status", handlers.pomodoro_status))
    application.add_handler(CommandHandler("pomodoro_stop", handlers.pomodoro_stop))

    # Comandos para Metas
    application.add_handler(CommandHandler("meta_semanal", handlers.set_weekly_goal_command))
    application.add_handler(CommandHandler("ver_metas", handlers.view_weekly_goals_command))

    # --- Callback Queries (botões inline) ---
    application.add_handler(CallbackQueryHandler(handlers.main_menu, pattern=r"^main_menu$"))
    application.add_handler(CallbackQueryHandler(handlers.list_tasks, pattern=r"^list_tasks_"))
    application.add_handler(CallbackQueryHandler(handlers.mark_goal_done_callback, pattern=r"^(mark_done_|feedback_yes_|feedback_no_|feedback_postpone_|feedback_delete_)"))
    application.add_handler(CallbackQueryHandler(handlers.delete_meta_callback, pattern=r"^delete_meta_")) 
    application.add_handler(CallbackQueryHandler(handlers.delete_task_callback, pattern=r"^delete_task_"))
    
    # Callbacks para Pomodoro
    application.add_handler(CallbackQueryHandler(handlers.pomodoro_callback, pattern=r"^pomodoro_"))
    application.add_handler(CallbackQueryHandler(handlers.pomodoro_set_time_callback, pattern=r"^set_pomodoro_"))
    application.add_handler(CallbackQueryHandler(handlers.pomodoro_menu, pattern=r"^menu_pomodoro$"))

    # Callbacks para Rotina Semanal
    application.add_handler(CallbackQueryHandler(handlers.edit_full_weekly_routine_callback, pattern=r"^edit_full_weekly_routine$"))
    application.add_handler(CallbackQueryHandler(handlers.delete_item_weekly_routine_callback, pattern=r"^delete_item_weekly_routine$"))
    application.add_handler(CallbackQueryHandler(handlers.delete_routine_task_confirm_callback, pattern=r"^delete_routine_task_confirm_"))
    application.add_handler(CallbackQueryHandler(handlers.view_weekly_routine_menu_callback, pattern=r"^view_weekly_routine_menu$"))

    # Callbacks para Metas Semanais
    application.add_handler(CallbackQueryHandler(handlers.set_weekly_goal_command_cb, pattern=r"^set_weekly_goal_command_cb$"))
    application.add_handler(CallbackQueryHandler(handlers.delete_weekly_goal_menu, pattern=r"^delete_weekly_goal_menu$"))
    application.add_handler(CallbackQueryHandler(handlers.delete_weekly_goal_confirm_callback, pattern=r"^delete_weekly_goal_confirm_"))
    application.add_handler(CallbackQueryHandler(handlers.view_weekly_goals_command, pattern=r"^view_weekly_goals_command$"))

    # Callbacks para Relatórios (se estas funções estiverem em handlers.py)
    application.add_handler(CallbackQueryHandler(handlers.show_reports_menu, pattern=r"^show_reports_menu$"))
    application.add_handler(CallbackQueryHandler(handlers.get_daily_feedback_callback, pattern=r"^get_daily_feedback$"))
    application.add_handler(CallbackQueryHandler(handlers.get_weekly_feedback_callback, pattern=r"^get_weekly_feedback$"))

    # Mensagens de texto (genérico) - DEVE SER O ÚLTIMO
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_text_input))

    # Iniciar o bot
    logger.info("Bot iniciando polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
    logger.info("Bot finalizado.")

if __name__ == "__main__":
    main()
