"""
test_historico_em_tabela.py

O turno 300 apagava o turno 100.

A coluna `historico` resolveu o PESO da gravação (82% do documento eram
conversa). Não resolveu isto: memory.MAX_HISTORY_SAVED corta a conversa nas
últimas 200 mensagens A CADA GRAVAÇÃO, e o que cai fora some de vez. O jogador
não tem como reler a cena em que conheceu alguém; o sistema não tem como
responder "onde foi mesmo que a gente deixou o cavalo".

Agora cada mensagem é uma linha:

    create table if not exists historico_mensagens (
      id bigserial primary key, user_id text not null,
      campaign_name text not null, ordem integer not null,
      role text not null, content text not null default '',
      interno text, created_at timestamptz not null default now(),
      unique (user_id, campaign_name, ordem));

A janela de trabalho continua sendo as últimas 200 — é o que o mestre lê e o
que a tela desenha. O resto se alcança por página ou por busca.

ENQUANTO O SQL NÃO RODAR nada muda: a primeira tentativa falha, o módulo anota
e a conversa continua na coluna. É a mesma tolerância da coluna, pelo mesmo
motivo — ambiente sem DDL não pode parar de gravar.
"""
import importlib.util
from pathlib import Path

import pytest

# Como em test_historico_em_coluna.py: a conftest troca rpg.database por um
# dublê, e aqui quem está sob exame é o módulo REAL, carregado do arquivo com
# um cliente Postgrest de bancada — nada toca a rede.
_ARQUIVO = Path(__file__).resolve().parent.parent / "rpg" / "database.py"
_spec = importlib.util.spec_from_file_location("database_com_tabela", _ARQUIVO)
database = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(database)


class _Resposta:
    def __init__(self, data):
        self.data = data


class _Mensagens:
    """A tabela historico_mensagens: filtros, ordem, limite e upsert por ordem."""

    def __init__(self, linhas, existe=True):
        self.linhas, self.existe = linhas, existe
        self.acao = self.payload = None
        self.filtros, self.menor_que = {}, None
        self.contem = None
        self._limite = None
        self.desc = False

    def _checar(self):
        if not self.existe:
            raise RuntimeError(
                "Could not find the table 'public.historico_mensagens' in the "
                "schema cache (PGRST205)")

    def select(self, colunas):
        self.acao, self.colunas = "select", colunas
        return self

    def upsert(self, payload, on_conflict=None):
        self.acao, self.payload = "upsert", payload
        return self

    def update(self, payload):
        self.acao, self.payload = "update", payload
        return self

    def delete(self):
        self.acao = "delete"
        return self

    def eq(self, campo, valor):
        self.filtros[campo] = valor
        return self

    def lt(self, campo, valor):
        self.menor_que = (campo, valor)
        return self

    def ilike(self, campo, padrao):
        self.contem = (campo, padrao.strip("%").replace("\\", ""))
        return self

    def order(self, campo, desc=False):
        self.desc = desc
        return self

    def limit(self, n):
        self._limite = n
        return self

    def _casam(self):
        fora = []
        for l in self.linhas:
            if any(l.get(k) != v for k, v in self.filtros.items()):
                continue
            if self.menor_que and not l.get(self.menor_que[0]) < self.menor_que[1]:
                continue
            if self.contem and self.contem[1].lower() not in (l.get("content") or "").lower():
                continue
            fora.append(l)
        return fora

    def execute(self):
        self._checar()
        if self.acao == "upsert":
            for nova in self.payload:
                chave = (nova["user_id"], nova["campaign_name"], nova["ordem"])
                antiga = next((l for l in self.linhas
                               if (l["user_id"], l["campaign_name"], l["ordem"]) == chave),
                              None)
                if antiga:
                    antiga.update(nova)
                else:
                    self.linhas.append(dict(nova))
            return _Resposta(list(self.payload))
        achadas = self._casam()
        if self.acao == "delete":
            for l in achadas:
                self.linhas.remove(l)
            return _Resposta(achadas)
        if self.acao == "update":
            for l in achadas:
                l.update(self.payload)
            return _Resposta(achadas)
        achadas = sorted(achadas, key=lambda l: l["ordem"], reverse=self.desc)
        if self._limite:
            achadas = achadas[:self._limite]
        return _Resposta([dict(l) for l in achadas])


