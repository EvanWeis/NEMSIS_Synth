"""nemsis-gen command line entry point."""

from __future__ import annotations

import json
from pathlib import Path

import click
from dotenv import load_dotenv

from .validate import DEFAULT_SCHEMA, validate_file
from .valuesets import (
    DEFAULT_REGISTRY_PATH,
    DEFAULT_XSD_DIR,
    build_registry,
    load_registry,
    write_registry,
)

load_dotenv()


@click.group()
def cli() -> None:
    """Generate and validate synthetic NEMSIS v3.5.0 patient care reports."""


@cli.group()
def valuesets() -> None:
    """Build and query the XSD-derived code tables."""


@valuesets.command("build")
@click.option("--xsd-dir", type=click.Path(path_type=Path), default=DEFAULT_XSD_DIR)
@click.option("--out", type=click.Path(path_type=Path), default=DEFAULT_REGISTRY_PATH)
@click.option("--version", default="3.5.0")
def valuesets_build(xsd_dir: Path, out: Path, version: str) -> None:
    """Re-derive reference/valuesets.json from the XSDs on disk."""
    registry = build_registry(xsd_dir, version=version)
    write_registry(registry, out)
    click.echo(
        f"{len(registry.fields)} fields, {len(registry.types)} value sets, "
        f"{len(registry.all_codes())} codes -> {out}"
    )


@valuesets.command("show")
@click.argument("field")
def valuesets_show(field: str) -> None:
    """Print the legal coded values for a field, e.g. eDispatch.01."""
    registry = load_registry()
    fd = registry.fields.get(field)
    if fd is None:
        raise click.ClickException(f"unknown field {field!r}")
    click.echo(f"{fd.number}  {fd.name}  [{fd.usage}]  type={fd.type_name}")
    if fd.definition:
        click.echo(f"  {fd.definition}")
    for value in registry.values_for(field):
        click.echo(f"  {value.code}  {value.label}")


@cli.command("validate")
@click.argument("paths", nargs=-1, required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--schema", type=click.Path(path_type=Path), default=DEFAULT_SCHEMA)
@click.option("--json", "as_json", is_flag=True, help="Emit one JSON object per file.")
def validate_cmd(paths: tuple[Path, ...], schema: Path, as_json: bool) -> None:
    """Validate XML files: well-formedness, XSD structure, and code value sets."""
    registry = load_registry()
    files: list[Path] = []
    for path in paths:
        files.extend(sorted(path.glob("*.xml")) if path.is_dir() else [path])

    failed = 0
    for path in files:
        result = validate_file(path, schema_path=schema, registry=registry)
        failed += not result.ok
        if as_json:
            click.echo(json.dumps({"file": str(path), **result.to_json()}))
        else:
            status = "PASS" if result.ok else "FAIL"
            click.echo(f"{status}  {path.name}")
            for msg in (result.errors + result.code_errors)[:5]:
                click.echo(f"      {msg}")

    if not as_json:
        click.echo(f"\n{len(files) - failed}/{len(files)} passed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    cli()
