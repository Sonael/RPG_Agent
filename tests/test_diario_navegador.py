"""
test_diario_navegador.py

O diário como livro no navegador: abre pelo "Ler o diário", pelo capítulo da
aba Mundo e pela entrada da barra lateral (na página dela, em destaque, e não
no editor); vira as páginas; leva às fichas dos personagens e dos locais e à
missão; "Editar" e "Nova entrada" usam o editor de sempre (e a entrada nova
agora é gravada); põe um evento sem capítulo no capítulo certo; e se
redesenha quando o mestre escreve com o livro aberto.

Depende do Playwright, que não está em requirements-dev.txt. Sem ele o arquivo
é pulado:

    pip install playwright && playwright install chromium
"""
import copy
import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent

pytest.importorskip("playwright.sync_api",
                    reason="Playwright não instalado — veja o docstring")

sys.path.insert(0, str(RAIZ / "scripts"))

pytestmark = pytest.mark.slow


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
    from playwright.sync_api import sync_playwright
    import requests

    url, nome, cap = app_no_ar
    campanha = json.loads((RAIZ / "scripts" / "temp.json").read_text(encoding="utf-8"))
    estado = copy.deepcopy(cap.DIARIO)
    estado["diary"] = campanha["diary"]          # a lista volta ao original a cada teste
    estado["saque_proposto"] = None
    requests.post(f"{url}/__estado", json=estado, timeout=10)
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        ctx = nav.new_context(viewport={"width": 1440, "height": 980})
        ctx.add_init_script(cap._script_de_semente(nome, "pergaminho", cap.HISTORICO))
        pg = ctx.new_page()
        erros = []
        pg.on("pageerror", lambda e: erros.append(str(e)))
        pg.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
        pg.goto(f"{url}/game.html", wait_until="networkidle")
        cap._sanear(pg)
        pg.wait_for_timeout(800)
        yield pg, erros, url
        nav.close()


def _esperar_pagina(pg, rotulo):
    pg.wait_for_selector("#diario-overlay:not(.hidden) .dia-pagina-titulo", timeout=5000)
    pg.wait_for_function(
        f"() => document.querySelector('#dia-pagina .dia-pagina-titulo').textContent === {rotulo!r}",
        timeout=5000)


def test_ler_o_diario_abre_no_capitulo_atual(pagina):
    pg, erros, _ = pagina
    pg.click(".tab-btn[data-tab='diario']")
    pg.click("#sb-diario-ler")
    _esperar_pagina(pg, "Capítulo 2")
    indice = [el.get_attribute("data-numero") for el in pg.query_selector_all("#dia-indice .dia-cap-item")]
    assert indice == ["resumo", "1", "2", "sem"]
    assert "atual" in pg.inner_text("#dia-indice .dia-cap-item[data-numero='2']")
    titulos = [t.inner_text() for t in pg.query_selector_all("#dia-pagina .dia-entrada h3")]
    assert titulos == ["Entre Sedas e Sombras", "O Peso da Coroa e o Aroma do Jasmim"]
    # Depois do capítulo 2 ainda vem a página "Sem capítulo".
    assert pg.is_enabled("#dia-proximo") and pg.is_enabled("#dia-anterior")
    assert not erros, erros[:3]


def test_capitulo_da_aba_mundo_abre_o_livro(pagina):
    pg, _, _ = pagina
    pg.click(".tab-btn[data-tab='mundo']")
    pg.click("#ws-chapter")
    _esperar_pagina(pg, "Capítulo 2")


def test_entrada_da_barra_lateral_abre_a_pagina_dela_e_nao_o_editor(pagina):
    pg, _, _ = pagina
    pg.click(".tab-btn[data-tab='diario']")
    # A barra lateral lista da mais nova para a mais antiga: a última é a do capítulo 1.
    pg.locator("#sb-diary .diary-entry").last.click()
    _esperar_pagina(pg, "Capítulo 1")
    assert pg.locator("#dia-pagina .dia-entrada.dia-destaque[data-indice='0']").count() == 1
    assert not pg.is_visible("#edit-overlay")


