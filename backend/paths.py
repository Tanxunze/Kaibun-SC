"""Resolve all local configuration and writable state from one project root."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def project_path(value):
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()

def data_root():
    return project_path(os.environ.get('KAIBUN_DATA_PATH') or 'data')

def characters_path_from_env():
    return project_path(os.environ.get('KAIBUN_CHARACTERS_PATH') or 'characters/characters.toml')

def load_environment():
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')

def runtime_connection(token=None):
    import json
    import secrets
    token = token or os.environ.get('KAIBUN_API_TOKEN') or secrets.token_urlsafe(32)
    directory = ROOT / '.runtime'
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / 'connection.json'
    path.write_text(json.dumps({'url': 'http://127.0.0.1:' + os.environ.get('KAIBUN_PORT', '8011'), 'token': token}), encoding='utf-8')
    path.chmod(0o600)
    return token
