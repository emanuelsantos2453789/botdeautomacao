import os
import json
import datetime
from io import BytesIO

from telegram import Bot
from telegram.constants import ParseMode
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import pandas as pd
import pytz

# Define o diretório da aplicação para garantir caminhos de arquivo corretos
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DADOS_FILE = os.path.join(APP_DIR, "dados.json")

# Define o fuso horário para as operações do seu bot
TIMEZONE = 'America/Sao_Paulo'
SAO_PAULO_TZ = pytz.timezone(TIMEZONE)


def load_data():
    if not os.path.exists(DADOS_FILE):
        return {}
    with open(DADOS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    with open(DADOS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# NOVO: Função para enviar o resumo diário (chamada toda noite às 20h)
async def send_daily_summary_job(context):
    bot: Bot = context.bot
    data = load_data()

    for chat_id, user_data in data.items():
        tarefas = user_data.setdefault("tarefas", [])
        
        now_aware = datetime.datetime.now(SAO_PAULO_TZ)
        today = now_aware.date()
        tomorrow = today + datetime.timedelta(days=1)

        # Filtra tarefas para o dia atual e para amanhã
        tasks_today = []
        tasks_tomorrow = []
        
        for task in tarefas:
            try:
                task_start_dt_naive = datetime.datetime.fromisoformat(task['start_when'])
                task_start_dt_aware = SAO_PAULO_TZ.localize(task_start_dt_naive)
                task_date = task_start_dt_aware.date()
            except ValueError:
                continue # Pula tarefas com datas inválidas

            if task_date == today and not task.get('done', False) and task_start_dt_aware > now_aware:
                tasks_today.append(task)
            elif task_date == tomorrow:
                tasks_tomorrow.append(task)

        msg_parts = []
        msg_parts.append(f"✨ *Seu Resumo Noturno* ({today.strftime('%d/%m/%Y')}):")
        msg_parts.append("\n_Prepare-se para um dia incrível!_")

        # Tarefas pendentes para hoje (se houver)
        if tasks_today:
            msg_parts.append("\n⏰ Tarefas que *ainda* estão pendentes para HOJE:")
            for t in sorted(tasks_today, key=lambda x: datetime.datetime.fromisoformat(x['start_when']).time()):
                start_time = datetime.datetime.fromisoformat(t['start_when']).strftime('%H:%M')
                msg_parts.append(f"• {t['activity']} às {start_time}")
        
        # Tarefas agendadas para amanhã
        if tasks_tomorrow:
            msg_parts.append(f"\n🗓️ *Sua agenda para AMANHÃ* ({tomorrow.strftime('%d/%m/%Y')}):")
            for t in sorted(tasks_tomorrow, key=lambda x: datetime.datetime.fromisoformat(x['start_when']).time()):
                start_time = datetime.datetime.fromisoformat(t['start_when']).strftime('%H:%M')
                end_time_str = ""
                if t.get('end_when'):
                    end_time_str = f" até {datetime.datetime.fromisoformat(t['end_when']).strftime('%H:%M')}"
                msg_parts.append(f"• {t['activity']} às {start_time}{end_time_str}")
        else:
            msg_parts.append("\n🎉 Nada agendado para amanhã ainda! Que tal planejar algo produtivo? 😉")

        msg_parts.append("\nLembre-se: Cada dia é uma nova chance de brilhar! ✨")

        try:
            await bot.send_message(
                chat_id=int(chat_id),
                text="\n".join(msg_parts),
                parse_mode=ParseMode.MARKDOWN
            )
            context.application.logger.info(f"Resumo diário enviado para {chat_id}.")
        except Exception as e:
            context.application.logger.error(f"Erro ao enviar resumo diário para {chat_id}: {e}", exc_info=True)


async def weekly_report_job(context):
    bot: Bot = context.bot
    data = load_data()

    # Pega a data de hoje no fuso horário especificado
    now_aware = datetime.datetime.now(SAO_PAULO_TZ)
    today = now_aware.date()
    # Calcula a data de 7 dias atrás para pegar a semana
    start_of_week = today - datetime.timedelta(days=today.weekday()) # Volta para a segunda-feira da semana atual
    if today.weekday() == 6: # Se for domingo, a semana começa há 6 dias
        start_of_week = today - datetime.timedelta(days=6)
    
    # Para o relatório semanal, considere a semana anterior completa
    # (por exemplo, de segunda a domingo da semana passada)
    # Se o job roda no domingo à noite, ele reporta a semana que está terminando.
    report_end_date = today
    report_start_date = report_end_date - datetime.timedelta(days=6) # Últimos 7 dias, incluindo hoje

    for chat_id, user in data.items():
        completed_tasks_week = []
        not_completed_tasks_week = []
        imprevistos_week = []
        weekly_score = 0
        total_score = user.get("score", 0)

        for task in user.get("tarefas", []):
            try:
                task_start_dt_naive = datetime.datetime.fromisoformat(task['start_when'])
                task_start_dt_aware = SAO_PAULO_TZ.localize(task_start_dt_naive)
                task_date = task_start_dt_aware.date()
            except ValueError:
                continue # Pula tarefas com datas inválidas

            if report_start_date <= task_date <= report_end_date:
                if task.get('completion_status') == 'completed_on_time' or task.get('completion_status') == 'completed_manually':
                    completed_tasks_week.append(task['activity'])
                    weekly_score += 10 # Se a tarefa foi concluída esta semana, soma os pontos
                elif task.get('completion_status') == 'not_completed':
                    not_completed_tasks_week.append(task['activity'])
                    if task.get('reason_not_completed'):
                        imprevistos_week.append(f"- *{task['activity']}*: {task['reason_not_completed']}")

        # --- Envio do resumo semanal via mensagem de texto (mais imediato e alegre) ---
        summary_message = f"🎉 *Seu Relatório Semanal de Brilho* ({report_start_date.strftime('%d/%m')} a {report_end_date.strftime('%d/%m')}): ✨\n\n"
        
        summary_message += "*📈 Metas da Semana:*\n"
        metas_exist = False
        for m in user.get("metas", []):
            metas_exist = True
            prog = m.get("progress", 0)
            target = m.get("target", 1)
            summary_message += f"• {m['activity']} ({prog}/{target})\n"
        if not metas_exist:
            summary_message += "Nenhuma meta definida esta semana. Que tal traçar novos horizontes? 🚀\n"

        summary_message += "\n*✅ Tarefas Concluídas:*\n"
        if completed_tasks_week:
            summary_message += "\n".join(f"• {t}" for t in completed_tasks_week) + "\n"
        else:
            summary_message += "Nenhuma tarefa concluída esta semana. Vamos planejar mais para a próxima! 💪\n"

        summary_message += "\n*❌ Tarefas Não Concluídas:*\n"
        if not_completed_tasks_week:
            summary_message += "\n".join(f"• {t}" for t in not_completed_tasks_week) + "\n"
        else:
            summary_message += "Todas as tarefas foram um sucesso! Que maravilha! 🎉\n"

        if imprevistos_week:
            summary_message += "\n*⚠️ Imprevistos e Desafios:*\n"
            summary_message += "\n".join(imprevistos_week) + "\n"

        summary_message += f"\n📊 *Pontuação da Semana*: *{weekly_score}* pontos!\n"
        summary_message += f"🏆 *Pontuação Total Acumulada*: *{total_score}* pontos!\n\n"
        summary_message += "Cada passo conta! Continue firme na sua jornada! Você é incrível! ✨"

        try:
            await bot.send_message(
                chat_id=int(chat_id),
                text=summary_message,
                parse_mode=ParseMode.MARKDOWN
            )
            context.application.logger.info(f"Relatório semanal em texto enviado para {chat_id}.")
        except Exception as e:
            context.application.logger.error(f"Erro ao enviar relatório semanal em texto para {chat_id}: {e}", exc_info=True)


        # --- Geração e envio do PDF (mantido como uma opção robusta de relatório) ---
        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        pdf.setTitle("Relatório Semanal de Produtividade")
        
        # Cores e fontes para um visual mais alegre
        pdf.setFillColorRGB(0.1, 0.4, 0.7) # Azul mais vibrante
        pdf.setFont("Helvetica-Bold", 24)
        pdf.drawString(50, 780, "🌟 Seu Relatório Semanal de Produtividade! 🌟")
        
        pdf.setFillColorRGB(0, 0, 0) # Preto
        pdf.setFont("Helvetica", 12)
        y = 750
        
        pdf.drawString(50, y, f"Período: {report_start_date.strftime('%d/%m/%Y')} a {report_end_date.strftime('%d/%m/%Y')}")
        y -= 25

        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(50, y, "📈 Metas da Semana:")
        y -= 20
        pdf.setFont("Helvetica", 12)
        for m in user.get("metas", []):
            if y < 100: pdf.showPage(); y = 780; pdf.setFont("Helvetica", 12) # Nova página se necessário
            pdf.drawString(60, y, f"• {m['activity']} (Progresso: {m.get('progress', 0)}/{m.get('target', 1)})")
            y -= 15
        if not metas_exist:
            if y < 100: pdf.showPage(); y = 780; pdf.setFont("Helvetica", 12)
            pdf.drawString(60, y, "Nenhuma meta definida esta semana. Que tal traçar novos horizontes?")
            y -= 15

        y -= 20
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(50, y, "✅ Tarefas Concluídas:")
        y -= 20
        pdf.setFont("Helvetica", 12)
        if completed_tasks_week:
            for t_desc in completed_tasks_week:
                if y < 100: pdf.showPage(); y = 780; pdf.setFont("Helvetica", 12)
                pdf.drawString(60, y, f"• {t_desc}")
                y -= 15
        else:
            if y < 100: pdf.showPage(); y = 780; pdf.setFont("Helvetica", 12)
            pdf.drawString(60, y, "Nenhuma tarefa concluída esta semana. Mas cada novo dia é uma oportunidade!")
            y -= 15

        y -= 20
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(50, y, "❌ Tarefas Não Concluídas:")
        y -= 20
        pdf.setFont("Helvetica", 12)
        if not_completed_tasks_week:
            for t_desc in not_completed_tasks_week:
                if y < 100: pdf.showPage(); y = 780; pdf.setFont("Helvetica", 12)
                pdf.drawString(60, y, f"• {t_desc}")
                y -= 15
        else:
            if y < 100: pdf.showPage(); y = 780; pdf.setFont("Helvetica", 12)
            pdf.drawString(60, y, "Todas as tarefas foram um sucesso! Mandou bem!")
            y -= 15

        if imprevistos_week:
            y -= 20
            pdf.setFont("Helvetica-Bold", 14)
            pdf.drawString(50, y, "⚠️ Imprevistos e Desafios:")
            y -= 20
            pdf.setFont("Helvetica", 12)
            for imp in imprevistos_week:
                if y < 100: pdf.showPage(); y = 780; pdf.setFont("Helvetica", 12)
                pdf.drawString(60, y, imp)
                y -= 15

        y -= 20
        pdf.setFont("Helvetica-Bold", 14)
        if y < 100: pdf.showPage(); y = 780; pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(50, y, f"📊 Pontuação da Semana: {weekly_score} pontos")
        y -= 20
        if y < 100: pdf.showPage(); y = 780; pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(50, y, f"🏆 Pontuação Total Acumulada: {total_score} pontos")
        y -= 30
        
        pdf.setFont("Helvetica-Oblique", 10)
        if y < 100: pdf.showPage(); y = 780; pdf.setFont("Helvetica-Oblique", 10)
        pdf.drawString(50, y, "Lembre-se: Cada passo, por menor que seja, te leva mais perto dos seus sonhos! Continue a brilhar! ✨")

        pdf.showPage()
        pdf.save()
        buffer.seek(0)

        try:
            await bot.send_document(
                chat_id=int(chat_id),
                document=buffer,
                filename=f"relatorio_semanal_{report_end_date.strftime('%Y%m%d')}.pdf",
                caption=f"🎉 Seu Relatório Semanal de Produtividade está aqui! {report_start_date.strftime('%d/%m')} a {report_end_date.strftime('%d/%m')}. 😉"
            )
            context.application.logger.info(f"Relatório semanal PDF enviado para {chat_id}.")
        except Exception as e:
            context.application.logger.error(f"Erro ao enviar relatório semanal PDF para {chat_id}: {e}", exc_info=True)


def weekly_backup_job(context):
    bot: Bot = context.bot # Adicionado para usar o logger do bot/application
    data = load_data()
    # Pega a hora atual no fuso horário especificado para o timestamp do backup
    timestamp = datetime.datetime.now(SAO_PAULO_TZ).strftime("%Y%m%d_%H%M")

    try:
        # Backup JSON para o diretório da aplicação
        backup_json_path = os.path.join(APP_DIR, f"backup_{timestamp}.json")
        with open(backup_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        context.application.logger.info(f"Backup JSON criado em {backup_json_path}")

        # Backup CSV para o diretório da aplicação
        rows = []
        for chat_id, user in data.items():
            for m in user.get("metas", []):
                rows.append({
                    "chat_id": chat_id,
                    "tipo": "meta",
                    "activity": m["activity"],
                    "progress": m.get("progress", 0),
                    "target": m.get("target", 1),
                    "start_when": None,
                    "end_when": None,
                    "done": None,
                    "completion_status": None,
                    "reason_not_completed": None
                })
            for t in user.get("tarefas", []):
                rows.append({
                    "chat_id": chat_id,
                    "tipo": "tarefa",
                    "activity": t["activity"],
                    "done": t.get("done", False),
                    "start_when": t.get("start_when", ""),
                    "end_when": t.get("end_when", ""),
                    "completion_status": t.get("completion_status", None),
                    "reason_not_completed": t.get("reason_not_completed", None),
                    "progress": None, # Não se aplica a tarefas
                    "target": None # Não se aplica a tarefas
                })

        df = pd.DataFrame(rows)
        backup_csv_path = os.path.join(APP_DIR, f"backup_{timestamp}.csv")
        df.to_csv(backup_csv_path, index=False)
        context.application.logger.info(f"Backup CSV criado em {backup_csv_path}")

        # Opcional: Enviar os backups para o usuário (se o contexto tiver chat_id)
        # Isso pode gerar muitos arquivos, então cuidado ao habilitar em produção.
        # Para fins de demonstração, não enviarei os backups para o usuário automaticamente.
        # Se quiser, pode adicionar:
        # for chat_id in data.keys(): # Envia para todos os usuários com dados
        #     await bot.send_document(chat_id=int(chat_id), document=open(backup_json_path, 'rb'), filename=os.path.basename(backup_json_path))
        #     await bot.send_document(chat_id=int(chat_id), document=open(backup_csv_path, 'rb'), filename=os.path.basename(backup_csv_path))

    except Exception as e:
        context.application.logger.error(f"Erro ao realizar o backup semanal: {e}", exc_info=True)
