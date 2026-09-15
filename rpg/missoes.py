"""
missoes.py
Tela de missões ("O Livro de Missões"): todas as missões da campanha, as
ativas com objetivos marcáveis e as encerradas com o desfecho.

Antes elas apareciam só na barra lateral, e só as ativas: sem recompensa, sem
desfecho, sem o histórico do que o grupo já fez ou deixou de fazer.

Quem decide o que ACONTECEU na história continua sendo o mestre. Por isso:
  • o jogador pode marcar e desmarcar objetivos (é a lista de tarefas dele),
    mas cada marcação fica anotada e, ao fechar a tela, o mestre recebe UM
    aviso [MISSÕES ATUALIZADAS NA TELA] com o que mudou, para confirmar na
    narração ou desfazer com update_quest_objective;
  • o jogador pode ABANDONAR uma missão (é decisão do grupo), mas concluir e
    falhar ficam com o mestre, que é quem entrega (ou não) a recompensa;
  • com todos os objetivos feitos, a tela oferece "Falar com <quem deu>",
    que manda ao mestre a fala do jogador, como a ficha do local.
"""
from rpg import memory
from rpg import locais
from rpg import tools as tl

_ORDEM = {"ativa": 0, "concluida": 1, "falhou": 2, "abandonada": 3}


def _anotacoes() -> list[dict]:
    return memory.campaign.setdefault("missoes_mudadas_na_tela", [])


def _anotar(missao: dict, oque: str) -> None:
    lista = _anotacoes()
    chave = (missao["titulo"], oque.split(":", 1)[-1].strip())
    # Marcar e desmarcar o mesmo objetivo se cancelam: não vale avisar o mestre.
    oposta = None
    if oque.startswith("feito:"):
        oposta = "desfeito:" + chave[1]
    elif oque.startswith("desfeito:"):
        oposta = "feito:" + chave[1]
    for i, a in enumerate(lista):
        if a["missao"] == missao["titulo"] and a["mudanca"] == oposta:
            del lista[i]
            return
    lista.append({"missao": missao["titulo"], "mudanca": oque})


def _achar(quest: str) -> tuple[str, dict] | tuple[None, None]:
    """Pela chave ou pelo título sem caixa nem acento (ver tools._achar_missao)."""
    return tl._achar_missao(quest)


def _quem_deu(nome: str) -> dict | None:
    if not (nome or "").strip():
        return None
    chars = memory.campaign.get("characters") or {}
    ch = chars.get(memory.char_key(nome)) or next(
        (c for c in chars.values()
         if isinstance(c, dict) and locais.norm(c.get("name", "")) == locais.norm(nome)), None)
    return {"nome": (ch or {}).get("name", nome.strip()), "existe": bool(ch),
            "status": (ch or {}).get("status", "")}


def quest_snapshot() -> dict:
    """Estado das missões para a tela (JSON-serializável)."""
    missoes = []
    for chave, m in (memory.campaign.get("quests") or {}).items():
        if not isinstance(m, dict):
            continue
        objetivos = [{"indice": i, "texto": o.get("texto", ""), "feito": bool(o.get("feito"))}
                     for i, o in enumerate(m.get("objetivos") or []) if isinstance(o, dict)]
        feitos = sum(1 for o in objetivos if o["feito"])
        quem = _quem_deu(m.get("quem_deu", ""))
        status = m.get("status", "ativa")
        missoes.append({
            "chave": chave, "titulo": m.get("titulo", chave), "descricao": m.get("descricao", "") or "",
            "status": status, "objetivos": objetivos, "feitos": feitos, "total": len(objetivos),
            "quem_deu": quem, "recompensa": m.get("recompensa", "") or "",
            "cap_inicio": m.get("cap_inicio"), "cap_fim": m.get("cap_fim"),
            "desfecho": m.get("desfecho", "") or "",
            # Tudo feito e ainda ativa: o próximo passo é voltar a quem encomendou.
            "pronta_para_entregar": (status == "ativa" and bool(objetivos)
                                     and feitos == len(objetivos)),
        })
    missoes.sort(key=lambda x: (_ORDEM.get(x["status"], 9), -(x["cap_inicio"] or 0), x["titulo"]))
    contagem = {s: sum(1 for m in missoes if m["status"] == s) for s in _ORDEM}
    return {"missoes": missoes, "contagem": contagem,
            "mudancas_pendentes": len(_anotacoes())}


