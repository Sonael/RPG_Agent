"""
subclasses.py
As características de subclasse e de nível alto que caíam em "o Mestre
decide": Metamagia, Maestria e Assinatura de Feitiço, Palma Vibrante, os
efeitos de Canalizar Divindade que faltavam, Avatar Sagrado, Anjo Vingador,
Coroa da Luz, as do bruxo, do feiticeiro dracônico e do selvagem, do monge
das sombras e dos quatro elementos.

As ações de classe ficam aqui (executores, modos, alvo e custo por escolha);
rpg/resolucao.py as registra em ACOES_DE_CLASSE. As reações ficam em
rpg/reacoes.py; os ganchos de ataque, teste, descanso e conjuração, em
rpg/tools_dnd.py.
"""
from __future__ import annotations

import random

from rpg import memory


def _td():
    from rpg import tools_dnd
    return tools_dnd


def _rs():
    from rpg import resolucao
    return resolucao


def _ch(nome: str) -> dict | None:
    return memory.campaign.get("characters", {}).get(memory.char_key(nome or ""))


def _nivel(char: dict) -> int:
    return int(((char.get("sheet") or {}).get("nivel", 1)) or 1)


def _mod(char: dict, attr: str) -> int:
    return _td()._modifier(int(((char.get("sheet") or {}).get(attr, 10)) or 10))


def _eu(char: dict) -> str:
    return memory.char_key(char.get("name", ""))


def _token() -> int:
    return int((memory.campaign.get("combat_state") or {}).get("turn_token", 0) or 0)


def _cd_car(char: dict) -> int:
    return 8 + int((char.get("sheet") or {}).get("proficiencia", 2) or 2) + _mod(char, "carisma")


def _magias_por_nivel(char: dict, nivel: int) -> list[str]:
    rs = _rs()
    saida = []
    for h in char.get("habilidades") or []:
        m = rs._magia_srd(h) if isinstance(h, dict) else None
        if m and int(m.get("nivel", 0) or 0) == nivel:
            saida.append(h["nome"])
    return saida


def _condicao(alvo: dict, nome: str, por: dict, **extra) -> None:
    rs = _rs()
    rs._tirar_condicoes(alvo, (nome,))
    c = {"nome": nome, "duracao": None, "por": por.get("name", "")}
    c.update(extra)
    alvo.setdefault("sheet", {}).setdefault("condicoes", []).append(c)


def _inimigos_perto(char: dict, passos: int = 0) -> list[dict]:
    rs = _rs()
    return [c for c in rs._combatentes_vivos() if not rs._mesmo_lado(char, c) and rs._perto(char, c, passos)]


def _aliados_perto(char: dict) -> list[dict]:
    rs = _rs()
    lista = [c for c in rs._combatentes_vivos() if rs._mesmo_lado(char, c) and rs._perto(char, c)]
    return lista if char in lista else lista + [char]


# ===========================================================================
# Maestria e Assinatura de Feitiço (mago 18 e 20)
# ===========================================================================
# A ficha não tinha onde gravar a escolha. A própria ação escolhe: usar
# "Maestria de Feitiço" com uma magia de 1º ou 2º círculo marca essa magia
# (uma de cada círculo); daí em diante ela sai sem mana no círculo dela.

def _escolhas(char: dict, feat: str) -> list[str]:
    v = _td()._get_feature_choice(char, feat)
    return [v] if isinstance(v, str) else list(v or [])


def _gravar_escolha(char: dict, feat: str, lista: list[str]) -> None:
    char.setdefault("sheet", {}).setdefault("feature_choices", {})[feat] = lista


def modos_maestria(char: dict) -> dict:
    return {n: f"{n} ({nv}º círculo)" for nv in (1, 2) for n in _magias_por_nivel(char, nv)}


def modos_assinatura(char: dict) -> dict:
    return {n: f"{n} (3º círculo)" for n in _magias_por_nivel(char, 3)}


def maestria(char, hab, alvo, modo):
    rs = _rs()
    nivel = int((rs._magia_srd({"nome": modo}) or {}).get("nivel", 0) or 0)
    lista = [n for n in _escolhas(char, "Maestria de Feitiço")
             if int((rs._magia_srd({"nome": n}) or {}).get("nivel", 0) or 0) != nivel] + [modo]
    _gravar_escolha(char, "Maestria de Feitiço", lista)
    return f"\n   Maestria de Feitiço: {modo} ({nivel}º círculo) agora sai sem mana no círculo dela."


