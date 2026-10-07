"""Importa datele din vechea baza Firebase Realtime Database.

    python manage.py import_firebase --url https://<proiect>.firebasedatabase.app
    python manage.py import_firebase --file export.json
"""

import datetime as dt
import json
import urllib.request

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from pontaj.models import SP_VALUE, Code, Employee, Entry, Section, SummerBonus


def _date(value):
    try:
        return dt.date.fromisoformat(value) if value else None
    except ValueError:
        return None


class Command(BaseCommand):
    help = 'Importa sectii, angajati, pontaj, bonusuri si parole din Firebase.'

    def add_arguments(self, parser):
        src = parser.add_mutually_exclusive_group(required=True)
        src.add_argument('--url', help='URL-ul bazei Firebase (fara /.json)')
        src.add_argument('--file', help='Fisier JSON exportat din Firebase')
        parser.add_argument('--replace', action='store_true',
                            help='Sterge datele existente (sectii, angajati, pontaj) inainte de import')

    def handle(self, *args, **opts):
        data = self._load(opts)
        with transaction.atomic():
            if opts['replace']:
                Entry.objects.all().delete()
                SummerBonus.objects.all().delete()
                Employee.objects.all().delete()
                Section.objects.all().delete()
            elif Employee.objects.exists():
                raise CommandError('Exista deja angajati. Foloseste --replace ca sa reimporti.')
            sections = self._sections(data.get('sectii') or {})
            emps = self._employees(data.get('angajati') or {}, data.get('pontaj') or {}, sections)
            n_entries = self._entries(data.get('pontaj') or {}, emps)
            n_bonus = self._bonuses(data.get('bonusuri') or {}, emps)
            self._accounts(data.get('setari') or {})
        self.stdout.write(self.style.SUCCESS(
            f'Importat: {len(sections)} sectii, {len(emps)} angajati, {n_entries} zile, {n_bonus} bonusuri.'))

    def _load(self, opts):
        if opts['file']:
            with open(opts['file'], encoding='utf-8') as fh:
                return json.load(fh)
        url = opts['url'].rstrip('/') + '/.json'
        with urllib.request.urlopen(url, timeout=60) as resp:
            return json.loads(resp.read().decode())

    def _sections(self, raw):
        sections = {}
        for code, s in sorted(raw.items(), key=lambda kv: kv[1].get('order', 99)):
            sections[code] = Section.objects.create(
                code=code, label=s.get('label') or code.title(), bg=s.get('bg', '#f0ece3'),
                color=s.get('c', '#5a5040'), order=s.get('order', len(sections)))
        if 'ALTELE' not in sections:
            sections['ALTELE'] = Section.objects.create(code='ALTELE', label='Altele', order=99)
        return sections

    def _employees(self, raw, pontaj, sections):
        emps = {}
        for legacy_id, e in raw.items():
            start = _date(e.get('startFrom'))
            if not start:
                days = sorted(pontaj.get(legacy_id, {}))
                start = _date(days[0]) if days else dt.date(2025, 1, 1)
            inactive = _date(e.get('inactiveFrom'))
            if e.get('active') is False and not inactive:
                inactive = start  # vechea aplicatie il trata ca inactiv de tot
            emps[legacy_id] = Employee.objects.create(
                name=(e.get('name') or '?').strip().upper(),
                section=sections.get(e.get('section'), sections['ALTELE']),
                shift=2 if e.get('tura') == 2 else 1,
                start_from=start, inactive_from=inactive, legacy_id=legacy_id)
        return emps

    def _entries(self, raw, emps):
        rows = []
        for legacy_id, days in raw.items():
            emp = emps.get(legacy_id)
            if not emp:
                continue
            for day, cell in (days or {}).items():
                d = _date(day)
                if not d or not cell:
                    continue
                if cell.get('type') == 'interval':
                    rows.append(Entry(employee=emp, day=d, start_h=cell['s'], end_h=cell['e']))
                elif cell.get('type') == 'code':
                    code = {'CFP': 'LFP'}.get(cell.get('code'), cell.get('code'))
                    if code in Code.values:
                        rows.append(Entry(employee=emp, day=d, code=code,
                                          approved=cell.get('approved') if code == Code.CO else None))
        Entry.objects.bulk_create(rows)
        return len(rows)

    def _bonuses(self, raw, emps):
        rows = []
        for month_key, per_emp in raw.items():
            month = _date(month_key + '-01')
            if not month:
                continue
            # Firebase transforma cheile numerice in liste.
            items = enumerate(per_emp) if isinstance(per_emp, list) else per_emp.items()
            for legacy_id, code in items:
                emp = emps.get(str(legacy_id))
                if emp and code in SP_VALUE:
                    rows.append(SummerBonus(employee=emp, month=month, code=code))
        SummerBonus.objects.bulk_create(rows)
        return len(rows)

    def _accounts(self, setari):
        """Conturile `admin` si `angajat` pastreaza parolele vechi (hash SHA-256)."""
        for username, key, staff in (('admin', 'admin_pass', True), ('angajat', 'emp_pass', False)):
            digest = setari.get(key)
            user, created = User.objects.get_or_create(
                username=username, defaults={'is_staff': staff, 'first_name': username.title()})
            if digest and (created or not user.has_usable_password()):
                user.password = f'legacy_sha256$${digest}'
                user.save()
                self.stdout.write(f'Cont {username}: parola veche pastrata.')
            elif created:
                user.set_unusable_password()
                user.save()
                self.stdout.write(self.style.WARNING(f'Cont {username}: fara parola, seteaz-o din Conturi.'))
