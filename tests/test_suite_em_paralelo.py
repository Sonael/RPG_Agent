"""
test_suite_em_paralelo.py

A suíte levava ~17 minutos parada. Agora leva ~2min30.

Quase tudo é teste de tela: cada um abre game.html num Chromium e espera a
rede sossegar. Medido num arquivo típico: 23 testes em 76 segundos — 1,9 s de
preparo e 1,5 s de execução por teste, e isso não encurta sem perder o que
eles provam.

O QUE RESOLVEU: `-n 8 --dist loadfile` (pytest.ini). Cada ARQUIVO inteiro
dentro de um worker, que é o modo que preserva o que a suíte já assume —
fixture de escopo de módulo (o servidor Flask de cada arquivo), ordem dentro
do arquivo, e a porta de rede, escolhida livre por processo. Quatro arquivos
de tela que levavam 76 s cada passaram a terminar juntos em 69 s.

O QUE FOI TENTADO E DESFEITO: compartilhar UM Chromium entre todos os testes,
trocando `sync_playwright` por um atalho para o navegador que já estava de pé.
Duas razões para ter voltado atrás:

  • o ganho era pequeno perto do da paralelização — 76 s → 68 s no mesmo
    arquivo, cerca de 10%;
  • o Playwright síncrono roda o próprio laço de eventos na THREAD PRINCIPAL,
    via greenlet, e quem o deixa de pé quebra `asyncio.run()` em todo teste
    que vier depois no mesmo worker. Três testes caíram assim, com
    "asyncio.run() cannot be called from a running event loop" — e a causa
    ficava a arquivos de distância de quem a criou.

O Chromium por teste é desperdício conhecido e medido. Trocá-lo por um defeito
que aparece longe da causa não é troca boa.

`-n 8` e não `auto`: cada worker carrega um Chromium e um Flask, e `auto` abre
um por núcleo — numa máquina de 20 núcleos são 20 navegadores disputando 8 GB.
"""
import configparser
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def _addopts():
    cfg = configparser.ConfigParser()
    cfg.read(RAIZ / "pytest.ini", encoding="utf-8")
    return cfg["pytest"]["addopts"]


def test_a_suite_continua_configurada_para_rodar_em_paralelo():
    addopts = _addopts()
    assert "--dist loadfile" in addopts, (
        "sem loadfile, os testes de um mesmo arquivo se espalham entre workers "
        "e a fixture de módulo (o servidor Flask) sobe várias vezes"
    )
    assert "-n " in addopts, "sem -n a suíte volta a rodar em série"


def test_o_plugin_esta_declarado_para_quem_for_instalar():
    """`-n` no pytest.ini sem o xdist instalado quebra a suíte inteira no
    primeiro comando: o pytest não entende a opção e nem coleta."""
    dev = (RAIZ / "requirements-dev.txt").read_text(encoding="utf-8")
    assert "pytest-xdist" in dev


def test_a_suite_nao_compartilha_o_navegador_entre_testes():
    """
    Ver o cabeçalho: o Playwright síncrono deixa um laço de eventos rodando na
    thread principal, e mantê-lo de pé derruba `asyncio.run()` nos testes
    seguintes do mesmo worker — longe de onde o laço nasceu.
    """
    conftest = (RAIZ / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert "sync_playwright" not in conftest, (
        "a conftest voltou a mexer no sync_playwright; ver o cabeçalho deste "
        "arquivo antes de tentar de novo"
    )
