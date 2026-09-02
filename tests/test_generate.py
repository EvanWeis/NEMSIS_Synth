"""Generation pipeline tests that make no API calls.

The model's two stages are the only part that needs the network. Everything
after them - code placement, rendering, validation - is deterministic, so it is
tested against canned stage A/B payloads.
"""

from pathlib import Path

import pytest

from nemsis_gen.generate import (
    DEFAULT_TEMPLATE,
    apply_selections,
    build_code_catalogue,
    find_path,
    load_fieldplan,
)
from nemsis_gen.render import render_dataset, value_tree_from_document
from nemsis_gen.schema_model import load_model
from nemsis_gen.validate import validate_bytes

CLINICAL = {
    "age": "64",
    "narrative": (
        "64-year-old male found seated, tripoding, in severe respiratory distress with "
        "audible wheezing and one-word dyspnea. SpO2 84% on room air. Patient unable to "
        "ambulate more than two steps without desaturating; transport by private vehicle "
        "was unsafe given the need for continuous oxygen, cardiac monitoring and "
        "nebulized bronchodilator therapy en route."
    ),
    "vitals": [
        {
            "sbp": "138",
            "heart_rate": "112",
            "spo2": "84",
            "respiratory_rate": "32",
            "pain_score": "0",
        },
        {
            "sbp": "132",
            "heart_rate": "98",
            "spo2": "94",
            "respiratory_rate": "24",
            "pain_score": "0",
        },
    ],
    "medications": [
        {
            "medication": "albuterol",
            "dosage": "2.5",
            "dosage_units": "milligrams",
            "route": "nebulized",
        }
    ],
    "procedures": [{"procedure": "IV access", "attempts": "1"}],
}


@pytest.fixture(scope="session")
def model():
    return load_model()


def _codes(registry) -> dict:
    """Pick real codes off the registry, the way stage B is meant to."""

    def first(field: str) -> str:
        return registry.values_for(field)[0].code

    return {
        "singletons": {
            "eDispatch.01": first("eDispatch.01"),
            "eSituation.11": first("eSituation.11"),
            "ePatient.13": first("ePatient.13"),
            "eDisposition.32": first("eDisposition.32"),
        },
        "repeating_singletons": {"eSituation.10": [first("eSituation.10")]},
        "groups": {
            "eVitals.VitalGroup": [
                {"eVitals.26": first("eVitals.26")},
                {"eVitals.26": first("eVitals.26")},
            ],
            "eMedications.MedicationGroup": [{"eMedications.03": first("eMedications.03")}],
            "eProcedures.ProcedureGroup": [{"eProcedures.03": first("eProcedures.03")}],
        },
    }


def test_field_paths_are_derived_from_the_schema(model):
    assert find_path(model, "eVitals.26") == ["eVitals", "eVitals.VitalGroup", "eVitals.26"]
    assert find_path(model, "ePatient.15") == ["ePatient", "ePatient.AgeGroup", "ePatient.15"]
    assert find_path(model, "nonsense.99") is None


def test_every_planned_coded_field_has_a_value_set_and_a_path(registry, model):
    plan = load_fieldplan()
    for field in plan.coded_fields():
        assert field in registry.fields, field
        assert registry.values_for(field), f"{field} has no candidates to choose from"
        assert find_path(model, field), f"{field} is not locatable in the document tree"


def test_catalogue_lists_labels_the_model_can_match_against(registry):
    catalogue = build_code_catalogue(registry, load_fieldplan())
    assert "Albuterol (Proventil, Ventolin, AccuNeb)" in catalogue
    assert "### eSituation.11" in catalogue


def test_generated_record_is_schema_valid(registry, model):
    sections, demographic, _uuid = value_tree_from_document(
        DEFAULT_TEMPLATE.read_bytes(), model=model
    )
    unknown = apply_selections(
        sections, CLINICAL, _codes(registry), load_fieldplan(), model, registry
    )
    assert unknown == []

    xml, report = render_dataset(sections, demographic, model=model)
    assert report.unknown_keys == []

    result = validate_bytes(xml, registry=registry)
    assert result.ok, (result.errors[:3], result.code_errors[:3])


def test_clinical_content_actually_lands_in_the_document(registry, model):
    sections, demographic, _uuid = value_tree_from_document(
        DEFAULT_TEMPLATE.read_bytes(), model=model
    )
    apply_selections(sections, CLINICAL, _codes(registry), load_fieldplan(), model, registry)
    xml, _ = render_dataset(sections, demographic, model=model)
    text = xml.decode("utf-8")

    assert "<eNarrative.01>" in text
    assert "transport by private vehicle" in text
    assert "<ePatient.15>64</ePatient.15>" in text
    assert text.count("<eVitals.VitalGroup>") == 2  # both sets, not just the template's one
    assert "<eVitals.06>138</eVitals.06>" in text


def test_a_code_off_the_table_is_recorded_not_silently_accepted(registry, model):
    sections, demographic, _uuid = value_tree_from_document(
        DEFAULT_TEMPLATE.read_bytes(), model=model
    )
    codes = _codes(registry)
    codes["singletons"]["eDispatch.01"] = "9999999"
    unknown = apply_selections(sections, CLINICAL, codes, load_fieldplan(), model, registry)
    assert unknown == ["eDispatch.01=9999999"]


def test_medication_code_carries_its_codetype_attribute(registry, model):
    sections, demographic, _uuid = value_tree_from_document(
        DEFAULT_TEMPLATE.read_bytes(), model=model
    )
    apply_selections(sections, CLINICAL, _codes(registry), load_fieldplan(), model, registry)
    xml, _ = render_dataset(sections, demographic, model=model)
    assert 'CodeType="9924003"' in xml.decode("utf-8")


def test_default_template_exists_and_is_valid(registry):
    assert DEFAULT_TEMPLATE.exists()
    assert validate_bytes(Path(DEFAULT_TEMPLATE).read_bytes(), registry=registry).ok
