# google_calendar.py
import os
import json
import logging
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError # Importar para capturar erros específicos da API

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
            logging.error(f"Google Calendar: Falha ao carregar credenciais.json: {e}")
            # Não retornar, tentar a próxima opção

    # 2) Se ainda não tiver credenciais, tenta a variável de ambiente
    if not creds:
        raw = os.getenv('GOOGLE_CREDENTIALS_JSON', '').strip()
        if raw:
            try:
                # É crucial que raw seja um JSON válido e em uma única linha se for de variável de ambiente
                data = json.loads(raw)
                creds = service_account.Credentials.from_service_account_info(
                    data, scopes=SCOPES
                )
                logging.info("Google Calendar: credenciais carregadas de variável de ambiente")
            except json.JSONDecodeError as je:
                logging.error(f"Google Calendar: GOOGLE_CREDENTIALS_JSON não é JSON válido: {je}")
            except Exception as e:
                logging.error(f"Google Calendar: Erro criando credenciais de serviço: {e}")

    # 3) Se ainda não conseguiu, aborta com erro claro
    if not creds:
        raise RuntimeError(
            "Não foi possível inicializar credenciais do Google Calendar. "
            "Verifique se credenciais.json existe ou se a variável GOOGLE_CREDENTIALS_JSON está correta."
        )

    # 4) Constrói o serviço
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
