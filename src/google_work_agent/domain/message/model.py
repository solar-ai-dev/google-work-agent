"""Message semantic invariants."""
MAX_MESSAGE_UTF8_BYTES = 65_536

def validate_message_content(content: str) -> None:
    """Validate the persisted Message content boundary."""
    if len(content.encode("utf-8")) > MAX_MESSAGE_UTF8_BYTES:
        raise ValueError("message content exceeds 65536 UTF-8 bytes")