def assinatura(char, hab, alvo, modo):
    lista = [n for n in _escolhas(char, "Assinatura de Feitiço") if n != modo][-1:] + [modo]
    _gravar_escolha(char, "Assinatura de Feitiço", lista)
    return (f"\n   Assinatura de Feitiço: {', '.join(lista)} — cada uma sai sem mana uma vez por "
            f"descanso curto, no 3º círculo.")


def custo_de_graca(char: dict, hab: dict, circulo: int) -> str:
    """'' ou o motivo de esta conjuração não gastar mana (Maestria, Assinatura)."""
    rs = _rs()
    m = rs._magia_srd(hab) or {}
    base = int(m.get("nivel", 0) or 0)
    if circulo and circulo != base:
        return ""
    nome = hab.get("nome", "")
    if _td()._tem_habilidade(char, "maestria de feitico") and nome in _escolhas(char, "Maestria de Feitiço"):
        return "Maestria de Feitiço"
    s = char.get("sheet") or {}
    if (_td()._tem_habilidade(char, "assinatura de feitico") and nome in _escolhas(char, "Assinatura de Feitiço")
            and nome not in (s.get("assinatura_usada") or [])):
        s.setdefault("assinatura_usada", []).append(nome)
        return "Assinatura de Feitiço"
    return ""


# ===========================================================================
# Metamagia (feiticeiro)
# ===========================================================================
METAMAGIAS = {
    "acelerada": ("Magia Acelerada", 2, "a próxima magia de ação sai como ação bônus"),
    "gemea": ("Magia Gêmea", 0, "a próxima magia de um alvo só pega também o alvo escolhido (pontos = círculo)"),
    "cuidadosa": ("Magia Cuidadosa", 1, "na próxima magia de área, os aliados passam na salvaguarda"),
    "intensificada": ("Magia Intensificada", 3, "na próxima magia, o primeiro alvo faz a salvaguarda com desvantagem"),
    "potencializada": ("Magia Potencializada", 1, "na próxima magia de dano, os dados mais baixos são rolados de novo"),
    "sutil": ("Magia Sutil", 1, "a próxima magia sai sem som nem gesto: o Silêncio não impede e ninguém a anula"),
    "distante": ("Magia Distante", 1, "alcance dobrado na próxima magia (o Mestre considera)"),
    "estendida": ("Magia Estendida", 1, "duração dobrada na próxima magia (o Mestre considera)"),
}
_ALIAS_META = {"sutil": "sutil", "subtle": "sutil", "acelerada": "acelerada", "quickened": "acelerada",
               "gemea": "gemea", "twinned": "gemea", "cuidadosa": "cuidadosa", "careful": "cuidadosa",
               "intensificada": "intensificada", "heightened": "intensificada",
               "potencializada": "potencializada", "empoderada": "potencializada", "empowered": "potencializada",
               "distante": "distante", "distant": "distante", "estendida": "estendida", "extended": "estendida"}


def metamagias_conhecidas(char: dict) -> list[str]:
    rs = _rs()
    escolhidas = []
    for n in _escolhas(char, "Metamagia"):
        for parte in rs.norm(n).split():
            if parte in _ALIAS_META:
                escolhidas.append(_ALIAS_META[parte])
    return list(dict.fromkeys(escolhidas)) or list(METAMAGIAS)


def modos_metamagia(char: dict) -> dict:
    return {k: f"{METAMAGIAS[k][0]}: {METAMAGIAS[k][2]}"
            + (f" ({METAMAGIAS[k][1]} ponto{'s' if METAMAGIAS[k][1] > 1 else ''})" if METAMAGIAS[k][1] else "")
            for k in metamagias_conhecidas(char)}


def _pontos(char: dict) -> int:
    return int(_td().usos_restantes(char, "Fonte de Magia") or 0)


def _gastar_pontos(char: dict, n: int) -> None:
    s = char.setdefault("sheet", {})
    s.setdefault("usos", {})["pontos de feiticaria"] = max(0, _pontos(char) - n)


