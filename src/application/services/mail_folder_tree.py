import logging
from concurrent.futures import ThreadPoolExecutor

from src.application.abstractions.i_account_broker import IAccountBroker
from src.application.abstractions.i_graph_client import IGraphClient
from src.application.abstractions.i_mail_folder_roles import IMailFolderRoles


class MailFolderTree:
    """The mail folders as a tree, with their well-known names."""

    log = logging.getLogger("schuly.microsoft")

    def __init__(self, roles: IMailFolderRoles):
        self._roles = roles

    def read(self, note: IGraphClient, broker: IAccountBroker) -> list[dict]:
        roles = self._roles.cached(broker)
        if roles is not None:
            return self.tree(note.mail_folders(include_children=True), roles)
        # First list this hour: resolve the well-known roles in parallel with the folder walk, so they cost no extra round trip.
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(self._roles.lookup, note)
            flat = note.mail_folders(include_children=True)
            try:
                roles = pending.result()
            except Exception as ex:
                # Roles only label folders; the tree is still useful without them.
                self.log.info("mail folder role lookup failed: %s", type(ex).__name__)
                roles = {}
        self._roles.remember(broker, roles)
        return self.tree(flat, roles)

    @staticmethod
    def tree(flat: list[dict], roles: dict[str, str] | None = None) -> list[dict]:
        # OutNote walks the subfolders breadth-first into a flat list; rebuild the nesting from parentFolderId.
        roles = roles or {}
        nodes = {f["id"]: {**f, "wellKnownName": roles.get(f["id"]), "childFolders": []} for f in flat}
        roots = []
        for f in flat:
            parent = nodes.get(f.get("parentFolderId"))
            (parent["childFolders"] if parent is not None and f["id"] != f.get("parentFolderId") else roots).append(nodes[f["id"]])
        return roots
