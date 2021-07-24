from typing import Any


class InvalidToken(Exception):
    def __init__(self, address: Any) -> None:
        Exception.__init__(self, f"Invalid token address: {address}")


class InsufficientBalance(Exception):
    def __init__(self, had: int, needed: int) -> None:
        Exception.__init__(self, f"Insufficient balance. Had {had}, needed {needed}")