def metamagia(char, hab, alvo, modo):
    nome, custo, texto = METAMAGIAS[modo]
    if custo and _pontos(char) < custo:
        return f"\n   {nome}: faltam pontos de feitiçaria ({_pontos(char)}/{custo})."
    efeito = {"nome": nome, "metamagia": modo, "ate_fim_turno_de": _eu(char)}
    if modo == "gemea":
        efeito["gemea_alvo"] = alvo
    _td().dar_efeito_de_combate(char, efeito)
    return f"\n   {nome} pronta: {texto}." + (f" Segundo alvo: {alvo}." if modo == "gemea" else "")


def metamagia_armada(char: dict, tipo: str) -> dict | None:
    return next((e for e in _td()._efeitos_de(char) if e.get("metamagia") == tipo), None)


def consumir_metamagia(char: dict, tipo: str, custo: int | None = None) -> bool:
    """Gasta os pontos e tira o efeito. False quando não está armada ou falta ponto."""
    e = metamagia_armada(char, tipo)
    if not e:
        return False
    custo = METAMAGIAS[tipo][1] if custo is None else custo
    if _pontos(char) < custo:
        return False
    _gastar_pontos(char, custo)
    s = char["sheet"]
    s["efeitos"] = [x for x in s.get("efeitos") or [] if x is not e]
    return True


# ===========================================================================
# Ações de classe
# ===========================================================================

def mestre_sobrenatural(char, hab, alvo, modo):
    s = char["sheet"]
    ganho = _td().SPELL_MANA_COST[5]
    antes = int(s.get("mana_atual", 0) or 0)
    s["mana_atual"] = min(int(s.get("mana_max", 0) or 0), antes + ganho)
    return f"\n   Mestre Sobrenatural: o pacto devolve um espaço de 5º círculo ({antes} → {s['mana_atual']} mana)."


def disparo_magico(char, hab, alvo, modo):
    td = _td()
    arma = (((char.get("sheet") or {}).get("equipamentos") or {}).get("arma_principal") or "ataque desarmado")
    return "\n" + td.attack_roll(char["name"], alvo, arma, 6, end_turn=False, _skip_turn_check=True)


def avatar_sagrado(char, hab, alvo, modo):
    td = _td()
    todos = list(_rs()._TODOS_OS_DANOS_MENOS_FORCA) + ["force"]
    nomes = []
    for c in _aliados_perto(char):
        td.dar_efeito_de_combate(c, {"nome": "Avatar Sagrado", "resistencias": todos})
        nomes.append(c["name"])
    return (f"\n   Avatar Sagrado: uma aura sagrada envolve {', '.join(nomes)} — resistência a todo dano até o "
            f"fim do combate. (Mestre: narre a luz da aura.)")


def tornado_de_folhas(char, hab, alvo, modo):
    td = _td()
    a = _ch(alvo)
    if td._imune_a_condicao(a, "Amedrontado"):
        return f"\n   Tornado de Folhas: {a['name']} é imune a Amedrontado."
    passou, linha = td._rolar_salvaguarda(a, "sabedoria", _rs()._cd(char), contra="amedrontado")
    if passou:
        return f"\n   Tornado de Folhas: {a['name']}: {linha} — resiste."
    _condicao(a, "Amedrontado", char, magia="Tornado de Folhas")
    return f"\n   Tornado de Folhas: {a['name']}: {linha} — AMEDRONTADO até o fim do combate."


def anjo_vingador(char, hab, alvo, modo):
    td = _td()
    bonus = max(1, _mod(char, "carisma"))
    td.dar_efeito_de_combate(char, {"nome": "Anjo Vingador", "movimento_por_turno": 1, "dano_fixo": bonus})
    linhas = []
    for c in _inimigos_perto(char):
        if td._imune_a_condicao(c, "Amedrontado"):
            continue
        passou, linha = td._rolar_salvaguarda(c, "sabedoria", _cd_car(char), contra="amedrontado")
        if not passou:
            _condicao(c, "Amedrontado", char, magia="Anjo Vingador")
        linhas.append(f"{c['name']}: {linha} — " + ("resiste" if passou else "AMEDRONTADO"))
    return (f"\n   Anjo Vingador: asas (mais uma zona de movimento por turno) e +{bonus} de dano até o fim do "
            f"combate." + "".join(f"\n   • {l}" for l in linhas))


