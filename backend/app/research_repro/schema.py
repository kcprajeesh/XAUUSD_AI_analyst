"""Closed v1 research schemas and canonical profile; no implicit defaults."""
from hashlib import sha256
from pathlib import PurePosixPath
import re
import unicodedata
from zoneinfo import ZoneInfo

from app.canonical import (
    ArraySchema, CanonicalError, CanonicalLimits, Field, JSONNumber, ObjectSchema,
    Scalar, canonical_json, parse_json,
)

LIMITS = CanonicalLimits(4_000_000, 128, 100, 100, 4_000_000)
TEXT = Scalar("string")
INT = Scalar("integer", minimum=0, maximum=2**63 - 1)
BOOL = Scalar("boolean")
TIME = Scalar("timestamp")
DECIMAL = Scalar("decimal")


def obj(**fields):
    return ObjectSchema({key: Field(value, True, False) for key, value in fields.items()})


def array(element):
    return ArraySchema(element)


STRINGS = array(TEXT)
IDENTITY = obj(path=TEXT, size=INT, sha256=TEXT)
SETTING = obj(name=TEXT, value=TEXT)
DECIMAL_SETTING = obj(name=TEXT, value=DECIMAL)
WINDOW = obj(input_start=TIME, warmup_end=TIME, evaluation_start=TIME, cutoff=TIME,
             boundary_inclusion=TEXT, candle_close_eligibility=TEXT)
TIME_POLICY = obj(broker=TEXT, broker_to_utc=TEXT, broker_to_qatar=TEXT,
                  utc_to_qatar=TEXT, qatar=TEXT, session_zones=STRINGS)
FIXED_TIME_POLICY = dict(broker="UTC+02:00_FIXED_NO_DST", broker_to_utc="subtract_two_hours",
                         broker_to_qatar="add_one_hour", utc_to_qatar="add_three_hours",
                         qatar="Asia/Qatar")
RESTRICTIONS = ["offline_only", "no_broker_execution", "no_live_integration",
                "no_parameter_optimization", "separate_owner_execution_authorization_required"]
DATASET = obj(path=TEXT, role=TEXT, timeframe=TEXT, size=INT, sha256=TEXT,
              provider=TEXT, symbol=TEXT, classification=TEXT)
STATISTICS = obj(procedure_version=TEXT, chronological_split=TEXT, untouched_holdout=TEXT,
                 repeated_inspection=TEXT, dependence_clustering=TEXT, month_blocks=TEXT,
                 multiple_comparisons=TEXT, shared_trades=TEXT, ambiguous_outcomes=TEXT,
                 censoring=TEXT, missing_intervals=TEXT, annual_session_stability=TEXT,
                 largest_winner=TEXT)
COSTS = obj(procedure_version=TEXT, spread=TEXT, commission=TEXT, slippage=TEXT,
            financing_swap=TEXT, stop_gaps=TEXT, partial_rejected_fills=TEXT, liquidity=TEXT,
            contract_specifications=TEXT, reliability_coverage=TEXT, missing_cost_policy=TEXT)
