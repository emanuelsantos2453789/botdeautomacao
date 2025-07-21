from telegram.ext import Application, CommandHandler, MessageHandler, filters

# --- 1. Seu Token do Bot ---
# Você consegue esse token com o BotFather no Telegram.
# Substitua "SEU_TOKEN_AQUI" pelo token real do seu bot.
TOKEN = "BOT_TOKEN"

# --- 2. Funções para lidar com Comandos e Mensagens ---

# Esta função será executada quando o usuário enviar o comando /start
async def start(update, context):
    """Responde ao comando /start."""
    await update.message.reply_text("Olá! Eu sou seu novo bot. Como posso ajudar hoje?")
    print("EU Estou Aqui")

# Esta função será executada quando o usuário enviar uma mensagem de texto (que não seja um comando)
async def ecoar_mensagem(update, context):
    """Ecoa a mensagem de texto recebida."""
    texto_recebido = update.message.text
    await update.message.reply_text(f"Você disse: '{texto_recebido}'")

# --- 3. Função Principal para Iniciar o Bot ---

def main():
    """Inicia o bot."""
    # Cria a aplicação do bot com seu token.
    application = Application.builder().token(TOKEN).build()

    # Adiciona os "handlers" (manipuladores) que dizem ao bot o que fazer.
    # O CommandHandler reage a comandos específicos (ex: /start).
    application.add_handler(CommandHandler("start", start))

    # O MessageHandler reage a tipos de mensagens (ex: mensagens de texto que não são comandos).
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ecoar_mensagem))

    # Inicia o bot, ele ficará "escutando" por novas mensagens.
    print("Bot rodando... Pressione Ctrl+C para parar.")
    application.run_polling()

# --- 4. Ponto de Entrada do Script ---
# Garante que a função 'main' seja chamada quando o script for executado.
if __name__ == "__main__":
    main()
