"""
test_grimorio.py

O motor sempre soube APRENDER uma magia. O que ele não sabia era quantas o
personagem podia ter: a tabela de truques e magias conhecidas vivia só no
JavaScript do modal de edição, e o learn_spell — o caminho do mestre — dava a
décima magia a um clérigo de nível 3 sem reclamar.

Junto com a tela vieram quatro correções no learn_spell, todas do mesmo feitio
(a regra existia num lugar e não no outro):

1. LIMITE de truques e magias, agora no motor.
2. NÍVEL de magia por tipo de conjurador: a regra era 2L−1 para todos, e um
   paladino de nível 3 aprendia magia de 2º círculo.
3. SEM CONEXÃO, qualquer nome entrava na ficha com custo 4 e sem checagem.
4. A busca aproximada devolvia a primeira magia da lista mesmo sem nenhuma
   palavra em comum com o nome pedido.

E a ficha passa a gravar `nivel_magia` e `nome_srd`: sem eles a contagem
adivinhava pelo custo, e "Bola de Fogo" e "Fireball" eram magias diferentes.
"""
import pytest

from rpg import memory, open5e, tools_dnd as td

from conftest import criar_ficha


# ---------------------------------------------------------------------------
# Um SRD de mentira, pequeno: o Open5e fica offline na suíte
# ---------------------------------------------------------------------------

def _sp(nome, nivel, classes, escola="Evocation", desc="", dado="", conc="no", ritual="no"):
    # Como no Open5e v1: sim/não chegam como TEXTO "yes"/"no".
    return {"name": nome, "slug": nome.lower().replace(" ", "-").replace("'", ""),
            "spell_level": nivel, "dnd_class": classes, "school": escola,
            "desc": desc or f"{nome} does something magical.", "range": "60 feet",
            "concentration": conc, "ritual": ritual, "document__slug": "wotc-srd",
            "damage": {"damage_dice": dado}}


SRD = [
    _sp("Fire Bolt", 0, "Sorcerer, Wizard", dado="1d10"),
    _sp("Light", 0, "Bard, Cleric, Sorcerer, Wizard"),
    _sp("Sacred Flame", 0, "Cleric", dado="1d8"),
    _sp("Guidance", 0, "Cleric, Druid", escola="Divination"),
    _sp("Spare the Dying", 0, "Cleric", escola="Necromancy"),
    _sp("Magic Missile", 1, "Sorcerer, Wizard", dado="1d4"),
    _sp("Shield", 1, "Sorcerer, Wizard", escola="Abjuration"),
    _sp("Cure Wounds", 1, "Bard, Cleric, Druid, Paladin, Ranger", dado="1d8"),
    _sp("Bless", 1, "Cleric, Paladin", escola="Enchantment", conc="yes"),
    _sp("Aid", 2, "Cleric, Paladin", escola="Abjuration"),
    _sp("Misty Step", 2, "Sorcerer, Warlock, Wizard", escola="Conjuration"),
    _sp("Fireball", 3, "Sorcerer, Wizard", dado="8d6"),
]


PEDIDOS = []


@pytest.fixture
def srd(monkeypatch):
    PEDIDOS.clear()

    def falso(url, params=None, timeout=5.0):
        params = params or {}
        PEDIDOS.append((url, dict(params)))
        if "/spells/" not in url:
            return open5e.Response(ok=False, data=None, status_code=404)
        cauda = url.rstrip("/").split("/spells")[-1].strip("/")
        if cauda:                                   # /v1/spells/<slug>/
            achado = next((s for s in SRD if s["slug"] == cauda), None)
            return (open5e.Response(ok=True, data=achado, status_code=200) if achado
                    else open5e.Response(ok=False, data=None, status_code=404))
        res = list(SRD)
        if "name" in params:
            res = [s for s in res if s["name"].lower() == params["name"].lower()]
        if "search" in params:
            termo = params["search"].lower()
            # Como no Open5e, a busca textual casa também na descrição: toda
            # descrição daqui diz "magical", então "magical" traz tudo.
            res = [s for s in res if termo in s["name"].lower() or termo in s["desc"].lower()]
        if "dnd_class__icontains" in params:
            res = [s for s in res if params["dnd_class__icontains"].lower() in s["dnd_class"].lower()]
        if "spell_level__lte" in params:
            res = [s for s in res if s["spell_level"] <= int(params["spell_level__lte"])]
        if "spell_level" in params:
            res = [s for s in res if s["spell_level"] == int(params["spell_level"])]
        return open5e.Response(ok=True, data={"results": res}, status_code=200)

    monkeypatch.setattr(open5e, "get", falso)


