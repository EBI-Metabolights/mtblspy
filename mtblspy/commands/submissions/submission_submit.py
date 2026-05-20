import click

from mtblspy.commands.submissions.cli_utils import echo_validation_errors
from mtblspy.commands.submissions.client import (
    VALIDATION_MAX_POLLS,
    VALIDATION_POLL_INTERVAL_SECONDS,
    SubmissionClient,
)
from mtblspy.commands.submissions.exceptions import StudyValidationError, SubmissionError


@click.command(name="submit", short_help="Submit a study for review.")
@click.argument("study_id")
@click.option("--status", default="Submitted", show_default=True, help="Target study status.")
@click.option(
    "--validation-file-path",
    "--validation_file_path",
    "-v",
    type=click.Path(dir_okay=False),
    help="Path to save the validation report.",
)
@click.option("--validation-max-polls", default=VALIDATION_MAX_POLLS, show_default=True, help="Maximum validation status checks.")
@click.option(
    "--validation-poll-interval",
    default=VALIDATION_POLL_INTERVAL_SECONDS,
    show_default=True,
    help="Seconds between validation status checks.",
)
def submit_submission(study_id, status, validation_file_path, validation_max_polls, validation_poll_interval):
    """Submit a study for review by changing its status after validation."""
    try:
        client = SubmissionClient()
        click.echo(f"Running validation for {study_id.upper().strip()}...")
        result = client.submit_study(
            study_id,
            status=status,
            validation_file_path=validation_file_path,
            validation_max_polls=validation_max_polls,
            validation_poll_interval=validation_poll_interval,
        )
    except StudyValidationError as exc:
        click.echo("Validation completed with errors. Study status was not changed.", err=True)
        echo_validation_errors(exc.errors, err=True)
        raise click.ClickException(str(exc)) from exc
    except SubmissionError as exc:
        raise click.ClickException(str(exc)) from exc
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo("Validation completed successfully. No validation errors found.")
    click.echo(f"Study {result.study_id} status updated successfully to {result.status}.")
