"""
superioridade.py
As Manobras de Combate do Mestre de Batalha (guerreiro) e os Dados de
Superioridade que as alimentam.

POR QUE EXISTE
──────────────
A ficha do Mestre de Batalha dizia "Aprende 3 manobras" e "Pool de 4 dados
d8", e o motor tratava as duas como passivas: nenhuma manobra existia, nenhum
dado era gasto. A subclasse inteira era texto.

Como o motor usa cada manobra:
  golpe      armada antes do ataque (sem gastar ação); no próximo acerto com
             arma neste turno, gasta o dado, soma o dado ao dano e aplica o
             efeito (derrubar, amedrontar, empurrar...). Se não acertar, nada
             é gasto.
  precisao   armada; quando um ataque deste turno ERRA, o motor rola o dado e
             soma ao ataque — se virar acerto, valeu (o dado é gasto só se usado)
  finta      ação bônus: vantagem no próximo ataque contra o alvo neste turno,
             e o dado soma ao dano se acertar
  reagrupar  ação bônus: um aliado ganha PV temporários (dado + mod. de CAR)
  reações    Contra-Ataque e Aparar: o motor usa sozinho (rpg/reacoes.py)

As manobras que a ficha aprendeu vêm de feature_choices["Manobras de
Combate"] (e das Manobras Aprimoradas e Relâmpago). Sem escolha gravada, o
motor oferece todas — a ficha antiga não guardava a escolha.
"""
from __future__ import annotations

from rpg import memory

# nome → {tipo, texto, e o que o golpe faz}
MANOBRAS: dict[str, dict] = {
    "Ataque Ameaçador": {"tipo": "golpe", "texto": "+dado no dano; SAB ou fica Amedrontado até o fim do seu próximo turno",
                         "condicao": "Amedrontado", "salvaguarda": "sabedoria", "proximo_turno": True},
    "Ataque Derrubador": {"tipo": "golpe", "texto": "+dado no dano; FOR ou fica Caído",
                          "condicao": "Caído", "salvaguarda": "forca"},
    "Ataque de Empurrão": {"tipo": "golpe", "texto": "+dado no dano; FOR ou é empurrado para a zona vizinha",
                           "empurrar": True, "salvaguarda": "forca"},
    "Ataque Desarmante": {"tipo": "golpe", "texto": "+dado no dano; FOR ou larga a arma (desvantagem no próximo ataque)",
                          "desarmar": True, "salvaguarda": "forca"},
    "Ataque Distrativo": {"tipo": "golpe", "texto": "+dado no dano; o próximo ataque de um aliado contra o alvo tem vantagem",
                          "distrair": True},
    "Ataque Provocador": {"tipo": "golpe", "texto": "+dado no dano; SAB ou tem desvantagem para atacar outros que não você",
                          "provocar": True, "salvaguarda": "sabedoria"},
    "Ataque Varredor": {"tipo": "golpe", "texto": "se acertar, o dado fere outro inimigo na mesma zona",
                        "varrer": True},
    "Ataque Preciso": {"tipo": "precisao", "texto": "se um ataque deste turno errar, soma o dado ao ataque"},
    "Finta": {"tipo": "finta", "texto": "ação bônus: vantagem no próximo ataque contra o alvo e +dado no dano"},
    "Reagrupar": {"tipo": "reagrupar", "texto": "ação bônus: um aliado ganha PV temporários (dado + mod. de CAR)"},
    "Contra-Ataque": {"tipo": "reacao", "texto": "reação: quando um inimigo erra você corpo a corpo, você ataca (+dado)"},
    "Aparar": {"tipo": "reacao", "texto": "reação: quando um ataque corpo a corpo acerta você, reduz o dano em dado + DES"},
}

_CHAVE = {memory.char_key(n): n for n in MANOBRAS}


def _td():
    from rpg import tools_dnd
    return tools_dnd


def tem(char: dict) -> bool:
    return _td()._tem_habilidade(char, "manobras de combate", "dado de superioridade",
                                 "superioridade em combate", "combat superiority")


