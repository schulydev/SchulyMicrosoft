class ChatServiceError(RuntimeError):
    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(f"Teams chat service {status}: {message}")
