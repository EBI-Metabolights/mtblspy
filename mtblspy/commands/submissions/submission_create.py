import json
import os

import click

from mtblspy.commands.submissions.cli_utils import get_created_study_id
from mtblspy.commands.submissions.client import SubmissionClient
from mtblspy.commands.submissions.models import StudyInputFormat


@click.command(name="create", short_help="Create a provisional study.")
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
def create_submission(input_file, input_format):
    """
    Create a new provisional study from a study creation request.

    If no input file is provided, it defaults to metabolights-data/submission/data/study_input.json.
    """
    try:
        client = SubmissionClient()
        click.echo(f"Creating provisional study from {input_format} input: {input_file}...")
        result = client.create_study(input_file, StudyInputFormat(input_format))
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    study_id = get_created_study_id(result)
    if study_id:
        click.echo(f"Study created successfully: {study_id}")
    else:
        click.echo("Study created successfully.")
    click.echo(json.dumps(result, indent=2))
