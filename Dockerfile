# backend/Dockerfile
FROM python:3.9-slim-buster

WORKDIR /app

# Instala dependências do sistema necessárias
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copia apenas os requirements primeiro para aproveitar cache Docker
COPY backend/requirements.txt .

# Instala dependências Python (inclui gunicorn e eventlet)
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir gunicorn==20.1.0 eventlet==0.33.3

# Copia o restante da aplicação
COPY . .

# Variáveis de ambiente
ENV FLASK_APP=backend.app
ENV FLASK_ENV=production
ENV PORT=5000
EXPOSE $PORT

# Comando de inicialização otimizado para SocketIO
CMD ["gunicorn", 
     "--worker-class", "eventlet",  # Critical for SocketIO
     "--bind", "0.0.0.0:5000", 
     "--timeout", "120", 
     "--reload",  # Apenas para desenvolvimento, remova para produção
     "--access-logfile", "-", 
     "--error-logfile", "-", 
     "backend.app:app"]
