"""
encantos.py
Enfeitiçar e dominar, dentro e fora do combate.

POR QUE EXISTE
──────────────
Numa partida, o clérigo enfeitiçou o orc com Enfeitiçar Pessoa. O motor
rolou a salvaguarda, marcou "Enfeitiçado" — e no turno seguinte o orc atacou
o clérigo e o derrubou. A condição estava na ficha e nada a lia: o motor não
impedia o enfeitiçado de atacar quem o enfeitiçou, o encanto não acabava em
1 hora (nem com o fim da luta) e fora de combate não mudava nada no trato.

Aqui o encanto é uma coisa que o jogo lembra:

  • QUEM enfeitiçou QUEM, com que magia e até quando (pelo relógio do mundo,
    ou pela concentração de quem conjurou, no caso do Dominar);
  • em combate, o enfeitiçado não ataca quem o enfeitiçou (o dominado, ninguém
    do lado de quem o domina); o encanto quebra quando esse lado o fere;
  • fora de combate, a atitude dele sobe para "amistoso" enquanto durar, e
    os testes sociais de quem o enfeitiçou ficam mais fáceis;
  • quando acaba, a atitude volta ao que era — e, se a magia diz que o alvo
    percebe (Enfeitiçar Pessoa), ela cai: ele sabe o que fizeram com ele.

Vale para qualquer pessoa da história, com ou sem ficha de regras: o guarda
do portão também pode ser enfeitiçado.
"""

from __future__ import annotations

import random

from rpg import memory

# nome no SRD → como o encanto funciona
ENCANTOS = {
    "Charm Person":      {"tipo": "enfeitiçado", "horas": 1, "percebe": True,
                          "alvos": ("humanoid", "humanoide", "humano", "elfo", "anao", "anão",
                                    "halfling", "gnomo", "orc", "goblin", "meio", "tiefling",
                                    "draconato", "kobold", "hobgoblin", "bugbear", "gnoll")},
    "Charm Monster":     {"tipo": "enfeitiçado", "horas": 1, "percebe": True},
    "Animal Friendship": {"tipo": "enfeitiçado", "horas": 24, "percebe": False,
                          "alvos": ("beast", "besta", "animal", "lobo", "urso", "cavalo",
                                    "cao", "cão", "gato", "javali", "aranha gigante")},
    "Dominate Person":   {"tipo": "dominado", "concentracao": True, "percebe": True},
    "Dominate Beast":    {"tipo": "dominado", "concentracao": True, "percebe": False},
    "Dominate Monster":  {"tipo": "dominado", "concentracao": True, "percebe": True},
}

ATITUDE_ENFEITICADO = 40   # "amistoso" (tools._FAIXAS_ATITUDE)
PERCEBEU = -20             # quando acaba e o alvo sabe que foi enfeitiçado


def _registro() -> list[dict]:
    r = memory.campaign.setdefault("encantos", [])
    if not isinstance(r, list):
        r = []
        memory.campaign["encantos"] = r
    return r


def _agora() -> int:
    from rpg import tools_dnd as td
    return td._agora_em_horas()


def _char(nome: str) -> dict | None:
    return memory.campaign.get("characters", {}).get(memory.char_key(nome or ""))


def do_encanto(magia_srd: str) -> dict | None:
    return ENCANTOS.get(magia_srd)


def _vale(e: dict) -> bool:
    if e.get("ate_hora") is not None and _agora() >= int(e["ate_hora"]):
        return False
    if e.get("concentracao_de"):
        conj = memory.campaign.get("characters", {}).get(e["concentracao_de"]) or {}
        atual = ((conj.get("sheet") or {}).get("concentracao") or {})
        from rpg import resolucao
        if resolucao.norm(atual.get("magia", "")) != resolucao.norm(e.get("magia_ficha", "")):
            return False
    return True


def ativo(alvo: dict | None) -> dict | None:
    """O encanto que pesa sobre `alvo` agora, ou None."""
    if not alvo:
        return None
    chave = memory.char_key(alvo.get("name", ""))
    for e in _registro():
        if e.get("alvo") == chave and _vale(e):
            return e
    return None


