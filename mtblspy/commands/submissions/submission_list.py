import click

from mtblspy.commands.submissions.client import SubmissionClient


@click.command(name="list")
def list_submissions():
    """List studies created by the user."""
    try:
        client = SubmissionClient()
        click.echo(f"Fetching studies from {client.rest_api_base_url}/studies/user...")
        studies = client.list_studies()
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

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
