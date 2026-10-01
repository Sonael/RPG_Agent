"""
test_subclasses.py

As características de subclasse e de nível alto que caíam em "o Mestre
decide" (rpg/subclasses.py e as reações em rpg/reacoes.py).
"""
import random

import pytest

from rpg import criaturas, memory, reacoes, resolucao, subclasses, tools_dnd as td

from conftest import criar_ficha, iniciar_combate


def _ch(nome):
    return memory.campaign["characters"].get(memory.char_key(nome))


def _hab(nome, custo=0):
    m = resolucao._magia_srd({"nome": nome})
    h = {"nome": nome, "custo_mana": custo, "dado": "", "descricao": "[Magia] " if m else ""}
    if m:
        h["nivel_magia"] = m.get("nivel", 0)
    return h


def _vez(nome):
    cs = memory.campaign["combat_state"]
    cs["current_turn_index"] = cs["initiative_order"].index(nome)
    cs["turn_token"] = int(cs.get("turn_token", 0) or 0) + 1
    td._reset_turn_economy(cs)


def _usar(ator, hab, alvo="", modo=""):
    _vez(ator)
    return td.combat_action("ability", actor=ator, ability=hab, target=alvo, weapon=modo)


def _d20(monkeypatch, valor):
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda *a, **k: (valor, f"d20={valor}"))


def _salva(monkeypatch, passa):
    monkeypatch.setattr(td, "_rolar_salvaguarda", lambda *a, **k: (passa, "salvaguarda: " + ("passou" if passa else "falhou")))


def _luta(povoar, *heroes, inimigos=("Orc", "Ogro")):
    povoar(*heroes, *[criar_ficha(n, vida=80, ca=10, arma="machado grande") for n in inimigos])
    ordem = [h["name"] for h in heroes] + list(inimigos)
    iniciar_combate(ordem)
    _vez(ordem[0])


NOMES = ["Maestria de Feitiço", "Assinatura de Feitiço", "Metamagia", "Mestre Sobrenatural", "Disparo Mágico",
         "Avatar Sagrado", "Canalizar Divindade (Tornado de Folhas)", "Anjo Vingador",
         "Canalizar Divindade (Ler Pensamentos)", "Coroa da Luz", "Canalizar Divindade (Encantar Animais e Plantas)",
         "Bênção do Trapaceiro", "Canalizar Divindade (Invocar Duplicação)", "Palma Vibrante Trêmula",
         "Salto Sombrio", "Manto Sombrio", "Conjuração Elemental", "Terceiro Olho", "Conjuração Veloz",
         "Teletransporte Pequeno", "Asas Dracônicas", "Presença Dracônica", "Esculpir o Caos", "Presença Feérica",
         "Apenas Para Mim", "Mestrado do Grande Antigo"]
PASSIVAS = ["Inspiração Bárdica Aprimorada", "Inspiração Superior Aprimorada", "Visão Aprofundada",
            "Lampejos Aprimorados", "Atleta Notável", "Bênção do Trapaceiro Aprimorada", "Magias Lunares",
            "Restauração de Feitiçaria", "Inimigo do Inimigo", "Surto de Magia Selvagem",
            "Encontrar Familiar Aprimorado"]
REACOES = ["Golpe Mágico", "Marca da Vingança", "Oportunista", "Recuperação Bestial", "Mudança Imediata",
           "Resistência Mágica Projetada", "Refúgio Feérico", "Vingança do Grande Antigo",
           "Lampejos de Adivinhação"]


@pytest.mark.parametrize("nome", NOMES)
def test_cartao_acao(nome):
    d = td.CLASS_FEATURE_DESCS.get(nome, {})
    assert resolucao.como_resolve({"nome": nome, "descricao": d.get("descricao", "")})["tipo"] == "acao_de_classe", nome


