import click

from mtblspy.commands.output import json_output_option
from mtblspy.commands.submissions.client import save_sample_study_input


@click.command(name="study-creation-input")
@json_output_option("Save the example study creation JSON input. Filename-only values are saved to the default data folder.")
@click.option("--data-folder", type=click.Path(file_okay=False), help="Directory to save study_input.json.")
@click.option("--overwrite/--no-overwrite", default=True, show_default=True, help="Overwrite an existing study_input.json.")
def study_creation_input(output, data_folder, overwrite):
    """Create a sample study creation JSON input file."""
    try:
        output_path = save_sample_study_input(data_folder=data_folder, output_path=output, overwrite=overwrite)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Sample study input JSON saved to {output_path}")
