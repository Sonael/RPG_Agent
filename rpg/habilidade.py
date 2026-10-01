"""
habilidade.py
Uma habilidade, do jeito que a TELA precisa mostrar — lida das mesmas funções
que o motor usa para resolvê-la.

POR QUE EXISTE
──────────────
A tela tática montava o botão de cada habilidade direto da ficha: o campo
`dado` cru, e a descrição só no `title` (aparece ao passar o mouse — no toque,
não existe). O motor, enquanto isso, rolava `dado_efetivo()`, lia a área do
texto e escolhia os alvos por outro caminho. Os dois discordavam:

  • Infligir Ferimentos aparecia SEM DADO na tela e rolava 3d10 no motor;
  • no celular não havia como saber se a magia causava dano ou curava;
  • a mesma Chama Sagrada aparecia duas vezes ("Truque Bônus (Chamas
    Sagradas)" é a mesma magia, ganha por uma característica de subclasse);
  • e uma magia que só fere criaturas HOSTIS atingiu aliados, sem que nada
    na tela avisasse quem estava na área.

Aqui cada habilidade vira um registro, montado a partir das MESMAS funções do
motor (tools_dnd: dado_efetivo, efeito_do_dado, area_da_habilidade,
alvos_da_habilidade...), que por sua vez consultam o compêndio do SRD
primeiro. Tela e motor deixam de discordar por construção.
"""

from __future__ import annotations

from rpg import compendio

TIPO_DANO_PT = {
    "acid": "ácido", "bludgeoning": "concussão", "cold": "frio", "fire": "fogo",
    "force": "força", "lightning": "elétrico", "necrotic": "necrótico",
    "piercing": "perfurante", "poison": "veneno", "psychic": "psíquico",
    "radiant": "radiante", "slashing": "cortante", "thunder": "trovejante",
}
SIGLA = {"forca": "FOR", "destreza": "DES", "constituicao": "CON",
         "inteligencia": "INT", "sabedoria": "SAB", "carisma": "CAR"}

# Rótulo curto do efeito, que vira a etiqueta colorida do cartão.
ROTULO_EFEITO = {
    "dano": "Dano", "cura": "Cura", "condicao": "Controle", "pool": "Controle",
    "bonus": "Reforço", "buff": "Reforço", "invocacao": "Invocação",
    "utilidade": "Utilidade", "nenhum": "Utilidade", "passiva": "Passiva",
}


def chave_canonica(hab: dict) -> str:
    """
    A identidade de uma habilidade para tirar duplicatas: o nome do SRD
    quando ela é do SRD, senão o nome desembrulhado e normalizado.
    """
    nome = (hab or {}).get("nome", "")
    srd = (compendio.magia((hab or {}).get("nome_srd") or "")
           or compendio.magia(nome))
    if srd:
        return "magia:" + srd["chave"]
    # Característica é deduplicada pelo NOME EXATO, nunca pela "mãe". A busca
    # do compêndio cai em "Canalizar Divindade" quando não conhece "Canalizar
    # Divindade (Radiância do Amanhecer)" — e a primeira versão tratou as duas
    # como cópia, sumindo justamente com o efeito usado em combate.
    return "ficha:" + compendio.norm(compendio.desembrulhar(nome))


def sem_duplicatas(habs: list) -> list:
    """
    A lista sem a mesma habilidade duas vezes — fica a primeira. A ficha da
    Selene tinha "Chamas Sagradas" e "Truque Bônus (Chamas Sagradas)".
    """
    vistas, saida = set(), []
    for h in habs or []:
        if not isinstance(h, dict):
            continue
        chave = chave_canonica(h)
        if chave in vistas:
            continue
        vistas.add(chave)
        saida.append(h)
    return saida


def _acao_no_texto(hab: dict) -> str:
    """
    O tipo de ação escrito na descrição de uma habilidade fora do SRD —
    "Reação ao ser atingido: …" é reação, mesmo sem o nome dizer.
    """
    t = compendio.norm((hab or {}).get("descricao", ""))
    if t.startswith("reacao") or " reacao " in f" {t[:40]} " or "como reacao" in t:
        return "reacao"
    if "acao bonus" in t[:60]:
        return "bonus"
    return ""


def _resumo_da_ficha(r: dict) -> str:
    """O resumo de uma habilidade que NÃO é do SRD, montado do que se sabe."""
    partes = []
    ef = r["efeito"]
    if ef == "dano" and r["dado"]:
        partes.append(f"Dano {r['dado']} {TIPO_DANO_PT.get(r['tipo_dano'], '')}".strip())
    elif ef == "cura" and r["dado"]:
        partes.append(f"Cura {r['dado']}")
    else:
        partes.append(ROTULO_EFEITO.get(ef, "Utilidade"))
    if r["salvaguarda"]:
        partes.append(SIGLA.get(r["salvaguarda"], r["salvaguarda"].upper()))
    if r["area"]:
        partes.append(r["area"])
    alvo = {"hostis": "só inimigos", "escolha": "à sua escolha",
            "todos": "TODOS na área, aliados inclusive", "si": "em si"}.get(r["alvos"])
    if alvo and (r["area"] or r["alvos"] in ("hostis", "si")):
        partes.append(alvo)
    return " · ".join(p for p in partes if p)


