import json
import subprocess
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import requests

from mtblspy.commands.output import resolve_json_output_path, write_json_file
from mtblspy.commands.submissions.client import DEFAULT_LOCAL_SUBMISSION_CACHE_PATH, normalize_study_id
from mtblspy.commands.submissions.exceptions import SubmissionAPIError

DEFAULT_VALIDATION_BUNDLE_URL = "https://ebi-metabolights.github.io/mtbls-validation/bundle.tar.gz"
DEFAULT_VALIDATION_BUNDLE_PATH = "./bundle.tar.gz"
LOCAL_VALIDATION_TIMEOUT_SECONDS = 120


@dataclass
class LocalValidationResult:
    report: dict
    errors: list[dict]
    report_path: Path
    validation_input_path: Path


def run_local_validation(
    study_id,
    metadata_path=None,
    data_files_path=None,
    validation_bundle_path=DEFAULT_VALIDATION_BUNDLE_PATH,
    validation_bundle_url=DEFAULT_VALIDATION_BUNDLE_URL,
    refetch_validation_bundle=False,
    opa_executable_path="opa",
    validation_file_path=None,
    validation_input_path=None,
    config_file=None,
    overridden_rules_file_path=None,
    timeout=LOCAL_VALIDATION_TIMEOUT_SECONDS,
):
    study_id = normalize_study_id(study_id)
    default_cache_directory = DEFAULT_LOCAL_SUBMISSION_CACHE_PATH / study_id
    metadata_path = resolve_metadata_path(study_id, metadata_path)
    if not data_files_path:
        data_files_path = metadata_path / "FILES"
    validation_input = load_local_validation_input(study_id, metadata_path, data_files_path)
    validation_input_path = save_local_validation_input(study_id, validation_input, validation_input_path)
    validation_result = run_opa_validation(
        validation_input_path,
        validation_bundle_path=validation_bundle_path,
        validation_bundle_url=validation_bundle_url,
        refetch_validation_bundle=refetch_validation_bundle,
        opa_executable_path=opa_executable_path,
        timeout=timeout,
    )

    overridden_rule_ids, overridden_files = get_overrides(config_file, overridden_rules_file_path)
    errors, overrides = split_validation_errors(validation_result, overridden_rule_ids, overridden_files)
    report = {
        "accession": study_id,
        "status": "failed" if errors else "success",
        "validationResult": validation_result,
        "errors": errors,
        "overrides": overrides,
    }
    report_path = save_local_validation_report(
        study_id,
        report,
        validation_file_path,
        default_cache_directory,
    )
    return LocalValidationResult(
        report=report,
        errors=errors,
        report_path=report_path,
        validation_input_path=validation_input_path,
    )


def resolve_metadata_path(study_id, metadata_path=None):
    if metadata_path:
        return Path(metadata_path).expanduser().resolve()
    return (Path.home() / "metabolights_data" / "submission" / "data" / study_id).resolve()


def load_local_validation_input(study_id, metadata_path, data_files_path):
    metadata_path = Path(metadata_path)
    if not metadata_path.exists() or not metadata_path.is_dir():
        raise SubmissionAPIError(f"Metadata path does not exist or is not a directory: {metadata_path}")

    investigation_path = get_investigation_file(metadata_path)
    sample_files = sorted(metadata_path.glob("s_*.txt"))
    assay_files = sorted(metadata_path.glob("a_*.txt"))
    assignment_files = sorted(metadata_path.glob("m_*.tsv"))

    samples = {path.name: build_table_file(path, file_type="sample") for path in sample_files}
    assays = {path.name: build_assay_file(path) for path in assay_files}
    metabolite_assignments = {path.name: build_table_file(path, file_type="assignment") for path in assignment_files}

    referenced_assignment_files = sorted(
        {
            file_name
            for assay in assays.values()
            for file_name in assay.get("referencedAssignmentFiles", [])
        }
    )
    referenced_raw_files = sorted(
        {
            file_name
            for assay in assays.values()
            for file_name in assay.get("referencedRawFiles", [])
        }
    )
    referenced_derived_files = sorted(
        {
            file_name
            for assay in assays.values()
            for file_name in assay.get("referencedDerivedFiles", [])
        }
    )

    return {
        "version": "v1.1",
        "investigationFilePath": investigation_path.name,
        "investigation": build_investigation(investigation_path),
        "samples": samples,
        "assays": assays,
        "parserMessages": {},
        "referencedAssignmentFiles": referenced_assignment_files,
        "referencedRawFiles": referenced_raw_files,
        "referencedDerivedFiles": referenced_derived_files,
        "foldersInHierarchy": get_folders_in_hierarchy(referenced_raw_files + referenced_derived_files),
        "metaboliteAssignments": metabolite_assignments,
        "tags": [],
        "studyDbMetadata": build_study_db_metadata(study_id),
        "studyFolderMetadata": build_study_folder_metadata(metadata_path, data_files_path),
        "folderReaderMessages": [],
        "dbReaderMessages": [],
        "hasDbMetadata": False,
        "hasSampleTableData": bool(samples),
        "hasAssayTableData": bool(assays),
        "hasAssignmentTableData": bool(metabolite_assignments),
        "hasFolderMetadata": True,
        "hasInvestigationData": True,
    }


