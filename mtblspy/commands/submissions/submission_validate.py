import click

from mtblspy.commands.submissions.cli_utils import echo_report, echo_validation_errors
from mtblspy.commands.submissions.client import (
    VALIDATION_MAX_POLLS,
    VALIDATION_POLL_INTERVAL_SECONDS,
    SubmissionClient,
)


@click.command(name="validate", short_help="Run study validation.")
@click.argument("study_id")
@click.option("--max-polls", default=VALIDATION_MAX_POLLS, show_default=True, help="Maximum validation status checks.")
@click.option(
    "--poll-interval",
    default=VALIDATION_POLL_INTERVAL_SECONDS,
    show_default=True,
    help="Seconds between validation status checks.",
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
def validate_submission(study_id, max_polls, poll_interval, validation_file_path):
    """Run validation for a study and show the validation report."""
    try:
        client = SubmissionClient()
        click.echo(f"Running validation for {study_id.upper().strip()}...")
        result = client.validate_study(
            study_id,
            validation_file_path=validation_file_path,
            max_polls=max_polls,
            poll_interval=poll_interval,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    if result.errors:
        click.echo(f"Validation completed with {len(result.errors)} error(s).")
        echo_validation_errors(result.errors)
    else:
        click.echo("Validation completed successfully. No validation errors found.")

    echo_report(result.report_path)
    click.echo(f"Validation report is saved as {result.report_path}")
