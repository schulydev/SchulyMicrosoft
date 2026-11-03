from src.application.abstractions.i_graph_client import IGraphClient
from src.application.services.chat_html_sanitizer import ChatHtmlSanitizer
from src.application.services.graph_paths import GraphPaths


class ChatFileLookup:
    """A file shared in a chat message, found by its attachment id."""

    def __init__(self, html: ChatHtmlSanitizer):
        self._html = html

    def find(self, note: IGraphClient, chat_id: str, message_id: str, attachment_id: str) -> dict | None:
        message = note.get(GraphPaths.message_path(chat_id, message_id))
        return next((f for f in self._html.reference_files(message) if f.get("id") == attachment_id), None)
