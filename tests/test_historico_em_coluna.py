"""
test_historico_em_coluna.py

O histórico de conversa saiu de dentro do documento.

POR QUÊ, MEDIDO NA CAMPANHA REAL
    documento inteiro .......... 219 KB
    conversation_history ....... 180 KB  (82%)

Esses 82% viajavam em TODA gravação — e um turno grava. Pior ainda: a tela de
escolher campanha (`list_campaigns`) faz `select name, data` e baixava o
histórico inteiro de TODAS as campanhas só para desenhar uma lista.

Agora ele mora na coluna `historico`:

    alter table campaigns add column if not exists historico jsonb
      default '[]'::jsonb;

O PostgREST grava só as colunas que recebe, então a gravação de um turno
deixou de carregar a conversa.

DOIS MUNDOS AO MESMO TEMPO, de propósito: campanha gravada no formato antigo
continua abrindo, e ambiente onde o ALTER TABLE não rodou continua gravando
como antes — o módulo descobre isso sozinho na primeira tentativa.
"""
import importlib.util
from pathlib import Path

import pytest

# A conftest troca rpg.database por um dublê (nenhum teste fala com o Supabase
# de verdade). Aqui quem está sob exame é o módulo REAL, então ele é carregado
# do arquivo, com outro nome, e continua sem tocar em rede: o cliente
# Postgrest é substituído pelo de bancada abaixo.
_ARQUIVO = Path(__file__).resolve().parent.parent / "rpg" / "database.py"
_spec = importlib.util.spec_from_file_location("database_de_verdade", _ARQUIVO)
database = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(database)


class _Resposta:
    def __init__(self, data):
        self.data = data


class _Consulta:
    """O mínimo do PostgREST que o database.py usa."""

    def __init__(self, banco, acao, colunas="", payload=None, sem_coluna=(),
                 filtro_json_funciona=True):
        self.banco, self.acao, self.colunas = banco, acao, colunas
        self.payload, self.sem_coluna = payload, sem_coluna
        self.filtro_json_funciona = filtro_json_funciona
        self.filtros = {}

    def eq(self, campo, valor):
        self.filtros[campo] = valor
        return self

    def limit(self, _n):
        return self

    def order(self, *a, **k):
        return self

    def execute(self):
        pedidas = [c.strip() for c in self.colunas.split(",") if c.strip()]
        for coluna in self.sem_coluna:
            if coluna in pedidas or (self.payload or {}).get(coluna) is not None:
                raise RuntimeError(
                    f"column campaigns.{coluna} does not exist (PGRST204)")
        if self.acao == "select":
            linhas = [l for l in self.banco
                      if all(l.get(k) == v for k, v in self.filtros.items())]
            return _Resposta([{c: l.get(c) for c in pedidas} for l in linhas])
        if self.acao == "upsert":
            chave = (self.payload["user_id"], self.payload["name"])
            for linha in self.banco:
                if (linha["user_id"], linha["name"]) == chave:
                    linha.update(self.payload)
                    return _Resposta([linha])
            self.banco.append(dict(self.payload))
            return _Resposta([self.payload])
        if self.acao == "update":
            atingidas = []
            for linha in self.banco:
                if any(linha.get(k) != v for k, v in self.filtros.items()
                       if "->>" not in k):
                    continue
                # O filtro no caminho do JSON: "data->>_version" = "3".
                for campo, valor in self.filtros.items():
                    if "->>" not in campo:
                        continue
                    if not self.filtro_json_funciona:
                        break          # Postgrest que não entende o caminho
                    coluna, chave_json = campo.split("->>")
                    if str((linha.get(coluna) or {}).get(chave_json)) != str(valor):
                        break
                else:
                    linha.update(self.payload)
                    atingidas.append(linha)
            return _Resposta(atingidas)
        return _Resposta([])