@pytest.mark.parametrize("nome", PASSIVAS)
def test_cartao_passiva(nome):
    d = td.CLASS_FEATURE_DESCS.get(nome, {})
    r = resolucao.como_resolve({"nome": nome, "descricao": d.get("descricao", "")})
    assert r["tipo"] == "passiva" and "motor" in r["texto"], (nome, r)


@pytest.mark.parametrize("nome", REACOES)
def test_cartao_reacao(nome):
    d = td.CLASS_FEATURE_DESCS.get(nome, {})
    assert resolucao.como_resolve({"nome": nome, "descricao": d.get("descricao", "")})["tipo"] == "reacao", nome


# ---------------------------------------------------------------------------
# Mago: Maestria, Assinatura, Lampejos, Terceiro Olho, Conjuração Veloz
# ---------------------------------------------------------------------------

def test_maestria_escolhe_e_a_magia_sai_sem_mana(campanha, povoar):
    _luta(povoar, criar_ficha("Mira", grupo=True, classe="mago", nivel=18, mana=100,
                              habilidades=[_hab("Maestria de Feitiço"), _hab("Shield", 2), _hab("Magic Missile", 2),
                                           _hab("Misty Step", 3)]))
    assert set(resolucao.modos_de("maestria de feitico", _ch("Mira"))) == {"Shield", "Magic Missile", "Misty Step"}
    assert _usar("Mira", "Maestria de Feitiço", modo="Magic Missile")["ok"]
    _usar("Mira", "Magic Missile", "Orc")
    assert _ch("Mira")["sheet"]["mana_atual"] == 100
    # Outra do mesmo círculo substitui.
    _usar("Mira", "Maestria de Feitiço", modo="Shield")
    assert td._get_feature_choice(_ch("Mira"), "Maestria de Feitiço") == ["Shield"]


def test_assinatura_uma_vez_por_descanso_curto(campanha, povoar):
    povoar(criar_ficha("Mira", grupo=True, classe="mago", nivel=20, mana=133,
                       habilidades=[_hab("Assinatura de Feitiço"), _hab("Fireball", 5)],
                       feature_choices={"Assinatura de Feitiço": ["Fireball"]}),
           criar_ficha("Orc", vida=200))
    td.use_ability("Mira", "Fireball", "Orc", end_turn=False)
    assert _ch("Mira")["sheet"]["mana_atual"] == 133
    td.use_ability("Mira", "Fireball", "Orc", end_turn=False)
    assert _ch("Mira")["sheet"]["mana_atual"] == 128
    td.short_rest("Mira")
    td.use_ability("Mira", "Fireball", "Orc", end_turn=False)
    assert _ch("Mira")["sheet"]["mana_atual"] == 128


def test_lampejo_faz_o_golpe_inimigo_errar(campanha, povoar, monkeypatch):
    _luta(povoar, criar_ficha("Mira", grupo=True, classe="mago", nivel=14, habilidades=[_hab("Lampejos de Adivinhação"),
                                                                                       _hab("Visão Aprofundada")]),
          criar_ficha("Alden", grupo=True, ca=15, vida=40))
    _ch("Mira")["sheet"]["lampejos"] = [2, 19, 11]
    _d20(monkeypatch, 15)                  # 15 + 3 + 2 = 20 vs 15: acertaria
    saida = td.attack_roll("Orc", "Alden", "machado grande", 12, end_turn=False, _skip_turn_check=True)
    assert "Lampejo" in saida and "ERROU" in saida, saida
    assert _ch("Mira")["sheet"]["lampejos"] == [19, 11]


def test_lampejo_salva_a_salvaguarda(campanha, povoar, monkeypatch):
    povoar(criar_ficha("Mira", grupo=True, classe="mago", nivel=2, habilidades=[_hab("Lampejos de Adivinhação")]),
           criar_ficha("Alden", grupo=True))
    _ch("Mira")["sheet"]["lampejos"] = [18, 3]
    monkeypatch.setattr(random, "randint", lambda a, b: 2)
    passou, linha = td._rolar_salvaguarda(_ch("Alden"), "sabedoria", 15)
    assert passou and "Lampejo" in linha
    assert _ch("Mira")["sheet"]["lampejos"] == [3]