_manifest = obj(
    schema_version=TEXT, experiment_id=TEXT, attempt_id=TEXT,
    authorization=obj(reference=TEXT, operation=TEXT, scope=STRINGS),
    strategy=obj(path=TEXT, sha256=TEXT, revision=TEXT),
    configuration=obj(variants=STRINGS, values=array(SETTING), decimals=array(DECIMAL_SETTING),
                      session_policy=TEXT, gap_policy=TEXT, ambiguity_policy=TEXT, cutoff_policy=TEXT),
    datasets=array(DATASET),
    source=obj(snapshot_id=TEXT, inventory_path=TEXT, inventory_sha256=TEXT, entry_point=TEXT),
    git=obj(head_available=BOOL, head=TEXT, no_usable_baseline=BOOL,
            tracked_modifications=STRINGS, untracked_files=STRINGS),
    runtime=obj(implementation=TEXT, version=TEXT, build=TEXT, executable=IDENTITY,
                os=TEXT, architecture=TEXT, numeric=TEXT, timezone_database=TEXT),
    dependencies=obj(installed=array(SETTING), lockfiles=array(IDENTITY), non_pip=array(SETTING)),
    time_policy=TIME_POLICY, window=WINDOW,
    invocation=obj(interpreter=TEXT, arguments=STRINGS, working_directory=TEXT,
                   environment=array(SETTING), inline_script_sha256=TEXT),
    determinism=obj(randomness=BOOL, ordering=TEXT, decimals=array(DECIMAL_SETTING),
                    decimal_precision=INT, rounding=TEXT, concurrency=TEXT),
    preflight=obj(procedure_version=TEXT, required_checks=STRINGS, fail_conditions=STRINGS),
    outputs=obj(paths=STRINGS, serializer=TEXT, schema_version=TEXT, required_stages=STRINGS),
    inferential=BOOL, cost_adjusted=BOOL,
)
MANIFEST = ObjectSchema(dict(_manifest.fields) | {
    "retry_parent": Field(TEXT, False, False),
    "random_generators": Field(array(obj(generator=TEXT, seed=INT)), False, False),
    "statistical_plan": Field(STATISTICS, False, False),
    "cost_model": Field(COSTS, False, False),
})
_authorization = obj(schema_version=TEXT, reference=TEXT, date=TIME, manifest_sha256=TEXT,
                    operation=TEXT, variants=STRINGS, dataset_hashes=STRINGS,
                    window=WINDOW, restrictions=STRINGS)
AUTHORIZATION = ObjectSchema(dict(_authorization.fields) | {
    "advisory_notes": Field(STRINGS, False, False),
    "restriction_scope": Field(obj(operation=TEXT, variants=STRINGS,
                                  dataset_hashes=STRINGS, window=WINDOW), False, False),
})
SUPPORTED_RESTRICTIONS = set(RESTRICTIONS) | {"synthetic_receipt_only", "variant_a_only", "exact_scope"}
SUPPORTED_OUTPUT_CONTRACTS = {("research.canonical.v1", "research.receipt.v1")}

INVENTORY = obj(schema_version=TEXT, snapshot_id=TEXT, entries=array(IDENTITY), exclusions=STRINGS)
RECORD = obj(schema_version=TEXT, experiment_id=TEXT, attempt_id=TEXT, manifest_sha256=TEXT,
             state=TEXT, sequence=INT, previous_sha256=TEXT, observed_at=TIME,
             stages=array(obj(name=TEXT, succeeded=BOOL)),
             preflight=array(obj(name=TEXT, succeeded=BOOL)), diagnostics=array(IDENTITY),
             outputs=array(IDENTITY), output_validation=BOOL, source_postcheck=BOOL,
             dataset_postcheck=BOOL, deviations=STRINGS)
ENVIRONMENT = {"PYTHONHASHSEED", "TZ", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS",
               "MKL_NUM_THREADS", "LC_ALL", "LANG"}


def require(condition, code):
    if not condition:
        raise ValueError(code)


def relative_path(value):
    require(type(value) is str and value and "\\" not in value and ":" not in value,
            "invalid_relative_path")
    path = PurePosixPath(value)
    require(not path.is_absolute() and all(p not in {"", ".", ".."} for p in value.split("/")),
            "invalid_relative_path")
    require(path.as_posix() == value, "noncanonical_path")
    require(all(ord(c) >= 32 for c in value), "invalid_path_character")
    return value


def unique_paths(paths):
    for path in paths:
        relative_path(path)
    folded = [p.casefold() for p in paths]
    require(len(set(folded)) == len(paths), "ambiguous_or_duplicate_path")
    require(not any(b.startswith(a + "/") for a in folded for b in folded if a != b),
            "file_directory_collision")


def strict(value):
    """Reject unsupported tokens before the shared serializer can normalize them."""
    if type(value) is JSONNumber:
        require(re.fullmatch(r"-?(0|[1-9][0-9]*)", value.lexeme) is not None, "json_float_token")
        return int(value.lexeme)
    if type(value) is str:
        require(not any(0xD800 <= ord(c) <= 0xDFFF for c in value), "surrogate")
        require(unicodedata.is_normalized("NFC", value), "non_nfc")
    elif type(value) is dict:
        require(all(type(k) is str and k.isascii() for k in value), "non_ascii_key")
        return {strict(k): strict(v) for k, v in value.items()}
    elif type(value) is list:
        return [strict(v) for v in value]
    else:
        require(value is None or type(value) in {bool, int}, "unsupported_value")
    return value