def get_investigation_file(metadata_path):
    investigation_files = sorted(metadata_path.glob("i_*.txt"))
    if not investigation_files:
        raise SubmissionAPIError(f"No investigation file matching i_*.txt found in {metadata_path}")
    return investigation_files[0]


def build_investigation(investigation_path):
    sections = parse_investigation_sections(investigation_path)
    investigation_values = section_values(sections.get("INVESTIGATION", []))
    study_values = section_values(sections.get("STUDY", []))
    return {
        "comments": [],
        "identifier": first_value(investigation_values, "Investigation Identifier"),
        "title": first_value(investigation_values, "Investigation Title"),
        "description": first_value(investigation_values, "Investigation Description"),
        "submissionDate": first_value(investigation_values, "Investigation Submission Date"),
        "publicReleaseDate": first_value(investigation_values, "Investigation Public Release Date"),
        "ontologySourceReferences": {"comments": [], "references": []},
        "investigationPublications": {"comments": [], "publications": []},
        "investigationContacts": {"comments": [], "people": []},
        "studies": [
            {
                "comments": [],
                "identifier": first_value(study_values, "Study Identifier"),
                "title": first_value(study_values, "Study Title"),
                "description": first_value(study_values, "Study Description"),
                "submissionDate": first_value(study_values, "Study Submission Date"),
                "publicReleaseDate": first_value(study_values, "Study Public Release Date"),
                "fileName": first_value(study_values, "Study File Name"),
                "studyCategory": "",
                "templateVersion": "",
                "sampleTemplate": "",
                "studyTemplate": "",
                "linkedStudyAccession": [],
                "mhdAccession": "",
                "mhdModelVersion": "",
                "createdAt": "",
                "revisionNumber": "",
                "revisionDate": "",
                "revisionComment": "",
                "studyDesignDescriptors": {"comments": [], "designDescriptors": []},
                "studyPublications": {"comments": [], "publications": []},
                "studyFactors": {"comments": [], "factors": []},
                "studyAssays": {
                    "comments": [],
                    "assays": build_study_assay_entries(sections.get("STUDY ASSAYS", [])),
                },
                "studyProtocols": {"comments": [], "protocols": []},
                "studyContacts": {"comments": [], "people": []},
            }
        ],
        "sections": sections,
    }


def parse_investigation_sections(path):
    sections = {}
    current_section = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        cells = split_isa_line(raw_line)
        if not cells:
            continue
        if len(cells) == 1 and cells[0] and not cells[0].startswith(("Comment[", "#")):
            current_section = cells[0]
            sections.setdefault(current_section, [])
            continue
        if current_section:
            sections.setdefault(current_section, []).append(cells)
    return sections


def section_values(rows):
    return {row[0]: row[1:] for row in rows if row}


def first_value(values, key):
    items = values.get(key) or []
    return items[0] if items else ""


