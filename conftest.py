"""
conftest.py
Configuração compartilhada do pytest.

DUAS RESPONSABILIDADES
──────────────────────
1. Isolar a suíte de rede e de banco. `tools_dnd` importa `memory`, que fala
   com o Supabase; e o motor consulta o SRD em api.open5e.com. Nenhum teste
   deve depender de nenhum dos dois: aqui o `database` vira um stub e a
   camada SRD entra em modo offline.

2. Expor os dois scripts de teste legados (tests.py e tests_combat_fuzz.py)
   ao pytest. Eles não eram coletados por ninguém — e o tests.py chegou a
   acumular 5 checks falhando enquanto saía com código 0. Em vez de reescrever
   ~50 mil caracteres de asserts, rodamos cada script uma vez por sessão e
   transformamos CADA check num caso de teste do pytest, com nome próprio.
"""

import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Isolamento: sem Supabase, sem rede
# ---------------------------------------------------------------------------

def _stub_database() -> None:
    """`memory` importa `database` (Supabase). Nos testes, ele não existe."""
    if "database" in sys.modules:
        return
    db = types.ModuleType("database")
    db.get_campaign    = lambda *a, **k: None
    db.save_campaign   = lambda *a, **k: None
    db.list_campaigns  = lambda *a, **k: []
    db.delete_campaign = lambda *a, **k: None
    db.rename_campaign = lambda *a, **k: None
    db.campaign_exists = lambda *a, **k: False
    sys.modules["database"] = db


_stub_database()

# Modo offline por padrão: nenhum teste sai para a rede sem pedir.
os.environ.setdefault("RPG_SRD_OFFLINE", "1")
os.environ.setdefault("RPG_SRD_CACHE_DISABLED", "1")


@pytest.fixture(autouse=True)
def _srd_offline():
    """Garante offline mesmo se um teste anterior tiver ligado a rede."""
    import open5e
    open5e.set_offline(True)
    open5e.clear_cache()
    open5e.reset_stats()
    yield


# ---------------------------------------------------------------------------
# Ponte para as suítes legadas
# ---------------------------------------------------------------------------

_legacy_cache: list[dict] | None = None


def _run_legacy_suite() -> list[dict]:
    """
    Roda tests.py uma vez (em subprocesso, para não contaminar o pytest com o
    módulo `memory` falso que ele instala) e devolve a lista de checks.
    """
    global _legacy_cache
    if _legacy_cache is not None:
        return _legacy_cache

    saida = ROOT / ".pytest_cache" / "legacy_results.json"
    saida.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}

    try:
        proc = subprocess.run(
            [sys.executable, "tests.py", f"--json={saida}"],
            cwd=ROOT, capture_output=True, text=True, timeout=600, env=env,
        )
    except Exception as exc:                                   # pragma: no cover
        _legacy_cache = [{
            "section": "harness", "label": f"tests.py não executou: {exc}",
            "passed": False, "got": "", "expected": "",
        }]
        return _legacy_cache

    try:
        _legacy_cache = json.loads(saida.read_text(encoding="utf-8"))
    except Exception:
        cauda = (proc.stdout or "")[-2000:] + (proc.stderr or "")[-2000:]
        _legacy_cache = [{
            "section": "harness",
            "label": f"tests.py não produziu resultados (exit {proc.returncode})",
            "passed": False, "got": cauda, "expected": "JSON de resultados",
        }]
    return _legacy_cache


def _id_do_check(c: dict) -> str:
    """Id legível e estável para o caso de teste."""
    secao = (c.get("section") or "geral").split("—")[0].strip().replace(" ", "_")
    rotulo = (c.get("label") or "check")[:70].replace(" ", "_")
    return f"{secao}::{rotulo}"


def pytest_generate_tests(metafunc):
    if "legacy_check" in metafunc.fixturenames:
        checks = _run_legacy_suite()
        metafunc.parametrize(
            "legacy_check", checks, ids=[_id_do_check(c) for c in checks],
        )


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: teste demorado (fuzzer); pule com -m 'not slow'",
    )
