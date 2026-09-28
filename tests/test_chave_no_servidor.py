"""
test_chave_no_servidor.py

A chave de API sai do navegador e passa a morar presa ao usuário.

O conserto anterior fechou o vazamento entre contas apagando o localStorage no
logout — mas cobrava um "colar de novo" a cada saída, e a credencial continuava
num lugar que qualquer XSS lê e que viaja pela rede a cada início de sessão.

Agora ela vive numa linha por usuário, cifrada. O navegador nunca a recebe de
volta: a tela sabe só que ela existe e o fim dela.

O que estes testes prendem:
  • a chave inteira NÃO volta para o cliente — é o ponto da mudança;
  • ela é gravada cifrada, e não em claro;
  • cada usuário lê a sua, e só a sua;
  • gravar uma não encosta na outra, e string vazia apaga;
  • sem a tabela, nada quebra: o caminho antigo continua atendendo;
  • segredo trocado devolve vazio em vez de mandar lixo para a API.
"""
import importlib.util
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent

# Como nos outros testes de banco: o módulo REAL, carregado do arquivo, com um
# cliente Postgrest de bancada. Nada toca a rede.
_ARQ = RAIZ / "rpg" / "chaves.py"
_spec = importlib.util.spec_from_file_location("chaves_de_verdade", _ARQ)
chaves = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chaves)


class _Resposta:
    def __init__(self, data):
        self.data = data


class _Tabela:
    def __init__(self, linhas, existe=True):
        self.linhas, self.existe = linhas, existe
        self.acao = self.payload = None
        self.filtros = {}

    def _checar(self):
        if not self.existe:
            raise RuntimeError("Could not find the table 'public.usuario_chaves' "
                               "in the schema cache (PGRST205)")

    def select(self, _colunas):
        self.acao = "select"
        return self

    def upsert(self, payload, on_conflict=None):
        self.acao, self.payload = "upsert", payload
        return self

    def delete(self):
        self.acao = "delete"
        return self

    def eq(self, campo, valor):
        self.filtros[campo] = valor
        return self

    def limit(self, _n):
        return self

    def execute(self):
        self._checar()
        if self.acao == "upsert":
            alvo = next((l for l in self.linhas
                         if l["user_id"] == self.payload["user_id"]), None)
            if alvo:
                alvo.update(self.payload)
            else:
                self.linhas.append(dict(self.payload))
            return _Resposta([self.payload])
        achadas = [l for l in self.linhas
                   if all(l.get(k) == v for k, v in self.filtros.items())]
        if self.acao == "delete":
            for l in achadas:
                self.linhas.remove(l)
            return _Resposta(achadas)
        return _Resposta([dict(l) for l in achadas])


class _Cliente:
    def __init__(self, linhas, existe=True):
        self.linhas, self.existe = linhas, existe

    def from_(self, _tabela):
        return _Tabela(self.linhas, self.existe)


UM = "11111111-1111-1111-1111-111111111111"
OUTRO = "22222222-2222-2222-2222-222222222222"


def _montar(monkeypatch, existe=True, segredo="segredo-de-bancada"):
    """
    A bancada entra em `_tabela`, e não em `database._client`: a conftest
    troca `rpg.database` por um dublê que não tem cliente nenhum, e o que
    interessa medir aqui é o chaves.py, não o caminho até o Postgrest.
    """
    linhas = []
    monkeypatch.setattr(chaves, "_tabela",
                        lambda _uid: _Tabela(linhas, existe))
    monkeypatch.setenv("RPG_SEGREDO_CHAVES", segredo)
    monkeypatch.setattr(chaves, "_tem_tabela", None)
    monkeypatch.setattr(chaves, "_fernet", None)
    return linhas


@pytest.fixture
def banco(monkeypatch):
    return _montar(monkeypatch)


@pytest.fixture
def banco_sem_tabela(monkeypatch):
    return _montar(monkeypatch, existe=False)


# ---------------------------------------------------------------------------
# 1. Guardar e ler
# ---------------------------------------------------------------------------

def test_guarda_e_devolve_a_chave(banco):
    chaves.salvar(UM, google="AIza-minha-chave")
    assert chaves.ler(UM)["google"] == "AIza-minha-chave"


def test_cada_um_le_a_sua(banco):
    chaves.salvar(UM, google="chave-do-um")
    chaves.salvar(OUTRO, google="chave-do-outro")
    assert chaves.ler(UM)["google"] == "chave-do-um"
    assert chaves.ler(OUTRO)["google"] == "chave-do-outro"


def test_quem_nao_tem_chave_recebe_vazio(banco):
    assert chaves.ler(OUTRO) == {"google": "", "deepseek": ""}


def test_gravar_uma_nao_encosta_na_outra(banco):
    chaves.salvar(UM, google="a-do-google", deepseek="a-da-deepseek")
    chaves.salvar(UM, google="google-nova")
    guardadas = chaves.ler(UM)
    assert guardadas["google"] == "google-nova"
    assert guardadas["deepseek"] == "a-da-deepseek"


def test_string_vazia_apaga(banco):
    chaves.salvar(UM, google="a-do-google")
    chaves.salvar(UM, google="")
    assert chaves.ler(UM)["google"] == ""


def test_apagar_leva_as_duas(banco):
    chaves.salvar(UM, google="g", deepseek="d")
    chaves.apagar(UM)
    assert chaves.ler(UM) == {"google": "", "deepseek": ""}


def test_sem_user_id_nao_grava_nem_le(banco):
    assert chaves.ler("") == {"google": "", "deepseek": ""}
    assert chaves.salvar("", google="x") is False


