from fastapi import Request

from src.domain.errors.service_error import ServiceError


class LimitedRequest:
    """A request whose body is cut off past a cap, whatever Content-Length claims."""

    @staticmethod
    def limit(request: Request, cap: int) -> Request:
        received = 0
        upstream = request.receive

        async def receive():
            nonlocal received
            message = await upstream()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > cap:
                    raise ServiceError(413, "The message is larger than the send limit.")
            return message

        return Request(request.scope, receive)
