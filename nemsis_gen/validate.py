"""Local validation of generated PCR documents.

Three independent layers, reported separately so a manifest row can say *which*
gate a record failed:

1. well-formedness  - can it be parsed at all
2. XSD structural   - does it satisfy EMSDataSet_v3.xsd and its 27 includes
3. code value sets  - is every enumerated leaf a legal national code

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

    @property
    def ok(self) -> bool:
        return bool(self.well_formed and self.xsd_valid and self.code_valid)

    def to_json(self) -> dict:
        return {
            "well_formed": self.well_formed,
            "xsd_valid": self.xsd_valid,
            "code_valid": self.code_valid,
            "errors": self.errors,
            "code_errors": self.code_errors,
        }


@lru_cache(maxsize=4)
def load_schema(schema_path: Path = DEFAULT_SCHEMA) -> etree.XMLSchema:
    """Compile the root schema. All 27 includes must sit beside it on disk."""
    return etree.XMLSchema(etree.parse(str(schema_path)))


def check_codes(root: etree._Element, registry: Registry) -> list[str]:
    """Flag enumerated leaves carrying a value outside their national value set."""
    errors: list[str] = []
    prefix = f"{{{NEMSIS_NS}}}"
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        number = el.tag.replace(prefix, "")
        values = registry.values_for(number)
        if not values:
            continue
        text = (el.text or "").strip()
        if not text:
            continue  # empty/nil is a structural question, not a value-set one
        if not registry.is_legal(number, text):
            type_name = registry.fields[number].type_name
            errors.append(f"{number}: '{text}' is not in value set {type_name}")
    return errors


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
    code_errors = check_codes(root, registry)

    return ValidationResult(
        well_formed=True,
        xsd_valid=xsd_valid,
        code_valid=not code_errors,
        errors=errors,
        code_errors=code_errors,
    )


def schematron_validate(path: Path, schematron_path: Path) -> tuple[bool, list[str]]:
    """NEMSIS business-rule layer - stricter than XSD, reported independently."""
    from lxml.isoschematron import Schematron

    sct = Schematron(etree.parse(str(schematron_path)), store_report=True)
    valid = sct.validate(etree.parse(str(path)))
    msgs = []
    if not valid and sct.validation_report is not None:
        for fail in sct.validation_report.iter("{http://purl.oclc.org/dsdl/svrl}failed-assert"):
            msgs.append(" ".join("".join(fail.itertext()).split()))
    return valid, msgs
