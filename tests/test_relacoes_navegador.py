"""
test_relacoes_navegador.py

A barra lateral fala a língua do gênero, e no romance o atalho do grupo abre
as Relações.

A barra dizia "Grupo" e "Missões" num romance, como se ele fosse uma aventura
de D&D. Agora cada gênero dá nome às telas ("Tramas", "Sobreviventes",
"Casos"), e no romance o coração do jogo — como cada pessoa se sente, em
afeto e confiança — tem tela própria.

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
                  "relacao_historico": [
                      {"eixo": "afeto", "delta": 30, "motivo": "Dividiram o guarda-chuva", "cap": 2},
                      {"eixo": "confianca", "delta": -30, "motivo": "Mentiu sobre a carta", "cap": 3},
                  ],
                  "estagio": "flerte",
                  "momentos": [
                      {"titulo": "O guarda-chuva dividido", "descricao": "Ele molhou o ombro inteiro",
                       "tipo": "momento", "cap": 2},
                      {"titulo": "Começou o flerte", "descricao": "O bilhete debaixo da porta",
                       "tipo": "estagio", "cap": 3},
                  ]},
        "rafael": {"name": "Rafael", "description": "O ex.", "status": "vivo",
                   "atitude": -20, "estagio": "rompimento", "estagio_antes": "namoro"},
        "marina": {"name": "Marina", "description": "Amiga de infância.", "status": "vivo",
                   "atitude": 70, "confianca": 60},
        "tomas": {"name": "Tomás", "description": "O professor de dança.", "status": "vivo",
                  "atitude": 30, "estagio": "flerte"},
        "helena": {"name": "Helena", "description": "A ex de Lucas.", "status": "vivo"},
    },
    "tensoes": {
        "helena|lucas": {"a": "Helena", "b": "Lucas", "tipo": "ciume", "intensidade": 55, "percebida": True,
                         "historico": [{"delta": 55, "motivo": "A cena no corredor", "cap": 3}], "cap": 3},
        # Ainda não percebida: nunca pode aparecer na tela.
        "lucas|marina": {"a": "Marina", "b": "Lucas", "tipo": "ciume", "intensidade": 30, "percebida": False,
                         "historico": [{"delta": 30, "motivo": "Marina escondeu o bilhete", "cap": 3}], "cap": 3},
    },
    "party": [{"name": "Lucas", "role": "interesse romântico"},
              {"name": "Marina", "role": "melhor amiga"}],
    "segredos": {
        "a bolsa em lisboa": {
            "titulo": "A bolsa em Lisboa", "descricao": "Aceitou a bolsa e vai embora em março",
            "dono": "", "escondido_de": ["Lucas"], "sabem": ["Marina"],
            "revelado": False, "como": "", "dono_sabe": True, "cap": 2,
            "historico": [{"acao": "contou", "quem": "Marina", "cap": 2}]},
        "o irmao na prisao": {
            "titulo": "O irmão na prisão", "descricao": "Visita o irmão todo domingo",
            "dono": "Lucas", "escondido_de": [], "sabem": [],
            "revelado": True, "como": "descobriu", "dono_sabe": False, "cap": 1, "cap_revelado": 3,
            "historico": [{"acao": "descobriu", "quem": "Clara", "cap": 3}]},
        # Ainda não revelado: nunca pode aparecer na tela.
        "o anel guardado": {
            "titulo": "O anel guardado", "descricao": "Comprou um anel e não teve coragem",
            "dono": "Lucas", "escondido_de": [], "sabem": [],
            "revelado": False, "como": "", "dono_sabe": True, "cap": 3, "historico": []},
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
    """Abre o jogo com um estado; devolve (página, erros)."""
    from playwright.sync_api import sync_playwright
    import requests

    url, nome, cap = app_no_ar
    with sync_playwright() as pw:
        nav = pw.chromium.launch()

        def abrir(estado, viewport=None):
            requests.post(f"{url}/__estado", json=copy.deepcopy(estado), timeout=10)
            ctx = nav.new_context(viewport=viewport or {"width": 1440, "height": 980})
            ctx.add_init_script(cap._script_de_semente(nome, "pergaminho", cap.HISTORICO))
            pg = ctx.new_page()
            erros = []
            pg.on("pageerror", lambda e: erros.append(str(e)))
            pg.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
            pg.goto(f"{url}/game.html", wait_until="networkidle")
            cap._sanear(pg)
            pg.wait_for_selector("#sb-atalhos .sb-atalho", timeout=8000)
            pg.wait_for_timeout(500)
            return pg, erros

        yield abrir
        nav.close()


def _atalhos(pg):
    return pg.eval_on_selector_all("#sb-atalhos .sb-atalho .sb-atalho-rotulo",
                                   "els => els.map(e => e.textContent.trim())")


def test_romance_tem_relacoes_tramas_e_lugares(jogo):
    pg, erros = jogo(ROMANCE)
    atalhos = _atalhos(pg)
    assert atalhos[:3] == ["Relações", "Tramas", "Lugares"], atalhos
    assert "Grupo" not in atalhos and "Missões" not in atalhos and "Mochila" not in atalhos
    assert not erros, erros[:3]


def test_barra_inferior_do_celular_tambem(jogo):
    pg, erros = jogo(ROMANCE, viewport={"width": 390, "height": 844})
    rotulos = pg.eval_on_selector_all("#barra-inferior .bi-rotulo", "els => els.map(e => e.textContent.trim())")
    assert rotulos[:3] == ["Relações", "Tramas", "Lugares"], rotulos
    assert not erros, erros[:3]


def test_relacoes_mostra_afeto_confianca_vinculo_e_o_porque(jogo):
    pg, erros = jogo(ROMANCE)
    pg.click("#sb-atalho-grupo")
    pg.wait_for_selector("#relacoes-overlay:not(.hidden) .rel-cartao", timeout=8000)
    assert "Clara" in pg.inner_text("#rel-sub")
    nomes = pg.eval_on_selector_all(".rel-cartao", "els => els.map(e => e.dataset.nome)")
    # Próximas primeiro, do afeto maior ao menor; a protagonista não entra.
    assert nomes[:2] == ["Marina", "Lucas"] and "Clara" not in nomes
    lucas = pg.locator(".rel-cartao[data-nome='Lucas']")
    texto = lucas.inner_text()
    assert "interesse romântico" in texto
    assert "afeição" in texto and "com um pé atrás" in texto
    assert "Mentiu sobre a carta" in texto and "cap. 3" in texto
    # A mudança mais recente em cima.
    assert texto.index("Mentiu sobre a carta") < texto.index("Dividiram o guarda-chuva")
    # A marca da confiança fica à esquerda do meio (negativa), a do afeto à direita.
    afeto = lucas.locator(".rel-afeto .psn-barra-marca").get_attribute("style")
    conf = lucas.locator(".rel-confianca .psn-barra-marca").get_attribute("style")
    assert "left:72.5%" in afeto and "left:35%" in conf
    assert not erros, erros[:3]


def test_nome_abre_a_ficha_com_a_relacao(jogo):
    pg, erros = jogo(ROMANCE)
    pg.evaluate("() => window.Relacoes._abrir()")
    pg.wait_for_selector(".rel-cartao[data-nome='Lucas'] .rel-nome", timeout=8000)
    pg.click(".rel-cartao[data-nome='Lucas'] .rel-nome")
    pg.wait_for_selector("#pessoa-overlay:not(.hidden)", timeout=8000)
    pg.wait_for_function("() => document.getElementById('psn-nome').textContent === 'Lucas'", timeout=8000)
    assert pg.inner_text("#psn-relacao-titulo") == "Relação com você"
    # Duas barras: afeto e confiança (a escada do estágio é outra coisa).
    assert pg.locator("#psn-relacao .psn-barra").count() == 2
    assert "Mentiu sobre a carta" in pg.inner_text("#psn-relacao")
    assert not erros, erros[:3]


def test_titulos_das_telas_no_romance(jogo):
    pg, erros = jogo(ROMANCE)
    pg.click("#sb-atalho-missoes")
    pg.wait_for_selector("#missoes-overlay:not(.hidden)", timeout=8000)
    assert pg.inner_text("#msn-titulo") == "As Tramas"
    pg.evaluate("() => window.Missoes._fechar()")
    pg.click("#sb-atalho-mapa")
    pg.wait_for_selector("#mapa-overlay:not(.hidden)", timeout=8000)
    assert pg.inner_text("#map-titulo") == "Os Lugares"
    assert not erros, erros[:3]


def test_horror_chama_o_grupo_de_sobreviventes(jogo, app_no_ar):
    cap = app_no_ar[2]
    estado = copy.deepcopy(cap.CIDADE)
    estado.update({"campaign_type": "horror", "dnd_mode": False})
    pg, erros = jogo(estado)
    atalhos = _atalhos(pg)
    assert atalhos[:2] == ["Sobreviventes", "Objetivos"], atalhos
    # O atalho do grupo continua abrindo o grupo, e o filtro dele tem o nome.
    pg.click("#sb-atalho-grupo")
    pg.wait_for_selector("#elenco-overlay:not(.hidden) .elc-filtro[data-filtro='grupo']", timeout=8000)
    assert pg.text_content(".elc-filtro[data-filtro='grupo']").strip().startswith("Sobreviventes")
    assert not erros, erros[:3]


def test_fantasia_com_regras_continua_como_era(jogo, app_no_ar):
    cap = app_no_ar[2]
    estado = copy.deepcopy(cap.CIDADE)
    estado.update({"campaign_type": "fantasia", "dnd_mode": True})
    pg, erros = jogo(estado)
    atalhos = _atalhos(pg)
    assert atalhos[:2] == ["Grupo", "Missões"] and "Mochila" in atalhos, atalhos
    assert not erros, erros[:3]


def test_cartao_mostra_o_estagio_e_o_ultimo_momento(jogo):
    pg, erros = jogo(ROMANCE)
    pg.evaluate("() => window.Relacoes._abrir()")
    pg.wait_for_selector(".rel-cartao[data-nome='Lucas'] .rel-escada", timeout=8000)
    lucas = pg.locator(".rel-cartao[data-nome='Lucas']")
    assert lucas.locator(".rel-estagio").inner_text() == "flerte"
    # Cinco degraus; cheios até o flerte (o terceiro).
    assert lucas.locator(".rel-segmento").count() == 5
    assert lucas.locator(".rel-segmento-cheio").count() == 3
    # text_content: o rótulo "Último momento de 2" é maiúsculo por CSS.
    ultimo = lucas.locator(".rel-ultimo").text_content()
    assert "Começou o flerte" in ultimo and "O guarda-chuva" not in ultimo
    assert "de 2" in ultimo
    # Marina nunca mudou de estágio: amizade, e nenhum momento ainda.
    marina = pg.locator(".rel-cartao[data-nome='Marina']")
    assert marina.locator(".rel-estagio").inner_text() == "amizade"
    assert marina.locator(".rel-ultimo").count() == 0
    assert not erros, erros[:3]


def test_rompimento_mostra_ate_onde_chegou(jogo):
    pg, erros = jogo(ROMANCE)
    pg.evaluate("() => window.Relacoes._abrir()")
    pg.wait_for_selector(".rel-cartao[data-nome='Rafael'] .rel-escada-rompida", timeout=8000)
    rafael = pg.locator(".rel-cartao[data-nome='Rafael']")
    assert rafael.locator(".rel-estagio").inner_text() == "rompimento (chegaram a namoro)"
    assert rafael.locator(".rel-segmento-cheio").count() == 4
    assert not erros, erros[:3]


def test_ficha_tem_a_linha_do_tempo_inteira(jogo):
    pg, erros = jogo(ROMANCE)
    pg.evaluate("() => window.Personagens._abrir('Lucas')")
    pg.wait_for_selector("#psn-relacao .rel-momentos", timeout=8000)
    titulos = pg.eval_on_selector_all("#psn-relacao .rel-momento-titulo", "els => els.map(e => e.textContent)")
    assert titulos == ["Começou o flerte", "O guarda-chuva dividido"]
    assert pg.locator("#psn-relacao .rel-momento-estagio").count() == 1
    assert "Ele molhou o ombro inteiro" in pg.inner_text("#psn-relacao")
    assert pg.locator("#psn-relacao .rel-estagio").inner_text() == "flerte"
    assert not erros, erros[:3]


def test_cartao_mostra_os_segredos_que_tocam_cada_pessoa(jogo):
    pg, erros = jogo(ROMANCE)
    pg.evaluate("() => window.Relacoes._abrir()")
    pg.wait_for_selector(".rel-cartao[data-nome='Lucas'] .rel-segs", timeout=8000)
    lucas = pg.locator(".rel-cartao[data-nome='Lucas'] .rel-segs").text_content()
    assert "Você esconde" in lucas and "A bolsa em Lisboa" in lucas
    assert "O irmão na prisão" in lucas and "não sabe que você sabe" in lucas
    marina = pg.locator(".rel-cartao[data-nome='Marina'] .rel-segs").text_content()
    assert "Sabe do seu" in marina and "A bolsa em Lisboa" in marina
    # O segredo que ainda não foi revelado não chega à tela.
    assert "O anel guardado" not in pg.content()
    assert not erros, erros[:3]


def test_aba_de_segredos(jogo):
    pg, erros = jogo(ROMANCE)
    pg.evaluate("() => window.Relacoes._abrir()")
    pg.wait_for_selector("#rel-abas .elc-filtro[data-aba='segredos']", timeout=8000)
    assert pg.text_content("#rel-abas .elc-filtro[data-aba='segredos'] .elc-filtro-conta") == "2"
    pg.click("#rel-abas .elc-filtro[data-aba='segredos']")
    pg.wait_for_selector(".rel-segredo", timeout=5000)
    seu = pg.locator(".rel-segredo[data-titulo='A bolsa em Lisboa']")
    texto = seu.text_content()
    assert "Escondido de" in texto and "Lucas" in texto
    assert "Marina — você contou" in " ".join(texto.split())
    assert "rel-segredo-escondido" in seu.get_attribute("class")
    outro = " ".join(pg.locator(".rel-segredo[data-titulo='O irmão na prisão']").text_content().split())
    assert "de Lucas" in outro and "você descobriu — Lucas não sabe que você sabe" in outro
    assert "O anel guardado" not in pg.content()
    # E volta para as pessoas.
    pg.click("#rel-abas .elc-filtro[data-aba='pessoas']")
    pg.wait_for_selector(".rel-cartao", timeout=5000)
    assert not erros, erros[:3]


def test_ficha_traz_os_segredos_da_pessoa(jogo):
    pg, erros = jogo(ROMANCE)
    pg.evaluate("() => window.Personagens._abrir('Lucas')")
    pg.wait_for_selector("#psn-relacao .rel-segs", timeout=8000)
    texto = pg.text_content("#psn-relacao .rel-segs")
    assert "A bolsa em Lisboa" in texto and "O irmão na prisão" in texto
    assert "O anel guardado" not in pg.content()
    assert not erros, erros[:3]


def test_barra_mostra_o_proximo_encontro_e_abre_a_ficha(jogo):
    pg, erros = jogo(ROMANCE)
    pg.wait_for_selector("#sb-encontro:not(.hidden)", timeout=8000)
    texto = " ".join(pg.text_content("#sb-encontro").split())
    assert "jantar com Lucas" in texto and "Dia 3, 18h" in texto and "Café Aurora" in texto and "em 4h" in texto
    # Faltam 4h: está perto, a barra avisa.
    assert "sb-encontro-alerta" in pg.get_attribute("#sb-encontro", "class")
    pg.click("#sb-encontro")
    pg.wait_for_function("() => document.getElementById('psn-nome')?.textContent === 'Lucas'", timeout=8000)
    assert "jantar" in pg.text_content("#psn-relacao .rel-encontros")
    assert not erros, erros[:3]


def test_cartao_mostra_o_encontro(jogo):
    pg, erros = jogo(ROMANCE)
    pg.evaluate("() => window.Relacoes._abrir()")
    pg.wait_for_selector(".rel-cartao[data-nome='Lucas'] .rel-encontro", timeout=8000)
    texto = " ".join(pg.text_content(".rel-cartao[data-nome='Lucas'] .rel-encontro").split())
    assert "jantar — Dia 3, 18h, Café Aurora (em 4h)" in texto
    assert not erros, erros[:3]


def test_gestos_mandam_a_fala_ao_mestre(jogo):
    pg, erros = jogo(ROMANCE)
    pg.evaluate("() => { window.__enviado = null; window.sendToAgent = async (t) => { window.__enviado = t; }; }")
    pg.evaluate("() => window.Personagens._abrir('Lucas')")
    pg.wait_for_selector("#psn-relacao .psn-gestos button", timeout=8000)
    rotulos = pg.eval_on_selector_all("#psn-relacao .psn-gestos button", "els => els.map(e => e.textContent.trim())")
    assert rotulos == ["Convidar para sair", "Marcar um encontro", "Dar um presente", "Pedir desculpas",
                       "Declarar-se", "Contar: A bolsa em Lisboa"]
    pg.click("#psn-relacao .psn-gestos button:has-text('Contar: A bolsa em Lisboa')")
    pg.wait_for_function("() => window.__enviado", timeout=5000)
    assert pg.evaluate("() => window.__enviado") == "Quero contar a Lucas sobre A bolsa em Lisboa."
    assert not erros, erros[:3]


def test_gestos_esperam_quem_esta_longe(jogo):
    pg, erros = jogo(ROMANCE)
    pg.evaluate("() => window.Personagens._abrir('Rafael')")
    pg.wait_for_selector("#psn-relacao .psn-gestos", timeout=8000)
    assert pg.locator("#psn-relacao .psn-gestos button:not([disabled])").count() == 0
    assert "Longe de você" in pg.text_content("#psn-relacao .psn-gestos")
    assert not erros, erros[:3]


def test_no_romance_as_telas_falam_de_voce_e_nao_do_grupo(jogo):
    """"O que o grupo sabe" num romance não fazia sentido; "com ele" supunha o gênero."""
    pg, erros = jogo(ROMANCE)
    pg.evaluate("() => window.Personagens._abrir('Lucas')")
    pg.wait_for_function("() => document.getElementById('psn-nome')?.textContent === 'Lucas'", timeout=8000)
    assert pg.inner_text("#psn-sabe-titulo") == "O que você sabe"
    assert pg.inner_text("#psn-cenas-titulo") == "Últimas cenas com Lucas"
    assert "Do seu círculo" in pg.inner_text("#psn-onde")
    pg.evaluate("() => window.Personagens._fechar()")
    pg.evaluate("() => window.Locais._abrir('')")
    pg.wait_for_selector("#local-overlay:not(.hidden) #lcl-selo", timeout=8000)
    pg.wait_for_timeout(300)
    assert "Você está aqui" in pg.inner_text("#lcl-selo")
    assert pg.inner_text("#lcl-onde") == "Onde você está"
    # "Com você" não lista a própria protagonista.
    com_voce = pg.inner_text("#lcl-grupo")
    assert "Lucas" in com_voce and "Clara" not in com_voce
    pg.evaluate("() => window.Locais._fechar()")
    pg.evaluate("() => window.Mapa._abrir('')")
    pg.wait_for_selector("#mapa-overlay:not(.hidden) .map-onde-rotulo", timeout=8000)
    assert pg.inner_text(".map-onde-rotulo") == "Você está em"
    pg.evaluate("() => window.Mapa._fechar()")
    pg.evaluate("() => window.Relacoes._abrir()")
    pg.wait_for_selector(".rel-cartao[data-nome='Lucas'] .lcl-marca-grupo", timeout=8000)
    assert pg.inner_text(".rel-cartao[data-nome='Lucas'] .lcl-marca-grupo") == "seu círculo"
    assert "grupo" not in pg.inner_text("#relacoes-overlay").lower()
    assert not erros, erros[:3]


def test_fora_do_romance_as_frases_continuam(jogo, app_no_ar):
    cap = app_no_ar[2]
    estado = copy.deepcopy(cap.CIDADE)
    estado.update({"campaign_type": "fantasia", "dnd_mode": True})
    pg, erros = jogo(estado)
    pg.evaluate("() => window.Personagens._abrir('Brom')")
    pg.wait_for_function("() => document.getElementById('psn-nome')?.textContent === 'Brom'", timeout=8000)
    assert pg.inner_text("#psn-sabe-titulo") == "O que o grupo sabe"
    assert pg.inner_text("#psn-cenas-titulo") == "Últimas cenas com Brom"
    assert not erros, erros[:3]


def test_aba_de_tensoes_e_triangulos(jogo):
    pg, erros = jogo(ROMANCE)
    pg.evaluate("() => window.Relacoes._abrir('tensoes')")
    pg.wait_for_selector(".rel-tensao", timeout=8000)
    # Uma tensão percebida e um triângulo (flerte com Lucas e com Tomás).
    assert pg.text_content("#rel-abas .elc-filtro[data-aba='tensoes'] .elc-filtro-conta") == "2"
    tensao = " ".join(pg.locator(".rel-tensao[data-par='Helena × Lucas']").text_content().split())
    assert "ciúme" in tensao and "tensão aberta" in tensao and "A cena no corredor" in tensao
    assert "rel-tensao-forte" in pg.get_attribute(".rel-tensao[data-par='Helena × Lucas']", "class")
    tri = " ".join(pg.locator(".rel-triangulo").text_content().split())
    assert "Você entre Lucas e Tomás" in tri and "flerte com Lucas" in tri
    # O ciúme que a protagonista não percebeu não chega à tela.
    assert "Marina escondeu o bilhete" not in pg.content()
    assert "Marina × Lucas" not in pg.content()
    assert not erros, erros[:3]


def test_cartao_mostra_a_tensao_com_a_outra_ponta(jogo):
    pg, erros = jogo(ROMANCE)
    pg.evaluate("() => window.Relacoes._abrir()")
    pg.wait_for_selector(".rel-cartao[data-nome='Lucas'] .rel-tensoes", timeout=8000)
    lucas = " ".join(pg.text_content(".rel-cartao[data-nome='Lucas'] .rel-tensoes").split())
    assert "Tensão com Helena" in lucas and "ciúme, tensão aberta" in lucas
    assert "Marina" not in lucas
    assert not erros, erros[:3]
