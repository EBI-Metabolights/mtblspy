import json

import click

from mtblspy.config import get_config


@click.command(name="show")
def show_config():
    """Show effective configuration."""
    click.echo(json.dumps(get_config(), indent=2))