def conhecidas(char: dict) -> list[str]:
    """As manobras que a ficha aprendeu; todas, quando a escolha não foi gravada."""
    td = _td()
    escolhas = []
    for feat in ("Manobras de Combate", "Manobras Aprimoradas", "Manobras Relâmpago"):
        v = td._get_feature_choice(char, feat)
        escolhas += ([v] if isinstance(v, str) else list(v or []))
    nomes = [_CHAVE[memory.char_key(n)] for n in escolhas if memory.char_key(n) in _CHAVE]
    return nomes or list(MANOBRAS)


def dado(char: dict) -> int:
    nivel = int(((char.get("sheet") or {}).get("nivel", 1)) or 1)
    return 12 if nivel >= 18 else 10 if nivel >= 10 else 8


def cd(char: dict) -> int:
    td = _td()
    s = char.get("sheet") or {}
    mod = max(td._modifier(int(s.get("forca", 10) or 10)), td._modifier(int(s.get("destreza", 10) or 10)))
    return 8 + int(s.get("proficiencia", 2) or 2) + mod


def restantes(char: dict) -> int:
    return int(_td().usos_restantes(char, "Dados de Superioridade") or 0)


def gastar(char: dict) -> None:
    _td()._gastar_uso(char, "Dados de Superioridade")


def modos(char: dict) -> dict:
    """id → texto das manobras que se ARMAM ou usam na vez (as reações ficam com o motor)."""
    return {memory.char_key(n): f"{n}: {MANOBRAS[n]['texto']}"
            for n in conhecidas(char) if MANOBRAS[n]["tipo"] != "reacao"}


def alvo_do_modo(modo: str) -> str:
    n = _CHAVE.get(memory.char_key(modo or ""), "")
    return {"finta": "inimigo", "reagrupar": "aliado"}.get(MANOBRAS.get(n, {}).get("tipo"), "si")


def slot_do_modo(modo: str) -> str:
    n = _CHAVE.get(memory.char_key(modo or ""), "")
    return "bonus" if MANOBRAS.get(n, {}).get("tipo") in ("finta", "reagrupar") else "livre"


def usar(char: dict, modo: str, alvo_nome: str) -> str:
    """Arma a manobra (golpe, precisão) ou a resolve na hora (finta, reagrupar)."""
    td = _td()
    nome = _CHAVE[memory.char_key(modo)]
    cfg = MANOBRAS[nome]
    eu = memory.char_key(char.get("name", ""))
    face = dado(char)
    if cfg["tipo"] == "golpe":
        efeito = {"nome": nome, "golpe_dado": f"1d{face}", "golpe_superioridade": True,
                  "golpe_tipo_da_arma": True, "ate_fim_turno_de": eu, "manobra": nome}
        if cfg.get("condicao"):
            efeito["golpe_condicao"] = {"nome": cfg["condicao"], "salvaguarda": cfg["salvaguarda"], "cd": cd(char)}
            if cfg.get("proximo_turno"):
                efeito["golpe_condicao"]["ate_fim_do_proximo_turno_de"] = eu
        td.dar_efeito_de_combate(char, efeito)
        return f"\n   {nome} pronto: no próximo acerto com arma neste turno, {cfg['texto']} (CD {cd(char)})."
    if cfg["tipo"] == "precisao":
        td.dar_efeito_de_combate(char, {"nome": nome, "precisao": f"1d{face}", "ate_fim_turno_de": eu})
        return f"\n   {nome} pronto: se um ataque deste turno errar, o motor soma 1d{face} a ele."
    if cfg["tipo"] == "finta":
        gastar(char)
        td.dar_efeito_de_combate(char, {"nome": "Finta", "vantagem_ataque": True, "usos": 1,
                                        "contra": memory.char_key(alvo_nome), "ate_fim_turno_de": eu})
        td.dar_efeito_de_combate(char, {"nome": "Finta (dano)", "golpe_dado": f"1d{face}",
                                        "golpe_tipo_da_arma": True, "ate_fim_turno_de": eu})
        return (f"\n   Finta: vantagem no próximo ataque contra {alvo_nome} neste turno, +1d{face} no dano "
                f"se acertar. Dados de Superioridade: {restantes(char)}.")
    if cfg["tipo"] == "reagrupar":
        gastar(char)
        a = memory.campaign["characters"].get(memory.char_key(alvo_nome)) or char
        import random
        valor = random.randint(1, face) + max(0, td._modifier(int((char.get("sheet") or {}).get("carisma", 10) or 10)))
        st = a.setdefault("sheet", {})
        st["vida_temp"] = max(int(st.get("vida_temp", 0) or 0), valor)
        return (f"\n   Reagrupar: {a['name']} ganha {valor} PV temporários. "
                f"Dados de Superioridade: {restantes(char)}.")
    return ""


