import os
import json
import logging
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Escopos necessários para ler/escrever na Agenda
SCOPES = ['https://www.googleapis.com/auth/calendar']

def init_calendar_service():
    """
    Inicializa e retorna o serviço da Google Calendar API.
    **Prioriza o carregamento de credenciais.json para este teste.**
    """
    creds = None

    # Caminho para o arquivo credenciais.json
    local_path = os.path.join(os.path.dirname(__file__), 'credenciais.json')
    
    # 1) Tenta carregar do arquivo credenciais.json
    if os.path.isfile(local_path):
        try:
            creds = service_account.Credentials.from_service_account_file(
                local_path, scopes=SCOPES
            )
            logging.info("Google Calendar: credenciais carregadas de credenciais.json")
        except Exception as e:
            logging.error(f"Google Calendar: Falha ao carregar credenciais.json: {e}. Verifique o conteúdo do arquivo.")
            # Não retornar, o erro será propagado mais abaixo se 'creds' for None
    else:
        logging.error("Google Calendar: Arquivo credenciais.json NÃO ENCONTRADO no caminho esperado.")


    # 2) Se não conseguiu carregar as credenciais, levanta um erro claro
    if not creds:
        raise RuntimeError(
            "Não foi possível inicializar credenciais do Google Calendar. "
            "Verifique se o arquivo 'credenciais.json' existe na raiz do seu projeto "
            "e se o JSON dentro dele está correto e completo."
        )

    # 3) Constrói o serviço da API
    try:
        service = build('calendar', 'v3', credentials=creds)
        logging.info("Google Calendar: Serviço construído com sucesso.")
        return service
    except Exception as e:
        logging.error(f"Google Calendar: Erro ao construir o serviço da API: {e}")
        raise # Propaga o erro para o main

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
            'timeZone': os.getenv('TZ', 'America/Sao_Paulo') # Usar TZ para timezone
        },
        'end': {
            'dateTime': end_dt.isoformat(),
            'timeZone': os.getenv('TZ', 'America/Sao_Paulo')
        }
    }

    try:
        event = service.events().insert(
            calendarId=calendar_id,
            body=event_body
        ).execute()
        logging.info(f"Evento criado no Google Calendar: {event.get('htmlLink')}")
        return event
    except HttpError as error: # Captura erros específicos da API Google
        logging.error(f"Erro da API do Google Calendar ao criar evento: {error}")
        if error.resp.status == 401: # Unauthorized
            logging.error("Verifique as permissões da conta de serviço na sua agenda do Google.")
        elif error.resp.status == 404: # Not Found (calendar_id incorreto)
            logging.error(f"Calendar ID '{calendar_id}' não encontrado ou inacessível. Verifique o ID e as permissões.")
        raise # Relança o erro para ser capturado no handler do Telegram
    except Exception as e: # Captura outros erros
        logging.error(f"Erro inesperado ao criar evento no Google Calendar: {e}")
        raise # Relança o erro
