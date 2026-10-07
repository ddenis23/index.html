"""Creeaza conturile de baza in Firebase, daca lipsesc. Ruleaza la fiecare pornire (idempotent).

- `admin` si `angajat` primesc parolele actuale ale vechii aplicatii (setari/admin_pass, setari/emp_pass);
- `superadmin` e creat doar daca e setata variabila SUPERADMIN_PASSWORD si contul nu exista inca.
"""

import os

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand

from pontaj import store


class Command(BaseCommand):
    help = 'Creeaza conturile admin / angajat / superadmin daca lipsesc.'

    def handle(self, *args, **opts):
        legacy = store.legacy_passwords()
        for username, key, role in (('admin', 'admin_pass', 'admin'), ('angajat', 'emp_pass', 'angajat')):
            if store.get_user(username):
                continue
            digest = legacy.get(key)
            store.save_user(store.User(username, f'legacy_sha256$${digest}' if digest else '', role,
                                       username.title()))
            self.stdout.write(f'Cont {username} creat' + (' cu parola veche.' if digest else ' FARA parola.'))

        password = os.environ.get('SUPERADMIN_PASSWORD')
        if password and not store.get_user('superadmin'):
            store.save_user(store.User('superadmin', make_password(password), 'superadmin', 'Superadmin'))
            self.stdout.write(self.style.SUCCESS('Cont superadmin creat.'))
        self.stdout.write('Conturi verificate.')
