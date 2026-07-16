import os
from dotenv import load_dotenv

load_dotenv()

_basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'change-this-in-production')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {'pool_pre_ping': True}
    TEMPLATES_AUTO_RELOAD = False
    CRON_SECRET = os.environ.get('CRON_SECRET', 'change-me-in-production')


class DevConfig(Config):
    DEBUG = True
    _dev_db = f'sqlite:///{os.path.join(_basedir, "instance", "institute.db").replace(os.sep, "/")}'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or _dev_db


class ProdConfig(Config):
    DEBUG = False
    _raw = (os.environ.get('DATABASE_URL') or 'sqlite:///institute.db').strip().strip('"').strip("'")
    if _raw.startswith('postgres://'):
        _raw = 'postgresql' + _raw[len('postgres'):]
    try:
        from urllib.parse import urlparse, quote
        parsed = urlparse(_raw)
        if parsed.password:
            netloc = f"{parsed.username}:{quote(parsed.password, safe='')}@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            _raw = _raw.replace(f"{parsed.username}:{parsed.password}@{parsed.hostname}", netloc, 1)
    except Exception:
        pass
    SQLALCHEMY_DATABASE_URI = _raw


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