def pode_atacar(atacante: dict, alvo: dict) -> str:
    """'' quando pode; senão o motivo — o enfeitiçado não ataca quem o enfeitiçou."""
    e = ativo(atacante)
    if not e:
        return ""
    por = _char(e["por_nome"])
    if not por:
        return ""
    if e["tipo"] == "enfeitiçado" and alvo is por:
        return (f"{atacante.get('name')} está Enfeitiçado por {por.get('name')} e não "
                f"pode atacá-lo.")
    if e["tipo"] == "dominado" and memory.luta_com_o_grupo(alvo) == memory.luta_com_o_grupo(por):
        return (f"{atacante.get('name')} está Dominado por {por.get('name')} e não ataca "
                f"o lado de quem o domina.")
    return ""


def encantar(conjurador: dict, alvo: dict, magia_srd: str, magia_ficha: str, nome_pt: str) -> str:
    """Grava o encanto (a salvaguarda já falhou). Devolve a linha do resultado."""
    from rpg import tools as tl
    cfg = ENCANTOS[magia_srd]
    chave = memory.char_key(alvo.get("name", ""))
    # Um encanto por alvo: o novo substitui o anterior, sem a "percepção".
    memory.campaign["encantos"] = [e for e in _registro() if e.get("alvo") != chave]
    antes = tl.atitude_de(alvo)
    e = {
        "alvo": chave, "alvo_nome": alvo.get("name", ""),
        "por": memory.char_key(conjurador.get("name", "")), "por_nome": conjurador.get("name", ""),
        "magia": nome_pt, "magia_srd": magia_srd, "magia_ficha": magia_ficha,
        "tipo": cfg["tipo"], "percebe": cfg.get("percebe", False),
        "atitude_antes": antes,
    }
    if cfg.get("horas"):
        e["ate_hora"] = _agora() + int(cfg["horas"])
    if cfg.get("concentracao"):
        e["concentracao_de"] = memory.char_key(conjurador.get("name", ""))
    _registro().append(e)
    # Fora da luta, é o que muda: ele trata quem o enfeitiçou como um conhecido
    # amistoso. A atitude é o que mexe na CD social e no preço da loja.
    if antes < ATITUDE_ENFEITICADO:
        alvo["atitude"] = ATITUDE_ENFEITICADO
    # A condição na ficha (quando há ficha) é o que a tela de combate mostra.
    s = alvo.get("sheet")
    if isinstance(s, dict):
        conds = s.setdefault("condicoes", [])
        conds[:] = [c for c in conds if not (isinstance(c, dict) and c.get("encanto"))]
        conds.append({"nome": "Enfeitiçado" if cfg["tipo"] == "enfeitiçado" else "Dominado",
                      "duracao": None, "encanto": True, "por": e["por_nome"]})
    quando = _quando(e)
    efeito = ("não ataca " + conjurador.get("name", "") if cfg["tipo"] == "enfeitiçado"
              else "não ataca o lado de " + conjurador.get("name", ""))
    return (f"{alvo.get('name')} está {'ENFEITIÇADO' if cfg['tipo'] == 'enfeitiçado' else 'DOMINADO'} "
            f"por {conjurador.get('name')} {quando}: {efeito}, trata-o como amigo"
            f"{'' if cfg['tipo'] == 'dominado' else ' (atitude amistosa)'}.")


def _quando(e: dict) -> str:
    if e.get("ate_hora") is not None:
        h = int(e["ate_hora"])
        return f"até o Dia {h // 24}, {h % 24:02d}h"
    if e.get("concentracao_de"):
        return "enquanto durar a concentração"
    return ""


def quebrar(alvo: dict, motivo: str) -> str:
    """Acaba com o encanto sobre `alvo`. Devolve a linha do que aconteceu."""
    from rpg import tools as tl
    chave = memory.char_key(alvo.get("name", ""))
    achados = [e for e in _registro() if e.get("alvo") == chave]
    if not achados:
        return ""
    memory.campaign["encantos"] = [e for e in _registro() if e.get("alvo") != chave]
    e = achados[-1]
    s = alvo.get("sheet")
    if isinstance(s, dict) and isinstance(s.get("condicoes"), list):
        s["condicoes"] = [c for c in s["condicoes"] if not (isinstance(c, dict) and c.get("encanto"))]
    # A atitude volta ao que era; e quem percebe, guarda rancor.
    alvo["atitude"] = int(e.get("atitude_antes", 0) or 0)
    linha = f"O encanto de {e.get('por_nome')} sobre {alvo.get('name')} acabou ({motivo})."
    if e.get("percebe"):
        tl.adjust_attitude(alvo.get("name", ""), PERCEBEU,
                           f"percebeu que foi enfeitiçado por {e.get('por_nome')}")
        linha += f" {alvo.get('name')} sabe que foi enfeitiçado."
    return linha


