import dateparser
from datetime import datetime

def parse_date_from_text(text):
    """Retorna um objeto datetime se encontrar uma data/hora no texto."""
    dt = dateparser.parse(text, languages=['pt'])
    return dt

def format_datetime(dt: datetime):
    """Formata datetime para string legível."""
    return dt.strftime("%d/%m/%Y %H:%M")