def test_lampejos_rolados_no_descanso(campanha, povoar):
    povoar(criar_ficha("Mira", grupo=True, classe="mago", nivel=14,
                       habilidades=[_hab("Lampejos de Adivinhação"), _hab("Visão Aprofundada")]))
    assert len(reacoes._lampejos(_ch("Mira"))) == 3
    td.long_rest("Mira")
    assert "lampejos" not in _ch("Mira")["sheet"]


def test_conjuracao_veloz_vira_acao_bonus(campanha, povoar):
    _luta(povoar, criar_ficha("Mira", grupo=True, classe="mago", nivel=10, mana=60,
                              habilidades=[_hab("Conjuração Veloz"), _hab("Misty Step", 3), _hab("Fire Bolt"),
                                           _hab("Conjure Woodland Beings", 6)]))
    assert _usar("Mira", "Conjuração Veloz")["ok"]
    cs = memory.campaign["combat_state"]
    r = td.combat_action("ability", actor="Mira", ability="Conjure Woodland Beings", weapon="satiro:4")
    assert r["ok"] and cs["turn_economy"]["bonus_usada"] and not cs["turn_economy"]["acao_usada"], r["message"]


def test_terceiro_olho(campanha, povoar):
    _luta(povoar, criar_ficha("Mira", grupo=True, classe="mago", nivel=6, habilidades=[_hab("Terceiro Olho")]))
    assert _usar("Mira", "Terceiro Olho")["ok"]
    assert td._ve_invisivel(_ch("Mira"))
    assert not _usar("Mira", "Terceiro Olho")["ok"]


# ---------------------------------------------------------------------------
# Feiticeiro: Metamagia, Surto, Presença, Asas, Esculpir o Caos, Restauração
# ---------------------------------------------------------------------------

def _feiticeiro(habilidades=None, **extra):
    return criar_ficha("Sol", grupo=True, classe="feiticeiro", nivel=10, carisma=18, mana=64,
                       habilidades=habilidades or [_hab("Metamagia"), _hab("Fonte de Magia"), _hab("Fire Bolt"),
                                                   _hab("Hold Person", 3), _hab("Fireball", 5),
                                                   _hab("Scorching Ray", 3)], **extra)


def test_metamagia_acelerada(campanha, povoar):
    _luta(povoar, _feiticeiro())
    assert _usar("Sol", "Metamagia", modo="acelerada")["ok"]
    cs = memory.campaign["combat_state"]
    r = td.combat_action("ability", actor="Sol", ability="Fire Bolt", target="Orc")
    assert r["ok"] and cs["turn_economy"]["bonus_usada"] and not cs["turn_economy"]["acao_usada"], r["message"]
    assert td.usos_restantes(_ch("Sol"), "Fonte de Magia") == 8


def test_metamagia_gemea(campanha, povoar, monkeypatch):
    _luta(povoar, _feiticeiro())
    _salva(monkeypatch, False)
    assert _usar("Sol", "Metamagia", "Ogro", "gemea")["ok"]
    r = td.combat_action("ability", actor="Sol", ability="Hold Person", target="Orc")
    assert "Magia Gêmea" in r["message"], r["message"]
    assert td._impedido_de_agir(_ch("Orc")) and td._impedido_de_agir(_ch("Ogro"))
    assert _ch("Sol")["sheet"]["mana_atual"] == 61                      # uma vez só
    assert td.usos_restantes(_ch("Sol"), "Fonte de Magia") == 8          # 2º círculo: 2 pontos


