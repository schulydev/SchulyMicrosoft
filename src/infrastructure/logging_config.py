class LoggerNames:
    """The service's logger names. They are not configured here: uvicorn's defaults stay, and its access log stays off (see asgi.py)."""

    SERVICE = "schuly.microsoft"
    PASSWORD_SIGN_IN = "schuly.microsoft.password"
