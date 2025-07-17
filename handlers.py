# handlers.py

import re
import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext

def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "👋 Olá! Eu sou seu Bot de Rotina. "
        "Conte o que você quer fazer (por exemplo: “Esta semana quero estudar Python”) "
        "e eu ajudo você a organizar! 🚀"
    )

def help_command(update: Update, context: CallbackContext):
    update.message.reply_text(
        "✨ Mande frases livres como:\n"
        "- “Amanhã correr 7h”\n"
        "- “Quero estudar Python 5 vezes”\n\n"
        "Eu vou sugerir metas, agendar na sua Agenda Google e acompanhar o progresso."
    )

def handle_text(calendar_service, calendar_id):
    """
    Retorna uma função que processa toda mensagem de texto.
    Detecta metas e agendamentos e propõe ações via botões.
    """
    def _inner(update: Update, context: CallbackContext):
        text = update.message.text.lower()

        # 1. Proposta de Meta (ex: “Quero estudar Python”)
        if any(kw in text for kw in ["quero", "vou", "desejo", "pretendo"]):
            verb_match = re.search(r"(estudar|correr)\s*(.*)", text)
            if verb_match:
                action = verb_match.group(1)
                target = verb_match.group(2).strip() or action
                context.user_data['proposed_meta'] = target

                buttons = [
                    [
                        InlineKeyboardButton("Sim", callback_data="meta_yes"),
                        InlineKeyboardButton("Não", callback_data="meta_no")
                    ]
                ]
                keyboard = InlineKeyboardMarkup(buttons)
                update.message.reply_text(
                    f"🐾 Que demais! Quer que eu salve “{target}” como meta semanal?",
                    reply_markup=keyboard
                )
                return

        # 2. Proposta de Agendamento (ex: “Amanhã correr 7h”)
        time_match = re.search(r"(\d{1,2})(?:h|:)?(\d{0,2})", text)
        day_keyword = "amanhã" if "
