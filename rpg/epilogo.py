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

CAMPOS = ("local", "tempo", "lugar", "gente", "fato", "relacao", "cena",
          "capitulo", "diario")
# Como o campo aparece ESCRITO no bloco: a leitura tira o acento, o prompt não.
ESCRITO = {"relacao": "relação", "capitulo": "capítulo", "diario": "diário"}
TETO = {"lugar": 3, "gente": 3, "fato": 2, "local": 1, "tempo": 1, "relacao": 2,
        "cena": 1, "capitulo": 1, "diario": 1}

# "Helena → Selene -20 — odiou o controle velado"
# "Selene ↔ Sonael +30 — amigos de infância"
# O sinal é opcional porque "Selene → Helena 0 — não notou nada" é uma linha
# legítima: ela declara que ESTE lado não mudou, e é assim que o mestre faz um
# sentimento valer só de um lado.
_RELACAO_RE = re.compile(
    r"^\s*(?P<a>[^→↔<>-]+?)\s*(?P<seta>→|↔|->|<->|<-->)\s*(?P<b>.+?)\s*"
    r"(?P<delta>[+-]?\s*\d{1,3})\s*(?:[—–:]|\s-\s)?\s*(?P<motivo>.*)$"
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
                 "relacoes": "relacao", "relacionamento": "relacao",
                 "evento": "cena", "acontecimento": "cena",
                 "cap": "capitulo"}.get(campo, campo)
        if campo not in CAMPOS or not valor or valor in ("-", "—", "nenhum", "nada"):
            continue
        campos.setdefault(campo, []).append(valor)

    limpo = (texto[:achado.start()] + texto[achado.end():]).strip()
    return limpo, campos


def _tem_evidencia(nome: str, narracao: str) -> bool:
    """
    O nome precisa aparecer na narração do turno. Sem isso, não registra — é
    o que impede o bloco de virar porta para inventar gente e lugar que a
    história não teve.

    "APARECER" NÃO É "COINCIDIR". A primeira medição real mostrou o custo de
    exigir o nome inteiro: três dos cinco registros recusados eram o nome
    completo do bloco contra a forma curta da cena —

        bloco:    gente: Mestre Alquimista Faelar
        narração: "Atrás do balcão, o velho Faelar ergue os olhos."

    Perder esse registro é pior do que aceitar um nome um pouco inflado: o
    mestre está batizando o que ACABOU de narrar. Basta uma palavra distinta
    do nome aparecer na cena.
    """
    n = _norm(nome)
    if not n:
        return False
    texto = _norm(narracao)

    palavras = [p for p in n.split() if len(p) >= 4]
    if not palavras:
        # Nome curto ("Pip", "Bo"): só vale inteiro e como palavra, senão
        # "Pip" se daria por citado numa cena que falou de uma pipa.
        return bool(re.search(rf"\b{re.escape(n)}\b", texto))

    if n in texto:
        return True
    # As palavras de peso primeiro: "Torre do Mago Sombrio" não se dá por
    # citada só porque a cena tinha um mago.
    grandes = [p for p in palavras if len(p) >= 5]
    return any(re.search(rf"\b{re.escape(p)}", texto) for p in (grandes or palavras))


