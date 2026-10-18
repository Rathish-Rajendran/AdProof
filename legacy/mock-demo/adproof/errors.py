class DemoError(Exception):
    """An error safe to return through the local demo API."""

    def __init__(self, code, message, status=400, fields=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.fields = fields

    def as_dict(self):
        result = {"code": self.code, "message": self.message}
        if self.fields:
            result["fields"] = self.fields
        return result
