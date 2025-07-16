import json
import os
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Escopos necessários para acesso ao Google Calendar
SCOPES = ['https://www.googleapis.com/auth/calendar']

def get_calendar_service():
    """Autentica e retorna o serviço do Google Calendar."""
    # Carrega credenciais do JSON de serviço do ambiente
    info = json.loads(os.environ['GOOGLE_KEY_JSON'])
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    service = build('calendar', 'v3', credentials=creds)
    return service

def create_event(summary, dt):
    """
    Cria um evento no Google Calendar.
    summary: string do evento, dt: datetime de início.
    Retorna o objeto do evento criado.
    """
    service = get_calendar_service()
    # Define hora de término como +1h por padrão
    end_dt = dt + timedelta(hours=1)
    event_body = {
        'summary': summary,
        'start': {'dateTime': dt.isoformat(), 'timeZone': 'America/Sao_Paulo'},
        'end': {'dateTime': end_dt.isoformat(), 'timeZone': 'America/Sao_Paulo'}
    }
    created_event = service.events().insert(calendarId='primary', body=event_body).execute()
    return created_event
