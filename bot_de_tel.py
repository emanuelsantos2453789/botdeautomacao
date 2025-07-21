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
import handlers  # Importa seu arquivo handlers.py
import jobs      # Importa seu arquivo jobs.py

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
    """Função principal que inicializa e executa o bot."""
    try:
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

        # --- Handlers de Comandos ---
        # Certifique-se de que todas as funções de handlers estejam prefixadas com 'handlers.'
        application.add_handler(CommandHandler("start", handlers.main_menu))
        application.add_handler(CommandHandler("add_task", handlers.add_task_command))
        application.add_handler(CommandHandler("tasks", handlers.show_tasks_command))
        application.add_handler(CommandHandler("pomodoro", handlers.pomodoro_menu))
        application.add_handler(CommandHandler("routine", handlers.show_weekly_routine_command))
        application.add_handler(CommandHandler("goals", handlers.view_weekly_goals_command))
        application.add_handler(CommandHandler("set_goal", handlers.set_weekly_goal_command))
        application.add_handler(CommandHandler("set_routine", handlers.handle_weekly_routine_input))

        # --- Handlers de Callbacks de Botões Inline ---
        # Certifique-se de que todas as funções de handlers estejam prefixadas com 'handlers.'
        application.add_handler(CallbackQueryHandler(handlers.main_menu, pattern="^main_menu$"))
        application.add_handler(CallbackQueryHandler(handlers.list_tasks, pattern="^list_tasks_"))
        application.add_handler(CallbackQueryHandler(handlers.select_task_to_mark_done, pattern="^select_task_to_mark_done$"))
        application.add_handler(CallbackQueryHandler(handlers.mark_task_done_callback, pattern="^mark_done_id_"))
        application.add_handler(CallbackQueryHandler(handlers.select_task_to_delete, pattern="^select_task_to_delete$"))
        application.add_handler(CallbackQueryHandler(handlers.feedback_yes_id_callback, pattern="^feedback_yes_id_"))
        application.add_handler(CallbackQueryHandler(handlers.feedback_no_id_callback, pattern="^feedback_no_id_"))
        application.add_handler(CallbackQueryHandler(handlers.feedback_postpone_id_callback, pattern="^feedback_postpone_id_"))
        application.add_handler(CallbackQueryHandler(handlers.feedback_delete_id_callback, pattern="^feedback_delete_id_"))
        application.add_handler(CallbackQueryHandler(handlers.add_new_task_menu, pattern="^add_new_task_menu$"))
        application.add_handler(CallbackQueryHandler(handlers.add_task_no_datetime, pattern="^add_task_no_datetime$"))
        application.add_handler(CallbackQueryHandler(handlers.add_task_no_duration, pattern="^add_task_no_duration$"))

        # Handlers para Pomodoro
        application.add_handler(CallbackQueryHandler(handlers.pomodoro_menu, pattern="^menu_pomodoro$"))
        application.add_handler(CallbackQueryHandler(handlers.pomodoro_callback, pattern="^pomodoro_start$"))
        application.add_handler(CallbackQueryHandler(handlers.pomodoro_callback, pattern="^pomodoro_pause$"))
        application.add_handler(CallbackQueryHandler(handlers.pomodoro_callback, pattern="^pomodoro_resume$"))
        application.add_handler(CallbackQueryHandler(handlers.pomodoro_stop, pattern="^pomodoro_stop_command$")) 
        application.add_handler(CallbackQueryHandler(handlers.pomodoro_callback, pattern="^pomodoro_config_times$"))
        application.add_handler(CallbackQueryHandler(handlers.pomodoro_status, pattern="^pomodoro_status_command$")) 
        application.add_handler(CallbackQueryHandler(handlers.pomodoro_set_time_callback, pattern="^set_pomodoro_"))

        # Handlers para Rotina Semanal
        application.add_handler(CallbackQueryHandler(handlers.show_weekly_routine_command, pattern="^show_weekly_routine_command$"))
        application.add_handler(CallbackQueryHandler(handlers.edit_full_weekly_routine_callback, pattern="^edit_full_weekly_routine$"))
        application.add_handler(CallbackQueryHandler(handlers.delete_item_weekly_routine_callback, pattern="^delete_item_weekly_routine$"))
        application.add_handler(CallbackQueryHandler(handlers.delete_routine_task_confirm_callback, pattern="^delete_routine_task_by_id_"))
        application.add_handler(CallbackQueryHandler(handlers.view_weekly_routine_menu_callback, pattern="^view_weekly_routine_menu$"))

        # Handlers para Metas Semanais
        application.add_handler(CallbackQueryHandler(handlers.view_weekly_goals_command, pattern="^view_weekly_goals_command$"))
        application.add_handler(CallbackQueryHandler(handlers.set_weekly_goal_command_cb, pattern="^set_weekly_goal_command_cb$"))
        application.add_handler(CallbackQueryHandler(handlers.select_goal_to_mark_done, pattern="^select_goal_to_mark_done$"))
        application.add_handler(CallbackQueryHandler(handlers.mark_goal_done_callback, pattern="^mark_goal_done_id_"))
        application.add_handler(CallbackQueryHandler(handlers.delete_weekly_goal_menu, pattern="^delete_weekly_goal_menu$"))
        application.add_handler(CallbackQueryHandler(handlers.delete_weekly_goal_confirm_callback, pattern="^delete_weekly_goal_confirm_id_"))

        # Handlers para Relatórios
        application.add_handler(CallbackQueryHandler(handlers.show_reports_menu, pattern="^show_reports_menu$"))
        application.add_handler(CallbackQueryHandler(handlers.get_daily_feedback_callback, pattern="^get_daily_feedback$"))
        application.add_handler(CallbackQueryHandler(handlers.get_weekly_feedback_callback, pattern="^get_weekly_feedback$"))

        # --- Handler de Mensagens de Texto (para inputs de estados) ---
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_message))

        # REGISTRAR O MANIPULADOR DE ERROS GLOBAL AQUI
        application.add_error_handler(handlers.error_handler)
        logger.info("Manipulador de erros global registrado.")

        # Inicia o bot
        logger.info("Bot iniciado com sucesso! Escutando por atualizações...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

    except Exception as e:
        logger.error(f"Ocorreu um erro fatal na inicialização do bot: {e}", exc_info=True)
        # Você pode adicionar aqui uma notificação para você mesmo, se o bot travar
        # Por exemplo, enviar uma mensagem de erro para um chat específico.

if __name__ == "__main__":
    main()
