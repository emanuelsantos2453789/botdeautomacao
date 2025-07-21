# main.py
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from pomodoro_manager import Pomodoro # Importa a classe Pomodoro

# --- 1. Seu Token do Bot ---
TOKEN = "8025423173:AAE4cXH3_UVQEigT64VWZfloN9IiJD-yVMY"

# Dicionário para armazenar uma instância de Pomodoro para cada usuário
# A chave será o user_id do Telegram
user_pomodoros = {}

# --- 2. Funções para lidar com Comandos de Pomodoro ---

async def get_or_create_pomodoro(update, context):
    """
    Função auxiliar para obter a instância do Pomodoro para o usuário,
    ou criar uma nova se não existir.
    """
    user_id = update.effective_user.id
    if user_id not in user_pomodoros:
        # Passa o objeto bot e o chat_id para a instância Pomodoro
        user_pomodoros[user_id] = Pomodoro(bot=context.bot, chat_id=update.effective_chat.id)
    return user_pomodoros[user_id]

async def iniciar_pomodoro(update, context):
    """Responde ao comando /iniciar."""
    pomodoro = await get_or_create_pomodoro(update, context)
    response = await pomodoro.iniciar()
    await update.message.reply_text(response)

async def pausar_pomodoro(update, context):
    """Responde ao comando /pausar."""
    pomodoro = await get_or_create_pomodoro(update, context)
    response = await pomodoro.pausar()
    await update.message.reply_text(response)

async def parar_pomodoro(update, context):
    """Responde ao comando /parar."""
    pomodoro = await get_or_create_pomodoro(update, context)
    response = await pomodoro.parar()
    await update.message.reply_text(response, parse_mode='Markdown') # Use Markdown para o relatório formatado

async def status_pomodoro(update, context):
    """Responde ao comando /status."""
    pomodoro = await get_or_create_pomodoro(update, context)
    response = pomodoro.status() # Não é await porque não faz chamadas assíncronas internas
    await update.message.reply_text(response)

async def configurar_pomodoro(update, context):
    """Responde ao comando /configurar e define os tempos do Pomodoro."""
    pomodoro = await get_or_create_pomodoro(update, context)
    
    args = context.args # Lista de argumentos passados após o comando

    if not args or len(args) % 2 != 0:
        await update.message.reply_text(
            "Uso: /configurar foco <min> pausa_curta <min> pausa_longa <min> ciclos <num>\n"
            "Ex: /configurar foco 30 pausa_curta 7 ciclos 3"
        )
        return

    foco, pausa_curta, pausa_longa, ciclos_longa = None, None, None, None
    try:
        for i in range(0, len(args), 2):
            key = args[i]
            value = int(args[i+1])
            if key == "foco":
                foco = value
            elif key == "pausa_curta":
                pausa_curta = value
            elif key == "pausa_longa":
                pausa_longa = value
            elif key == "ciclos":
                ciclos_longa = value
            else:
                await update.message.reply_text(f"Argumento desconhecido: '{key}'.")
                return
    except (ValueError, IndexError):
        await update.message.reply_text("Erro de formato. Certifique-se de que os valores são números inteiros.")
        return

    response = await pomodoro.configurar(foco, pausa_curta, pausa_longa, ciclos_longa)
    await update.message.reply_text(response)

# --- Funções existentes do seu bot ---
async def start(update, context):
    """Responde ao comando /start."""
    await update.message.reply_text("Olá! Eu sou seu novo bot. Como posso ajudar hoje? "
                                    "Experimente /iniciar para começar um Pomodoro!")
    print("EU Estou Aqui")

async def ecoar_mensagem(update, context):
    """Ecoa a mensagem de texto recebida."""
    texto_recebido = update.message.text
    await update.message.reply_text(f"Você disse: '{texto_recebido}'")

# --- 3. Função Principal para Iniciar o Bot ---

def main():
    """Inicia o bot."""
    application = Application.builder().token(TOKEN).build()

    # Adiciona os handlers para os comandos do Pomodoro
    application.add_handler(CommandHandler("iniciar", iniciar_pomodoro))
    application.add_handler(CommandHandler("pausar", pausar_pomodoro))
    application.add_handler(CommandHandler("parar", parar_pomodoro))
    application.add_handler(CommandHandler("status", status_pomodoro))
    application.add_handler(CommandHandler("configurar", configurar_pomodoro))


    # Adiciona os handlers que você já tinha
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ecoar_mensagem))

    print("Bot rodando... Pressione Ctrl+C para parar.")
    application.run_polling()

# --- 4. Ponto de Entrada do Script ---
if __name__ == "__main__":
    main()
