import base64
from urllib.parse import quote


class GraphPaths:
    """Graph paths of chat messages and of the drive items behind sharing links."""

    DRIVE_ITEM_FIELDS = "id,name,size,file,webUrl"

    @staticmethod
    def share_id(url: str) -> str:
        return "u!" + base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")

    @classmethod
    def drive_item_path(cls, url: str, select: str = DRIVE_ITEM_FIELDS) -> str:
        return f"shares/{cls.share_id(url)}/driveItem?$select={select}"

    @classmethod
    def share_item_path(cls, url: str) -> str:
        """The whole drive item, the one form Graph always puts `@microsoft.graph.downloadUrl` in: a `$select` can leave it out and cost a second call."""
        return f"shares/{cls.share_id(url)}/driveItem"

    @staticmethod
    def message_path(chat_id: str, message_id: str) -> str:
        return f"chats/{chat_id}/messages/{quote(message_id, safe='')}"
