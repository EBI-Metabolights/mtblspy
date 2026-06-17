import click

from mtblspy.commands.submissions.cli_utils import echo_validation_errors
from mtblspy.commands.submissions.local_validation import (
    DEFAULT_VALIDATION_BUNDLE_PATH,
    DEFAULT_VALIDATION_BUNDLE_URL,
    LOCAL_VALIDATION_TIMEOUT_SECONDS,
    run_local_validation,
)


@click.command(name="validate-local", short_help="Run local study validation.")
@click.argument("study_id")
@click.option(
    "--metadata-path",
    "-p",
    type=click.Path(exists=True, file_okay=False),
    help="Local ISA-Tab metadata directory. Defaults to ~/metabolights_data/submission/data/<study_id>.",
)
@click.option(
    "--data-files-path",
    help="Data files root path used while building the local validation input.",
)
@click.option(
    "--validation-bundle-path",
    default=DEFAULT_VALIDATION_BUNDLE_PATH,
    show_default=True,
    help="Local MetaboLights validation bundle path. Downloaded automatically if missing.",
)
@click.option(
    "--validation-bundle-url",
    default=DEFAULT_VALIDATION_BUNDLE_URL,
    show_default=True,
    help="URL used to download the validation bundle when it is missing.",
)
@click.option(
    "--refetch-validation-bundle",
    is_flag=True,
    default=False,
    help="Download the validation bundle even if --validation-bundle-path already exists.",
)
@click.option("--opa-executable-path", default="opa", show_default=True, help="OPA executable path.")
@click.option(
    "--validation-input-path",
    type=click.Path(dir_okay=False),
    help="Path to save the generated local validation input JSON.",
)
@click.option(
    "--validation-file-path",
    "--validation_file_path",
    "--output",
    "-v",
    "-o",
    type=click.Path(dir_okay=False),
    help="Path to save the local validation report. Filename-only values are saved to the study cache.",
)
@click.option(
    "--config-file",
    type=click.Path(exists=True, dir_okay=False),
    help="Optional configuration file with validation overrides.",
)
@click.option(
    "--overridden-rules-file-path",
    type=click.Path(exists=True, dir_okay=False),
    help="Text file with validation rule identifiers or metadata filenames to ignore.",
)
@click.option("--timeout", default=LOCAL_VALIDATION_TIMEOUT_SECONDS, show_default=True, help="OPA validation timeout in seconds.")
def validate_local_submission(
    study_id,
    metadata_path,
    data_files_path,
    validation_bundle_path,
    validation_bundle_url,
    refetch_validation_bundle,
    opa_executable_path,
    validation_input_path,
    validation_file_path,
    config_file,
    overridden_rules_file_path,
    timeout,
):
    """Run local validation for a study using the MetaboLights validation bundle."""
    try:
        click.echo(f"Running local validation for {study_id.upper().strip()}...")
        result = run_local_validation(
            study_id,
            metadata_path=metadata_path,
            data_files_path=data_files_path,
            validation_bundle_path=validation_bundle_path,
            validation_bundle_url=validation_bundle_url,
            refetch_validation_bundle=refetch_validation_bundle,
            opa_executable_path=opa_executable_path,
            validation_file_path=validation_file_path,
            validation_input_path=validation_input_path,
            config_file=config_file,
            overridden_rules_file_path=overridden_rules_file_path,
            timeout=timeout,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    if result.errors:
        click.echo(f"Local validation completed with {len(result.errors)} error(s).")
        echo_validation_errors(result.errors)
    else:
        click.echo("Local validation completed successfully. No validation errors found.")

    click.echo(f"Local validation input is saved as {result.validation_input_path}")
    click.echo(f"Local validation report is saved as {result.report_path}")
