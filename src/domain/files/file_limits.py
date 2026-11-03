class FileLimits:
    """Size caps of the file and send routes. Read at call time."""

    MAX_TEXT_SOURCE_BYTES = 25 * 1024 * 1024
    MAX_CHAT_FILE_BYTES = 100 * 1024 * 1024
    MAX_SEND_BYTES = 105 * 1024 * 1024  # a whole chat send: one 100 MB file plus the message and inline images
    MAX_JSON_SEND_BYTES = 256 * 1024
    MAX_BODY_BYTES = 1024 * 1024
    MAX_SEND_ATTACHMENT_BYTES = 3 * 1024 * 1024
    MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
