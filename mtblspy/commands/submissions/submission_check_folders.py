import json
import re
import zipfile
from pathlib import Path

import click

from mtblspy.commands.output import save_json_output
from mtblspy.commands.submissions.client import (
    DEFAULT_LOCAL_SUBMISSION_CACHE_PATH,
    DEFAULT_LOCAL_SUBMISSION_DATA_PATH,
    is_metadata_filename,
    normalize_study_id,
)
from mtblspy.commands.submissions.exceptions import SubmissionAPIError
from mtblspy.commands.submissions.local_validation import (
    RAW_FILE_COLUMNS,
    DERIVED_FILE_COLUMNS,
    ASSIGNMENT_FILE_COLUMNS,
    get_column_values,
    load_local_validation_input,
    resolve_metadata_path,
    table_rows,
)

ALLOWED_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
RAW_FOLDER_SUFFIXES = (".d", ".raw")


@click.command(name="check-folders", short_help="Check local metadata and data folders before submission.")
@click.argument("study_id")
@click.option(
    "--default-submission-data-path",
    default=str(DEFAULT_LOCAL_SUBMISSION_DATA_PATH),
    show_default=True,
    help="Parent folder for default metadata lookup.",
)
@click.option(
    "-p",
    "--metadata-files-path",
    "--metadata-path",
    help="Local ISA-Tab metadata directory. Defaults to <default-submission-data-path>/<study-id>.",
)
@click.option(
    "--data-files-path",
    "--data-files-root-path",
    help="Local data FILES directory. Defaults to <metadata-files-path>/FILES.",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(dir_okay=False),
    help="Save the folder check report as JSON. Defaults to the local MetaboLights cache folder.",
)
def check_folders(study_id, default_submission_data_path, metadata_files_path, data_files_path, output):
    """Check local study folders against MetaboLights submission prerequisites."""
    result = check_submission_folders(
        study_id,
        metadata_files_path=metadata_files_path,
        data_files_path=data_files_path,
        default_submission_data_path=default_submission_data_path,
    )
    output_path = save_check_folders_output(result, output, result["study_id"])
    click.echo(json.dumps(result, indent=2))
    click.echo(f"Folder check report JSON saved to {output_path}")
    if result["status"] == "failed":
        raise click.exceptions.Exit(1)


def check_submission_folders(study_id, metadata_files_path=None, data_files_path=None, default_submission_data_path=None):
    study_id = normalize_study_id(study_id)
    metadata_path = resolve_metadata_path(study_id, metadata_files_path, default_submission_data_path)
    data_path = resolve_data_files_path(data_files_path, metadata_path)
    result = {
        "study_id": study_id,
        "status": "success",
        "metadata_files_path": str(metadata_path),
        "data_files_path": str(data_path),
        "summary": {
            "metadata_files": 0,
            "data_files": 0,
            "data_folders": 0,
            "referenced_raw_files": 0,
            "referenced_derived_files": 0,
            "referenced_assignment_files": 0,
        },
        "errors": [],
        "warnings": [],
    }

    validation_input = None
    check_metadata_folder(metadata_path, result)
    check_data_folder(data_path, result)
    if metadata_path.exists() and metadata_path.is_dir():
        try:
            validation_input = load_local_validation_input(study_id, metadata_path, data_path)
        except SubmissionAPIError as exc:
            add_error(result, "metadata_parse_failed", metadata_path, str(exc))
        except Exception as exc:
            add_error(result, "metadata_parse_failed", metadata_path, f"Unable to parse ISA-Tab metadata: {exc}")

    if validation_input:
        update_summary(result, validation_input)
        check_assay_file_references(validation_input, metadata_path, data_path, result)

    check_zip_raw_folder_contents(data_path, result)
    result["errors"] = deduplicate_checks(result["errors"])
    result["warnings"] = deduplicate_checks(result["warnings"])
    result["status"] = "failed" if result["errors"] else "success"
    return result


def resolve_data_files_path(data_files_path, metadata_path):
    if data_files_path:
        return Path(data_files_path).expanduser().resolve()
    return (metadata_path / "FILES").resolve()


def save_check_folders_output(payload, output, study_id):
    return save_json_output(
        payload,
        output,
        DEFAULT_LOCAL_SUBMISSION_CACHE_PATH / study_id,
        f"{study_id}_folder_check_report.json",
    )


def check_metadata_folder(metadata_path, result):
    if not metadata_path.exists() or not metadata_path.is_dir():
        add_error(result, "metadata_path_missing", metadata_path, f"Metadata path does not exist or is not a directory: {metadata_path}")
        return

    metadata_files = [path for path in metadata_path.iterdir() if path.is_file() and is_metadata_filename(path.name)]
    result["summary"]["metadata_files"] = len(metadata_files)
    all_files = [path for path in metadata_path.iterdir() if path.is_file()]
    for path in all_files:
        check_allowed_name(path.name, path, result)
        if path.suffix.lower() in {".txt", ".tsv"} and not is_metadata_filename(path.name):
            add_error(result, "metadata_filename_invalid", path, "Metadata files must use i_*.txt, s_*.txt, a_*.txt, or m_*.tsv names.")

    investigation_files = sorted(path for path in metadata_files if path.name.startswith("i_"))
    sample_files = sorted(path for path in metadata_files if path.name.startswith("s_"))
    assay_files = sorted(path for path in metadata_files if path.name.startswith("a_"))
    assignment_files = sorted(path for path in metadata_files if path.name.startswith("m_"))
    if not investigation_files:
        add_error(result, "investigation_file_missing", metadata_path, "No investigation file matching i_*.txt found.")
    if len(investigation_files) > 1:
        add_warning(result, "multiple_investigation_files", metadata_path, "Multiple i_*.txt files found; the first sorted file will be used by validation.")
    if not sample_files:
        add_error(result, "sample_file_missing", metadata_path, "No sample file matching s_*.txt found.")
    if not assay_files:
        add_error(result, "assay_file_missing", metadata_path, "No assay file matching a_*.txt found.")
    if not assignment_files:
        add_warning(result, "assignment_file_missing", metadata_path, "No metabolite assignment file matching m_*.tsv found.")


