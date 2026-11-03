class PhotoThrottled(RuntimeError):
    def __init__(self, retry_after: float | None = None):
        self.retry_after = retry_after
        super().__init__("throttled")
