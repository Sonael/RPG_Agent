"""
test_open5e_cache.py
Comportamento da camada de acesso ao SRD.

O QUE ESTES TESTES PROTEGEM
───────────────────────────
Antes, cada consulta ao SRD era um requests.get solto: sem sessão, sem retry e
sem cache. Um turno de combate podia disparar dezenas de round-trips seriais
dentro do tempo de resposta do chat, e "bite" (que não é arma do SRD) repetia
o mesmo 404 de 4 segundos a cada ataque. Estes testes trancam as três regras
que resolvem isso: acerto é cacheado, 404 também é, e erro de REDE não é.
"""

import pytest

from app import open5e


URL = "https://api.open5e.com/v1/monsters/goblin/"


class FakeResposta:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._payload = payload if payload is not None else {"name": "Goblin"}

    def json(self):
        return self._payload


@pytest.fixture
def rede(monkeypatch):
    """
    Liga a 'rede' (o conftest deixa tudo offline por padrão) e conta quantas
    vezes a sessão HTTP foi realmente usada.
    """
    open5e.set_offline(False)
    open5e.clear_cache()
    open5e.reset_stats()

    estado = {"chamadas": 0, "resposta": FakeResposta(), "erro": None}

    def fake_get(url, params=None, timeout=None):
        estado["chamadas"] += 1
        if estado["erro"] is not None:
            raise estado["erro"]
        return estado["resposta"]

    monkeypatch.setattr(open5e._session, "get", fake_get)
    yield estado
    open5e.set_offline(True)


def test_segunda_consulta_igual_nao_toca_a_rede(rede):
    primeira = open5e.get(URL)
    segunda  = open5e.get(URL)

    assert primeira.ok and segunda.ok
    assert segunda.json() == {"name": "Goblin"}
    assert rede["chamadas"] == 1, "a segunda consulta foi à rede de novo"
    assert segunda.from_cache is True


def test_params_diferentes_sao_entradas_diferentes(rede):
    open5e.get(URL, params={"limit": 5})
    open5e.get(URL, params={"limit": 9})
    assert rede["chamadas"] == 2


def test_ordem_dos_params_nao_cria_entrada_duplicada(rede):
    open5e.get(URL, params={"search": "goblin", "limit": 5})
    open5e.get(URL, params={"limit": 5, "search": "goblin"})
    assert rede["chamadas"] == 1


def test_404_e_cacheado(rede):
    """
    'bite' não é arma do SRD e nunca será. Sem cache negativo, todo ataque de
    monstro repetiria o mesmo 404 — que é justamente o caminho quente.
    """
    rede["resposta"] = FakeResposta(status=404, payload={})

    primeira = open5e.get("https://api.open5e.com/v1/weapons/bite/")
    segunda  = open5e.get("https://api.open5e.com/v1/weapons/bite/")

    assert not primeira.ok and not segunda.ok
    assert rede["chamadas"] == 1


def test_erro_de_rede_nao_e_cacheado(rede):
    """
    Um timeout é transitório: cachear a falha deixaria o jogo degradado por
    uma hora por causa de um soluço da API.
    """
    rede["erro"] = ConnectionError("timeout")

    primeira = open5e.get(URL)
    assert not primeira.ok

    rede["erro"] = None
    segunda = open5e.get(URL)

    assert segunda.ok, "a consulta deveria ter sido tentada de novo"
    assert rede["chamadas"] == 2


def test_resposta_ok_com_corpo_invalido_nao_vira_sucesso(rede):
    rede["resposta"] = FakeResposta(status=200, payload=["lista", "inesperada"])
    r = open5e.get(URL)
    assert not r.ok
    assert r.json() == {}


def test_modo_offline_nao_toca_a_rede(rede):
    with open5e.offline():
        r = open5e.get(URL)
    assert not r.ok
    assert rede["chamadas"] == 0


def test_get_nunca_levanta_excecao(rede):
    """
    O motor tem caminhos de fallback para "não achei" — mas não para uma
    exceção subindo do meio de um attack_roll.
    """
    rede["erro"] = RuntimeError("catástrofe na camada de socket")
    r = open5e.get(URL)
    assert r.ok is False


def test_stats_contam_acerto_e_ida_a_rede(rede):
    open5e.get(URL)
    open5e.get(URL)
    s = open5e.stats()
    assert s["misses"] == 1
    assert s["hits"] == 1
    assert s["hit_rate"] == pytest.approx(0.5)


def test_shim_http_tem_a_mesma_cara_de_requests(rede):
    """Os call sites do motor trocaram `requests` por este shim sem mais nada."""
    r = open5e.http.get(URL, params={"search": "goblin"}, timeout=4)
    assert r.ok
    assert r.json()["name"] == "Goblin"
