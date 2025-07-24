# backend/Dockerfile
# Estágio de construção
FROM python:3.9-slim as builder

# Instala dependências de sistema necessárias
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

# Cria e ativa virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Instala dependências Python
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# --- Estágio final ---
FROM python:3.9-slim

# Copia o virtual env do estágio builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copia o código da aplicação
WORKDIR /app
COPY backend .

# Configurações de ambiente
ENV FLASK_APP=app.py
ENV FLASK_ENV=production
ENV PORT=5000
EXPOSE $PORT

# Comando de execução otimizado
CMD ["gunicorn", \
    "--worker-class", "eventlet", \
    "--bind", "0.0.0.0:5000", \
    "--timeout", "120", \
    "--access-logfile", "-", \
    "--error-logfile", "-", \
    "app:app"]
