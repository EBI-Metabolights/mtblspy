import click

from mtblspy.commands.submissions.submission_create import create_submission
from mtblspy.commands.submissions.submission_ftp_credentials import private_ftp_credentials
from mtblspy.commands.submissions.submission_list import list_submissions
from mtblspy.commands.submissions.submission_submit import submit_submission
from mtblspy.commands.submissions.submission_templates import submission_templates
from mtblspy.commands.submissions.submission_upload_metadata import upload_metadata
from mtblspy.commands.submissions.submission_validate import validate_submission
from mtblspy.commands.submissions.submission_validate_local import validate_local_submission
from mtblspy.commands.submissions.submission_validation_debug import validation_debug


@click.group(name="submission")
def submission_cli():
    """Commands to use MetaboLights study submission REST API."""


submission_cli.add_command(list_submissions)
submission_cli.add_command(create_submission)
submission_cli.add_command(private_ftp_credentials)
submission_cli.add_command(upload_metadata)
submission_cli.add_command(validate_submission)
submission_cli.add_command(validate_local_submission)
# submission_cli.add_command(validation_debug)
submission_cli.add_command(submit_submission)
submission_cli.add_command(submission_templates)


if __name__ == "__main__":
    submission_cli()