def _quem_aparece(narracao: str, limite: int = 6) -> list[str]:
    """
    Os personagens conhecidos citados nesta narração. É o que faz o
    acontecimento aparecer na ficha de cada um deles ("últimas cenas com…").
    """
    achados = []
    for ch in (memory.campaign.get("characters") or {}).values():
        nome = (ch or {}).get("name", "")
        if nome and _tem_evidencia(nome, narracao):
            achados.append(nome)
        if len(achados) >= limite:
            break
    return achados


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
    # O que o JOGADOR precisa ver no chat. `feitos` é log de motor
    # ("relacao('Helena'→'Selene',+25)"); aqui vai a frase dele.
    avisos: list[str] = []

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
        # "0h — ajuste de laços" é o mestre dizendo que a cena não gastou
        # tempo. Isso não é erro: é a resposta certa para uma conversa de dois
        # minutos. Era recusado e entrava na conta de registro falhado.
        if horas == 0:
            continue
        if horas > 24:
            recusa("tempo", valor, "mais de 24 horas num turno só")
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

    # Uma relação é DAS DUAS pessoas: o que muda entre elas muda para as duas.
    # Antes, "Selene → Helena +25" deixava a ficha de Helena vazia, e o jogador
    # que fez as duas se elogiarem via a relação só de um lado — parecia bug,
    # e era. Cada linha passa a mexer nos dois sentidos.
    #
    # O lado avesso continua possível, e é o que explica o caso que deu origem
    # a tudo isto ("Helena odiou a sugestão de Selene", sem Selene notar):
    # basta o mestre escrever a OUTRA direção na mesma lista, com o número
    # dela. Uma direção escrita à mão nunca é sobrescrita pelo espelho.
    romance = (memory.campaign.get("campaign_type") or "") == "romance"
    protagonista = _norm(memory.campaign.get("protagonist", "") or "")

    def _na_cena(nome: str) -> bool:
        # O protagonista está SEMPRE na cena, e o mestre escreve "você" no
        # lugar do nome dele metade do tempo. Cobrar o nome dele na narração
        # recusaria a relação mais importante do jogo.
        return (protagonista and _norm(nome) == protagonista) or _tem_evidencia(nome, narracao)

    linhas = []
    for valor in campos.get("relacao", [])[:TETO["relacao"]]:
        m = _RELACAO_RE.match(valor)
        if not m:
            recusa("relacao", valor, "use 'Fulano → Beltrano ±N — motivo'")
            continue
        a, b = _partes(m.group("a"))[0], _partes(m.group("b"))[0]
        delta = int(m.group("delta").replace(" ", ""))
        if not (_na_cena(a) and _na_cena(b)):
            recusa("relacao", f"{a} → {b}", "os dois nomes precisam aparecer na narração")
            continue
        if abs(delta) > PASSO_MAXIMO:
            recusa("relacao", f"{a} → {b}", f"passo maior que {PASSO_MAXIMO} num turno só")
            continue
        linhas.append((a, b, delta, (m.group("motivo") or "").strip(" —–:-")))

    escritas = {(_norm(a), _norm(b)) for a, b, _, _ in linhas}

    for a, b, delta, motivo in linhas:
        # No ROMANCE, a relação com o protagonista tem casa própria: afeto e
        # confiança (rpg/relacoes.py), que é o que a tela de Relações mostra.
        # Escrever isso em entre.py criaria dois números para a mesma coisa,
        # em dois lugares, nenhum sabendo do outro. O fechamento entrega na
        # casa certa; o mestre não precisa escolher.
        if romance and protagonista and protagonista in (_norm(a), _norm(b)):
            outro = b if _norm(a) == protagonista else a
            if not delta:
                continue
            try:
                from rpg import relacoes as _relacoes
                resposta = _relacoes.ajustar(outro, afeto=delta, motivo=motivo)
            except Exception as e:
                recusa("relacao", f"{a} → {b}", f"falhou: {e}")
                continue
            if "não encontrado" in resposta or resposta.startswith(("Informe", "Nada")):
                recusa("relacao", outro, resposta)
            else:
                feitos.append(f"ajustar_relacao({outro!r},afeto={delta:+d})")
                avisos.append(resposta)
            continue

        # O espelho só entra quando o mestre NÃO escreveu a volta.
        espelhar = (_norm(b), _norm(a)) not in escritas
        try:
            antes = _entre.valor_entre(a, b)
            resposta = _entre.ajustar(a, b, delta, motivo)
            if str(resposta).startswith("Erro:"):
                recusa("relacao", f"{a} → {b}", resposta[6:].strip())
                continue
            feitos.append(f"relacao({a!r}→{b!r},{delta:+d})")

            if espelhar:
                volta = _entre.ajustar(b, a, delta, motivo)
                if not str(volta).startswith("Erro:"):
                    feitos.append(f"relacao({b!r}→{a!r},{delta:+d})")

            # A relação é a única coisa do fechamento que o jogador PROVOCA de
            # propósito ("fiz as duas se elogiarem"). Ela mudava em silêncio, e
            # a mudança de atitude sempre avisou — parecia que nada aconteceu.
            depois = _entre.valor_entre(a, b)
            entre_os_dois = f"{a} e {b}" if espelhar else f"{a} → {b}"
            avisos.append(f"{entre_os_dois}: {antes:+d} → {depois:+d} "
                          f"({_entre.faixa(depois)})" + (f" — {motivo}" if motivo else ""))
        except Exception as e:
            recusa("relacao", f"{a} → {b}", f"falhou: {e}")

    # ---- a cena que virou acontecimento -----------------------------------
    # Medido na campanha de 91 turnos: 3 eventos e 4 entradas de diário. A
    # linha do tempo é o que a ficha do personagem, a do local e o bloco de
    # cena leem para lembrar o que já houve — vazia, o mestre repete encontros
    # e esquece consequências.
    for valor in campos.get("cena", [])[:TETO["cena"]]:
        resumo, consequencia = _partes(valor)
        if len(resumo) < 12:
            recusa("cena", valor, "resumo curto demais para virar acontecimento")
            continue
        try:
            tl.save_event(resumo,
                          characters_involved=", ".join(_quem_aparece(narracao)),
                          location=memory.campaign.get("current_location", ""),
                          consequence=consequencia)
            feitos.append(f"save_event({resumo[:40]!r})")
        except Exception as e:
            recusa("cena", resumo, f"falhou: {e}")

    # ---- a página do diário -----------------------------------------------
    # Medido: 4 entradas em 91 turnos. O diário é o que o jogador abre para
    # lembrar a própria história, e ele nascia vazio porque add_diary_entry
    # era mais uma ferramenta para lembrar no meio da cena.
    for valor in campos.get("diario", [])[:TETO["diario"]]:
        titulo, conteudo = _partes(valor)
        if not conteudo:
            titulo, conteudo = (titulo[:60], titulo) if len(titulo) >= 25 else (titulo, "")
        if len(conteudo) < 25:
            recusa("diario", valor, "página curta demais: escreva 'Título — o que aconteceu'")
            continue
        try:
            tl.add_diary_entry(titulo or conteudo[:50], conteudo)
            feitos.append(f"add_diary_entry({(titulo or conteudo)[:40]!r})")
        except Exception as e:
            recusa("diario", titulo, f"falhou: {e}")

    # ---- virada de capítulo -----------------------------------------------
    # O capítulo ficou em 1 durante 91 turnos. Só o passo seguinte é aceito:
    # capítulo é numeração de história, não campo livre.
    for valor in campos.get("capitulo", [])[:TETO["capitulo"]]:
        m = re.search(r"\d{1,3}", valor)
        if not m:
            recusa("capitulo", valor, "escreva só o número do capítulo novo")
            continue
        novo = int(m.group(0))
        atual = int(memory.campaign.get("chapter", 1) or 1)
        if novo == atual:
            continue
        if novo != atual + 1:
            recusa("capitulo", valor, f"o capítulo vai de {atual} para {atual + 1}, um de cada vez")
            continue
        try:
            tl.update_world_state(chapter=novo)
            feitos.append(f"update_world_state(chapter={novo})")
        except Exception as e:
            recusa("capitulo", valor, f"falhou: {e}")

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
    return {"feitos": feitos, "recusados": recusados, "avisos": avisos}


def processar(texto: str) -> tuple[str, dict]:
    """
    O caminho inteiro: tira o bloco do texto, aplica o que ele pediu e devolve
    (narração limpa, relatório). Usado pelo servidor a cada turno.
    """
    limpo, campos = extrair(texto)
    relatorio = {"tinha_bloco": bool(campos) or ABRE.strip("[]") in (texto or "").lower(),
                 "campos": campos, "feitos": [], "recusados": [], "avisos": []}
    if campos:
        relatorio.update(aplicar(campos, limpo))
    return limpo, relatorio
