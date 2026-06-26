import click

from mtblspy.commands.submissions.study_creation_input import study_creation_input
from mtblspy.commands.submissions.template_files import isa_tab_file_template, result_file_template


@click.group(
    name="templates",
    context_settings={"help_option_names": ["-h", "--help"]},
    no_args_is_help=True,
)
def submission_templates():
    """Commands to use MetaboLights study submission templates."""


submission_templates.add_command(study_creation_input)
submission_templates.add_command(isa_tab_file_template)
submission_templates.add_command(result_file_template)


if __name__ == "__main__":
    submission_templates()
