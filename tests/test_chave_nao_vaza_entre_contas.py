"""
test_chave_nao_vaza_entre_contas.py

A chave de API de um jogador aparecia para o próximo que entrasse no mesmo
navegador.

RELATADO NA PARTIDA: "quando eu deslogo e logo em outra conta, a chave de api
do usuário anterior aparece".

E o que aparece é a menor parte. `getApiKeys` (menu.html) injeta a chave em
/api/session/start, então a conta NOVA passava a gastar a cota — e a fatura —
da conta anterior, sem que nenhuma das duas percebesse. Vazavam junto a
contagem de uso, a cota do dia e as chaves `rpg_telas::<campanha>::…`, que
carregam o NOME das campanhas do outro dentro do próprio nome da chave.

A causa: `clearTokens()` apagava os dois tokens e mais nada.

O conserto tem duas pontas, porque o logout não é o único caminho — sessão que
expira, aba fechada, ou outra pessoa entrando direto também deixam o
localStorage do anterior de pé:

  • sair limpa tudo o que é do usuário;
  • entrar com outro user_id limpa antes de guardar qualquer coisa nova.

Estes testes rodam o utils.js DE VERDADE dentro do navegador, e não uma cópia
da lógica: o que falhou foi a fiação, não o raciocínio.

Depende do Playwright, que não está em requirements-dev.txt. Sem ele o arquivo
é pulado:

    pip install playwright && playwright install chromium
"""
import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent

pytest.importorskip("playwright.sync_api",
                    reason="Playwright não instalado — veja o docstring")

sys.path.insert(0, str(RAIZ / "scripts"))

pytestmark = pytest.mark.slow


# O que o jogador anterior deixou no navegador.
DO_ANTERIOR = {
    "rpg_access_token": "token-do-anterior",
    "rpg_refresh_token": "refresh-do-anterior",
    "rpg_token": "token-antigo-do-anterior",
    "access_token": "nome-legado-do-anterior",
    "rpg_user_id": "utilizador-1",
    "rpg_google_api_key": "AIza-CHAVE-SECRETA-DO-ANTERIOR",
    "rpg_deepseek_api_key": "sk-CHAVE-SECRETA-DO-ANTERIOR",
    "rpg_session": "sessao-do-anterior",
    "rpg_total_tokens": "98765",
    "rpg_daily_reqs": "42",
    "rpg_quota_date": "2026-09-01",
    "rpg_max_rpd": "1500",
    "rpg_telas::Campanha Secreta do Anterior::loja_visita": "7",
}

# O que é do APARELHO e não tem dono: sobrevive à troca de conta.
DO_APARELHO = {
    "rpg_theme": "pergaminho",
    "rpg_animacoes": "ligadas",
    "rpg_font_master": "Lora",
    "rpg_font_user": "Caveat",
    "rpg_font_menu": "Playfair Display",
    "rpg_barra_recolhida": "1",
}

SEGREDOS = ("rpg_google_api_key", "rpg_deepseek_api_key")


@pytest.fixture(scope="module")
def app_no_ar():
    import capturar_telas as cap

    campanha = json.loads((RAIZ / "scripts" / "temp.json").read_text(encoding="utf-8"))
    nome = campanha.get("name") or "Crônicas de Oakhaven"
    campanha["name"] = nome
    url, parar = cap._subir_servidor(campanha, nome)
    try:
        yield url, nome, cap
    finally:
        parar()


@pytest.fixture
def pagina(app_no_ar):
    """A tela de login com o navegador do jogador ANTERIOR já sujo."""
    from playwright.sync_api import sync_playwright

    url, _, _ = app_no_ar
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        ctx = nav.new_context(viewport={"width": 1280, "height": 900})
        semente = {**DO_ANTERIOR, **DO_APARELHO}
        ctx.add_init_script(
            "try { const s = " + json.dumps(semente) + ";"
            " Object.keys(s).forEach(k => localStorage.setItem(k, s[k])); }"
            " catch (_) {}"
        )
        pg = ctx.new_page()
        erros = []
        pg.on("pageerror", lambda e: erros.append(str(e)))
        pg.goto(f"{url}/login.html", wait_until="networkidle")
        yield pg, erros
        nav.close()


def _chaves(pg):
    return set(pg.evaluate("() => Object.keys(localStorage)"))


# ---------------------------------------------------------------------------
# 1. Sair leva tudo o que é do usuário
# ---------------------------------------------------------------------------

def test_a_chave_legada_nao_sobrevive_a_uma_visita_ao_menu(pagina):
    """
    A chave saiu do navegador de vez: agora ela vive presa à conta, no
    servidor (rpg/chaves.py). Quem ainda tinha uma guardada aqui a vê subir na
    primeira visita ao menu e sumir daqui — sem precisar colar de novo.

    Este teste começa com o navegador "sujo" do jeito antigo e confere que,
    depois de a página carregar, não sobrou chave nenhuma no localStorage.
    """
    pg, erros = pagina
    pg.wait_for_function(
        "() => !localStorage.getItem('rpg_google_api_key')", timeout=8000)

    for chave in SEGREDOS:
        assert pg.evaluate(f"() => localStorage.getItem('{chave}')") is None, chave
    assert not erros, erros[:3]