def build_study_assay_entries(rows):
    values = section_values(rows)
    file_names = values.get("Study Assay File Name", [])
    measurement_types = values.get("Study Assay Measurement Type", [])
    measurement_accessions = values.get("Study Assay Measurement Type Term Accession Number", [])
    measurement_sources = values.get("Study Assay Measurement Type Term Source REF", [])
    technology_types = values.get("Study Assay Technology Type", [])
    technology_accessions = values.get("Study Assay Technology Type Term Accession Number", [])
    technology_sources = values.get("Study Assay Technology Type Term Source REF", [])
    platforms = values.get("Study Assay Technology Platform", [])

    assays = []
    for index, file_name in enumerate(file_names):
        assays.append(
            {
                "fileName": file_name,
                "measurementType": ontology_annotation(
                    get_index(measurement_types, index),
                    get_index(measurement_accessions, index),
                    get_index(measurement_sources, index),
                ),
                "technologyType": ontology_annotation(
                    get_index(technology_types, index),
                    get_index(technology_accessions, index),
                    get_index(technology_sources, index),
                ),
                "technologyPlatform": get_index(platforms, index),
                "assayIdentifier": "",
                "assayType": ontology_annotation(),
                "omicsType": ontology_annotation(),
                "assayDescriptors": [],
                "resultFileFormat": "",
            }
        )
    return assays


def ontology_annotation(term="", term_accession_number="", term_source_ref=""):
    return {
        "term": term,
        "termAccessionNumber": term_accession_number,
        "termSourceRef": term_source_ref,
    }


def build_table_file(path, file_type):
    table = parse_isa_table(path)
    return {
        "filePath": path.name,
        "sha256Hash": sha256_file(path),
        "table": table,
        **table_file_summary(table, file_type),
    }


def build_assay_file(path):
    table_file = build_table_file(path, file_type="assay")
    rows = table_rows(table_file["table"])
    raw_files = get_column_values(rows, RAW_FILE_COLUMNS)
    derived_files = get_column_values(rows, DERIVED_FILE_COLUMNS)
    assignment_files = get_column_values(rows, ASSIGNMENT_FILE_COLUMNS)
    table_file.update(
        {
            "referencedAssignmentFiles": sorted(set(assignment_files)),
            "referencedRawFiles": sorted(set(raw_files)),
            "referencedDerivedFiles": sorted(set(derived_files)),
            "referencedRawFileExtensions": sorted({Path(value).suffix for value in raw_files if Path(value).suffix}),
            "referencedDerivedFileExtensions": sorted(
                {Path(value).suffix for value in derived_files if Path(value).suffix}
            ),
            "assayTechnique": {"name": "", "mainTechnique": "", "technique": "", "subTechnique": ""},
            "numberOfAssayRows": table_file["table"]["totalRowCount"],
        }
    )
    return table_file


RAW_FILE_COLUMNS = {
    "Raw Data File",
    "Raw Spectral Data File",
    "Raw Data File Name",
    "Free Induction Decay Data File",
}
DERIVED_FILE_COLUMNS = {
    "Derived Data File",
    "Derived Spectral Data File",
    "Derived Data File Name",
}
ASSIGNMENT_FILE_COLUMNS = {"Metabolite Assignment File"}