class _Tabela:
    def __init__(self, banco, sem_coluna, filtro_json_funciona=True):
        self.banco, self.sem_coluna = banco, sem_coluna
        self.filtro_json_funciona = filtro_json_funciona

    def select(self, colunas):
        return _Consulta(self.banco, "select", colunas, sem_coluna=self.sem_coluna)

    def upsert(self, payload, on_conflict=None):
        return _Consulta(self.banco, "upsert", payload=payload,
                         sem_coluna=self.sem_coluna)

    def update(self, payload):
        return _Consulta(self.banco, "update", payload=payload,
                         sem_coluna=self.sem_coluna,
                         filtro_json_funciona=self.filtro_json_funciona)


class _Cliente:
    def __init__(self, banco, sem_coluna, filtro_json_funciona=True):
        self.banco, self.sem_coluna = banco, sem_coluna
        self.filtro_json_funciona = filtro_json_funciona

    def from_(self, _tabela):
        return _Tabela(self.banco, self.sem_coluna, self.filtro_json_funciona)


@pytest.fixture
def banco(monkeypatch):
    linhas: list[dict] = []
    monkeypatch.setattr(database, "_client", lambda: _Cliente(linhas, ()))
    monkeypatch.setattr(database, "_tem_coluna_historico", None)
    monkeypatch.setattr(database, "_versao_condicional", True)
    return linhas


@pytest.fixture
def banco_sem_filtro_json(monkeypatch):
    """Postgrest em que o filtro no caminho do JSON não pega nada."""
    linhas: list[dict] = []
    monkeypatch.setattr(database, "_client",
                        lambda: _Cliente(linhas, (), filtro_json_funciona=False))
    monkeypatch.setattr(database, "_tem_coluna_historico", None)
    monkeypatch.setattr(database, "_versao_condicional", True)
    return linhas


@pytest.fixture
def banco_antigo(monkeypatch):
    """Ambiente onde o ALTER TABLE não rodou."""
    linhas: list[dict] = []
    monkeypatch.setattr(database, "_client", lambda: _Cliente(linhas, ("historico",)))
    monkeypatch.setattr(database, "_tem_coluna_historico", None)
    return linhas


CONVERSA = [{"role": "user", "text": "olá"}, {"role": "assistant", "text": "a taverna"}]
CAMPANHA = {"name": "Teste", "chapter": 2, "characters": {"a": {"name": "A"}},
            "conversation_history": CONVERSA}


# ---------------------------------------------------------------------------
# Gravar
# ---------------------------------------------------------------------------

def test_a_conversa_sai_do_documento(banco):
    database.save_campaign("u1", "Teste", CAMPANHA)
    linha = banco[0]
    assert "conversation_history" not in linha["data"]
    assert linha["historico"] == CONVERSA


def test_o_resto_da_campanha_continua_no_data(banco):
    database.save_campaign("u1", "Teste", CAMPANHA)
    assert banco[0]["data"]["chapter"] == 2
    assert banco[0]["data"]["characters"] == {"a": {"name": "A"}}


def test_o_dict_de_quem_chamou_nao_e_mexido(banco):
    copia = dict(CAMPANHA)
    database.save_campaign("u1", "Teste", copia)
    assert copia["conversation_history"] == CONVERSA


def test_a_contagem_fica_no_data_para_o_menu(banco):
    database.save_campaign("u1", "Teste", CAMPANHA)
    assert banco[0]["data"]["_n_historico"] == 2


# ---------------------------------------------------------------------------
# Ler
# ---------------------------------------------------------------------------

def test_ler_devolve_a_campanha_inteira(banco):
    database.save_campaign("u1", "Teste", CAMPANHA)
    lida = database.get_campaign("u1", "Teste")
    assert lida["conversation_history"] == CONVERSA
    assert lida["chapter"] == 2
    assert "_n_historico" not in lida, "detalhe de armazenamento não vaza para o jogo"


def test_campanha_no_formato_antigo_continua_abrindo(banco):
    """Gravada antes da coluna existir: a conversa está dentro do data."""
    banco.append({"user_id": "u1", "name": "Velha",
                  "data": {"name": "Velha", "conversation_history": CONVERSA},
                  "historico": []})
    lida = database.get_campaign("u1", "Velha")
    assert lida["conversation_history"] == CONVERSA


