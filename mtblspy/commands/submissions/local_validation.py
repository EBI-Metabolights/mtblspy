import json
import shutil
import subprocess
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import requests

from mtblspy.commands.output import resolve_json_output_path, write_json_file
from mtblspy.commands.submissions.client import (
    DEFAULT_LOCAL_SUBMISSION_CACHE_PATH,
    DEFAULT_LOCAL_SUBMISSION_DATA_PATH,
    normalize_study_id,
)
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
    default_submission_data_path=None,
    validation_bundle_path=DEFAULT_VALIDATION_BUNDLE_PATH,
    validation_bundle_url=DEFAULT_VALIDATION_BUNDLE_URL,
    refetch_validation_bundle=False,
    opa_executable_path="opa",
    validation_wasm_path=None,
    validation_wasm_url=None,
    validation_file_path=None,
    validation_input_path=None,
    config_file=None,
    overridden_rules_file_path=None,
    timeout=LOCAL_VALIDATION_TIMEOUT_SECONDS,
):
    study_id = normalize_study_id(study_id)
    default_cache_directory = DEFAULT_LOCAL_SUBMISSION_CACHE_PATH / study_id
    metadata_path = resolve_metadata_path(study_id, metadata_path, default_submission_data_path)
    if not data_files_path:
        data_files_path = metadata_path / "FILES"
    validation_input = load_local_validation_input(study_id, metadata_path, data_files_path)
    validation_input_path = save_local_validation_input(study_id, validation_input, validation_input_path)
    if validation_wasm_path or validation_wasm_url:
        validation_result = run_wasm_validation(
            validation_input_path,
            validation_wasm_path=validation_wasm_path,
            validation_wasm_url=validation_wasm_url,
            timeout=timeout,
        )
    else:
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


def resolve_metadata_path(study_id, metadata_path=None, default_submission_data_path=None):
    if metadata_path:
        return Path(metadata_path).expanduser().resolve()
    default_data_path = Path(default_submission_data_path).expanduser() if default_submission_data_path else DEFAULT_LOCAL_SUBMISSION_DATA_PATH
    return (default_data_path / study_id).resolve()


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
    metabolite_assignments = {path.name: build_assignment_file(path) for path in assignment_files}

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

    parser_messages = build_parser_messages(
        investigation_path,
        sample_files,
        assay_files,
        assignment_files,
    )

    return {
        "version": "v1.1",
        "investigationFilePath": investigation_path.name,
        "investigation": build_investigation(investigation_path),
        "samples": samples,
        "assays": assays,
        "parserMessages": parser_messages,
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


def build_parser_messages(*file_groups):
    parser_messages = {}
    for file_group in file_groups:
        if isinstance(file_group, Path):
            parser_messages[file_group.name] = []
            continue
        for path in file_group:
            parser_messages[path.name] = []
    return parser_messages


def build_investigation(investigation_path):
    sections = parse_investigation_sections(investigation_path)
    investigation_values = section_values(sections.get("INVESTIGATION", []))
    study_values = section_values(sections.get("STUDY", []))
    study_comments = comment_values(study_values)
    return {
        "comments": [],
        "identifier": first_value(investigation_values, "Investigation Identifier"),
        "title": first_value(investigation_values, "Investigation Title"),
        "description": first_value(investigation_values, "Investigation Description"),
        "submissionDate": first_value(investigation_values, "Investigation Submission Date"),
        "publicReleaseDate": first_value(investigation_values, "Investigation Public Release Date"),
        "ontologySourceReferences": {
            "comments": [],
            "references": build_ontology_source_references(sections.get("ONTOLOGY SOURCE REFERENCE", [])),
        },
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
                "studyCategory": first_value(study_comments, "Study Category"),
                "templateVersion": first_value(study_comments, "Template Version"),
                "sampleTemplate": first_value(study_comments, "Sample Template"),
                "studyTemplate": first_value(study_comments, "Study Template"),
                "mhdAccession": first_value(study_comments, "MHD Accession"),
                "mhdModelVersion": first_value(study_comments, "MHD Model Version"),
                "createdAt": first_value(study_comments, "Created At"),
                "revisionNumber": first_value(study_comments, "Revision"),
                "revisionDate": first_value(study_comments, "Revision Date"),
                "revisionComment": first_value(study_comments, "Revision Log"),
                "datasetLicense": first_value(study_comments, "License"),
                "funders": [],
                "characteristicTypes": [],
                "studyDesignDescriptors": {
                    "comments": [],
                    "designTypes": build_study_design_descriptors(sections.get("STUDY DESIGN DESCRIPTORS", [])),
                },
                "studyPublications": {
                    "comments": [],
                    "publications": build_study_publications(sections.get("STUDY PUBLICATIONS", [])),
                },
                "studyFactors": {
                    "comments": [],
                    "factors": build_study_factors(sections.get("STUDY FACTORS", [])),
                },
                "studyAssays": {
                    "comments": [],
                    "assays": build_study_assay_entries(sections.get("STUDY ASSAYS", [])),
                },
                "studyProtocols": {
                    "comments": [],
                    "protocols": build_study_protocols(sections.get("STUDY PROTOCOLS", [])),
                },
                "studyContacts": {
                    "comments": [],
                    "people": build_study_contacts(sections.get("STUDY CONTACTS", [])),
                },
            }
        ],
    }