def test_metamagia_cuidadosa_e_intensificada(campanha, povoar, monkeypatch):
    _luta(povoar, _feiticeiro(), criar_ficha("Alden", grupo=True, vida=60))
    cs = memory.campaign["combat_state"]
    cs["zonas"] = ["A", "B"]
    cs["posicoes"] = {"sol": "A", "alden": "B", "orc": "B", "ogro": "B"}
    pedidos = []

    def salvar(alvo, attr, cd, vantagem=False, desvantagem=False, contra=""):
        pedidos.append((alvo["name"], desvantagem))
        return False, "falhou"
    monkeypatch.setattr(td, "_rolar_salvaguarda", salvar)
    _usar("Sol", "Metamagia", modo="cuidadosa")
    _vez("Sol")
    td.dar_efeito_de_combate(_ch("Sol"), {"nome": "Magia Intensificada", "metamagia": "intensificada",
                                          "ate_fim_turno_de": "sol"})
    r = td.combat_action("ability", actor="Sol", ability="Fireball", target="Orc")
    assert "Cuidadosa" in r["message"] and "Alden: " in r["message"], r["message"]
    assert "Alden" not in [p[0] for p in pedidos]            # aliado passa sem rolar
    assert pedidos[0][1] is True and all(not d for _, d in pedidos[1:])


def test_metamagia_sutil_passa_pelo_silencio_e_pela_contramagica(campanha, povoar):
    _luta(povoar, _feiticeiro(), criar_ficha("Necro", vida=40, mana=20, habilidades=[_hab("Counterspell", 5)]),
          inimigos=("Orc",))
    _ch("Necro")["lado"] = "inimigo"
    memory.campaign["combat_state"]["efeitos_de_zona"] = [
        {"criatura": "sol", "tipo": "silencio", "nome": "Silêncio", "concentracao_de": ""}]
    assert _usar("Sol", "Hold Person", "Orc").get("ok") is False
    _usar("Sol", "Metamagia", modo="sutil")
    r = td.combat_action("ability", actor="Sol", ability="Hold Person", target="Orc")
    assert r["ok"] and "Sutil" in r["message"] and "Contramágica" not in r["message"], r["message"]


def test_surto_de_magia_selvagem(campanha, povoar, monkeypatch):
    povoar(criar_ficha("Sol", grupo=True, classe="feiticeiro", nivel=3, mana=14,
                       habilidades=[_hab("Surto de Magia Selvagem"), _hab("Magic Missile", 2)]),
           criar_ficha("Orc", vida=100))
    monkeypatch.setattr(random, "randint", lambda a, b: 1)
    saida = td.use_ability("Sol", "Magic Missile", "Orc", end_turn=False)
    assert "SURTO DE MAGIA SELVAGEM" in saida and "d100 = 1" in saida


def test_restauracao_de_feiticaria(campanha, povoar):
    povoar(criar_ficha("Sol", grupo=True, classe="feiticeiro", nivel=20, habilidades=[
        _hab("Restauração de Feitiçaria"), _hab("Fonte de Magia")]))
    _ch("Sol")["sheet"]["usos"] = {"pontos de feiticaria": 5}
    _ch("Sol")["sheet"]["vida_atual"] = 10
    td.short_rest("Sol", 0)
    assert td.usos_restantes(_ch("Sol"), "Fonte de Magia") == 9


def test_presenca_draconica_gasta_tres_pontos(campanha, povoar, monkeypatch):
    _luta(povoar, _feiticeiro(habilidades=[_hab("Presença Dracônica"), _hab("Fonte de Magia")]))
    _salva(monkeypatch, False)
    assert _usar("Sol", "Presença Dracônica", modo="medo")["ok"]
    assert any(c["nome"] == "Amedrontado" for c in _ch("Orc")["sheet"]["condicoes"])
    assert td.usos_restantes(_ch("Sol"), "Fonte de Magia") == 7


def test_esculpir_o_caos_e_asas(campanha, povoar):
    _luta(povoar, _feiticeiro(habilidades=[_hab("Esculpir o Caos"), _hab("Asas Dracônicas"), _hab("Fonte de Magia")]))
    r = _usar("Sol", "Esculpir o Caos")
    assert "d100" in r["message"] and td.usos_restantes(_ch("Sol"), "Fonte de Magia") == 8
    _usar("Sol", "Asas Dracônicas")
    _vez("Sol")
    assert memory.campaign["combat_state"]["turn_economy"]["movimento_extra"] == 1


