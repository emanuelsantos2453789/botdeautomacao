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
        tasks_today_pending = []
        tasks_tomorrow_scheduled = []
        
        for task in tarefas:
            try:
                task_start_dt_naive = datetime.datetime.fromisoformat(task['start_when'])
                task_start_dt_aware = SAO_PAULO_TZ.localize(task_start_dt_naive)
                task_date = task_start_dt_aware.date()
            except (ValueError, TypeError):
                context.application.logger.warning(f"Data de início inválida para a tarefa: {task.get('activity')}. Pulando.")
                continue

            # Tarefas de hoje que ainda não foram concluídas e que o tempo ainda não passou (ou passou muito pouco)
            if task_date == today and not task.get('done', False) and (task_start_dt_aware > now_aware - datetime.timedelta(hours=12)): # Considera 12h para "atrasadas" no resumo noturno
                tasks_today_pending.append(task)
            # Tarefas agendadas para amanhã
            elif task_date == tomorrow:
                tasks_tomorrow_scheduled.append(task)

        msg_parts = []
        msg_parts.append(f"✨ *Seu Resumo Noturno* ({today.strftime('%d/%m/%Y')}):")
        msg_parts.append("\n_Prepare-se para um dia incrível!_")

        if tasks_today_pending:
            msg_parts.append("\n⏰ Tarefas que *ainda* estão pendentes para HOJE:")
            for t in sorted(tasks_today_pending, key=lambda x: datetime.datetime.fromisoformat(x['start_when']).time()):
                start_time = datetime.datetime.fromisoformat(t['start_when']).strftime('%H:%M')
                msg_parts.append(f"• {t['activity']} às {start_time}")
        
        if tasks_tomorrow_scheduled:
            msg_parts.append(f"\n🗓️ *Sua agenda para AMANHÃ* ({tomorrow.strftime('%d/%m/%Y')}):")
            for t in sorted(tasks_tomorrow_scheduled, key=lambda x: datetime.datetime.fromisoformat(x['start_when']).time()):
                start_time = datetime.datetime.fromisoformat(t['start_when']).strftime('%H:%M')
                end_time_str = ""
                if t.get('end_when'):
                    try:
                        end_time_str = f" até {datetime.datetime.fromisoformat(t['end_when']).strftime('%H:%M')}"
                    except (ValueError, TypeError):
                        pass # Ignora se a data de fim for inválida
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

    now_aware = datetime.datetime.now(SAO_PAULO_TZ)
    today = now_aware.date()
    
    # Reporta a semana *que terminou* (do domingo passado até hoje)
    report_end_date = today
    report_start_date = report_end_date - datetime.timedelta(days=6)

    for chat_id, user in data.items():
        completed_tasks_week = []
        not_completed_tasks_week = []
        imprevistos_week = []
        weekly_score_contribution = 0 # Pontos ganhos *nesta semana*
        total_score = user.get("score", 0)

        for task in user.get("tarefas", []):
            try:
                task_start_dt_naive = datetime.datetime.fromisoformat(task['start_when'])
                task_start_dt_aware = SAO_PAULO_TZ.localize(task_start_dt_naive)
                task_date = task_start_dt_aware.date()
            except (ValueError, TypeError):
                continue

            if report_start_date <= task_date <= report_end_date:
                if task.get('completion_status') == 'completed_on_time' or task.get('completion_status') == 'completed_manually':
                    completed_tasks_week.append(task['activity'])
                    # Assumimos 10 pontos por tarefa concluída. Isso precisa ser consistente.
                    # Se você armazenar os pontos ganhos por tarefa, some isso aqui.
                    # Por enquanto, vou manter a lógica de 10 pontos fixos por tarefa concluída na semana.
                    weekly_score_contribution += 10 
                elif task.get('completion_status') == 'not_completed':
                    not_completed_tasks_week.append(task['activity'])
                    if task.get('reason_not_completed'):
                        imprevistos_week.append(f"- *{task['activity']}*: {task['reason_not_completed']}")

        # --- Envio do resumo semanal via mensagem de texto ---
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

        summary_message += f"\n📊 *Pontuação da Semana*: *{weekly_score_contribution}* pontos!\n"
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
        
        pdf.setFillColorRGB(0.1, 0.4, 0.7)
        pdf.setFont("Helvetica-Bold", 24)
        pdf.drawString(50, 780, "🌟 Seu Relatório Semanal de Produtividade! 🌟")
        
        pdf.setFillColorRGB(0, 0, 0)
        pdf.setFont("Helvetica", 12)
        y = 750
        
        pdf.drawString(50, y, f"Período: {report_start_date.strftime('%d/%m/%Y')} a {report_end_date.strftime('%d/%m/%Y')}")
        y -= 25

        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(50, y, "📈 Metas da Semana:")
        y -= 20
        pdf.setFont("Helvetica", 12)
        for m in user.get("metas", []):
            if y < 100: pdf.showPage(); y = 780; pdf.setFont("Helvetica", 12)
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
        pdf.drawString(50, y, f"📊 Pontuação da Semana: {weekly_score_contribution} pontos")
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
    bot: Bot = context.bot
    data = load_data()
    timestamp = datetime.datetime.now(SAO_PAULO_TZ).strftime("%Y%m%d_%H%M")

    try:
        backup_json_path = os.path.join(APP_DIR, f"backup_{timestamp}.json")
        with open(backup_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        context.application.logger.info(f"Backup JSON criado em {backup_json_path}")

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
                    "reason_not_completed": None,
                    "job_names": None # Não se aplica a metas
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
                    "progress": None,
                    "target": None,
                    "job_names": json.dumps(t.get("job_names", [])) if t.get("job_names") else "[]" # Salva como string JSON
                })

        df = pd.DataFrame(rows)
        backup_csv_path = os.path.join(APP_DIR, f"backup_{timestamp}.csv")
        df.to_csv(backup_csv_path, index=False)
        context.application.logger.info(f"Backup CSV criado em {backup_csv_path}")

    except Exception as e:
        context.application.logger.error(f"Erro ao realizar o backup semanal: {e}", exc_info=True)