def parse_isa_table(path):
    rows = [split_isa_line(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    headers = rows[0] if rows else []
    data_rows = rows[1:]
    columns = [{"index": index, "header": header} for index, header in enumerate(headers)]
    data = {
        str(row_index): {
            header: get_index(row, column_index)
            for column_index, header in enumerate(headers)
        }
        for row_index, row in enumerate(data_rows)
    }
    return {
        "columns": columns,
        "headers": headers,
        "data": data,
        "rowIndices": list(range(len(data_rows))),
        "columnIndices": list(range(len(headers))),
        "filteredTotalRowCount": len(data_rows),
        "rowOffset": 0,
        "rowCount": len(data_rows),
        "totalRowCount": len(data_rows),
        "selectedColumnCount": len(headers),
        "totalColumnCount": len(headers),
        "filterOptions": [],
        "sortOptions": [],
    }


def split_isa_line(line):
    return [cell.strip().strip('"') for cell in line.rstrip("\n").split("\t")]


def table_file_summary(table, file_type):
    rows = table_rows(table)
    if file_type == "sample":
        return {
            "sampleNames": sorted(set(get_column_values(rows, {"Sample Name"}))),
            "numberOfSampleRows": table["totalRowCount"],
        }
    if file_type == "assay":
        return {
            "sampleNames": sorted(set(get_column_values(rows, {"Sample Name"}))),
            "assayNames": sorted(set(get_column_values(rows, {"Assay Name", "NMR Assay Name"}))),
        }
    return {
        "metaboliteIdentificationRowsCount": table["totalRowCount"],
    }


def table_rows(table):
    return [table["data"][str(index)] for index in table["rowIndices"]]


def get_column_values(rows, column_names):
    values = []
    for row in rows:
        for column_name in column_names:
            value = row.get(column_name, "")
            if value:
                values.append(value)
    return values


def get_folders_in_hierarchy(file_paths):
    folders = set()
    for file_path in file_paths:
        parent = Path(file_path).parent
        while str(parent) not in ("", "."):
            folders.add(parent.as_posix())
            parent = parent.parent
    return sorted(folders)


def build_study_db_metadata(study_id):
    numeric_part = "".join(character for character in study_id if character.isdigit())
    return {
        "dbId": -1,
        "studyId": study_id,
        "numericStudyId": int(numeric_part) if numeric_part else -1,
        "obfuscationCode": "",
        "studySize": -1,
        "submissionDate": "",
        "releaseDate": "",
        "updateDate": "",
        "statusDate": "",
        "studyTypes": [],
        "status": "SUBMITTED",
        "curationRequest": "MANUAL_CURATION",
        "overrides": {},
        "submitters": [],
        "reservedAccession": "",
        "reservedSubmissionId": "",
        "revisionDate": "",
        "revisionNumber": 0,
        "revisionComment": "",
        "firstPrivateDate": "",
        "firstPublicDate": "",
        "datasetLicense": "",
        "datasetLicenseVersion": "",
        "datasetLicenseUrl": "",
        "sampleTemplate": "",
        "studyTemplate": "",
        "studyCategory": 0,
        "templateVersion": "",
        "reservedMhdAccession": "",
        "mhdModelVersion": "",
        "createdAt": "",
    }


def build_study_folder_metadata(metadata_path, data_files_path):
    folders = {}
    files = {}
    for path in sorted(metadata_path.rglob("*")):
        relative_path = path.relative_to(metadata_path).as_posix()
        descriptor = file_descriptor(path, relative_path)
        if path.is_dir():
            folders[relative_path] = descriptor
        else:
            files[relative_path] = descriptor

    data_path = Path(data_files_path)
    if not data_path.is_absolute():
        data_path = metadata_path / data_path
    if data_path.exists():
        for path in sorted(data_path.rglob("*")):
            relative_path = path.relative_to(metadata_path).as_posix() if path.is_relative_to(metadata_path) else path.name
            descriptor = file_descriptor(path, relative_path)
            if path.is_dir():
                folders[relative_path] = descriptor
            else:
                files[relative_path] = descriptor

    return {
        "dataFolderSizeCalculated": False,
        "metadataFolderSizeCalculated": False,
        "folderSizeInBytes": -1,
        "folderSizeInStr": "",
        "folders": folders,
        "files": files,
    }


def file_descriptor(path, relative_path):
    stat = path.stat()
    return {
        "filePath": relative_path,
        "baseName": path.name,
        "parentDirectory": str(Path(relative_path).parent) if str(Path(relative_path).parent) != "." else "",
        "extension": path.suffix,
        "sizeInBytes": stat.st_size,
        "isDirectory": path.is_dir(),
        "isLink": path.is_symlink(),
        "modifiedAt": int(stat.st_mtime),
        "createdAt": int(stat.st_ctime),
        "mode": oct(stat.st_mode & 0o777),
        "tags": [],
    }


def sha256_file(path):
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_index(values, index, default=""):
    return values[index] if index < len(values) else default


def save_local_validation_input(study_id, validation_input, validation_input_path=None):
    default_directory = DEFAULT_LOCAL_SUBMISSION_CACHE_PATH / study_id
    default_filename = f"{study_id}_local_validation_input.json"
    output_path = resolve_json_output_path(validation_input_path, default_directory, default_filename)
    return write_json_file(validation_input, output_path)


def run_opa_validation(
    validation_input_path,
    validation_bundle_path=DEFAULT_VALIDATION_BUNDLE_PATH,
    validation_bundle_url=DEFAULT_VALIDATION_BUNDLE_URL,
    refetch_validation_bundle=False,
    opa_executable_path="opa",
    timeout=LOCAL_VALIDATION_TIMEOUT_SECONDS,
):
    validation_bundle_path = ensure_validation_bundle(validation_bundle_path, validation_bundle_url, refetch_validation_bundle)
    command = [
        opa_executable_path,
        "eval",
        "--data",
        str(validation_bundle_path),
        "data.metabolights.validation.v2.report.complete_report",
        "-i",
        str(validation_input_path),
    ]
    try:
        task = subprocess.run(command, capture_output=True, text=True, check=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise SubmissionAPIError(
            f"OPA executable not found: {opa_executable_path}. "
            "Install OPA or pass --opa-executable-path."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise SubmissionAPIError("The local validation process timed out.") from exc
    except subprocess.CalledProcessError as exc:
        message = exc.stderr or exc.stdout or str(exc)
        raise SubmissionAPIError(f"The local validation process failed: {message}") from exc

    return parse_opa_validation_output(task.stdout)


def ensure_validation_bundle(validation_bundle_path, validation_bundle_url, refetch_validation_bundle=False):
    validation_bundle_path = Path(validation_bundle_path).expanduser().resolve()
    if validation_bundle_path.exists() and not refetch_validation_bundle:
        return validation_bundle_path

    if not validation_bundle_url:
        raise SubmissionAPIError(f"Validation bundle does not exist on {validation_bundle_path}")
    validation_bundle_path.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(validation_bundle_url, timeout=60)
    response.raise_for_status()
    validation_bundle_path.write_bytes(response.content)
    return validation_bundle_path


def parse_opa_validation_output(output):
    try:
        raw_validation_result = json.loads(output)
    except json.JSONDecodeError as exc:
        raise SubmissionAPIError("OPA validation output is not valid JSON.") from exc

    try:
        return raw_validation_result["result"][0]["expressions"][0]["value"]
    except (KeyError, IndexError, TypeError) as exc:
        raise SubmissionAPIError("OPA validation output did not include a validation result.") from exc


def get_overrides(config_file=None, overridden_rules_file_path=None):
    overridden_rule_ids = get_overridden_rule_ids(config_file)
    file_rule_ids, overridden_files = get_text_overrides(overridden_rules_file_path)
    return overridden_rule_ids | file_rule_ids, overridden_files


def get_overridden_rule_ids(config_file=None):
    if not config_file:
        return set()
    with Path(config_file).expanduser().open("r", encoding="utf-8") as file:
        config = json.load(file)
    overrides = config.get("validation", {}).get("overrides", [])
    return {override.get("ruleId") for override in overrides if override.get("ruleId")}


def get_text_overrides(overridden_rules_file_path=None):
    if not overridden_rules_file_path:
        return set(), set()
    override_values = Path(overridden_rules_file_path).expanduser().read_text(encoding="utf-8").split()
    overridden_rule_ids = {value for value in override_values if value.startswith("rule_")}
    overridden_files = {
        value
        for value in override_values
        if len(value) > 2 and value[:2] in {"a_", "i_", "s_", "m_"}
    }
    return overridden_rule_ids, overridden_files


def split_validation_errors(validation_result, overridden_rule_ids=None, overridden_files=None):
    overridden_rule_ids = overridden_rule_ids or set()
    overridden_files = overridden_files or set()
    violations = validation_result.get("violations", []) if isinstance(validation_result, dict) else []
    errors = []
    overrides = []
    for violation in violations:
        if not is_error_violation(violation):
            continue
        if violation.get("identifier") in overridden_rule_ids:
            overrides.append(mark_overridden(violation, "rule id is in the exclude list"))
        elif violation.get("sourceFile") in overridden_files or violation.get("source_file") in overridden_files:
            overrides.append(mark_overridden(violation, "file name is in the exclude list"))
        else:
            errors.append(violation)
    return errors, overrides


def is_error_violation(violation):
    return str(violation.get("type", "")).upper() == "ERROR"


def mark_overridden(violation, comment):
    output = dict(violation)
    output["overridden"] = True
    output["overrideComment"] = comment
    output["type"] = "WARNING"
    return output


def save_local_validation_report(study_id, report, validation_file_path=None, default_directory=None):
    default_directory = default_directory or DEFAULT_LOCAL_SUBMISSION_CACHE_PATH / study_id
    output_path = resolve_json_output_path(
        validation_file_path,
        default_directory,
        f"{study_id}_local_validation_report.json",
    )
    return write_json_file(report, output_path)
