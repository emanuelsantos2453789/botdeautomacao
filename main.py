# main.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ConversationHandler, ContextTypes

from handlers.pomodoro import Pomodoro # Importa a classe Pomodoro

# --- 1. Seu Token do Bot ---
TOKEN = "8025423173:AAE4cX3_UVQEigT64VWZfloN9IiJD-yVMY"

# Dicionário para armazenar uma instância de Pomodoro para cada usuário
user_pomodoros = {}

# --- Estados da Conversa Global (se houver mais módulos no futuro) ---
# Por enquanto, apenas o estado inicial para o menu principal
MAIN_MENU_STATE = 0


# --- Funções Auxiliares para o Bot Principal ---

def get_main_menu_keyboard():
    """Retorna o teclado do menu principal."""
    keyboard = [
        [InlineKeyboardButton("🍅 Pomodoro", callback_data="open_pomodoro_menu")],
        # Adicione outros botões de menu principal aqui, se tiver
        # Ex: [InlineKeyboardButton("📝 Tarefas", callback_data="open_tasks_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Responde ao comando /start e mostra o menu principal."""
    await update.message.reply_text(
        "Olá! Eu sou seu bot de produtividade. Escolha uma opção:",
        reply_markup=get_main_menu_keyboard()
    )
    return MAIN_MENU_STATE # Inicia a conversa no estado do menu principal

async def open_pomodoro_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Abre o menu Pomodoro a partir do menu principal."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    if user_id not in user_pomodoros:
        # Cria uma instância de Pomodoro para o usuário, passando o bot e o chat_id
        user_pomodoros[user_id] = Pomodoro(bot=context.bot, chat_id=update.effective_chat.id)
    
    # Chama o método que mostra o menu do Pomodoro
    return await user_pomodoros[user_id]._show_pomodoro_menu(update, context)


async def return_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Retorna ao menu principal do bot."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "De volta ao menu principal. Escolha uma opção:",
        reply_markup=get_main_menu_keyboard()
    )
    return MAIN_MENU_STATE


async def fallback_global(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler de fallback global para mensagens não esperadas."""
    if update.message:
        await update.message.reply_text(
            "Desculpe, não entendi. Por favor, use os botões ou o comando /start.",
            reply_markup=get_main_menu_keyboard()
        )
    elif update.callback_query:
        await update.callback_query.answer("Ação inválida. Por favor, use os botões.")
        # Opcional: tentar editar a mensagem do callback_query para mostrar o menu principal
        # await update.callback_query.edit_message_text(
        #     "Ação inválida. Escolha uma opção:",
        #     reply_markup=get_main_menu_keyboard()
        # )
    return MAIN_MENU_STATE


# --- Função Principal para Iniciar o Bot ---

def main():
    """Inicia o bot."""
    application = Application.builder().token(TOKEN).build()

    # Cria uma instância "vazia" de Pomodoro apenas para acessar o ConversationHandler
    # A instância real para o usuário será criada no `open_pomodoro_menu`
    temp_pomodoro_instance = Pomodoro() 

    # Constrói o ConversationHandler para o fluxo principal do bot
    main_conversation_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={
            MAIN_MENU_STATE: [
                CallbackQueryHandler(open_pomodoro_menu, pattern="^open_pomodoro_menu$"),
                # Aqui você adicionaria handlers para outros módulos/menus no futuro
            ],
            # Adiciona o Pomodoro ConversationHandler como um sub-handler
            # O estado que representa o Pomodoro ConversationHandler é o seu `entry_point`
            # Ele "pega" a conversa quando o padrão do CallbackQueryHandler é acionado
            # e a libera quando `ConversationHandler.END` é retornado de dentro dele.
            temp_pomodoro_instance.POMODORO_MENU_STATE: [
                temp_pomodoro_instance.get_pomodoro_conversation_handler(),
                CallbackQueryHandler(return_to_main_menu, pattern="^main_menu_return$"), # Handler para o botão "Voltar ao Início"
            ]
        },
        fallbacks=[
            # Fallback para mensagens não reconhecidas em qualquer estado
            MessageHandler(filters.ALL, fallback_global),
        ],
        # `per_user=True` é o padrão para ConversationHandler, o que é bom para nosso caso de múltiplos usuários
        # `allow_reentry=True` permite reentrar no mesmo ConversationHandler se ele já terminou
    )

    application.add_handler(main_conversation_handler)

    print("Bot rodando... Pressione Ctrl+C para parar.")
    application.run_polling()

# --- Ponto de Entrada do Script ---
if __name__ == "__main__":
    main()
