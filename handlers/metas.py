from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, CallbackQueryHandler, filters

# --- Estados da Conversa para Metas (Locais) ---
# Estes estados são específicos para o ConversationHandler de metas
CHOOSING_METAS_ACTION = 101
TYPING_META_ADD = 102
TYPING_META_COMPLETE = 103
TYPING_META_DELETE = 104

# Dicionário para armazenar as metas. Será armazenado em context.user_data para persistência por usuário.
# metas_semanais = {
#     user_id: {
#         'meta_texto_1': 'pendente',
#         'meta_texto_2': 'concluída'
#     }
# }

def get_metas_menu_keyboard():
    """Retorna o teclado com as opções do menu de metas."""
    keyboard = [
        [InlineKeyboardButton("➕ Adicionar Meta", callback_data='metas_add')],
        [InlineKeyboardButton("📋 Listar Metas", callback_data='metas_list')],
        [InlineKeyboardButton("✅ Concluir Meta", callback_data='metas_complete')],
        [InlineKeyboardButton("🗑️ Apagar Meta", callback_data='metas_delete')],
        [InlineKeyboardButton("↩️ Voltar ao Menu Principal", callback_data='main_menu_return')]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start_metas_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Exibe o menu de gerenciamento de metas e define o estado da conversa.
    Este é o ponto de entrada para o ConversationHandler de Metas.
    """
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(
            'O que você quer fazer com suas metas semanais? 🎯',
            reply_markup=get_metas_menu_keyboard()
        )
    else: # Caso seja chamado por um comando direto, como /metas, sem callback
        await update.message.reply_text(
            'O que você quer fazer com suas metas semanais? 🎯',
            reply_markup=get_metas_menu_keyboard()
        )
    return CHOOSING_METAS_ACTION

async def add_meta_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Pede ao usuário para digitar a nova meta."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Qual meta você quer adicionar? Digite abaixo:")
    return TYPING_META_ADD

async def process_add_meta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Processa o texto digitado pelo usuário e adiciona a meta."""
    user_id = update.effective_user.id
    new_meta = update.message.text.strip()

    if 'metas_semanais' not in context.user_data:
        context.user_data['metas_semanais'] = {}
    if user_id not in context.user_data['metas_semanais']:
        context.user_data['metas_semanais'][user_id] = {}

    if new_meta:
        context.user_data['metas_semanais'][user_id][new_meta] = 'pendente'
        await update.message.reply_text(f'Meta "{new_meta}" adicionada com sucesso! 🎉')
    else:
        await update.message.reply_text("Você não digitou nada. Tente novamente.")

    await update.message.reply_text(
        'O que mais você quer fazer com suas metas semanais? 🎯',
        reply_markup=get_metas_menu_keyboard()
    )
    return CHOOSING_METAS_ACTION

async def list_metas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Lista as metas do usuário, separando por pendentes e concluídas."""
    user_id = update.effective_user.id
    query = update.callback_query
    
    metas_do_usuario = context.user_data.get('metas_semanais', {}).get(user_id, {})

    if not metas_do_usuario:
        message = "Você não tem nenhuma meta cadastrada ainda. Que tal adicionar uma? 🤔"
    else:
        mensagem = "Suas Metas Semanais:\n\n"
        metas_pendentes = [meta for meta, status in metas_do_usuario.items() if status == 'pendente']
        metas_concluidas = [meta for meta, status in metas_do_usuario.items() if status == 'concluída']

        if metas_pendentes:
            mensagem += "📚 *Pendentes:*\n"
            for i, meta in enumerate(metas_pendentes, 1):
                mensagem += f"{i}. {meta}\n"
        else:
            mensagem += "🎉 Nenhuma meta pendente! Parabéns!\n"

        if metas_concluidas:
            mensagem += "\n✅ *Concluídas:*\n"
            for i, meta in enumerate(metas_concluidas, 1):
                mensagem += f"{i}. {meta}\n"
        message = mensagem

    await query.answer()
    await query.edit_message_text(text=message, parse_mode='Markdown')
    
    await query.message.reply_text(
        'O que mais você quer fazer com suas metas semanais? 🎯',
        reply_markup=get_metas_menu_keyboard()
    )
    return CHOOSING_METAS_ACTION

async def complete_meta_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Pede ao usuário para digitar a meta que deseja concluir."""
    user_id = update.effective_user.id
    query = update.callback_query
    await query.answer()

    metas_do_usuario = context.user_data.get('metas_semanais', {}).get(user_id, {})
    metas_pendentes = [meta for meta, status in metas_do_usuario.items() if status == 'pendente']

    if not metas_pendentes:
        await query.edit_message_text("Você não tem metas pendentes para concluir! 🎉")
        await query.message.reply_text(
            'O que mais você quer fazer com suas metas semanais? 🎯',
            reply_markup=get_metas_menu_keyboard()
        )
        return CHOOSING_METAS_ACTION

    lista_metas_str = "\n".join([f"- {meta}" for meta in metas_pendentes])
    await query.edit_message_text(text=f"Qual meta você concluiu? Digite o nome exato:\n{lista_metas_str}")
    return TYPING_META_COMPLETE

async def process_complete_meta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Processa o texto digitado pelo usuário e conclui a meta."""
    user_id = update.effective_user.id
    meta_to_complete = update.message.text.strip()
    metas_do_usuario = context.user_data.get('metas_semanais', {}).get(user_id, {})

    if meta_to_complete in metas_do_usuario and metas_do_usuario[meta_to_complete] == 'pendente':
        metas_do_usuario[meta_to_complete] = 'concluída'
        await update.message.reply_text(f'Parabéns! Meta "{meta_to_complete}" concluída! ✅')
    else:
        await update.message.reply_text(f'A meta "{meta_to_complete}" não foi encontrada ou já está concluída. 🤔')

    await update.message.reply_text(
        'O que mais você quer fazer com suas metas semanais? 🎯',
        reply_markup=get_metas_menu_keyboard()
    )
    return CHOOSING_METAS_ACTION

async def delete_meta_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Pede ao usuário para digitar a meta que deseja apagar."""
    user_id = update.effective_user.id
    query = update.callback_query
    await query.answer()

    metas_do_usuario = context.user_data.get('metas_semanais', {}).get(user_id, {})
    if not metas_do_usuario:
        await query.edit_message_text("Você não tem nenhuma meta para apagar. 🤔")
        await query.message.reply_text(
            'O que mais você quer fazer com suas metas semanais? 🎯',
            reply_markup=get_metas_menu_keyboard()
        )
        return CHOOSING_METAS_ACTION

    lista_metas_str = "\n".join([f"- {meta}" for meta in metas_do_usuario.keys()])
    await query.edit_message_text(text=f"Qual meta você quer apagar? Digite o nome exato:\n{lista_metas_str}")
    return TYPING_META_DELETE

async def process_delete_meta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Processa o texto digitado pelo usuário e apaga a meta."""
    user_id = update.effective_user.id
    meta_to_delete = update.message.text.strip()
    metas_do_usuario = context.user_data.get('metas_semanais', {}).get(user_id, {})

    if meta_to_delete in metas_do_usuario:
        del metas_do_usuario[meta_to_delete]
        await update.message.reply_text(f'Meta "{meta_to_delete}" apagada com sucesso! 🗑️')
    else:
        await update.message.reply_text(f'A meta "{meta_to_delete}" não foi encontrada. 🤔')

    await update.message.reply_text(
        'O que mais você quer fazer com suas metas semanaais? 🎯',
        reply_markup=get_metas_menu_keyboard()
    )
    return CHOOSING_METAS_ACTION

async def cancel_metas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancela a conversa de metas e retorna ao menu principal."""
    query = update.callback_query
    if query:
        await query.answer()
        # O retorno para o menu principal será tratado pelo CallbackQueryHandler no main.py
        # que escuta por 'main_menu_return' e leva ao MAIN_MENU_STATE.
        # Não precisamos editar a mensagem aqui, pois o main_menu_return fará isso.
    return ConversationHandler.END


def get_metas_conversation_handler() -> ConversationHandler:
    """Retorna o ConversationHandler para a funcionalidade de metas."""
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_metas_menu, pattern='^open_metas_menu$')
        ],
        states={
            CHOOSING_METAS_ACTION: [
                CallbackQueryHandler(add_meta_prompt, pattern='^metas_add$'),
                CallbackQueryHandler(list_metas, pattern='^metas_list$'),
                CallbackQueryHandler(complete_meta_prompt, pattern='^metas_complete$'),
                CallbackQueryHandler(delete_meta_prompt, pattern='^metas_delete$'),
                CallbackQueryHandler(cancel_metas, pattern='^main_menu_return$') # Handler para voltar ao menu principal
            ],
            TYPING_META_ADD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_add_meta)
            ],
            TYPING_META_COMPLETE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_complete_meta)
            ],
            TYPING_META_DELETE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_delete_meta)
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel_metas, pattern='^main_menu_return$'), # Fallback global para voltar
            MessageHandler(filters.ALL & ~filters.COMMAND, start_metas_menu) # Tenta mostrar o menu novamente
        ],
        map_to_parent={
            ConversationHandler.END: ConversationHandler.END # Indica ao handler pai que a conversa terminou
        }
    )
