# backend/Dockerfile
# Estágio de construção
FROM python:3.9-slim as builder

WORKDIR /app

# 1. Instala dependências de sistema necessárias
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    default-libmysqlclient-dev \  # Para MySQL/PyMySQL
    && rm -rf /var/lib/apt/lists/*

# 2. Cria e ativa virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 3. Instala dependências Python
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# --- Estágio final ---
FROM python:3.9-slim

WORKDIR /app

# 4. Copia o virtual env do estágio builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 5. Copia apenas o necessário
COPY backend/. .

# 6. Configurações de ambiente
ENV FLASK_APP=app.py
ENV FLASK_ENV=production
ENV PORT=5000
EXPOSE $PORT

# 7. Comando de execução otimizado
CMD ["gunicorn", \
    "--worker-class", "eventlet", \
    "--bind", "0.0.0.0:5000", \
    "--timeout", "120", \
    "--workers", "2", \
    "--access-logfile", "-", \
    "--error-logfile", "-", \
    "app:app"]
