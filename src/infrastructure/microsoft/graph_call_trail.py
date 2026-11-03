class GraphCallTrail:
    """Stands in for a client during one action and remembers what was last asked of it, so a throttled call can be named in the log.

    A path is kept only with its known Graph words: everything else (ids, addresses, names, the query) becomes `*`, so nothing of the user's reaches the log."""

    PATH_METHODS = frozenset({"get", "list", "post", "patch", "put", "delete", "redirect"})
    GRAPH_WORDS = frozenset(
        """me users chats messages hostedContents replies members shares driveItem drive drives items root children content thumbnails small medium large
        photo photos $value teams channels filesFolder groups sites onenote notebooks sections pages mailFolders attachments events calendar search query $batch""".split()
    )

    def __init__(self, client):
        self._client = client
        self.route = "unknown"

    def __getattr__(self, name):
        attribute = getattr(self._client, name)
        if not callable(attribute):
            return attribute

        def call(*args, **kwargs):
            self.route = self.mask(args[0]) if name in self.PATH_METHODS and args and isinstance(args[0], str) else name
            return attribute(*args, **kwargs)

        return call

    @classmethod
    def mask(cls, path: str) -> str:
        return "/".join(part if part in cls.GRAPH_WORDS else "*" for part in path.split("?")[0].strip("/").split("/"))
