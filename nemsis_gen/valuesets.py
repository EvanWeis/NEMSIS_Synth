"""Extract NEMSIS field metadata and code value sets directly from the official XSDs.

Two sources, merged into one registry:

1. **The component XSDs.** Each enumerated field's type is an ``xs:simpleType``
   whose ``xs:enumeration`` values are the national codes, annotated with their
   human-readable labels. Deriving these from the XSDs keeps codes and schema in
   lockstep and generalises across NEMSIS versions.

2. **The NEMSIS Defined Lists** (``reference/definedlists/``). A handful of
   fields draw on external clinical vocabularies that the XSDs cannot enumerate:
   ICD-10 for provider impression, RxNorm/SNOMED for medications, SNOMED for
   procedures and symptoms. NEMSIS publishes these as JSON that self-describes
   which elements it governs, so they wire in generically rather than by a
   hardcoded field map.

Together these cover every coded field, which is what lets the generator *select*
codes from a table instead of recalling them.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path

from lxml import etree

XS = "http://www.w3.org/2001/XMLSchema"
_Q = lambda tag: f"{{{XS}}}{tag}"  # noqa: E731

# eDispatch.01, ePatient.13, dAgency.01 ... but not eResponse.AgencyGroup.
FIELD_NUMBER_RE = re.compile(r"^[a-z][A-Za-z]+\.\d+$")


@dataclass(frozen=True)
class CodeValue:
    code: str
    label: str
    category: str = ""
    code_type: str = ""  # e.g. 9924003 (RxNorm) for eMedications.03


@dataclass
class DefinedList:
    """An external clinical vocabulary NEMSIS pins to specific elements."""

    name: str
    source_vocabularies: list[str]
    elements: list[str]
    values: list[CodeValue]


@dataclass
class FieldDef:
    """One NEMSIS leaf element, e.g. ``eDispatch.01``."""

    number: str
    name: str
    definition: str
    usage: str  # Mandatory | Required | Recommended | Optional
    type_name: str | None
    defined_list: str | None
    source_xsd: str
    min_occurs: int
    max_occurs: str  # int as str, or "unbounded"
    nillable: bool
    nv_types: list[str] = dc_field(default_factory=list)

    @property
    def is_enumerated(self) -> bool:
        return self.type_name is not None or self.defined_list is not None


@dataclass
class Registry:
    """Field metadata + code tables for one NEMSIS version."""

    version: str
    fields: dict[str, FieldDef]
    types: dict[str, list[CodeValue]]
    defined_lists: dict[str, DefinedList] = dc_field(default_factory=dict)

    def values_for(self, number: str) -> list[CodeValue]:
        """Legal coded values for a field number, or [] if it is not enumerated.

        Defined-list fields resolve against the external vocabulary; everything
        else against the XSD enumerations.
        """
        fd = self.fields.get(number)
        if fd is None:
            return []
        if fd.defined_list is not None:
            return self.defined_lists[fd.defined_list].values
        if fd.type_name is None:
            return []
        return self.types.get(fd.type_name, [])

    def is_legal(self, number: str, code: str) -> bool:
        """True if ``code`` is in the field's XSD value set (or it has none).

        Defined-list fields always pass here: their XSD type admits any code from
        the external vocabulary. Use ``in_defined_list`` for that softer check.
        """
        field = self.fields.get(number)
        if field is None or field.defined_list is not None:
            return True
        values = self.values_for(number)
        if not values:
            return True
        return any(v.code == code for v in values)

    def in_defined_list(self, number: str, code: str) -> bool:
        """True if ``code`` appears in the NEMSIS defined list for this field."""
        return any(v.code == code for v in self.values_for(number))

    def all_codes(self) -> set[str]:
        codes = {v.code for values in self.types.values() for v in values}
        codes |= {v.code for dl in self.defined_lists.values() for v in dl.values}
        return codes

    def to_json(self) -> dict:
        return {
            "version": self.version,
            "fields": {
                num: {
                    "name": fd.name,
                    "definition": fd.definition,
                    "usage": fd.usage,
                    "type": fd.type_name,
                    "defined_list": fd.defined_list,
                    "source_xsd": fd.source_xsd,
                    "minOccurs": fd.min_occurs,
                    "maxOccurs": fd.max_occurs,
                    "nillable": fd.nillable,
                    "nv_types": fd.nv_types,
                }
                for num, fd in sorted(self.fields.items())
            },
            "types": {
                name: [{"code": v.code, "label": v.label} for v in values]
                for name, values in sorted(self.types.items())
            },
            "defined_lists": {
                name: {
                    "source_vocabularies": dl.source_vocabularies,
                    "elements": dl.elements,
                    "values": [
                        {
                            "code": v.code,
                            "label": v.label,
                            "category": v.category,
                            "code_type": v.code_type,
                        }
                        for v in dl.values
                    ],
                }
                for name, dl in sorted(self.defined_lists.items())
            },
        }


def _text(node: etree._Element | None) -> str:
    if node is None:
        return ""
    return " ".join("".join(node.itertext()).split())


def _tacdoc(el: etree._Element) -> dict[str, str]:
    """Pull the nemsisTacDoc annotation attached directly to an element."""
    ann = el.find(_Q("annotation"))
    if ann is None:
        return {}
    # The component XSDs declare xmlns="http://www.nemsis.org" as the default
    # namespace, so the nemsisTacDoc block is namespaced too - match on local-name.
    docs = ann.xpath(".//*[local-name()='nemsisTacDoc']")
    if not docs:
        return {}
    doc = docs[0]
    out = {}
    for key in ("number", "name", "definition", "usage"):
        found = doc.xpath("./*[local-name()=$k]", k=key)
        out[key] = _text(found[0]) if found else ""
    return out


def _resolve_type(el: etree._Element) -> tuple[str | None, list[str]]:
    """Return (type name, NV union member types) for an element declaration.

    A field's type is either a ``type=`` attribute or, when the element wraps its
    value to carry an ``NV`` attribute, the ``base=`` of the inner extension.
    """
    type_name = el.get("type")
    nv_types: list[str] = []

    ext = el.find(f".//{_Q('simpleContent')}/{_Q('extension')}")
    if type_name is None and ext is not None:
        type_name = ext.get("base")

    for union in el.findall(f".//{_Q('attribute')}//{_Q('union')}"):
        nv_types.extend((union.get("memberTypes") or "").split())

    if type_name and ":" in type_name:  # xs:string, xs:date, ... not a NEMSIS code list
        return None, nv_types
    return type_name, nv_types


def _iter_xsds(xsd_dir: Path) -> Iterator[Path]:
    yield from sorted(xsd_dir.glob("*_v3.xsd"))


def load_defined_lists(directory: Path) -> dict[str, DefinedList]:
    """Load NEMSIS Defined List JSON exports.

    Each file names the elements it governs in its own header, so adding a new
    vocabulary is a matter of dropping the JSON in - no code change.
    """
    lists: dict[str, DefinedList] = {}
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))["DefinedList"]
        header = payload["Header"]
        values = []
        for code in payload["Codes"]["Code"]:
            value = code["Value"]
            values.append(
                CodeValue(
                    code=value["Value"],
                    # SuggestedLabel is the EMS-facing wording; SourceLabel is the
                    # vocabulary's own. The former is what a clinician would recognise.
                    label=code.get("SuggestedLabel") or code.get("SourceLabel", ""),
                    category=code.get("Category", ""),
                    code_type=value.get("CodeType", ""),
                )
            )
        lists[path.stem] = DefinedList(
            name=path.stem,
            source_vocabularies=[
                v["Value"] for v in header["SourceVocabularies"]["SourceVocabulary"]
            ],
            elements=list(header["NemsisElements"]["NemsisElement"]),
            values=values,
        )
    return lists


def build_registry(
    xsd_dir: Path,
    version: str = "3.5.0",
    defined_list_dir: Path | None = None,
) -> Registry:
    types: dict[str, list[CodeValue]] = {}
    fields: dict[str, FieldDef] = {}

    for path in _iter_xsds(xsd_dir):
        tree = etree.parse(str(path))
        root = tree.getroot()

        for st in root.iter(_Q("simpleType")):
            name = st.get("name")
            if not name:
                continue
            restriction = st.find(_Q("restriction"))
            if restriction is None:
                continue
            values = [
                CodeValue(code=enum.get("value"), label=_text(enum.find(_Q("annotation"))))
                for enum in restriction.findall(_Q("enumeration"))
            ]
            if values:
                types[name] = values

        for el in root.iter(_Q("element")):
            name = el.get("name") or ""
            if not FIELD_NUMBER_RE.match(name):
                continue
            tac = _tacdoc(el)
            type_name, nv_types = _resolve_type(el)
            fields[name] = FieldDef(
                number=name,
                defined_list=None,
                name=tac.get("name", ""),
                definition=tac.get("definition", ""),
                usage=tac.get("usage", ""),
                type_name=type_name,
                source_xsd=path.name,
                min_occurs=int(el.get("minOccurs", "1")),
                max_occurs=el.get("maxOccurs", "1"),
                nillable=el.get("nillable") == "true",
                nv_types=nv_types,
            )

    defined_lists = load_defined_lists(defined_list_dir or DEFAULT_DEFINED_LIST_DIR)
    for dl in defined_lists.values():
        for number in dl.elements:
            if number in fields:
                fields[number].defined_list = dl.name

    return Registry(version=version, fields=fields, types=types, defined_lists=defined_lists)


DEFAULT_XSD_DIR = Path(__file__).resolve().parent.parent / "reference" / "xsd"
DEFAULT_DEFINED_LIST_DIR = Path(__file__).resolve().parent.parent / "reference" / "definedlists"
DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parent.parent / "reference" / "valuesets.json"


def load_registry(path: Path = DEFAULT_REGISTRY_PATH) -> Registry:
    data = json.loads(path.read_text(encoding="utf-8"))
    fields = {
        num: FieldDef(
            number=num,
            name=f["name"],
            definition=f["definition"],
            usage=f["usage"],
            type_name=f["type"],
            defined_list=f["defined_list"],
            source_xsd=f["source_xsd"],
            min_occurs=f["minOccurs"],
            max_occurs=f["maxOccurs"],
            nillable=f["nillable"],
            nv_types=f["nv_types"],
        )
        for num, f in data["fields"].items()
    }
    types = {
        name: [CodeValue(code=v["code"], label=v["label"]) for v in values]
        for name, values in data["types"].items()
    }
    defined_lists = {
        name: DefinedList(
            name=name,
            source_vocabularies=dl["source_vocabularies"],
            elements=dl["elements"],
            values=[
                CodeValue(
                    code=v["code"],
                    label=v["label"],
                    category=v["category"],
                    code_type=v["code_type"],
                )
                for v in dl["values"]
            ],
        )
        for name, dl in data["defined_lists"].items()
    }
    return Registry(
        version=data["version"], fields=fields, types=types, defined_lists=defined_lists
    )


def write_registry(registry: Registry, path: Path = DEFAULT_REGISTRY_PATH) -> None:
    path.write_text(
        json.dumps(registry.to_json(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
