from app import create_app
import os

app = create_app()

if __name__ == '__main__':
    debug = os.environ.get('FLASK_ENV', '').lower() == 'development'
    # Disable the reloader to keep a single process so tracebacks print reliably
    app.run(debug=debug, port=5000, use_reloader=False)
