import os
import logging
from datetime import time, datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters, 
    CallbackQueryHandler, CallbackContext
)
from google_calendar import get_calendar_service, create_event
from data_manager import add_meta, record_event
from report_generator import generate_weekly_report, generate_daily_report
from utils import parse_date_from_text, format_datetime

# Configurações de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Carrega o token do bot do ambiente
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    logger.error("Não encontrou o BOT_TOKEN no ambiente.")
    exit(1)

def start(update: Update, context: CallbackContext):
    """Handler do comando /start."""
    user = update.effective_user.first_name
    update.message.reply_text(
        f"Olá, {user}! 👋 Eu sou seu assistente de agenda e metas. "
        "Me diga o que você quer fazer (ex: \"Vou correr amanhã às 7h\")."
    )

def handle_text(update: Update, context: CallbackContext):
    """Handler para mensagens de texto em linguagem natural."""
    text = update.message.text
    user_id = update.effective_chat.id

    # Usa dateparser para extrair data/hora (referência [5])
    dt = parse_date_from_text(text)
    context.user_data['last_text'] = text
    context.user_data['last_datetime'] = dt

    if dt:
        # Formata data para mensagem (ex: 15/07/2025 07:00)
        human_time = format_datetime(dt)
        message = (
            f"Entendi que você deseja: \"{text}\" 📅\n"
            f"Quer adicionar isso ao Google Agenda para {human_time}? 😃"
        )
        # Botões inline Sim/Não para confirmar adição na agenda
        buttons = [
            InlineKeyboardButton("Sim, adicionar", callback_data='cal_yes'),
            InlineKeyboardButton("Não", callback_data='cal_no')
        ]
        update.message.reply_text(message, reply_markup=InlineKeyboardMarkup([buttons]))
    else:
        # Sem data/horário detectado: propõe adicionar como meta
        message = (
            f"Parece que você quer: \"{text}\" 📝\n"
            "Deseja adicionar isso às suas metas? 🏆"
        )
        buttons = [
            InlineKeyboardButton("Sim, adicionar", callback_data='meta_yes'),
            InlineKeyboardButton("Não", callback_data='meta_no')
        ]
        update.message.reply_text(message, reply_markup=InlineKeyboardMarkup([buttons]))

def callback_handler(update: Update, context: CallbackContext):
    """Handler para callback queries dos botões inline."""
    query = update.callback_query
    query_data = query.data
    query.answer()

    # Recupera dados da última mensagem do usuário
    text = context.user_data.get('last_text')
    dt = context.user_data.get('last_datetime')
    chat_id = query.message.chat_id

    # 1. Confirmação para adicionar no calendário
    if query_data == 'cal_yes':
        # Chama função que cria evento no Google Calendar
        event = create_event(text, dt)
        # Registra localmente (opcional)
        record_event(event)
        query.edit_message_text(f"✅ Evento salvo no Google Agenda: *{text}* às {format_datetime(dt)}! 🎉",
                                 parse_mode='Markdown')
        # Pergunta sobre meta
        buttons = [
            InlineKeyboardButton("Sim, adicionar meta", callback_data='meta_yes'),
            InlineKeyboardButton("Não", callback_data='meta_no')
        ]
        query.message.reply_text("Também deseja adicionar isso às suas metas? 🤔",
                                 reply_markup=InlineKeyboardMarkup([buttons]))

    elif query_data == 'cal_no':
        query.edit_message_text("Entendido, não vou adicionar ao calendário. 😉")
        # Pergunta sobre meta
        buttons = [
            InlineKeyboardButton("Sim, adicionar meta", callback_data='meta_yes'),
            InlineKeyboardButton("Não", callback_data='meta_no')
        ]
        query.message.reply_text("Deseja adicionar às metas? 🏆",
                                 reply_markup=InlineKeyboardMarkup([buttons]))

    # 2. Confirmação para adicionar às metas
    elif query_data == 'meta_yes':
        add_meta(text, dt)
        query.edit_message_text("✅ Tudo certo! Metas atualizadas com sucesso. 🎯")
    elif query_data == 'meta_no':
        query.edit_message_text("OK, tudo bem! Sem alterações nas metas por enquanto. 😌")

def main():
    # Inicializa o bot e dispatcher
    updater = Updater(token=TOKEN)
    dp = updater.dispatcher

    # Handlers
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text))
    dp.add_handler(CallbackQueryHandler(callback_handler))

    # Job queues para relatórios automáticos (exemplos)
    # Relatório diário às 21:00
    updater.job_queue.run_daily(generate_daily_report, time=time(hour=21, minute=0))
    # Relatório semanal aos domingos às 09:00
    updater.job_queue.run_daily(generate_weekly_report, time=time(hour=9, minute=0), days=[6])

    # Inicia o bot
    logger.info("Bot iniciado. Aguardando mensagens...")
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
