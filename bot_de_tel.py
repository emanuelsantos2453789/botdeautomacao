import os
import json
import logging
from io import BytesIO
from datetime import datetime, date, time, timedelta

from telegram import Update, InputMediaDocument
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

from google.oauth2 import service_account
from googleapiclient.discovery import build

# Configuração básica de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Carrega as credenciais do Google Calendar da variável de ambiente
GOOGLE_KEY_JSON = os.environ.get('GOOGLE_KEY_JSON')
CALENDAR_ID = os.environ.get('CALENDAR_ID', 'primary')
if not GOOGLE_KEY_JSON:
    logger.error("Variável de ambiente GOOGLE_KEY_JSON não definida")
    exit(1)
service_account_info = json.loads(GOOGLE_KEY_JSON)
credentials = service_account.Credentials.from_service_account_info(
    service_account_info,
    scopes=['https://www.googleapis.com/auth/calendar']
)
calendar_service = build('calendar', 'v3', credentials=credentials)

# Dicionários em memória para armazenar metas e suas pontuações
goals = {}  # ex: {'meta1': 10, 'meta2': 5}
# (Em produção, considere persistir em arquivo/banco; aqui usamos memoria simples.)

# Handler para /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = (
        "Olá! Eu sou seu bot de metas e rotina.\n"
        "Use /metas para definir suas metas semanais.\n"
        "Use /atualizar <meta> <valor> para atualizar o progresso.\n"
        "Use /progresso para ver o progresso atual.\n"
        "Use /rotina para agendar tarefas no Google Agenda.\n"
        "Use /feedback para receber um resumo das metas."
    )
    await context.bot.send_message(chat_id=chat_id, text=text)

# Handler para /metas: define metas da semana e zera progresso
async def metas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text  # ex: "/metas estudar, exercicio"
    # Remove o comando e separa por vírgula
    metas_text = text[len("/metas"):].strip()
    if not metas_text:
        await context.bot.send_message(chat_id, "Por favor, informe as metas separadas por vírgula.")
        return
    lista_metas = [m.strip() for m in metas_text.split(",") if m.strip()]
    global goals
    goals = {m: 0 for m in lista_metas}
    resposta = "Metas definidas para a semana:\n" + "\n".join(f"- {m}: 0" for m in lista_metas)
    await context.bot.send_message(chat_id, resposta)

# Handler para /atualizar <meta> <valor>
async def atualizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args
    if len(args) < 2:
        await context.bot.send_message(chat_id, "Use /atualizar <meta> <valor>.")
        return
    meta = args[0]
    try:
        valor = float(args[1])
    except ValueError:
        await context.bot.send_message(chat_id, "Valor inválido. Informe um número.")
        return
    if meta in goals:
        goals[meta] = valor
        await context.bot.send_message(chat_id, f"Meta '{meta}' atualizada para {valor}.")
    else:
        await context.bot.send_message(chat_id, f"Meta '{meta}' não encontrada.")

