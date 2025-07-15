import logging
import os
import json
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(level=logging.INFO)

# Função para salvar mensagens como "rotina"
def salvar_rotina(mensagem):
    if not os.path.exists("rotina.json"):
        rotina = []
    else:
        with open("rotina.json", "r") as f:
            rotina = json.load(f)
    rotina.append(mensagem)
    with open("rotina.json", "w") as f:
        json.dump(rotina, f, indent=2)

# Comando /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot de rotina ativo! Envie sua rotina que eu salvo.")

# Quando o usuário manda qualquer texto
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    salvar_rotina(texto)
    await update.message.reply_text("Rotina salva com sucesso! ✅")

# Inicializa o bot
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.run_polling()

if __name__ == '__main__':
    main()

    thread.start()

    updater.start_polling()
    updater.idle()
