import posixpath
from urllib.parse import quote

from fastapi import Response
from fastapi.responses import StreamingResponse

from src.application.services.content_names import ContentNames
from src.domain.files.binary_content import BinaryContent
from src.domain.files.file_stream import FileStream
from src.domain.files.spooled_pdf import SpooledPdf


class FileResponses:
    """File answers. The rotated refresh token may ride on any of them (see the middleware), so nothing may store them; the plugin caches images itself."""

    SANDBOX = "sandbox; default-src 'none'"

    @classmethod
    def attachment(cls, content: BinaryContent) -> Response:
        return Response(content=content.data, media_type=content.content_type, headers=cls._download_headers(content.file_name))

    @classmethod
    def stream(cls, content: FileStream) -> StreamingResponse:
        return StreamingResponse(content.chunks, media_type=content.content_type, headers=cls._download_headers(content.file_name))

    @classmethod
    def image(cls, content: BinaryContent) -> Response:
        return Response(content=content.data, media_type=content.content_type, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    @staticmethod
    def user_photo(content: BinaryContent) -> Response:
        # The caller caches the photo itself.
        return Response(content=content.data, media_type=content.content_type, headers={"Cache-Control": "no-store"})

    @classmethod
    def pdf(cls, pdf: SpooledPdf) -> StreamingResponse:
        """Inline (it was checked to be a PDF), sandboxed, never stored."""
        pdf_name = posixpath.splitext(ContentNames.safe_name(pdf.source_name))[0] + ".pdf"
        spooled = pdf.file
        size = spooled.seek(0, 2)
        spooled.seek(0)
        headers = {"Content-Disposition": f"inline; filename*=UTF-8''{quote(pdf_name, safe='')}", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Content-Security-Policy": cls.SANDBOX, "Content-Length": str(size)}

        def body():
            try:
                while chunk := spooled.read(64 * 1024):
                    yield chunk
            finally:
                spooled.close()

        return StreamingResponse(body(), media_type="application/pdf", headers=headers)

    @classmethod
    def _download_headers(cls, name: str) -> dict[str, str]:
        return {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name, safe='')}", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Content-Security-Policy": cls.SANDBOX}
