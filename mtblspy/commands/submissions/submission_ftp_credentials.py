import json

import click

from mtblspy.commands.submissions.client import SubmissionClient


@click.command(name="ftp-credentials")
@click.argument("study_id")
def private_ftp_credentials(study_id):
    """Get private FTP upload credentials for a study."""
    try:
        client = SubmissionClient()
        details = client.get_private_ftp_credentials(study_id)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(json.dumps(details.model_dump(), indent=2))
