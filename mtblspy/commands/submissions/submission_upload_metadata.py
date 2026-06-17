import click

from mtblspy.commands.submissions.cli_utils import echo_validation_errors
from mtblspy.commands.submissions.client import (
    VALIDATION_MAX_POLLS,
    VALIDATION_POLL_INTERVAL_SECONDS,
    SubmissionClient,
)
from mtblspy.commands.submissions.exceptions import SubmissionError


@click.command(name="upload-metadata")
@click.argument("study_id")
@click.argument("metadata_files", nargs=-1, type=click.Path(dir_okay=False))
@click.option(
    "--metadata-path",
    "-p",
    type=click.Path(exists=False),
    help=(
        "Metadata file or directory. Defaults to "
        "~/metabolights_data/submission/data/<study_id>."
    ),
)
@click.option(
    "--validate/--no-validate",
    default=True,
    show_default=True,
    help="Run study validation after successful metadata upload.",
)
@click.option(
    "--validation-file-path",
    "--validation_file_path",
    "--output",
    "-v",
    "-o",
    type=click.Path(dir_okay=False),
    help="Path to save the validation report. Filename-only values are saved to the study cache.",
)
@click.option("--validation-max-polls", default=VALIDATION_MAX_POLLS, show_default=True, help="Maximum validation status checks.")
@click.option(
    "--validation-poll-interval",
    default=VALIDATION_POLL_INTERVAL_SECONDS,
    show_default=True,
    help="Seconds between validation status checks.",
)
def upload_metadata(
    study_id,
    metadata_files,
    metadata_path,
    validate,
    validation_file_path,
    validation_max_polls,
    validation_poll_interval,
):
    """Upload ISA-Tab metadata files for a study."""
    try:
        client = SubmissionClient()
        result = client.upload_metadata(
            study_id,
            metadata_path=metadata_path,
            metadata_files=metadata_files,
            validate_after_upload=validate,
            validation_file_path=validation_file_path,
            validation_max_polls=validation_max_polls,
            validation_poll_interval=validation_poll_interval,
        )
    except SubmissionError as exc:
        raise click.ClickException(str(exc)) from exc
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Uploaded {len(result.uploaded_files)} metadata file(s) for {result.study_id}.")
    for file_path in result.uploaded_files:
        click.echo(f"- {file_path.name}")

    if result.validation_result:
        if result.validation_result.errors:
            click.echo(f"Validation completed with {len(result.validation_result.errors)} error(s).")
            echo_validation_errors(result.validation_result.errors)
        else:
            click.echo("Validation completed successfully. No validation errors found.")
        click.echo(f"Validation report is saved as {result.validation_result.report_path}")