# ---------------------------------------------------------------------------
# Clérigo, paladino
# ---------------------------------------------------------------------------

def test_coroa_da_luz_desvantagem_contra_fogo(campanha, povoar, monkeypatch):
    _luta(povoar, criar_ficha("Kae", grupo=True, classe="clérigo", nivel=17, mana=100,
                              habilidades=[_hab("Coroa da Luz"), _hab("Fireball", 5), _hab("Hold Person", 3)]))
    _usar("Kae", "Coroa da Luz")
    assert subclasses.coroa_contra(_ch("Orc"), _hab("Fireball"))
    assert not subclasses.coroa_contra(_ch("Orc"), _hab("Hold Person"))


def test_tornado_de_folhas_e_ler_pensamentos(campanha, povoar, monkeypatch):
    _luta(povoar, criar_ficha("Kae", grupo=True, classe="clérigo", nivel=6, habilidades=[
        _hab("Canalizar Divindade (Tornado de Folhas)"), _hab("Canalizar Divindade (Ler Pensamentos)")]))
    _salva(monkeypatch, False)
    assert _usar("Kae", "Canalizar Divindade (Tornado de Folhas)", "Orc")["ok"]
    assert any(c["nome"] == "Amedrontado" for c in _ch("Orc")["sheet"]["condicoes"])
    r = _usar("Kae", "Canalizar Divindade (Ler Pensamentos)", "Ogro")
    assert r["ok"] and "Mestre" in r["message"]
    # Os dois gastam o Canalizar Divindade (2 no 6º nível).
    assert td.usos_restantes(_ch("Kae"), "Canalizar Divindade") == 0


def test_invocar_duplicacao_e_bencao_do_trapaceiro(campanha, povoar, monkeypatch):
    _luta(povoar, criar_ficha("Kae", grupo=True, classe="clérigo", nivel=17, habilidades=[
        _hab("Canalizar Divindade (Invocar Duplicação)"), _hab("Bênção do Trapaceiro"),
        _hab("Bênção do Trapaceiro Aprimorada")]), criar_ficha("Alden", grupo=True))
    _usar("Kae", "Canalizar Divindade (Invocar Duplicação)")
    assert td._mods_de_ataque(_ch("Kae"), _ch("Orc"), True)["vantagem"]
    r = _usar("Kae", "Bênção do Trapaceiro", "Alden")
    assert r["ok"] and memory.campaign["combat_state"]["turn_economy"]["bonus_usada"]
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda v, d: (10, "d20=10") if v else (1, "d20=1"))
    assert "= **11**" in td.make_skill_check("Alden", "destreza", 15, skill="furtividade")


def test_encantar_animais(campanha, povoar, monkeypatch):
    povoar(criar_ficha("Kae", grupo=True, classe="clérigo", nivel=6,
                       habilidades=[_hab("Canalizar Divindade (Encantar Animais e Plantas)")]),
           criar_ficha("Lobo", vida=11, tipo="beast"), criar_ficha("Orc", vida=20))
    iniciar_combate(["Kae", "Lobo", "Orc"])
    _salva(monkeypatch, False)
    _usar("Kae", "Canalizar Divindade (Encantar Animais e Plantas)")
    assert any(c["nome"] == "Enfeitiçado" for c in _ch("Lobo")["sheet"]["condicoes"])
    assert not _ch("Orc")["sheet"]["condicoes"]