def test_virar_as_paginas_e_o_indice(pagina):
    pg, _, _ = pagina
    pg.evaluate("() => window.Diario._abrir()")
    _esperar_pagina(pg, "Capítulo 2")
    pg.click("#dia-anterior")
    _esperar_pagina(pg, "Capítulo 1")
    assert "Duelo das Pétalas" in pg.inner_text("#dia-pagina .dia-eventos")
    pg.click("#dia-anterior")
    _esperar_pagina(pg, "Até aqui")
    assert pg.is_disabled("#dia-anterior"), "Até aqui é a primeira página"
    pg.click("#dia-proximo")
    _esperar_pagina(pg, "Capítulo 1")
    pg.click("#dia-proximo")
    _esperar_pagina(pg, "Capítulo 2")
    pg.click("#dia-indice .dia-cap-item[data-numero='sem']")
    _esperar_pagina(pg, "Eventos de antes do registro de capítulos")


def test_neste_capitulo_leva_a_personagem_local_e_missao(pagina):
    pg, erros, _ = pagina
    pg.evaluate("() => window.Diario._abrir(2)")
    _esperar_pagina(pg, "Capítulo 2")
    ligacoes = pg.inner_text("#dia-pagina .dia-ligacoes")
    assert "Recrutamento das Sombras" in ligacoes and "Teste de Infiltração" in ligacoes
    assert "Duelo das Pétalas" not in ligacoes, "evento do capítulo 1 não entra no 2"
    assert "Villa Ravenhurst" in ligacoes and "A audiência real" in ligacoes and "começou" in ligacoes
    # Victoria só é citada no texto das entradas, não nos eventos.
    assert pg.locator("#dia-pagina .dia-ligacoes > .dia-pessoas .dia-pessoa", has_text="Victoria").count() == 1

    pg.locator("#dia-pagina .dia-ligacoes > .dia-pessoas .dia-pessoa", has_text="Natasha").first.click()
    pg.wait_for_function("() => document.getElementById('psn-nome').textContent === 'Natasha'", timeout=5000)
    assert pg.is_hidden("#diario-overlay")
    pg.evaluate("() => window.Personagens._fechar()")

    pg.evaluate("() => window.Diario._abrir(2)")
    _esperar_pagina(pg, "Capítulo 2")
    pg.locator("#dia-pagina .dia-locais .dia-link", has_text="Villa Ravenhurst").click()
    pg.wait_for_function("() => document.getElementById('lcl-nome').textContent === 'Villa Ravenhurst'",
                         timeout=5000)
    pg.evaluate("() => window.Locais._fechar()")

    pg.evaluate("() => window.Diario._abrir(2)")
    _esperar_pagina(pg, "Capítulo 2")
    pg.locator("#dia-pagina .dia-missoes .dia-link", has_text="A audiência real").click()
    pg.wait_for_selector("#missoes-overlay:not(.hidden) .msn-cartao[data-titulo='A audiência real']",
                         timeout=5000)
    assert not erros, erros[:3]


def test_editar_abre_o_editor_com_a_entrada(pagina):
    pg, _, _ = pagina
    pg.evaluate("() => window.Diario._abrir(2)")
    _esperar_pagina(pg, "Capítulo 2")
    pg.click("#dia-pagina .dia-entrada[data-indice='2'] .dia-editar")
    pg.wait_for_selector("#edit-overlay:not(.hidden) #ef-title", timeout=5000)
    assert pg.input_value("#ef-title") == "O Peso da Coroa e o Aroma do Jasmim"
    assert pg.is_hidden("#diario-overlay")


