from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def to_camel(value):
    first, *remaining = value.split("_")
    return first + "".join(word.capitalize() for word in remaining)


class CamelCaseModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class StudyInputFormat(str, Enum):
    JSON = "json"


class StudyCreationRequest(CamelCaseModel):
    selected_template_version: str | None = None
    selected_study_categories: dict[str, list[str]] = Field(default_factory=lambda: {"ms-mhd-legacy": []})
    selected_investigation_file_template: str | None = None
    selected_sample_file_template: str | None = None
    dataset_license_agreement: bool = False
    dataset_policy_agreement: bool = False
    privacy_policy_agreement: bool = True
    publications: list[dict[str, Any]] = Field(default_factory=list)
    title: str = ""
    description: str = ""
    related_datasets: list[dict[str, Any]] = Field(default_factory=list)
    funding: list[dict[str, Any]] = Field(default_factory=list)
    contacts: list[dict[str, Any]] = Field(default_factory=list)
    design_descriptors: list[dict[str, Any]] = Field(default_factory=list)
    factors: list[dict[str, Any]] = Field(default_factory=list)
    assays: list[dict[str, Any]] = Field(default_factory=list)
    selected_submission_workflows: list[str] = Field(default_factory=list)


class FtpUploadDetails(CamelCaseModel):
    study_id: str = ""
    ftp_folder: str = ""
    ftp_host: str = ""
    ftp_user: str = ""
    ftp_password: str = ""


def default_term_source(name=""):
    return {
        "comments": [],
        "name": name,
        "file": "",
        "version": "",
        "description": "",
    }


def default_ontology_term(annotation_value, term_accession="", term_source_name=""):
    return {
        "comments": [],
        "termAccession": term_accession,
        "annotationValue": annotation_value,
        "termSource": default_term_source(term_source_name),
    }


def get_default_study_creation_request():
    return StudyCreationRequest(
        selected_template_version="1.0",
        selected_study_categories={"ms-mhd-legacy": ["MS"]},
        selected_investigation_file_template="minimum",
        selected_sample_file_template="minimum",
        dataset_license_agreement=True,
        dataset_policy_agreement=True,
        privacy_policy_agreement=True,
        title="A new study submission",
        description="A new study submission",
        publications=[
            {
                "title": "Example publication title",
                "authorList": "Doe J, Smith A",
                "doi": "",
                "pubmedId": "",
                "status": default_ontology_term(
                    "in preparation",
                    "http://www.ebi.ac.uk/efo/EFO_0001795",
                    "EFO",
                ),
            }
        ],
        related_datasets=[
            {
                "repository": "MetaboLights",
                "accession": "MTBLS1",
                "url": "https://www.ebi.ac.uk/metabolights/MTBLS1",
                "description": "Example related MetaboLights study.",
            }
        ],
        funding=[
            {
                "fundingOrganization": default_ontology_term(
                    "Example funding organization",
                    "",
                    "",
                ),
                "grantIdentifier": "EXAMPLE-GRANT-001",
            }
        ],
        contacts=[
            {
                "comments": [],
                "firstName": "Jane",
                "lastName": "Doe",
                "email": "jane.doe@example.org",
                "affiliation": "Example Institute",
                "address": "",
                "fax": "",
                "midInitials": "",
                "phone": "",
                "roles": [
                    default_ontology_term(
                        "Principal Investigator",
                        "http://purl.obolibrary.org/obo/NCIT_C19924",
                        "NCIT",
                    )
                ],
            }
        ],
        design_descriptors=[
            default_ontology_term(
                "metabolite profiling",
                "http://purl.obolibrary.org/obo/OBI_0000366",
                "OBI",
            )
        ],
        factors=[],
        assays=[],
        selected_submission_workflows=[],
    )
