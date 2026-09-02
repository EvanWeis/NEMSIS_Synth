"""Each gate must fail independently and for the documented reason."""

from nemsis_gen.validate import validate_bytes


def _sample_bytes(sample_files) -> bytes:
    return sample_files[0].read_bytes()


def test_malformed_xml_fails_at_the_parser_gate(sample_files, registry):
    broken = _sample_bytes(sample_files).replace(b"</eRecord>", b"</eRecordX>", 1)
    result = validate_bytes(broken, registry=registry)
    assert result.well_formed is False
    assert result.xsd_valid is None  # never got far enough to run
    assert "XMLSyntaxError" in result.errors[0]


def test_wrong_element_order_fails_xsd_not_codes(sample_files, registry):
    """eResponse before eRecord violates the PatientCareReport xs:sequence."""
    data = _sample_bytes(sample_files).decode("utf-8")
    start, end = data.index("<eRecord>"), data.index("</eRecord>") + len("</eRecord>")
    record = data[start:end]
    moved = data[:start] + data[end:]
    insert_at = moved.index("</eResponse>") + len("</eResponse>")
    reordered = moved[:insert_at] + record + moved[insert_at:]

    result = validate_bytes(reordered.encode("utf-8"), registry=registry)
    assert result.well_formed is True
    assert result.xsd_valid is False
    assert result.code_valid is True


def test_illegal_code_passes_xsd_check_only_at_the_value_set_gate(sample_files, registry):
    """A code the XSD enumerates but of the wrong list fails XSD too; this asserts
    the value-set gate reports the specific offending field either way."""
    data = _sample_bytes(sample_files).decode("utf-8")
    original = data[data.index("<eDispatch.01>") : data.index("</eDispatch.01>")]
    code = original.split(">")[-1]
    tampered = data.replace(f"<eDispatch.01>{code}<", "<eDispatch.01>9999999<", 1)

    result = validate_bytes(tampered.encode("utf-8"), registry=registry)
    assert result.code_valid is False
    assert any("eDispatch.01" in e for e in result.code_errors)