def ler_pensamentos(char, hab, alvo, modo):
    a = _ch(alvo)
    passou, linha = _td()._rolar_salvaguarda(a, "sabedoria", _rs()._cd(char))
    if passou:
        return f"\n   Ler Pensamentos: {a['name']}: {linha} — a mente dele resiste."
    return (f"\n   Ler Pensamentos: {a['name']}: {linha} — por um minuto, {char['name']} lê os pensamentos "
            f"superficiais dele.\n   (Mestre: diga o que ele pensa agora.)")


def coroa_da_luz(char, hab, alvo, modo):
    _td().dar_efeito_de_combate(char, {"nome": "Coroa da Luz", "coroa_da_luz": True})
    return ("\n   Coroa da Luz: até o fim do combate, inimigos fazem com desvantagem as salvaguardas contra "
            "magias de fogo e radiantes do grupo.")


def encantar_animais(char, hab, alvo, modo):
    td = _td()
    rs = _rs()
    linhas = []
    for c in _inimigos_perto(char, 1):
        if not rs._e_do_tipo(c, ("beast", "fera", "animal", "plant", "planta", "lobo", "urso", "aranha")):
            continue
        passou, linha = td._rolar_salvaguarda(c, "sabedoria", rs._cd(char), contra="enfeiticado")
        if not passou:
            _condicao(c, "Enfeitiçado", char, magia="Encantar Animais e Plantas")
        linhas.append(f"{c['name']}: {linha} — " + ("resiste" if passou else "ENFEITIÇADO"))
    if not linhas:
        return "\n   Encantar Animais e Plantas: nenhum animal ou planta inimigo por perto."
    return "\n   Encantar Animais e Plantas:" + "".join(f"\n   • {l}" for l in linhas)


def bencao_do_trapaceiro(char, hab, alvo, modo):
    a = _ch(alvo) or char
    _td().dar_efeito_de_combate(a, {"nome": "Bênção do Trapaceiro", "vantagem_pericias": ["furtividade"],
                                    "ate": "horas", "ate_hora": _td()._agora_em_horas() + 1})
    return f"\n   Bênção do Trapaceiro: {a['name']} tem vantagem em Furtividade por uma hora."


def invocar_duplicacao(char, hab, alvo, modo):
    _td().dar_efeito_de_combate(char, {"nome": "Duplicata Ilusória", "vantagem_ataque": True,
                                       "concentracao_de": _eu(char), "magia": hab.get("nome", "")})
    _td()._start_concentration(char, hab.get("nome", ""))
    return ("\n   Invocar Duplicação: uma cópia ilusória confunde os inimigos — vantagem nos seus ataques "
            "enquanto durar a concentração.")


def modos_palma(char: dict) -> dict:
    return {"vibrar": "Vibrar: o próximo golpe desarmado que acertar planta a vibração (1 ki)",
            "detonar": "Detonar: o alvo com a vibração faz CON; falha cai a 0 PV, sucesso leva 10d10 necrótico"}


def palma_vibrante(char, hab, alvo, modo):
    td = _td()
    if modo == "vibrar":
        td.dar_efeito_de_combate(char, {"nome": "Palma Vibrante", "golpe_ki": 1, "golpe_so_corpo": True,
                                        "golpe_condicao": {"nome": "Vibração", "salvaguarda": ""},
                                        "ate_fim_turno_de": _eu(char)})
        return "\n   Palma Vibrante pronta: o próximo golpe que acertar neste turno planta a vibração (1 ki)."
    a = _ch(alvo)
    marca = next((c for c in (a.get("sheet") or {}).get("condicoes") or []
                  if isinstance(c, dict) and c.get("nome") == "Vibração"
                  and memory.char_key(c.get("por", "")) == _eu(char)), None)
    if not marca:
        return f"\n   Palma Vibrante: {a['name']} não carrega a sua vibração."
    a["sheet"]["condicoes"].remove(marca)
    cd = 8 + int(char["sheet"].get("proficiencia", 2) or 2) + _mod(char, "sabedoria")
    passou, linha = td._rolar_salvaguarda(a, "constituicao", cd)
    if not passou:
        antes = int(a["sheet"].get("vida_atual", 0) or 0)
        a["sheet"]["vida_atual"] = 0
        return (f"\n   Palma Vibrante: {a['name']}: {linha} — o corpo cede ({antes} → 0)."
                + td._mark_at_zero_hp(a, char["name"]))
    rolls = [random.randint(1, 10) for _ in range(10)]
    res = td._apply_damage(a, sum(rolls), "necrotic", source_name=char["name"])
    return (f"\n   Palma Vibrante: {a['name']}: {linha} — 10d10 = {res['dano']} necrótico "
            f"({res['hp_antes']} → {res['hp_depois']}).")