def test_avatar_e_anjo(campanha, povoar, monkeypatch):
    _luta(povoar, criar_ficha("Brann", grupo=True, classe="paladino", nivel=20, carisma=18,
                              habilidades=[_hab("Avatar Sagrado"), _hab("Anjo Vingador")]),
          criar_ficha("Alden", grupo=True, vida=40))
    _usar("Brann", "Avatar Sagrado")
    assert td._apply_damage(_ch("Alden"), 10, "fire", source_name="Orc")["dano"] == 5
    assert not _usar("Brann", "Avatar Sagrado")["ok"]
    _salva(monkeypatch, False)
    _usar("Brann", "Anjo Vingador")
    assert any(c["nome"] == "Amedrontado" for c in _ch("Orc")["sheet"]["condicoes"])


def test_marca_da_vinganca(campanha, povoar, monkeypatch):
    _luta(povoar, criar_ficha("Brann", grupo=True, classe="paladino", nivel=15, habilidades=[_hab("Marca da Vingança")]),
          criar_ficha("Alden", grupo=True, vida=60, ca=10))
    _d20(monkeypatch, 15)
    saida = td.attack_roll("Orc", "Alden", "machado grande", 12, end_turn=False, _skip_turn_check=True)
    assert "Brann usa Marca da Vingança" in saida and "Brann ataca Orc" in saida, saida


# ---------------------------------------------------------------------------
# Monge, ladino, patrulheiro, guerreiro
# ---------------------------------------------------------------------------

def _monge(habilidades=None, **extra):
    return criar_ficha("Lin", grupo=True, classe="monge", nivel=17, destreza=18, sabedoria=16, arma="ataque desarmado",
                       habilidades=[_hab("Artes Marciais"), _hab("Ki"), _hab("Palma Vibrante Trêmula"),
                                    _hab("Conjuração Elemental"), _hab("Oportunista")] + list(habilidades or []),
                       **extra)


def test_palma_vibrante(campanha, povoar, monkeypatch):
    _luta(povoar, _monge())
    _usar("Lin", "Palma Vibrante Trêmula", modo="vibrar")
    _d20(monkeypatch, 18)
    td.attack_roll("Lin", "Orc", "ataque desarmado", 6, end_turn=False, _skip_turn_check=True)
    assert any(c["nome"] == "Vibração" for c in _ch("Orc")["sheet"]["condicoes"])
    assert td.usos_restantes(_ch("Lin"), "Ki") == 16
    _salva(monkeypatch, False)
    r = _usar("Lin", "Palma Vibrante Trêmula", "Orc", "detonar")
    assert r["ok"] and _ch("Orc")["sheet"]["vida_atual"] == 0, r["message"]


def test_conjuracao_elemental(campanha, povoar, monkeypatch):
    _luta(povoar, _monge())
    _salva(monkeypatch, False)
    r = _usar("Lin", "Conjuração Elemental", "Orc", "ar")
    assert r["ok"] and _ch("Orc")["sheet"]["vida_atual"] < 80
    assert td.usos_restantes(_ch("Lin"), "Ki") == 15


def test_oportunista(campanha, povoar, monkeypatch):
    _luta(povoar, _monge(), criar_ficha("Alden", grupo=True))
    _d20(monkeypatch, 18)
    saida = td.attack_roll("Alden", "Orc", "espada longa", 8, end_turn=False, _skip_turn_check=True)
    assert "Lin usa Oportunista" in saida, saida


def test_salto_e_manto_sombrio_so_nas_sombras(campanha, povoar):
    _luta(povoar, _monge(habilidades=[_hab("Salto Sombrio"), _hab("Manto Sombrio")]))
    cs = memory.campaign["combat_state"]
    cs["zonas"] = ["A", "B", "C"]
    cs["posicoes"] = {"lin": "A", "orc": "B", "ogro": "C"}
    assert not _usar("Lin", "Manto Sombrio")["ok"]
    cs["efeitos_de_zona"] = [{"zona": "A", "tipo": "escuridao", "nome": "Escuridão"}]
    assert _usar("Lin", "Manto Sombrio")["ok"] and td._invisivel(_ch("Lin"))
    assert _usar("Lin", "Salto Sombrio", modo="C")["ok"] and td._zona_de("Lin") == "C"


