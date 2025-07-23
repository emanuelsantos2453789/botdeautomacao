# backend/app.py
from flask import Flask, send_from_directory
import os

app = Flask(__name__, static_folder='../frontend', static_url_path='/')

# Rota para a página inicial
@app.route('/')
def serve_index():
    return send_from_directory(app.static_folder, 'index.html')

# Opcional: Rotas para servir outros arquivos estáticos (CSS, JS)
# Flask já faz isso automaticamente com static_folder, mas é bom ter em mente
# para casos mais complexos. Para este exemplo simples, 'static_url_path='/' já resolve.

if __name__ == '__main__':
    # Obtém a porta do ambiente (Railway fornece a variável PORT)
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
