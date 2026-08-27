"""UUID4 generator adapter."""

import uuid


class Uuid4Adapter:
    def new_uuid(self) -> str:
        return str(uuid.uuid4())
