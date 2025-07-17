# jobs.py

import os
import json
import datetime
from io import BytesIO

from telegram import Bot, ParseMode
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import pandas as pd

DADOS_FILE = "dados.json"


def load_data():
    """Carrega o JSON de usuários/metas/tarefas."""
    if not os.path.exists(DADOS_FILE):
        return {}
    with open(DADOS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    """Salva o estado atual em dados.json."""
    with open(DADOS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def daily_feedback_job(context):
    """
    Envia, todo dia, um feedback para cada usuário:
      ✔ Tarefas concluídas
      ❌ Tarefas pendentes
      🎯 Progresso de metas
      🌟 Destaque do dia (usamos a última tarefa concluída como exemplo)
    """
    bot: Bot = context.bot
    data = load_data()

    for chat_id, user in data.items():
        feitas = [t for t in user.get("tarefas", []) if t.get("done")]
        pendentes = [t for t in user.get("tarefas", []) if not t.get("done")]

        # Formata mensagem
        msg = []
        msg.append(f"📋 *Resumo do Dia* ({datetime.date.today().strftime('%d/%m/%Y')}):")
        msg.append(f"✔️ Concluídas: {len(feitas)}")
        msg.append(f"❌ Pendentes: {len(pendentes)}")
        msg.append(f"🎯 Metas semanais:")
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
    """
    Gera um PDF com o resumo da semana e envia para cada usuário.
    """
    bot: Bot = context.bot
    data = load_data()

    for chat_id, user in data.items():
        # Prepara PDF em memória
        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        pdf.setTitle("Relatório Semanal")

        y = 800
        pdf.drawString(50, y, f"Relatório Semanal – Semana de {datetime.date.today():%d/%m/%Y}")
        y -= 30

        # Lista de metas
        pdf.drawString(50, y, "Metas Semanais:")
        y -= 20
        for m in user.get("metas", []):
            prog = m.get("progress", 0)
            alvo = m.get("target", 1)
            pdf.drawString(60, y, f"- {m['activity']}: {prog}/{alvo}")
            y -= 15

        # Lista de tarefas concluídas
        feitas = [t for t in user.get("tarefas", []) if t.get("done")]
        pdf.drawString(50, y, f"Tarefas concluídas ({len(feitas)}):")
        y -= 20
        for t in feitas[-10:]:  # últimos 10
            pdf.drawString(60, y, f"- {t['activity']} em {t['when']}")
            y -= 15

        pdf.showPage()
        pdf.save()
        buffer.seek(0)

        # Envia PDF
        bot.send_document(
            chat_id=int(chat_id),
            document=buffer,
            filename="relatorio_semanal.pdf"
        )


def weekly_backup_job(context):
    """
    Salva uma cópia dos dados em JSON e CSV toda segunda.
    """
    data = load_data()
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    # Backup JSON
    with open(f"backup_{timestamp}.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Backup CSV (metas e tarefas em planilhas separadas)
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

    # (Opcional) você pode subir esses arquivos para o Google Drive aqui

