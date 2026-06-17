import click

from mtblspy.config import get_config, save_config


@click.command(name="set")
@click.option(
    "--base-url",
    required=True,
    help="MetaboLights REST API base URL to save for future commands.",
)
def set_config(base_url):
    """Set persistent configuration values."""
    try:
        save_config(base_url=base_url)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Base URL saved: {get_config()['base_url']}")