def test_nova_entrada_e_gravada_e_aparece_no_capitulo(pagina):
    pg, erros, _ = pagina
    pg.evaluate("() => window.Diario._abrir(1)")
    _esperar_pagina(pg, "Capítulo 1")
    pg.click("#dia-nova")
    pg.wait_for_selector("#edit-overlay:not(.hidden) #ef-title", timeout=5000)
    assert pg.input_value("#ef-chapter") == "1"
    pg.fill("#ef-title", "A promessa na fogueira")
    pg.fill("#ef-content", "Helena jurou que voltaria a Oakhaven.")
    pg.click("#edit-overlay button:has-text('Salvar')")
    pg.wait_for_selector("#edit-overlay", state="hidden", timeout=5000)
    pg.wait_for_function("() => (window._lastMem.diary || []).some(d => d.title === 'A promessa na fogueira')",
                         timeout=5000)
    pg.evaluate("() => window.Diario._abrir(1)")
    _esperar_pagina(pg, "Capítulo 1")
    assert "A promessa na fogueira" in pg.inner_text("#dia-pagina .dia-entradas")
    assert not erros, erros[:3]


def test_por_evento_sem_capitulo_no_capitulo_certo(pagina):
    pg, erros, _ = pagina
    pg.evaluate("() => window.Diario._abrir('sem')")
    _esperar_pagina(pg, "Eventos de antes do registro de capítulos")
    assert pg.input_value("#dia-mover-4") == "2", "sugere o capítulo atual"
    pg.select_option("#dia-mover-4", "1")
    pg.click("#dia-pagina .dia-evento[data-index='4'] .dia-mover button")
    # Sem mais eventos sem capítulo, o livro volta ao capítulo atual.
    _esperar_pagina(pg, "Capítulo 2")
    assert pg.locator("#dia-indice .dia-cap-item[data-numero='sem']").count() == 0
    assert "agora está no capítulo 1" in pg.inner_text("#dia-msg")
    pg.click("#dia-indice .dia-cap-item[data-numero='1']")
    _esperar_pagina(pg, "Capítulo 1")
    assert "O Reconhecimento Real" in pg.inner_text("#dia-pagina .dia-eventos")
    assert not erros, erros[:3]


def test_aberto_mostra_a_entrada_que_o_mestre_acabou_de_escrever(pagina):
    import requests
    pg, _, url = pagina
    pg.evaluate("() => window.Diario._abrir(2)")
    _esperar_pagina(pg, "Capítulo 2")
    campanha = json.loads((RAIZ / "scripts" / "temp.json").read_text(encoding="utf-8"))
    diario = campanha["diary"] + [{"chapter": 2, "title": "O convite lacrado",
                                   "content": "Um mensageiro trouxe o selo real."}]
    requests.post(f"{url}/__estado", json={"diary": diario}, timeout=10)
    pg.evaluate("() => window.sincronizarTelas()")
    pg.wait_for_function(
        "() => document.getElementById('dia-pagina').textContent.includes('O convite lacrado')", timeout=5000)


def test_saque_nao_abre_por_cima_do_diario(pagina):
    import capturar_telas as cap
    import requests
    pg, _, url = pagina
    pg.evaluate("() => window.Diario._abrir()")
    _esperar_pagina(pg, "Capítulo 2")
    requests.post(f"{url}/__estado", json=copy.deepcopy(cap.SAQUE), timeout=10)
    pg.evaluate("() => window.sincronizarTelas()")
    pg.wait_for_timeout(1000)
    assert pg.is_hidden("#loot-overlay"), "o saque abriu por cima do diário"
    pg.evaluate("() => window.Diario._fechar()")
    pg.wait_for_selector("#loot-overlay:not(.hidden)", timeout=5000)


def _visivel_no_indice(pg, numero):
    return pg.evaluate(
        """(numero) => {
             const nav = document.getElementById('dia-indice');
             const item = nav.querySelector(`.dia-cap-item[data-numero="${numero}"]`);
             const n = nav.getBoundingClientRect(), a = item.getBoundingClientRect();
             return a.left >= n.left - 1 && a.right <= n.right + 1
                 && a.top >= n.top - 1 && a.bottom <= n.bottom + 1;
           }""", str(numero))


