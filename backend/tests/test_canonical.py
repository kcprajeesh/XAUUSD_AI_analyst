"""New synthetic conformance cases, separate from the historical six vectors."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from decimal import Decimal, Inexact, Rounded, localcontext
import random

import pytest

from app.canonical import (
    ArraySchema, CanonicalError, CanonicalLimits, Field, JSONNumber, ObjectSchema,
    Scalar, canonical_decimal, canonical_json, canonical_timestamp, parse_json,
)


LIMITS = CanonicalLimits(20_000, 10_000, 10_000, 10_000, 20_000)


def test_limits_are_required_positive_independent_and_immutable():
    with pytest.raises(TypeError):
        CanonicalLimits()
    for name in LIMITS.__dataclass_fields__:
        for value in (True, False, 0, -1, 1.0, "1", None):
            with pytest.raises(CanonicalError, match="invalid_limit:" + name):
                replace(LIMITS, **{name: value})
    with pytest.raises(FrozenInstanceError):
        LIMITS.max_document_bytes = 1


def test_numeric_lexemes_are_retained_even_for_integer_tokens():
    values = parse_json(b'[-0,1,1.2300,2e+0002,-3E-2]', LIMITS)
    assert [value.lexeme for value in values] == ["-0", "1", "1.2300", "2e+0002", "-3E-2"]
    assert all(type(value) is JSONNumber for value in values)


@pytest.mark.parametrize("document,code", [
    (b'\xef\xbb\xbf{}', "leading_bom"),
    (b'"\xff"', "invalid_utf8"),
    (b'\xff\xfe{\x00}\x00', "invalid_utf8"),
    (b'{', "invalid_json"),
    (b'{} {}', "invalid_json"),
    (b'01', "invalid_json"),
    (b'"unescaped\ncontrol"', "invalid_json"),
    (b'NaN', "invalid_json_constant"),
    (b'Infinity', "invalid_json_constant"),
    (b'-Infinity', "invalid_json_constant"),
    (b'{"x":1,"x":2}', "duplicate_key"),
    (b'{"x":1,"\\u0078":2}', "duplicate_key"),
    (b'{"nested":{"x":1,"\\u0078":2}}', "duplicate_key"),
    (b'"\\ud800"', "invalid_unicode"),
    (b'"\\udfff"', "invalid_unicode"),
    (b'{"\\ud800":1}', "invalid_unicode"),
    (b'["\\ud800"]', "invalid_unicode"),
])
def test_strict_json_rejects_invalid_input(document, code):
    with pytest.raises(CanonicalError) as failure:
        parse_json(document, LIMITS)
    assert failure.value.code == code


def test_scalar_unicode_and_duplicate_detection_precede_nfc():
    assert parse_json(b'"\\ud83d\\ude00"', LIMITS) == "😀"
    assert parse_json('"\ufeff"'.encode(), LIMITS) == "\ufeff"
    result = parse_json('{"é":1,"é":2}'.encode(), LIMITS)
    assert len(result) == 2
    with pytest.raises(CanonicalError, match="invalid_document_type"):
        parse_json("{}", LIMITS)


@pytest.mark.parametrize("source,expected", [
    ("0", "0"), ("-0", "0"), ("-0.000e+0002", "0"),
    ("1.2300", "1.23"), ("-12.3400", "-12.34"),
    ("1000", "1000"), ("1000e-3", "1"),
    ("1e3", "1000"), ("1E-3", "0.001"),
    ("123.4500e-1", "12.345"), ("-12e-3", "-0.012"),
    ("0.0001000", "0.0001"), (42, "42"),
    (JSONNumber("1.200e+1"), "12"),
])
def test_exact_decimal_forms(source, expected):
    assert canonical_decimal(source, LIMITS) == expected
    assert canonical_decimal(expected, LIMITS) == expected


@pytest.mark.parametrize("value", [
    True, False, 1.25, Decimal("1.25"), None, b"1", [], {},
    "", " 1", "1 ", "+1", "01", "-01", ".1", "1.", "1_000",
    "NaN", "Infinity", "1e", "1e+", "١", JSONNumber("01"), JSONNumber(1),
])
def test_decimal_rejects_coercion_and_invalid_grammar(value):
    with pytest.raises(CanonicalError):
        canonical_decimal(value, LIMITS)


def test_all_five_limit_boundaries_and_no_zero_shortcut():
    assert parse_json(b' [0] ', replace(LIMITS, max_document_bytes=5))
    with pytest.raises(CanonicalError, match="max_document_bytes"):
        parse_json(b' [0] ', replace(LIMITS, max_document_bytes=4))
    assert canonical_decimal("12.345", replace(LIMITS, max_decimal_token_bytes=6)) == "12.345"
    with pytest.raises(CanonicalError, match="max_decimal_token_bytes"):
        canonical_decimal("12.345", replace(LIMITS, max_decimal_token_bytes=5))
    assert canonical_decimal("0.00120", replace(LIMITS, max_significand_digits=6)) == "0.0012"
    with pytest.raises(CanonicalError, match="max_significand_digits"):
        canonical_decimal("0.00120", replace(LIMITS, max_significand_digits=5))
    assert canonical_decimal("0e-0002", replace(LIMITS, max_abs_exponent=2)) == "0"
    with pytest.raises(CanonicalError, match="max_abs_exponent"):
        canonical_decimal("-0e-0003", replace(LIMITS, max_abs_exponent=2))
    assert canonical_decimal("1e3", replace(LIMITS, max_canonical_output_bytes=4)) == "1000"
    with pytest.raises(CanonicalError, match="max_canonical_output_bytes"):
        canonical_decimal("1e3", replace(LIMITS, max_canonical_output_bytes=3))
    with pytest.raises(CanonicalError, match="max_canonical_output_bytes"):
        canonical_decimal("1e1000000000", replace(LIMITS, max_abs_exponent=1_000_000_000, max_canonical_output_bytes=10))
    with pytest.raises(CanonicalError, match="max_abs_exponent"):
        canonical_decimal("0e1000000000", LIMITS)


def test_parser_applies_lexical_limits_before_schema_conversion():
    for document, changes, name in [
        (b'123', {"max_decimal_token_bytes": 2}, "max_decimal_token_bytes"),
        (b'123', {"max_significand_digits": 2}, "max_significand_digits"),
        (b'0e3', {"max_abs_exponent": 2}, "max_abs_exponent"),
    ]:
        with pytest.raises(CanonicalError, match=name):
            parse_json(document, replace(LIMITS, **changes))


def test_decimal_is_exact_under_hostile_global_decimal_context():
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        assert canonical_decimal("123456789.012345678900", LIMITS) == "123456789.0123456789"
        assert canonical_decimal("1e-34", LIMITS) == "0." + "0" * 33 + "1"


def test_seeded_decimal_value_and_idempotence_invariants():
    generator = random.Random(20261118)
    for _ in range(100):
        source = f'{generator.randrange(-10**20, 10**20)}.{generator.randrange(10**8):08d}e{generator.randrange(-25, 25):+d}'
        result = canonical_decimal(source, LIMITS)
        assert Decimal(source) == Decimal(result)
        assert canonical_decimal(result, LIMITS) == result
        assert "e" not in result.lower()


def test_large_integers_do_not_depend_on_python_string_conversion_limit():
    value = 10**5_000 + 7
    expected = "1" + "0" * 4_999 + "7"
    assert canonical_decimal(value, LIMITS) == expected
    schema = Scalar("integer", minimum=0, maximum=10**5_001)
    assert canonical_json(value, schema, LIMITS) == expected.encode()
    assert canonical_json(parse_json(expected.encode(), LIMITS), schema, LIMITS) == expected.encode()


@pytest.mark.parametrize("source,expected", [
    ("2026-11-18T12:34:56Z", "2026-11-18T12:34:56.000000Z"),
    ("2026-11-18T15:34:56+03:00", "2026-11-18T12:34:56.000000Z"),
    ("2026-11-18T18:04:56.1+05:30", "2026-11-18T12:34:56.100000Z"),
    ("2026-11-18T12:34:56.123456+00:00", "2026-11-18T12:34:56.123456Z"),
    ("0001-01-01T00:00:00Z", "0001-01-01T00:00:00.000000Z"),
    ("0001-01-02T00:00:00+23:59", "0001-01-01T00:01:00.000000Z"),
    ("9999-12-30T23:59:59-23:59", "9999-12-31T23:58:59.000000Z"),
])
def test_timestamp_normalizes_to_aware_utc_six_digits(source, expected):
    assert canonical_timestamp(source, LIMITS) == expected
    assert canonical_timestamp(expected, LIMITS) == expected


@pytest.mark.parametrize("value", [
    "2026-11-18", "2026-11-18T12:34:56", "2026-11-18T12:34Z",
    "2026-11-18 12:34:56Z", "2026-11-18T12:34:56z",
    "2026-11-18T12:34:56-00:00", "2026-11-18T12:34:56+24:00",
    "2026-11-18T12:34:56+00:60", "2026-11-18T12:34:56+03:00:01",
    "2026-11-18T12:34:60Z", "2026-11-18T12:34:56.1234567Z",
    "2026-02-30T12:34:56Z", "0000-01-01T00:00:00Z",
    "0001-01-01T00:00:00+00:01", "9999-12-31T23:59:59-00:01",
    None, True, datetime(2026, 11, 18, tzinfo=UTC),
])
def test_timestamp_rejects_ambiguity_invalid_offsets_and_overflow(value):
    with pytest.raises(CanonicalError, match="invalid_timestamp"):
        canonical_timestamp(value, LIMITS)


def test_timestamp_output_limit_is_measured_on_complete_output():
    value = "2026-11-18T12:34:56Z"
    assert len(canonical_timestamp(value, replace(LIMITS, max_canonical_output_bytes=27))) == 27
    with pytest.raises(CanonicalError, match="max_canonical_output_bytes"):
        canonical_timestamp(value, replace(LIMITS, max_canonical_output_bytes=26))


def test_schema_serialization_has_exact_escapes_opaque_text_and_omission():
    schema = ObjectSchema({
        "z": Field(Scalar("decimal"), required=True, nullable=False),
        "semantic": Field(Scalar("string", semantic_text=True), required=True, nullable=False),
        "opaque": Field(Scalar("string"), required=True, nullable=False),
        "optional": Field(Scalar("string"), required=False, nullable=True),
        "escape": Field(Scalar("string"), required=True, nullable=False),
    })
    value = {"z": JSONNumber("1.200"), "semantic": "é", "opaque": "é", "escape": '\x00\b\t\n\r\x1f"\\/😀'}
    result = canonical_json(value, schema, LIMITS)
    assert result == b'{"escape":"\\u0000\\u0008\\u0009\\u000a\\u000d\\u001f\\"\\\\/' + "😀".encode() + b'","opaque":"' + "é".encode() + b'","semantic":"' + "é".encode() + b'","z":"1.2"}'
    assert canonical_json(parse_json(result, LIMITS), schema, LIMITS) == result
    assert canonical_json(dict(reversed(list(value.items()))), schema, LIMITS) == result
    assert b'"optional":null' in canonical_json({**value, "optional": None}, schema, LIMITS)
    assert b'"optional"' not in result


def test_set_arrays_normalize_before_identity_checks_and_sort_by_bytes():
    schema = ArraySchema(Scalar("string", semantic_text=True), set_identity=())
    assert canonical_json(["z", "é", "a"], schema, LIMITS) == '["a","z","é"]'.encode()
    with pytest.raises(CanonicalError, match="duplicate_set_identity"):
        canonical_json(["é", "é"], schema, LIMITS)
    ordered = ArraySchema(Scalar("string", semantic_text=True))
    assert canonical_json(["é", "é", "a"], ordered, LIMITS) == '["é","é","a"]'.encode()
    opaque = ArraySchema(Scalar("string"), set_identity=())
    assert len(parse_json(canonical_json(["é", "é"], opaque, LIMITS), LIMITS)) == 2


def test_set_object_identity_is_distinct_from_full_element_and_sort_order():
    element = ObjectSchema({
        "id": Field(Scalar("string"), required=True, nullable=False),
        "label": Field(Scalar("string", semantic_text=True), required=True, nullable=False),
    })
    schema = ArraySchema(element, set_identity=("id",))
    value = [{"id": "b", "label": "second"}, {"id": "a", "label": "first"}]
    assert canonical_json(value, schema, LIMITS) == b'[{"id":"a","label":"first"},{"id":"b","label":"second"}]'
    with pytest.raises(CanonicalError, match="duplicate_set_identity"):
        canonical_json([{"id": "a", "label": "one"}, {"id": "a", "label": "two"}], schema, LIMITS)
    semantic_identity = ArraySchema(element, set_identity=("label",))
    with pytest.raises(CanonicalError, match="duplicate_set_identity"):
        canonical_json([{"id": "a", "label": "é"}, {"id": "b", "label": "é"}], semantic_identity, LIMITS)
    optional_identity = ObjectSchema({"id": Field(Scalar("string"), required=False, nullable=False)})
    with pytest.raises(CanonicalError, match="missing_set_identity"):
        canonical_json([{}], ArraySchema(optional_identity, set_identity=("id",)), LIMITS)


def test_integer_schema_preserves_exact_tokens_and_enforces_bounds():
    schema = Scalar("integer", minimum=-2, maximum=2)
    assert canonical_json(parse_json(b'-0', LIMITS), schema, LIMITS) == b'0'
    assert canonical_json(parse_json(b'-2', LIMITS), schema, LIMITS) == b'-2'
    for value in (True, "1", 1.0, Decimal(1), JSONNumber("1.0"), JSONNumber("1e0"), 3, -3):
        with pytest.raises(CanonicalError):
            canonical_json(value, schema, LIMITS)
    assert canonical_json(True, Scalar("boolean"), LIMITS) == b'true'
    assert canonical_json(None, Scalar("null"), LIMITS) == b'null'
    assert canonical_json("2026-11-18T12:34:56Z", Scalar("timestamp"), LIMITS) == b'"2026-11-18T12:34:56.000000Z"'


def test_output_limits_count_utf8_escapes_quotes_and_whole_containers():
    for value, expected, size in [("é", '"é"'.encode(), 4), ("\x00", b'"\\u0000"', 8)]:
        assert canonical_json(value, Scalar("string"), replace(LIMITS, max_canonical_output_bytes=size)) == expected
        with pytest.raises(CanonicalError, match="max_canonical_output_bytes"):
            canonical_json(value, Scalar("string"), replace(LIMITS, max_canonical_output_bytes=size - 1))
    for value, schema in [
        ("1000", Scalar("decimal")), (False, Scalar("boolean")), (None, Scalar("null")),
        (["a", "b"], ArraySchema(Scalar("string"))),
        (["b", "a"], ArraySchema(Scalar("string"), set_identity=())),
    ]:
        with pytest.raises(CanonicalError, match="max_canonical_output_bytes"):
            canonical_json(value, schema, replace(LIMITS, max_canonical_output_bytes=3))
    for schema in (ArraySchema(Scalar("string")), ArraySchema(Scalar("string"), set_identity=())):
        assert len(canonical_json(["a", "b"], schema, replace(LIMITS, max_canonical_output_bytes=9))) == 9
        with pytest.raises(CanonicalError, match="max_canonical_output_bytes"):
            canonical_json(["a", "b"], schema, replace(LIMITS, max_canonical_output_bytes=8))


def test_schema_unknown_missing_and_null_states_are_explicit():
    schema = ObjectSchema({"known": Field(Scalar("string"), required=True, nullable=False)})
    for value, code in [({}, "missing_field"), ({"known": None}, "null_not_allowed"),
                        ({"known": "yes", "secret_input": "DO_NOT_ECHO"}, "unknown_field")]:
        with pytest.raises(CanonicalError) as failure:
            canonical_json(value, schema, LIMITS)
        assert failure.value.code == code
        assert "secret_input" not in str(failure.value) and "DO_NOT_ECHO" not in str(failure.value)
    with pytest.raises(CanonicalError, match="invalid_unicode"):
        canonical_json("\ud800", Scalar("string"), LIMITS)
    for value, schema in [((), ArraySchema(Scalar("string"))), ([], ObjectSchema({})),
                          (1, Scalar("boolean")), (False, Scalar("null")), (1, Scalar("string"))]:
        with pytest.raises(CanonicalError):
            canonical_json(value, schema, LIMITS)


def test_schema_definitions_are_validated_and_cannot_be_changed_through_mapping():
    fields = {"known": Field(Scalar("string"), required=True, nullable=False)}
    schema = ObjectSchema(fields)
    fields["later"] = fields["known"]
    assert "later" not in schema.fields
    with pytest.raises(TypeError):
        schema.fields["later"] = fields["known"]
    for name in ("Upper", "é", "a-b", "_a", "a b"):
        with pytest.raises(CanonicalError, match="invalid_schema"):
            ObjectSchema({name: fields["known"]})
    for arguments in [dict(kind="unknown"), dict(kind=[]), dict(kind="integer"),
                      dict(kind="integer", minimum=True, maximum=2),
                      dict(kind="integer", minimum=2, maximum=1),
                      dict(kind="decimal", semantic_text=True), dict(kind="string", minimum=0)]:
        with pytest.raises(CanonicalError, match="invalid_schema"):
            Scalar(**arguments)
    with pytest.raises(CanonicalError, match="invalid_schema"):
        ArraySchema(Scalar("string"), set_identity=("id",))
    with pytest.raises(CanonicalError, match="invalid_schema"):
        ArraySchema(schema, set_identity=("unknown",))
    with pytest.raises(CanonicalError, match="invalid_schema"):
        Field(object(), required=True, nullable=False)
    with pytest.raises(CanonicalError, match="invalid_schema"):
        canonical_json({}, object(), LIMITS)


def test_every_public_primitive_requires_the_validated_limit_object():
    for operation in (
        lambda: parse_json(b'{}', None),
        lambda: canonical_decimal("1", None),
        lambda: canonical_timestamp("2026-11-18T00:00:00Z", None),
        lambda: canonical_json("text", Scalar("string"), None),
    ):
        with pytest.raises(CanonicalError, match="invalid_limits"):
            operation()