# ---------------------------------------------------------------------------
# 2. Cifrada em repouso
# ---------------------------------------------------------------------------

def test_a_chave_nao_fica_em_claro_no_banco(banco):
    chaves.salvar(UM, google="AIza-SEGREDO-EM-CLARO")
    guardado = banco[0]["google_api_key"]
    assert "AIza-SEGREDO-EM-CLARO" not in guardado
    assert guardado.startswith("f1:")


def test_valor_gravado_antes_da_cifra_continua_legivel(banco):
    """Ninguém fica trancado para fora por uma mudança de formato."""
    banco.append({"user_id": UM, "google_api_key": "chave-antiga-em-claro",
                  "deepseek_api_key": None})
    assert chaves.ler(UM)["google"] == "chave-antiga-em-claro"


def test_segredo_trocado_devolve_vazio_em_vez_de_lixo(banco, monkeypatch, capsys):
    """
    Mandar bytes ilegíveis para a API do Google daria um erro que o jogador
    não teria como entender. Vazio ele entende: a chave é pedida de novo.
    """
    chaves.salvar(UM, google="AIza-minha-chave")
    monkeypatch.setenv("RPG_SEGREDO_CHAVES", "outro-segredo")
    monkeypatch.setattr(chaves, "_fernet", None)

    assert chaves.ler(UM)["google"] == ""
    assert "decifrar" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 3. O que a TELA pode saber
# ---------------------------------------------------------------------------

def test_o_resumo_nao_entrega_a_chave(banco):
    chaves.salvar(UM, google="AIza-uma-chave-secreta-2f4a")
    r = chaves.resumo(UM)
    assert r["google"] == {"definida": True, "fim": "2f4a"}
    # A chave inteira não aparece em canto nenhum do que vai para a tela.
    assert "AIza-uma-chave-secreta" not in str(r)


def test_o_resumo_de_quem_nao_tem(banco):
    assert chaves.resumo(UM)["deepseek"] == {"definida": False, "fim": ""}


# ---------------------------------------------------------------------------
# 4. Sem a tabela, nada quebra
# ---------------------------------------------------------------------------

def test_sem_a_tabela_ler_devolve_vazio(banco_sem_tabela):
    assert chaves.ler(UM) == {"google": "", "deepseek": ""}


def test_sem_a_tabela_gravar_avisa_que_nao_deu(banco_sem_tabela):
    assert chaves.salvar(UM, google="x") is False


def test_a_falta_da_tabela_e_descoberta_uma_vez(banco_sem_tabela, capsys):
    chaves.ler(UM)
    chaves.ler(UM)
    chaves.salvar(UM, google="x")
    assert chaves._tem_tabela is False
    assert capsys.readouterr().out.count("não existe") == 1


def test_erro_que_nao_e_de_tabela_continua_subindo(monkeypatch):
    """Rede caindo não pode ser confundida com ambiente sem DDL."""
    def _explode(_uid):
        raise RuntimeError("connection reset by peer")

    monkeypatch.setattr(chaves, "_tabela", _explode)
    monkeypatch.setattr(chaves, "_tem_tabela", None)
    with pytest.raises(RuntimeError):
        chaves.ler(UM)


# ---------------------------------------------------------------------------
# 5. A fiação: o servidor e a tela
# ---------------------------------------------------------------------------

def test_o_servidor_abre_as_duas_rotas():
    import server
    rotas = {(str(r), tuple(sorted(r.methods & {"GET", "POST"})))
             for r in server.app.url_map.iter_rules()}
    assert ("/api/user/keys", ("GET",)) in rotas or \
           any(s == "/api/user/keys" for s, _ in rotas)
    metodos = set()
    for r in server.app.url_map.iter_rules():
        if str(r) == "/api/user/keys":
            metodos |= (r.methods & {"GET", "POST"})
    assert metodos == {"GET", "POST"}


def test_os_tres_consumidores_passam_pelo_mesmo_lugar():
    """
    Eram três leituras soltas de `data.get("google_api_key")`. Uma que
    escapasse continuaria aceitando a chave só do corpo — e o jogador com a
    chave guardada veria "sem chave" em uma tela e não em outra.
    """
    import inspect

    import server
    for rota in (server.gemini_models, server.start_session,
                 server.generate_lore):
        fonte = inspect.getsource(rota)
        assert "_chaves_do_usuario" in fonte, rota.__name__
        assert 'data.get("google_api_key"' not in fonte, rota.__name__


def test_o_navegador_nao_guarda_mais_a_chave():
    html = (RAIZ / "static" / "menu.html").read_text(encoding="utf-8")
    # O que sobrou de GOOGLE_KEY_STORAGE é só a migração de quem já tinha.
    assert "localStorage.setItem(GOOGLE_KEY_STORAGE" not in html
    assert "localStorage.removeItem(GOOGLE_KEY_STORAGE)" in html, (
        "a migração precisa apagar a chave velha do navegador"
    )
    # E o remendo que reescrevia window.fetch para injetar a chave saiu.
    assert "window.fetch = function" not in html


def test_a_tela_pergunta_ao_servidor_se_ha_chave():
    js = (RAIZ / "static" / "js" / "menu.js").read_text(encoding="utf-8")
    assert "_chavesDefinidas" in js
    assert "getApiKeys().google_api_key" not in js


def test_a_versao_do_menu_subiu():
    """Correção de credencial servida de cache não chega a ninguém."""
    html = (RAIZ / "static" / "menu.html").read_text(encoding="utf-8")
    assert "menu.js?v=99" not in html