def parse_investigation_sections(path):
    sections = {}
    current_section = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        cells = split_isa_line(raw_line)
        if not cells:
            continue
        if is_investigation_section_line(cells):
            current_section = cells[0]
            sections.setdefault(current_section, [])
            continue
        if current_section:
            sections.setdefault(current_section, []).append(cells)
    return sections


def is_investigation_section_line(cells):
    section_name = cells[0]
    return bool(
        section_name
        and section_name == section_name.upper()
        and not section_name.startswith(("Comment[", "#"))
        and all(not cell for cell in cells[1:])
    )


def section_values(rows):
    return {row[0]: trim_trailing_empty_values(row[1:]) for row in rows if row}


def trim_trailing_empty_values(values):
    values = list(values)
    while values and values[-1] == "":
        values.pop()
    return values


def first_value(values, key):
    items = values.get(key) or []
    return items[0] if items else ""


def comment_values(values):
    comments = {}
    for key, value in values.items():
        if key.startswith("Comment[") and key.endswith("]"):
            comments[key.removeprefix("Comment[").removesuffix("]")] = value
    return comments


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


def build_study_design_descriptors(rows):
    values = section_values(rows)
    terms = values.get("Study Design Type", [])
    accessions = values.get("Study Design Type Term Accession Number", [])
    sources = values.get("Study Design Type Term Source REF", [])
    comments = comment_values(values)
    categories = comments.get("Study Design Category", [])
    descriptor_sources = comments.get("Study Design Source", [])

    descriptors = []
    for index in range(max_length(terms, accessions, sources, categories, descriptor_sources)):
        term = get_index(terms, index)
        if term:
            descriptors.append(
                {
                    "term": term,
                    "termAccessionNumber": get_index(accessions, index),
                    "termSourceRef": get_index(sources, index),
                    "category": get_index(categories, index),
                    "source": get_index(descriptor_sources, index),
                }
            )
    return descriptors


def build_study_publications(rows):
    values = section_values(rows)
    pubmed_ids = values.get("Study PubMed ID", [])
    dois = values.get("Study Publication DOI", [])
    authors = values.get("Study Publication Author List", [])
    titles = values.get("Study Publication Title", [])
    statuses = values.get("Study Publication Status", [])
    accessions = values.get("Study Publication Status Term Accession Number", [])
    sources = values.get("Study Publication Status Term Source REF", [])

    publications = []
    for index in range(max_length(pubmed_ids, dois, authors, titles, statuses)):
        publication = {
            "pubMedId": get_index(pubmed_ids, index),
            "doi": get_index(dois, index),
            "authorList": get_index(authors, index),
            "title": get_index(titles, index),
            "status": ontology_annotation(
                get_index(statuses, index),
                get_index(accessions, index),
                get_index(sources, index),
            ),
        }
        if any([publication["pubMedId"], publication["doi"], publication["authorList"], publication["title"]]):
            publications.append(publication)
    return publications


