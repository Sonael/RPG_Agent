"""
epilogo.py
O que mudou na cena, anotado DEPOIS de narrar.

POR QUE EXISTE
──────────────
O mestre chamava as ferramentas ANTES de escrever a narração. Para registrar
um lugar novo ele precisava prever o que estava prestes a narrar — e no
momento da chamada o fato ainda não existe. Resultado medido numa campanha de
91 turnos: 10 das 72 mensagens digitadas pelo jogador foram para cobrar
registro ("adicione Ravenrust ao mapa", "salve o personagem torbin",
"atualize a hora"). Um de cada sete turnos dele.

Agora a resposta termina com um bloco escondido, que o jogador não vê:

    [[registro]]
    local: Ponte Quebrada
    tempo: 2h — viagem pela trilha
    lugar: Ponte Quebrada (dentro de: Vale de Oakhaven) — tábuas podres
    gente: Aldric — ferreiro da vila
    fato: ponte_atravessada=sim
    [[/registro]]

Escrever isso é continuar escrevendo texto, na ordem natural (narra, depois
anota), e são CINCO nomes de campo para lembrar em vez de 117 ferramentas.
Quem chama a ferramenta é o servidor, aqui, com regras que dão para testar.

O QUE O SERVIDOR NÃO ACEITA
  • Nome que não aparece na narração do turno — a mesma trava dos avisos:
    sem evidência no texto, não vira registro.
  • Mais do que o teto por turno (3 lugares, 3 pessoas, 2 fatos).
  • O que já está igual na memória: não regrava.
  • Dado, vida, XP e combate NÃO passam por aqui. Isso continua sendo
    ferramenta antes da narração, porque o resultado muda o que se narra.
"""

from __future__ import annotations

import re
import unicodedata

from rpg import memory

ABRE = "[[registro]]"
FECHA = "[[/registro]]"

# Tolerante: cerca de markdown em volta, espaço sobrando, caixa trocada.
_BLOCO_RE = re.compile(
    r"`{0,3}\s*\[\[\s*registro\s*\]\]\s*(.*?)\s*\[\[\s*/\s*registro\s*\]\]\s*`{0,3}",
    re.IGNORECASE | re.DOTALL,
)

CAMPOS = ("local", "tempo", "lugar", "gente", "fato", "relacao")
# Como o campo aparece ESCRITO no bloco: a leitura tira o acento, o prompt não.
ESCRITO = {"relacao": "relação"}
TETO = {"lugar": 3, "gente": 3, "fato": 2, "local": 1, "tempo": 1, "relacao": 2}

# "Helena → Selene -20 — odiou o controle velado"
# "Selene ↔ Sonael +30 — amigos de infância"
_RELACAO_RE = re.compile(
    r"^\s*(?P<a>[^→↔<>-]+?)\s*(?P<seta>→|↔|->|<->|<-->)\s*(?P<b>.+?)\s*"
    r"(?P<delta>[+-]\s*\d{1,3})\s*(?:[—–:]|\s-\s)?\s*(?P<motivo>.*)$"
)
# Uma cena não vira ódio em amor: o passo de um turno tem teto.
PASSO_MAXIMO = 30

# O nome do campo aceita acento: "relação:" é o que o mestre escreve, e
# [a-z] deixava a linha inteira de fora sem dizer por quê.
_LINHA_RE = re.compile(r"^\s*[-*•]?\s*([A-Za-zÀ-ÿ]+)\s*:\s*(.+?)\s*$")
# "2h — viagem", "2 horas: viagem", "3h de caminhada"
_TEMPO_RE = re.compile(r"^\s*(\d{1,2})\s*(?:h|hs|hora|horas)?\b\s*[—–:-]?\s*(.*)$", re.IGNORECASE)
# "Ponte Quebrada (dentro de: Vale) — tábuas podres"
_DENTRO_RE = re.compile(r"\((?:dentro\s+de|em)\s*:?\s*(.+?)\)", re.IGNORECASE)
_FATO_RE = re.compile(r"^\s*([\w ]+?)\s*=\s*(.+?)\s*$")


def _norm(texto: str) -> str:
    sem = unicodedata.normalize("NFD", str(texto or ""))
    sem = "".join(c for c in sem if unicodedata.category(c) != "Mn")
    return " ".join(sem.lower().split())


