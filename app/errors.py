from app.reasons import REASONS


class DomainError(Exception):
    def __init__(self, code, status=422, *, file=None, line=None, detail=None):
        self.code = code
        self.status = status
        self.file = file
        self.line = line
        self.detail = detail
        super().__init__(REASONS[code])

    def payload(self):
        return {
            "code": self.code,
            "message": str(self),
            "file": self.file,
            "line": self.line,
            "detail": self.detail,
        }
