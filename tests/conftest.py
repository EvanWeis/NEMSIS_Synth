from pathlib import Path

import pytest

from nemsis_gen.valuesets import load_registry

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "reference" / "samples" / "ems_xml"
XSD_DIR = ROOT / "reference" / "xsd"


@pytest.fixture(scope="session")
def registry():
    return load_registry()


@pytest.fixture(scope="session")
def sample_files() -> list[Path]:
    return sorted(SAMPLES.glob("*.xml"))
