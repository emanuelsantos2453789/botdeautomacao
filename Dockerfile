# backend/Dockerfile
FROM python:3.9-slim

WORKDIR /app

# Instala dependências de sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

# Copia e instala requirements
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copia a aplicação
COPY . .

# Configurações de ambiente
ENV FLASK_APP=app.py
ENV FLASK_ENV=production
ENV PORT=5000
EXPOSE $PORT

# Comando de execução (versão simplificada e robusta)
CMD gunicorn --worker-class eventlet --bind 0.0.0.0:$PORT --access-logfile - --error-logfile - app:app
