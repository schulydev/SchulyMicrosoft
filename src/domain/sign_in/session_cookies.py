class SessionCookies:
    """The Microsoft sign-in session a password sign-in ends with, in the shape the app's WebView capture sends:
    `{domain, name, path, value}`, only for Microsoft's sign-in hosts. A credential: never log it."""

    SIGN_IN_HOSTS = frozenset({"login.microsoftonline.com", "login.microsoft.com", "login.live.com"})

    @classmethod
    def sign_in_only(cls, cookies) -> list[dict[str, str]]:
        kept = []
        for cookie in cookies or []:
            if not isinstance(cookie, dict):
                continue
            domain = str(cookie.get("domain") or "").strip().lstrip(".").lower()
            name, value, path = cookie.get("name"), cookie.get("value"), cookie.get("path")
            if domain not in cls.SIGN_IN_HOSTS or not isinstance(name, str) or not name.strip() or not isinstance(value, str):
                continue
            kept.append({"domain": domain, "name": name, "path": path if isinstance(path, str) and path.strip() else "/", "value": value})
        return kept