# Handler para /progresso: mostra progresso total e individual
async def progresso(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not goals:
        await context.bot.send_message(chat_id, "Nenhuma meta definida. Use /metas primeiro.")
        return
    total = sum(goals.values())
    lines = [f"{m}: {v}" for m, v in goals.items()]
    resposta = f"Progresso total: {total}\n" + "\n".join(lines)
    await context.bot.send_message(chat_id, resposta)

# Handler para /rotina: agendar tarefa no Google Calendar
async def rotina(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text  # ex: "/rotina segunda 10:00 estudar"
    partes = text.split(maxsplit=3)
    if len(partes) < 4:
        await context.bot.send_message(chat_id, "Use /rotina <dia_semana> <HH:MM> <descrição>.")
        return
    dia_sem, hora, desc = partes[1], partes[2], partes[3]
    # Mapeia dia da semana em português para número (segunda=0..domingo=6)
    dias = {'segunda': 0, 'terca': 1, 'terça': 1, 'quarta': 2, 'quinta': 3,
            'sexta': 4, 'sabado': 5, 'sábado': 5, 'domingo': 6}
    if dia_sem.lower() not in dias:
        await context.bot.send_message(chat_id, "Dia da semana inválido.")
        return
    weekday = dias[dia_sem.lower()]
    # Calcula a próxima data para o dia da semana informado
    today = date.today()
    days_ahead = (weekday - today.weekday() + 7) % 7
    if days_ahead == 0:
        days_ahead = 7  # próxima semana
    event_date = today + timedelta(days=days_ahead)
    try:
        hora_dt = datetime.strptime(hora, "%H:%M").time()
    except ValueError:
        await context.bot.send_message(chat_id, "Hora inválida. Use HH:MM (24h).")
        return
    start_dt = datetime.combine(event_date, hora_dt)
    end_dt = start_dt + timedelta(hours=1)
    event_body = {
        'summary': desc,
        'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'America/Sao_Paulo'},
        'end': {'dateTime': end_dt.isoformat(), 'timeZone': 'America/Sao_Paulo'},
    }
    try:
        calendar_service.events().insert(calendarId=CALENDAR_ID, body=event_body).execute()
        await context.bot.send_message(chat_id, f"Tarefa '{desc}' agendada para {dia_sem} às {hora}.")
    except Exception as e:
        logger.error(f"Erro ao criar evento: {e}")
        await context.bot.send_message(chat_id, "Erro ao agendar no Google Agenda.")

# Handler para /feedback: resumo do progresso
async def feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not goals:
        await context.bot.send_message(chat_id, "Nenhuma meta definida.")
        return
    total = sum(goals.values())
    maior_meta = max(goals, key=goals.get)
    resposta = f"Progresso total: {total}\nMeta mais avançada: {maior_meta} ({goals[maior_meta]})"
    await context.bot.send_message(chat_id, resposta)

# Funções de job (tarefas agendadas)
async def job_feedback_daily(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    if not goals:
        return
    total = sum(goals.values())
    resposta = f"[Diário] Progresso total: {total}"
    await context.bot.send_message(chat_id, resposta)

async def job_relatorio_semanal(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    if not goals:
        return
    # Gera relatório em PDF das metas
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, "Relatório Semanal de Metas", ln=1, align='C')
    for m, v in goals.items():
        pdf.cell(0, 10, f"{m}: {v}", ln=1)
    bio = BytesIO(pdf.output(dest='S').encode('latin-1'))
    bio.name = "relatorio_semanal.pdf"
    await context.bot.send_document(chat_id, document=bio)

async def job_backup_csv(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    if not goals:
        return
    # Gera backup em CSV das metas
    import csv
    bio = BytesIO()
    writer = csv.writer(bio)
    writer.writerow(["Meta", "Progresso"])
    for m, v in goals.items():
        writer.writerow([m, v])
    bio.seek(0)
    bio.name = "backup_metas.csv"
    await context.bot.send_document(chat_id, document=bio)

if __name__ == '__main__':
    # Cria aplicação do bot
    app = ApplicationBuilder().token(os.environ['BOT_TOKEN']).build()

    # Registra handlers de comando
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("metas", metas))
    app.add_handler(CommandHandler("atualizar", atualizar))
    app.add_handler(CommandHandler("progresso", progresso))
    app.add_handler(CommandHandler("rotina", rotina))
    app.add_handler(CommandHandler("feedback", feedback))

    # Agendamento de tarefas automáticas
    jq = app.job_queue
    # Feedback diário às 20:00 (usuário principal; need chat_id)
    # Assumimos que /start armazena o chat_id do usuário: por simplicidade, pegamos do primeiro /start
    # Na prática, teríamos que guardar chat_id em persistência; aqui usamos job_queue com chat_id fixo exemplo
    # Supondo apenas um usuário, usamos job_queue.run_daily com chat_id do último update visto (ex.: start)
    # Para efeito de exemplo:
    from datetime import time as dtime
    # Observação: para fuse local, ajustar timezone ou usar DefaultDefaults
    jq.run_daily(job_feedback_daily, time=dtime(hour=20, minute=0), days=(0,1,2,3,4,5,6), chat_id=update.effective_chat.id if 'update' in locals() else None)
    # Relatório semanal (domingo às 21:00 -> day=6)
    jq.run_daily(job_relatorio_semanal, time=dtime(hour=21, minute=0), days=(6,), chat_id=update.effective_chat.id if 'update' in locals() else None)
    # Backup CSV (sexta às 18:00 -> day=4)
    jq.run_daily(job_backup_csv, time=dtime(hour=18, minute=0), days=(4,), chat_id=update.effective_chat.id if 'update' in locals() else None)

    app.run_polling()