def check_data_folder(data_path, result):
    if not data_path.exists() or not data_path.is_dir():
        add_error(result, "data_path_missing", data_path, f"Data files path does not exist or is not a directory: {data_path}")
        return

    file_count = 0
    folder_count = 0
    for path in sorted(data_path.rglob("*")):
        relative_path = path.relative_to(data_path)
        check_allowed_path(relative_path, path, result)
        if path.is_file():
            file_count += 1
        elif path.is_dir():
            folder_count += 1
            if path.suffix.lower() in RAW_FOLDER_SUFFIXES:
                add_error(
                    result,
                    "raw_data_folder_not_compressed",
                    path,
                    "Raw data folders such as .d or .raw must be compressed individually before submission.",
                )
    result["summary"]["data_files"] = file_count
    result["summary"]["data_folders"] = folder_count


def check_allowed_path(relative_path, absolute_path, result):
    for part in relative_path.parts:
        check_allowed_name(part, absolute_path, result)


def check_allowed_name(name, path, result):
    if not ALLOWED_NAME_RE.fullmatch(name):
        add_error(
            result,
            "filename_contains_invalid_characters",
            path,
            "File and folder names may contain only letters, numbers, hyphen, underscore, and dot.",
        )


def update_summary(result, validation_input):
    result["summary"]["referenced_raw_files"] = len(validation_input.get("referencedRawFiles", []))
    result["summary"]["referenced_derived_files"] = len(validation_input.get("referencedDerivedFiles", []))
    result["summary"]["referenced_assignment_files"] = len(validation_input.get("referencedAssignmentFiles", []))


def check_assay_file_references(validation_input, metadata_path, data_path, result):
    referenced_assignment_files = set()
    referenced_data_files = set()
    for assay_file_name, assay_file in validation_input.get("assays", {}).items():
        rows = table_rows(assay_file.get("table", {}))
        raw_files = get_column_values(rows, RAW_FILE_COLUMNS)
        derived_files = get_column_values(rows, DERIVED_FILE_COLUMNS)
        assignment_files = get_column_values(rows, ASSIGNMENT_FILE_COLUMNS)
        referenced_assignment_files.update(assignment_files)
        referenced_data_files.update(raw_files)
        referenced_data_files.update(derived_files)
        for file_name in raw_files + derived_files:
            if not file_name.startswith("FILES/"):
                add_error(result, "data_reference_without_files_prefix", assay_file_name, f"Data file reference must start with FILES/: {file_name}")
                continue
            relative_name = file_name.removeprefix("FILES/")
            if not (data_path / relative_name).exists():
                add_error(result, "referenced_data_file_missing", assay_file_name, f"Referenced data file or folder was not found: {file_name}")
        for file_name in assignment_files:
            if not (metadata_path / file_name).is_file():
                add_error(result, "referenced_assignment_file_missing", assay_file_name, f"Referenced metabolite assignment file was not found: {file_name}")

    if not referenced_data_files:
        add_warning(result, "data_files_not_referenced", metadata_path, "No raw or derived data files are referenced from assay files.")
    if not referenced_assignment_files:
        add_warning(result, "assignment_files_not_referenced", metadata_path, "No metabolite assignment files are referenced from assay files.")


def check_zip_raw_folder_contents(data_path, result):
    if not data_path.exists() or not data_path.is_dir():
        return
    for zip_path in sorted(data_path.rglob("*.zip")):
        try:
            with zipfile.ZipFile(zip_path) as archive:
                raw_roots = {
                    name.split("/", 1)[0]
                    for name in archive.namelist()
                    if "/" in name and name.split("/", 1)[0].lower().endswith(RAW_FOLDER_SUFFIXES)
                }
        except zipfile.BadZipFile:
            add_error(result, "zip_file_invalid", zip_path, "Zip file could not be read.")
            continue
        if len(raw_roots) > 1:
            add_error(
                result,
                "zip_contains_multiple_raw_folders",
                zip_path,
                "Zip files must not contain multiple raw data folders; compress each raw data folder individually.",
            )


def add_error(result, code, path, message):
    result["errors"].append({"code": code, "path": str(path), "message": message})


def add_warning(result, code, path, message):
    result["warnings"].append({"code": code, "path": str(path), "message": message})


def deduplicate_checks(checks):
    seen = set()
    deduplicated = []
    for check in checks:
        key = (check.get("code"), check.get("path"), check.get("message"))
        if key not in seen:
            deduplicated.append(check)
            seen.add(key)
    return deduplicated
