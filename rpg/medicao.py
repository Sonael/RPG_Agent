"""
medicao.py
Uma linha por turno, para saber se o esquecimento diminuiu.

POR QUE EXISTE
──────────────
A medição de uma campanha de 91 turnos mostrou que 10 das 72 mensagens
digitadas pelo jogador eram cobrança de registro ("adicione Ravenrust ao
mapa", "salve o personagem torbin", "atualize a hora") — um de cada sete
turnos dele. O retrato do banco não mostrava isso: mostrava tudo registrado,
porque o jogador pagou por isso.

Agora cada turno deixa uma linha em campanhas/medicao.jsonl com o que foi
chamado, o que o fechamento registrou e se o jogador precisou cobrar. É o
número que diz se o fechamento do turno funcionou — e é o mesmo número antes
e depois, que é o que permite comparar.

NÃO muda o jogo: falha em silêncio, não levanta exceção, e sai do caminho
com MEDICAO_DESLIGADA=1.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from rpg import memory

ARQUIVO = Path(os.environ.get(
    "MEDICAO_ARQUIVO",
    Path(__file__).resolve().parent.parent / "campanhas" / "medicao.jsonl"))

# O jogador cobrando o que o mestre devia ter feito sozinho. São os padrões
# achados nas mensagens reais da campanha medida.
_COBRANCAS = {
    "hora": re.compile(r"\b(atualiz\w+ (?:a )?hora|avanc\w+ (?:o )?tempo|adiant\w+ (?:o )?rel[oó]gio"
                       r"|passa\w* (?:o )?tempo)", re.I),
    "local": re.compile(r"\b(adicion\w+|salv\w+|registr\w+|coloc\w+)\b[^.]{0,40}"
                        r"\b(no mapa|ao mapa|local|lugar)", re.I),
    "personagem": re.compile(r"\b(salv\w+|registr\w+|adicion\w+|cri\w+)\b[^.]{0,40}"
                             r"\b(personagem|npc|ficha)", re.I),
    "missao_diario": re.compile(r"\b(atualiz\w+|salv\w+|registr\w+|anot\w+)\b[^.]{0,40}"
                                r"\b(miss[ãa]o|di[áa]rio|resumo|evento|cap[íi]tulo)", re.I),
    "teste": re.compile(r"\b(fa[çc]a (?:um )?teste|pede (?:um )?teste|quero rolar)", re.I),
    "generica": re.compile(r"\b(voc[êe] esqueceu|esqueceu de|n[ãa]o atualizou|faltou (?:salvar|registrar))", re.I),
}


def cobrancas_do_jogador(texto: str) -> list[str]:
    """Quais cobranças a mensagem do jogador contém (lista vazia = nenhuma)."""
    if not texto or texto.strip().startswith("["):      # veio de tela, não é cobrança
        return []
    return [nome for nome, rx in _COBRANCAS.items() if rx.search(texto)]


# ── O encontro sugerido e o encontro que aconteceu ────────────────────────
# Na partida medida, o sistema calculou o orçamento de XP e ofereceu três
# opções balanceadas — e o mestre criou os próprios cultistas por fora. Antes
# de OBRIGAR alguma coisa, é preciso saber se foi uma vez ou se é a regra.
# Estas duas funções só anotam; quem decide continua sendo o mestre.

def _caderno() -> dict:
    return memory.campaign.setdefault("_encontro", {})


def registrar_sugestao(nomes, orcamento=0) -> None:
    try:
        _caderno().update({"sugeridos": [str(n) for n in (nomes or []) if n],
                           "orcamento": int(orcamento or 0),
                           "turno": memory.turno_atual()})
    except Exception:
        pass


def registrar_inimigo(nome: str) -> None:
    try:
        criados = _caderno().setdefault("criados", [])
        if nome and str(nome) not in criados:
            criados.append(str(nome))
    except Exception:
        pass


def _encontro_do_turno() -> dict:
    """
    O que houve de encontro neste turno, esvaziando o que já foi contado — a
    sugestão fica de pé (ela pode ser seguida no turno seguinte), o que foi
    criado não.
    """
    try:
        caderno = _caderno()
        criados = list(caderno.get("criados") or [])
        caderno["criados"] = []
        if not criados and "sugeridos" not in caderno:
            return {}
        sugeridos = [s.lower() for s in (caderno.get("sugeridos") or [])]
        seguiu = None
        if criados and sugeridos:
            seguiu = any(any(s in c.lower() or c.lower() in s for s in sugeridos)
                         for c in criados)
        return {"sugeridos": caderno.get("sugeridos") or [],
                "criados": criados,
                "seguiu": seguiu,
                "turno_da_sugestao": caderno.get("turno")}
    except Exception:
        return {}


def registrar_turno(mensagem_do_jogador: str, ferramentas, registro: dict) -> None:
    if os.environ.get("MEDICAO_DESLIGADA"):
        return
    try:
        linha = {
            "quando": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "campanha": memory.campaign.get("name", ""),
            "turno": memory.turno_atual(),
            "de_tela": bool((mensagem_do_jogador or "").strip().startswith("[")),
            "cobrancas": cobrancas_do_jogador(mensagem_do_jogador),
            "ferramentas": sorted(ferramentas or []),
            "fechamento": {
                "tinha_bloco": bool(registro.get("tinha_bloco")),
                "campos": {k: len(v) for k, v in (registro.get("campos") or {}).items()},
                "feitos": registro.get("feitos") or [],
                "recusados": registro.get("recusados") or [],
            },
        }
        encontro = _encontro_do_turno()
        if encontro:
            linha["encontro"] = encontro
        ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
        with ARQUIVO.open("a", encoding="utf-8") as saida:
            saida.write(json.dumps(linha, ensure_ascii=False) + "\n")
    except Exception:
        pass        # medir nunca pode atrapalhar quem está jogando


def resumo(caminho: Path | None = None) -> dict:
    """Os números acumulados, para o relatório. Arquivo ausente = tudo zero."""
    arq = Path(caminho or ARQUIVO)
    turnos = []
    if arq.exists():
        for linha in arq.read_text(encoding="utf-8").splitlines():
            try:
                turnos.append(json.loads(linha))
            except ValueError:
                continue
    digitados = [t for t in turnos if not t.get("de_tela")]
    com_cobranca = [t for t in digitados if t.get("cobrancas")]
    com_bloco = [t for t in turnos if (t.get("fechamento") or {}).get("tinha_bloco")]
    feitos = sum(len((t.get("fechamento") or {}).get("feitos") or []) for t in turnos)
    recusados = sum(len((t.get("fechamento") or {}).get("recusados") or []) for t in turnos)
    # Encontros: de todas as vezes em que inimigos entraram na mesa, quantas
    # vieram do encontro que o sistema tinha acabado de sugerir.
    com_inimigo = [t for t in turnos if (t.get("encontro") or {}).get("criados")]
    julgados = [t for t in com_inimigo if (t.get("encontro") or {}).get("seguiu") is not None]
    seguiram = [t for t in julgados if t["encontro"]["seguiu"]]
    return {
        "turnos": len(turnos),
        "digitados": len(digitados),
        "turnos_com_cobranca": len(com_cobranca),
        "porcentagem_de_cobranca": round(100 * len(com_cobranca) / len(digitados), 1) if digitados else 0.0,
        "turnos_com_bloco": len(com_bloco),
        "porcentagem_com_bloco": round(100 * len(com_bloco) / len(turnos), 1) if turnos else 0.0,
        "registros_feitos": feitos,
        "registros_recusados": recusados,
        "turnos_com_inimigo_novo": len(com_inimigo),
        "turnos_com_sugestao_na_mesa": len(julgados),
        "seguiram_a_sugestao": len(seguiram),
        "porcentagem_que_seguiu": round(100 * len(seguiram) / len(julgados), 1) if julgados else 0.0,
    }
