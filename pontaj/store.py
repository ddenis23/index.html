"""Datele aplicatiei, citite si scrise in Firebase.

Structura e aceeasi cu a vechii aplicatii (index.html), ca ambele sa poata
rula in paralel pe aceleasi date:

    sectii/{COD}                {label, bg, c, order}
    angajati/{id}               {name, section, tura, active, startFrom, inactiveFrom}
    pontaj/{id}/{YYYY-MM-DD}    {type: 'interval', s, e} | {type: 'code', code, approved?}
    bonusuri/{YYYY-MM}/{id}     'SP' | 'SP0.5' | 'SP+'
    setari                      {admin_pass, emp_pass}  (hash-uri vechi)

Noduri noi:
    utilizatori/{username}      {password, role, name, active, last_login}
    istoric/{pushId}            {when, user, action, target, emp, summary, before, after, ip}
"""

import datetime as dt
import itertools
import random
import string
import time
from dataclasses import dataclass, field

from django.utils import timezone

from .firebase import backend


class Code:
    SP, SP05, SPP, CO, CM, OFF, LP, LFP = 'SP', 'SP0.5', 'SP+', 'CO', 'CM', 'OFF', 'LP', 'LFP'
    choices = [
        (SP, 'SP — 1 tura'), (SP05, 'SP½ — ½ tura'), (SPP, 'SP+ — 1.5 ture'), (CO, 'CO — Concediu'),
        (CM, 'CM — Medical'), (OFF, 'OFF — Liber'), (LP, 'LP — Liber cu plata'), (LFP, 'LFP — Liber fara plata'),
    ]
    values = [c for c, _ in choices]
    labels = dict(choices)


SP_VALUE = {Code.SP: 1, Code.SP05: 0.5, Code.SPP: 1.5}


def _date(value):
    try:
        return dt.date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def new_id():
    """Acelasi format ca vechea aplicatie: timestamp base36 + 3 caractere aleatoare."""
    n, digits, out = int(time.time() * 1000), string.digits + string.ascii_lowercase, ''
    while n:
        n, r = divmod(n, 36)
        out = digits[r] + out
    return out + ''.join(random.choices(digits, k=3))


# ── Domeniu ──────────────────────────────────────────────

@dataclass
class Section:
    id: str
    label: str
    bg: str = '#f0ece3'
    color: str = '#5a5040'
    order: int = 0

    def __str__(self):
        return self.label


FALLBACK_SECTION = Section('ALTELE', 'Altele', order=99)


@dataclass
class Employee:
    id: str
    name: str
    section: Section
    shift: int
    start_from: dt.date
    inactive_from: dt.date | None = None

    def __str__(self):
        return self.name

    def is_active_on(self, day):
        if day < self.start_from:
            return False
        return not (self.inactive_from and day >= self.inactive_from)

    def is_active_in(self, first, last):
        if self.start_from > last:
            return False
        return not (self.inactive_from and self.inactive_from <= first)

    def lock_reason(self, day):
        if day < self.start_from:
            return f'Angajatul incepe din {self.start_from:%d.%m.%Y}'
        if self.inactive_from and day >= self.inactive_from:
            return f'Angajatul este inactiv din {self.inactive_from:%d.%m.%Y}'
        return ''

    @property
    def initials(self):
        return ''.join(w[0] for w in self.name.split()[:2])


@dataclass
class Entry:
    """O zi de pontaj: fie un interval orar, fie un cod."""

    employee_id: str
    day: dt.date
    start_h: int | None = None
    end_h: int | None = None
    code: str = ''
    approved: bool | None = None

    @property
    def is_interval(self):
        return not self.code

    @property
    def hours(self):
        if self.code:
            return 0
        end = self.end_h if self.end_h > self.start_h else self.end_h + 24
        return end - self.start_h

    def describe(self):
        if not self.code:
            return f'{self.start_h:02d}–{self.end_h:02d} ({self.hours}h)'
        if self.code == Code.CO and self.approved is not None:
            return f'CO ({"aprobat" if self.approved else "neaprobat"})'
        return 'SP½' if self.code == Code.SP05 else self.code

    def get_code_display(self):
        return Code.labels.get(self.code, self.code)

    def to_firebase(self):
        if not self.code:
            return {'type': 'interval', 's': self.start_h, 'e': self.end_h}
        row = {'type': 'code', 'code': self.code}
        if self.code == Code.CO and self.approved is not None:
            row['approved'] = self.approved
        return row

    @classmethod
    def from_firebase(cls, emp_id, day, raw):
        if not isinstance(raw, dict):
            return None
        if raw.get('type') == 'interval' and raw.get('s') is not None and raw.get('e') is not None:
            return cls(emp_id, day, start_h=int(raw['s']), end_h=int(raw['e']))
        if raw.get('type') == 'code':
            code = {'CFP': 'LFP'}.get(raw.get('code'), raw.get('code'))
            if code in Code.values:
                return cls(emp_id, day, code=code, approved=raw.get('approved') if code == Code.CO else None)
        return None