def _conjurador(povoar, nome, classe, nivel, habilidades=None):
    povoar(criar_ficha(nome, grupo=True, nivel=nivel))
    ch = memory.campaign["characters"][memory.char_key(nome)]
    ch["sheet"]["classe"] = classe
    ch["habilidades"] = list(habilidades or [])
    return ch


def _magia(nome, nivel):
    return {"nome": nome, "descricao": "[Evocation] x", "nivel_magia": nivel,
            "custo_mana": td.SPELL_MANA_COST.get(nivel, 0), "dado": ""}


@pytest.fixture
def lyra(campanha, povoar):
    return _conjurador(povoar, "Lyra", "mago", 3)


@pytest.fixture
def irma(campanha, povoar):
    """Clériga de nível 1: 3 truques e 3 magias no máximo."""
    return _conjurador(povoar, "Irmã Vera", "clérigo", 1)


# ---------------------------------------------------------------------------
# 1. Limites e nível de magia saem do motor
# ---------------------------------------------------------------------------

def test_limite_vem_da_tabela_da_classe(lyra):
    assert td._limite_de_magias(lyra["sheet"]) == {"truques": 3, "magias": 10}


def test_classe_que_nao_conjura_nao_tem_limite(campanha, povoar):
    povoar(criar_ficha("Bram", grupo=True, nivel=5))
    assert td._limite_de_magias(memory.campaign["characters"]["bram"]["sheet"]) is None


@pytest.mark.parametrize("classe,nivel,esperado", [
    ("mago", 1, 1), ("mago", 3, 2), ("mago", 5, 3), ("mago", 17, 9),
    ("paladino", 1, 0), ("paladino", 2, 1), ("paladino", 4, 1),
    ("paladino", 5, 2), ("paladino", 9, 3), ("patrulheiro", 17, 5),
    ("guerreiro", 5, 0),
])
def test_nivel_maximo_de_magia_por_tipo_de_conjurador(classe, nivel, esperado):
    assert td._nivel_maximo_de_magia({"classe": classe, "nivel": nivel}) == esperado


@pytest.mark.parametrize("hab,nivel", [
    ({"nome": "Bola de Fogo", "descricao": "[Evocação] x", "custo_mana": 12}, 3),
    ({"nome": "Prestidigitação", "descricao": "[Truque] x", "custo_mana": 0}, 0),
    ({"nome": "Algo Antigo", "descricao": "[Evocation] x", "custo_mana": 5}, 3),
    ({"nome": "Algo Caseiro", "descricao": "[Evocation] x", "custo_mana": 4}, 1),
    ({"nome": "Qualquer", "descricao": "[x]", "custo_mana": 99, "nivel_magia": 2}, 2),
])
def test_nivel_da_magia_em_ficha_antiga(hab, nivel):
    """Ficha antiga não gravava o nível; a contagem não pode chutar errado."""
    assert td._nivel_da_magia(hab) == nivel


def test_magia_sem_marca_e_reconhecida_pelo_nome_do_srd(lyra):
    """Ficha importada trazia "Chamas Sagradas" sem "[escola]" nem nível."""
    lyra["habilidades"] = [
        {"nome": "Chamas Sagradas", "descricao": "Luz radiante.", "custo_mana": 0},
        {"nome": "Golpe Imponente", "descricao": "Poder da campanha.", "custo_mana": 0},
    ]
    assert td._contagem_de_magias(lyra) == (1, 0)


