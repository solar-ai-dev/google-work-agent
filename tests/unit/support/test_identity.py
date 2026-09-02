from tests.support.fakes import DeterministicUUID


def test_deterministic_uuid__generates_same_sequence__for_same_seed() -> None:
    left = DeterministicUUID(prefix="run", start=7)
    right = DeterministicUUID(prefix="run", start=7)

    assert [left.next_id(), left.next_id(), left.next_id()] == [
        right.next_id(),
        right.next_id(),
        right.next_id(),
    ]


def test_deterministic_uuid__uses_queued__ids_in_order() -> None:
    generator = DeterministicUUID(queued_ids=("fixed-1", "fixed-2"))

    assert generator.next_id() == "fixed-1"
    assert generator.next_id() == "fixed-2"
    assert generator.next_id() == "id-0001"


def test_deterministic_uuid__blocks_duplicate__or_exhausted_queue() -> None:
    duplicate = DeterministicUUID(queued_ids=("same", "same"))
    duplicate.next_id()
    try:
        duplicate.next_id()
    except RuntimeError as error:
        assert "duplicate deterministic id" in str(error)
    else:
        raise AssertionError("expected RuntimeError for duplicate queued id")

    exhausted = DeterministicUUID(queued_ids=("only",), require_queued_ids=True)
    exhausted.next_id()
    try:
        exhausted.next_id()
    except RuntimeError as error:
        assert "queue is exhausted" in str(error)
    else:
        raise AssertionError("expected RuntimeError for exhausted queued ids")
