"""
main.py
=======
Entry point utama — jalankan Facebook Scraper API dengan uvicorn (ASGI).
Port dan host dibaca dari backend/.env (FB_API_PORT, FB_API_HOST).

Usage:
    # Dari folder project root:
    cd backend
    python main.py

    # Atau langsung dengan uvicorn:
    cd backend
    ..\\venv\\Scripts\\uvicorn main:asgi_app --host 0.0.0.0 --port 8003
"""

import os
import sys

# Pastikan folder backend ada di sys.path agar semua import engine bekerja
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(_HERE, ".env"))

import uvicorn
from asgiref.wsgi import WsgiToAsgi

# FIX: import Flask dulu untuk type hint yang proper, lalu import flask_app
# Pylance tidak bisa resolve 'app' dari modul dinamis — pakai importlib agar
# attribute access jelas dan bisa di-type-check dengan benar.
import importlib
from flask import Flask

_server_module = importlib.import_module("facebook_api_server")
flask_app: Flask = _server_module.app  # type: ignore[attr-defined]

HOST = os.getenv("FB_API_HOST", "0.0.0.0")
PORT = int(os.getenv("FB_API_PORT", "8003"))

# Wrap Flask WSGI → ASGI untuk uvicorn
asgi_app = WsgiToAsgi(flask_app)

if __name__ == "__main__":
    print("=" * 62)
    print("  FB Scraper API  —  uvicorn  (backend/main.py)")
    print(f"  .env   : backend/.env")
    print(f"  Host   : {HOST}:{PORT}")
    print(f"  URL    : http://localhost:{PORT}")
    print(f"  Health : http://localhost:{PORT}/api/v1/health")
    print("=" * 62)
    uvicorn.run(
        "main:asgi_app",
        host=HOST,
        port=PORT,
        reload=False,
        workers=1,
        log_level="info",
        timeout_keep_alive=300,
    )