# Dockerfile
# Usa uma imagem oficial do Python como base
FROM python:3.9-slim-buster

# Define o diretório de trabalho dentro do container
WORKDIR /app

# Copia o arquivo de requisitos e instala as dependências
# Isso aproveita o cache do Docker: se requirements.txt não mudar, não reinstala
COPY backend/requeriments.txt .
RUN pip install --no-cache-dir -r requeriments.txt

# Copia todo o restante do seu código para o diretório de trabalho
COPY . .

# Define a porta que a aplicação vai escutar. O Railway vai injetar sua própria PORT,
# mas 5000 é um bom valor padrão para desenvolvimento e para o comando CMD.
ENV PORT=5000
EXPOSE $PORT

# Comando para rodar a aplicação usando Gunicorn.
# 'backend.app:app' significa: no módulo backend/app.py, encontre a instância 'app'.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "backend.app:app"]