def resolver(hab: dict, char: dict | None = None) -> dict:
    """
    O que a tela precisa saber de uma habilidade. Os campos de regra (dado,
    área, alvos, salvaguarda) vêm das mesmas funções que o motor usa.
    """
    from rpg import tools_dnd as td

    hab = hab or {}
    nome = hab.get("nome", "")
    srd = (compendio.magia(hab.get("nome_srd") or "") or compendio.magia(nome))
    classe = ((char or {}).get("sheet") or {}).get("classe", "")
    caract = None if srd else compendio.caracteristica(nome, classe, exato=True)

    efeito = td.efeito_do_dado(hab)
    if srd:
        efeito = srd["efeito"]
    elif caract and caract["tipo"] == "passiva":
        efeito = "passiva"

    dado = td.dado_efetivo(hab, char) if efeito not in ("passiva",) else ""
    if caract and caract.get("progressao") and char is not None:
        nivel = int(((char.get("sheet") or {}).get("nivel", 1)) or 1)
        dado = compendio.progressao_no_nivel(caract["progressao"], nivel) or dado

    r = {
        "nome": srd["nome"] if srd else (caract["nome"] if caract else nome),
        "nome_na_ficha": nome,
        "fonte": "srd" if (srd or caract) else "ficha",
        "efeito": efeito,
        "rotulo": ROTULO_EFEITO.get(efeito, "Utilidade"),
        "dado": dado,
        "tipo_dano": ((srd or {}).get("tipo_dano")
                      or (td._damage_type_from_text(hab.get("descricao", ""))
                          if efeito == "dano" else "")),
        "salvaguarda": td.salvaguarda_da_habilidade(hab),
        "ataque": (srd or {}).get("ataque"),
        "area": td.area_da_habilidade(hab),
        "alvos": td.alvos_da_habilidade(hab),
        "alcance": (srd or {}).get("alcance") or hab.get("alcance") or "",
        "acao": ((srd or {}).get("acao") or (caract or {}).get("tipo")
                 or _acao_no_texto(hab) or td._ability_action_type(nome)),
        "concentracao": bool((srd or {}).get("concentracao") or hab.get("concentracao")),
        "nivel": (srd or {}).get("nivel"),
        "custo_mana": int(hab.get("custo_mana", 0) or 0),
        "usos": td.usos_restantes(char, nome) if char else None,
        "usos_max": td.usos_maximos(char, nome) if char else None,
        "descricao": (hab.get("descricao") or (caract or {}).get("descricao")
                      or (srd or {}).get("descricao_en") or ""),
        "chave": chave_canonica(hab),
    }
    # O que acontece quando se usa (rpg/resolucao.py): o jogador vê no cartão,
    # antes de gastar o turno, se o motor resolve, se vira efeito, se é
    # passiva ou se quem decide é o Mestre.
    from rpg import resolucao
    como = resolucao.como_resolve(hab, char)
    r["resolucao"] = como["tipo"]
    r["resolucao_texto"] = como["texto"]
    textos = como.get("modos_texto") or {}
    r["modos"] = [{"id": m, "texto": textos.get(m) or resolucao.MODOS_DE_MOVIMENTO.get(m, m)}
                  for m in como["modos"]]
    r["alvo_modo"] = como["alvo"]
    r["exige_ataque"] = bool((resolucao.ACOES_DE_CLASSE.get(como.get("chave", "")) or {}).get("exige_ataque"))
    # Quem a magia de efeito alcança: a tela oferece aliados ou inimigos.
    _, _ef = resolucao.efeito_de_magia(hab)
    if _ef:
        r["alvo_modo"] = {"aliado": "aliado", "aliados": "aliado", "si": "si",
                          "marca": "inimigo", "inimigos": "inimigo", "area": "inimigo"}.get(_ef["alvos"], "")
    if como["slot"]:
        r["acao"] = como["slot"]
    r["passiva"] = como["tipo"] in ("passiva", "reacao")
    r["reacao"] = como["tipo"] == "reacao"
    if srd:
        r["resumo"] = srd["resumo"]
        # O dado do resumo é o da base; com o truque crescido, o da ficha vale.
        if dado and srd.get("dado") and dado != srd["dado"]:
            r["resumo"] = r["resumo"].replace(srd["dado"], dado, 1)
    elif caract:
        r["resumo"] = caract["resumo"] + (f" · {dado}" if dado and dado not in caract["resumo"] else "")
    else:
        r["resumo"] = _resumo_da_ficha(r)
    return r
