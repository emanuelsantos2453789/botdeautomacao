import os
import json
import csv
import logging
import threading
import time
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from fpdf import FPDF
from google.oauth2 import service_account
from googleapiclient.discovery import build

# CONFIGURAÇÕES GERAIS
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.getenv("BOT_TOKEN") or "7648555006:AAExdMVbKsCFYc4Hsp4JNXTqlD8Q2KSlhpk"
ARQ_METAS = "metas.json"
ARQ_EVENTOS = "eventos.json"
chat_ids = []

# GOOGLE API
SCOPES = ["https://www.googleapis.com/auth/calendar"]
SERVICE_ACCOUNT_FILE = "credentials.json"

credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)
service = build("calendar", "v3", credentials=credentials)
CALENDAR_ID = "primary"

# FUNÇÕES DE METAS
def carregar_metas():
    if os.path.exists(ARQ_METAS):
        with open(ARQ_METAS, "r") as f:
            return json.load(f)
    return {}

def salvar_metas(metas):
    with open(ARQ_METAS, "w") as f:
        json.dump(metas, f, indent=4)

async def metas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.replace("/metas", "").strip()
    linhas = texto.split("\n")
    metas_dict = {linha.strip(): 0 for linha in linhas if linha.strip()}
    salvar_metas(metas_dict)
    await update.message.reply_text("Metas salvas com sucesso!")

async def progresso(update: Update, context: ContextTypes.DEFAULT_TYPE):
    metas = carregar_metas()
    if not metas:
        await update.message.reply_text("Nenhuma meta encontrada.")
        return
    total = sum(metas.values())
    maximo = len(metas) * 100
    porcentagem = int((total / maximo) * 100) if maximo > 0 else 0
    resposta = [f"{meta} - {valor}%" for meta, valor in metas.items()]
    resposta.append(f"\nProgresso total: {porcentagem}%")
    await update.message.reply_text("\n".join(resposta))

async def atualizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        partes = update.message.text.replace("/atualizar", "").strip().split(" ", 1)
        meta, valor = partes[0], int(partes[1])
        metas = carregar_metas()
        if meta in metas:
            metas[meta] = min(valor, 100)
            salvar_metas(metas)
            await update.message.reply_text(f"Meta '{meta}' atualizada para {valor}%")
        else:
            await update.message.reply_text("Meta não encontrada.")
    except:
        await update.message.reply_text("Formato inválido. Use: /atualizar <nome_da_meta> <valor>")

# FUNÇÕES DE ROTINA E GOOGLE AGENDA
async def rotina(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.replace("/rotina", "").strip()
    linhas = texto.split("\n")
    eventos = []
    hoje = datetime.now()
    dias_semana = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]

    for linha in linhas:
        for i, dia in enumerate(dias_semana):
            if linha.lower().startswith(dia):
                hora_texto = linha[len(dia):].strip().split(" ", 1)[0]
                tarefa = linha[len(dia) + len(hora_texto):].strip()
                data = hoje + timedelta(days=(i - hoje.weekday()) % 7)
                data_str = data.strftime("%Y-%m-%d")
                eventos.append({"data": data_str, "hora": hora_texto, "tarefa": tarefa})

                # Google Agenda
                hora_dt = datetime.strptime(hora_texto, "%H:%M")
                inicio = datetime.combine(data.date(), hora_dt.time())
                fim = inicio + timedelta(hours=1)
                evento = {
                    'summary': tarefa,
                    'start': {'dateTime': inicio.isoformat(), 'timeZone': 'America/Sao_Paulo'},
                    'end': {'dateTime': fim.isoformat(), 'timeZone': 'America/Sao_Paulo'}
                }
                try:
                    service.events().insert(calendarId=CALENDAR_ID, body=evento).execute()
                except Exception as e:
                    logging.warning(f"Erro ao salvar no Google Agenda: {e}")

    with open(ARQ_EVENTOS, "w") as f:
        json.dump(eventos, f, indent=4)

    await update.message.reply_text("Eventos salvos com sucesso!")

# FEEDBACK AUTOMÁTICO
async def feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    metas = carregar_metas()
    if not metas:
        await update.message.reply_text("Sem metas para avaliar.")
        return
    progresso_total = sum(metas.values()) / (len(metas) * 100) * 100
    meta_mais_proxima = max(metas.items(), key=lambda x: x[1])[0]
    msg = f"Resumo do dia:\n🎯 Progresso semanal: {int(progresso_total)}%\n📌 Meta mais próxima: {meta_mais_proxima}"
    await update.message.reply_text(msg)

# RELATÓRIO EM PDF
def gerar_pdf():
    metas = carregar_metas()
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt="Relatório Semanal de Metas", ln=True, align="C")
    pdf.ln()
    for meta, valor in metas.items():
        pdf.cell(200, 10, txt=f"{meta}: {valor}%", ln=True)
    pdf.output("relatorio_semanal.pdf")

# BACKUP EM CSV
def gerar_backup():
    metas = carregar_metas()
    with open("backup.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Meta", "Progresso"])
        for meta, valor in metas.items():
            writer.writerow([meta, valor])

# START
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat.id
    if chat_id not in chat_ids:
        chat_ids.append(chat_id)
    await update.message.reply_text("Olá! Envie /metas, /progresso, /atualizar, /rotina ou /feedback.")

# AGENDADOR DE TAREFAS
def agendador(app):
    while True:
        agora = datetime.now()

        # Feedback diário às 20:00
        if agora.strftime("%H:%M") == "20:00":
            for chat_id in chat_ids:
                metas = carregar_metas()
                if metas:
                    progresso_total = sum(metas.values()) / (len(metas) * 100) * 100
                    meta_mais_proxima = max(metas.items(), key=lambda x: x[1])[0]
                    msg = f"Resumo do dia:\n🎯 Progresso semanal: {int(progresso_total)}%\n📌 Meta mais próxima: {meta_mais_proxima}"
                    app.bot.send_message(chat_id=chat_id, text=msg)
            time.sleep(60)

        # Enviar PDF aos domingos às 21:00
        elif agora.strftime("%A") == "Sunday" and agora.strftime("%H:%M") == "21:00":
            gerar_pdf()
            for chat_id in chat_ids:
                app.bot.send_document(chat_id=chat_id, document=open("relatorio_semanal.pdf", "rb"))
            time.sleep(60)

        # Backup às sextas às 18:00
        elif agora.strftime("%A") == "Friday" and agora.strftime("%H:%M") == "18:00":
            gerar_backup()
            time.sleep(60)

        else:
            time.sleep(30)

# FUNÇÃO PRINCIPAL
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("metas", metas))
    app.add_handler(CommandHandler("progresso", progresso))
    app.add_handler(CommandHandler("atualizar", atualizar))
    app.add_handler(CommandHandler("rotina", rotina))
    app.add_handler(CommandHandler("feedback", feedback))

    threading.Thread(target=agendador, args=(app,), daemon=True).start()

    app.run_polling()

if __name__ == "__main__":
    main()
