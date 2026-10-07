import getpass

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError

from pontaj import store


class Command(BaseCommand):
    help = 'Creeaza sau reseteaza un cont de superadmin (vede istoricul si gestioneaza conturile).'

    def add_arguments(self, parser):
        parser.add_argument('--username', default='superadmin')
        parser.add_argument('--password', help='Daca lipseste, se cere interactiv')

    def handle(self, *args, **opts):
        password = opts['password'] or getpass.getpass('Parola superadmin: ')
        if len(password) < 6:
            raise CommandError('Parola trebuie sa aiba minim 6 caractere.')
        user = store.get_user(opts['username']) or store.User(opts['username'], name='Superadmin')
        user.role, user.active, user.password = 'superadmin', True, make_password(password)
        store.save_user(user)
        self.stdout.write(self.style.SUCCESS(f'Superadmin salvat: {user.username}'))