def _zonas_ate(char: dict, passos: int) -> dict:
    td = _td()
    zonas = td._zonas()
    aqui = td._zona_de(char.get("name", ""))
    if aqui not in zonas:
        return {}
    i = zonas.index(aqui)
    return {z: z for j, z in enumerate(zonas) if 0 < abs(j - i) <= passos}


def modos_salto_sombrio(char: dict) -> dict:
    return _zonas_ate(char, 2)


def modos_teletransporte(char: dict) -> dict:
    return _zonas_ate(char, 1)


def _teleportar(char: dict, zona: str, rotulo: str) -> str:
    td = _td()
    if not td._zonas_ativas():
        return f"\n   {rotulo}: sem zonas, o motor não tem para onde mover. (Mestre: narre o salto.)"
    memory.campaign["combat_state"].setdefault("posicoes", {})[_eu(char)] = zona
    return f"\n   {rotulo}: {char['name']} reaparece em {zona}, sem ataque de oportunidade."


def salto_sombrio(char, hab, alvo, modo):
    _td().dar_efeito_de_combate(char, {"nome": "Salto Sombrio", "vantagem_ataque": True, "usos": 1,
                                       "ate_fim_turno_de": _eu(char)})
    return _teleportar(char, modo, "Salto Sombrio") + " Vantagem no próximo ataque corpo a corpo deste turno."


def manto_sombrio(char, hab, alvo, modo):
    _condicao(char, "Invisível", char, some_ao_atacar=True)
    return "\n   Manto Sombrio: nas sombras, invisível — até atacar ou conjurar, ou sair da escuridão."


def modos_conjuracao_elemental(char: dict) -> dict:
    return {"fogo": "Varredura de Fogo (2 ki): cone de chamas, 3d6 de fogo na zona, DES metade",
            "ar": "Punho do Ar Desatado (2 ki): FOR ou 3d10 de concussão e é empurrado"}


def conjuracao_elemental(char, hab, alvo, modo):
    td = _td()
    rs = _rs()
    cd = 8 + int(char["sheet"].get("proficiencia", 2) or 2) + _mod(char, "sabedoria")
    a = _ch(alvo)
    if modo == "fogo":
        afetados = [c for c in rs._combatentes_vivos() if c is not char and rs._perto(a, c)] if td._zonas_ativas() else [a]
        linhas = []
        rolls = [random.randint(1, 6) for _ in range(3)]
        for c in afetados:
            passou, linha = td._rolar_salvaguarda(c, "destreza", cd)
            dano = sum(rolls) // 2 if passou else sum(rolls)
            res = td._apply_damage(c, dano, "fire", source_name=char["name"], arma_magica=True)
            linhas.append(f"{c['name']}: {linha} — {res['dano']} de fogo ({res['hp_antes']} → {res['hp_depois']})")
            if res["hp_depois"] == 0 and res["hp_antes"] > 0:
                td._mark_at_zero_hp(c, char["name"])
        return (f"\n   Varredura de Fogo (3d6 [{' + '.join(map(str, rolls))}]):"
                + "".join(f"\n   • {l}" for l in linhas))
    passou, linha = td._rolar_salvaguarda(a, "forca", cd)
    rolls = [random.randint(1, 10) for _ in range(3)]
    if passou:
        return f"\n   Punho do Ar Desatado: {a['name']}: {linha} — firme."
    res = td._apply_damage(a, sum(rolls), "bludgeoning", source_name=char["name"], arma_magica=True)
    destino = rs._empurrar_para_longe(a, char) if td._zonas_ativas() else ""
    return (f"\n   Punho do Ar Desatado: {a['name']}: {linha} — 3d10 = {res['dano']} "
            f"({res['hp_antes']} → {res['hp_depois']})" + (f", empurrado para {destino}" if destino else "") + ".")


def terceiro_olho(char, hab, alvo, modo):
    _td().dar_efeito_de_combate(char, {"nome": "Terceiro Olho", "ver_invisivel": True})
    return "\n   Terceiro Olho: até o fim do combate, você vê o invisível."