def extrair(texto: str) -> tuple[str, dict[str, list[str]]]:
    """
    Devolve (narração sem o bloco, campos). Sem bloco, campos vem vazio.

    O bloco sai do texto ANTES de qualquer coisa: ele não vai para a tela nem
    para o histórico da conversa.
    """
    campos: dict[str, list[str]] = {}
    achado = _BLOCO_RE.search(texto or "")
    if not achado:
        return (texto or "").strip(), campos

    for linha in achado.group(1).splitlines():
        m = _LINHA_RE.match(linha)
        if not m:
            continue
        campo, valor = _norm(m.group(1)), m.group(2).strip()
        campo = {"lugares": "lugar", "pessoas": "gente", "pessoa": "gente",
                 "npc": "gente", "hora": "tempo", "fatos": "fato",
                 "relacoes": "relacao", "relacionamento": "relacao"}.get(campo, campo)
        if campo not in CAMPOS or not valor or valor in ("-", "—", "nenhum", "nada"):
            continue
        campos.setdefault(campo, []).append(valor)

    limpo = (texto[:achado.start()] + texto[achado.end():]).strip()
    return limpo, campos


def _tem_evidencia(nome: str, narracao: str) -> bool:
    """O nome precisa aparecer na narração do turno. Sem isso, não registra."""
    n = _norm(nome)
    if not n:
        return False
    texto = _norm(narracao)
    if n in texto:
        return True
    # "Ponte Quebrada" vale se a narração disse "a Ponte Quebrada, de tábuas":
    # todas as palavras grandes do nome aparecem.
    palavras = [p for p in n.split() if len(p) >= 4]
    return bool(palavras) and all(p in texto for p in palavras)


def _ja_existe(colecao: str, nome: str) -> bool:
    alvo = _norm(nome)
    for chave, item in (memory.campaign.get(colecao) or {}).items():
        if alvo == _norm(chave) or alvo == _norm((item or {}).get("name", "")):
            return True
    return False


def _partes(valor: str) -> tuple[str, str]:
    """"Aldric — ferreiro da vila" → ("Aldric", "ferreiro da vila")."""
    for sep in ("—", "–", " - ", ":"):
        if sep in valor:
            nome, _, desc = valor.partition(sep)
            return nome.strip(" -—–:"), desc.strip()
    return valor.strip(), ""


