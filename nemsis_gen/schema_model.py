"""An ordered structural model of the EMSDataSet document, read from the XSDs.

``PatientCareReport``'s children are an ``xs:sequence``: a fixed element order,
not ``xs:all``. Rather than transcribe that order (and the order inside every
nested group) into code where it can drift from the schema, this module walks the
XSDs and builds the tree. The renderer then emits elements in schema order by
construction, which removes accidental element-ordering failures as a class -
important, because a false "invalid" verdict is worse than no verdict at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from functools import lru_cache
from pathlib import Path

from lxml import etree

from .valuesets import DEFAULT_XSD_DIR

XS = "http://www.w3.org/2001/XMLSchema"


def _q(tag: str) -> str:
    return f"{{{XS}}}{tag}"


@dataclass
class Node:
    """One element declaration: a leaf field, or a group with ordered children."""

    name: str
    min_occurs: int = 1
    max_occurs: str = "1"
    children: list[Node] = dc_field(default_factory=list)
    attributes: dict[str, str] = dc_field(default_factory=dict)

    @property
    def is_group(self) -> bool:
        return bool(self.children)

    @property
    def repeats(self) -> bool:
        return self.max_occurs == "unbounded" or int(self.max_occurs) > 1

    @property
    def required(self) -> bool:
        return self.min_occurs > 0

    def child(self, name: str) -> Node | None:
        for c in self.children:
            if c.name == name:
                return c
        return None

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    def leaf_names(self) -> list[str]:
        return [n.name for n in self.walk() if not n.is_group and n is not self]


class SchemaModel:
    """Lazily resolves named complexTypes across the whole included schema set."""

    def __init__(self, xsd_dir: Path):
        self.xsd_dir = xsd_dir
        self._complex_types: dict[str, etree._Element] = {}
        self._roots: list[etree._Element] = []
        for path in sorted(xsd_dir.glob("*_v3.xsd")):
            root = etree.parse(str(path)).getroot()
            self._roots.append(root)
            for ct in root.findall(_q("complexType")):
                if ct.get("name"):
                    self._complex_types[ct.get("name")] = ct

    def _find_element(self, name: str) -> etree._Element:
        for root in self._roots:
            for el in root.findall(_q("element")):
                if el.get("name") == name:
                    return el
        raise KeyError(f"no top-level element {name!r} in {self.xsd_dir}")

    def _attributes(self, el: etree._Element) -> dict[str, str]:
        """Attributes declared on this element, e.g. eMedications.03's CodeType.

        Scoped to the element's own type - a plain ``iter`` would also pick up
        attributes belonging to nested child elements.
        """
        out: dict[str, str] = {}

        def scan(node: etree._Element) -> None:
            for child in node:
                if child.tag == _q("element"):
                    continue  # belongs to a nested field, not this one
                if child.tag == _q("attribute") and child.get("name"):
                    out[child.get("name")] = child.get("type") or ""
                scan(child)

        complex_type = el.find(_q("complexType"))
        if complex_type is None and el.get("type") in self._complex_types:
            complex_type = self._complex_types[el.get("type")]
        if complex_type is not None:
            scan(complex_type)
        return out

    def _build(self, el: etree._Element, depth: int = 0) -> Node:
        node = Node(
            name=el.get("name"),
            min_occurs=int(el.get("minOccurs", "1")),
            max_occurs=el.get("maxOccurs", "1"),
            attributes=self._attributes(el),
        )
        if depth > 12:  # NEMSIS nests shallowly; a guard against pathological input
            return node

        complex_type = el.find(_q("complexType"))
        if complex_type is None and el.get("type") in self._complex_types:
            complex_type = self._complex_types[el.get("type")]
        if complex_type is None:
            return node

        sequence = complex_type.find(_q("sequence"))
        if sequence is None:
            return node
        for child in sequence.findall(_q("element")):
            node.children.append(self._build(child, depth + 1))
        return node

    @property
    def dataset(self) -> Node:
        return self._build(self._find_element("EMSDataSet"))

    @property
    def patient_care_report(self) -> Node:
        node = self.dataset.child("Header").child("PatientCareReport")
        assert node is not None
        return node

    def section_order(self) -> list[str]:
        return [c.name for c in self.patient_care_report.children]


@lru_cache(maxsize=2)
def load_model(xsd_dir: Path = DEFAULT_XSD_DIR) -> SchemaModel:
    return SchemaModel(xsd_dir)
