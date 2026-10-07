import getpass

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Creeaza sau reseteaza contul de superadmin (vede istoricul si gestioneaza conturile).'

    def add_arguments(self, parser):
        parser.add_argument('--username', default='superadmin')
        parser.add_argument('--password', help='Daca lipseste, se cere interactiv')

    def handle(self, *args, **opts):
        password = opts['password'] or getpass.getpass('Parola superadmin: ')
        if len(password) < 6:
            raise CommandError('Parola trebuie sa aiba minim 6 caractere.')
        user, created = User.objects.get_or_create(username=opts['username'])
        user.is_superuser = user.is_staff = user.is_active = True
        user.first_name = user.first_name or 'Superadmin'
        user.set_password(password)
        user.save()
        self.stdout.write(self.style.SUCCESS(f'Superadmin {"creat" if created else "actualizat"}: {user.username}'))
