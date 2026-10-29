class AppError(Exception):
    """Business-rule error rendered as FastAPI's standard error envelope."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)
