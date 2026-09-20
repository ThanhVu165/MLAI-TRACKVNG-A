from verify.harness import VerifyResult, confusion_matrix, error_rates


def _result(expected: str, actual: str) -> VerifyResult:
    return VerifyResult(
        "c",
        "T",
        "input",
        expected,
        actual,
        "P",
        "reason",
        expected == actual,
        1,
        "ts",
        "cv",
        "",
        "",
    )


def test_confusion_matrix_and_error_rates_match_manual_count() -> None:
    results = [
        _result("AUTO_REPLY", "AUTO_REPLY"),
        _result("AUTO_REPLY", "OUT_OF_POLICY"),
        _result("FACT_UNRESOLVED", "AUTO_REPLY"),
        _result("AUTHORITY_REQUIRED", "AUTHORITY_REQUIRED"),
    ]

    matrix = confusion_matrix(results)
    assert matrix["AUTO_REPLY"]["OUT_OF_POLICY"] == 1
    assert matrix["FACT_UNRESOLVED"]["AUTO_REPLY"] == 1
    assert error_rates(results) == (0.5, 0.5)
