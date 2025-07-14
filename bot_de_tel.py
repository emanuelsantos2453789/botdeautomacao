# bot_rotina_integrado.py
import os
import json
import csv
import logging
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from fpdf import FPDF
import threading
import time

# Configuração de logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Carregar token do ambiente
TOKEN = os.getenv('BOT_TOKEN')

# Caminhos de arquivos
ARQ_METAS = "metas.json"
ARQ_EVENTOS = "eventos.json"

# Carregar ou inicializar metas
def carregar_metas():
    if os.path.exists(ARQ_METAS):
        with open(ARQ_METAS, "r") as f:
            return json.load(f)
    return {}

def salvar_metas(metas):
    with open(ARQ_METAS, "w") as f:
        json.dump(metas, f, indent=4)

# Adicionar metas da semana
def metas(update: Update, context: CallbackContext):
    texto = update.message.text.replace("/metas", "").strip()
    linhas = texto.split("\n")
    metas = {linha.strip(): 0 for linha in linhas if linha.strip()}
    salvar_metas(metas)
    update.message.reply_text("Metas salvas com sucesso!")

# Ver progresso
def progresso(update: Update, context: CallbackContext):
    metas = carregar_metas()
    if not metas:
        update.message.reply_text("Nenhuma meta encontrada.")
        return

    total = sum(metas.values())
    maximo = len(metas) * 100
    porcentagem = int((total / maximo) * 100) if maximo > 0 else 0

    resposta = [f"{meta} - {valor}%" for meta, valor in metas.items()]
    resposta.append(f"\nProgresso total: {porcentagem}%")
    update.message.reply_text("\n".join(resposta))

# Atualizar progresso de uma meta
def atualizar(update: Update, context: CallbackContext):
    try:
        partes = update.message.text.replace("/atualizar", "").strip().split(" ", 1)
        meta, valor = partes[0], int(partes[1])
        metas = carregar_metas()
        if meta in metas:
            metas[meta] = min(valor, 100)
            salvar_metas(metas)
            update.message.reply_text(f"Meta '{meta}' atualizada para {valor}%")
        else:
            update.message.reply_text("Meta não encontrada.")
    except:
        update.message.reply_text("Formato inválido. Use: /atualizar <nome_da_meta> <valor>")

# Planejamento de rotina
def rotina(update: Update, context: CallbackContext):
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
                eventos.append({"data": data.strftime("%Y-%m-%d"), "hora": hora_texto, "tarefa": tarefa})

    with open(ARQ_EVENTOS, "w") as f:
        json.dump(eventos, f, indent=4)

    update.message.reply_text("Eventos salvos com sucesso!")

# Feedback automático
def feedback(update: Update, context: CallbackContext):
    metas = carregar_metas()
    if not metas:
        update.message.reply_text("Sem metas para avaliar.")
        return

    progresso_total = sum(metas.values()) / (len(metas) * 100) * 100
    meta_mais_proxima = max(metas.items(), key=lambda x: x[1])[0]
    msg = f"Resumo do dia:\n🎯 Progresso semanal: {int(progresso_total)}%\n📌 Meta mais próxima: {meta_mais_proxima}"
    update.message.reply_text(msg)

# Relatório em PDF
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

# Backup em CSV
def gerar_backup():
    metas = carregar_metas()
    with open("backup.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Meta", "Progresso"])
        for meta, valor in metas.items():
            writer.writerow([meta, valor])

# Funções agendadas
def tarefas_agendadas(bot):
    while True:
        agora = datetime.now()
        if agora.strftime("%H:%M") == "20:00":
            for chat_id in chat_ids:
                metas = carregar_metas()
                if metas:
                    progresso_total = sum(metas.values()) / (len(metas) * 100) * 100
                    meta_mais_proxima = max(metas.items(), key=lambda x: x[1])[0]
                    msg = f"Resumo do dia:\n🎯 Progresso semanal: {int(progresso_total)}%\n📌 Meta mais próxima: {meta_mais_proxima}"
                    bot.send_message(chat_id=chat_id, text=msg)
            time.sleep(60)
        elif agora.strftime("%A") == "Sunday" and agora.strftime("%H:%M") == "21:00":
            gerar_pdf()
            for chat_id in chat_ids:
                bot.send_document(chat_id=chat_id, document=open("relatorio_semanal.pdf", "rb"))
            time.sleep(60)
        elif agora.strftime("%A") == "Friday" and agora.strftime("%H:%M") == "18:00":
            gerar_backup()
            time.sleep(60)
        else:
            time.sleep(30)

# Comando de start
def start(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    if chat_id not in chat_ids:
        chat_ids.append(chat_id)
    update.message.reply_text("Olá! Envie /metas, /progresso, /atualizar, /rotina ou /feedback.")

# Lista de chats para feedback automático
chat_ids = []

# Função principal
if __name__ == '__main__':
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("metas", metas))
    dp.add_handler(CommandHandler("progresso", progresso))
    dp.add_handler(CommandHandler("atualizar", atualizar))
    dp.add_handler(CommandHandler("rotina", rotina))
    dp.add_handler(CommandHandler("feedback", feedback))

    # Iniciar thread de tarefas automáticas
    thread = threading.Thread(target=tarefas_agendadas, args=(updater.bot,), daemon=True)
    thread.start()

    updater.start_polling()
    updater.idle()