def test_campanha_sem_conversa_nenhuma(banco):
    database.save_campaign("u1", "Nova", {"name": "Nova"})
    assert database.get_campaign("u1", "Nova")["conversation_history"] == []


def test_campanha_que_nao_existe(banco):
    assert database.get_campaign("u1", "Fantasma") is None


def _sem_versao(campanha):
    return {k: v for k, v in (campanha or {}).items() if k != database.CAMPO_VERSAO}


def test_gravar_e_ler_de_volta_preserva_tudo(banco):
    database.save_campaign("u1", "Teste", CAMPANHA)
    lida = database.get_campaign("u1", "Teste")
    database.save_campaign("u1", "Teste", lida)
    # Só a versão muda de uma gravação para a outra; o jogo, não.
    assert _sem_versao(database.get_campaign("u1", "Teste")) == _sem_versao(lida)


# ---------------------------------------------------------------------------
# A migração acontece sozinha
# ---------------------------------------------------------------------------

def test_a_primeira_gravacao_migra_a_campanha_antiga(banco):
    banco.append({"user_id": "u1", "name": "Velha",
                  "data": {"name": "Velha", "chapter": 3,
                           "conversation_history": CONVERSA},
                  "historico": []})
    lida = database.get_campaign("u1", "Velha")
    database.save_campaign("u1", "Velha", lida)
    assert "conversation_history" not in banco[0]["data"]
    assert banco[0]["historico"] == CONVERSA
    assert banco[0]["data"]["chapter"] == 3


# ---------------------------------------------------------------------------
# O menu para de baixar a conversa
# ---------------------------------------------------------------------------

def test_o_menu_sabe_que_ha_conversa_sem_baixar_ela(banco):
    database.save_campaign("u1", "Teste", CAMPANHA)
    lista = database.list_campaigns("u1")
    assert lista[0]["has_history"] is True
    assert lista[0]["chapter"] == 2


def test_o_menu_com_campanha_sem_conversa(banco):
    database.save_campaign("u1", "Nova", {"name": "Nova"})
    assert database.list_campaigns("u1")[0]["has_history"] is False


def test_o_menu_ainda_le_campanha_do_formato_antigo(banco):
    banco.append({"user_id": "u1", "name": "Velha",
                  "data": {"name": "Velha", "conversation_history": CONVERSA},
                  "historico": []})
    assert database.list_campaigns("u1")[0]["has_history"] is True


def test_o_menu_nao_pede_a_coluna_do_historico():
    """Pedir `historico` aqui traria de volta o desperdício que isto conserta."""
    import inspect
    fonte = inspect.getsource(database.list_campaigns)
    assert '"name, data"' in fonte
    assert "historico" not in fonte.split('"name, data"')[0]


# ---------------------------------------------------------------------------
# Ambiente onde o ALTER TABLE não rodou
# ---------------------------------------------------------------------------

def test_sem_a_coluna_grava_como_antes(banco_antigo):
    database.save_campaign("u1", "Teste", CAMPANHA)
    assert banco_antigo[0]["data"]["conversation_history"] == CONVERSA
    assert "historico" not in banco_antigo[0]


def test_sem_a_coluna_le_como_antes(banco_antigo):
    database.save_campaign("u1", "Teste", CAMPANHA)
    lida = database.get_campaign("u1", "Teste")
    assert lida["conversation_history"] == CONVERSA


def test_a_descoberta_acontece_uma_vez_so(banco_antigo, monkeypatch):
    tentativas = {"n": 0}
    original = database._erro_de_coluna_ausente

    def contando(e):
        tentativas["n"] += 1
        return original(e)

    monkeypatch.setattr(database, "_erro_de_coluna_ausente", contando)
    for _ in range(5):
        database.save_campaign("u1", "Teste", CAMPANHA)
    assert tentativas["n"] == 1, "não pode bater a cabeça na coluna a cada gravação"


