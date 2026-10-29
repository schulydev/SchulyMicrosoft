"""Office files as PDF for the web viewer, converted by Microsoft 365 (Graph's `content?format=pdf`).

A file already in OneDrive / SharePoint (a drive item, a file shared in a chat) is converted where it is. A file that isn't in a
drive (a mail attachment, bytes the caller uploads) goes up to a temporary file in the app's own OneDrive folder
(`special/approot:/schuly-preview/<random>.<ext>`), is converted, and is deleted again in a `finally`. Leftovers (a crash between
upload and delete) are swept: files in that folder older than an hour are deleted, at most once per 10 minutes per account.

Graph answers a conversion with a 302 to a short-lived pre-authenticated URL on `<region>-mediap.svc.ms`; only that host (or a
SharePoint host) is fetched, https only, and the bytes are held in a spooled temporary file so they can be checked (`%PDF`, size)
before anything is sent.
"""

import logging
import posixpath
import re
import secrets
import tempfile
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit

import entrance
import httpx
from outnote import GraphError

from src.account_cache import for_broker

log = logging.getLogger("schuly.microsoft")

# Graph's format=pdf source types.
CONVERTIBLE = frozenset({"csv", "doc", "docx", "odp", "ods", "odt", "pot", "potm", "potx", "pps", "ppsx", "ppsxm", "ppt", "pptm", "pptx", "rtf", "xls", "xlsx"})
TEMP_FOLDER = "schuly-preview"
TEMP_MAX_AGE = timedelta(hours=1)
SWEEP_EVERY = 600
MAX_PDF_BYTES = 150 * 1024 * 1024
SPOOL_IN_MEMORY = 8 * 1024 * 1024
FETCH_TIMEOUT = httpx.Timeout(120.0, connect=5.0)
CONVERTED_HOST = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*-mediap\.svc\.ms")
HOST_SUFFIXES = (".sharepoint.com",)


class ConvertError(Exception):
    """The file can't be shown as PDF: `status` is the HTTP status to answer with (413, 415, 502)."""

    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(message)


def extension(name) -> str:
    return posixpath.splitext(name or "")[1].lstrip(".").lower() if isinstance(name, str) else ""


def is_convertible(name) -> bool:
    return extension(name) in CONVERTIBLE


def is_converted_url(url) -> bool:
    """True only for the https URL Graph redirects a conversion to: `<region>-mediap.svc.ms` exactly, or a SharePoint host."""
    if not isinstance(url, str) or not url or len(url) > 8000 or any(ord(c) < 33 for c in url):
        return False
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and port in (None, 443) and not parts.username and not parts.password and (bool(CONVERTED_HOST.fullmatch(host)) or any(host.endswith(s) for s in HOST_SUFFIXES))


def drive_item_pdf(note, item_id: str, drive_id: str | None = None):
    """A drive item converted to PDF, as a spooled file positioned at 0."""
    try:
        url = note.converted_url(quote(item_id, safe=""), "pdf", quote(drive_id, safe="") if drive_id else None)
    except GraphError as ex:
        if ex.status in (400, 406, 415, 422, 501):
            raise ConvertError(415, "Microsoft 365 cannot convert this file to PDF.")
        raise
    return fetch_pdf(url)


def fetch_pdf(url: str):
    """The converted bytes behind a pre-authenticated URL (no bearer token is sent), checked to be a PDF and capped."""
    if not is_converted_url(url):
        raise ConvertError(502, "The conversion answered with an unexpected location.")
    out = tempfile.SpooledTemporaryFile(max_size=SPOOL_IN_MEMORY)
    try:
        with entrance.http_client().stream("GET", url, timeout=FETCH_TIMEOUT, follow_redirects=False) as r:
            if r.status_code != 200:
                raise ConvertError(502, f"The conversion failed ({r.status_code}).")
            size = 0
            for chunk in r.iter_bytes(64 * 1024):
                size += len(chunk)
                if size > MAX_PDF_BYTES:
                    raise ConvertError(413, "The converted PDF is larger than 150 MB.")
                out.write(chunk)
        out.seek(0)
        if not out.read(1024).lstrip().startswith(b"%PDF"):
            raise ConvertError(502, "The conversion did not return a PDF.")
        out.seek(0)
        return out
    except BaseException:
        out.close()
        raise


def bytes_pdf(note, broker, data: bytes, name: str):
    """Bytes that aren't in a drive, converted through a temporary file in the app folder that is always deleted again."""
    ext = extension(name)
    if ext not in CONVERTIBLE:
        raise ConvertError(415, "This file type cannot be converted to PDF.")
    sweep(note, broker)
    item_id = None
    try:
        item = note.upload(data, f"{TEMP_FOLDER}/{secrets.token_hex(16)}.{ext}", conflict="fail", app_folder=True)
        item_id = (item or {}).get("id")
        if not item_id:
            raise ConvertError(502, "The temporary upload failed.")
        return drive_item_pdf(note, item_id)
    finally:
        if item_id:
            try:
                note.delete_file(quote(item_id, safe=""))
            except Exception as ex:
                # The sweep removes it within the hour.
                log.warning("temporary preview file not deleted: %s", type(ex).__name__)


def sweep(note, broker, now: datetime | None = None) -> int:
    """Deletes temporary files older than an hour (best effort, at most every 10 minutes per account); returns how many."""
    cache = for_broker(broker)
    if cache.has(("preview_sweep",)):
        return 0
    cache.set(("preview_sweep",), True, SWEEP_EVERY)
    now = now or datetime.now(timezone.utc)
    deleted = 0
    try:
        items = note.list(f"me/drive/special/approot:/{TEMP_FOLDER}:/children", {"$select": "id,name,createdDateTime", "$top": 200}, limit=200)
    except GraphError as ex:
        if ex.status != 404:
            log.info("preview sweep list failed: %s", ex.status)
        return 0
    except Exception as ex:
        log.info("preview sweep list failed: %s", type(ex).__name__)
        return 0
    for item in items:
        created = _parse_time(item.get("createdDateTime"))
        if created is None or now - created < TEMP_MAX_AGE or not isinstance(item.get("id"), str):
            continue
        try:
            note.delete_file(quote(item["id"], safe=""))
            deleted += 1
        except Exception as ex:
            log.info("preview sweep delete failed: %s", type(ex).__name__)
    return deleted


def _parse_time(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
