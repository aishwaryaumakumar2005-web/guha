import os, sys
print("=== WSGI START ===", flush=True)
print("CWD:", os.getcwd(), flush=True)
print("DIRS:", [d for d in os.listdir('.') if os.path.isdir(d)], flush=True)
print("FILES:", [f for f in os.listdir('.') if f.endswith('.py')][:10], flush=True)
print("HAS app/__init__:", os.path.isfile('app/__init__.py'), flush=True)
print("FLASK_ENV:", os.environ.get('FLASK_ENV'), flush=True)
print("DATABASE_URL:", os.environ.get('DATABASE_URL'), flush=True)

from app import create_app

app = create_app()
print("=== WSGI END ===", flush=True)
