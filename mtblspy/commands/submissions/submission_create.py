import json
import os

import click

from mtblspy.commands.output import json_output_option, save_json_output
from mtblspy.commands.submissions.cli_utils import get_created_study_id
from mtblspy.commands.submissions.client import DEFAULT_LOCAL_SUBMISSION_CACHE_PATH, SubmissionClient
from mtblspy.commands.submissions.exceptions import SubmissionAPIError
from mtblspy.commands.submissions.models import StudyInputFormat


@click.command(name="create", short_help="Create a provisional study.")
@click.option("--base-url", help="MetaboLights REST API base URL used to select credentials.")
@click.option(
    "--input-file",
    type=click.Path(exists=True, dir_okay=False, resolve_path=True),
    default=os.path.expanduser("~/metabolights_data/submission/data/study_input.json"),
    show_default=True,
    help="Path to the study creation input file.",
)
@click.option(
    "--input-format",
    type=click.Choice([item.value for item in StudyInputFormat]),
    default=StudyInputFormat.JSON.value,
    show_default=True,
    help="Study creation input format.",
)
@json_output_option("Save the study creation response as JSON. Filename-only values are saved to the current directory.")
def create_submission(base_url, input_file, input_format, output):
    """
    Create a new provisional study from a study creation request.

    If no input file is provided, it defaults to metabolights-data/submission/data/study_input.json.
    """
    try:
        client = SubmissionClient(base_url=base_url)
        click.echo(f"Creating provisional study from {input_format} input: {input_file}...")
        result = client.create_study(input_file, StudyInputFormat(input_format))
    except SubmissionAPIError as exc:
        raise click.ClickException(format_submission_api_error(exc)) from exc
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    study_id = get_created_study_id(result)
    if study_id:
        click.echo(f"Study created successfully: {study_id}")
    else:
        click.echo("Study created successfully.")
    if output:
        default_directory = DEFAULT_LOCAL_SUBMISSION_CACHE_PATH / study_id if study_id else DEFAULT_LOCAL_SUBMISSION_CACHE_PATH
        output_path = save_json_output(
            result,
            output,
            default_directory,
            "study_create_response.json",
        )
        click.echo(f"Study creation response JSON saved to {output_path}")
    click.echo(json.dumps(result, indent=2))


def format_submission_api_error(exc):
    lines = [str(exc)]
    if exc.errors:
        lines.append("Server response:")
        lines.extend(f"- {error}" for error in exc.errors)
    return "\n".join(lines)
