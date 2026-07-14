import click

from mtblspy.commands.output import json_output_option, save_json_output
from mtblspy.commands.submissions.cli_utils import create_submission_client, jwt_token_option
from mtblspy.commands.submissions.client import DEFAULT_LOCAL_SUBMISSION_CACHE_PATH


@click.command(name="list")
@click.option("--base-url", help="MetaboLights REST API base URL used to select credentials.")
@jwt_token_option
@json_output_option("Save the studies list as JSON. Filename-only values are saved to the current directory.")
def list_submissions(base_url, jwt_token, output):
    """List studies created by the user."""
    try:
        client = create_submission_client(base_url=base_url, jwt_token=jwt_token)
        click.echo(f"Fetching studies from {client.rest_api_base_url}/studies/user...")
        studies = client.list_studies()
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    if output:
        output_path = save_json_output(
            studies,
            output,
            DEFAULT_LOCAL_SUBMISSION_CACHE_PATH,
            "studies.json",
        )
        click.echo(f"Studies JSON saved to {output_path}")

    if not studies:
        click.echo("No studies found.")
        return

    click.echo(f"{'Accession':<15} | {'Status':<15} | {'Title'}")
    click.echo("-" * 60)
    for study in studies:
        accession = study.get("accession", "N/A")
        status = study.get("status", "N/A")
        title = study.get("title", "N/A")
        click.echo(f"{accession:<15} | {status:<15} | {title}")