def test_atleta_notavel_e_inimigo_do_inimigo(campanha, povoar, monkeypatch):
    _luta(povoar, criar_ficha("Tor", grupo=True, nivel=7, habilidades=[_hab("Atleta Notável"),
                                                                      _hab("Inimigo do Inimigo")]))
    pedidos = []
    monkeypatch.setattr(td, "_roll_d20_with_adv", lambda v, d: (pedidos.append(v), (15, "d20=15"))[1])
    td.make_skill_check("Tor", "forca", 15, skill="atletismo")
    assert pedidos == [True]
    saida = td.attack_roll("Tor", "Orc", "espada longa", 8, end_turn=False, _skip_turn_check=True)
    assert "Inimigo do Inimigo" in saida
    saida = td.attack_roll("Tor", "Orc", "espada longa", 8, end_turn=False, _skip_turn_check=True)
    assert "Inimigo do Inimigo" not in saida                       # uma vez por turno


def test_golpe_magico(campanha, povoar, monkeypatch):
    _luta(povoar, criar_ficha("Ela", grupo=True, classe="guerreiro", nivel=7, inteligencia=16,
                              habilidades=[_hab("Golpe Mágico"), _hab("Fire Bolt")]))
    _d20(monkeypatch, 18)
    saida = td.attack_roll("Ela", "Orc", "espada longa", 8, end_turn=False, _skip_turn_check=True)
    assert "Golpe Mágico" in saida and "Fire Bolt" in saida, saida


def test_disparo_magico_depois_de_conjurar(campanha, povoar, monkeypatch):
    _luta(povoar, criar_ficha("Ela", grupo=True, classe="mago", nivel=7, mana=30,
                              habilidades=[_hab("Disparo Mágico"), _hab("Fire Bolt")]))
    assert not _usar("Ela", "Disparo Mágico", "Orc")["ok"]
    _vez("Ela")
    _d20(monkeypatch, 18)
    td.combat_action("ability", actor="Ela", ability="Fire Bolt", target="Orc")
    r = td.combat_action("ability", actor="Ela", ability="Disparo Mágico", target="Orc")
    assert r["ok"] and "Ela ataca Orc" in r["message"], r["message"]


# ---------------------------------------------------------------------------
# Druida, bruxo, bardo
# ---------------------------------------------------------------------------

def test_magias_lunares_e_mudanca_imediata(campanha, povoar, monkeypatch):
    _luta(povoar, criar_ficha("Ravi", grupo=True, classe="druida", nivel=8, vida=40, mana=40,
                              habilidades=[_hab("Forma Selvagem"), _hab("Mudança Imediata"),
                                           _hab("Magias Lunares"), _hab("Cure Wounds", 2)]))
    _d20(monkeypatch, 18)
    saida = td.attack_roll("Orc", "Ravi", "machado grande", 12, end_turn=False, _skip_turn_check=True)
    assert "Mudança Imediata" in saida and criaturas.em_forma_selvagem(_ch("Ravi")), saida
    assert _ch("Ravi")["sheet"]["vida_max"] != 40                  # a fera levou o golpe
    r = _usar("Ravi", "Cure Wounds", "Ravi")
    assert r["ok"] and memory.campaign["combat_state"]["turn_economy"]["bonus_usada"], r["message"]


def test_recuperacao_bestial(campanha, povoar, monkeypatch):
    _luta(povoar, criar_ficha("Rae", grupo=True, classe="patrulheiro", nivel=7, vida=50,
                              habilidades=[_hab("Recuperação Bestial"), _hab("Conjure Animals", 5)], mana=30))
    _usar("Rae", "Conjure Animals", modo="lobo atroz:2")
    _d20(monkeypatch, 18)
    saida = td.attack_roll("Orc", "Lobo Atroz de Rae 1", "machado grande", 12, end_turn=False, _skip_turn_check=True)
    assert "Recuperação Bestial" in saida, saida
    assert _ch("Lobo Atroz de Rae 1")["sheet"]["vida_atual"] == 37 and _ch("Rae")["sheet"]["vida_atual"] < 50


