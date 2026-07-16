import os
from dotenv import load_dotenv

load_dotenv()

_basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'change-this-in-production')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'connect_args': {'check_same_thread': False},
        'pool_pre_ping': True,
    }
    TEMPLATES_AUTO_RELOAD = False
    CRON_SECRET = os.environ.get('CRON_SECRET', 'change-me-in-production')


class DevConfig(Config):
    DEBUG = True
    _dev_db = f'sqlite:///{os.path.join(_basedir, "instance", "institute.db").replace(os.sep, "/")}'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or _dev_db


class ProdConfig(Config):
    DEBUG = False
    _db_url = os.environ.get('DATABASE_URL') or 'sqlite:///institute.db'
    SQLALCHEMY_DATABASE_URI = _db_url.replace('postgres://', 'postgresql://')


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
