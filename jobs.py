# jobs.py

import os
import json
import datetime
from io import BytesIO

from telegram import Bot
from telegram.constants import ParseMode
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import pandas as pd

DADOS_FILE = "dados.json"


def load_data():
    if not os.path.exists(DADOS_FILE):
        return {}
    with open(DADOS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    with open(DADOS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def daily_feedback_job(context):
    bot: Bot = context.bot
    data = load_data()

    for chat_id, user in data.items():
        feitas = [t for t in user.get("tarefas", []) if t.get("done")]
        pendentes = [t for t in user.get("tarefas", []) if not t.get("done")]

        msg = []
        msg.append(f"📋 *Resumo do Dia* ({datetime.date.today():%d/%m/%Y}):")
        msg.append(f"✔️ Concluídas: {len(feitas)}")
        msg.append(f"❌ Pendentes: {len(pendentes)}")
        msg.append("🎯 Metas semanais:")
        for m in user.get("metas", []):
            prog = m.get("progress", 0)
            alvo = m.get("target", 1)
            barras = "✅" * prog + "❌" * (alvo - prog)
            msg.append(f"   • {m['activity']}: {prog}/{alvo} {barras}")

        destaque = feitas[-1]["activity"] if feitas else "—"
        msg.append(f"🌟 Destaque do dia: {destaque}")

        bot.send_message(
            chat_id=int(chat_id),
            text="\n".join(msg),
            parse_mode=ParseMode.MARKDOWN
        )


def weekly_report_job(context):
    bot: Bot = context.bot
    data = load_data()

    for chat_id, user in data.items():
        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        pdf.setTitle("Relatório Semanal")

        y = 800
        pdf.drawString(50, y, f"Relatório Semanal – Semana de {datetime.date.today():%d/%m/%Y}")
        y -= 30

        pdf.drawString(50, y, "Metas Semanais:")
        y -= 20
        for m in user.get("metas", []):
            prog = m.get("progress", 0)
            alvo = m.get("target", 1)
            pdf.drawString(60, y, f"- {m['activity']}: {prog}/{alvo}")
            y -= 15

        feitas = [t for t in user.get("tarefas", []) if t.get("done")]
        pdf.drawString(50, y, f"Tarefas concluídas ({len(feitas)}):")
        y -= 20
        for t in feitas[-10:]:
            pdf.drawString(60, y, f"- {t['activity']} em {t['when']}")
            y -= 15

        pdf.showPage()
        pdf.save()
        buffer.seek(0)

        bot.send_document(
            chat_id=int(chat_id),
            document=buffer,
            filename="relatorio_semanal.pdf"
        )


def weekly_backup_job(context):
    data = load_data()
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")

    # Backup JSON
    with open(f"backup_{timestamp}.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Backup CSV
    rows = []
    for chat_id, user in data.items():
        for m in user.get("metas", []):
            rows.append({
                "chat_id": chat_id,
                "tipo": "meta",
                "activity": m["activity"],
                "progress": m["progress"],
                "target": m["target"]
            })
        for t in user.get("tarefas", []):
            rows.append({
                "chat_id": chat_id,
                "tipo": "tarefa",
                "activity": t["activity"],
                "done": t.get("done", False),
                "when": t.get("when", "")
            })

    df = pd.DataFrame(rows)
    df.to_csv(f"backup_{timestamp}.csv", index=False)