def conjuracao_veloz(char, hab, alvo, modo):
    _td().dar_efeito_de_combate(char, {"nome": "Conjuração Veloz", "conjuracao_veloz": True,
                                       "ate_fim_turno_de": _eu(char)})
    return "\n   Conjuração Veloz: a próxima magia de conjuração deste turno sai como ação bônus."


def teletransporte_pequeno(char, hab, alvo, modo):
    s = char["sheet"]
    if s.get("_teleporte_token") == _token() and (memory.campaign.get("combat_state") or {}).get("is_active"):
        return "\n   Teletransporte Pequeno: uma vez por turno."
    s["_teleporte_token"] = _token()
    return _teleportar(char, modo, "Teletransporte Pequeno")


def asas_draconicas(char, hab, alvo, modo):
    _td().dar_efeito_de_combate(char, {"nome": "Asas Dracônicas", "movimento_por_turno": 1})
    return "\n   Asas Dracônicas: você voa — mais uma zona de movimento por turno até o fim do combate."


def modos_presenca(char: dict) -> dict:
    return {"medo": "Medo: quem falha fica Amedrontado", "admiracao": "Admiração: quem falha fica Enfeitiçado"}


def _aura_de_condicao(char: dict, hab: dict, modo: str, rotulo: str, ate_proximo_turno: bool) -> str:
    td = _td()
    cond = "Amedrontado" if modo in ("medo", "amedrontado") else "Enfeitiçado"
    linhas = []
    for c in _inimigos_perto(char):
        if td._imune_a_condicao(c, cond):
            linhas.append(f"{c['name']}: imune")
            continue
        passou, linha = td._rolar_salvaguarda(c, "sabedoria", _cd_car(char), contra=cond)
        if not passou:
            extra = ({"ate_fim_turno_de": _eu(char), "desde_token": _token()} if ate_proximo_turno
                     else {"magia": hab.get("nome", ""), "concentracao_de": _eu(char)})
            _condicao(c, cond, char, **extra)
        linhas.append(f"{c['name']}: {linha} — " + ("resiste" if passou else cond.upper()))
    if not linhas:
        return f"\n   {rotulo}: nenhum inimigo por perto."
    return f"\n   {rotulo}:" + "".join(f"\n   • {l}" for l in linhas)


def presenca_draconica(char, hab, alvo, modo):
    if _pontos(char) < 3:
        return f"\n   Presença Dracônica: precisa de 3 pontos de feitiçaria ({_pontos(char)})."
    _gastar_pontos(char, 3)
    _td()._start_concentration(char, hab.get("nome", ""))
    return _aura_de_condicao(char, hab, modo, "Presença Dracônica (3 pontos, concentração)", False)


def presenca_feerica(char, hab, alvo, modo):
    return _aura_de_condicao(char, hab, modo, "Presença Feérica", True)


def esculpir_o_caos(char, hab, alvo, modo):
    if _pontos(char) < 2:
        return f"\n   Esculpir o Caos: precisa de 2 pontos de feitiçaria ({_pontos(char)})."
    _gastar_pontos(char, 2)
    d100 = random.randint(1, 100)
    return (f"\n   Esculpir o Caos (2 pontos): Surto de Magia Selvagem, d100 = {d100}."
            f"\n   (Mestre: aplique o efeito {d100} da tabela de Surto de Magia Selvagem.)")


def apenas_para_mim(char, hab, alvo, modo):
    td = _td()
    a = _ch(alvo)
    if not _rs()._e_do_tipo(a, ("humanoid", "humanoide", "humano", "elfo", "anao", "orc", "goblin", "bandido",
                                "guarda", "mago", "cultista")):
        return f"\n   Apenas Para Mim: {a['name']} não é humanoide."
    passou, linha = td._rolar_salvaguarda(a, "sabedoria", _cd_car(char), contra="enfeiticado")
    if passou:
        return f"\n   Apenas Para Mim: {a['name']}: {linha} — resiste."
    _condicao(a, "Em Transe", char, salvaguarda_fim={"atributo": "sabedoria", "cd": _cd_car(char)})
    return f"\n   Apenas Para Mim: {a['name']}: {linha} — EM TRANSE (não age; SAB no fim de cada turno)."


