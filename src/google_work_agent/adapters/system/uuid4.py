"""UUID4 generator adapter."""

import uuid


class Uuid4Adapter:
    def next_id(self) -> str:
        return str(uuid.uuid4())