def test_habilidade_de_classe_nao_conta_como_magia(lyra):
    lyra["habilidades"] = [{"nome": "Recuperação Arcana", "descricao": "1 vez por dia...",
                            "custo_mana": 0, "dado": ""},
                           _magia("Fire Bolt", 0)]
    assert td._contagem_de_magias(lyra) == (1, 0)


# ---------------------------------------------------------------------------
# 2. learn_spell
# ---------------------------------------------------------------------------

def test_aprender_grava_nivel_e_nome_do_srd(lyra, srd):
    saida = td.learn_spell("Lyra", "Magic Missile")
    assert "aprendeu" in saida
    h = lyra["habilidades"][-1]
    assert h["nivel_magia"] == 1 and h["nome_srd"] == "Magic Missile"


def test_ja_conhece_pelo_nome_em_portugues(campanha, povoar, srd):
    """A ficha tinha "Bola de Fogo"; pedir "Fireball" não pode duplicar."""
    ch = _conjurador(povoar, "Kael", "mago", 5, [
        {"nome": "Bola de Fogo", "descricao": "[Evocação] x", "custo_mana": 5, "dado": "8d6"}])
    assert td.learn_spell("Kael", "Fireball").startswith("Nota:")
    assert len(ch["habilidades"]) == 1


def test_limite_de_magias_recusa_a_proxima(irma, srd):
    irma["habilidades"] = [_magia("Bless", 1), _magia("Cure Wounds", 1), _magia("Healing Word", 1)]
    saida = td.learn_spell("Irmã Vera", "Bless")
    # Bless já é conhecida: o limite não pode mascarar o "já conhece".
    assert saida.startswith("Nota:")

    irma["habilidades"][0] = _magia("Command", 1)
    saida = td.learn_spell("Irmã Vera", "Bless")
    assert saida.startswith("Erro:") and "3/3 magias" in saida
    assert len(irma["habilidades"]) == 3


def test_truque_nao_ocupa_vaga_de_magia(irma, srd):
    irma["habilidades"] = [_magia("Command", 1), _magia("Cure Wounds", 1), _magia("Healing Word", 1)]
    assert "aprendeu" in td.learn_spell("Irmã Vera", "Sacred Flame")


def test_limite_de_truques(irma, srd):
    irma["habilidades"] = [_magia("Light", 0), _magia("Guidance", 0), _magia("Thaumaturgy", 0)]
    saida = td.learn_spell("Irmã Vera", "Sacred Flame")
    assert saida.startswith("Erro:") and "3/3 truques" in saida


def test_paladino_nivel_3_nao_aprende_magia_de_2o_circulo(campanha, povoar, srd):
    """A regra antiga (2L−1) deixava: é a tabela do conjurador pleno."""
    ch = _conjurador(povoar, "Sir Aldo", "paladino", 3)
    saida = td.learn_spell("Sir Aldo", "Aid")
    assert saida.startswith("Erro:") and "até o nível 1" in saida
    ch["sheet"]["nivel"] = 5
    assert "aprendeu" in td.learn_spell("Sir Aldo", "Aid")


def test_magia_de_outra_classe_e_recusada(irma, srd):
    assert td.learn_spell("Irmã Vera", "Magic Missile").startswith("Erro:")


def test_nome_inventado_nao_herda_a_primeira_magia_da_busca(lyra, srd):
    """
    A busca textual casa na descrição. Sem palavra nenhuma em comum com o
    nome, "o mais próximo" era só o primeiro da lista — e a magia inventada
    entrava com os dados dele.
    """
    saida = td.learn_spell("Lyra", "Magical Rainbow of Doom")
    assert saida.startswith("Erro:")
    assert lyra["habilidades"] == []