def quest_action(action: str, quest: str = "", objective: int = -1) -> dict:
    """
    Aplica UMA intenção da tela de missões.

    actions: marcar | desmarcar | abandonar | fechar
    `fechar` devolve em `recap` o aviso ao mestre (vazio sem mudanças) e limpa
    as anotações.
    """
    a = (action or "").lower().strip()

    def _resposta(ok, msg, **extra):
        return {"ok": ok, "message": msg, "snapshot": quest_snapshot(), **extra}

    if a == "fechar":
        anot = list(_anotacoes())
        memory.campaign["missoes_mudadas_na_tela"] = []
        memory.save_campaign()
        if not anot:
            return _resposta(True, "", recap="")
        linhas = []
        for x in anot:
            tipo, _, texto = x["mudanca"].partition(":")
            if tipo == "feito":
                linhas.append(f"marcou como feito '{texto}' ({x['missao']})")
            elif tipo == "desfeito":
                linhas.append(f"desmarcou '{texto}' ({x['missao']})")
            elif tipo == "abandonada":
                linhas.append(f"abandonou a missão '{x['missao']}'")
        recap = ("[MISSÕES ATUALIZADAS NA TELA] O jogador " + "; ".join(linhas) + ". "
                 "Isso é a lista de tarefas dele: se a narração confirma, siga; se algo "
                 "marcado ainda NÃO aconteceu na história, diga isso a ele e desfaça com "
                 "update_quest_objective(missão, objetivo, done=False). Não conclua missão "
                 "nem entregue recompensa por causa deste aviso.")
        return _resposta(True, "", recap=recap)

    if a not in ("marcar", "desmarcar", "abandonar"):
        return _resposta(False, f"Erro: Ação '{action}' desconhecida.")
    chave, missao = _achar(quest)
    if not missao:
        return _resposta(False, f"Erro: Missão '{quest}' não encontrada.")
    if missao.get("status") != "ativa":
        return _resposta(False, f"Aviso: '{missao['titulo']}' já está encerrada ({missao.get('status')}).")

    if a == "abandonar":
        # Pela chave gravada: complete_quest procura pela chave, e ela pode
        # não bater com o título (ver _achar).
        saida = tl.complete_quest(chave, "abandonada", "abandonada pelo grupo")
        if saida.startswith(("Aviso:", "Erro:")):
            return _resposta(False, saida)
        _anotar(missao, "abandonada:")
        memory.save_campaign()
        return _resposta(True, f"Missão '{missao['titulo']}' abandonada.")

    objetivos = missao.get("objetivos") or []
    try:
        i = int(objective)
    except (TypeError, ValueError):
        i = -1
    if not 0 <= i < len(objetivos):
        return _resposta(False, "Erro: Objetivo inválido.")
    # Pelo índice, e não por trecho de texto como update_quest_objective:
    # "Chegar" casaria com "Chegar a Luminas" e com "Chegar ao porto".
    obj = objetivos[i]
    feito = a == "marcar"
    if bool(obj.get("feito")) == feito:
        return _resposta(True, "")
    obj["feito"] = feito
    _anotar(missao, ("feito:" if feito else "desfeito:") + obj.get("texto", ""))
    memory.save_campaign()
    feitos = sum(1 for o in objetivos if o.get("feito"))
    msg = f"{obj.get('texto', '')}: {'feito' if feito else 'reaberto'} ({feitos}/{len(objetivos)})."
    return _resposta(True, msg)
