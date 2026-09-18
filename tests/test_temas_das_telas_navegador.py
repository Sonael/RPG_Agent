"""
test_temas_das_telas_navegador.py

As telas novas (ficha do local, do personagem, do herói, grupo, missões,
mapa, diário, elenco), o combate, a loja e o grimório seguem o tema
escolhido.

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
  // rgb(...) vem de 0 a 255; o color-mix sai como color(srgb ...), de 0 a 1.
  const rgb = (s) => {
    const n = (s.match(/[\\d.]+/g) || []).map(Number);
    return s.startsWith('color(srgb') ? n.map((v, i) => i < 3 ? v * 255 : v) : n;
  };
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


# (estado, tela, variável do papel, título, como abrir). O /__estado funde os
# estados: o grimório vem antes, porque não abre com combate em curso.
TELAS_DE_REGRA = [
    ("GRIMORIO", "#grimoire-overlay", "--grm-paper", ".grm-title", _grimorio_com_nome_do_srd),
    ("LOJA", "#shop-overlay", "--shp-paper", ".shp-title", None),
    ("COMBATE_ZONAS", "#combat-overlay", "--cbt-paper", ".cbt-title",
     lambda pg: pg.click("#cbt-buttons button:has-text('Ação Livre')")),
]


@pytest.mark.parametrize("tema", ["noite-tinta", "sangue-dragao", "floresta", "oceano", "pergaminho"])
def test_combate_loja_e_grimorio_seguem_o_tema(app_no_ar, tema):
    """
    Combate, loja e grimório tinham papel claro fixo e seguem o tema agora,
    como as telas novas. O combate é aberto com o painel de Ação Livre e o
    grimório com um nome do SRD, os blocos mais recentes de cada tela.

    No pergaminho só se confere que o papel é o de sempre: lá os separadores
    dourados (›, →, "Vs.") ficam como sempre foram, decorativos.
    """
    import capturar_telas as cap
    import requests

    try:
        for estado, overlay, papel, titulo, preparar in TELAS_DE_REGRA:
            pg, erros, fechar = _abrir_estado(app_no_ar, copy.deepcopy(getattr(cap, estado)), tema)
            try:
                if overlay != "#grimoire-overlay":
                    pg.wait_for_selector(f"{overlay}:not(.hidden)", timeout=10000)
                if preparar:
                    preparar(pg)
                pg.wait_for_timeout(500)
                cor = pg.evaluate(
                    "([o, v]) => getComputedStyle(document.querySelector(o)).getPropertyValue(v).trim()",
                    [overlay, papel])
                if tema == "pergaminho":
                    assert cor == "#fffbf0", (overlay, cor)
                    continue
                assert cor != "#fffbf0", f"{overlay} ignorou o tema {tema}"
                # O destaque é a tinta do tema nas três telas. O combate e a
                # loja usavam o vermelho da paleta antiga, que no Floresta virava
                # marrom e deixava a tela com cara de pergaminho.
                titulo_cor, tinta = pg.evaluate(
                    """([o, t]) => {
                      const i = document.createElement('i');
                      i.style.color = 'var(--ink-user)';
                      document.body.append(i);
                      const tinta = getComputedStyle(i).color;
                      i.remove();
                      return [getComputedStyle(document.querySelector(o + ' ' + t)).color, tinta];
                    }""", [overlay, titulo])
                assert titulo_cor == tinta, f"{titulo} no tema {tema}: {titulo_cor} e não {tinta}"
                r = pg.evaluate(MEDIR, overlay)
                assert r["medidos"] > 10, (overlay, r)
                assert not r["ruins"], f"{overlay} no tema {tema}: {r['ruins'][:6]}"
                assert not erros, erros[:3]
            finally:
                fechar()
    finally:
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
