import logging
# Configuração básica de logging
# Isso irá registrar mensagens de nível INFO ou superior no console
# e mensagens de nível DEBUG ou superior em 'bot.log'
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO # Defina para DEBUG para ver mais detalhes durante o desenvolvimento
)
logger = logging.getLogger(__name__) # O logger para este módulo específico
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, CallbackQueryHandler, filters
import logging

# Configuração do logger para este módulo
logger = logging.getLogger(__name__)

# --- Estados da Conversa para Metas (Locais) ---
CHOOSING_METAS_ACTION = 101
TYPING_META_ADD = 102
TYPING_META_COMPLETE = 103
TYPING_META_DELETE = 104

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
    try:
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
        logger.info(f"Usuário {update.effective_user.id} entrou no menu de metas.")
        return CHOOSING_METAS_ACTION
    except Exception as e:
        logger.error(f"Erro ao iniciar o menu de metas para o usuário {update.effective_user.id}: {e}", exc_info=True)
        if update.callback_query:
            await update.callback_query.message.reply_text("Ops! Ocorreu um erro ao carregar o menu de metas. Tente novamente mais tarde.")
        else:
            await update.message.reply_text("Ops! Ocorreu um erro ao carregar o menu de metas. Tente novamente mais tarde.")
        return ConversationHandler.END # Pode ser útil encerrar a conversa em caso de erro crítico

async def add_meta_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Pede ao usuário para digitar a nova meta."""
    try:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("Qual meta você quer adicionar? Digite abaixo:")
        logger.info(f"Usuário {update.effective_user.id} solicitou adicionar uma meta.")
        return TYPING_META_ADD
    except Exception as e:
        logger.error(f"Erro ao solicitar meta para adição ao usuário {update.effective_user.id}: {e}", exc_info=True)
        await query.message.reply_text("Ops! Ocorreu um erro ao pedir sua meta. Por favor, tente novamente.")
        return CHOOSING_METAS_ACTION # Volta para o menu para o usuário tentar outra ação

async def process_add_meta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Processa o texto digitado pelo usuário e adiciona a meta."""
    try:
        user_id = update.effective_user.id
        new_meta = update.message.text.strip()

        if not new_meta:
            await update.message.reply_text("Você não digitou nada. Tente novamente.")
            logger.warning(f"Usuário {user_id} tentou adicionar meta vazia.")
        else:
            if 'metas_semanais' not in context.user_data:
                context.user_data['metas_semanais'] = {}
            if user_id not in context.user_data['metas_semanais']:
                context.user_data['metas_semanais'][user_id] = {}

            if new_meta in context.user_data['metas_semanais'][user_id]:
                await update.message.reply_text(f'A meta "{new_meta}" já existe! Tente outra ou verifique suas metas.')
                logger.info(f"Usuário {user_id} tentou adicionar meta duplicada: '{new_meta}'.")
            else:
                context.user_data['metas_semanais'][user_id][new_meta] = 'pendente'
                await update.message.reply_text(f'Meta "{new_meta}" adicionada com sucesso! 🎉')
                logger.info(f"Usuário {user_id} adicionou a meta: '{new_meta}'.")

        await update.message.reply_text(
            'O que mais você quer fazer com suas metas semanais? 🎯',
            reply_markup=get_metas_menu_keyboard()
        )
        return CHOOSING_METAS_ACTION
    except Exception as e:
        logger.error(f"Erro ao processar adição de meta para o usuário {update.effective_user.id} (meta: '{new_meta}'): {e}", exc_info=True)
        await update.message.reply_text("Ops! Ocorreu um erro ao adicionar sua meta. Por favor, tente novamente.")
        return CHOOSING_METAS_ACTION