def mestrado_grande_antigo(char, hab, alvo, modo):
    td = _td()
    rs = _rs()
    a = _ch(alvo)
    passou, linha = td._rolar_salvaguarda(a, "sabedoria", _cd_car(char))
    if passou:
        return f"\n   Mestrado do Grande Antigo: {a['name']}: {linha} — a mente dele resiste."
    vitimas = [c for c in rs._combatentes_vivos() if c is not a and rs._mesmo_lado(a, c) and rs._perto(a, c)]
    if not vitimas:
        return (f"\n   Mestrado do Grande Antigo: {a['name']}: {linha} — obedece, mas não há aliado dele ao "
                f"alcance. (Mestre: narre o que ele faz.)")
    arma = ((a.get("sheet") or {}).get("equipamentos") or {}).get("arma_principal") or "ataque desarmado"
    golpe = td.attack_roll(a["name"], vitimas[0]["name"], arma, 6, end_turn=False, _skip_turn_check=True)
    return (f"\n   Mestrado do Grande Antigo: {a['name']}: {linha} — ataca o próprio aliado:\n"
            + golpe.replace(td._BONUS_ACTION_HINT, ""))


EXECUTORES = {
    "maestria de feitico": maestria, "assinatura de feitico": assinatura, "metamagia": metamagia,
    "mestre sobrenatural": mestre_sobrenatural, "disparo magico": disparo_magico, "avatar sagrado": avatar_sagrado,
    "tornado de folhas": tornado_de_folhas, "anjo vingador": anjo_vingador, "ler pensamentos": ler_pensamentos,
    "coroa da luz": coroa_da_luz, "encantar animais e plantas": encantar_animais,
    "bencao do trapaceiro": bencao_do_trapaceiro, "invocar duplicacao": invocar_duplicacao,
    "palma vibrante": palma_vibrante, "salto sombrio": salto_sombrio, "manto sombrio": manto_sombrio,
    "conjuracao elemental": conjuracao_elemental, "terceiro olho": terceiro_olho,
    "conjuracao veloz": conjuracao_veloz, "teletransporte pequeno": teletransporte_pequeno,
    "asas draconicas": asas_draconicas, "presenca draconica": presenca_draconica,
    "presenca feerica": presenca_feerica, "esculpir o caos": esculpir_o_caos,
    "apenas para mim": apenas_para_mim, "mestrado do grande antigo": mestrado_grande_antigo,
}

MODOS = {
    "maestria de feitico": modos_maestria, "assinatura de feitico": modos_assinatura,
    "metamagia": modos_metamagia, "palma vibrante": modos_palma, "salto sombrio": modos_salto_sombrio,
    "teletransporte pequeno": modos_teletransporte, "conjuracao elemental": modos_conjuracao_elemental,
    "presenca draconica": modos_presenca, "presenca feerica": modos_presenca,
}

# A escolha que muda o alvo ou o custo.
ALVO_DO_MODO = {("palma vibrante", "detonar"): "inimigo", ("palma vibrante", "vibrar"): "si",
                ("metamagia", "gemea"): "aliado"}
SLOT_DO_MODO = {("palma vibrante", "detonar"): "acao", ("palma vibrante", "vibrar"): "livre"}


def validar(chave: str, char: dict, alvo: str, modo: str) -> str:
    td = _td()
    if chave == "disparo magico" and not _rs()._eco().get("conjurou"):
        return "Aviso: Disparo Mágico vale depois de conjurar uma magia neste turno. Nada foi gasto."
    if chave in ("salto sombrio", "manto sombrio") and not td._zona_obscurecida(char.get("name", "")):
        return ("Aviso: só funciona nas sombras — dentro de Escuridão ou Névoa (a luz da cena o Mestre "
                "decide; o motor confere a área de magia). Nada foi gasto.")
    if chave == "metamagia" and modo == "gemea" and not _ch(alvo):
        return "Aviso: escolha o segundo alvo da Magia Gêmea. Nada foi gasto."
    if chave == "palma vibrante" and modo == "detonar" and not _ch(alvo):
        return "Aviso: escolha quem carrega a vibração. Nada foi gasto."
    if chave == "metamagia" and METAMAGIAS.get(modo, ("", 0))[1] > _pontos(char):
        return f"Aviso: faltam pontos de feitiçaria para {METAMAGIAS[modo][0]}. Nada foi gasto."
    return ""


# ===========================================================================
# Ganchos de conjuração (chamados por rpg/tools_dnd.py)
# ===========================================================================

