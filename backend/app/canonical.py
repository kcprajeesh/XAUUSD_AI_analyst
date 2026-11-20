"""Isolated approved canonical primitives; no production profiles or persistence."""

from dataclasses import dataclass, fields
from datetime import UTC, datetime
import json
import re
from types import MappingProxyType
from typing import Mapping
import unicodedata


class CanonicalError(ValueError):
    """A typed failure whose message never includes supplied document content."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class CanonicalLimits:
    max_document_bytes: int
    max_decimal_token_bytes: int
    max_significand_digits: int
    max_abs_exponent: int
    max_canonical_output_bytes: int

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if type(value) is not int or value <= 0:
                raise CanonicalError("invalid_limit:" + field.name)


@dataclass(frozen=True, slots=True)
class JSONNumber:
    lexeme: str


_DECIMAL = re.compile(r"-?(0|[1-9][0-9]*)(?:\.([0-9]+))?(?:[eE]([+-]?[0-9]+))?\Z", re.ASCII)
_INTEGER = re.compile(r"-?(0|[1-9][0-9]*)\Z", re.ASCII)
_FIELD = re.compile(r"[a-z][a-z0-9_]*\Z", re.ASCII)
_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])\Z", re.ASCII,
)


def _limit(size: int, maximum: int, name: str):
    if size > maximum:
        raise CanonicalError("limit_exceeded:" + name)


def _limits(value):
    if type(value) is not CanonicalLimits:
        raise CanonicalError("invalid_limits")


def _integer_text(value: int, maximum: int) -> str:
    # Chunk conversion avoids Python's process-wide integer/string digit limit.
    negative = value < 0
    value = abs(value)
    chunks = []
    while value:
        value, chunk = divmod(value, 1_000_000_000)
        chunks.append(chunk)
        _limit((len(chunks) - 1) * 9 + 1 + negative, maximum, "max_decimal_token_bytes")
    text = (str(chunks.pop()) + "".join(f"{chunk:09d}" for chunk in reversed(chunks))) if chunks else "0"
    text = ("-" if negative else "") + text
    _limit(len(text), maximum, "max_decimal_token_bytes")
    return text


def _decimal_parts(value, limits: CanonicalLimits):
    if type(value) is JSONNumber:
        text = value.lexeme
    elif type(value) is str:
        text = value
    elif type(value) is int:
        text = _integer_text(value, limits.max_decimal_token_bytes)
    else:
        raise CanonicalError("invalid_decimal_type")
    if type(text) is not str or not text.isascii():
        raise CanonicalError("invalid_decimal")
    _limit(len(text), limits.max_decimal_token_bytes, "max_decimal_token_bytes")
    match = _DECIMAL.fullmatch(text)
    if match is None:
        raise CanonicalError("invalid_decimal")
    integer, fraction, exponent_text = match.groups()
    fraction = fraction or ""
    _limit(len(integer) + len(fraction), limits.max_significand_digits, "max_significand_digits")
    exponent = 0
    if exponent_text:
        for digit in exponent_text.lstrip("+-"):
            exponent = exponent * 10 + ord(digit) - ord("0")
            _limit(exponent, limits.max_abs_exponent, "max_abs_exponent")
        if exponent_text.startswith("-"):
            exponent = -exponent
    return text.startswith("-"), integer + fraction, exponent - len(fraction)


def canonical_decimal(value, limits: CanonicalLimits) -> str:
    _limits(limits)
    negative, digits, exponent = _decimal_parts(value, limits)
    digits = digits.lstrip("0")
    if not digits:
        result = "0"
    else:
        trimmed = digits.rstrip("0")
        exponent += len(digits) - len(trimmed)
        digits = trimmed
        split = len(digits) + exponent
        size = len(digits) + exponent if exponent >= 0 else (len(digits) + 1 if split > 0 else 2 - exponent)
        _limit(size + negative, limits.max_canonical_output_bytes, "max_canonical_output_bytes")
        if exponent >= 0:
            result = digits + "0" * exponent
        elif split > 0:
            result = digits[:split] + "." + digits[split:]
        else:
            result = "0." + "0" * -split + digits
        if negative:
            result = "-" + result
    _limit(len(result), limits.max_canonical_output_bytes, "max_canonical_output_bytes")
    return result


def canonical_timestamp(value, limits: CanonicalLimits) -> str:
    _limits(limits)
    if type(value) is not str or _TIMESTAMP.fullmatch(value) is None or value.endswith("-00:00"):
        raise CanonicalError("invalid_timestamp")
    try:
        instant = datetime.fromisoformat(value).astimezone(UTC)
    except (ValueError, OverflowError):
        raise CanonicalError("invalid_timestamp") from None
    result = instant.isoformat(timespec="microseconds").replace("+00:00", "Z")
    _limit(len(result), limits.max_canonical_output_bytes, "max_canonical_output_bytes")
    return result


def _scalars(value):
    pending = [value]
    while pending:
        item = pending.pop()
        if type(item) is str:
            if any(0xD800 <= ord(character) <= 0xDFFF for character in item):
                raise CanonicalError("invalid_unicode")
        elif type(item) is dict:
            pending.extend(item.keys())
            pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)


def parse_json(document: bytes, limits: CanonicalLimits):
    _limits(limits)
    if type(document) is not bytes:
        raise CanonicalError("invalid_document_type")
    _limit(len(document), limits.max_document_bytes, "max_document_bytes")
    if document.startswith(b"\xef\xbb\xbf"):
        raise CanonicalError("leading_bom")

    def pairs(entries):
        result = {}
        for key, value in entries:
            if key in result:
                raise CanonicalError("duplicate_key")
            result[key] = value
        return result

    def number(token):
        value = JSONNumber(token)
        _decimal_parts(value, limits)
        return value

    def constant(_value):
        raise CanonicalError("invalid_json_constant")

    try:
        text = document.decode("utf-8", errors="strict")
        result = json.loads(text, object_pairs_hook=pairs, parse_int=number,
                            parse_float=number, parse_constant=constant)
        _scalars(result)
        return result
    except UnicodeDecodeError:
        raise CanonicalError("invalid_utf8") from None
    except (json.JSONDecodeError, RecursionError):
        raise CanonicalError("invalid_json") from None


@dataclass(frozen=True, slots=True)
class Scalar:
    kind: str
    minimum: int | None = None
    maximum: int | None = None
    semantic_text: bool = False

    def __post_init__(self):
        if type(self.kind) is not str or self.kind not in {"string", "decimal", "timestamp", "integer", "boolean", "null"}:
            raise CanonicalError("invalid_schema")
        if type(self.semantic_text) is not bool or (self.semantic_text and self.kind != "string"):
            raise CanonicalError("invalid_schema")
        if self.kind == "integer":
            if type(self.minimum) is not int or type(self.maximum) is not int or self.minimum > self.maximum:
                raise CanonicalError("invalid_schema")
        elif self.minimum is not None or self.maximum is not None:
            raise CanonicalError("invalid_schema")


@dataclass(frozen=True, slots=True)
class Field:
    schema: "Scalar | ObjectSchema | ArraySchema"
    required: bool
    nullable: bool

    def __post_init__(self):
        if type(self.required) is not bool or type(self.nullable) is not bool:
            raise CanonicalError("invalid_schema")
        _schema(self.schema)


@dataclass(frozen=True, slots=True)
class ObjectSchema:
    fields: Mapping[str, Field]

    def __post_init__(self):
        if not isinstance(self.fields, Mapping):
            raise CanonicalError("invalid_schema")
        for name, field in self.fields.items():
            if type(name) is not str or _FIELD.fullmatch(name) is None or type(field) is not Field:
                raise CanonicalError("invalid_schema")
        object.__setattr__(self, "fields", MappingProxyType(dict(self.fields)))


@dataclass(frozen=True, slots=True)
class ArraySchema:
    element: "Scalar | ObjectSchema | ArraySchema"
    # None declares order; () declares whole-element set identity; names select object fields.
    set_identity: tuple[str, ...] | None = None

    def __post_init__(self):
        _schema(self.element)
        identity = self.set_identity
        if identity is not None:
            if type(identity) is not tuple or any(type(name) is not str for name in identity):
                raise CanonicalError("invalid_schema")
            if len(set(identity)) != len(identity):
                raise CanonicalError("invalid_schema")
            if identity and (type(self.element) is not ObjectSchema or any(name not in self.element.fields for name in identity)):
                raise CanonicalError("invalid_schema")


def _schema(value):
    if type(value) not in (Scalar, ObjectSchema, ArraySchema):
        raise CanonicalError("invalid_schema")


class _Output:
    def __init__(self, limits):
        self.maximum = limits.max_canonical_output_bytes
        self.buffer = bytearray()

    def add(self, value: bytes):
        _limit(len(self.buffer) + len(value), self.maximum, "max_canonical_output_bytes")
        self.buffer.extend(value)


def _quote(value: str, limits: CanonicalLimits) -> bytes:
    result = _Output(limits)
    result.add(b'"')
    for character in value:
        point = ord(character)
        if 0xD800 <= point <= 0xDFFF:
            raise CanonicalError("invalid_unicode")
        if character in {'"', "\\"}:
            result.add(("\\" + character).encode("utf-8"))
        elif point < 0x20:
            result.add(f"\\u{point:04x}".encode("ascii"))
        else:
            result.add(character.encode("utf-8"))
    result.add(b'"')
    return bytes(result.buffer)


def _bounded_integer(value, schema: Scalar, limits: CanonicalLimits) -> bytes:
    if type(value) is int:
        text = _integer_text(value, limits.max_decimal_token_bytes)
    elif type(value) is JSONNumber and type(value.lexeme) is str and _INTEGER.fullmatch(value.lexeme):
        text = value.lexeme
    else:
        raise CanonicalError("invalid_integer")
    _decimal_parts(JSONNumber(text), limits)
    number = 0
    cap = max(abs(schema.minimum), abs(schema.maximum))
    for digit in text.lstrip("-"):
        number = number * 10 + ord(digit) - ord("0")
        if number > cap:
            raise CanonicalError("integer_out_of_bounds")
    if text.startswith("-"):
        number = -number
    if not schema.minimum <= number <= schema.maximum:
        raise CanonicalError("integer_out_of_bounds")
    result = ("0" if number == 0 else text).encode("ascii")
    _limit(len(result), limits.max_canonical_output_bytes, "max_canonical_output_bytes")
    return result


def _field(value, field: Field, limits: CanonicalLimits) -> bytes:
    if value is None:
        if not field.nullable:
            raise CanonicalError("null_not_allowed")
        return b"null"
    return _encode(value, field.schema, limits)


def _encode(value, schema, limits: CanonicalLimits) -> bytes:
    _schema(schema)
    if type(schema) is Scalar:
        if schema.kind in {"string", "timestamp", "decimal"}:
            if schema.kind == "decimal":
                text = canonical_decimal(value, limits)
            elif schema.kind == "timestamp":
                text = canonical_timestamp(value, limits)
            elif type(value) is str:
                text = unicodedata.normalize("NFC", value) if schema.semantic_text else value
            else:
                raise CanonicalError("invalid_string")
            return _quote(text, limits)
        if schema.kind == "integer":
            return _bounded_integer(value, schema, limits)
        if schema.kind == "boolean" and type(value) is bool:
            return b"true" if value else b"false"
        if schema.kind == "null" and value is None:
            return b"null"
        raise CanonicalError("invalid_scalar")

    result = _Output(limits)
    if type(schema) is ObjectSchema:
        if type(value) is not dict:
            raise CanonicalError("invalid_object")
        if any(type(key) is not str or key not in schema.fields for key in value):
            raise CanonicalError("unknown_field")
        if any(field.required and name not in value for name, field in schema.fields.items()):
            raise CanonicalError("missing_field")
        result.add(b"{")
        for ordinal, name in enumerate(sorted(value, key=lambda key: key.encode("utf-8"))):
            if ordinal:
                result.add(b",")
            result.add(_quote(name, limits))
            result.add(b":")
            result.add(_field(value[name], schema.fields[name], limits))
        result.add(b"}")
    else:
        if type(value) is not list:
            raise CanonicalError("invalid_array")
        result.add(b"[")
        elements = []
        identities = set()
        size = 2
        identity_schema = None
        if schema.set_identity:
            identity_schema = ObjectSchema({name: schema.element.fields[name] for name in schema.set_identity})
        for ordinal, element in enumerate(value):
            encoded = _encode(element, schema.element, limits)
            if schema.set_identity is not None:
                size += len(encoded) + bool(ordinal)
                _limit(size, limits.max_canonical_output_bytes, "max_canonical_output_bytes")
                if schema.set_identity:
                    if any(name not in element for name in schema.set_identity):
                        raise CanonicalError("missing_set_identity")
                    identity = _encode({name: element[name] for name in schema.set_identity}, identity_schema, limits)
                else:
                    identity = encoded
                if identity in identities:
                    raise CanonicalError("duplicate_set_identity")
                identities.add(identity)
                elements.append(encoded)
            else:
                if ordinal:
                    result.add(b",")
                result.add(encoded)
        if schema.set_identity is not None:
            return b"[" + b",".join(sorted(elements)) + b"]"
        result.add(b"]")
    return bytes(result.buffer)


def canonical_json(value, schema: Scalar | ObjectSchema | ArraySchema, limits: CanonicalLimits) -> bytes:
    _limits(limits)
    try:
        result = _encode(value, schema, limits)
        _limit(len(result), limits.max_canonical_output_bytes, "max_canonical_output_bytes")
        return result
    except RecursionError:
        raise CanonicalError("invalid_nesting") from None
