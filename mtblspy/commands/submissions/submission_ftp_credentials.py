import json

import click

from mtblspy.commands.output import json_output_option, save_json_output
from mtblspy.commands.submissions.cli_utils import create_submission_client, jwt_token_option
from mtblspy.commands.submissions.client import DEFAULT_LOCAL_SUBMISSION_CACHE_PATH


@click.command(name="ftp-credentials")
@click.argument("study_id")
@click.option("--base-url", help="MetaboLights REST API base URL used to select credentials.")
@jwt_token_option
@json_output_option("Save FTP credentials as JSON. Filename-only values are saved to the current directory.")
def private_ftp_credentials(study_id, base_url, jwt_token, output):
    """Get private FTP upload credentials for a study."""
    try:
        client = create_submission_client(base_url=base_url, jwt_token=jwt_token)
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
