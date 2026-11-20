"""Isolated namespace allocation; no production registry or legacy ID changes."""

from dataclasses import dataclass
import re
from typing import Callable
from uuid import uuid4


class IdentityError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


_NAME = re.compile(r"[a-z][a-z0-9_.-]*\Z", re.ASCII)


@dataclass(frozen=True, slots=True)
class Namespace:
    name: str
    object_category: str
    owner: str
    uniqueness_scope: str

    def __post_init__(self):
        for value in (self.name, self.object_category):
            if type(value) is not str or _NAME.fullmatch(value) is None:
                raise IdentityError("invalid_namespace")
        for value in (self.owner, self.uniqueness_scope):
            if type(value) is not str or not value.strip():
                raise IdentityError("missing_namespace_ownership")


@dataclass(frozen=True, slots=True)
class NamespaceRegistry:
    entries: tuple[Namespace, ...]

    def __post_init__(self):
        if type(self.entries) is not tuple or any(type(entry) is not Namespace for entry in self.entries):
            raise IdentityError("invalid_namespace_registry")
        if len({entry.name for entry in self.entries}) != len(self.entries):
            raise IdentityError("duplicate_namespace")
        if len({entry.object_category for entry in self.entries}) != len(self.entries):
            raise IdentityError("duplicate_object_category")


@dataclass(frozen=True, slots=True)
class AllocatedID:
    value: str
    namespace: Namespace


def allocate_id(object_category: str, registry: NamespaceRegistry,
                reserve_id: Callable[[AllocatedID], bool]) -> AllocatedID:
    if type(registry) is not NamespaceRegistry or type(object_category) is not str:
        raise IdentityError("invalid_namespace_registry")
    namespace = next((entry for entry in registry.entries if entry.object_category == object_category), None)
    if namespace is None:
        raise IdentityError("unregistered_object_category")
    if not callable(reserve_id):
        raise IdentityError("invalid_reservation")
    identity = AllocatedID(f"{namespace.name}:{uuid4().hex}", namespace)
    # shortcut: reservation atomicity belongs to the callback; require transactional storage before production use.
    try:
        reserved = reserve_id(identity)
    except Exception:
        raise IdentityError("reservation_failed") from None
    if type(reserved) is not bool:
        raise IdentityError("invalid_reservation_result")
    if not reserved:
        raise IdentityError("identity_collision")
    return identity
