import os
import json
import csv
import logging
import threading
import time
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
from fpdf import FPDF
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ————————————— CONFIGURAÇÕES GERAIS —————————————
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

TOKEN = os.getenv("BOT_TOKEN")  # deve estar definido como variável de ambiente
ARQ_METAS = "metas.json"
ARQ_EVENTOS = "eventos.json"
chat_ids = []

# ————————————— GOOGLE CALENDAR API —————————————
SCOPES = ["https://www.googleapis.com/auth/calendar"]
SERVICE_ACCOUNT_FILE = "credentials.json"  # coloque esse arquivo no mesmo diretório

credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
service = build("calendar", "v3", credentials=credentials)
CALENDAR_ID = "primary"

# ————————————— FUNÇÕES DE METAS —————————————
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
    await update.message.reply_text("✅ Metas salvas com sucesso!")

async def progresso(update: Update, context: ContextTypes.DEFAULT_TYPE):
    metas = carregar_metas()
    if not metas:
        return await update.message.reply_text("⚠️ Nenhuma meta encontrada.")
    total = sum(metas.values())
    maximo = len(metas) * 100
    pct = int((total / maximo) * 100) if maximo else 0
    linhas = [f"{m} – {v}%" for m, v in metas.items()]
    linhas.append(f"\n📊 Progresso total: {pct}%")
    await update.message.reply_text("\n".join(linhas))

async def atualizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        _, resto = update.message.text.split(" ", 1)
        nome, valor = resto.split(" ", 1)
        valor = int(valor)
        metas = carregar_metas()
        if nome in metas:
            metas[nome] = min(valor, 100)
            salvar_metas(metas)
            await update.message.reply_text(f"↪️ Meta “{nome}” atualizada para {valor}%")
        else:
            await update.message.reply_text("❌ Meta não encontrada.")
    except:
        await update.message.reply_text("❌ Formato inválido. Use: /atualizar <meta> <valor>")

# ————————————— FUNÇÕES DE ROTINA & AGENDA —————————————
async def rotina(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.replace("/rotina", "").strip()
    linhas = texto.split("\n")
    eventos = []
    hoje = datetime.now()
    dias = ["segunda","terça","quarta","quinta","sexta","sábado","domingo"]

    for linha in linhas:
        for idx, dia in enumerate(dias):
            if linha.lower().startswith(dia):
                parts = linha[len(dia):].strip().split(" ",1)
                hora = parts[0]
                tarefa = parts[1] if len(parts)>1 else ""
                data = hoje + timedelta(days=(idx - hoje.weekday()) % 7)
                data_str = data.strftime("%Y-%m-%d")
                eventos.append({"data":data_str,"hora":hora,"tarefa":tarefa})
                # cria no Google Calendar
                try:
                    hora_dt = datetime.strptime(hora, "%H:%M").time()
                    inicio = datetime.combine(data.date(), hora_dt)
                    fim = inicio + timedelta(hours=1)
                    service.events().insert(
                        calendarId=CALENDAR_ID,
                        body={
                            'summary': tarefa,
                            'start': {'dateTime': inicio.isoformat(), 'timeZone': 'America/Sao_Paulo'},
                            'end':   {'dateTime':   fim.isoformat(), 'timeZone': 'America/Sao_Paulo'},
                        }
                    ).execute()
                except Exception as e:
                    logging.warning(f"⚠️ Google Agenda: {e}")

    with open(ARQ_EVENTOS, "w") as f:
        json.dump(eventos, f, indent=4)

    await update.message.reply_text("✅ Rotina salva com sucesso!")

# ————————————— FEEDBACK MANUAL —————————————
async def feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    metas = carregar_metas()
    if not metas:
        return await update.message.reply_text("⚠️ Sem metas para avaliar.")
    total = sum(metas.values())
    pct = int(total / (len(metas)*100) * 100)
    melhor = max(metas.items(), key=lambda x: x[1])[0]
    msg = (
        f"📋 Resumo do dia:\n"
        f"🎯 Progresso semanal: {pct}%\n"
        f"📌 Meta mais próxima: {melhor}"
    )
    await update.message.reply_text(msg)

# ————————————— GERAÇÃO DE PDF —————————————
def gerar_pdf():
    metas = carregar_metas()
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, "📈 Relatório Semanal de Metas", ln=True, align="C")
    pdf.ln(5)
    for m, v in metas.items():
        pdf.cell(0, 10, f"• {m}: {v}%", ln=True)
    pdf.output("relatorio_semanal.pdf")

# ————————————— BACKUP CSV —————————————
def gerar_backup():
    metas = carregar_metas()
    with open("backup.csv","w",newline="") as f:
        w=csv.writer(f)
        w.writerow(["Meta","Progresso"])
        for m,v in metas.items():
            w.writerow([m,v])

# ————————————— START —————————————
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    if cid not in chat_ids:
        chat_ids.append(cid)
    await update.message.reply_text(
        "👋 Olá! Use:\n"
        "/metas  – definir metas\n"
        "/progresso – ver progresso\n"
        "/atualizar – atualizar meta\n"
        "/rotina – salvar rotina\n"
        "/feedback – resumo diário"
    )

# ————————————— AGENDADOR —————————————
def agendador(app):
    while True:
        now = datetime.now()
        h = now.strftime("%H:%M")
        wd = now.strftime("%A")

        if h == "20:00":  # feedback diário
            for cid in chat_ids:
                # reutiliza função de feedback
                metas = carregar_metas()
                if metas:
                    total = sum(metas.values())
                    pct = int(total / (len(metas)*100) * 100)
                    melhor = max(metas.items(), key=lambda x: x[1])[0]
                    app.bot.send_message(cid, 
                        f"📋 Resumo do dia:\n🎯 Progresso semanal: {pct}%\n📌 Meta mais próxima: {melhor}"
                    )
            time.sleep(60)

        elif wd == "Sunday" and h == "21:00":  # PDF semanal
            gerar_pdf()
            for cid in chat_ids:
                app.bot.send_document(cid, open("relatorio_semanal.pdf","rb"))
            time.sleep(60)

        elif wd == "Friday" and h == "18:00":  # backup semanal
            gerar_backup()
            time.sleep(60)

        else:
            time.sleep(30)

# ————————————— FUNÇÃO PRINCIPAL —————————————
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("metas", metas))
    app.add_handler(CommandHandler("progresso", progresso))
    app.add_handler(CommandHandler("atualizar", atualizar))
    app.add_handler(CommandHandler("rotina", rotina))
    app.add_handler(CommandHandler("feedback", feedback))

    # inicia agendador em thread
    threading.Thread(target=agendador, args=(app,), daemon=True).start()

    # inicia o bot
    app.run_polling()

if __name__ == "__main__":
    main()