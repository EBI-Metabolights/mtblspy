import json

import pytest

from mtblspy.commands.submissions.exceptions import SubmissionAPIError
from mtblspy.commands.submissions.local_validation import (
    get_text_overrides,
    load_local_validation_input,
    parse_opa_validation_output,
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
                "INVESTIGATION",
                'Investigation Identifier\t"MTBLS123"',
                'Investigation Title\t"Investigation"',
                "STUDY",
                'Study Identifier\t"MTBLS123"',
                'Study Title\t"Test study"',
                'Study File Name\t"s_MTBLS123.txt"',
                "STUDY ASSAYS",
                'Study Assay File Name\t"a_MTBLS123.txt"',
                'Study Assay Measurement Type\t"metabolite profiling"',
                'Study Assay Technology Type\t"mass spectrometry"',
                'Study Assay Technology Platform\t"LC-MS"',
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "s_MTBLS123.txt").write_text(
        "Source Name\tSample Name\nsource-1\tsample-1\n",
        encoding="utf-8",
    )
    (tmp_path / "a_MTBLS123.txt").write_text(
        "Sample Name\tRaw Spectral Data File\tDerived Spectral Data File\tMetabolite Assignment File\n"
        "sample-1\tFILES/raw.raw\tFILES/derived.mzML\tm_MTBLS123.tsv\n",
        encoding="utf-8",
    )
    (tmp_path / "m_MTBLS123.tsv").write_text(
        "database_identifier\tchemical_formula\nCHEBI:123\tC1H2\n",
        encoding="utf-8",
    )

    validation_input = load_local_validation_input("MTBLS123", tmp_path, "FILES")

    assert validation_input["investigation"]["studies"][0]["title"] == "Test study"
    assert validation_input["samples"]["s_MTBLS123.txt"]["sampleNames"] == ["sample-1"]
    assert validation_input["assays"]["a_MTBLS123.txt"]["referencedRawFiles"] == ["FILES/raw.raw"]
    assert validation_input["referencedAssignmentFiles"] == ["m_MTBLS123.tsv"]
    assert validation_input["hasInvestigationData"] is True
