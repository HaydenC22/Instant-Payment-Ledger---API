class IdempotencyInProgressError(RuntimeError):
    def __init__(self, key: str, endpoint: str):
        self.key = key
        self.endpoint = endpoint
        super().__init__(
            f"a request with idempotency key {key!r} for {endpoint} is already in progress"
        )


class IdempotencyKeyReusedError(ValueError):
    def __init__(self, key: str, endpoint: str):
        self.key = key
        self.endpoint = endpoint
        super().__init__(
            f"idempotency key {key!r} for {endpoint} was already used with a different request body"
        )
