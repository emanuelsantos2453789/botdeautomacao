import json
from pathlib import Path

EVENTS_FILE = Path("data/events.json")
METAS_FILE = Path("data/metas.json")

def ensure_files():
    """Cria arquivos vazios se não existirem."""
    for file in [EVENTS_FILE, METAS_FILE]:
        file.parent.mkdir(exist_ok=True)
        if not file.exists():
            file.write_text("[]")

def record_event(event):
    """Salva informações básicas do evento criado em events.json."""
    ensure_files()
    data = json.loads(EVENTS_FILE.read_text())
    entry = {
        "id": event.get("id"),
        "summary": event.get("summary"),
        "start": event.get("start", {}).get("dateTime"),
        "created": datetime.utcnow().isoformat()
    }
    data.append(entry)
    EVENTS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))

def add_meta(text, dt):
    """Adiciona uma meta. dt pode ser None ou um deadline aproximado."""
    ensure_files()
    data = json.loads(METAS_FILE.read_text())
    entry = {"meta": text, "added": datetime.utcnow().isoformat(), "deadline": None}
    if dt:
        # Exemplo: usar data caso mencionada (pode refinar as metas semanais)
        entry["deadline"] = dt.isoformat()
    data.append(entry)
    METAS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
