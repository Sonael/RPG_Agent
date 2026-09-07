"""
test_legacy_dnd.py
Portão do pytest sobre a suíte legada (tests.py).

Cada check do script vira UM caso de teste aqui, com nome próprio — então uma
regressão aponta o check exato que quebrou, em vez de "o script falhou".
A lista vem de conftest.pytest_generate_tests, que roda tests.py uma única vez
por sessão em subprocesso.
"""


def test_legacy_check(legacy_check):
    if legacy_check["passed"]:
        return
    raise AssertionError(
        f"[{legacy_check['section']}] {legacy_check['label']}\n"
        f"  obtido:   {legacy_check['got']}\n"
        f"  esperado: {legacy_check['expected']}"
    )