async def list_metas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Lista as metas do usuário, separando por pendentes e concluídas."""
    try:
        user_id = update.effective_user.id
        query = update.callback_query
        await query.answer()
        
        metas_do_usuario = context.user_data.get('metas_semanais', {}).get(user_id, {})

        if not metas_do_usuario:
            message = "Você não tem nenhuma meta cadastrada ainda. Que tal adicionar uma? 🤔"
            logger.info(f"Usuário {user_id} solicitou listar metas, mas não tem nenhuma.")
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
            logger.info(f"Usuário {user_id} listou suas metas.")

        await query.edit_message_text(text=message, parse_mode='Markdown')
        
        await query.message.reply_text(
            'O que mais você quer fazer com suas metas semanais? 🎯',
            reply_markup=get_metas_menu_keyboard()
        )
        return CHOOSING_METAS_ACTION
    except Exception as e:
        logger.error(f"Erro ao listar metas para o usuário {update.effective_user.id}: {e}", exc_info=True)
        if query:
            await query.message.reply_text("Ops! Ocorreu um erro ao listar suas metas. Por favor, tente novamente.")
        else:
            await update.message.reply_text("Ops! Ocorreu um erro ao listar suas metas. Por favor, tente novamente.")
        return CHOOSING_METAS_ACTION

async def complete_meta_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Pede ao usuário para digitar a meta que deseja concluir."""
    try:
        user_id = update.effective_user.id
        query = update.callback_query
        await query.answer()

        metas_do_usuario = context.user_data.get('metas_semanais', {}).get(user_id, {})
        metas_pendentes = [meta for meta, status in metas_do_usuario.items() if status == 'pendente']

        if not metas_pendentes:
            await query.edit_message_text("Você não tem metas pendentes para concluir! 🎉")
            logger.info(f"Usuário {user_id} tentou concluir meta, mas não tem pendentes.")
            await query.message.reply_text(
                'O que mais você quer fazer com suas metas semanais? 🎯',
                reply_markup=get_metas_menu_keyboard()
            )
            return CHOOSING_METAS_ACTION

        lista_metas_str = "\n".join([f"- {meta}" for meta in metas_pendentes])
        await query.edit_message_text(text=f"Qual meta você concluiu? Digite o nome exato:\n{lista_metas_str}")
        logger.info(f"Usuário {user_id} solicitou concluir uma meta.")
        return TYPING_META_COMPLETE
    except Exception as e:
        logger.error(f"Erro ao solicitar meta para conclusão ao usuário {update.effective_user.id}: {e}", exc_info=True)
        await query.message.reply_text("Ops! Ocorreu um erro ao preparar a conclusão da meta. Por favor, tente novamente.")
        return CHOOSING_METAS_ACTION

async def process_complete_meta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Processa o texto digitado pelo usuário e conclui a meta."""
    try:
        user_id = update.effective_user.id
        meta_to_complete = update.message.text.strip()
        metas_do_usuario = context.user_data.get('metas_semanais', {}).get(user_id, {})

        if meta_to_complete in metas_do_usuario and metas_do_usuario[meta_to_complete] == 'pendente':
            metas_do_usuario[meta_to_complete] = 'concluída'
            await update.message.reply_text(f'Parabéns! Meta "{meta_to_complete}" concluída! ✅')
            logger.info(f"Usuário {user_id} concluiu a meta: '{meta_to_complete}'.")
        else:
            await update.message.reply_text(f'A meta "{meta_to_complete}" não foi encontrada ou já está concluída. 🤔')
            logger.warning(f"Usuário {user_id} tentou concluir meta inválida ou já concluída: '{meta_to_complete}'.")

        await update.message.reply_text(
            'O que mais você quer fazer com suas metas semanais? 🎯',
            reply_markup=get_metas_menu_keyboard()
        )
        return CHOOSING_METAS_ACTION
    except Exception as e:
        logger.error(f"Erro ao processar conclusão de meta para o usuário {update.effective_user.id} (meta: '{meta_to_complete}'): {e}", exc_info=True)
        await update.message.reply_text("Ops! Ocorreu um erro ao concluir sua meta. Por favor, tente novamente.")
        return CHOOSING_METAS_ACTION

async def delete_meta_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Pede ao usuário para digitar a meta que deseja apagar."""
    try:
        user_id = update.effective_user.id
        query = update.callback_query
        await query.answer()

        metas_do_usuario = context.user_data.get('metas_semanais', {}).get(user_id, {})
        if not metas_do_usuario:
            await query.edit_message_text("Você não tem nenhuma meta para apagar. 🤔")
            logger.info(f"Usuário {user_id} tentou apagar meta, mas não tem nenhuma.")
            await query.message.reply_text(
                'O que mais você quer fazer com suas metas semanais? 🎯',
                reply_markup=get_metas_menu_keyboard()
            )
            return CHOOSING_METAS_ACTION

        lista_metas_str = "\n".join([f"- {meta}" for meta in metas_do_usuario.keys()])
        await query.edit_message_text(text=f"Qual meta você quer apagar? Digite o nome exato:\n{lista_metas_str}")
        logger.info(f"Usuário {user_id} solicitou apagar uma meta.")
        return TYPING_META_DELETE
    except Exception as e:
        logger.error(f"Erro ao solicitar meta para exclusão ao usuário {update.effective_user.id}: {e}", exc_info=True)
        await query.message.reply_text("Ops! Ocorreu um erro ao preparar a exclusão da meta. Por favor, tente novamente.")
        return CHOOSING_METAS_ACTION