def load(data):
    return strict(parse_json(data, LIMITS))


def decimal_profile(value, schema):
    if isinstance(schema, Scalar) and schema.kind == "decimal":
        require(type(value) is str and re.fullmatch(r"-?(0|[1-9][0-9]*)(?:\.[0-9]+)?", value) is not None,
                "decimal_must_be_plain_string")
    elif isinstance(schema, ObjectSchema) and type(value) is dict:
        for key, child in value.items():
            if key in schema.fields and child is not None:
                decimal_profile(child, schema.fields[key].schema)
    elif isinstance(schema, ArraySchema) and type(value) is list:
        for child in value:
            decimal_profile(child, schema.element)


def canonical(value, schema):
    value = strict(value)
    decimal_profile(value, schema)
    if schema == INVENTORY:
        value = dict(value)
        unique_paths([entry["path"] for entry in value["entries"]])
        value["entries"] = sorted(value["entries"], key=lambda entry: entry["path"])
    return canonical_json(value, schema, LIMITS)


def digest(value, schema):
    return sha256(canonical(value, schema)).hexdigest()


def validate(value, schema):
    # Schema validation and normalization use the shared primitives after strict rejection.
    value = load(canonical(value, schema))
    require(value["schema_version"] == "research.v1", "schema_version")
    return value


def hash_text(value):
    require(type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None, "invalid_digest")


def identifiers(value):
    for key in ("experiment_id", "attempt_id"):
        require(re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value[key]) is not None, "invalid_identity")


def nonempty_unique(values):
    require(values and all(values) and len(values) == len(set(values)), "empty_or_duplicate_list")


