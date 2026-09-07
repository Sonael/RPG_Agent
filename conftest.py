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
# Fábrica de personagens para os testes do motor
# ---------------------------------------------------------------------------

def criar_ficha(nome, *, grupo=False, vida=30, vida_max=None, ca=12, nivel=3,
                forca=16, destreza=12, constituicao=14, inteligencia=10,
                sabedoria=10, carisma=10, mana=20, arma="espada longa",
                habilidades=None, **extras):
    """
    Personagem completo, com todos os campos que o motor espera.
    `extras` cai direto na ficha — é por onde os testes injetam resistências,
    imunidades, PV temporários, concentração, ataques de monstro, etc.
    """
    sheet = {
        "classe": "guerreiro" if grupo else "npc", "raca": "humano",
        "nivel": nivel, "xp": 0, "xp_proximo": 900,
        "forca": forca, "destreza": destreza, "constituicao": constituicao,
        "inteligencia": inteligencia, "sabedoria": sabedoria, "carisma": carisma,
        "vida_atual": vida, "vida_max": vida_max if vida_max is not None else vida,
        "mana_atual": mana, "mana_max": mana, "ca": ca,
        "proficiencia": 2, "hit_die": 10, "ouro": 0, "prata": 0, "cobre": 0,
        "equipamentos": {"armadura": None, "escudo": None,
                         "arma_principal": arma, "amuleto": None},
        "condicoes": [], "death_saves_sucessos": 0, "death_saves_falhas": 0,
        "vida_temp": 0, "concentracao": None,
        "resistencias": [], "imunidades": [], "vulnerabilidades": [],
    }
    sheet.update(extras)
    return {
        "name": nome, "status": "vivo" if grupo else "inimigo",
        "party_member": grupo, "description": "", "traits": "", "notes": "",
        "habilidades": habilidades or [], "inventario": [], "sheet": sheet,
    }


@pytest.fixture
def campanha():
    """Campanha zerada, com combat_state íntegro. Devolve o dict da campanha."""
    import memory
    memory.campaign["characters"] = {}
    memory.campaign["party"] = []
    memory.campaign["protagonist"] = ""
    memory.campaign["combat_state"] = {
        "is_active": False, "initiative_order": [], "current_turn_index": 0,
        "round": 1, "turn_resolved": False, "npc_strategies": {},
        "turn_auto_advanced": False, "turn_token": 0, "log": [], "result": None,
        "turn_economy": {"acao_usada": False, "bonus_usada": False},
    }
    return memory.campaign


@pytest.fixture
def povoar(campanha):
    """Insere personagens na campanha e devolve o dict deles por nome."""
    import memory

    def _povoar(*chars):
        criados = {}
        for ch in chars:
            memory.campaign["characters"][memory.char_key(ch["name"])] = ch
            if ch.get("party_member"):
                memory.campaign["party"].append(
                    {"name": ch["name"], "role": "", "notes": ""})
            criados[ch["name"]] = ch
        return criados

    return _povoar


def iniciar_combate(ordem, indice=0, rodada=1):
    """Liga o combate com a ordem de iniciativa dada."""
    import memory
    cs = memory.campaign["combat_state"]
    cs.update({"is_active": True, "initiative_order": list(ordem),
               "current_turn_index": indice, "round": rodada,
               "turn_resolved": False, "turn_auto_advanced": False})
    return cs


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
