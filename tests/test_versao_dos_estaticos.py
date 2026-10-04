"""
test_versao_dos_estaticos.py

As páginas carregam os scripts com "?v=", e o service worker responde
/static/* do cache pela URL inteira. O ?v= era subido à mão, e o esquecimento
voltou: depois da atualização da loja, a primeira carga servia o shop.js
velho, que lia um campo que o servidor já não mandava, e todo preço saía
"undefined po". O servidor agora troca o ?v= por um resumo do conteúdo.
"""
import hashlib
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture
def cliente():
    import server
    return server.app.test_client()


def _sha(rel: str) -> str:
    return hashlib.sha1((RAIZ / "static" / rel).read_bytes()).hexdigest()[:10]


@pytest.mark.parametrize("pagina", ["/", "/login.html", "/menu.html", "/game.html"])
def test_todo_script_e_estilo_sai_com_a_versao_do_conteudo(cliente, pagina):
    html = cliente.get(pagina).get_data(as_text=True)
    refs = re.findall(r'/static/([\w./\-]+\.(?:js|css))\?v=([\w.\-]+)', html)
    assert refs, "a página não carrega nada com ?v="
    for rel, versao in refs:
        assert versao == _sha(rel), f"{rel}: ?v={versao}, o conteúdo é {_sha(rel)}"


def test_a_loja_sai_com_a_versao_dela(cliente):
    html = cliente.get("/game.html").get_data(as_text=True)
    assert f"/static/js/shop.js?v={_sha('js/shop.js')}" in html


def test_mudou_o_arquivo_mudou_a_url(tmp_path, monkeypatch):
    import server
    (tmp_path / "js").mkdir()
    arquivo = tmp_path / "js" / "x.js"
    arquivo.write_text("let a = 1;", encoding="utf-8")
    monkeypatch.setattr(server, "_STATIC_DIR", str(tmp_path))
    monkeypatch.setattr(server, "_versoes_lidas", {})
    antes = server._com_versoes('<script src="/static/js/x.js?v=3"></script>')
    arquivo.write_text("let a = 2; // mudou", encoding="utf-8")
    depois = server._com_versoes('<script src="/static/js/x.js?v=3"></script>')
    assert antes != depois and "?v=3" not in antes


def test_arquivo_que_nao_existe_fica_como_estava(cliente):
    import server
    html = '<script src="/static/js/nao-existe.js?v=7"></script>'
    assert server._com_versoes(html) == html


def test_o_service_worker_trocou_de_cache():
    """O SW novo apaga, ao ativar, o cache com as cópias velhas."""
    sw = (RAIZ / "static" / "sw.js").read_text(encoding="utf-8")
    assert 'const CACHE = "rpg-agent-v2"' not in sw
    assert "podarVersoesAntigas(cache, url)" in sw
