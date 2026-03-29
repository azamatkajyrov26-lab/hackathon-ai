from django.apps import AppConfig


class EmulatorConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.emulator'
    verbose_name = 'Эмулятор внешних систем'
