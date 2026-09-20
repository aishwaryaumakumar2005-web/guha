import os
import sys
from app import create_app

print(f"BOOT[{os.getpid()}]: wsgi module import reached (python {sys.version.split()[0]})", flush=True)
app = create_app()
_db = app.config.get('SQLALCHEMY_DATABASE_URI', '?')
print(f"BOOT[{os.getpid()}]: create_app OK, db scheme={_db.split('://')[0]}, port env={os.environ.get('PORT', '')}", flush=True)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
