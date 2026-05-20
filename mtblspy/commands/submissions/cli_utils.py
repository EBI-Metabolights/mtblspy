from pathlib import Path

import click

from mtblspy.commands.submissions.client import format_validation_error


def echo_validation_errors(errors, err=False):
    for error in errors[:5]:
        click.echo(f"- {format_validation_error(error)}", err=err)
    if len(errors) > 5:
        click.echo(f"- ... and {len(errors) - 5} more error(s)", err=err)


def echo_report(validation_file_path):
    with Path(validation_file_path).open("r", encoding="utf-8") as validation_file:
        for line in validation_file:
            click.echo(line.rstrip())


def get_created_study_id(result):
    studies = result.get("studies")
    if isinstance(studies, dict) and studies:
        return ", ".join(studies.keys())
    return result.get("study_id") or result.get("accession")
