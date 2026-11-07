class AIError(Exception):
    def __init__(self, message, code="AI_ERROR", status=503, uncertain=False):
        super().__init__(message)
        self.code, self.status, self.uncertain = code, status, uncertain