def test_bruxo_vinganca_refugio_apenas_para_mim_mestrado(campanha, povoar, monkeypatch):
    _luta(povoar, criar_ficha("Zed", grupo=True, classe="bruxo", nivel=14, carisma=18, vida=60,
                              habilidades=[_hab("Vingança do Grande Antigo"), _hab("Refúgio Feérico"),
                                           _hab("Apenas Para Mim"), _hab("Mestrado do Grande Antigo"),
                                           _hab("Mestre Sobrenatural")]),
          inimigos=("Bandido", "Ogro"))
    _d20(monkeypatch, 2)
    saida = td.attack_roll("Bandido", "Zed", "machado grande", 12, end_turn=False, _skip_turn_check=True)
    assert "Vingança do Grande Antigo" in saida and _ch("Bandido")["sheet"]["vida_atual"] == 80 - 5, saida
    memory.campaign["combat_state"]["round"] = 2
    _d20(monkeypatch, 18)
    saida = td.attack_roll("Ogro", "Zed", "machado grande", 12, end_turn=False, _skip_turn_check=True)
    assert "Refúgio Feérico" in saida and td._invisivel(_ch("Zed")), saida
    _salva(monkeypatch, False)
    assert _usar("Zed", "Apenas Para Mim", "Bandido")["ok"]
    assert td._impedido_de_agir(_ch("Bandido"))
    _ch("Zed")["sheet"]["mana_atual"] = 0
    _ch("Zed")["sheet"]["mana_max"] = 30
    _usar("Zed", "Mestre Sobrenatural")
    assert _ch("Zed")["sheet"]["mana_atual"] == td.SPELL_MANA_COST[5]


def test_familiar_do_pacto_ataca(campanha, povoar):
    povoar(criar_ficha("Zed", grupo=True, classe="bruxo", nivel=3, mana=14,
                       habilidades=[_hab("Encontrar Familiar Aprimorado"), _hab("Find Familiar", 2)]))
    modos = resolucao.como_resolve(_hab("Find Familiar", 2), _ch("Zed"))["modos"]
    assert "diabrete:1" in modos
    assert td.conjurar_fora_de_combate("Zed", "Find Familiar", modo="diabrete:1")["ok"]
    assert _ch("Diabrete de Zed")
    # A coruja, que como familiar comum não ataca, no Pacto da Corrente ataca.
    _ch("Zed")["sheet"]["mana_atual"] = 14
    assert td.conjurar_fora_de_combate("Zed", "Find Familiar", modo="coruja:1")["ok"]
    assert not _ch("Coruja de Zed")["sheet"].get("nao_ataca")


def test_inspiracao_superior_ao_rolar_iniciativa(campanha, povoar):
    povoar(criar_ficha("Bia", grupo=True, classe="bardo", nivel=20, carisma=18,
                       habilidades=[_hab("Inspiração de Bardo"), _hab("Inspiração Superior Aprimorada")]),
           criar_ficha("Orc"))
    _ch("Bia")["sheet"]["usos"] = {"inspiracao de bardo": 0}
    td.roll_initiative("Bia, Orc")
    assert td.usos_restantes(_ch("Bia"), "Inspiração de Bardo") == 4


def test_resistencia_magica_projetada(campanha, povoar, monkeypatch):
    povoar(criar_ficha("Ivo", grupo=True, classe="mago", nivel=10, sabedoria=20,
                       habilidades=[_hab("Resistência Mágica Projetada")]),
           criar_ficha("Alden", grupo=True, sabedoria=8), criar_ficha("Orc"))
    iniciar_combate(["Ivo", "Alden", "Orc"])
    monkeypatch.setattr(random, "randint", lambda a, b: 10)
    passou, linha = td._rolar_salvaguarda(_ch("Alden"), "sabedoria", 15)
    assert passou and "Projetada" in linha, linha