def manifest(value):
    m = validate(value, MANIFEST)
    identifiers(m)
    if "retry_parent" in m:
        require(re.fullmatch(r"[A-Za-z0-9_-]{1,100}", m["retry_parent"]) is not None
                and m["retry_parent"] != m["attempt_id"], "retry_parent")
    require(m["authorization"]["reference"] and m["authorization"]["operation"], "authorization_scope")
    nonempty_unique(m["authorization"]["scope"])
    nonempty_unique(m["configuration"]["variants"])
    require(set(m["configuration"]["variants"]) <= {"A", "B", "C"}, "variant")
    require(m["datasets"], "missing_datasets")
    unique_paths([d["path"] for d in m["datasets"]])
    for d in m["datasets"]:
        hash_text(d["sha256"])
        require(d["provider"] == "Alpari MT5 Demo" and d["symbol"] == "XAUUSD_i", "historical_identity")
        require(d["timeframe"] in {"H1", "M15", "Daily", "H4"}, "timeframe")
        require(d["classification"] in {"included", "excluded"}, "classification")
        require(d["timeframe"] in {"H1", "M15"} or d["classification"] == "excluded", "disabled_timeframe")
        require(d["role"], "dataset_role")
    require(any(d["classification"] == "included" for d in m["datasets"]), "no_included_data")
    for k, expected in FIXED_TIME_POLICY.items():
        require(m["time_policy"][k] == expected, "time_policy")
    nonempty_unique(m["time_policy"]["session_zones"])
    for zone in m["time_policy"]["session_zones"]:
        ZoneInfo(zone)
    w = m["window"]
    require(w["input_start"] <= w["warmup_end"] <= w["evaluation_start"] < w["cutoff"], "window_order")
    require(w["boundary_inclusion"] and w["candle_close_eligibility"], "boundary_rules")
    for entries in (m["configuration"]["values"] + m["configuration"]["decimals"],
                    m["determinism"]["decimals"],
                    m["dependencies"]["installed"] + m["dependencies"]["non_pip"]):
        names = [e["name"] for e in entries]
        require(all(names) and len(names) == len(set(names)), "duplicate_or_empty_setting_name")
    unique_paths([e["path"] for e in m["dependencies"]["lockfiles"]])
    require((m["outputs"]["serializer"], m["outputs"]["schema_version"])
            in SUPPORTED_OUTPUT_CONTRACTS, "unsupported_output_contract")
    require(all(p.startswith("outputs/") for p in m["outputs"]["paths"]), "output_location")
    g = m["git"]
    for group, fields in ((m["runtime"], ("implementation", "version", "build", "os", "architecture", "numeric", "timezone_database")),
                          (m["configuration"], ("session_policy", "gap_policy", "ambiguity_policy", "cutoff_policy")),
                          (m["determinism"], ("ordering", "rounding", "concurrency")),
                          (m["preflight"], ("procedure_version",)),
                          (m["outputs"], ("serializer", "schema_version")),
                          (m["strategy"], ("revision",))):
        require(all(group[k] for k in fields), "missing_semantic_value")
    for key in ("statistical_plan", "cost_model"):
        if key in m:
            require(all(m[key].values()), "empty_plan_value")
    if "random_generators" in m:
        nonempty_unique([v["generator"] for v in m["random_generators"]])
    require(g["head_available"] == bool(g["head"]) and g["no_usable_baseline"] != g["head_available"], "git_state")
    require(not g["head"] or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", g["head"]), "git_head")
    for paths in (g["tracked_modifications"], g["untracked_files"], m["outputs"]["paths"]):
        unique_paths(paths)
    for item in [m["strategy"], *m["dependencies"]["lockfiles"]]:
        relative_path(item["path"])
        hash_text(item["sha256"])
    hash_text(m["runtime"]["executable"]["sha256"])
    s = m["source"]
    require(s["inventory_path"] == "inventory.json" and s["snapshot_id"], "source_identity")
    relative_path(s["entry_point"])
    hash_text(s["inventory_sha256"])
    require(m["determinism"]["decimal_precision"] > 0, "decimal_precision")
    require(m["determinism"]["rounding"] in {"ROUND_CEILING", "ROUND_DOWN", "ROUND_FLOOR", "ROUND_HALF_DOWN",
            "ROUND_HALF_EVEN", "ROUND_HALF_UP", "ROUND_UP", "ROUND_05UP"}, "decimal_rounding")
    inv = m["invocation"]
    require(inv["interpreter"] == m["runtime"]["executable"]["path"], "interpreter_identity")
    require(inv["arguments"] and inv["working_directory"], "invocation")
    names = [s["name"] for s in inv["environment"]]
    require(len(names) == len(set(names)) and set(names) <= ENVIRONMENT, "environment_allowlist")
    if inv["inline_script_sha256"]:
        hash_text(inv["inline_script_sha256"])
    for present, key in ((m["determinism"]["randomness"], "random_generators"),
                         (m["inferential"], "statistical_plan"), (m["cost_adjusted"], "cost_model")):
        require(present == (key in m), "conditional_field:" + key)
        if present:
            require(m[key], "empty_conditional")
    if m["cost_adjusted"]:
        require(m["cost_model"]["missing_cost_policy"] == "reject_net_claim", "missing_costs")
    for values in (m["preflight"]["required_checks"], m["preflight"]["fail_conditions"],
                   m["outputs"]["paths"], m["outputs"]["required_stages"]):
        nonempty_unique(values)
    require(not any(p.split('/')[0] in {"manifest.json", "authorization.json", "inventory.json", "records", "snapshot", "datasets"}
                    for p in m["outputs"]["paths"]), "reserved_output_path")
    return m


def authorize(m, value):
    a = validate(value, AUTHORIZATION)
    hash_text(a["manifest_sha256"])
    expected = dict(reference=m["authorization"]["reference"], manifest_sha256=digest(m, MANIFEST),
                    operation=m["authorization"]["operation"], variants=m["configuration"]["variants"],
                    dataset_hashes=[d["sha256"] for d in m["datasets"]], window=m["window"])
    for key, item in expected.items():
        require(a[key] == item, "authorization_mismatch:" + key)
    nonempty_unique(a["restrictions"])
    restrictions = set(a["restrictions"])
    require(restrictions <= SUPPORTED_RESTRICTIONS, "unsupported_restriction")
    require(set(RESTRICTIONS) <= restrictions, "missing_restrictions")
    if "synthetic_receipt_only" in restrictions:
        require(m["authorization"]["operation"] == "synthetic_receipt", "restricted_operation")
    if "variant_a_only" in restrictions:
        require(m["configuration"]["variants"] == ["A"], "restricted_variants")
    require(("exact_scope" in restrictions) == ("restriction_scope" in a), "restriction_scope_required")
    if "exact_scope" in restrictions:
        for key in ("operation", "variants", "dataset_hashes", "window"):
            require(a["restriction_scope"][key] == expected[key], "restricted_scope:" + key)
    return a

# Only this small synthetic receipt contract is supported; real report adapters need later approval.
OUTPUT = obj(schema_version=TEXT, result=TEXT)


def output_valid(data, m):
    require(m["outputs"]["serializer"] == "research.canonical.v1"
            and m["outputs"]["schema_version"] == "research.receipt.v1", "unsupported_output_contract")
    value = load(data)
    require(canonical(value, OUTPUT) == data and value["schema_version"] == "research.receipt.v1",
            "output_validation")


TRANSITIONS = {None: {"NOT_STARTED"}, "NOT_STARTED": {"RUNNING", "FAILED", "INTERRUPTED"},
               "RUNNING": {"COMPLETED", "FAILED", "INTERRUPTED"},
               "COMPLETED": set(), "FAILED": set(), "INTERRUPTED": set()}


def lifecycle(m, records):
    previous, previous_hash, previous_time = None, "", ""
    deviations = []
    require(records, "missing_lifecycle")
    for sequence, raw in enumerate(records):
        r = validate(raw, RECORD)
        require(r["experiment_id"] == m["experiment_id"] and r["attempt_id"] == m["attempt_id"]
                and r["manifest_sha256"] == digest(m, MANIFEST), "record_identity")
        require(r["sequence"] == sequence and r["previous_sha256"] == previous_hash, "record_chain")
        require(r["state"] in TRANSITIONS[previous], "illegal_transition")
        require(r["observed_at"] >= previous_time, "observation_order")
        stage_names = [s["name"] for s in r["stages"]]
        require(len(stage_names) == len(set(stage_names))
                and set(stage_names) <= set(m["outputs"]["required_stages"]), "stage_identity")
        for items in (r["outputs"], r["diagnostics"]):
            unique_paths([i["path"] for i in items])
            for item in items:
                hash_text(item["sha256"])
        checks = r["preflight"]
        check_names = [c["name"] for c in checks]
        require(len(check_names) == len(set(check_names))
                and set(check_names) <= set(m["preflight"]["required_checks"]), "preflight_identity")
        unique_paths([i["path"] for i in r["outputs"] + r["diagnostics"]])
        require(all(i["path"].startswith(("outputs/", "partial/")) for i in r["outputs"]), "output_location")
        require(all(i["path"].startswith("logs/") for i in r["diagnostics"]), "diagnostic_location")
        require(all(r["deviations"]), "empty_deviation")
        deviations.extend(r["deviations"])
        if r["state"] == "COMPLETED":
            require(set(check_names) == set(m["preflight"]["required_checks"])
                    and all(c["succeeded"] for c in checks), "incomplete_preflight")
            require(set(stage_names) == set(m["outputs"]["required_stages"])
                    and all(s["succeeded"] for s in r["stages"]), "incomplete_stages")
            require(all(r[k] for k in ("output_validation", "source_postcheck", "dataset_postcheck"))
                    and not deviations, "completion_evidence")
            require([o["path"] for o in r["outputs"]] == m["outputs"]["paths"], "output_contract")
        if r["state"] in {"FAILED", "INTERRUPTED"}:
            require(r["diagnostics"], "missing_diagnostics")
        previous, previous_hash, previous_time = r["state"], digest(r, RECORD), r["observed_at"]
    return previous