@dataclass
class Data:
    """Instantaneu al datelor de pontaj, incarcat o data pe cerere."""

    sections: list = field(default_factory=list)
    employees: list = field(default_factory=list)
    entries: dict = field(default_factory=dict)   # (emp_id, date) -> Entry
    bonuses: dict = field(default_factory=dict)   # (emp_id, 'YYYY-MM') -> cod

    def employee(self, emp_id):
        return next((e for e in self.employees if e.id == emp_id), None)

    def section(self, sec_id):
        return next((s for s in self.sections if s.id == sec_id), None)


def _as_dict(value):
    """Firebase intoarce liste cand cheile sunt numere consecutive."""
    if isinstance(value, list):
        return {str(i): v for i, v in enumerate(value) if v is not None}
    return value or {}


def load():
    raw_secs, raw_emps, raw_pontaj, raw_bonus = backend().get_many(['sectii', 'angajati', 'pontaj', 'bonusuri'])
    data = _people(raw_secs, raw_emps)
    _add_entries(data, raw_pontaj)
    for month, per_emp in _as_dict(raw_bonus).items():
        for eid, code in _as_dict(per_emp).items():
            if code in SP_VALUE:
                data.bonuses[(eid, month)] = code
    return data


def load_people():
    """Doar sectiile si angajatii (fara pontaj) — pentru salvari rapide."""
    return _people(*backend().get_many(['sectii', 'angajati']))


def load_entries(emp_ids):
    """Pontajul doar pentru angajatii dati: {(emp_id, data): Entry}."""
    emp_ids = list(emp_ids)
    data = Data()
    raws = backend().get_many([f'pontaj/{eid}' for eid in emp_ids])
    _add_entries(data, dict(zip(emp_ids, raws)))
    return data.entries


def _add_entries(data, raw_pontaj):
    for eid, days in _as_dict(raw_pontaj).items():
        for day, raw in _as_dict(days).items():
            d = _date(day)
            entry = Entry.from_firebase(eid, d, raw) if d else None
            if entry:
                data.entries[(eid, d)] = entry


def _people(raw_secs, raw_emps):
    data = Data()
    for sid, s in _as_dict(raw_secs).items():
        if isinstance(s, dict):
            data.sections.append(Section(sid, s.get('label') or sid.title(), s.get('bg', '#f0ece3'),
                                         s.get('c', '#5a5040'), int(s.get('order', 99))))
    data.sections.sort(key=lambda s: (s.order, s.label))
    by_id = {s.id: s for s in data.sections}
    order = {s.id: i for i, s in enumerate(data.sections)}

    for eid, e in _as_dict(raw_emps).items():
        if not isinstance(e, dict):
            continue
        start = _date(e.get('startFrom')) or dt.date(2025, 1, 1)
        inactive = _date(e.get('inactiveFrom'))
        if e.get('active') is False and not inactive:
            inactive = start  # vechea aplicatie il trata ca inactiv de tot
        data.employees.append(Employee(
            eid, (e.get('name') or '?').strip(), by_id.get(e.get('section'), FALLBACK_SECTION),
            2 if e.get('tura') == 2 else 1, start, inactive))
    data.employees.sort(key=lambda e: (order.get(e.section.id, 99), e.name))
    return data


# ── Scrieri ──────────────────────────────────────────────

def entry_path(emp_id, day):
    return f'pontaj/{emp_id}/{day:%Y-%m-%d}'


def commit(updates):
    """O singura scriere atomica, multi-path: {'pontaj/1/2026-10-05': {...} | None, 'istoric/<cheie>': {...}}."""
    if updates:
        backend().update('', updates)


def save_bonuses(month_key, codes):
    """codes: {emp_id: cod | None}"""
    backend().update(f'bonusuri/{month_key}', codes)


def save_employee(emp):
    backend().update(f'angajati/{emp.id}', {
        'name': emp.name, 'section': emp.section.id, 'tura': emp.shift,
        'startFrom': f'{emp.start_from:%Y-%m-%d}',
        'inactiveFrom': f'{emp.inactive_from:%Y-%m-%d}' if emp.inactive_from else None,
        'active': emp.inactive_from is None,
    })


