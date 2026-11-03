class FileTextLimits:
    """The paging bounds of a FileText read, shared by the routes and the extractor."""

    MAX_SOURCE_BYTES = 25 * 1024 * 1024
    DEFAULT_CHARS = 20000
    MAX_CHARS = 100000
    DEFAULT_ROWS = 500
    MAX_ROWS = 2000
    MAX_ROW_OFFSET = 1_000_000
    UNSUPPORTED = "This file type cannot be read as text."