class _Campanhas:
    """O mínimo da tabela campaigns — o suficiente para save/get funcionarem."""

    def __init__(self, linhas):
        self.linhas = linhas
        self.acao = self.payload = self.colunas = None
        self.filtros = {}

    def select(self, colunas):
        self.acao, self.colunas = "select", colunas
        return self

    def upsert(self, payload, on_conflict=None):
        self.acao, self.payload = "upsert", payload
        return self

    def update(self, payload):
        self.acao, self.payload = "update", payload
        return self

    def delete(self):
        self.acao = "delete"
        return self

    def eq(self, campo, valor):
        self.filtros[campo] = valor
        return self

    def limit(self, _n):
        return self

    def order(self, *a, **k):
        return self

    def execute(self):
        if self.acao == "upsert":
            chave = (self.payload["user_id"], self.payload["name"])
            for l in self.linhas:
                if (l["user_id"], l["name"]) == chave:
                    l.update(self.payload)
                    return _Resposta([l])
            self.linhas.append(dict(self.payload))
            return _Resposta([self.payload])
        achadas = [l for l in self.linhas
                   if all(l.get(k) == v for k, v in self.filtros.items()
                          if "->>" not in k)]
        if self.acao == "delete":
            for l in achadas:
                self.linhas.remove(l)
            return _Resposta(achadas)
        if self.acao == "update":
            for l in achadas:
                l.update(self.payload)
            return _Resposta(achadas)
        pedidas = [c.strip() for c in (self.colunas or "").split(",") if c.strip()]
        return _Resposta([{c: l.get(c) for c in pedidas} for l in achadas])


class _Cliente:
    def __init__(self, campanhas, mensagens, tabela_existe=True):
        self.campanhas, self.mensagens = campanhas, mensagens
        self.tabela_existe = tabela_existe

    def from_(self, tabela):
        if tabela == "historico_mensagens":
            return _Mensagens(self.mensagens, self.tabela_existe)
        return _Campanhas(self.campanhas)


def _montar(monkeypatch, tabela_existe=True):
    campanhas, mensagens = [], []
    monkeypatch.setattr(database, "_client",
                        lambda: _Cliente(campanhas, mensagens, tabela_existe))
    monkeypatch.setattr(database, "_tem_coluna_historico", None)
    monkeypatch.setattr(database, "_tem_tabela_historico", None)
    monkeypatch.setattr(database, "_versao_condicional", True)
    database._TOTAL_GRAVADO.clear()
    database._ULTIMA_GRAVADA.clear()
    return campanhas, mensagens


@pytest.fixture
def banco(monkeypatch):
    return _montar(monkeypatch)


@pytest.fixture
def banco_sem_tabela(monkeypatch):
    """Ambiente onde o SQL da tabela ainda não rodou."""
    return _montar(monkeypatch, tabela_existe=False)


def _campanha(conversa):
    return {"name": "Teste", "chapter": 1, "characters": {"a": {"name": "A"}},
            "conversation_history": list(conversa)}


def _conversa(n, inicio=0):
    """A conversa a partir da mensagem `inicio` — o papel vem da posição
    ABSOLUTA, como na conversa de verdade: a janela andar não troca quem
    falou."""
    return [{"role": "user" if ((inicio + i) % 2 == 0) else "assistant",
             "text": f"mensagem {inicio + i}"} for i in range(n)]


# ---------------------------------------------------------------------------
# 1. Gravar: uma linha por mensagem, e só o que é novo
# ---------------------------------------------------------------------------

def test_cada_mensagem_vira_uma_linha(banco):
    _, mensagens = banco
    database.save_campaign("u1", "Teste", _campanha(_conversa(3)))
    assert [m["ordem"] for m in mensagens] == [0, 1, 2]
    assert mensagens[0]["role"] == "user" and mensagens[0]["content"] == "mensagem 0"
    assert mensagens[0]["campaign_name"] == "Teste"


def test_a_segunda_gravacao_manda_so_o_que_e_novo(banco):
    _, mensagens = banco
    conversa = _conversa(3)
    database.save_campaign("u1", "Teste", _campanha(conversa))
    conversa.append({"role": "user", "text": "mensagem 3"})
    database.save_campaign("u1", "Teste", _campanha(conversa))
    assert [m["ordem"] for m in mensagens] == [0, 1, 2, 3]
    assert len(mensagens) == 4, "mensagem regravada virou linha duplicada"