def delete_employee(emp_id):
    backend().update('', {f'angajati/{emp_id}': None, f'pontaj/{emp_id}': None})


def save_section(sec):
    backend().update(f'sectii/{sec.id}', {'label': sec.label, 'bg': sec.bg, 'c': sec.color, 'order': sec.order})


def delete_section(sec_id):
    backend().set(f'sectii/{sec_id}', None)


def export_all():
    return backend().get('') or {}


# ── Utilizatori ──────────────────────────────────────────

ROLES = ('superadmin', 'admin', 'angajat')


@dataclass
class User:
    username: str
    password: str = ''
    role: str = 'angajat'
    name: str = ''
    active: bool = True
    last_login: dt.datetime | None = None

    is_authenticated = True

    @property
    def pk(self):
        return self.username

    id = pk

    @property
    def is_superuser(self):
        return self.role == 'superadmin'

    @property
    def is_staff(self):
        return self.role in ('superadmin', 'admin')

    @property
    def is_active(self):
        return self.active

    @property
    def first_name(self):
        return self.name

    def get_full_name(self):
        return self.name

    def to_firebase(self):
        return {'password': self.password, 'role': self.role, 'name': self.name, 'active': self.active,
                'last_login': self.last_login.isoformat() if self.last_login else None}

    @classmethod
    def from_firebase(cls, username, raw):
        last = raw.get('last_login')
        return cls(username, raw.get('password', ''), raw.get('role') if raw.get('role') in ROLES else 'angajat',
                   raw.get('name', ''), raw.get('active', True) is not False,
                   dt.datetime.fromisoformat(last) if last else None)


class AnonymousUser:
    is_authenticated = False
    is_staff = is_superuser = is_active = False
    username = ''


def valid_username(username):
    return bool(username) and all(c.isalnum() or c in '._-' for c in username) and len(username) <= 40


def get_user(username):
    if not valid_username(username):
        return None
    raw = backend().get(f'utilizatori/{username}')
    return User.from_firebase(username, raw) if isinstance(raw, dict) else None


def list_users():
    raw = _as_dict(backend().get('utilizatori'))
    return [User.from_firebase(u, r) for u, r in raw.items() if isinstance(r, dict)]


def save_user(user):
    backend().set(f'utilizatori/{user.username}', user.to_firebase())
    _user_cache.pop(user.username, None)


# Contul e citit la fiecare cerere; il tinem cateva secunde in memorie ca paginile sa fie rapide.
_user_cache = {}
USER_CACHE_SECONDS = 20


def get_user_cached(username):
    hit = _user_cache.get(username)
    if hit and hit[1] > time.monotonic():
        return hit[0]
    user = get_user(username)
    _user_cache[username] = (user, time.monotonic() + USER_CACHE_SECONDS)
    return user


def legacy_passwords():
    return backend().get('setari') or {}


# ── Istoric ──────────────────────────────────────────────

@dataclass
class LogEntry:
    key: str
    when: dt.datetime
    username: str
    action: str
    target: str
    employee_id: str
    employee_name: str
    summary: str
    before: str
    after: str

    ACTIONS = {'create': 'Adaugare', 'update': 'Modificare', 'delete': 'Stergere',
               'login': 'Autentificare', 'export': 'Export'}

    def get_action_display(self):
        return self.ACTIONS.get(self.action, self.action)


_log_seq = itertools.count()


def log_key():
    """Chei cronologice (sortate ca text), ca istoricul sa poata fi scris in aceeasi tranzactie cu modificarea.

    milisecunde + contor (ordinea in acelasi proces) + sufix aleator (unicitate intre procese).
    """
    return f'{int(time.time() * 1000):013d}{next(_log_seq) % 10000:04d}{"".join(random.choices(string.ascii_lowercase, k=3))}'


def add_log(row):
    backend().set(f'istoric/{log_key()}', row)


def recent_logs(limit=3000):
    raw = backend().last('istoric', limit)
    tz = timezone.get_current_timezone()
    logs = []
    for key, r in _as_dict(raw).items():
        try:
            when = dt.datetime.fromisoformat(r['when']).astimezone(tz)
        except (KeyError, TypeError, ValueError):
            continue
        logs.append(LogEntry(key, when, r.get('user', '?'), r.get('action', ''), r.get('target', ''),
                             r.get('emp', ''), r.get('emp_name', ''), r.get('summary', ''),
                             r.get('before', ''), r.get('after', '')))
    logs.sort(key=lambda l: l.key, reverse=True)
    return logs
