"""Autentificare cu conturile din Firebase (`utilizatori/`).

Sesiunea (cookie semnat) tine username-ul si o amprenta a hash-ului parolei:
daca parola e schimbata sau contul dezactivat, sesiunile vechi expira.
"""

import hashlib
import hmac
import logging
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.functional import SimpleLazyObject

from . import store
from .firebase import FirebaseError

logger = logging.getLogger(__name__)

SESSION_USER = 'uid'
SESSION_HASH = 'uh'
PUBLIC_PATHS = ('/login/', '/static/', '/healthz')


def _fingerprint(user):
    return hmac.new(settings.SECRET_KEY.encode(), user.password.encode(), hashlib.sha256).hexdigest()[:24]


def authenticate(username, password):
    user = store.get_user((username or '').strip().lower())
    if not user or not user.active or not user.password:
        return None

    def upgrade(raw):  # parolele vechi (SHA-256) sunt re-hash-uite la primul login
        user.password = make_password(raw)
        store.save_user(user)

    return user if check_password(password, user.password, setter=upgrade) else None


def login(request, user):
    from .audit import log
    request.session.cycle_key()
    request.session[SESSION_USER] = user.username
    request.session[SESSION_HASH] = _fingerprint(user)
    user.last_login = timezone.now()
    store.save_user(user)
    request.user = user
    log(request, 'login', 'cont', f'{user.username} s-a autentificat')


def logout(request):
    request.session.flush()
    request.user = store.AnonymousUser()


def refresh_session(request, user):
    """Dupa schimbarea propriei parole, sesiunea curenta ramane valida."""
    request.session[SESSION_HASH] = _fingerprint(user)


def _session_user(request):
    username = request.session.get(SESSION_USER)
    if not username:
        return store.AnonymousUser()
    user = store.get_user_cached(username)
    if not user or not user.active or not hmac.compare_digest(request.session.get(SESSION_HASH, ''), _fingerprint(user)):
        request.session.flush()
        return store.AnonymousUser()
    return user


class AuthMiddleware:
    """Seteaza request.user si cere autentificare pentru tot, mai putin login/static."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.user = SimpleLazyObject(lambda: _session_user(request))
        try:
            if not request.path.startswith(PUBLIC_PATHS) and not request.user.is_authenticated:
                return redirect(f'{settings.LOGIN_URL}?next={quote(request.get_full_path())}')
            return self.get_response(request)
        except FirebaseError as exc:
            return _unavailable(exc)

    def process_exception(self, request, exception):
        if isinstance(exception, FirebaseError):
            return _unavailable(exception)
        return None


def _unavailable(exc):
    logger.error('Firebase indisponibil: %s', exc)
    return HttpResponse(
        '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        '<div style="font-family:system-ui;max-width:420px;margin:15vh auto;padding:0 20px;text-align:center">'
        '<h2>Nu se poate conecta la baza de date</h2><p style="color:#666">Încearcă din nou peste câteva secunde. '
        'Datele deja salvate sunt în siguranță; ultima acțiune poate să nu se fi salvat.</p>'
        '<p><a href="">Reîncearcă</a></p></div>', status=503)