async def process_delete_meta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Processa o texto digitado pelo usuário e apaga a meta."""
    try:
        user_id = update.effective_user.id
        meta_to_delete = update.message.text.strip()
        metas_do_usuario = context.user_data.get('metas_semanais', {}).get(user_id, {})

        if meta_to_delete in metas_do_usuario:
            del metas_do_usuario[meta_to_delete]
            await update.message.reply_text(f'Meta "{meta_to_delete}" apagada com sucesso! 🗑️')
            logger.info(f"Usuário {user_id} apagou a meta: '{meta_to_delete}'.")
        else:
            await update.message.reply_text(f'A meta "{meta_to_delete}" não foi encontrada. 🤔')
            logger.warning(f"Usuário {user_id} tentou apagar meta não encontrada: '{meta_to_delete}'.")

        await update.message.reply_text(
            'O que mais você quer fazer com suas metas semanais? 🎯',
            reply_markup=get_metas_menu_keyboard()
        )
        return CHOOSING_METAS_ACTION
    except Exception as e:
        logger.error(f"Erro ao processar exclusão de meta para o usuário {update.effective_user.id} (meta: '{meta_to_delete}'): {e}", exc_info=True)
        await update.message.reply_text("Ops! Ocorreu um erro ao apagar sua meta. Por favor, tente novamente.")
        return CHOOSING_METAS_ACTION

async def cancel_metas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancela a conversa de metas e retorna ao menu principal."""
    try:
        query = update.callback_query
        if query:
            await query.answer()
        logger.info(f"Usuário {update.effective_user.id} cancelou a conversa de metas.")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Erro ao cancelar conversa de metas para o usuário {update.effective_user.id}: {e}", exc_info=True)
        # Tenta enviar uma mensagem de erro, mas o estado da conversa já pode estar em transição
        if update.callback_query:
            await update.callback_query.message.reply_text("Ops! Ocorreu um erro ao sair do menu de metas.")
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
            # Este fallback pega qualquer mensagem ou callback que não corresponda aos estados atuais
            # e tenta levar o usuário de volta ao menu de metas ou ao menu principal
            CallbackQueryHandler(cancel_metas, pattern='^main_menu_return$'), # Fallback global para voltar ao menu principal
            MessageHandler(filters.ALL & ~filters.COMMAND, start_metas_menu) # Tenta mostrar o menu novamente para qualquer texto/não-comando
        ],
        map_to_parent={
            ConversationHandler.END: ConversationHandler.END # Indica ao handler pai que a conversa terminou
        }
    )