def test_sem_conexao_magia_inventada_nao_entra(lyra):
    """Antes: qualquer nome, custo 4, sem checagem nenhuma."""
    saida = td.learn_spell("Lyra", "Lança Cósmica de Vhar")
    assert saida.startswith("Erro:") and "sem conexão" in saida
    assert lyra["habilidades"] == []


def test_sem_conexao_magia_padrao_da_classe_entra_com_nivel(lyra):
    saida = td.learn_spell("Lyra", "Raio de Gelo")
    assert "aprendeu" in saida
    assert lyra["habilidades"][-1]["nivel_magia"] == 0


def test_sem_conexao_ainda_confere_a_classe(campanha, povoar):
    """Bola de Fogo só está na lista local do feiticeiro."""
    ch = _conjurador(povoar, "Kael", "mago", 5)
    assert td.learn_spell("Kael", "Bola de Fogo").startswith("Erro:")
    assert ch["habilidades"] == []


def test_sem_conexao_ainda_confere_o_nivel(campanha, povoar):
    ch = _conjurador(povoar, "Nix", "feiticeiro", 1)
    assert td.learn_spell("Nix", "Bola de Fogo").startswith("Erro:")
    assert ch["habilidades"] == []


# ---------------------------------------------------------------------------
# 3. Catálogo
# ---------------------------------------------------------------------------

def test_catalogo_online_filtra_classe_e_nivel(srd):
    nomes = {s["nome"] for s in td.class_spell_catalog("mago", 1)}
    assert nomes == {"Fire Bolt", "Light", "Magic Missile", "Shield"}


def test_catalogo_le_sim_e_nao_como_texto(srd):
    """bool("no") é True: toda magia saía marcada como concentração e ritual."""
    por_nome = {s["nome"]: s for s in td.class_spell_catalog("clérigo", 1)}
    assert por_nome["Bless"]["concentracao"] is True
    assert por_nome["Cure Wounds"]["concentracao"] is False
    assert por_nome["Cure Wounds"]["ritual"] is False


def test_learn_spell_nao_marca_ritual_que_nao_e(lyra, srd):
    saida = td.learn_spell("Lyra", "Magic Missile")
    assert "ritual" not in saida and "concentração" not in saida
    assert "(ritual)" not in lyra["habilidades"][-1]["descricao"]


def test_descricao_longa_corta_na_palavra(srd, monkeypatch):
    longa = "word " * 80
    SRD.append(_sp("Long Spell", 1, "Wizard", desc=longa))
    try:
        sp = next(s for s in td.class_spell_catalog("mago", 1) if s["nome"] == "Long Spell")
    finally:
        SRD.pop()
    assert sp["descricao"].endswith("…") and "wor…" not in sp["descricao"]
    assert len(sp["descricao"]) <= 251


def test_catalogo_pede_so_o_srd(srd):
    """O Open5e mistura livros de terceiros na lista da classe."""
    td.class_spell_catalog("mago", 1)
    assert PEDIDOS and PEDIDOS[-1][1].get("document__slug") == "wotc-srd"


def test_catalogo_offline_usa_a_lista_local_sem_magia_acima_do_nivel():
    nomes = {s["nome"]: s["nivel_magia"] for s in td.class_spell_catalog("feiticeiro", 1)}
    assert "Bola de Fogo" not in nomes, "magia de 3º círculo no catálogo de nível 1"
    assert nomes.get("Raio de Gelo") == 0


# ---------------------------------------------------------------------------
# 4. Snapshot e ação da tela
# ---------------------------------------------------------------------------

def test_snapshot_so_traz_quem_conjura(lyra, povoar, srd):
    povoar(criar_ficha("Bram", grupo=True, nivel=3))
    snap = td.grimoire_snapshot()
    assert snap["grupo"] == ["Lyra"]


