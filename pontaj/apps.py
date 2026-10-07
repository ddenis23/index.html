from django.apps import AppConfig


class PontajConfig(AppConfig):
    name = 'pontaj'
    verbose_name = 'Pontaj'

    def ready(self):
        from . import audit  # noqa: F401  inregistreaza semnalul de login
