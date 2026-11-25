import os

settings_module = os.environ.get("DJANGO_SETTINGS_MODULE")

if settings_module in {None, "leoTrade.settings"}:
    if os.environ.get("DJANGO_ENV") == "prod":
        from .prod import *  # noqa: F401,F403
    else:
        from .dev import *  # noqa: F401,F403
