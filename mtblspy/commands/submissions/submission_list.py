import click

from mtblspy.commands.output import json_output_option, save_json_output
from mtblspy.commands.submissions.client import DEFAULT_LOCAL_SUBMISSION_CACHE_PATH, SubmissionClient


@click.command(name="list")
@json_output_option("Save the studies list as JSON. Filename-only values are saved to the submission cache.")
def list_submissions(output):
    """List studies created by the user."""
    try:
        client = SubmissionClient()
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
