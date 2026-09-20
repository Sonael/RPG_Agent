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
  • o jogador pode EDITAR a missão (título, descrição, recompensa, quem
    encomendou e a lista de objetivos) e CRIAR missão própria — é o caderno
    dele. Cada edição entra no mesmo aviso ao mestre, que corrige na narração
    se a história disser outra coisa;
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


def _texto_limpo(valor, limite: int) -> str:
    return " ".join(str(valor or "").split())[:limite]


def _titulo_repetido(titulo: str, menos: str = "") -> bool:
    alvo = locais.norm(titulo)
    for chave, m in (memory.campaign.get("quests") or {}).items():
        if chave == menos or not isinstance(m, dict):
            continue
        if locais.norm(m.get("titulo", chave)) == alvo:
            return True
    return False


# Os campos que o jogador edita. O status não está aqui: concluir e falhar
# são do mestre, e abandonar tem ação própria.
CAMPOS_EDITAVEIS = {"titulo": 120, "descricao": 600, "recompensa": 200, "quem_deu": 80}


def quest_action(action: str, quest: str = "", objective: int = -1,
                 text: str = "", fields: dict | None = None) -> dict:
    """
    Aplica UMA intenção da tela de missões.

    actions: marcar | desmarcar | abandonar | fechar | nova | editar |
             objetivo_novo | objetivo_texto | objetivo_remover | objetivo_mover
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
            elif tipo == "criou":
                linhas.append(f"criou a missão '{x['missao']}'")
            elif tipo == "campo":
                linhas.append(f"mudou {texto} em '{x['missao']}'")
            elif tipo == "obj_novo":
                linhas.append(f"acrescentou o objetivo '{texto}' em '{x['missao']}'")
            elif tipo == "obj_texto":
                linhas.append(f"reescreveu um objetivo como '{texto}' em '{x['missao']}'")
            elif tipo == "obj_removido":
                linhas.append(f"removeu o objetivo '{texto}' de '{x['missao']}'")
            elif tipo == "obj_movido":
                linhas.append(f"mudou a ordem dos objetivos de '{x['missao']}'")
        recap = ("[MISSÕES ATUALIZADAS NA TELA] O jogador " + "; ".join(linhas) + ". "
                 "Isso é a lista de tarefas dele: se a narração confirma, siga; se algo "
                 "marcado ainda NÃO aconteceu na história, diga isso a ele e desfaça com "
                 "update_quest_objective(missão, objetivo, done=False). Não conclua missão "
                 "nem entregue recompensa por causa deste aviso.")
        return _resposta(True, "", recap=recap)

    if a == "nova":
        campos = fields if isinstance(fields, dict) else {}
        titulo = _texto_limpo(campos.get("titulo") or quest, CAMPOS_EDITAVEIS["titulo"])
        if not titulo:
            return _resposta(False, "Erro: A missão precisa de um título.")
        if _titulo_repetido(titulo):
            return _resposta(False, f"Erro: Já existe uma missão chamada '{titulo}'.")
        saida = tl.add_quest(
            titulo,
            _texto_limpo(campos.get("descricao"), CAMPOS_EDITAVEIS["descricao"]),
            _texto_limpo(campos.get("objetivos"), 600),
            giver=_texto_limpo(campos.get("quem_deu"), CAMPOS_EDITAVEIS["quem_deu"]),
            reward=_texto_limpo(campos.get("recompensa"), CAMPOS_EDITAVEIS["recompensa"]),
        )
        if saida.startswith(("Aviso:", "Erro:")):
            return _resposta(False, saida)
        _, nova = _achar(titulo)
        if nova:
            # Nasceu na tela, não na narração: o mestre precisa saber.
            nova["origem"] = "jogador"
            _anotar(nova, "criou:")
        memory.save_campaign()
        return _resposta(True, f"Missão '{titulo}' criada.", criada=titulo)

    if a not in ("marcar", "desmarcar", "abandonar", "editar", "objetivo_novo",
                 "objetivo_texto", "objetivo_remover", "objetivo_mover"):
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

    if a == "editar":
        campos = fields if isinstance(fields, dict) else {}
        mudou = []
        for campo, limite in CAMPOS_EDITAVEIS.items():
            if campo not in campos:
                continue
            novo = _texto_limpo(campos.get(campo), limite)
            if campo == "titulo":
                if not novo:
                    return _resposta(False, "Erro: A missão precisa de um título.")
                if _titulo_repetido(novo, menos=chave):
                    return _resposta(False, f"Erro: Já existe uma missão chamada '{novo}'.")
            if novo == (missao.get(campo) or ""):
                continue
            # O título muda no campo, não na chave: as ferramentas do mestre
            # acham a missão pelos dois (tools._achar_missao).
            antigo = missao.get(campo) or ""
            missao[campo] = novo
            mudou.append((campo, antigo, novo))
        if not mudou:
            return _resposta(True, "")
        for campo, antigo, novo in mudou:
            if campo == "titulo":
                _anotar(missao, f"campo:o título (era '{antigo}')")
            else:
                rotulo = {"descricao": "a descrição", "recompensa": "a recompensa",
                          "quem_deu": "quem encomendou"}[campo]
                _anotar(missao, f"campo:{rotulo}")
        memory.save_campaign()
        return _resposta(True, "Missão atualizada.")

    if a == "objetivo_novo":
        texto = _texto_limpo(text, 200)
        if not texto:
            return _resposta(False, "Erro: O objetivo precisa de um texto.")
        objetivos = missao.setdefault("objetivos", [])
        if any(locais.norm(o.get("texto", "")) == locais.norm(texto) for o in objetivos):
            return _resposta(False, f"Aviso: '{texto}' já está na lista.")
        objetivos.append({"texto": texto, "feito": False})
        _anotar(missao, "obj_novo:" + texto)
        memory.save_campaign()
        return _resposta(True, f"Objetivo '{texto}' acrescentado.")

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

    if a == "objetivo_texto":
        texto = _texto_limpo(text, 200)
        if not texto:
            return _resposta(False, "Erro: O objetivo precisa de um texto.")
        if texto == obj.get("texto"):
            return _resposta(True, "")
        obj["texto"] = texto
        _anotar(missao, "obj_texto:" + texto)
        memory.save_campaign()
        return _resposta(True, "Objetivo reescrito.")

    if a == "objetivo_remover":
        texto = obj.get("texto", "")
        del objetivos[i]
        _anotar(missao, "obj_removido:" + texto)
        memory.save_campaign()
        return _resposta(True, f"Objetivo '{texto}' removido.")

    if a == "objetivo_mover":
        passo = -1 if str(text or "").strip().lower() in ("cima", "-1", "antes") else 1
        j = i + passo
        if not 0 <= j < len(objetivos):
            return _resposta(True, "")
        objetivos[i], objetivos[j] = objetivos[j], objetivos[i]
        _anotar(missao, "obj_movido:")
        memory.save_campaign()
        return _resposta(True, "Ordem dos objetivos mudada.")

    feito = a == "marcar"
    if bool(obj.get("feito")) == feito:
        return _resposta(True, "")
    obj["feito"] = feito
    _anotar(missao, ("feito:" if feito else "desfeito:") + obj.get("texto", ""))
    memory.save_campaign()
    feitos = sum(1 for o in objetivos if o.get("feito"))
    msg = f"{obj.get('texto', '')}: {'feito' if feito else 'reaberto'} ({feitos}/{len(objetivos)})."
    return _resposta(True, msg)
