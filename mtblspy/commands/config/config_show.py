import json
from pathlib import Path

import click

from mtblspy.commands.output import json_output_option, save_json_output
from mtblspy.config import get_config


@click.command(name="show")
@json_output_option("Save the effective configuration as JSON.")
def show_config(output):
    """Show effective configuration."""
    config = get_config()
    if output:
        output_path = save_json_output(config, output, Path.cwd(), "mtbls_config.json")
        click.echo(f"Configuration JSON saved to {output_path}")
        return
    click.echo(json.dumps(config, indent=2))
