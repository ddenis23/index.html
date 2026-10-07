"""Acces la Firebase Realtime Database.

Trei implementari cu aceeasi interfata:
- `RestBackend`: baza reala, prin REST, autentificat cu un service account
  (ocoleste regulile Firebase, deci baza poate fi inchisa pentru public);
- `JsonFileBackend`: o copie locala (fisier JSON), pentru dezvoltare;
- `MemoryBackend`: pentru teste.

Semantica e cea din Firebase: a scrie `None` sterge cheia, iar nodurile
ramase goale dispar.
"""

import copy
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from django.conf import settings


class FirebaseError(Exception):
    pass


def _parts(path):
    return [p for p in path.strip('/').split('/') if p]


def _prune(value):
    """Imita Firebase: elimina None si dictionarele goale."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            v = _prune(v)
            if v is not None:
                out[str(k)] = v
        return out or None
    if isinstance(value, list):
        return _prune({str(i): v for i, v in enumerate(value)})
    return value


class MemoryBackend:
    def __init__(self, data=None):
        self.data = _prune(copy.deepcopy(data)) or {}
        self.lock = threading.Lock()
        self._counter = 0

    def _read(self, path):
        node = self.data
        for p in _parts(path):
            if not isinstance(node, dict) or p not in node:
                return None
            node = node[p]
        return copy.deepcopy(node)

    def _write(self, path, value):
        parts = _parts(path)
        if not parts:
            self.data = _prune(value) or {}
            return
        stack, node = [], self.data
        for p in parts[:-1]:
            if not isinstance(node.get(p), dict):
                node[p] = {}
            stack.append((node, p))
            node = node[p]
        value = _prune(copy.deepcopy(value))
        if value is None:
            node.pop(parts[-1], None)
        else:
            node[parts[-1]] = value
        for parent, key in reversed(stack):  # sterge parintii ramasi goi
            if parent[key] == {}:
                del parent[key]

    def get(self, path):
        with self.lock:
            return self._read(path)

    def get_many(self, paths):
        with self.lock:
            return [self._read(p) for p in paths]

    def set(self, path, value):
        with self.lock:
            self._write(path, value)
            self._saved()

    def update(self, path, values):
        """Update multi-path, atomic: cheile pot fi cai relative (`a/b`)."""
        base = path.strip('/')
        with self.lock:
            for key, value in values.items():
                self._write(f'{base}/{key}' if base else key, value)
            self._saved()

    def push(self, path, value):
        import time
        with self.lock:
            self._counter += 1
            key = f'{int(time.time() * 1000):013d}{self._counter:06d}'
            self._write(f'{path}/{key}', value)
            self._saved()
        return key

    def last(self, path, limit):
        node = self.get(path) or {}
        keys = sorted(node)[-limit:]
        return {k: node[k] for k in keys}

    def _saved(self):
        pass


class JsonFileBackend(MemoryBackend):
    def __init__(self, path):
        self.path = Path(path)
        super().__init__(json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {})

    def _saved(self):
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding='utf-8')
        tmp.replace(self.path)


class RestBackend:
    SCOPES = ['https://www.googleapis.com/auth/firebase.database',
              'https://www.googleapis.com/auth/userinfo.email']

    def __init__(self, url, service_account_info):
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_info(service_account_info, scopes=self.SCOPES)
        self.session = AuthorizedSession(creds)
        self.url = url.rstrip('/')
        self.pool = ThreadPoolExecutor(max_workers=6)

    def _req(self, method, path, params=None, body=None):
        import requests
        try:
            resp = self.session.request(method, f'{self.url}/{path.strip("/")}.json', params=params,
                                        data=None if body is None else json.dumps(body), timeout=20)
        except requests.RequestException as exc:
            raise FirebaseError(f'Nu se poate conecta la Firebase: {exc}') from exc
        if resp.status_code >= 400:
            raise FirebaseError(f'Firebase {resp.status_code}: {resp.text[:200]}')
        return resp.json()

    def get(self, path):
        return self._req('GET', path)

    def get_many(self, paths):
        return list(self.pool.map(self.get, paths))

    def set(self, path, value):
        if value is None:
            self._req('DELETE', path)
        else:
            self._req('PUT', path, body=value)

    def update(self, path, values):
        self._req('PATCH', path, body=values)

    def push(self, path, value):
        return self._req('POST', path, body=value)['name']

    def last(self, path, limit):
        return self._req('GET', path, params={'orderBy': '"$key"', 'limitToLast': limit}) or {}


_backend = None
_backend_lock = threading.Lock()


def backend():
    global _backend
    if _backend is None:
        with _backend_lock:
            if _backend is None:
                _backend = _create()
    return _backend


def use_backend(instance):
    """Pentru teste: inlocuieste backend-ul curent."""
    global _backend
    _backend = instance


def _create():
    raw = os.environ.get('FIREBASE_SERVICE_ACCOUNT')
    file = os.environ.get('FIREBASE_SERVICE_ACCOUNT_FILE')
    if raw or file:
        info = json.loads(raw) if raw else json.loads(Path(file).read_text(encoding='utf-8'))
        return RestBackend(settings.FIREBASE_DB_URL, info)
    local = os.environ.get('FIREBASE_LOCAL_FILE')
    if local:
        return JsonFileBackend(local)
    raise FirebaseError(
        'Firebase neconfigurat: seteaza FIREBASE_SERVICE_ACCOUNT (productie) '
        'sau FIREBASE_LOCAL_FILE (copie locala pentru dezvoltare).')
