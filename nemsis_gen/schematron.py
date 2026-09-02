"""Schematron business-rule validation - the layer XSD cannot express.

XSD checks structure and value sets. It cannot say "if a Not Value is present the
element must be empty" or "a procedure time must fall inside the incident window".
Those are Schematron rules, and they are much closer to what a QA tool actually
enforces.

Two things make this awkward, both discovered rather than assumed:

1. **NEMSIS Schematron is `queryBinding="xslt2"`.** ``lxml.isoschematron`` is
   XSLT 1.0 only and refuses to compile it outright. So this module drives the
   official ISO skeleton pipeline through Saxon (``saxonche``) instead:
   ``iso_dsdl_include`` -> ``iso_abstract_expand`` -> ``iso_svrl_for_xslt2``
   produces a validator stylesheet, which is then run against the instance to
   yield an SVRL report.

2. **The 187 national rules are not published as Schematron source.** The public
   repo ships a *sample* rule set (8 asserts, covering nil/NV/PN consistency), the
   dev kit, and a 196-case test corpus with expected SVRL output - but not the
   rules that corpus exercises. Point ``rules_path`` at a state or agency rule set
   to check against real business rules; the bundled sample is what is available
   out of the box.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from functools import lru_cache
from pathlib import Path

from lxml import etree

SVRL_NS = "http://purl.oclc.org/dsdl/svrl"
SCHEMATRON_DIR = Path(__file__).resolve().parent.parent / "reference" / "schematron"
ISO_DIR = SCHEMATRON_DIR / "iso"
DEFAULT_RULES = SCHEMATRON_DIR / "SampleEMSDataSet.sch"

PIPELINE = ("iso_dsdl_include.xsl", "iso_abstract_expand.xsl", "iso_svrl_for_xslt2.xsl")


class SchematronUnavailable(RuntimeError):
    """Saxon is not installed, so XSLT2 Schematron cannot run."""


@dataclass
class Assertion:
    rule_id: str
    role: str
    message: str
    location: str

    @property
    def is_error(self) -> bool:
        return "ERROR" in self.role.upper()

    def to_json(self) -> dict:
        return {
            "id": self.rule_id,
            "role": self.role,
            "message": self.message,
            "location": self.location,
        }


@dataclass
class SchematronResult:
    ran: bool
    rules: str = ""
    failures: list[Assertion] = dc_field(default_factory=list)
    error: str = ""

    @property
    def errors(self) -> list[Assertion]:
        return [a for a in self.failures if a.is_error]

    @property
    def ok(self) -> bool:
        return self.ran and not self.errors

    def to_json(self) -> dict:
        return {
            "ran": self.ran,
            "rules": self.rules,
            "ok": self.ok,
            "error": self.error,
            "failures": [a.to_json() for a in self.failures],
        }


@lru_cache(maxsize=4)
def compile_rules(rules_path: Path = DEFAULT_RULES, iso_dir: Path = ISO_DIR) -> str:
    """Run the ISO skeleton pipeline to turn a .sch into a validator stylesheet."""
    try:
        from saxonche import PySaxonProcessor
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise SchematronUnavailable(
            "saxonche is required for xslt2 Schematron: pip install saxonche"
        ) from exc

    with PySaxonProcessor(license=False) as processor:
        xslt = processor.new_xslt30_processor()
        current = rules_path.read_text(encoding="utf-8")
        for stage in PIPELINE:
            executable = xslt.compile_stylesheet(stylesheet_file=str(iso_dir / stage))
            # cwd matters: the skeleton resolves sch:include relative to the rules.
            document = processor.parse_xml(xml_text=current)
            current = executable.transform_to_string(xdm_node=document)
            if current is None:
                raise SchematronUnavailable(f"ISO pipeline stage {stage} produced no output")
    return current


def validate(
    xml_path: Path,
    rules_path: Path = DEFAULT_RULES,
    iso_dir: Path = ISO_DIR,
) -> SchematronResult:
    """Validate one document, returning every failed assertion with its rule id."""
    try:
        validator_xslt = compile_rules(rules_path, iso_dir)
    except SchematronUnavailable as exc:
        return SchematronResult(ran=False, rules=rules_path.name, error=str(exc))

    from saxonche import PySaxonProcessor

    try:
        with PySaxonProcessor(license=False) as processor:
            xslt = processor.new_xslt30_processor()
            executable = xslt.compile_stylesheet(stylesheet_text=validator_xslt)
            svrl = executable.transform_to_string(source_file=str(xml_path))
    except Exception as exc:  # noqa: BLE001 - engine failure is a result, not a crash
        return SchematronResult(ran=False, rules=rules_path.name, error=str(exc)[:300])

    if not svrl:
        return SchematronResult(ran=False, rules=rules_path.name, error="empty SVRL report")

    return SchematronResult(
        ran=True, rules=rules_path.name, failures=parse_svrl(svrl.encode("utf-8"))
    )


def parse_svrl(svrl: bytes) -> list[Assertion]:
    report = etree.fromstring(svrl)
    failures = []
    for node in report.iter(f"{{{SVRL_NS}}}failed-assert", f"{{{SVRL_NS}}}successful-report"):
        failures.append(
            Assertion(
                rule_id=node.get("id") or "",
                role=node.get("role") or "",
                message=" ".join("".join(node.itertext()).split()),
                location=node.get("location") or "",
            )
        )
    return failures