def build_study_factors(rows):
    values = section_values(rows)
    names = values.get("Study Factor Name", [])
    types = values.get("Study Factor Type", [])
    accessions = values.get("Study Factor Type Term Accession Number", [])
    sources = values.get("Study Factor Type Term Source REF", [])

    factors = []
    for index in range(max_length(names, types)):
        name = get_index(names, index) or get_index(types, index)
        factor_type = ontology_annotation(
            get_index(types, index),
            get_index(accessions, index),
            get_index(sources, index),
        )
        if name or factor_type["term"]:
            factors.append({"name": name, "type": factor_type, "valueFormat": ""})
    return factors


def build_study_protocols(rows):
    values = section_values(rows)
    names = values.get("Study Protocol Name", [])
    types = values.get("Study Protocol Type", [])
    accessions = values.get("Study Protocol Type Term Accession Number", [])
    sources = values.get("Study Protocol Type Term Source REF", [])
    descriptions = values.get("Study Protocol Description", [])
    uris = values.get("Study Protocol URI", [])
    versions = values.get("Study Protocol Version", [])
    parameter_names = values.get("Study Protocol Parameters Name", [])
    parameter_accessions = values.get("Study Protocol Parameters Name Term Accession Number", [])
    parameter_sources = values.get("Study Protocol Parameters Name Term Source REF", [])
    parameter_value_formats = values.get("Comment[Study Protocol Parameters Value Format]", [])

    protocols = []
    for index in range(max_length(names, types, descriptions, parameter_names)):
        name = get_index(names, index)
        protocol_type = ontology_annotation(
            get_index(types, index),
            get_index(accessions, index),
            get_index(sources, index),
        )
        protocol = {
            "name": name,
            "protocolType": protocol_type,
            "description": get_index(descriptions, index),
            "uri": get_index(uris, index),
            "version": get_index(versions, index),
            "parameters": build_protocol_parameters(
                get_index(parameter_names, index),
                get_index(parameter_accessions, index),
                get_index(parameter_sources, index),
                get_index(parameter_value_formats, index),
            ),
            "components": [],
        }
        if name or protocol_type["term"] or protocol["description"] or protocol["parameters"]:
            protocols.append(protocol)
    return protocols


def build_ontology_source_references(rows):
    values = section_values(rows)
    names = values.get("Term Source Name", [])
    files = values.get("Term Source File", [])
    versions = values.get("Term Source Version", [])
    descriptions = values.get("Term Source Description", [])

    references = []
    for index in range(max_length(names, files, versions, descriptions)):
        source_name = get_index(names, index)
        if source_name:
            references.append(
                {
                    "sourceName": source_name,
                    "sourceFile": get_index(files, index),
                    "sourceVersion": get_index(versions, index),
                    "sourceDescription": get_index(descriptions, index),
                }
            )
    return references


def build_study_contacts(rows):
    values = section_values(rows)
    last_names = values.get("Study Person Last Name", [])
    first_names = values.get("Study Person First Name", [])
    mid_initials = values.get("Study Person Mid Initials", [])
    emails = values.get("Study Person Email", [])
    phones = values.get("Study Person Phone", [])
    faxes = values.get("Study Person Fax", [])
    addresses = values.get("Study Person Address", [])
    affiliations = values.get("Study Person Affiliation", [])
    roles = values.get("Study Person Roles", [])
    role_accessions = values.get("Study Person Roles Term Accession Number", [])
    role_sources = values.get("Study Person Roles Term Source REF", [])
    comments = comment_values(values)
    orcids = comments.get("Study Person ORCID", [])
    affiliation_ror_ids = comments.get("Study Person Affiliation ROR ID", [])

    people = []
    for index in range(max_length(last_names, first_names, emails, affiliations, roles)):
        person = {
            "lastName": get_index(last_names, index),
            "firstName": get_index(first_names, index),
            "midInitials": get_index(mid_initials, index),
            "email": get_index(emails, index),
            "phone": get_index(phones, index),
            "fax": get_index(faxes, index),
            "address": get_index(addresses, index),
            "affiliation": get_index(affiliations, index),
            "roles": build_contact_roles(
                get_index(roles, index),
                get_index(role_accessions, index),
                get_index(role_sources, index),
            ),
            "orcid": get_index(orcids, index),
            "additionalEmails": [],
            "affiliationRorId": get_index(affiliation_ror_ids, index),
        }
        if any([person["lastName"], person["firstName"], person["email"], person["affiliation"], person["roles"]]):
            people.append(person)
    return people