# NOVO: Job para limpar tarefas antigas/concluídas do JSON
async def clean_up_old_tasks_job(context):
    data = load_data()
    now_aware = datetime.datetime.now(SAO_PAULO_TZ)
    
    tasks_cleaned_count = 0
    for chat_id, user_data in data.items():
        if "tarefas" in user_data:
            # Mantém apenas as tarefas que não estão 'done' ou que são recentes (últimos 30 dias)
            # Remove tarefas concluídas que sejam mais antigas que 7 dias
            # Remove tarefas não concluídas que sejam mais antigas que 30 dias
            
            # Ajustei a lógica de remoção:
            # Se uma tarefa estiver "done", ela é mantida por 7 dias. Após isso, é removida.
            # Se uma tarefa não estiver "done" e o horário de fim (ou início se não tiver fim) já passou há mais de 30 dias, é removida.
            # Tarefas recorrentes que não foram "done" mas já passaram, serão mantidas na lista de não-concluídas, mas seu job será removido.
            
            updated_tasks = []
            for task in user_data["tarefas"]:
                try:
                    task_start_dt_naive = datetime.datetime.fromisoformat(task['start_when'])
                    task_dt_aware = SAO_PAULO_TZ.localize(task_start_dt_naive)
                    
                    # Calcula a data de referência para remoção
                    reference_date = task_dt_aware
                    if task.get('end_when'):
                        end_dt_naive = datetime.datetime.fromisoformat(task['end_when'])
                        end_dt_aware = SAO_PAULO_TZ.localize(end_dt_naive)
                        reference_date = end_dt_aware
                        
                    if task.get('done', False):
                        # Se concluída, remove se tiver mais de 7 dias
                        if (now_aware - reference_date).days > 7:
                            tasks_cleaned_count += 1
                            # Não precisamos cancelar jobs aqui, eles já deveriam ter rodado ou sido cancelados ao marcar como done
                            continue # Não adiciona à lista
                    elif task.get('completion_status') == 'not_completed':
                        # Se não concluída, remove se tiver mais de 30 dias
                        if (now_aware - reference_date).days > 30:
                            tasks_cleaned_count += 1
                            continue # Não adiciona à lista
                    elif reference_date < now_aware - datetime.timedelta(days=30):
                         # Tarefas pendentes muito antigas (mais de 30 dias atrás) que não foram marcadas
                         tasks_cleaned_count += 1
                         continue
                         
                except (ValueError, TypeError):
                    context.application.logger.warning(f"Tarefa com data inválida encontrada durante a limpeza: {task.get('activity')}. Removendo.")
                    tasks_cleaned_count += 1
                    continue # Remove tarefas com datas inválidas
                
                updated_tasks.append(task)
            user_data["tarefas"] = updated_tasks
    
    if tasks_cleaned_count > 0:
        save_data(data)
        context.application.logger.info(f"Limpeza de tarefas concluída. {tasks_cleaned_count} tarefas antigas foram removidas.")
    else:
        context.application.logger.info("Nenhuma tarefa antiga para limpar.")