def test_o_logout_apaga_a_chave_de_api(pagina):
    """A trava continua valendo para quem chegar com a chave de outro jeito."""
    pg, erros = pagina
    pg.evaluate("() => localStorage.setItem('rpg_google_api_key', 'AIza-de-algum-lugar')")

    pg.evaluate("() => clearTokens()")

    for chave in SEGREDOS:
        assert pg.evaluate(f"() => localStorage.getItem('{chave}')") is None, chave
    assert not erros, erros[:3]


def test_o_logout_nao_deixa_nada_do_usuario_para_tras(pagina):
    pg, _ = pagina
    pg.evaluate("() => clearTokens()")
    ficaram = _chaves(pg) & set(DO_ANTERIOR)
    assert not ficaram, sorted(ficaram)


def test_o_nome_da_campanha_do_outro_nao_fica_na_chave(pagina):
    """`rpg_telas::<campanha>::…` carrega o nome da campanha no próprio nome."""
    pg, _ = pagina
    pg.evaluate("() => clearTokens()")
    assert not any("Campanha Secreta" in k for k in _chaves(pg))


def test_a_preferencia_do_aparelho_sobrevive(pagina):
    """Trocar de conta não pode apagar o tema e a fonte de quem empresta o PC."""
    pg, _ = pagina
    pg.evaluate("() => clearTokens()")
    for chave, valor in DO_APARELHO.items():
        assert pg.evaluate(f"() => localStorage.getItem('{chave}')") == valor, chave


# ---------------------------------------------------------------------------
# 2. Entrar com outra conta também limpa
# ---------------------------------------------------------------------------
# O logout é o caminho feliz. Sessão expirada, aba fechada e "outra pessoa
# entrou direto" deixam o localStorage do anterior de pé — e era por aí que a
# chave continuaria passando mesmo com o logout consertado.

def test_entrar_com_outra_conta_limpa_o_que_era_do_anterior(pagina):
    pg, _ = pagina
    pg.evaluate("() => entrarComoUsuario('utilizador-2')")

    for chave in SEGREDOS:
        assert pg.evaluate(f"() => localStorage.getItem('{chave}')") is None, chave
    assert pg.evaluate("() => localStorage.getItem('rpg_user_id')") == "utilizador-2"


def test_entrar_na_mesma_conta_nao_limpa_nada(pagina):
    """
    Voltar para a própria conta não pode custar as preferências guardadas —
    e não custa mais a chave, que hoje vem do servidor de qualquer forma.
    """
    pg, _ = pagina
    pg.evaluate("() => localStorage.setItem('rpg_total_tokens', '4242')")
    pg.evaluate("() => localStorage.setItem('rpg_user_id', 'utilizador-1')")

    pg.evaluate("() => entrarComoUsuario('utilizador-1')")

    assert pg.evaluate("() => localStorage.getItem('rpg_total_tokens')") == "4242"


def test_primeiro_login_do_aparelho_nao_apaga_nada(pagina):
    """Sem dono anterior registrado, não há o que limpar."""
    pg, _ = pagina
    pg.evaluate("() => localStorage.setItem('rpg_total_tokens', '4242')")
    pg.evaluate("() => localStorage.removeItem('rpg_user_id')")

    pg.evaluate("() => entrarComoUsuario('utilizador-9')")

    assert pg.evaluate("() => localStorage.getItem('rpg_total_tokens')") == "4242"


# ---------------------------------------------------------------------------
# 3. A fiação
# ---------------------------------------------------------------------------

def test_a_lista_de_excecoes_e_de_excecoes_e_nao_de_alvos():
    """
    Quem acrescentar uma chave no futuro e esquecer do utils.js precisa errar
    para o lado seguro: a chave é apagada a mais, não vazada a menos.
    """
    js = (RAIZ / "static" / "js" / "utils.js").read_text(encoding="utf-8")
    assert "CHAVES_DO_APARELHO" in js
    assert "k.startsWith('rpg_')" in js, (
        "a limpeza precisa varrer tudo o que é `rpg_` e poupar só a lista"
    )


def test_o_login_avisa_a_troca_de_usuario():
    js = (RAIZ / "static" / "js" / "auth.js").read_text(encoding="utf-8")
    assert "entrarComoUsuario(data.user_id)" in js
    # Antes de guardar o que é novo, senão a limpeza levaria junto.
    assert js.index("entrarComoUsuario") < js.index("setTokens(data.access_token")


def test_o_servidor_manda_o_user_id_no_login():
    fonte = (RAIZ / "rpg" / "auth.py").read_text(encoding="utf-8")
    assert '"user_id":' in fonte, "sem user_id o cliente não sabe que trocou de conta"


def test_a_versao_do_js_subiu():
    """
    Correção de segurança com JS em cache é correção que não chega a ninguém.
    """
    for pagina_html in ("login.html", "menu.html", "game.html"):
        html = (RAIZ / "static" / pagina_html).read_text(encoding="utf-8")
        if "utils.js?v=" in html:
            assert "utils.js?v=27" not in html, pagina_html
