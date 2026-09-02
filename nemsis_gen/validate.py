"""Local validation of generated PCR documents.

Three independent layers, reported separately so a manifest row can say *which*
gate a record failed:

1. well-formedness  - can it be parsed at all
2. XSD structural   - does it satisfy EMSDataSet_v3.xsd and its 27 includes
3. code value sets  - is every XSD-enumerated leaf a legal national code

Plus one advisory signal that is deliberately *not* a gate: defined-list
membership. Fields like eProcedures.03 and eSituation.11 draw on external
vocabularies (SNOMED, ICD-10) whose XSD types accept any well-formed code, and
NEMSIS's published Defined Lists are a curated subset rather than a closed
enumeration - the official sample corpus itself sits outside them most of the
time. So a code off the list is worth reporting (the generator should be
selecting from the list) but is not invalid.

The Schematron business-rule layer shipped with the sample package is a fourth,
stricter gate; see ``schematron_validate``.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from functools import lru_cache
from pathlib import Path

from lxml import etree

from .valuesets import Registry, load_registry

NEMSIS_NS = "http://www.nemsis.org"
DEFAULT_SCHEMA = Path(__file__).resolve().parent.parent / "reference" / "xsd" / "EMSDataSet_v3.xsd"


@dataclass
class ValidationResult:
    well_formed: bool
    xsd_valid: bool | None  # None when parsing failed, so XSD never ran
    code_valid: bool | None
    errors: list[str] = dc_field(default_factory=list)
    code_errors: list[str] = dc_field(default_factory=list)
    defined_list_warnings: list[str] = dc_field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.well_formed and self.xsd_valid and self.code_valid)

    def to_json(self) -> dict:
        return {
            "ok": self.ok,
            "well_formed": self.well_formed,
            "xsd_valid": self.xsd_valid,
            "code_valid": self.code_valid,
            "errors": self.errors,
            "code_errors": self.code_errors,
            "defined_list_warnings": self.defined_list_warnings,
        }


@lru_cache(maxsize=4)
def load_schema(schema_path: Path = DEFAULT_SCHEMA) -> etree.XMLSchema:
    """Compile the root schema. All 27 includes must sit beside it on disk."""
    return etree.XMLSchema(etree.parse(str(schema_path)))


def check_codes(root: etree._Element, registry: Registry) -> tuple[list[str], list[str]]:
    """Check coded leaves. Returns (hard errors, defined-list advisories)."""
    errors: list[str] = []
    warnings: list[str] = []
    prefix = f"{{{NEMSIS_NS}}}"
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        number = el.tag.replace(prefix, "")
        field = registry.fields.get(number)
        if field is None:
            continue
        text = (el.text or "").strip()
        if not text:
            continue  # empty/nil is a structural question, not a value-set one

        if field.defined_list is not None:
            values = registry.values_for(number)
            if values and not any(v.code == text for v in values):
                warnings.append(
                    f"{number}: '{text}' is outside the {field.defined_list} defined list"
                )
            continue

        if field.type_name is None or not registry.types.get(field.type_name):
            continue
        if not registry.is_legal(number, text):
            errors.append(f"{number}: '{text}' is not in value set {field.type_name}")
    return errors, warnings


def validate_file(
    path: Path,
    schema_path: Path = DEFAULT_SCHEMA,
    registry: Registry | None = None,
) -> ValidationResult:
    return validate_bytes(path.read_bytes(), schema_path=schema_path, registry=registry)


def validate_bytes(
    data: bytes,
    schema_path: Path = DEFAULT_SCHEMA,
    registry: Registry | None = None,
) -> ValidationResult:
    try:
        root = etree.fromstring(data)
    except etree.XMLSyntaxError as exc:
        return ValidationResult(False, None, None, errors=[f"XMLSyntaxError: {exc}"])

    schema = load_schema(schema_path)
    xsd_valid = schema.validate(root.getroottree())
    errors = [f"line {e.line}: {e.message}" for e in schema.error_log]

    registry = registry or load_registry()
    code_errors, warnings = check_codes(root, registry)

    return ValidationResult(
        well_formed=True,
        xsd_valid=xsd_valid,
        code_valid=not code_errors,
        errors=errors,
        code_errors=code_errors,
        defined_list_warnings=warnings,
    )


def schematron_validate(path: Path, rules_path: Path | None = None):
    """NEMSIS business-rule layer - reported independently of the three gates.

    Delegates to :mod:`nemsis_gen.schematron`, which drives the ISO XSLT2 pipeline
    through Saxon. lxml's own isoschematron cannot be used here: the NEMSIS rules
    declare ``queryBinding="xslt2"`` and it refuses them outright.
    """
    from .schematron import DEFAULT_RULES
    from .schematron import validate as run_schematron

    return run_schematron(path, rules_path or DEFAULT_RULES)
