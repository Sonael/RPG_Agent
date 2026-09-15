"""
diario.py
O diário como livro: um capítulo por página, com o que aconteceu nele.

O diário era uma lista de entradas na barra lateral que abria um modal de
edição, e os eventos da linha do tempo não apareciam em lugar nenhum da tela.
Para reler a campanha o jogador exportava um .md.

Aqui cada capítulo junta as entradas do diário daquele capítulo e o que se
liga a elas: os eventos registrados no capítulo, os personagens e os locais
citados (nos eventos e no texto das entradas) e as missões que começaram ou
terminaram ali. Tudo vem do que já está gravado; nada é inferido além de
casar nomes conhecidos no texto.

Evento gravado antes de save_event guardar o capítulo não tem como ser
datado: fica em "sem capítulo", e o jogador pode pô-lo no capítulo certo.
"""

from __future__ import annotations

import re

from rpg import memory
from rpg.locais import norm


def _capitulo(valor, padrao: int | None = None) -> int | None:
    """Capítulo gravado como 2 ou "2" (JSON importado). Inválido vira o padrão."""
    try:
        n = int(str(valor).strip())
        return n if n > 0 else padrao
    except (TypeError, ValueError):
        return padrao


def _separar_nomes(texto: str) -> list[str]:
    partes = re.split(r"[,;]| e ", texto or "")
    return [p.strip() for p in partes if p.strip()]


def _cita_no_texto(texto_normalizado: str, nome: str) -> bool:
    alvo = norm(nome)
    if len(alvo) < 3:
        return False
    return re.search(rf"(?<!\w){re.escape(alvo)}(?!\w)", texto_normalizado) is not None


def _personagens_conhecidos() -> dict[str, dict]:
    return {norm(c.get("name", "")): c for c in (memory.campaign.get("characters") or {}).values()
            if isinstance(c, dict) and c.get("name")}


def _locais_conhecidos() -> list[str]:
    nomes = [l.get("name", "") for l in (memory.campaign.get("locations") or {}).values()
             if isinstance(l, dict)]
    nomes += [l.get("nome", "") for l in (memory.campaign.get("lojas") or {}).values()
              if isinstance(l, dict)]
    return [n for n in nomes if n]


def _evento(e: dict, conhecidos: dict) -> dict:
    pessoas = []
    for nome in _separar_nomes(e.get("characters_involved", "")):
        ch = conhecidos.get(norm(nome))
        pessoas.append({"nome": ch.get("name") if ch else nome, "tem_ficha": bool(ch)})
    return {
        "index": _capitulo(e.get("index"), 0),
        "resumo": e.get("summary", "") or "",
        "local": e.get("location", "") or "",
        "consequencia": e.get("consequence", "") or "",
        "personagens": pessoas,
    }


def _ligacoes(entradas: list[dict], eventos: list[dict], conhecidos: dict,
              locais_nomes: list[str]) -> tuple[list[dict], list[str]]:
    """Personagens e locais do capítulo, os mais citados primeiro."""
    texto = norm(" ".join(f"{x['titulo']} {x['conteudo']}" for x in entradas))
    contagem: dict[str, int] = {}
    ordem: list[str] = []

    def contar(nome: str, vezes: int = 1):
        if nome not in contagem:
            contagem[nome] = 0
            ordem.append(nome)
        contagem[nome] += vezes

    for ev in eventos:
        for p in ev["personagens"]:
            if p["tem_ficha"]:
                contar(p["nome"])
    for chave, ch in conhecidos.items():
        vezes = len(re.findall(rf"(?<!\w){re.escape(chave)}(?!\w)", texto)) if len(chave) >= 3 else 0
        if vezes:
            contar(ch["name"], vezes)

    personagens = []
    for nome in sorted(ordem, key=lambda n: (-contagem[n], ordem.index(n))):
        ch = conhecidos.get(norm(nome)) or {}
        personagens.append({"nome": nome, "status": ch.get("status", "") or "vivo",
                            "do_grupo": bool(memory.is_party_member(ch)) if ch else False,
                            "citacoes": contagem[nome]})

    lugares: list[str] = []
    for ev in eventos:
        if ev["local"] and ev["local"] not in lugares:
            lugares.append(ev["local"])
    for nome in locais_nomes:
        if nome not in lugares and _cita_no_texto(texto, nome):
            lugares.append(nome)
    return personagens, lugares


def _missoes_do_capitulo(numero: int) -> list[dict]:
    saida = []
    for m in (memory.campaign.get("quests") or {}).values():
        if not isinstance(m, dict):
            continue
        titulo = m.get("titulo") or ""
        if _capitulo(m.get("cap_inicio")) == numero:
            saida.append({"titulo": titulo, "status": m.get("status", ""), "marco": "começou"})
        if _capitulo(m.get("cap_fim")) == numero and m.get("status") != "ativa":
            marco = {"concluida": "concluída", "falhou": "falhou",
                     "abandonada": "abandonada"}.get(m.get("status", ""), "terminou")
            saida.append({"titulo": titulo, "status": m.get("status", ""), "marco": marco})
    return saida


def diary_snapshot() -> dict:
    """O livro inteiro: capítulos em ordem, com entradas e ligações (JSON-serializável)."""
    camp = memory.campaign
    atual = _capitulo(camp.get("chapter"), 1)
    diario = [d for d in (camp.get("diary") or []) if isinstance(d, dict)]
    eventos = [e for e in (camp.get("events") or []) if isinstance(e, dict)]
    conhecidos = _personagens_conhecidos()
    locais_nomes = _locais_conhecidos()

    numeros = {atual}
    numeros |= {_capitulo(d.get("chapter"), 1) for d in diario}
    numeros |= {n for n in (_capitulo(e.get("chapter")) for e in eventos) if n}

    capitulos = []
    for numero in sorted(numeros):
        entradas = [{"indice": i, "titulo": d.get("title", "") or "", "conteudo": d.get("content", "") or ""}
                    for i, d in enumerate(camp.get("diary") or [])
                    if isinstance(d, dict) and _capitulo(d.get("chapter"), 1) == numero]
        evs = [_evento(e, conhecidos) for e in eventos if _capitulo(e.get("chapter")) == numero]
        personagens, lugares = _ligacoes(entradas, evs, conhecidos, locais_nomes)
        capitulos.append({
            "numero": numero,
            "titulo": entradas[0]["titulo"] if entradas else "",
            "atual": numero == atual,
            "entradas": entradas,
            "eventos": evs,
            "personagens": personagens,
            "locais": lugares,
            "missoes": _missoes_do_capitulo(numero),
        })

    return {
        "campanha": camp.get("name", "") or "",
        "capitulo_atual": atual,
        "capitulos": capitulos,
        "eventos_sem_capitulo": [_evento(e, conhecidos) for e in eventos if not _capitulo(e.get("chapter"))],
        "total_entradas": len(diario),
    }


def mover_evento(index, capitulo) -> dict:
    """Põe um evento (pelo número dele) num capítulo. {ok, message}."""
    alvo = _capitulo(index)
    numero = _capitulo(capitulo)
    if not alvo or not numero:
        return {"ok": False, "message": "Erro: informe o evento e um capítulo maior que zero."}
    for e in memory.campaign.get("events") or []:
        if isinstance(e, dict) and _capitulo(e.get("index")) == alvo:
            e["chapter"] = numero
            memory.save_campaign()
            return {"ok": True, "message": f"Evento #{alvo} agora está no capítulo {numero}."}
    return {"ok": False, "message": f"Erro: evento #{alvo} não encontrado."}
