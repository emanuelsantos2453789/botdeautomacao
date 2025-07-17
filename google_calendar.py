# google_calendar.py

import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Escopos necessários para ler/escrever na Agenda
SCOPES = ['https://www.googleapis.com/auth/calendar']

def init_calendar_service():
    """
    Inicializa e retorna o serviço da Google Calendar API.
    Tenta ler as credenciais de uma variável de ambiente JSON ou
    do arquivo 'credenciais.json' na raiz do projeto.
    """
    creds = None

    # 1) A partir de variável de ambiente (opcional)
    creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
    if creds_json:
        data = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(
            data, scopes=SCOPES
        )
    else:
        # 2) A partir do arquivo local
        creds = service_account.Credentials.from_service_account_file(
            'credenciais.json', scopes=SCOPES
        )

    service = build('calendar', 'v3', credentials=creds)
    return service

def create_event(service, calendar_id, summary, start_dt, end_dt, description=None):
    """
    Cria um evento na Google Agenda.
    - service: instância retornada por init_calendar_service()
    - calendar_id: ID da agenda (ex: user@gmail.com)
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

    created_event = service.events().insert(
        calendarId=calendar_id,
        body=event_body
    ).execute()
    return created_event