def build_contact_roles(roles, accessions="", sources=""):
    roles = split_multi_value(roles)
    accessions = split_multi_value(accessions)
    sources = split_multi_value(sources)
    return [
        ontology_annotation(role, get_index(accessions, index), get_index(sources, index))
        for index, role in enumerate(roles)
        if role
    ]


def build_protocol_parameters(names, accessions="", sources="", value_formats=""):
    names = split_multi_value(names)
    accessions = split_multi_value(accessions)
    sources = split_multi_value(sources)
    value_formats = split_multi_value(value_formats)
    parameters = []
    for index, name in enumerate(names):
        if name:
            parameters.append(
                {
                    "term": name,
                    "termAccessionNumber": get_index(accessions, index),
                    "termSourceRef": get_index(sources, index),
                    "valueFormat": get_index(value_formats, index),
                }
            )
    return parameters


def split_multi_value(value):
    return [item.strip() for item in value.split(";")] if value else []


def max_length(*values):
    return max((len(value) for value in values), default=0)


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
            "referencedRawFileExtensions": sorted({Path(value).suffix.lower() for value in raw_files if Path(value).suffix}),
            "referencedDerivedFileExtensions": sorted(
                {Path(value).suffix.lower() for value in derived_files if Path(value).suffix}
            ),
            "assayTechnique": infer_assay_technique(path, table_file["table"]),
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
    columns = unique_column_names(headers)
    data = {
        column_name: [get_index(row, column_index) for row in data_rows]
        for column_index, column_name in enumerate(columns)
    }
    return {
        "columns": columns,
        "headers": isa_table_headers(headers, columns),
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


def unique_column_names(headers):
    seen = {}
    columns = []
    for header in headers:
        count = seen.get(header, 0)
        columns.append(header if count == 0 else f"{header}.{count}")
        seen[header] = count + 1
    return columns


def isa_table_headers(headers, columns):
    table_headers = []
    linked_column_indexes = set()
    for index, column_name in enumerate(columns):
        column_header = headers[index] if index < len(headers) else ""
        if index in linked_column_indexes:
            table_headers.append(
                isa_table_header(
                    index,
                    column_name,
                    column_header,
                    column_category="Linked Column",
                    column_structure="LINKED_COLUMN",
                )
            )
            continue

        additional_columns = linked_columns_after(headers, index)
        linked_column_indexes.update(range(index + 1, index + 1 + len(additional_columns)))
        table_headers.append(
            isa_table_header(
                index,
                column_name,
                column_header,
                additional_columns=additional_columns,
                column_structure=column_structure(additional_columns),
            )
        )
    return table_headers


def isa_table_header(
    column_index,
    column_name,
    column_header,
    additional_columns=None,
    column_category=None,
    column_structure="SINGLE_COLUMN",
):
    return {
        "columnIndex": column_index,
        "columnName": column_name,
        "columnHeader": column_header,
        "additionalColumns": additional_columns or [],
        "columnCategory": column_category or default_column_category(column_header),
        "columnStructure": column_structure,
        "columnPrefix": column_prefix(column_header),
        "columnSearchPattern": "",
    }


def linked_columns_after(headers, index):
    next_headers = headers[index + 1 : index + 4]
    if len(next_headers) >= 3 and is_unit_header(next_headers[0]) and is_term_source_header(next_headers[1]):
        if is_term_accession_header(next_headers[2]):
            return ["Unit", "Term Source REF", "Term Accession Number"]
    if len(next_headers) >= 2 and is_term_source_header(next_headers[0]) and is_term_accession_header(next_headers[1]):
        return ["Term Source REF", "Term Accession Number"]
    return []


def column_structure(additional_columns):
    if additional_columns == ["Unit", "Term Source REF", "Term Accession Number"]:
        return "SINGLE_COLUMN_AND_UNIT_ONTOLOGY"
    if additional_columns == ["Term Source REF", "Term Accession Number"]:
        return "ONTOLOGY_COLUMN"
    return "SINGLE_COLUMN"


def is_unit_header(header):
    return header == "Unit"


def is_term_source_header(header):
    return header == "Term Source REF"


def is_term_accession_header(header):
    return header == "Term Accession Number"


def default_column_category(column_header):
    if column_header in {"Source Name", "Sample Name"}:
        return "Basic"
    if "[" in column_header:
        return column_header.split("[", 1)[0].strip()
    if column_header.startswith("Protocol REF"):
        return "Protocol"
    return column_header


def column_prefix(column_header):
    if "[" not in column_header or "]" not in column_header:
        if column_header.startswith("Protocol REF"):
            return "Protocol"
        return ""
    return column_header.split("[", 1)[0].strip()


def table_file_summary(table, file_type):
    rows = table_rows(table)
    if file_type == "sample":
        return {
            "sampleNames": sorted(set(get_column_values(rows, {"Sample Name"}))),
            "organisms": ontology_values(table, "Characteristics[Organism]"),
            "organismParts": ontology_values(table, "Characteristics[Organism part]"),
            "organismAndOrganismPartPairs": organism_pairs(table),
            "variants": ontology_values(table, "Characteristics[Variant]"),
            "sampleTypes": ontology_values(table, "Characteristics[Sample type]"),
        }
    if file_type == "assay":
        return {
            "sampleNames": sorted(set(get_column_values(rows, {"Sample Name"}))),
            "assayNames": sorted(set(get_column_values(rows, {"Assay Name", "NMR Assay Name"}))),
        }
    return {}


def build_assignment_file(path):
    table_file = build_table_file(path, file_type="assignment")
    rows = table_rows(table_file["table"])
    metabolite_names = get_column_values(rows, {"metabolite_identification"})
    assigned_rows = [
        row
        for row in rows
        if row.get("metabolite_identification", "") and row.get("database_identifier", "")
    ]
    assignments = {
        row.get("metabolite_identification", ""): row.get("database_identifier", "")
        for row in assigned_rows
    }
    table_file.update(
        {
            "identifiedMetaboliteNames": sorted(set(metabolite_names)),
            "metaboliteAssignments": assignments,
            "assayTechnique": infer_assay_technique(path, table_file["table"]),
            "numberOfRows": table_file["table"]["totalRowCount"],
            "numberOfAssignedRows": len(assigned_rows),
            "numberOfUnassignedRows": max(table_file["table"]["totalRowCount"] - len(assigned_rows), 0),
        }
    )
    return table_file


def table_rows(table):
    rows = []
    columns = table.get("columns", [])
    data = table.get("data", {})
    for row_index in table.get("rowIndices", []):
        row = {}
        for column in columns:
            values = data.get(column, [])
            row[column] = get_index(values, row_index)
        rows.append(row)
    return rows


def get_column_values(rows, column_names):
    values = []
    for row in rows:
        for column_name in column_names:
            value = row.get(column_name, "")
            if value:
                values.append(value)
    return values


def ontology_values(table, value_column):
    columns = table.get("columns", [])
    if value_column not in columns:
        return []
    source_column, accession_column = linked_ontology_columns(columns, value_column)
    items = []
    for row in table_rows(table):
        item = ontology_item(
            row.get(value_column, ""),
            row.get(source_column, "") if source_column else "",
            row.get(accession_column, "") if accession_column else "",
        )
        if item["term"] and item not in items:
            items.append(item)
    return items


def organism_pairs(table):
    pairs = []
    for row in table_rows(table):
        pair = {
            "organism": row_ontology_item(table, row, "Characteristics[Organism]"),
            "organismPart": row_ontology_item(table, row, "Characteristics[Organism part]"),
            "variant": row_ontology_item(table, row, "Characteristics[Variant]"),
            "sampleType": row_ontology_item(table, row, "Characteristics[Sample type]"),
        }
        if (pair["organism"]["term"] or pair["organismPart"]["term"]) and pair not in pairs:
            pairs.append(pair)
    return pairs


def row_ontology_item(table, row, value_column):
    columns = table.get("columns", [])
    source_column, accession_column = linked_ontology_columns(columns, value_column)
    return ontology_item(
        row.get(value_column, ""),
        row.get(source_column, "") if source_column else "",
        row.get(accession_column, "") if accession_column else "",
    )


def ontology_item(term="", term_source_ref="", term_accession_number=""):
    return {
        "term": term,
        "termSourceRef": term_source_ref,
        "termAccessionNumber": term_accession_number,
    }


def linked_ontology_columns(columns, value_column):
    try:
        start_index = columns.index(value_column) + 1
    except ValueError:
        return "", ""
    source_column = ""
    accession_column = ""
    for column in columns[start_index : start_index + 3]:
        if column.startswith("Term Source REF") and not source_column:
            source_column = column
        elif column.startswith("Term Accession Number") and not accession_column:
            accession_column = column
    return source_column, accession_column


def infer_assay_technique(path, table):
    text = " ".join([path.name, *table.get("columns", [])]).lower()
    if "nmr" in text or "free induction decay" in text:
        return {
            "name": "NMR",
            "mainTechnique": "NMR",
            "technique": "NMR",
            "subTechnique": "Nuclear magnetic resonance",
        }
    if "lc-ms" in text or "lcms" in text:
        return {
            "name": "LC-MS",
            "mainTechnique": "MS",
            "technique": "LC-MS",
            "subTechnique": "LC",
        }
    if "gcxgc-ms" in text:
        return {
            "name": "GCxGC-MS",
            "mainTechnique": "MS",
            "technique": "GC-MS",
            "subTechnique": "Tandem (GCxGC)",
        }
    if "gc-ms" in text or "gcms" in text:
        return {
            "name": "GC-MS",
            "mainTechnique": "MS",
            "technique": "GC-MS",
            "subTechnique": "GC",
        }
    return {
        "name": "MS",
        "mainTechnique": "MS",
        "technique": "Direct Injection",
        "subTechnique": "MS",
    }


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


def run_wasm_validation(
    validation_input_path,
    validation_wasm_path=None,
    validation_wasm_url=None,
    timeout=LOCAL_VALIDATION_TIMEOUT_SECONDS,
    wasmtime_executable_path="wasmtime",
):
    validation_wasm_path = ensure_validation_wasm(validation_wasm_path, validation_wasm_url)
    wasmtime_path = shutil.which(wasmtime_executable_path)
    if not wasmtime_path:
        raise SubmissionAPIError(
            "WASM validation requires the wasmtime executable. "
            "Install wasmtime or run validation without --mtbls-validation-wasm-path/--mtbls-validation-wasm-url "
            "to use the default OPA bundle."
        )

    command = [
        wasmtime_path,
        str(validation_wasm_path),
        str(Path(validation_input_path).expanduser().resolve()),
    ]
    try:
        task = subprocess.run(command, capture_output=True, text=True, check=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise SubmissionAPIError("The WASM validation process timed out.") from exc
    except subprocess.CalledProcessError as exc:
        message = exc.stderr or exc.stdout or str(exc)
        raise SubmissionAPIError(f"The WASM validation process failed: {message}") from exc

    return parse_wasm_validation_output(task.stdout)


def ensure_validation_wasm(validation_wasm_path=None, validation_wasm_url=None):
    if validation_wasm_path:
        validation_wasm_path = Path(validation_wasm_path).expanduser().resolve()
        if validation_wasm_path.exists():
            return validation_wasm_path
        if not validation_wasm_url:
            raise SubmissionAPIError(f"Validation WASM does not exist on {validation_wasm_path}")
    elif validation_wasm_url:
        validation_wasm_path = DEFAULT_LOCAL_SUBMISSION_CACHE_PATH / "validation.wasm"
    else:
        raise SubmissionAPIError("Validation WASM path or URL is required for WASM validation.")

    response = requests.get(validation_wasm_url, timeout=60)
    response.raise_for_status()
    validation_wasm_path.parent.mkdir(parents=True, exist_ok=True)
    validation_wasm_path.write_bytes(response.content)
    return validation_wasm_path


def parse_wasm_validation_output(output):
    try:
        result = json.loads(output)
    except json.JSONDecodeError as exc:
        raise SubmissionAPIError("WASM validation output is not valid JSON.") from exc
    return result.get("validationResult", result)


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
