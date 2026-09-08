"""
test_js_auth.py
Ponte do pytest sobre tests/js/authfetch_refresh.mjs.

O authFetch é a única porta de todas as chamadas autenticadas do jogo, e o bug
que ele guarda só aparece sob CONCORRÊNCIA — teste manual quase nunca reproduz,
porque depende de duas chamadas levarem 401 na mesma janela de milissegundos.
Daí valer um teste automático.

Cada check do script vira um caso aqui, no mesmo formato de test_legacy_dnd.py.
Precisa de `node` no PATH; sem ele os casos são pulados, não falham — o node
não é dependência do servidor, só desta verificação.
"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
SCRIPT = RAIZ / "tests" / "js" / "authfetch_refresh.mjs"
NODE = shutil.which("node")


def _rodar():
    with tempfile.TemporaryDirectory() as tmp:
        saida = Path(tmp) / "res.json"
        proc = subprocess.run(
            [NODE, str(SCRIPT), f"--json={saida}"],
            cwd=RAIZ, capture_output=True, text=True, timeout=120,
        )
        if not saida.exists():
            raise RuntimeError(
                f"o script não gerou resultados (saída {proc.returncode})\n"
                f"{proc.stdout}\n{proc.stderr}"
            )
        return json.loads(saida.read_text(encoding="utf-8"))


def pytest_generate_tests(metafunc):
    if "check_js" not in metafunc.fixturenames:
        return
    if NODE is None or not SCRIPT.exists():
        metafunc.parametrize("check_js", [None], ids=["node-ausente"])
        return
    checks = _rodar()
    metafunc.parametrize(
        "check_js", checks,
        ids=[c["label"].replace(" ", "-") for c in checks],
    )


def test_authfetch(check_js):
    if check_js is None:
        pytest.skip("`node` não está no PATH — verificação de JS pulada")
    if check_js["passed"]:
        return
    raise AssertionError(
        f"{check_js['label']}\n"
        f"  obtido:   {check_js['got']}\n"
        f"  esperado: {check_js['expected']}"
    )
