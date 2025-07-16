from fpdf import FPDF
from telegram.ext import CallbackContext

def generate_weekly_report(context: CallbackContext):
    """Gera e envia um relatório semanal em PDF via Telegram."""
    # Coleta dados (eventos e metas) - simplificado
    # Gera PDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, "Relatório Semanal de Metas e Eventos", ln=1, align='C')
    pdf.set_font("Arial", size=12)
    # Aqui inserir lógica de resumo. Exemplo estático:
    pdf.ln(10)
    pdf.multi_cell(0, 10, "• Metas conquistadas esta semana: ...\n• Eventos planejados realizados: ...\n")
    pdf.output("weekly_report.pdf")

    # Envia PDF pelo bot (para um chat específico ou canal)
    chat_id = os.environ.get("ADMIN_CHAT_ID")
    if chat_id:
        with open("weekly_report.pdf", "rb") as doc:
            context.bot.send_document(chat_id=chat_id, document=doc,
                                     caption="Seu relatório semanal! 📊")
