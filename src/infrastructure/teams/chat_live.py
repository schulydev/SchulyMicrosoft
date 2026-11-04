"""Live chat events for one open Schuly chat page, over OutNote's `listen()` (Teams' own push service, undocumented).

The feed lives exactly as long as the request: no listener outlives its caller, and nothing is stored. It says only that something
changed in a chat, never what: the caller reads the messages the normal way. `reconnect=False` on purpose, so a broken feed ends the
stream and the caller sees it, falls back to polling and reconnects, rather than a stream that looks up and delivers nothing.
"""

import asyncio
import json
import logging
import threading
from collections import Counter
from collections.abc import AsyncIterator

from src.application.abstractions.i_chat_live import IChatLive
from src.domain.errors.service_error import ServiceError
from src.domain.validation.graph_ids import GraphIds
from src.infrastructure.logging_config import LoggerNames


class ChatLive(IChatLive):
    """One thread and one Teams connection per open stream, capped because this service is one process."""

    log = logging.getLogger(LoggerNames.SERVICE)
    HEARTBEAT = 20.0  # seconds; keeps proxies from closing a quiet stream
    MAX_STREAMS = 200
    MAX_PER_ACCOUNT = 3  # a few tabs; each one is its own connection to Teams
    PING = b'{"kind":"ping"}\n'
    CHANGES = frozenset({"message", "message_updated", "message_deleted"})

    def __init__(self):
        self._guard = threading.Lock()
        self._streams = Counter()

    def _has_room(self, broker) -> bool:
        return self._streams.total() < self.MAX_STREAMS and self._streams[broker] < self.MAX_PER_ACCOUNT

    def _enter(self, broker) -> bool:
        with self._guard:
            if not self._has_room(broker):
                return False
            self._streams[broker] += 1
            return True

    def _leave(self, broker) -> None:
        with self._guard:
            self._streams[broker] -= 1
            if self._streams[broker] <= 0:
                del self._streams[broker]

    def line(self, event) -> bytes | None:
        """What the caller may see of an event, or None: everything else (typing, presence, read receipts) stays here."""
        if event.kind == "connected":
            return b'{"kind":"connected"}\n'
        if event.kind not in self.CHANGES or not isinstance(event.chat_id, str):
            return None
        if not GraphIds.CHAT_ID_PATTERN.fullmatch(event.chat_id) or GraphIds.has_dot_segment(event.chat_id):
            return None
        return (json.dumps({"kind": event.kind, "chatId": event.chat_id, "fromMe": bool(event.from_me)}) + "\n").encode()

    def open(self, note, broker) -> AsyncIterator[bytes]:
        with self._guard:
            if not self._has_room(broker):
                raise ServiceError(503, "Too many live chat connections.", headers={"Retry-After": "60"})
        return self._stream(note.listen(reconnect=False), broker)

    def _pump(self, live, loop, queue) -> None:
        def put(item) -> None:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, item)
            except RuntimeError:
                live.close()  # the loop is gone, and so is the caller

        try:
            for event in live:
                line = self.line(event)
                if line:
                    put(line)
        except Exception as ex:  # network, auth or protocol: the caller reconnects
            self.log.warning("Live chat feed ended: %s", type(ex).__name__)
        finally:
            put(None)

    async def _stream(self, live, broker) -> AsyncIterator[bytes]:
        # The slot is taken here and not in open(): a generator that never starts never reaches a finally.
        if not self._enter(broker):
            live.close()
            return
        try:
            queue = asyncio.Queue()
            threading.Thread(target=self._pump, args=(live, asyncio.get_running_loop(), queue), daemon=True, name="chat-live").start()
            yield self.PING
            while True:
                try:
                    line = await asyncio.wait_for(queue.get(), self.HEARTBEAT)
                except TimeoutError:
                    yield self.PING
                    continue
                if line is None:
                    return
                yield line
        finally:
            live.close()
            self._leave(broker)