def test_erro_que_nao_e_de_coluna_continua_subindo(banco, monkeypatch):
    def explode(*a, **k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(database, "_scoped_upsert", explode)
    with pytest.raises(RuntimeError, match="connection refused"):
        database.save_campaign("u1", "Teste", CAMPANHA)


# ---------------------------------------------------------------------------
# A trava contra escrita perdida
# ---------------------------------------------------------------------------
# Duas abas na mesma campanha: quem grava por último apagava o turno do outro,
# em silêncio. A versão dentro do  torna o atropelo um fato conhecido.

def test_a_versao_sobe_a_cada_gravacao(banco):
    assert database.save_campaign("u1", "Teste", CAMPANHA) == 1
    assert banco[0]["data"][database.CAMPO_VERSAO] == 1
    lida = database.get_campaign("u1", "Teste")
    assert database.save_campaign("u1", "Teste", lida, versao_esperada=1) == 2


def test_gravar_com_a_versao_certa_passa(banco):
    database.save_campaign("u1", "Teste", CAMPANHA)
    database.save_campaign("u1", "Teste", {**CAMPANHA, "chapter": 9},
                           versao_esperada=1)
    assert banco[0]["data"]["chapter"] == 9


def test_gravar_com_versao_velha_e_conflito(banco):
    """A outra aba: leu na versão 1, alguém gravou a 2, e ela tenta com a 1."""
    database.save_campaign("u1", "Teste", CAMPANHA)              # v1
    database.save_campaign("u1", "Teste", CAMPANHA, versao_esperada=1)  # v2
    with pytest.raises(database.ConflitoDeGravacao) as erro:
        database.save_campaign("u1", "Teste", {**CAMPANHA, "chapter": 99},
                               versao_esperada=1)
    assert erro.value.esperada == 1 and str(erro.value.encontrada) == "2"
    assert banco[0]["data"]["chapter"] != 99, "o conflito não pode ter gravado"


def test_sem_versao_esperada_grava_como_sempre(banco):
    database.save_campaign("u1", "Teste", CAMPANHA)
    database.save_campaign("u1", "Teste", {**CAMPANHA, "chapter": 7})
    assert banco[0]["data"]["chapter"] == 7


def test_linha_que_ainda_nao_existe_e_criada(banco):
    """Sessão que leu de uma campanha apagada não pode ficar sem gravar."""
    database.save_campaign("u1", "Nova", CAMPANHA, versao_esperada=5)
    assert banco and banco[0]["name"] == "Nova"


def test_filtro_que_nao_serve_nao_trava_o_jogo(banco_sem_filtro_json):
    """
    Se o filtro no caminho do JSON não pegar nada neste Postgrest, TODA
    gravação pareceria conflito e o jogo pararia de salvar. Antes de gritar
    conflito, o módulo confere a versão de verdade — e, vendo que ela é a
    esperada, desliga a trava e grava.
    """
    database.save_campaign("u1", "Teste", CAMPANHA)
    database.save_campaign("u1", "Teste", {**CAMPANHA, "chapter": 4},
                           versao_esperada=1)
    assert banco_sem_filtro_json[0]["data"]["chapter"] == 4
    assert database._versao_condicional is False


def test_depois_de_desligada_nao_tenta_de_novo(banco_sem_filtro_json):
    database.save_campaign("u1", "Teste", CAMPANHA)
    database.save_campaign("u1", "Teste", CAMPANHA, versao_esperada=1)
    chamadas = {"n": 0}
    original = database._versao_gravada

    def contando(*a, **k):
        chamadas["n"] += 1
        return original(*a, **k)

    database._versao_gravada = contando
    try:
        database.save_campaign("u1", "Teste", CAMPANHA, versao_esperada=2)
    finally:
        database._versao_gravada = original
    assert chamadas["n"] == 0


def test_a_versao_lida_volta_para_a_sessao(banco):
    database.save_campaign("u1", "Teste", CAMPANHA)
    assert database.versao_de(database.get_campaign("u1", "Teste")) == 1