def test_a_janela_cortada_nao_apaga_o_comeco(banco):
    """
    O caso que motivou tudo: a memória corta nas últimas 200 e regrava. A
    campanha inteira tem de continuar na tabela.
    """
    _, mensagens = banco
    database.save_campaign("u1", "Teste", _campanha(_conversa(200)))
    # O turno seguinte: a memória já cortou a primeira e acrescentou uma nova.
    janela = _conversa(200, inicio=1)
    database.save_campaign("u1", "Teste", _campanha(janela))
    assert len(mensagens) == 201
    assert mensagens[0]["content"] == "mensagem 0", "o começo da campanha sumiu"


def test_a_contagem_vai_no_data_para_o_menu(banco):
    campanhas, _ = banco
    database.save_campaign("u1", "Teste", _campanha(_conversa(5)))
    assert campanhas[0]["data"]["_n_historico"] == 5


def test_o_dict_de_quem_chamou_fica_intacto(banco):
    dados = _campanha(_conversa(2))
    database.save_campaign("u1", "Teste", dados)
    assert dados["conversation_history"] and "_n_historico" not in dados


# ---------------------------------------------------------------------------
# 2. Ler: a janela vem da tabela
# ---------------------------------------------------------------------------

def test_a_leitura_traz_a_janela_da_tabela(banco):
    database.save_campaign("u1", "Teste", _campanha(_conversa(5)))
    lida = database.get_campaign("u1", "Teste")
    assert [m["text"] for m in lida["conversation_history"]] == \
           [f"mensagem {i}" for i in range(5)]
    assert "_n_historico" not in lida, "detalhe de armazenamento vazou"


def test_a_janela_tem_teto(banco, monkeypatch):
    monkeypatch.setattr(database, "JANELA_HISTORICO", 10)
    database.save_campaign("u1", "Teste", _campanha(_conversa(25)))
    lida = database.get_campaign("u1", "Teste")
    janela = lida["conversation_history"]
    assert len(janela) == 10
    assert janela[0]["text"] == "mensagem 15" and janela[-1]["text"] == "mensagem 24"


def test_campanha_sem_linha_na_tabela_cai_na_coluna(banco):
    """Campanha gravada antes da tabela existir continua abrindo."""
    campanhas, _ = banco
    campanhas.append({"user_id": "u1", "name": "Antiga",
                      "data": {"chapter": 1},
                      "historico": [{"role": "user", "text": "de antes"}]})
    lida = database.get_campaign("u1", "Antiga")
    assert [m["text"] for m in lida["conversation_history"]] == ["de antes"]


# ---------------------------------------------------------------------------
# 3. Paginar e procurar — o que a tabela existe para permitir
# ---------------------------------------------------------------------------

def test_a_pagina_volta_no_tempo(banco):
    database.save_campaign("u1", "Teste", _campanha(_conversa(30)))

    p1 = database.historico_pagina("u1", "Teste", limite=10)
    assert [m["text"] for m in p1["mensagens"]] == \
           [f"mensagem {i}" for i in range(20, 30)]
    assert p1["tem_mais"] is True and p1["primeira_ordem"] == 20

    p2 = database.historico_pagina("u1", "Teste", antes_de=p1["primeira_ordem"],
                                   limite=10)
    assert [m["text"] for m in p2["mensagens"]] == \
           [f"mensagem {i}" for i in range(10, 20)]


def test_a_ultima_pagina_avisa_que_acabou(banco):
    database.save_campaign("u1", "Teste", _campanha(_conversa(8)))
    p = database.historico_pagina("u1", "Teste", limite=10)
    assert p["tem_mais"] is False and len(p["mensagens"]) == 8


def test_a_busca_acha_o_que_saiu_da_janela(banco):
    conversa = _conversa(5)
    conversa[1] = {"role": "assistant", "text": "O cavalo ficou preso na Ponte Quebrada."}
    database.save_campaign("u1", "Teste", _campanha(conversa))

    achados = database.historico_busca("u1", "Teste", "cavalo")

    assert len(achados) == 1
    assert "Ponte Quebrada" in achados[0]["text"] and achados[0]["ordem"] == 1


def test_a_busca_ignora_termo_curto_demais(banco):
    database.save_campaign("u1", "Teste", _campanha(_conversa(5)))
    assert database.historico_busca("u1", "Teste", "a") == []


