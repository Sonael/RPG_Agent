"""
test_comandos_navegador.py

Os comandos "/" do chat, refeitos.

Eles nasceram antes das telas e continuaram despejando no chat uma cópia pior
do que as telas mostram. O que cada teste prende:
  • quem tem tela abre a tela (/ficha, /mochila, /magias, /proximos…), e o
    nome é achado sem acento e pela metade ("/ficha hel");
  • comando errado não vai ao Mestre como fala (gastava uma requisição e
    entrava na história) e sugere o certo;
  • /flags e /contexto, que mostravam as anotações internas do Mestre, saíram
    e explicam para onde ir;
  • /status lista só o grupo (antes vinham inimigos e mortos de lutas antigas);
  • /exportar baixa o arquivo (antes quebrava lendo o .md como JSON);
  • /rolar aceita d20 puro, vários termos e vantagem;
  • cada gênero fala a própria língua: no romance, /proximos, /tramas,
    /lugares, /segredos, /tensoes e /encontro — e nada de /rolar ou /status.

Depende do Playwright, que não está em requirements-dev.txt. Sem ele o arquivo
é pulado:

    pip install playwright && playwright install chromium
"""
import copy
import json
import re
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent

pytest.importorskip("playwright.sync_api",
                    reason="Playwright não instalado — veja o docstring")

sys.path.insert(0, str(RAIZ / "scripts"))

pytestmark = pytest.mark.slow

ROMANCE = {
    "campaign_type": "romance",
    "dnd_mode": False,
    "protagonist": "Clara",
    "chapter": 3,
    "relogio": {"dia": 3, "hora": 14},
    "encontros": [{"id": 1, "com": "Lucas", "dia": 3, "hora": 18, "onde": "Café Aurora",
                   "o_que": "jantar", "estado": "marcado", "cap": 3}],
    "characters": {
        "clara": {"name": "Clara", "description": "A protagonista.", "status": "vivo"},
        "lucas": {"name": "Lucas", "description": "O vizinho do 302.", "status": "vivo",
                  "atitude": 45, "confianca": -30, "vinculo": "interesse romântico",
                  "estagio": "flerte"},
        "marina": {"name": "Marina", "description": "Amiga de infância.", "status": "vivo",
                   "atitude": 70, "confianca": 60},
    },
    "party": [{"name": "Lucas", "role": "interesse romântico"},
              {"name": "Marina", "role": "melhor amiga"}],
    "segredos": {
        "a bolsa em lisboa": {
            "titulo": "A bolsa em Lisboa", "descricao": "Aceitou a bolsa e vai embora em março",
            "dono": "", "escondido_de": ["Lucas"], "sabem": ["Marina"],
            "revelado": False, "como": "", "dono_sabe": True, "cap": 2,
            "historico": [{"acao": "contou", "quem": "Marina", "cap": 2}]},
    },
    "quests": {
        "a carta perdida": {"titulo": "A carta perdida", "descricao": "Quem escreveu a carta?",
                            "status": "ativa", "objetivos": [], "cap_inicio": 3},
    },
}


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
def jogo(app_no_ar):
    """Abre o jogo com um estado; devolve (página, erros, pedidos ao Mestre)."""
    from playwright.sync_api import sync_playwright
    import requests

    url, nome, cap = app_no_ar
    with sync_playwright() as pw:
        nav = pw.chromium.launch()

        def abrir(estado=None):
            requests.post(f"{url}/__estado", json=estado or {}, timeout=10)
            ctx = nav.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True)
            ctx.add_init_script(cap._script_de_semente(nome, "pergaminho", cap.HISTORICO))
            pg = ctx.new_page()
            erros, ao_mestre = [], []
            pg.on("pageerror", lambda e: erros.append(str(e)))
            pg.on("request", lambda r: ao_mestre.append(r.post_data) if "/api/chat" in r.url else None)
            pg.goto(f"{url}/game.html", wait_until="networkidle")
            pg.wait_for_function("() => window._lastMem && window._lastMem.campaign_config && window.Comandos",
                                 timeout=8000)
            return pg, erros, ao_mestre

        yield abrir, cap
        nav.close()


def _digitar(pg, texto):
    pg.fill("#chat-input", texto)
    pg.press("#chat-input", "Enter")


def _ultima_nota(pg):
    pg.wait_for_timeout(250)
    return pg.locator("#chat-history .msg-row.system").last.inner_text()


# ---------------------------------------------------------------------------
# 1. D&D
# ---------------------------------------------------------------------------

