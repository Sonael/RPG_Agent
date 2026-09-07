"""
test_fuzz_invariants.py
Portão do pytest sobre o fuzzer de invariantes de turno (tests_combat_fuzz.py).

O fuzzer já sabia sair com código != 0; o que faltava era alguém rodá-lo. Aqui
ele entra na suíte com um N modesto, para o `pytest` continuar rápido. Antes de
publicar, rode o fuzzer cheio:

    python tests_combat_fuzz.py both 10000 1234
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent

# Combates por modo. Baixo o bastante para a suíte rodar em segundos e alto o
# bastante para exercitar ordem de turno, mortes no meio e ações fora de ordem.
N_COMBATES = 120
SEED = 1234


@pytest.mark.slow
@pytest.mark.parametrize("modo", ["engine", "screen"])
def test_invariantes_de_turno(modo):
    proc = subprocess.run(
        [sys.executable, "tests_combat_fuzz.py", modo, str(N_COMBATES), str(SEED)],
        cwd=ROOT, capture_output=True, text=True, timeout=900,
    )
    if proc.returncode != 0:
        saida = (proc.stdout or "")[-3000:] + (proc.stderr or "")[-2000:]
        raise AssertionError(
            f"fuzzer '{modo}' encontrou violações de invariante:\n{saida}"
        )
