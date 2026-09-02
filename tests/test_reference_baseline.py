"""The trust anchor for everything downstream.

If these fail, the schema set and the sample corpus have drifted apart (they are
pinned together at NEMSIS tag 3.5.0.230317CP4 - see reference/xsd/VERSION.txt)
and no conclusion drawn from a *generated* file's validation result is reliable.
"""

from lxml import etree

from nemsis_gen.validate import NEMSIS_NS, check_codes, validate_file

EXPECTED_SAMPLE_COUNT = 40


def test_sample_corpus_present(sample_files):
    assert len(sample_files) == EXPECTED_SAMPLE_COUNT


def test_registry_extracted_from_xsds(registry):
    # Sanity floor, not an exact count - upstream adds codes between patch releases.
    assert len(registry.fields) > 400
    assert len(registry.all_codes()) > 2000
    assert registry.fields["eDispatch.01"].name == "Dispatch Reason"
    assert registry.fields["eDispatch.01"].usage == "Mandatory"
    assert any(v.label == "Abdominal Pain/Problems" for v in registry.values_for("eDispatch.01"))


def test_every_official_sample_passes_all_gates(sample_files, registry):
    failures = []
    for path in sample_files:
        result = validate_file(path, registry=registry)
        if not result.ok:
            failures.append((path.name, result.errors[:2], result.code_errors[:2]))
    assert not failures, failures


def test_every_code_in_the_corpus_is_in_the_derived_value_sets(sample_files, registry):
    """Proves the XSD-derived tables are complete, not just self-consistent."""
    prefix = f"{{{NEMSIS_NS}}}"
    checked = 0
    for path in sample_files:
        root = etree.parse(str(path)).getroot()
        for el in root.iter():
            if not isinstance(el.tag, str):
                continue
            if registry.values_for(el.tag.replace(prefix, "")):
                checked += 1
        assert not check_codes(root, registry), path.name
    assert checked > 5000, "corpus scan covered suspiciously few enumerated elements"
