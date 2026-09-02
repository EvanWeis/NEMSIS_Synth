"""nemsis-gen command line entry point."""

from __future__ import annotations

import json
from pathlib import Path

import click
from dotenv import load_dotenv

from .api_client import DEFAULT_MODEL, ApiClient, OutputContractError
from .generate import DEFAULT_TEMPLATE, build_cached_system, generate_record
from .manifest import Manifest
from .mutate import apply_mutation
from .profiles import load_profiles
from .scenario import Scenario
from .validate import DEFAULT_SCHEMA, validate_file
from .valuesets import (
    DEFAULT_REGISTRY_PATH,
    DEFAULT_XSD_DIR,
    build_registry,
    load_registry,
    write_registry,
)

# .env.local first so a local key overrides a checked-in default.
for _env_file in (".env.local", ".env"):
    load_dotenv(_env_file, override=False)


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
    if fd.defined_list:
        dl = registry.defined_lists[fd.defined_list]
        click.echo(
            f"  defined list: {dl.name} ({', '.join(dl.source_vocabularies)}) - "
            "a curated subset; the schema admits any valid code from the vocabulary"
        )
    for value in registry.values_for(field):
        suffix = f"  [{value.category}]" if value.category else ""
        click.echo(f"  {value.code}  {value.label}{suffix}")


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
            warned = (
                f"  ({len(result.defined_list_warnings)} defined-list advisories)"
                if result.defined_list_warnings
                else ""
            )
            click.echo(f"{status}  {path.name}{warned}")
            for msg in (result.errors + result.code_errors)[:5]:
                click.echo(f"      {msg}")

    if not as_json:
        click.echo(f"\n{len(files) - failed}/{len(files)} passed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    cli()


@cli.command("profiles")
def profiles_cmd() -> None:
    """List the configured quality profiles."""
    config = load_profiles()
    for name, profile in sorted(config.profiles.items()):
        expected = "valid" if profile.expects_valid else f"invalid ({profile.mutation.name})"
        click.echo(f"{name:28} narrative={profile.narrative_quality}/5  expects {expected}")
        click.echo(f"  {profile.description}")


@cli.command("generate")
@click.option("--profile", "profile_name", required=True)
@click.option("--scenario", "scenario_text", default=None, help="Free-text clinical scenario.")
@click.option(
    "--scenario-file",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Structured scenario YAML (patient, scene, assessment, interventions, narrative).",
)
@click.option("--count", default=1, show_default=True)
@click.option("--out-dir", type=click.Path(path_type=Path), default=Path("out"), show_default=True)
@click.option("--model", default=DEFAULT_MODEL, show_default=True)
@click.option(
    "--coder-model",
    default=None,
    help="Run stage B (code selection) on a different model from stage A.",
)
@click.option("--template", type=click.Path(exists=True, path_type=Path), default=DEFAULT_TEMPLATE)
@click.option("--manifest", "manifest_path", type=click.Path(path_type=Path), default=None)
@click.option("--validate/--no-validate", default=True, show_default=True)
@click.option("--seed", type=int, default=None, help="Seed for mutation choices.")
@click.option("--dry-run", is_flag=True, help="Estimate prompt size and cost, make no API calls.")
def generate_cmd(
    profile_name: str,
    scenario_text: str | None,
    scenario_file: Path | None,
    count: int,
    out_dir: Path,
    model: str,
    coder_model: str | None,
    template: Path,
    manifest_path: Path | None,
    validate: bool,
    seed: int | None,
    dry_run: bool,
) -> None:
    """Generate N synthetic PCRs for one quality profile."""
    if not scenario_text and not scenario_file:
        raise click.UsageError("give --scenario or --scenario-file")

    config = load_profiles()
    try:
        profile = config.get(profile_name)
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc

    scenario = (
        Scenario.from_file(scenario_file) if scenario_file else Scenario.from_text(scenario_text)
    )
    registry = load_registry()

    if dry_run:
        cached = build_cached_system(registry)
        cached_tokens = len(cached) // 4
        click.echo(f"profile:        {profile.name} (narrative {profile.narrative_quality}/5)")
        click.echo(f"scenario:       {scenario.name}")
        click.echo(f"cached system:  ~{cached_tokens:,} tokens, sent once then cached")
        click.echo(f"calls:          {count * 2} ({count} records x 2 stages)")
        click.echo(
            "Cache reads are billed at a fraction of input rate, so the catalogue is "
            "paid for roughly once per run rather than once per call."
        )
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = Manifest(manifest_path or Path("manifest") / f"{profile.name}.jsonl")
    try:
        client = ApiClient(model=model)
        coder = ApiClient(model=coder_model) if coder_model else None
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    written = 0
    for index in range(count):
        name = f"{profile.name}_{index + 1:03d}.xml"
        path = out_dir / name
        row: dict = {
            "file": str(path),
            "profile": profile.name,
            "narrative_quality": profile.narrative_quality,
            "scenario": scenario.to_json(),
            "model": model,
            "coder_model": coder_model or model,
            "template": str(template),
        }

        try:
            result = generate_record(client, scenario, profile, config, registry, template=template)
        except OutputContractError as exc:
            row.update(status="output_contract_violation", error=str(exc), raw=exc.raw[:2000])
            manifest.append(row)
            click.echo(f"FAIL  {name}  model did not honour the output contract")
            continue
        except Exception as exc:  # noqa: BLE001 - a failed record is data, not a crash
            row.update(status="generation_error", error=f"{type(exc).__name__}: {exc}")
            manifest.append(row)
            click.echo(f"FAIL  {name}  {type(exc).__name__}: {exc}")
            continue

        data = result.xml
        row["unknown_codes"] = result.unknown_codes
        row["render_report"] = result.render_report.to_json()
        row["narrative"] = result.clinical.get("narrative", "")

        if profile.mutation is not None:
            data, description = apply_mutation(
                profile.mutation.name, data, registry, profile.mutation.params, seed=seed
            )
            row["mutation"] = {"name": profile.mutation.name, "applied": description}

        path.write_bytes(data)
        written += 1

        if validate:
            outcome = validate_file(path, registry=registry)
            row["validation"] = outcome.to_json()
            row["expected_valid"] = profile.expects_valid
            row["matched_expectation"] = outcome.ok == profile.expects_valid
            status = "PASS" if outcome.ok else "FAIL"
            flag = "" if row["matched_expectation"] else "  !! did not match profile expectation"
            click.echo(f"{status}  {name}{flag}")
        else:
            click.echo(f"WROTE {name}")

        row["status"] = "ok"
        row["usage"] = client.usage.to_json()
        if coder is not None:
            row["coder_usage"] = coder.usage.to_json()
        manifest.append(row)

    click.echo(f"\n{written}/{count} written to {out_dir}")
    click.echo(f"manifest: {manifest.path}")
    click.echo(f"tokens: {json.dumps(client.usage.to_json())}")
