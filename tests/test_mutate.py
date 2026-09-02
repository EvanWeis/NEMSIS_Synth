"""Each invalid-by-design profile must fail at its own gate, and only its own.

This is the acceptance criterion that separates a useful fixture set from a pile
of broken files: the manifest says *why* a record is invalid, so a validator that
rejects it for the wrong reason is still a bug.
"""

import pytest

from nemsis_gen.generate import DEFAULT_TEMPLATE
from nemsis_gen.mutate import MUTATIONS, apply_mutation
from nemsis_gen.profiles import load_profiles
from nemsis_gen.validate import validate_bytes


@pytest.fixture(scope="module")
def valid_record() -> bytes:
    return DEFAULT_TEMPLATE.read_bytes()


def test_baseline_record_is_valid(valid_record, registry):
    assert validate_bytes(valid_record, registry=registry).ok


def test_structural_mutation_fails_xsd_only(valid_record, registry):
    data, description = apply_mutation("structural", valid_record, registry, {}, seed=7)
    result = validate_bytes(data, registry=registry)
    assert result.well_formed is True
    assert result.xsd_valid is False
    assert result.code_valid is True
    assert "element order" in description
    assert any("not expected" in e for e in result.errors)


def test_missing_required_fields_fail_xsd_only(valid_record, registry):
    data, description = apply_mutation(
        "drop_required_leaves", valid_record, registry, {"count": 3}, seed=7
    )
    result = validate_bytes(data, registry=registry)
    assert result.well_formed is True
    assert result.xsd_valid is False
    assert result.code_valid is True
    assert description.startswith("removed required elements: ")


def test_malformed_xml_fails_before_the_schema_is_consulted(valid_record, registry):
    data, description = apply_mutation("malform", valid_record, registry, {}, seed=7)
    result = validate_bytes(data, registry=registry)
    assert result.well_formed is False
    assert result.xsd_valid is None
    assert "malformed XML" in description


def test_illegal_codes_fail_the_value_set_gate(valid_record, registry):
    data, description = apply_mutation(
        "illegal_codes", valid_record, registry, {"count": 2}, seed=7
    )
    result = validate_bytes(data, registry=registry)
    assert result.code_valid is False
    assert len(result.code_errors) == 2
    assert "->" in description

    # The manifest's description must name the same fields the validator flags.
    named = {part.split(":")[0].strip() for part in description.split("injected:")[1].split(";")}
    flagged = {error.split(":")[0] for error in result.code_errors}
    assert named == flagged


def test_mutations_are_deterministic_under_a_seed(valid_record, registry):
    for name in MUTATIONS:
        first = apply_mutation(name, valid_record, registry, {}, seed=11)
        second = apply_mutation(name, valid_record, registry, {}, seed=11)
        assert first == second, name


def test_every_invalid_profile_names_a_real_mutation():
    config = load_profiles()
    for profile in config.profiles.values():
        if profile.mutation is not None:
            assert profile.mutation.name in MUTATIONS, profile.name


def test_every_profile_declares_a_rubric_level_that_exists():
    config = load_profiles()
    for profile in config.profiles.values():
        assert config.rubric_for(profile.narrative_quality)
