"""The Schematron gate, checked against NEMSIS's own test corpus.

The corpus ships 196 cases with expected verdicts, so the engine can be verified
rather than trusted. Only the cases the bundled sample rule set actually covers
are asserted here - see `scripts/eval_schematron.py` for the full sweep and
`nemsis_gen/schematron.py` for why the other 179 rules are not available.
"""

from pathlib import Path

import pytest

from nemsis_gen.schematron import SchematronUnavailable, compile_rules, validate

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "reference" / "samples" / "_stale_package" / "Schematron" / "EMS" / "xml"

# The eight cases the sample rule set covers: nil / NV / PN consistency.
COVERED_ERROR_CASES = [f"EMSDataSet-nemSch_e{n:03d}_A.xml" for n in range(1, 9)]

pytestmark = pytest.mark.skipif(not CORPUS.exists(), reason="Schematron corpus not present")


@pytest.fixture(scope="module")
def compiled():
    try:
        return compile_rules()
    except SchematronUnavailable as exc:  # pragma: no cover - environment-dependent
        pytest.skip(str(exc))


def test_rules_compile_through_the_iso_xslt2_pipeline(compiled):
    assert "<xsl:stylesheet" in compiled or "<xsl:transform" in compiled


def test_official_base_case_is_clean(compiled):
    """The corpus's Base document is built to pass while firing as many rules as it can."""
    result = validate(CORPUS / "EMSDataSet--Base.xml")
    assert result.ran, result.error
    assert result.ok, [a.to_json() for a in result.errors]


@pytest.mark.parametrize("case", COVERED_ERROR_CASES)
def test_covered_error_cases_are_flagged(case, compiled):
    result = validate(CORPUS / case)
    assert result.ran, result.error
    assert result.errors, f"{case} should have failed a rule"


def test_generated_records_satisfy_the_nil_nv_pn_rules(tmp_path, registry):
    """Our null-flavour handling has to satisfy the business rules, not just XSD.

    A section marked Not Applicable is written as `xsi:nil="true" NV="7701001"`,
    and rules e001/e002 check exactly that pairing - so this is the check that
    applicability.py agrees with NEMSIS rather than merely validating.
    """
    from nemsis_gen.applicability import apply_not_applicable
    from nemsis_gen.generate import DEFAULT_TEMPLATE
    from nemsis_gen.render import render_dataset, value_tree_from_document
    from nemsis_gen.schema_model import load_model

    model = load_model()
    sections, demographic, _uuid = value_tree_from_document(
        DEFAULT_TEMPLATE.read_bytes(), model=model
    )
    apply_not_applicable(
        sections, {"is_injury": False, "is_cardiac_arrest": False}, model, registry
    )
    xml, _report = render_dataset(sections, demographic, model=model)

    path = tmp_path / "nilled.xml"
    path.write_bytes(xml)

    result = validate(path)
    assert result.ran, result.error
    assert result.ok, [a.to_json() for a in result.errors]
