"""New synthetic namespace cases, with no production registry or persistence."""

from dataclasses import FrozenInstanceError, replace
from uuid import UUID

import pytest

import app.canonical_identity as allocation
from app.canonical_identity import AllocatedID, IdentityError, Namespace, NamespaceRegistry, allocate_id


LOGICAL = Namespace("synthetic.logical.v1", "logical", "synthetic-backend", "synthetic-archive")
OCCURRENCE = replace(LOGICAL, name="synthetic.occurrence.v1", object_category="occurrence")
REVISION = replace(LOGICAL, name="synthetic.revision.v1", object_category="revision")
REGISTRY = NamespaceRegistry((LOGICAL, OCCURRENCE, REVISION))


def test_ids_are_reserved_in_their_explicit_namespace_before_return():
    reserved = []

    def reserve(identity):
        reserved.append(identity)
        return True

    identity = allocate_id("occurrence", REGISTRY, reserve)
    assert reserved == [identity]
    namespace, token = identity.value.rsplit(":", 1)
    assert namespace == OCCURRENCE.name
    assert identity.namespace.owner == "synthetic-backend"
    assert identity.namespace.uniqueness_scope == "synthetic-archive"
    assert UUID(hex=token).version == 4 and len(token) == 32 and token == token.lower()
    with pytest.raises(FrozenInstanceError):
        identity.value = "changed"


def test_logical_id_is_kept_as_reference_across_independently_allocated_revisions():
    logical = allocate_id("logical", REGISTRY, lambda _identity: True)
    revisions = [allocate_id("revision", REGISTRY, lambda _identity: True) for _ in range(2)]
    associations = [(logical, revision) for revision in revisions]
    assert associations[0][0] is associations[1][0]
    assert len({logical.value, *[revision.value for revision in revisions]}) == 3
    occurrences = [allocate_id("occurrence", REGISTRY, lambda _identity: True) for _ in range(2)]
    assert occurrences[0].value != occurrences[1].value


def test_forced_collision_is_failure_without_retry_or_content_identity_reuse(monkeypatch):
    calls = []
    reserved = set()

    def candidate():
        calls.append("uuid")
        return UUID("00000000-0000-4000-8000-000000000001")

    def reserve(identity):
        if identity.value in reserved:
            return False
        reserved.add(identity.value)
        return True

    monkeypatch.setattr(allocation, "uuid4", candidate)
    first = allocate_id("occurrence", REGISTRY, reserve)
    with pytest.raises(IdentityError, match="identity_collision"):
        allocate_id("occurrence", REGISTRY, reserve)
    assert calls == ["uuid", "uuid"]
    assert reserved == {first.value}


def test_registry_ownership_and_scope_are_required_and_immutable():
    with pytest.raises(TypeError):
        Namespace("synthetic", "occurrence")
    with pytest.raises(FrozenInstanceError):
        REGISTRY.entries = ()
    for field in ("owner", "uniqueness_scope"):
        with pytest.raises(IdentityError, match="missing_namespace_ownership"):
            replace(LOGICAL, **{field: " "})
    for field, value in (("name", "é"), ("name", "name:ambiguous"), ("object_category", None)):
        with pytest.raises(IdentityError, match="invalid_namespace"):
            replace(LOGICAL, **{field: value})
    with pytest.raises(IdentityError, match="duplicate_namespace"):
        NamespaceRegistry((LOGICAL, replace(LOGICAL, object_category="other")))
    with pytest.raises(IdentityError, match="duplicate_object_category"):
        NamespaceRegistry((LOGICAL, replace(LOGICAL, name="synthetic.other")))
    with pytest.raises(IdentityError, match="invalid_namespace_registry"):
        NamespaceRegistry([LOGICAL])


def test_unknown_category_and_invalid_reservation_fail_before_allocating(monkeypatch):
    monkeypatch.setattr(allocation, "uuid4", lambda: pytest.fail("invalid input allocated an ID"))
    with pytest.raises(IdentityError, match="unregistered_object_category"):
        allocate_id("unknown", REGISTRY, lambda _identity: True)
    with pytest.raises(IdentityError, match="invalid_reservation"):
        allocate_id("logical", REGISTRY, None)


@pytest.mark.parametrize("value", [1, None, "true"])
def test_reservation_result_cannot_coerce_to_success(value):
    with pytest.raises(IdentityError, match="invalid_reservation_result"):
        allocate_id("logical", REGISTRY, lambda _identity: value)


def test_reservation_errors_are_sanitized():
    def failed(_identity: AllocatedID):
        raise OSError("secret database context")

    with pytest.raises(IdentityError) as failure:
        allocate_id("logical", REGISTRY, failed)
    assert failure.value.code == "reservation_failed"
    assert str(failure.value) == "reservation_failed" and failure.value.__cause__ is None
