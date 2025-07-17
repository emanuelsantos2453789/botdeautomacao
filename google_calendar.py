# google_calendar.py

import os
import json
import logging
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Escopos necessários para ler/escrever na Agenda
SCOPES = ['https://www.googleapis.com/auth/calendar']

def init_calendar_service():
    """
    Inicializa e retorna o serviço da Google Calendar API.
    1) Carrega de credenciais.json se existir.
    2) Senão, tenta usar a variável GOOGLE_CREDENTIALS_JSON.
    """
    creds = None

    # 1) Se o arquivo credenciais.json estiver presente, usa ele
    local_path = os.path.join(os.path.dirname(__file__), 'credenciais.json')
    if os.path.isfile(local_path):
        try:
            creds = service_account.Credentials.from_service_account_file(
                local_path, scopes=SCOPES
            )
            logging.info("Google Calendar: credenciais carregadas de credenciais.json")
        except Exception as e:
            logging.error(f"Falha ao carregar credenciais.json: {e}")

    # 2) Se ainda não tiver credenciais, tenta a variável de ambiente
    if not creds:
        raw = os.getenv('GOOGLE_CREDENTIALS_JSON', '').strip()
        if raw:
            try:
                data = json.loads(raw)
                creds = service_account.Credentials.from_service_account_info(
                    data, scopes=SCOPES
                )
                logging.info("Google Calendar: credenciais carregadas de variável de ambiente")
            except json.JSONDecodeError as je:
                logging.error("GOOGLE_CREDENTIALS_JSON não é JSON válido")
            except Exception as e:
                logging.error(f"Erro criando credenciais de serviço: {e}")

    # 3) Se ainda não conseguiu, aborta com erro claro
    if not creds:
        raise RuntimeError(
            "Não foi possível inicializar credenciais do Google Calendar. "
            "Verifique se credenciais.json existe ou se a variável GOOGLE_CREDENTIALS_JSON está correta."
        )

    # 4) Constrói o serviço
    service = build('calendar', 'v3', credentials=creds)
    return service


def create_event(service, calendar_id, summary, start_dt, end_dt, description=None):
    """
    Cria um evento na Google Agenda.
    - service: instância retornada por init_calendar_service()
    - calendar_id: ID da agenda (ex: user@gmail.com ou 'primary')
    - summary: título do evento
    - start_dt, end_dt: datetime.datetime
    - description: texto opcional
    """
    event_body = {
        'summary': summary,
        'description': description or '',
        'start': {
            'dateTime': start_dt.isoformat(),
            'timeZone': os.getenv('TZ', 'America/Sao_Paulo')
        },
        'end': {
            'dateTime': end_dt.isoformat(),
            'timeZone': os.getenv('TZ', 'America/Sao_Paulo')
        }
    }

    return service.events().insert(
        calendarId=calendar_id,
        body=event_body
    ).execute()
