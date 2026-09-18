"""
test_temas_das_telas_navegador.py

As telas novas (ficha do local, do personagem, do herói, grupo, missões,
mapa, diário, elenco) seguem o tema escolhido.

Elas tinham a paleta de pergaminho fixa, e os blocos mais recentes já usavam
as variáveis do tema: no Noite de Tinta o texto ficava claro sobre o papel
claro. Aqui cada tela é aberta em temas claros e escuros e todo texto visível
é medido contra o fundo que está de fato atrás dele.

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

# Contraste mínimo de texto (WCAG pede 4,5 para texto comum; 3 é o piso para
# texto grande e o que separa "difícil" de "ilegível"). O texto apagado das
# telas é secundário de propósito, então o piso é o de texto grande.
CONTRASTE_MINIMO = 3.0

TELAS = [
    ("local", "#local-overlay", "() => window.Locais._abrir('Forja de Cliviate')"),
    ("personagem", "#pessoa-overlay", "() => window.Personagens._abrir('Brom')"),
    ("heroi", "#heroi-overlay", "() => window.Herois._abrir('Stelar')"),
    ("grupo", "#grupo-overlay", "() => window.Grupo._abrir()"),
    ("mapa", "#mapa-overlay", "() => window.Mapa._abrir('')"),
    ("missoes", "#missoes-overlay", "() => window.Missoes._abrir()"),
    ("diario", "#diario-overlay", "() => window.Diario._abrir()"),
    ("elenco", "#elenco-overlay", "() => window.Elenco._abrir('todos')"),
]

# Mede cada elemento com texto próprio: a cor do texto contra o primeiro
# fundo opaco dos ancestrais. Devolve os piores casos.
MEDIR = """
(seletor) => {
  const rgb = (s) => (s.match(/[\\d.]+/g) || []).map(Number);
  const lum = ([r, g, b]) => {
    const c = [r, g, b].map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  };
  const fundo = (el) => {
    for (let e = el; e && e !== document.documentElement; e = e.parentElement) {
      const c = rgb(getComputedStyle(e).backgroundColor);
      if (c.length >= 3 && (c.length < 4 || c[3] > 0.5)) return c;
    }
    return [255, 255, 255];
  };
  const raizes = [...document.querySelectorAll(seletor)];
  const raiz = raizes[0];
  const ruins = [];
  let medidos = 0;
  for (const el of raizes.flatMap(r => [r, ...r.querySelectorAll('*')])) {
    const proprio = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())
      || el.matches('textarea, input[type=text]');
    if (!proprio || !el.getClientRects().length) continue;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || Number(st.opacity) < 0.6) continue;
    if (el.closest(':disabled, [disabled]')) continue;
    const a = lum(rgb(st.color)), b = lum(fundo(el));
    const razao = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    medidos++;
    if (razao < %s) ruins.push([razao.toFixed(2), el.className || el.tagName, el.textContent.trim().slice(0, 40)]);
  }
  return {medidos, ruins, papel: getComputedStyle(raiz).getPropertyValue('--lcl-paper').trim()};
}
""" % CONTRASTE_MINIMO


@pytest.fixture(scope="module")
def app_no_ar():
    import capturar_telas as cap
    import requests

    campanha = json.loads((RAIZ / "scripts" / "temp.json").read_text(encoding="utf-8"))
    nome = campanha.get("name") or "Crônicas de Oakhaven"
    campanha["name"] = nome
    url, parar = cap._subir_servidor(campanha, nome)
    try:
        requests.post(f"{url}/__estado", json=copy.deepcopy(cap.CIDADE), timeout=10)
        yield url, nome, cap
    finally:
        parar()


def _abrir_no_tema(app_no_ar, tema):
    from playwright.sync_api import sync_playwright

    url, nome, cap = app_no_ar
    pw = sync_playwright().start()
    nav = pw.chromium.launch()
    ctx = nav.new_context(viewport={"width": 1440, "height": 980})
    ctx.add_init_script(cap._script_de_semente(nome, tema, cap.HISTORICO))
    pg = ctx.new_page()
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(f"{url}/game.html", wait_until="networkidle")
    cap._sanear(pg)
    pg.wait_for_timeout(600)

    def fechar():
        nav.close()
        pw.stop()

    return pg, erros, fechar


def _medir(pg, seletor, abrir):
    for _, outro, _ in TELAS:
        pg.evaluate(f"() => document.querySelector('{outro}')?.classList.add('hidden')")
    pg.evaluate(abrir)
    pg.wait_for_selector(f"{seletor}:not(.hidden)", timeout=8000)
    pg.wait_for_timeout(500)
    return pg.evaluate(MEDIR, seletor)


@pytest.mark.parametrize("tema", ["noite-tinta", "sangue-dragao", "floresta", "oceano", "pergaminho"])
def test_texto_legivel_em_todas_as_telas_novas(app_no_ar, tema):
    pg, erros, fechar = _abrir_no_tema(app_no_ar, tema)
    try:
        assert pg.evaluate("() => document.documentElement.dataset.theme") == tema
        problemas = {}
        for nome, seletor, abrir in TELAS:
            r = _medir(pg, seletor, abrir)
            assert r["medidos"] > 5, f"{nome}: a tela abriu sem texto ({r})"
            if r["ruins"]:
                problemas[nome] = r["ruins"][:5]
        assert not problemas, f"texto ilegível no tema {tema}: {problemas}"
        assert not erros, erros[:3]
    finally:
        fechar()


def _abrir_estado(app_no_ar, estado, tema):
    import requests

    url, _, cap = app_no_ar
    requests.post(f"{url}/__estado", json=estado, timeout=10)
    return _abrir_no_tema(app_no_ar, tema)


def _grimorio_com_nome_do_srd(pg):
    # O catálogo de teste só tem magias com nome em português, que não mostram
    # o nome do SRD. O que se mede é a cor da classe dentro do grimório: a
    # marca entra numa magia de verdade da lista, com o markup do grimoire.js.
    pg.evaluate("() => window.Grimoire._abrir('Helena')")
    pg.wait_for_selector("#grimoire-overlay .grm-magia-nome", timeout=8000)
    pg.evaluate("""() => document.querySelector('#grimoire-overlay .grm-magia-nome')
      .insertAdjacentHTML('afterend', '<span class="grm-magia-srd" title="Nome no SRD">Sacred Flame</span>')""")


def test_blocos_novos_das_telas_de_papel_fixo_no_tema_escuro(app_no_ar):
    """
    Combate, loja e grimório não seguem o tema: o papel é sempre claro. Os
    blocos acrescentados a elas (Ação Livre, Pechinchar, nome do SRD) usavam
    as variáveis do tema e, no escuro, pintavam texto claro no papel claro.
    """
    import capturar_telas as cap

    try:
        # (estado, tela, bloco novo, como abrir o bloco). O /__estado funde os
        # estados: o grimório vem antes, porque não abre com combate em curso.
        casos = [
            (cap.GRIMORIO, "#grimoire-overlay", ".grm-magia-srd", _grimorio_com_nome_do_srd),
            (cap.LOJA, "#shop-overlay", ".shp-pechinchar", None),
            (cap.COMBATE_ZONAS, "#combat-overlay", "#cbt-livre",
             lambda pg: pg.click("#cbt-buttons button:has-text('Ação Livre')")),
        ]
        for estado, overlay, alvo, preparar in casos:
            pg, erros, fechar = _abrir_estado(app_no_ar, copy.deepcopy(estado), "noite-tinta")
            try:
                if overlay != "#grimoire-overlay":
                    pg.wait_for_selector(f"{overlay}:not(.hidden)", timeout=10000)
                if preparar:
                    preparar(pg)
                pg.wait_for_selector(f"{alvo} >> nth=0", state="attached", timeout=8000)
                pg.wait_for_timeout(300)
                # Só o bloco novo: o resto da tela tem a paleta dela, igual em
                # todo tema, e não é o que este teste mede.
                r = pg.evaluate(MEDIR, alvo)
                assert r["medidos"] >= 1, (alvo, r)
                assert not r["ruins"], f"{alvo} no Noite de Tinta: {r['ruins'][:5]}"
                assert not erros, erros[:3]
            finally:
                fechar()
    finally:
        import requests
        requests.post(f"{app_no_ar[0]}/__estado", json=copy.deepcopy(cap.CIDADE), timeout=10)


def test_papel_segue_o_tema_e_o_pergaminho_nao_muda(app_no_ar):
    papeis = {}
    for tema in ("pergaminho", "noite-tinta"):
        pg, _, fechar = _abrir_no_tema(app_no_ar, tema)
        try:
            papeis[tema] = _medir(pg, "#local-overlay", TELAS[0][2])["papel"]
        finally:
            fechar()
    # O pergaminho é o padrão: as cores de sempre.
    assert papeis["pergaminho"] == "#fffbf0"
    # No escuro, o papel é a página do tema.
    assert papeis["noite-tinta"] != "#fffbf0"