def conjuracao_rapida(char: dict, hab: dict) -> str:
    """
    O que faz esta magia de ação sair como ação bônus: "acelerada"
    (Metamagia), "veloz" (Conjuração Veloz, só escola de conjuração),
    "lunar" (Magias Lunares: Curar Ferimentos na Forma Selvagem), ou "".
    Não consome nada: quem chama consome depois que a magia sai.
    """
    td = _td()
    m = _rs()._magia_srd(hab) or {}
    if not m:
        return ""
    if metamagia_armada(char, "acelerada") and _pontos(char) >= 2:
        return "acelerada"
    if (any(e.get("conjuracao_veloz") for e in td._efeitos_de(char))
            and _rs().norm(m.get("escola", "")).startswith("conjura")):
        return "veloz"
    if (m.get("nome_srd") == "Cure Wounds" and td._tem_habilidade(char, "magias lunares")
            and (char.get("sheet") or {}).get("_forma_selvagem")):
        return "lunar"
    return ""


def consumir_rapida(char: dict, tipo: str) -> str:
    td = _td()
    if tipo == "acelerada":
        consumir_metamagia(char, "acelerada")
        return "\n   Magia Acelerada (2 pontos): saiu como ação bônus."
    if tipo == "veloz":
        s = char["sheet"]
        s["efeitos"] = [e for e in s.get("efeitos") or [] if not e.get("conjuracao_veloz")]
        td._gastar_uso(char, "Conjuração Veloz")
        return "\n   Conjuração Veloz: saiu como ação bônus."
    if tipo == "lunar":
        return "\n   Magias Lunares: Curar Ferimentos como ação bônus, na forma de fera."
    return ""


def lancar_gemea(ator: str, habilidade: str, modo: str) -> str:
    """Magia Gêmea: a magia de um alvo só, de novo no segundo alvo, sem mana (pontos = círculo)."""
    td = _td()
    char = _ch(ator)
    e = metamagia_armada(char, "gemea") if char else None
    if not e:
        return ""
    hab = next((h for h in char.get("habilidades") or [] if isinstance(h, dict)
                and _rs().norm(h.get("nome", "")) == _rs().norm(habilidade)), None)
    m = _rs()._magia_srd(hab or {}) or {}
    if not m or m.get("alvos") not in ("uma",) or td.area_da_habilidade(hab) or m.get("origem") == "si":
        return "\n   Magia Gêmea: esta magia não tem um alvo só — a metamagia continua pronta."
    custo = max(1, int(m.get("nivel", 0) or 0))
    if not consumir_metamagia(char, "gemea", custo):
        return f"\n   Magia Gêmea: faltam pontos de feitiçaria ({custo})."
    segundo = td.use_ability(ator, habilidade, e.get("gemea_alvo", ""), end_turn=False,
                             _skip_turn_check=True, modo=modo, _sem_custo=True)
    return f"\n   Magia Gêmea ({custo} pontos), em {e.get('gemea_alvo')}:\n" + segundo


def surto(char: dict, hab: dict) -> str:
    """Surto de Magia Selvagem: magia de 1º círculo ou mais, d20; no 1, o d100 da tabela."""
    if not _td()._tem_habilidade(char, "surto de magia selvagem"):
        return ""
    m = _rs()._magia_srd(hab) or {}
    if int(m.get("nivel", 0) or 0) < 1:
        return ""
    d20 = random.randint(1, 20)
    if d20 != 1:
        return ""
    d100 = random.randint(1, 100)
    return (f"\n   SURTO DE MAGIA SELVAGEM (d20 = 1): d100 = {d100}."
            f"\n   (Mestre: aplique o efeito {d100} da tabela de Surto de Magia Selvagem.)")


def coroa_contra(alvo: dict, hab: dict) -> bool:
    """Coroa da Luz: o inimigo de quem a tem faz com desvantagem a salvaguarda contra fogo e radiante."""
    td = _td()
    m = _rs()._magia_srd(hab) or {}
    tipo = td._norm_damage_type(m.get("tipo_dano", "") or (hab or {}).get("tipo_dano", "") or "")
    if tipo not in ("fire", "radiant"):
        return False
    for c in _rs()._combatentes_vivos():
        if (not _rs()._mesmo_lado(c, alvo)
                and any(e.get("coroa_da_luz") for e in td._efeitos_de(c))):
            return True
    return False
