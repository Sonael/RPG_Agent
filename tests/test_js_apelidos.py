"""
test_js_apelidos.py

Cada tela exporta as funções num objeto com apelido (window.Combat = {
_act: act, ... }). Por dentro do módulo o nome é o original; o apelido só
existe no objeto. Chamar o apelido por dentro lança ReferenceError, que
some no console.

Foi o que deixou o botão Mover do combate sem efeito desde a onda 3:
_mover chamava _act(...). Este teste lê os módulos de static/js e acusa
qualquer chamada, por dentro, a um apelido que não foi definido no escopo.
"""
import re
from pathlib import Path

JS = Path(__file__).resolve().parent.parent / "static" / "js"


def _chamadas_a_apelidos(texto: str) -> list[str]:
    apelidos = set(re.findall(r"\b(_[A-Za-z]\w*)\s*:\s*(?:[A-Za-z]\w*|\()", texto))
    achadas = []
    linhas = texto.splitlines()
    for apelido in sorted(apelidos):
        definido = re.search(rf"function\s+{apelido}\s*\(|(?:const|let|var)\s+{apelido}\b", texto)
        if definido:
            continue
        for m in re.finditer(rf"(?<![.\w]){apelido}\s*\(", texto):
            n = texto.count("\n", 0, m.start()) + 1
            achadas.append(f"{n}: {linhas[n - 1].strip()[:120]}")
    return achadas


def test_o_detector_pega_o_bug_do_mover():
    velho = """
      function act(p) {}
      function _mover(z) { _act({ action: 'move', target: z }); }
      window.Combat = { _mover, _act: act };
    """
    assert _chamadas_a_apelidos(velho) == ["3: function _mover(z) { _act({ action: 'move', target: z }); }"]


def test_nenhuma_tela_chama_um_apelido_por_dentro():
    problemas = {f.name: _chamadas_a_apelidos(f.read_text(encoding="utf-8"))
                 for f in sorted(JS.glob("*.js"))}
    problemas = {k: v for k, v in problemas.items() if v}
    assert not problemas, problemas
