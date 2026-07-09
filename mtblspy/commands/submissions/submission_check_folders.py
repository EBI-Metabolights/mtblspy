import json
import re
import zipfile
from collections import Counter
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
        check_investigation_completeness(validation_input, result)
        check_sample_assay_consistency(validation_input, result)
        check_assay_file_references(validation_input, metadata_path, data_path, result)

    check_wiff_pairs(data_path, result)
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


def check_investigation_completeness(validation_input, result):
    investigation = validation_input.get("investigation", {})
    studies = investigation.get("studies") or []
    study = studies[0] if studies else {}
    if not (study.get("title") or investigation.get("title")):
        add_error(result, "study_title_missing", validation_input.get("investigationFilePath"), "Study title is missing from the investigation file.")
    if not (study.get("description") or investigation.get("description")):
        add_error(result, "study_description_missing", validation_input.get("investigationFilePath"), "Study abstract or description is missing from the investigation file.")

    descriptors = study.get("studyDesignDescriptors", {}).get("designTypes", [])
    if len(descriptors) < 3:
        add_warning(result, "study_descriptors_incomplete", validation_input.get("investigationFilePath"), "Add at least three study descriptors or keywords.")

    protocols = study.get("studyProtocols", {}).get("protocols", [])
    if not protocols:
        add_error(result, "protocols_missing", validation_input.get("investigationFilePath"), "At least one study protocol is required.")

    factors = study.get("studyFactors", {}).get("factors", [])
    if not factors:
        add_error(result, "study_factor_missing", validation_input.get("investigationFilePath"), "At least one study factor is required.")

    contacts = study.get("studyContacts", {}).get("people", [])
    if not contacts:
        add_error(result, "study_contacts_missing", validation_input.get("investigationFilePath"), "At least one study contact is required.")
    elif not has_principal_investigator(contacts):
        add_warning(result, "principal_investigator_missing", validation_input.get("investigationFilePath"), "Add a principal investigator contact.")


def has_principal_investigator(contacts):
    for contact in contacts:
        for role in contact.get("roles", []):
            if "principal investigator" in str(role.get("term", "")).lower():
                return True
    return False


def check_sample_assay_consistency(validation_input, result):
    sample_names = []
    for sample_file_name, sample_file in validation_input.get("samples", {}).items():
        file_sample_names = sample_file.get("sampleNames", [])
        sample_names.extend(file_sample_names)
        rows = table_rows(sample_file.get("table", {}))
        check_factor_values(sample_file_name, rows, result)

    duplicated_sample_names = sorted(name for name, count in Counter(sample_names).items() if count > 1)
    for sample_name in duplicated_sample_names:
        add_error(result, "sample_name_duplicate", sample_name, f"Sample name is duplicated: {sample_name}")

    known_samples = set(sample_names)
    assay_sample_names = []
    for assay_file_name, assay_file in validation_input.get("assays", {}).items():
        current_assay_samples = assay_file.get("sampleNames", [])
        assay_sample_names.extend(current_assay_samples)
        missing_samples = sorted(set(current_assay_samples) - known_samples)
        for sample_name in missing_samples:
            add_error(result, "assay_sample_not_in_sample_file", assay_file_name, f"Assay references sample not present in sample files: {sample_name}")

    unreferenced_samples = sorted(known_samples - set(assay_sample_names))
    for sample_name in unreferenced_samples:
        add_warning(result, "sample_not_referenced_by_assay", sample_name, f"Sample is not referenced by any assay file: {sample_name}")


def check_factor_values(sample_file_name, rows, result):
    factor_columns = [column for row in rows for column in row if column.startswith("Factor Value[")]
    if not factor_columns:
        add_warning(result, "factor_values_missing", sample_file_name, "Sample file has no Factor Value[...] column.")
        return
    for column in sorted(set(factor_columns)):
        values = {row.get(column, "") for row in rows if row.get(column, "")}
        if not values:
            add_warning(result, "factor_values_empty", sample_file_name, f"Factor column has no values: {column}")
        elif len(rows) >= 2 and len(values) < 2:
            add_warning(result, "factor_values_not_different", sample_file_name, f"At least two rows should have different values for {column}.")


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


def check_wiff_pairs(data_path, result):
    if not data_path.exists() or not data_path.is_dir():
        return
    files_by_lower_path = {str(path.relative_to(data_path)).lower(): path for path in data_path.rglob("*") if path.is_file()}
    for lower_relative_path, path in files_by_lower_path.items():
        if lower_relative_path.endswith(".wiff") and f"{lower_relative_path}.scan" not in files_by_lower_path:
            add_error(result, "wiff_scan_missing", path, ".wiff files must be submitted with the matching .wiff.scan file.")
        elif lower_relative_path.endswith(".wiff.scan"):
            wiff_path = lower_relative_path.removesuffix(".scan")
            if wiff_path not in files_by_lower_path:
                add_error(result, "wiff_missing", path, ".wiff.scan files must be submitted with the matching .wiff file.")


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