def test_snapshot_marca_ja_conhece_e_limite(irma, srd):
    irma["habilidades"] = [_magia("Command", 1), _magia("Cure Wounds", 1),
                           _magia("Healing Word", 1), _magia("Light", 0)]
    snap = td.grimoire_snapshot("Irmã Vera")
    por_nome = {s["nome"]: s["bloqueio"] for s in snap["catalogo"]}
    assert por_nome["Cure Wounds"] == "já conhece"
    assert por_nome["Bless"] == "limite de magias"
    assert por_nome["Sacred Flame"] == ""
    assert snap["personagem"]["vagas"]["truques"] == 2
    assert "Aid" not in por_nome, "magia de 2º círculo para clériga de nível 1"


def test_sem_nome_abre_em_quem_tem_vaga(lyra, povoar, srd):
    cheia = _conjurador(povoar, "Nix", "feiticeiro", 1)
    cheia["habilidades"] = [_magia(n, 0) for n in ("a", "b", "c", "d")] + \
                           [_magia(n, 1) for n in ("e", "f")]
    lyra["habilidades"] = [_magia(n, 0) for n in ("a", "b", "c")] + \
                          [_magia(f"m{i}", 1) for i in range(10)]
    snap = td.grimoire_snapshot()
    assert snap["devendo"] == []
    lyra["habilidades"].pop()
    snap = td.grimoire_snapshot()
    assert snap["personagem"]["nome"] == "Lyra" and snap["devendo"] == ["Lyra"]


def test_assinatura_nao_muda_quando_a_vaga_so_diminui(lyra, srd):
    """Aprender uma magia pelo chat não pode reabrir a tela no jogador."""
    antes = td.grimoire_snapshot(com_catalogo=False)["assinatura"]
    td.learn_spell("Lyra", "Shield")
    assert td.grimoire_snapshot(com_catalogo=False)["assinatura"] == antes == "Lyra:3"


def test_assinatura_muda_quando_sobe_de_nivel(lyra, srd):
    antes = td.grimoire_snapshot()["assinatura"]
    lyra["sheet"]["nivel"] = 4
    assert td.grimoire_snapshot()["assinatura"] != antes


def test_acao_aprender_passa_pelo_learn_spell(lyra, srd, monkeypatch):
    vistos = []
    real = td.learn_spell
    monkeypatch.setattr(td, "learn_spell", lambda *a, _r=real: (vistos.append(a), _r(*a))[1])
    r = td.grimoire_action("aprender", char="Lyra", spell="Shield")
    assert vistos == [("Lyra", "Shield")]
    assert r["ok"] is True
    assert r["snapshot"]["personagem"]["vagas"]["magias_usadas"] == 1


def test_acao_recusada_devolve_ok_falso(irma, srd):
    r = td.grimoire_action("aprender", char="Irmã Vera", spell="Fireball")
    assert r["ok"] is False


def test_acao_desconhecida(lyra, srd):
    r = td.grimoire_action("esquecer_tudo", char="Lyra", spell="Shield")
    assert r["ok"] is False and lyra["habilidades"] == []


def test_resumo_nao_vai_ao_srd(lyra, monkeypatch):
    """A fila de telas pede o resumo a cada turno: sem catálogo, sem rede."""
    chamadas = []
    monkeypatch.setattr(open5e, "get", lambda *a, **k: chamadas.append(a) or
                        open5e.Response(ok=False, data=None))
    snap = td.grimoire_snapshot(com_catalogo=False)
    assert chamadas == [] and snap["catalogo"] == []
    assert snap["devendo"] == ["Lyra"]


def test_grupo_vazio_nao_quebra(campanha):
    snap = td.grimoire_snapshot()
    assert snap["tem_personagem"] is False and snap["catalogo"] == []


def test_level_up_avisa_as_magias_a_aprender(lyra):
    lyra["sheet"].update({"xp": 2700, "xp_proximo": 2700})
    saida = td.grant_xp("Lyra", 0)
    assert "Magias a aprender" in saida and "Grimório" in saida


def test_as_rotas_do_grimorio_estao_registradas():
    import server
    rotas = {r.rule for r in server.app.url_map.iter_rules()}
    assert "/api/grimoire/state" in rotas and "/api/grimoire/action" in rotas
    assert "/api/dnd/class-spells" in rotas
