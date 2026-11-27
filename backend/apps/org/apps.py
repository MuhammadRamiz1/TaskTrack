from django.apps import AppConfig


class OrgConfig(AppConfig):
    name = "apps.org"
    label = "org"

    def ready(self):
        from . import scopes

        scopes.register_all()