def test_a_busca_nao_vaza_para_outra_campanha(banco):
    database.save_campaign("u1", "Uma", _campanha(
        [{"role": "user", "text": "o cavalo malhado"}]))
    database.save_campaign("u1", "Outra", _campanha(
        [{"role": "user", "text": "o cavalo preto"}]))
    achados = database.historico_busca("u1", "Uma", "cavalo")
    assert [m["text"] for m in achados] == ["o cavalo malhado"]


# ---------------------------------------------------------------------------
# 4. Renomear e apagar arrastam a conversa junto
# ---------------------------------------------------------------------------

def test_renomear_leva_a_conversa(banco):
    _, mensagens = banco
    database.save_campaign("u1", "Teste", _campanha(_conversa(3)))
    database.rename_campaign("u1", "Teste", "Outro Nome")
    assert {m["campaign_name"] for m in mensagens} == {"Outro Nome"}
    assert database.historico_pagina("u1", "Outro Nome")["mensagens"]


def test_apagar_a_campanha_apaga_a_conversa(banco):
    _, mensagens = banco
    database.save_campaign("u1", "Teste", _campanha(_conversa(3)))
    database.delete_campaign("u1", "Teste")
    assert mensagens == []


# ---------------------------------------------------------------------------
# 5. Ambiente sem a tabela: nada muda
# ---------------------------------------------------------------------------

def test_sem_a_tabela_a_conversa_continua_na_coluna(banco_sem_tabela):
    campanhas, mensagens = banco_sem_tabela
    database.save_campaign("u1", "Teste", _campanha(_conversa(3)))
    assert mensagens == []
    assert len(campanhas[0]["historico"]) == 3
    lida = database.get_campaign("u1", "Teste")
    assert len(lida["conversation_history"]) == 3


def test_a_falta_da_tabela_e_descoberta_uma_vez(banco_sem_tabela, capsys):
    database.save_campaign("u1", "Teste", _campanha(_conversa(2)))
    database.save_campaign("u1", "Teste", _campanha(_conversa(3)))
    assert database._tem_tabela_historico is False
    assert capsys.readouterr().out.count("não existe") == 1


def test_sem_a_tabela_a_pagina_e_a_busca_voltam_vazias(banco_sem_tabela):
    database.save_campaign("u1", "Teste", _campanha(_conversa(3)))
    assert database.historico_pagina("u1", "Teste")["mensagens"] == []
    assert database.historico_busca("u1", "Teste", "mensagem") == []
    assert database.total_de_mensagens("u1", "Teste") == 0


def test_erro_que_nao_e_de_tabela_continua_subindo(monkeypatch):
    """Rede caindo não pode ser confundida com ambiente sem DDL."""
    class _Explode:
        def from_(self, _t):
            raise RuntimeError("connection reset by peer")

    monkeypatch.setattr(database, "_client", _Explode)
    monkeypatch.setattr(database, "_tem_tabela_historico", None)
    database._TOTAL_GRAVADO.clear()
    database._ULTIMA_GRAVADA.clear()
    with pytest.raises(RuntimeError):
        database.historico_busca("u1", "Teste", "cavalo")


# ---------------------------------------------------------------------------
# 6. O caminho: o servidor abre a porta e a tela usa
# ---------------------------------------------------------------------------
# Os testes acima exercitam o módulo. Dá para apagar a rota e todos eles
# continuam verdes.

def test_o_servidor_tem_a_rota_do_historico():
    import server
    rotas = {str(r) for r in server.app.url_map.iter_rules()}
    assert "/api/campaigns/<name>/historico" in rotas


def test_a_sessao_diz_onde_a_janela_comeca():
    import inspect

    import server
    fonte = inspect.getsource(server.start_session)
    assert "historico_comeca_em" in fonte, (
        "sem isto a tela não sabe que há campanha atrás da janela e o botão "
        "nunca aparece"
    )


def test_a_tela_sabe_paginar_e_procurar():
    raiz = Path(__file__).resolve().parents[1] / "static"
    js = (raiz / "js" / "game.js").read_text(encoding="utf-8")
    html = (raiz / "game.html").read_text(encoding="utf-8")
    assert "carregarHistoricoAnterior" in js and "buscarNoHistorico" in js
    assert "historico_comeca_em" in js
    assert "hist-mais" in html and "hist-busca" in html
