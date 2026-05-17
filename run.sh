#!/usr/bin/env bash
set -e

CERT_DIR="$(dirname "$0")/certs"
KEY="$CERT_DIR/key.pem"
CERT="$CERT_DIR/cert.pem"

if [ ! -f "$KEY" ] || [ ! -f "$CERT" ]; then
    echo "🔐 Generando certificado SSL autofirmado..."
    mkdir -p "$CERT_DIR"
    openssl req -x509 -newkey rsa:4096 -keyout "$KEY" -out "$CERT" \
        -days 365 -nodes \
        -subj "/CN=localhost" \
        -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
    echo "✅ Certificado generado en $CERT_DIR/"
fi

VENV_DIR="$(dirname "$0")/venv"
if [ -f "$VENV_DIR/bin/activate" ]; then
    source "$VENV_DIR/bin/activate"
fi

pip install -q -r "$(dirname "$0")/requirements.txt"

echo "🚀 Servidor corriendo en https://localhost:8000"
uvicorn main:app --host 0.0.0.0 --port 8000 \
    --ssl-keyfile "$KEY" --ssl-certfile "$CERT" \
    --reload