def test_ajuda_lista_so_o_que_existe_nesta_campanha(jogo):
    abrir, _ = jogo
    pg, erros, _ = abrir()
    _digitar(pg, "/ajuda")
    texto = _ultima_nota(pg)
    for cmd in ("/ficha", "/status", "/mochila", "/magias", "/rolar", "/mundo", "/lembrar"):
        assert cmd in texto, (cmd, texto)
    for cmd in ("/flags", "/contexto", "/salvar", "/segredos"):
        assert cmd not in texto, (cmd, texto)
    assert not erros, erros[:3]


def test_comando_errado_nao_vai_ao_mestre(jogo):
    abrir, _ = jogo
    pg, erros, ao_mestre = abrir()
    _digitar(pg, "/fixa helena")
    texto = _ultima_nota(pg)
    assert "não é um comando" in texto and "/ficha" in texto, texto
    assert ao_mestre == [], "o comando errado foi ao Mestre como fala"
    assert not erros, erros[:3]


def test_comandos_que_sairam_dizem_para_onde_ir(jogo):
    abrir, _ = jogo
    pg, erros, ao_mestre = abrir()
    _digitar(pg, "/flags")
    assert "anotações internas" in _ultima_nota(pg)
    _digitar(pg, "/salvar local Torre Velha")
    assert "/lembrar" in _ultima_nota(pg)
    assert ao_mestre == []
    assert not erros, erros[:3]


def test_ficha_abre_a_tela_pelo_comeco_do_nome(jogo):
    abrir, _ = jogo
    pg, erros, _ = abrir()
    _digitar(pg, "/ficha hel")
    pg.wait_for_selector("#heroi-overlay:not(.hidden)", timeout=5000)
    pg.wait_for_function("() => /Helena/.test(document.getElementById('heroi-overlay').innerText)", timeout=5000)
    assert not erros, erros[:3]


def test_mochila_e_magias_abrem_as_telas(jogo):
    abrir, _ = jogo
    pg, erros, _ = abrir()
    _digitar(pg, "/inventario STELAR")     # apelido antigo, caixa alta
    pg.wait_for_selector("#inventory-overlay:not(.hidden)", timeout=5000)
    pg.keyboard.press("Escape")
    pg.evaluate("() => document.getElementById('inventory-overlay').classList.add('hidden')")
    _digitar(pg, "/magias helena")
    pg.wait_for_selector("#grimoire-overlay:not(.hidden)", timeout=5000)
    assert not erros, erros[:3]


def test_nome_que_nao_existe_avisa(jogo):
    abrir, _ = jogo
    pg, erros, _ = abrir()
    _digitar(pg, "/ficha <img src=x onerror=window.__xss=1>")
    texto = _ultima_nota(pg)
    assert "ninguém com o nome" in texto, texto
    assert pg.evaluate("() => !window.__xss && !document.querySelector('#chat-history img[src=x]')")
    assert not erros, erros[:3]


def test_status_lista_so_o_grupo(jogo):
    abrir, cap = jogo
    pg, erros, _ = abrir(copy.deepcopy(cap.COMBATE_ATIVO))   # Victoria, inimiga com ficha
    pg.evaluate("() => window.Combat && window.Combat._dismiss && window.Combat._dismiss()")
    _digitar(pg, "/status")
    pg.wait_for_selector("#chat-history .cmd-status-linha", timeout=5000)
    texto = _ultima_nota(pg)
    for nome in ("Stelar", "Helena", "Natasha"):
        assert nome in texto, texto
    assert "Victoria" not in texto, "inimiga no status do grupo"
    assert not erros, erros[:3]


def test_exportar_baixa_o_diario(jogo):
    abrir, _ = jogo
    pg, erros, _ = abrir()
    with pg.expect_download(timeout=8000) as baixou:
        _digitar(pg, "/exportar")
    assert baixou.value.suggested_filename.endswith(".md")
    assert not erros, erros[:3]


def test_rolar(jogo):
    abrir, _ = jogo
    pg, erros, ao_mestre = abrir()
    # A fórmula, sem depender da sorte.
    casos = pg.evaluate("""() => {
        const C = window.Comandos;
        const um = () => 0.999;                   // sempre o maior valor
        const total = (f) => C._lancar(C._interpretar(f), um).total;
        // Primeiro d20 tira 1, o segundo tira 20: a vantagem fica com o 20.
        const seq = () => { const v = [0, 0.999]; let i = 0; return () => v[i++ % 2]; };
        const comModo = (f) => C._lancar(C._interpretar(f), seq()).total;
        return {
            vantagem: comModo('d20 vantagem'), desvantagem: comModo('d20 desvantagem'),
            d20: total(''), soma: total('2d6+3'), varios: total('1d8+1d6+3'),
            menos: total('d20-2'), pct: total('d%'),
            ruim: C._interpretar('banana').erro, demais: C._interpretar('60d6').erro,
            modoErrado: C._interpretar('2d6 vantagem').erro,
        };
    }""")
    assert casos == {"vantagem": 20, "desvantagem": 1, "d20": 20, "soma": 15, "varios": 17, "menos": 18, "pct": 100,
                     "ruim": "formula", "demais": "limite", "modoErrado": "modo"}, casos
    _digitar(pg, "/rolar d20 vantagem")
    pg.wait_for_selector("#chat-history .cmd-rolagem .cmd-descartado", timeout=3000)
    _digitar(pg, "/rolar 2d6+3")
    total = int(pg.locator("#chat-history .cmd-rolagem strong").last.inner_text())
    assert 5 <= total <= 15
    assert ao_mestre == [], "a rolagem local foi ao Mestre"
    assert not erros, erros[:3]


