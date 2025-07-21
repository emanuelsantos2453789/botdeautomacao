# main.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters
)

from handlers.pomodoro import Pomodoro # Importa a classe Pomodoro

# --- 1. Seu Token do Bot ---
TOKEN = "7677783341:AAFiCgEdkcaV_V03y_CZo2L2_F_NHGwlN54 "

# Dicionário para armazenar uma instância de Pomodoro para cada usuário
# Isso garante que cada usuário tenha suas próprias configurações e estado do Pomodoro.
user_pomodoros = {}

# --- Estados da Conversa Global (do bot principal) ---
MAIN_MENU_STATE = 0


# --- Funções Auxiliares para o Bot Principal ---

def get_main_menu_keyboard():
    """Retorna o teclado do menu principal do bot."""
    keyboard = [
        [InlineKeyboardButton("🍅 Pomodoro", callback_data="open_pomodoro_menu")],
        # Adicione outros botões de menu principal aqui, se tiver
        # Ex: [InlineKeyboardButton("📝 Tarefas", callback_data="open_tasks_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Responde ao comando /start e mostra o menu principal do bot."""
    await update.message.reply_text(
        "Olá! Eu sou seu bot de produtividade. Escolha uma opção:",
        reply_markup=get_main_menu_keyboard()
    )
    return MAIN_MENU_STATE # Define o estado inicial da conversa como o menu principal

async def open_pomodoro_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler para o botão 'Pomodoro' no menu principal.
    Responsável por inicializar a instância do Pomodoro para o usuário
    e passar o controle para o ConversationHandler do Pomodoro.
    """
    query = update.callback_query
    await query.answer() # Sempre responda à query de callback

    user_id = update.effective_user.id
    if user_id not in user_pomodoros:
        # Cria uma instância de Pomodoro para o usuário, passando o bot e o chat_id
        user_pomodoros[user_id] = Pomodoro(bot=context.bot, chat_id=update.effective_chat.id)
    
    # O retorno de _show_pomodoro_menu é o estado POMODORO_MENU_STATE.
    # Ao retornar este estado do handler do entry_point do ConversationHandler aninhado,
    # o ConversationHandler principal "muda" para o estado que corresponde ao sub-ConversationHandler.
    return await user_pomodoros[user_id]._show_pomodoro_menu(update, context)


async def return_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler para o callback 'main_menu_return'.
    É acionado quando o ConversationHandler do Pomodoro retorna ConversationHandler.END
    e o `map_to_parent` direciona para cá.
    """
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "De volta ao menu principal. Escolha uma opção:",
        reply_markup=get_main_menu_keyboard()
    )
    return MAIN_MENU_STATE # Retorna ao estado do menu principal do bot


async def fallback_global(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler de fallback global para mensagens ou callbacks não esperados
    em qualquer estado da conversa principal.
    """
    if update.message:
        await update.message.reply_text(
            "Desculpe, não entendi. Por favor, use os botões ou o comando /start.",
            reply_markup=get_main_menu_keyboard()
        )
    elif update.callback_query:
        await update.callback_query.answer("Ação inválida. Por favor, use os botões.")
        # Se um callback_query inesperado ocorrer, tentamos editar a mensagem para mostrar o menu principal
        await update.callback_query.edit_message_text(
            "Ação inválida. Escolha uma opção:",
            reply_markup=get_main_menu_keyboard()
        )
    return MAIN_MENU_STATE # Tenta retornar ao estado do menu principal


# --- Função Principal para Iniciar o Bot ---

def main():
    """Configura e inicia o bot."""
    application = Application.builder().token(TOKEN).build()

    # Cria uma instância temporária de Pomodoro apenas para obter o ConversationHandler.
    # A instância real para cada usuário é criada e gerenciada em user_pomodoros.
    temp_pomodoro_instance = Pomodoro() 

    # Constrói o ConversationHandler para o fluxo principal do bot.
    # Este handler gerencia a transição entre os módulos principais (e o Pomodoro).
    main_conversation_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start_command)], # Ponto de entrada principal do bot
        states={
            MAIN_MENU_STATE: [
                # Quando o usuário clica em 'open_pomodoro_menu', ele entra na sub-conversação do Pomodoro.
                # O ConversationHandler do Pomodoro (retornado por get_pomodoro_conversation_handler)
                # se torna o handler ativo para o estado MAIN_MENU_STATE neste ponto.
                # O `entry_point` do ConversationHandler do Pomodoro deve ser o mesmo pattern 'open_pomodoro_menu'.
                temp_pomodoro_instance.get_pomodoro_conversation_handler(),
            ],
            # Outros estados para outros menus principais podem ser adicionados aqui no futuro.
            # Ex: OTHER_MENU_STATE: [...]
        },
        fallbacks=[
            # Este fallback captura o CallbackQuery "main_menu_return" que o Pomodoro envia
            # quando sua conversa aninhada retorna ConversationHandler.END.
            # Ele então chama return_to_main_menu para exibir o menu principal novamente.
            CallbackQueryHandler(return_to_main_menu, pattern="^main_menu_return$"),
            # Fallback geral para qualquer outra mensagem ou comando não tratado
            MessageHandler(filters.ALL, fallback_global),
        ],
        # per_user=True é o padrão para ConversationHandler e é crucial para manter
        # estados de conversa separados para cada usuário.
    )

    application.add_handler(main_conversation_handler)

    print("Bot rodando... Pressione Ctrl+C para parar.")
    application.run_polling(poll_interval=1.0) # Adicionado poll_interval para melhor controle

# --- Ponto de Entrada do Script ---
if __name__ == "__main__":
    main()
