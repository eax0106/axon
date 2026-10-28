"""Refuse a request body over the limit with 413, whether or not the client announced its size.

The biggest honest body is a phone photo or a PDF (8 MB, see app.training.router); a spoken-brief
chunk and a CSV are smaller. Nothing else is read whole, so a larger body is an attack or a mistake.
"""

from fastapi import HTTPException
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_BODY_BYTES = 10_000_000
_TOO_BIG = f"request body over {MAX_BODY_BYTES // 1_000_000} MB"


class BodyLimit:
    def __init__(self, app: ASGIApp, limit: int = MAX_BODY_BYTES) -> None:
        self.app, self.limit = app, limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        announced = Headers(scope=scope).get("content-length", "")
        if announced.isdigit() and int(announced) > self.limit:
            await JSONResponse({"detail": _TOO_BIG}, status_code=413)(scope, receive, send)
            return
        seen = 0

        async def counted() -> Message:
            nonlocal seen
            message = await receive()
            seen += len(message.get("body", b"")) if message["type"] == "http.request" else 0
            if seen > self.limit:  # chunked, or a client that lied about its length
                raise HTTPException(413, _TOO_BIG)
            return message

        await self.app(scope, counted, send)
