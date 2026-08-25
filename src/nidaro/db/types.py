from datetime import UTC, datetime
from uuid import UUID, uuid4


def new_uuid() -> UUID:
    uuid7 = getattr(__import__("uuid"), "uuid7", None)
    return uuid7() if uuid7 is not None else uuid4()


def utc_now() -> datetime:
    return datetime.now(UTC)
