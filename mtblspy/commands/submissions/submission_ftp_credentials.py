import json

import click

from mtblspy.commands.output import json_output_option, save_json_output
from mtblspy.commands.submissions.client import DEFAULT_LOCAL_SUBMISSION_CACHE_PATH, SubmissionClient


@click.command(name="ftp-credentials")
@click.argument("study_id")
@json_output_option("Save FTP credentials as JSON. Filename-only values are saved to the study cache.")
def private_ftp_credentials(study_id, output):
    """Get private FTP upload credentials for a study."""
    try:
        client = SubmissionClient()
        details = client.get_private_ftp_credentials(study_id)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    payload = details.model_dump()
    if output:
        default_directory = DEFAULT_LOCAL_SUBMISSION_CACHE_PATH / (details.study_id or study_id.upper().strip())
        output_path = save_json_output(
            payload,
            output,
            default_directory,
            "ftp_credentials.json",
        )
        click.echo(f"FTP credentials JSON saved to {output_path}")
    click.echo(json.dumps(payload, indent=2))
