import click

from mtblspy.commands.submissions.cli_utils import echo_validation_errors
from mtblspy.commands.submissions.client import (
    VALIDATION_MAX_POLLS,
    VALIDATION_POLL_INTERVAL_SECONDS,
    SubmissionClient,
)


@click.command(name="validation-debug", short_help="Create ISA JSON and validation root-cause report.")
@click.argument("study_id")
@click.option(
    "--isa-json-file-path",
    "--isa_json_file_path",
    "--isa-output",
    "-i",
    type=click.Path(dir_okay=False),
    help="Path to save the fetched ISA JSON. Defaults to the submission cache as <accession>.json.",
)
@click.option(
    "--validation-file-path",
    "--validation_file_path",
    "--output",
    "-v",
    "-o",
    type=click.Path(dir_okay=False),
    help="Path to save the enriched validation root-cause report. Filename-only values are saved to the study cache.",
)
@click.option("--max-polls", default=VALIDATION_MAX_POLLS, show_default=True, help="Maximum validation status checks.")
@click.option(
    "--poll-interval",
    default=VALIDATION_POLL_INTERVAL_SECONDS,
    show_default=True,
    help="Seconds between validation status checks.",
)
def validation_debug(study_id, isa_json_file_path, validation_file_path, max_polls, poll_interval):
    """Developer helper: save study ISA JSON and explain validation root causes."""
    try:
        client = SubmissionClient()
        click.echo(f"Creating ISA JSON and validation root-cause report for {study_id.upper().strip()}...")
        result = client.find_validation_root_causes(
            study_id,
            isa_json_file_path=isa_json_file_path,
            validation_file_path=validation_file_path,
            max_polls=max_polls,
            poll_interval=poll_interval,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    validation_result = result.validation_result
    if validation_result.errors:
        click.echo(f"Validation completed with {len(validation_result.errors)} error(s).")
        echo_validation_errors(validation_result.errors)
    else:
        click.echo("Validation completed successfully. No validation errors found.")

    click.echo(f"ISA JSON is saved as {result.isa_json_path}")
    click.echo(f"Validation root-cause report is saved as {validation_result.report_path}")