def depois_do_acerto(atacante: dict, alvo: dict, efeito: dict, tipo_dano: str) -> str:
    """O que a manobra faz além do dado e da condição: empurrar, desarmar, distrair, provocar, varrer."""
    td = _td()
    nome = efeito.get("manobra", "")
    cfg = MANOBRAS.get(nome) or {}
    linhas = []
    if cfg.get("salvaguarda") and not cfg.get("condicao"):
        passou, linha = td._rolar_salvaguarda(alvo, cfg["salvaguarda"], cd(atacante))
        if passou:
            return f"\n   {nome}: {alvo['name']}: {linha} — resiste."
        linhas.append(f"{alvo['name']}: {linha}")
    if cfg.get("empurrar"):
        if td._zonas_ativas():
            zonas = td._zonas()
            aqui = td._zona_de(alvo["name"])
            i = zonas.index(aqui) if aqui in zonas else 0
            destino = zonas[i + 1] if i + 1 < len(zonas) else zonas[i - 1]
            memory.campaign["combat_state"].setdefault("posicoes", {})[memory.char_key(alvo["name"])] = destino
            linhas.append(f"empurrado para {destino}")
        else:
            linhas.append("empurrado para longe (sem zonas, o Mestre narra onde)")
    if cfg.get("desarmar"):
        td.dar_efeito_de_combate(alvo, {"nome": "Desarmado", "desvantagem_ataque": True, "usos": 1})
        linhas.append("larga a arma: desvantagem no próximo ataque")
    if cfg.get("distrair"):
        td.dar_efeito_de_combate(alvo, {"nome": f"Distraído por {atacante['name']}", "vantagem_contra_mim": True,
                                        "usos": 1, "ate_turno_de": memory.char_key(atacante["name"])})
        linhas.append("o próximo ataque de um aliado contra ele tem vantagem")
    if cfg.get("provocar"):
        td.dar_efeito_de_combate(alvo, {"nome": f"Provocado por {atacante['name']}", "provocado_por":
                                        memory.char_key(atacante["name"]),
                                        "ate_fim_turno_de": memory.char_key(atacante["name"]),
                                        "desde_token": int((memory.campaign.get("combat_state") or {})
                                                           .get("turn_token", 0) or 0)})
        linhas.append(f"desvantagem para atacar quem não for {atacante['name']}")
    if cfg.get("varrer"):
        import random
        outros = [c for c in _vizinhos_inimigos(atacante, alvo)]
        if outros:
            o = outros[0]
            valor = random.randint(1, dado(atacante))
            res = td._apply_damage(o, valor, tipo_dano, source_name=atacante["name"])
            linhas.append(f"o golpe varre {o['name']}: {res['dano']} de dano ({res['hp_antes']} → {res['hp_depois']})")
            if res["hp_depois"] == 0 and res["hp_antes"] > 0:
                linhas.append(td._mark_at_zero_hp(o, atacante["name"]).strip())
        else:
            linhas.append("ninguém mais ao alcance para varrer")
    return (f"\n   {nome}: " + "; ".join(linhas) + ".") if linhas else ""


def _vizinhos_inimigos(atacante: dict, alvo: dict) -> list[dict]:
    td = _td()
    cs = memory.campaign.get("combat_state") or {}
    saida = []
    for nm in cs.get("initiative_order") or []:
        c = memory.campaign["characters"].get(memory.char_key(nm))
        if (not c or c is alvo or c is atacante
                or memory.luta_com_o_grupo(c) == memory.luta_com_o_grupo(atacante)
                or (c.get("status") or "").lower() in td.OUT_OF_COMBAT_STATUSES):
            continue
        d = td._distancia(atacante["name"], c["name"])
        if d is None or d == 0:
            saida.append(c)
    return saida
