import os
import csv
from datetime import datetime, timezone
from fpdf import FPDF
from google.oauth2 import service_account
from googleapiclient.discovery import build
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Carrega token do bot e outras configurações do ambiente
BOT_TOKEN = os.environ.get("BOT_TOKEN")
SERVICE_ACCOUNT_FILE = 'credentials.json'   # Nome do Secret File no Render
SCOPES = ['https://www.googleapis.com/auth/calendar']
CALENDAR_ID = 'primary'  # Calendário Google a usar (por exemplo)

# Inicializa cliente Google Calendar
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)
calendar_service = build('calendar', 'v3', credentials=credentials)

# --- Handlers Telegram ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Olá! Bot iniciado. Use /eventos para listar eventos do Google Calendar.")

async def listar_eventos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Lista próximos eventos do Google Calendar
    now = datetime.utcnow().isoformat() + 'Z'
    events_result = calendar_service.events().list(
        calendarId=CALENDAR_ID, timeMin=now, maxResults=5, singleEvents=True,
        orderBy='startTime'
    ).execute()
    events = events_result.get('items', [])
    if not events:
        await update.message.reply_text("Não há próximos eventos.")
        return
    texto = "Próximos eventos:\n"
    for event in events:
        start = event['start'].get('dateTime', event['start'].get('date'))
        summary = event.get('summary', 'Sem título')
        texto += f"- {start}: {summary}\n"
    await update.message.reply_text(texto)

async def gerar_relatorio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Gera relatório em PDF com os próximos eventos
    now = datetime.utcnow().isoformat() + 'Z'
    events = calendar_service.events().list(
        calendarId=CALENDAR_ID, timeMin=now, maxResults=10,
        singleEvents=True, orderBy='startTime'
    ).execute().get('items', [])
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font('Helvetica', size=12)
    pdf.cell(0, 10, txt="Relatório de Eventos", ln=1)
    if events:
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            summary = event.get('summary', 'Sem título')
            pdf.cell(0, 10, txt=f"{start}: {summary}", ln=1)
    else:
        pdf.cell(0, 10, txt="Nenhum evento encontrado.", ln=1)
    pdf_filename = "relatorio.pdf"
    pdf.output(pdf_filename)
    # Envia o PDF gerado
    await update.message.reply_document(document=open(pdf_filename, "rb"))

async def backup_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Gera backup em CSV dos próximos eventos
    now = datetime.utcnow().isoformat() + 'Z'
    events = calendar_service.events().list(
        calendarId=CALENDAR_ID, timeMin=now, maxResults=10,
        singleEvents=True, orderBy='startTime'
    ).execute().get('items', [])
    csv_filename = "backup.csv"
    with open(csv_filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Data', 'Resumo'])
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            summary = event.get('summary', 'Sem título')
            writer.writerow([start, summary])
    await update.message.reply_document(document=open(csv_filename, "rb"))

async def enviar_diario(context: ContextTypes.DEFAULT_TYPE):
    # Exemplo de tarefa agendada diária (envia mensagem para chat ADM)
    chat_id = int(os.environ.get("ADMIN_CHAT_ID", 0))
    if chat_id:
        await context.bot.send_message(chat_id, text="Lembrete diário automático.")

# --- Configuração do Bot e Agendamentos ---
if __name__ == '__main__':
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("eventos", listar_eventos))
    application.add_handler(CommandHandler("relatorio", gerar_relatorio))
    application.add_handler(CommandHandler("backup", backup_csv))
    # Agendamento diário (usa JobQueue interno do PTB)
    admin_chat_id = os.environ.get("ADMIN_CHAT_ID")
    if admin_chat_id:
        application.job_queue.run_repeating(
            enviar_diario, interval=86400, first=10, chat_id=int(admin_chat_id)
        )
    application.run_polling()