def test_celular_indice_rola_ate_a_pagina_aberta(pagina):
    """No celular o índice é uma faixa horizontal: "Sem capítulo", a última,
    abria com o próprio botão fora da tela."""
    pg, _, _ = pagina
    pg.set_viewport_size({"width": 390, "height": 844})
    pg.evaluate("() => window.Diario._abrir('sem')")
    _esperar_pagina(pg, "Eventos de antes do registro de capítulos")
    assert pg.evaluate("() => { const n = document.getElementById('dia-indice');"
                       " return n.scrollWidth > n.clientWidth; }"), "a faixa precisa rolar neste cenário"
    assert _visivel_no_indice(pg, "sem")

    pg.click("#dia-anterior")
    _esperar_pagina(pg, "Capítulo 2")
    assert _visivel_no_indice(pg, 2)
    pg.click("#dia-anterior")
    _esperar_pagina(pg, "Capítulo 1")
    assert _visivel_no_indice(pg, 1)


def test_muitos_capitulos_a_coluna_rola_ate_o_aberto(pagina):
    import requests
    pg, _, url = pagina
    diario = [{"chapter": n, "title": f"Entrada do capítulo {n}", "content": "Texto."} for n in range(1, 21)]
    requests.post(f"{url}/__estado", json={"diary": diario, "chapter": 20}, timeout=10)
    pg.evaluate("() => window.Diario._abrir()")
    _esperar_pagina(pg, "Capítulo 20")
    assert pg.evaluate("() => { const n = document.getElementById('dia-indice');"
                       " return n.scrollHeight > n.clientHeight; }"), "a coluna precisa rolar neste cenário"
    assert _visivel_no_indice(pg, 20)


def test_ate_aqui_mostra_o_resumo_e_onde_estamos(pagina):
    import requests
    pg, erros, url = pagina
    requests.post(f"{url}/__estado", json={
        "story_summary": "Elowen se disfarça de boticário.\n\nA princesa Elara conhece o segredo.",
        "current_scene": "A antessala de prata, antes da audiência.",
        "current_location": "Palácio Real de Luminas",
    }, timeout=10)
    pg.evaluate("() => window.Diario._abrir('resumo')")
    _esperar_pagina(pg, "Até aqui")
    texto = pg.inner_text("#dia-pagina")
    assert "Elowen se disfarça de boticário." in texto and "A princesa Elara conhece o segredo." in texto
    assert pg.locator("#dia-pagina .dia-resumo .dia-texto p").count() == 2
    assert "A antessala de prata" in texto
    assert pg.locator("#dia-indice .dia-cap-aberto[data-numero='resumo']").count() == 1
    assert pg.is_hidden("#dia-nova"), "nova entrada é de capítulo"

    pg.locator("#dia-pagina .dia-onde .dia-link", has_text="Palácio Real de Luminas").click()
    pg.wait_for_function("() => document.getElementById('lcl-nome').textContent === 'Palácio Real de Luminas'",
                         timeout=5000)
    pg.evaluate("() => window.Locais._fechar()")

    pg.evaluate("() => window.Diario._abrir('resumo')")
    _esperar_pagina(pg, "Até aqui")
    pg.locator("#dia-pagina .dia-onde .dia-link").first.click()
    _esperar_pagina(pg, "Capítulo 2")
    assert not erros, erros[:3]


def test_editar_resumo_abre_o_editor_do_mundo(pagina):
    pg, _, _ = pagina
    pg.evaluate("() => window.Diario._abrir('resumo')")
    _esperar_pagina(pg, "Até aqui")
    pg.click("#dia-editar-mundo")
    pg.wait_for_selector("#edit-overlay:not(.hidden) #ef-story_summary", timeout=5000)
    assert pg.is_hidden("#diario-overlay")


def test_exportar_baixa_o_diario_em_markdown(pagina):
    pg, erros, _ = pagina
    pg.evaluate("() => window.Diario._abrir(2)")
    _esperar_pagina(pg, "Capítulo 2")
    with pg.expect_download(timeout=5000) as baixado:
        pg.click("#dia-exportar")
    arquivo = baixado.value
    assert arquivo.suggested_filename.endswith(".diario.md")
    conteudo = Path(arquivo.path()).read_text(encoding="utf-8")
    assert conteudo.startswith("# Diário de Campanha")
    assert "Entre Sedas e Sombras" in conteudo
    assert not erros, erros[:3]
