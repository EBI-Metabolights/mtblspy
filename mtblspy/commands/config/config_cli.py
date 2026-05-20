import click

from mtblspy.commands.config.config_show import show_config


@click.group(name="config")
def config_cli():
    """Configuration management."""


config_cli.add_command(show_config)