def aplicar(campos: dict[str, list[str]], narracao: str) -> dict:
    """
    Chama as ferramentas que o bloco pediu, com as travas.

    Devolve o que foi feito e o que foi recusado, para o log de medição e
    para os testes — nada aqui levanta exceção: epílogo torto não derruba o
    turno, no máximo não registra.
    """
    from rpg import tools as tl
    from rpg import tools_dnd as td

    feitos: list[str] = []
    recusados: list[str] = []

    def recusa(campo, valor, porque):
        recusados.append(f"{campo}={valor!r}: {porque}")

    # ---- local atual ------------------------------------------------------
    for valor in campos.get("local", [])[:TETO["local"]]:
        nome = _partes(valor)[0]
        if not _tem_evidencia(nome, narracao):
            recusa("local", nome, "não aparece na narração")
            continue
        if _norm(nome) == _norm(memory.campaign.get("current_location", "")):
            continue
        try:
            tl.update_world_state(current_location=nome)
            feitos.append(f"update_world_state(current_location={nome!r})")
        except Exception as e:                                   # nunca derruba o turno
            recusa("local", nome, f"falhou: {e}")

    # ---- tempo ------------------------------------------------------------
    for valor in campos.get("tempo", [])[:TETO["tempo"]]:
        m = _TEMPO_RE.match(valor)
        if not m:
            recusa("tempo", valor, "não dá para ler as horas")
            continue
        horas = int(m.group(1))
        if not 1 <= horas <= 24:
            recusa("tempo", valor, "fora de 1 a 24 horas")
            continue
        motivo = m.group(2).strip() or "o tempo da cena"
        try:
            td.advance_time(horas, motivo)
            feitos.append(f"advance_time({horas}, {motivo!r})")
        except Exception as e:
            recusa("tempo", valor, f"falhou: {e}")

    # ---- lugar novo -------------------------------------------------------
    for valor in campos.get("lugar", [])[:TETO["lugar"]]:
        dentro = ""
        m = _DENTRO_RE.search(valor)
        if m:
            dentro = m.group(1).strip()
            valor = _DENTRO_RE.sub("", valor)
        nome, desc = _partes(valor)
        if not _tem_evidencia(nome, narracao):
            recusa("lugar", nome, "não aparece na narração")
            continue
        if _ja_existe("locations", nome):
            continue
        try:
            tl.save_location(nome, desc or "Descrito em cena.", dentro_de=dentro)
            feitos.append(f"save_location({nome!r})")
        except Exception as e:
            recusa("lugar", nome, f"falhou: {e}")

    # ---- gente nova -------------------------------------------------------
    for valor in campos.get("gente", [])[:TETO["gente"]]:
        nome, desc = _partes(valor)
        if not _tem_evidencia(nome, narracao):
            recusa("gente", nome, "não aparece na narração")
            continue
        if _ja_existe("characters", nome):
            continue
        try:
            tl.save_character(nome, desc or "Apareceu em cena.",
                              local=memory.campaign.get("current_location", ""))
            feitos.append(f"save_character({nome!r})")
        except Exception as e:
            recusa("gente", nome, f"falhou: {e}")

    # ---- relação entre duas pessoas ---------------------------------------
    # Sem ferramenta nova para o mestre, de propósito: a mesa dele já tem 117
    # e a lição medida é que ferramenta a mais é ferramenta esquecida. Aqui a
    # relação é uma linha de texto, como o resto do fechamento.
    from rpg import entre as _entre

    for valor in campos.get("relacao", [])[:TETO["relacao"]]:
        m = _RELACAO_RE.match(valor)
        if not m:
            recusa("relacao", valor, "use 'Fulano → Beltrano ±N — motivo'")
            continue
        a, b = _partes(m.group("a"))[0], _partes(m.group("b"))[0]
        delta = int(m.group("delta").replace(" ", ""))
        if not (_tem_evidencia(a, narracao) and _tem_evidencia(b, narracao)):
            recusa("relacao", f"{a} → {b}", "os dois nomes precisam aparecer na narração")
            continue
        if abs(delta) > PASSO_MAXIMO:
            recusa("relacao", f"{a} → {b}", f"passo maior que {PASSO_MAXIMO} num turno só")
            continue
        motivo = (m.group("motivo") or "").strip(" —–:-")
        mutua = m.group("seta") in ("↔", "<->", "<-->")
        try:
            for de, para in ([(a, b), (b, a)] if mutua else [(a, b)]):
                resposta = _entre.ajustar(de, para, delta, motivo)
                if str(resposta).startswith("Erro:"):
                    recusa("relacao", f"{de} → {para}", resposta[6:].strip())
                else:
                    feitos.append(f"relacao({de!r}→{para!r},{delta:+d})")
        except Exception as e:
            recusa("relacao", f"{a} → {b}", f"falhou: {e}")

    # ---- fato do mundo ----------------------------------------------------
    for valor in campos.get("fato", [])[:TETO["fato"]]:
        m = _FATO_RE.match(valor)
        if not m:
            recusa("fato", valor, "use chave=valor")
            continue
        chave = "_".join(_norm(m.group(1)).split())
        try:
            tl.set_flag(chave, m.group(2).strip())
            feitos.append(f"set_flag({chave!r})")
        except Exception as e:
            recusa("fato", valor, f"falhou: {e}")

    if feitos:
        memory.save_campaign()
    return {"feitos": feitos, "recusados": recusados}


def processar(texto: str) -> tuple[str, dict]:
    """
    O caminho inteiro: tira o bloco do texto, aplica o que ele pediu e devolve
    (narração limpa, relatório). Usado pelo servidor a cada turno.
    """
    limpo, campos = extrair(texto)
    relatorio = {"tinha_bloco": bool(campos) or ABRE.strip("[]") in (texto or "").lower(),
                 "campos": campos, "feitos": [], "recusados": []}
    if campos:
        relatorio.update(aplicar(campos, limpo))
    return limpo, relatorio
