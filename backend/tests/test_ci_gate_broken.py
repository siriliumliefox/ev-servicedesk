def test_ci_gate_must_fail():
    assert 1 == 2, "намеренно сломанный тест (проверка ci-gate, #24)"