def expirar() -> list[str]:
    """Encerra os encantos que venceram (relógio ou concentração)."""
    linhas = []
    for e in list(_registro()):
        if not _vale(e):
            alvo = _char(e.get("alvo_nome", ""))
            if alvo:
                linhas.append(quebrar(alvo, "o tempo da magia acabou"
                                      if e.get("ate_hora") is not None else "a concentração caiu"))
            else:
                memory.campaign["encantos"] = [x for x in _registro() if x is not e]
    return [l for l in linhas if l]


def ferido_por(alvo: dict, fonte_nome: str) -> str:
    """
    O enfeitiçado levou dano de quem o enfeitiçou ou de alguém do lado dele:
    o encanto quebra (é a regra do Enfeitiçar Pessoa).
    """
    e = ativo(alvo)
    if not e or not fonte_nome:
        return ""
    fonte = _char(fonte_nome)
    por = _char(e.get("por_nome", ""))
    if not fonte or not por:
        return ""
    if fonte is por or memory.luta_com_o_grupo(fonte) == memory.luta_com_o_grupo(por):
        return quebrar(alvo, f"{fonte.get('name')} o feriu")
    return ""


def nota(alvo: dict) -> str:
    """A linha para o Mestre e para a ficha: quem enfeitiçou, até quando."""
    e = ativo(alvo)
    if not e:
        return ""
    if e["tipo"] == "dominado":
        return (f"Dominado por {e['por_nome']} ({e['magia']}, {_quando(e)}): obedece às "
                f"ordens dele e não ataca o lado dele.")
    return (f"Enfeitiçado por {e['por_nome']} ({e['magia']}, {_quando(e)}): trata "
            f"{e['por_nome']} como um conhecido amistoso, não o ataca, e {e['por_nome']} "
            f"tem vantagem nos testes sociais com ele.")


def tipo_combina(alvo: dict, magia_srd: str) -> bool:
    """Enfeitiçar Pessoa só afeta humanoides; Amizade Animal, bestas."""
    cfg = ENCANTOS.get(magia_srd) or {}
    palavras = cfg.get("alvos")
    if not palavras:
        return True
    s = alvo.get("sheet") or {}
    from rpg import resolucao
    texto = resolucao.norm(" ".join(str(x or "") for x in (s.get("tipo"), s.get("raca"))))
    if not texto:
        return True     # sem informação de tipo: o mestre decide
    return any(resolucao.norm(p) in texto for p in palavras)


def conjurar(conjurador: dict, hab: dict, alvo_nome: str, magia_srd: str, nome_pt: str) -> str:
    """
    Resolve uma magia de encanto: salvaguarda de SAB (com vantagem se o alvo
    está lutando contra o lado de quem conjura) e, se falhar, o encanto.
    Funciona em quem não tem ficha de regras: salvaguarda com modificador 0.
    """
    from rpg import tools_dnd as td
    from rpg import resolucao
    alvo = _char(alvo_nome)
    if not alvo:
        return f"\n   Ninguém chamado {alvo_nome} na história."
    if not tipo_combina(alvo, magia_srd):
        return (f"\n   {nome_pt} não afeta {alvo.get('name')}: "
                f"{'só humanoides' if magia_srd == 'Charm Person' else 'só bestas'}.")
    cd = resolucao._cd(conjurador)
    cs = memory.campaign.get("combat_state") or {}
    na_luta = {memory.char_key(n) for n in (cs.get("initiative_order") or [])} if cs.get("is_active") else set()
    lutando = (memory.char_key(alvo.get("name", "")) in na_luta
               and memory.luta_com_o_grupo(alvo) != memory.luta_com_o_grupo(conjurador))
    if alvo.get("sheet"):
        passou, linha = td._rolar_salvaguarda(alvo, "sabedoria", cd, vantagem=lutando)
    else:
        d20 = random.randint(1, 20)
        if lutando:
            d20 = max(d20, random.randint(1, 20))
        passou, linha = d20 >= cd, f"salvaguarda de SAB: {d20}+0 = {d20} vs CD {cd}"
    if lutando:
        linha += " (com vantagem: está lutando contra vocês)"
    if passou:
        return f"\n   {alvo.get('name')}: {linha} — resistiu ao encanto."
    return f"\n   {alvo.get('name')}: {linha} — falhou.\n   " + encantar(
        conjurador, alvo, magia_srd, hab.get("nome", ""), nome_pt)
