import gzip
import io
import json
import tarfile
from types import SimpleNamespace

import pytest

from mtblspy.commands.submissions.exceptions import SubmissionAPIError
from mtblspy.commands.submissions.local_validation import (
    get_text_overrides,
    load_local_validation_input,
    normalize_validation_wasm_file,
    prepare_validation_wasm_artifact,
    parse_opa_validation_output,
    run_wasm_validation,
    split_validation_errors,
)


def test_parse_opa_validation_output_extracts_complete_report():
    output = json.dumps(
        {
            "result": [
                {
                    "expressions": [
                        {
                            "value": {
                                "violations": [
                                    {
                                        "type": "ERROR",
                                        "identifier": "rule_i_100_001",
                                        "title": "Study title is required",
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
    )

    result = parse_opa_validation_output(output)

    assert result["violations"][0]["identifier"] == "rule_i_100_001"


def test_parse_opa_validation_output_rejects_unexpected_shape():
    with pytest.raises(SubmissionAPIError, match="did not include a validation result"):
        parse_opa_validation_output('{"result": []}')


def test_split_validation_errors_filters_non_errors_and_overrides():
    validation_result = {
        "violations": [
            {"type": "ERROR", "identifier": "rule-error", "title": "Error"},
            {"type": "ERROR", "identifier": "rule-overridden", "title": "Overridden"},
            {"type": "WARNING", "identifier": "rule-warning", "title": "Warning"},
        ]
    }

    errors, overrides = split_validation_errors(validation_result, {"rule-overridden"})

    assert errors == [{"type": "ERROR", "identifier": "rule-error", "title": "Error"}]
    assert overrides == [
        {
            "type": "WARNING",
            "identifier": "rule-overridden",
            "title": "Overridden",
            "overridden": True,
            "overrideComment": "rule id is in the exclude list",
        }
    ]


def test_text_overrides_include_rule_ids_and_metadata_files(tmp_path):
    overrides_file = tmp_path / "overrides.txt"
    overrides_file.write_text("rule_i_100_001\na_MTBLS123.txt\nnotes.txt\n", encoding="utf-8")

    rule_ids, files = get_text_overrides(overrides_file)

    assert rule_ids == {"rule_i_100_001"}
    assert files == {"a_MTBLS123.txt"}


def test_normalize_validation_wasm_file_decompresses_gzip_cache(tmp_path):
    wasm_path = tmp_path / "validation.wasm"
    wasm_bytes = b"\x00asm\x01\x00\x00\x00"
    wasm_path.write_bytes(gzip.compress(wasm_bytes))

    normalized_path = normalize_validation_wasm_file(wasm_path)

    assert normalized_path == wasm_path.resolve()
    assert wasm_path.read_bytes() == wasm_bytes


def test_prepare_validation_wasm_artifact_gzips_plain_opa_wasm_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "mtblspy.commands.submissions.local_validation.DEFAULT_LOCAL_SUBMISSION_CACHE_PATH",
        tmp_path / "cache",
    )
    bundle_path = tmp_path / "mtbls-validation.wasm"
    with tarfile.open(bundle_path, "w") as archive:
        for name, content in {
            "/policy.wasm": b"\x00asm\x01\x00\x00\x00",
            "/.manifest": b'{"wasm":[]}',
        }.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))

    artifact = prepare_validation_wasm_artifact(bundle_path)

    assert artifact.artifact_type == "opa_wasm_bundle"
    assert artifact.path != bundle_path.resolve()
    assert artifact.path.suffixes[-2:] == [".tar", ".gz"]
    assert artifact.path.read_bytes().startswith(b"\x1f\x8b")


def test_run_wasm_validation_uses_opa_for_gzipped_opa_wasm_bundle(tmp_path, monkeypatch):
    input_path = tmp_path / "input.json"
    input_path.write_text("{}", encoding="utf-8")
    bundle_path = tmp_path / "mtbls-validation.wasm"
    with tarfile.open(bundle_path, "w:gz") as archive:
        for name, content in {
            "/policy.wasm": b"\x00asm\x01\x00\x00\x00",
            "/.manifest": b'{"wasm":[]}',
        }.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))

    popen_calls = []
    post_calls = []

    class FakeProcess:
        stdout = None
        stderr = None

        def poll(self):
            return None

        def terminate(self):
            return None

        def communicate(self, timeout=None):
            return "", ""

        def kill(self):
            return None

    class FakeResponse:
        def __init__(self, payload=None):
            self.payload = payload or {}

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_popen(command, **kwargs):
        popen_calls.append(command)
        return FakeProcess()

    def fake_post(url, **kwargs):
        post_calls.append((url, kwargs))
        return FakeResponse({"result": {"violations": []}})

    monkeypatch.setattr("mtblspy.commands.submissions.local_validation.get_free_local_port", lambda: 8182)
    monkeypatch.setattr("mtblspy.commands.submissions.local_validation.subprocess.Popen", fake_popen)
    monkeypatch.setattr(
        "mtblspy.commands.submissions.local_validation.requests",
        SimpleNamespace(
            RequestException=Exception,
            get=lambda *args, **kwargs: FakeResponse(),
            post=fake_post,
        ),
    )

    result = run_wasm_validation(input_path, validation_wasm_path=bundle_path, opa_executable_path="opa-with-wasm")

    assert result == {"violations": []}
    assert popen_calls[0][:5] == ["opa-with-wasm", "run", "--server", "--addr", "127.0.0.1:8182"]
    assert post_calls[0][0] == "http://127.0.0.1:8182/v1/data/metabolights/validation/v2/report/complete_report"
    assert post_calls[0][1]["json"] == {"input": {}}


def test_split_validation_errors_filters_file_overrides():
    validation_result = {
        "violations": [
            {"type": "ERROR", "identifier": "rule-error", "sourceFile": "a_MTBLS123.txt"},
            {"type": "ERROR", "identifier": "rule-other", "sourceFile": "i_Investigation.txt"},
        ]
    }

    errors, overrides = split_validation_errors(validation_result, overridden_files={"a_MTBLS123.txt"})

    assert errors == [{"type": "ERROR", "identifier": "rule-other", "sourceFile": "i_Investigation.txt"}]
    assert overrides == [
        {
            "type": "WARNING",
            "identifier": "rule-error",
            "sourceFile": "a_MTBLS123.txt",
            "overridden": True,
            "overrideComment": "file name is in the exclude list",
        }
    ]


def test_load_local_validation_input_parses_isatab_without_metabolights_utils(tmp_path):
    (tmp_path / "i_Investigation.txt").write_text(
        "\n".join(
            [
                "INVESTIGATION\t\t",
                'Investigation Identifier\t"MTBLS123"',
                'Investigation Title\t"Investigation"',
                "STUDY\t\t",
                'Study Identifier\t"MTBLS123"',
                'Study Title\t"Test study"',
                'Study File Name\t"s_MTBLS123.txt"',
                'Comment[Template Version]\t"1.0"',
                'Comment[Sample Template]\t"minimum"',
                'Comment[Study Template]\t"minimum"',
                'Comment[Created At]\t"2026-01-01T00:00:00"',
                "STUDY DESIGN DESCRIPTORS\t\t",
                'Study Design Type\t"metabolomics"\t"LC-MS"\t"Homo sapiens"',
                'Study Design Type Term Accession Number\t"MTBLS:1"\t"MTBLS:2"\t"NCBITaxon:9606"',
                'Study Design Type Term Source REF\t"MTBLS"\t"MTBLS"\t"NCBITaxon"',
                'Comment[Study Design Category]\t""\t"Instrument"\t"Organism"',
                'Comment[Study Design Source]\t"submitter"\t"status-update-workflow"\t"status-update-workflow"',
                "STUDY PUBLICATIONS\t\t",
                "Study PubMed ID\t\t",
                'Study Publication Title\t"Example publication"\t',
                "STUDY ASSAYS\t\t",
                'Study Assay File Name\t"a_MTBLS123.txt"',
                'Study Assay Measurement Type\t"metabolite profiling"',
                'Study Assay Technology Type\t"mass spectrometry"',
                'Study Assay Technology Platform\t"LC-MS"',
                "STUDY CONTACTS\t\t",
                'Study Person Last Name\t"Li"',
                'Study Person First Name\t"Ma"',
                'Study Person Email\t"ma@example.org"',
                'Study Person Roles\t"Principal Investigator"',
                'Study Person Roles Term Accession Number\t"NCIT:C19924"',
                'Study Person Roles Term Source REF\t"NCIT"',
                'Comment[Study Person Affiliation ROR ID]\t"https://ror.org/12345"',
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "s_MTBLS123.txt").write_text(
        "Source Name\tSample Name\nsource-1\tsample-1\n",
        encoding="utf-8",
    )
    (tmp_path / "a_MTBLS123.txt").write_text(
        "Sample Name\tParameter Value[Instrument]\tTerm Source REF\tTerm Accession Number\t"
        "Raw Spectral Data File\tDerived Spectral Data File\tMetabolite Assignment File\n"
        "sample-1\tQ Exactive\tMS\tMS:1001911\tFILES/raw.raw\tFILES/derived.mzML\tm_MTBLS123.tsv\n",
        encoding="utf-8",
    )
    (tmp_path / "m_MTBLS123.tsv").write_text(
        "database_identifier\tchemical_formula\nCHEBI:123\tC1H2\n",
        encoding="utf-8",
    )

    validation_input = load_local_validation_input("MTBLS123", tmp_path, "FILES")

    assert validation_input["investigation"]["studies"][0]["title"] == "Test study"
    assert validation_input["investigation"]["studies"][0]["fileName"] == "s_MTBLS123.txt"
    assert validation_input["investigation"]["studies"][0]["sampleTemplate"] == "minimum"
    assert len(validation_input["investigation"]["studies"][0]["studyDesignDescriptors"]["designTypes"]) == 3
    assert (
        validation_input["investigation"]["studies"][0]["studyPublications"]["publications"][0]["title"]
        == "Example publication"
    )
    assert (
        validation_input["investigation"]["studies"][0]["studyContacts"]["people"][0]["affiliationRorId"]
        == "https://ror.org/12345"
    )
    assert validation_input["investigation"]["studies"][0]["studyAssays"]["assays"][0]["fileName"] == "a_MTBLS123.txt"
    assert validation_input["samples"]["s_MTBLS123.txt"]["sampleNames"] == ["sample-1"]
    assert validation_input["assays"]["a_MTBLS123.txt"]["referencedRawFiles"] == ["FILES/raw.raw"]
    assert validation_input["assays"]["a_MTBLS123.txt"]["assayTechnique"]["mainTechnique"] == "MS"
    assert validation_input["referencedAssignmentFiles"] == ["m_MTBLS123.tsv"]
    assert validation_input["parserMessages"] == {
        "i_Investigation.txt": [],
        "s_MTBLS123.txt": [],
        "a_MTBLS123.txt": [],
        "m_MTBLS123.tsv": [],
    }
    assert validation_input["samples"]["s_MTBLS123.txt"]["table"]["columns"] == ["Source Name", "Sample Name"]
    assert validation_input["samples"]["s_MTBLS123.txt"]["table"]["data"] == {
        "Source Name": ["source-1"],
        "Sample Name": ["sample-1"],
    }
    sample_headers = validation_input["samples"]["s_MTBLS123.txt"]["table"]["headers"]
    assert sample_headers[0]["columnCategory"] == "Basic"
    assert sample_headers[1]["columnCategory"] == "Basic"
    assert validation_input["assays"]["a_MTBLS123.txt"]["table"]["headers"][1]["columnPrefix"] == "Parameter Value"
    assay_headers = validation_input["assays"]["a_MTBLS123.txt"]["table"]["headers"]
    assert assay_headers[1]["columnStructure"] == "ONTOLOGY_COLUMN"
    assert assay_headers[1]["additionalColumns"] == ["Term Source REF", "Term Accession Number"]
    assert assay_headers[2]["columnStructure"] == "LINKED_COLUMN"
    assert "numberOfSampleRows" not in validation_input["samples"]["s_MTBLS123.txt"]
    assert validation_input["metaboliteAssignments"]["m_MTBLS123.tsv"]["identifiedMetaboliteNames"] == []
    assert validation_input["metaboliteAssignments"]["m_MTBLS123.tsv"]["numberOfRows"] == 1
    assert validation_input["metaboliteAssignments"]["m_MTBLS123.tsv"]["numberOfAssignedRows"] == 0
    assert "FILES/raw.raw" not in validation_input["studyFolderMetadata"]["files"]
    assert validation_input["hasInvestigationData"] is True