def test_menu_sugere_nomes_depois_do_comando(jogo):
    abrir, _ = jogo
    pg, erros, _ = abrir()
    pg.fill("#chat-input", "/fic")
    pg.wait_for_selector("#cmd-menu .cmd-item", timeout=3000)
    assert "/ficha" in pg.inner_text("#cmd-menu")
    pg.press("#chat-input", "Tab")          # escolhe /ficha e passa aos nomes
    assert pg.input_value("#chat-input") == "/ficha "
    pg.wait_for_function("() => /Helena/.test(document.getElementById('cmd-menu').innerText)", timeout=3000)
    pg.fill("#chat-input", "/ficha nat")
    pg.wait_for_function("() => /Natasha/.test(document.getElementById('cmd-menu').innerText)", timeout=3000)
    assert "Helena" not in pg.inner_text("#cmd-menu")
    assert not erros, erros[:3]


# ---------------------------------------------------------------------------
# 2. Romance
# ---------------------------------------------------------------------------

def test_romance_fala_a_lingua_do_genero(jogo):
    abrir, _ = jogo
    pg, erros, _ = abrir(copy.deepcopy(ROMANCE))
    _digitar(pg, "/ajuda")
    texto = _ultima_nota(pg)
    for cmd in ("/proximos", "/tramas", "/lugares", "/segredos", "/tensoes", "/encontro", "/ficha"):
        assert cmd in texto, (cmd, texto)
    # Regras de D&D e o mundo da fantasia não existem aqui.
    for cmd in ("/status", "/rolar", "/mochila", "/magias", "/combate", "/mundo"):
        assert not re.search(re.escape(cmd) + r"\b", texto), (cmd, texto)
    assert not erros, erros[:3]


def test_romance_proximos_e_grupo_abrem_as_relacoes(jogo):
    abrir, _ = jogo
    pg, erros, _ = abrir(copy.deepcopy(ROMANCE))
    _digitar(pg, "/proximos")
    pg.wait_for_selector("#relacoes-overlay:not(.hidden)", timeout=5000)
    pg.evaluate("() => window.Relacoes._fechar ? window.Relacoes._fechar()"
                " : document.getElementById('relacoes-overlay').classList.add('hidden')")
    _digitar(pg, "/grupo")                    # o nome de sempre continua valendo
    pg.wait_for_selector("#relacoes-overlay:not(.hidden)", timeout=5000)
    assert not erros, erros[:3]


def test_romance_segredos_abre_na_aba_dos_segredos(jogo):
    abrir, _ = jogo
    pg, erros, _ = abrir(copy.deepcopy(ROMANCE))
    _digitar(pg, "/segredos")
    pg.wait_for_function(
        "() => /A bolsa em Lisboa/.test((document.getElementById('relacoes-overlay') || {}).innerText || '')",
        timeout=5000)
    assert not erros, erros[:3]


def test_romance_tramas_e_ficha_da_protagonista(jogo):
    abrir, _ = jogo
    pg, erros, _ = abrir(copy.deepcopy(ROMANCE))
    _digitar(pg, "/tramas carta")
    pg.wait_for_selector("#missoes-overlay:not(.hidden)", timeout=5000)
    assert "As Tramas" in pg.inner_text("#missoes-overlay")
    pg.evaluate("() => document.getElementById('missoes-overlay').classList.add('hidden')")
    _digitar(pg, "/ficha")                    # sem nome: a protagonista
    pg.wait_for_function("() => /Clara/.test((document.getElementById('pessoa-overlay') || {}).innerText || '')",
                         timeout=5000)
    assert not erros, erros[:3]


def test_romance_encontro_e_comando_de_regras(jogo):
    abrir, _ = jogo
    pg, erros, ao_mestre = abrir(copy.deepcopy(ROMANCE))
    _digitar(pg, "/encontro")
    assert "jantar com Lucas" in _ultima_nota(pg)
    _digitar(pg, "/rolar 2d6")
    assert "regras de D&D" in _ultima_nota(pg)
    assert ao_mestre == []
    assert not erros, erros[:3]
