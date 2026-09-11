"""
test_tela_de_nivel.py

O motor sempre soube SUBIR de nível e sempre soube APLICAR uma escolha. O que
faltava era o meio: saber que o personagem DEVE uma escolha.

Sem isso, "escolha um Estilo de Combate" era uma frase no fim do texto de
level-up. Se ninguém escolhesse, nada acontecia e nada cobrava — e um
guerreiro atravessava a campanha inteira sem o estilo a que tinha direito
desde o nível 1.

Quase tudo aqui é CALCULADO, não gravado: tem a habilidade na ficha e não tem
entrada em `feature_choices` logo deve a escolha. Isso vale para fichas salvas
antes desta mudança, sem migração nenhuma.

A exceção é o Incremento de Atributo, que não deixa rastro — um +2 em Força é
indistinguível de uma força alta na criação. Esse precisa de contador, e o
contador é ancorado no presente: cobrar retroativamente os 5 incrementos de um
personagem de nível 19 daria +10 de atributo de presente.
"""
import pytest

from rpg import memory, tools_dnd as td

from conftest import criar_ficha


@pytest.fixture
def helena(campanha, povoar):
    povoar(criar_ficha("Helena", grupo=True, nivel=4, forca=16, destreza=14,
                       constituicao=15, carisma=8))
    ch = memory.campaign["characters"]["helena"]
    ch["sheet"].update({"classe": "guerreiro", "xp": 3100, "xp_proximo": 6500,
                        "asi_pontos_gastos": 0, "feature_choices": {}})
    ch["habilidades"] = [
        {"nome": "Estilo de Combate", "descricao": "", "custo_mana": 0, "dado": ""},
        {"nome": "Arquétipo Marcial", "descricao": "", "custo_mana": 0, "dado": ""},
    ]
    return ch


def _rotulos(char):
    return [q["rotulo"] for q in td._escolhas_pendentes(char)]


# ---------------------------------------------------------------------------
# 1. O que está pendente sai da ficha, sem estado novo
# ---------------------------------------------------------------------------

def test_feature_com_variante_e_sem_escolha_esta_pendente(helena):
    assert "Estilo de Combate" in _rotulos(helena)
    assert "Arquétipo Marcial" in _rotulos(helena)


def test_escolher_tira_da_lista(helena):
    td.set_feature_choice("Helena", "Estilo de Combate", "Defesa")
    assert "Estilo de Combate" not in _rotulos(helena)


def test_habilidade_sem_variante_nunca_aparece(helena):
    """Segunda Fôlego não tem o que escolher; não pode virar pendência falsa."""
    helena["habilidades"].append(
        {"nome": "Segunda Fôlego", "descricao": "", "custo_mana": 0, "dado": ""})
    assert "Segunda Fôlego" not in _rotulos(helena)


def test_ficha_sem_a_habilidade_nao_deve_nada(campanha, povoar):
    povoar(criar_ficha("Novata", grupo=True, nivel=1))
    ch = memory.campaign["characters"]["novata"]
    ch["habilidades"] = []
    ch["sheet"]["asi_pontos_gastos"] = 0
    assert td._escolhas_pendentes(ch) == []


def test_as_opcoes_vem_do_motor_e_excluem_o_ja_escolhido(helena):
    q = next(x for x in td._escolhas_pendentes(helena)
             if x["rotulo"] == "Estilo de Combate")
    nomes = [o["nome"] for o in q["opcoes"]]
    assert "Defesa" in nomes and "Duelo" in nomes
    assert all(o["descricao"] for o in q["opcoes"]), "opção sem descrição"


# ---------------------------------------------------------------------------
# 2. Incremento de Atributo
# ---------------------------------------------------------------------------

def test_nivel_4_deve_dois_pontos(helena):
    q = next(x for x in td._escolhas_pendentes(helena) if x["tipo"] == "asi")
    assert q["faltam"] == 2


def test_guerreiro_ganha_incremento_no_6_e_no_14():
    """Extras de classe: é parte do que compensa a falta de magia."""
    assert td._niveis_asi("guerreiro") == {4, 6, 8, 12, 14, 16, 19}
    assert td._niveis_asi("ladino") == {4, 8, 10, 12, 16, 19}
    assert td._niveis_asi("mago") == {4, 8, 12, 16, 19}


def test_gastar_ponto_sobe_o_atributo_e_desconta(helena):
    saida = td.apply_asi("Helena", "forca", 1)
    assert helena["sheet"]["forca"] == 17
    assert "17" in saida
    q = next(x for x in td._escolhas_pendentes(helena) if x["tipo"] == "asi")
    assert q["faltam"] == 1


def test_dois_pontos_no_mesmo_atributo(helena):
    td.apply_asi("Helena", "forca", 2)
    assert helena["sheet"]["forca"] == 18
    assert not [x for x in td._escolhas_pendentes(helena) if x["tipo"] == "asi"]


def test_nao_gasta_mais_do_que_tem(helena):
    td.apply_asi("Helena", "forca", 2)
    saida = td.apply_asi("Helena", "destreza", 1)
    assert "não tem incremento" in saida
    assert helena["sheet"]["destreza"] == 14


def test_teto_de_20(helena):
    """
    set_stat não impõe teto — é ajuste livre do mestre. O ASI impõe, e é por
    isso que ele precisou de função própria em vez de reusar set_stat.
    """
    helena["sheet"]["forca"] = 20
    saida = td.apply_asi("Helena", "forca", 1)
    assert "teto" in saida
    assert helena["sheet"]["forca"] == 20
    assert td._asi_pontos_pendentes(helena["sheet"]) == 2, "não podia gastar"


def test_constituicao_puxa_a_vida_maxima(helena):
    """CON 15 → 16 muda o modificador de +2 para +3: +1 PV por nível."""
    antes = helena["sheet"]["vida_max"]
    td.apply_asi("Helena", "constituicao", 1)
    assert helena["sheet"]["vida_max"] == antes + helena["sheet"]["nivel"]


def test_atributo_invalido_e_recusado(helena):
    assert "não é atributo" in td.apply_asi("Helena", "sorte", 1)


# ---------------------------------------------------------------------------
# 3. Ficha antiga não é cobrada retroativamente
# ---------------------------------------------------------------------------

def test_ficha_sem_contador_nao_deve_nada():
    antiga = {"nivel": 12, "classe": "guerreiro"}
    assert td._asi_pontos_pendentes(antiga) == 0


def test_carimbo_ancora_no_presente():
    antiga = {"nivel": 12, "classe": "guerreiro"}
    td._carimbar_asi(antiga)
    # nível 12 de guerreiro: incrementos em 4, 6, 8 e 12 = 4 × 2 pontos
    assert antiga["asi_pontos_gastos"] == 8
    assert td._asi_pontos_pendentes(antiga) == 0


def test_carimbo_nao_mexe_em_quem_ja_tem_contador():
    s = {"nivel": 8, "classe": "mago", "asi_pontos_gastos": 2}
    td._carimbar_asi(s)
    assert s["asi_pontos_gastos"] == 2


def test_o_proximo_nivel_passa_a_ser_cobrado(campanha, povoar):
    """
    O passado não é cobrado, mas o futuro é: este é o teste que garante que o
    carimbo ancora em vez de desligar a conta para sempre.
    """
    povoar(criar_ficha("Antiga", grupo=True, nivel=3))
    ch = memory.campaign["characters"]["antiga"]
    ch["sheet"].update({"classe": "guerreiro", "xp": 900, "xp_proximo": 2700})
    ch["sheet"].pop("asi_pontos_gastos", None)
    ch["habilidades"] = []

    assert td._escolhas_pendentes(ch) == []

    td.grant_xp("Antiga", 1900)              # chega ao nível 4

    assert ch["sheet"]["nivel"] == 4
    q = [x for x in td._escolhas_pendentes(ch) if x["tipo"] == "asi"]
    assert q and q[0]["faltam"] == 2


def test_o_texto_do_level_up_avisa_o_que_ficou_pendente(helena):
    helena["sheet"]["asi_pontos_gastos"] = 2      # zera o do nível 4
    saida = td.grant_xp("Helena", 4000)           # nível 5
    assert "PENDENTES" in saida
    assert "Estilo de Combate" in saida


# ---------------------------------------------------------------------------
# 4. O snapshot
# ---------------------------------------------------------------------------

def test_snapshot_abre_em_quem_esta_devendo(campanha, povoar):
    povoar(criar_ficha("Stelar", grupo=True, nivel=3),
           criar_ficha("Helena", grupo=True, nivel=4))
    for nome in ("stelar", "helena"):
        memory.campaign["characters"][nome]["sheet"]["asi_pontos_gastos"] = 0
        memory.campaign["characters"][nome]["habilidades"] = []
    h = memory.campaign["characters"]["helena"]
    h["sheet"]["classe"] = "guerreiro"

    snap = td.levelup_snapshot()

    assert snap["personagem"]["nome"] == "Helena", "abriu em quem não devia nada"
    assert snap["devendo"] == ["Helena"]


def test_snapshot_traz_atributos_com_sigla(helena):
    p = td.levelup_snapshot()["personagem"]
    siglas = [a["sigla"] for a in p["atributos"]]
    assert siglas == ["FOR", "DES", "CON", "INT", "SAB", "CAR"]


def test_barra_de_xp_situa_dentro_da_faixa_do_nivel(helena):
    """
    A porcentagem é do progresso DENTRO do nível, não do total. Sem descontar
    o piso, um personagem de nível 4 com 3100 de 6500 apareceria com metade
    da barra cheia quando mal começou.
    """
    p = td.levelup_snapshot()["personagem"]
    assert 0 <= p["xp_pct"] <= 100
    assert p["xp_pct"] < 20, f"3100 de 2700→6500 deveria ser ~11%, deu {p['xp_pct']}"


def test_grupo_vazio_nao_quebra(campanha):
    snap = td.levelup_snapshot()
    assert snap["tem_personagem"] is False
    assert snap["pendencias"] == []


# ---------------------------------------------------------------------------
# 5. A costura: a tela não pode ter regra própria
# ---------------------------------------------------------------------------

def test_a_tela_passa_pelas_MESMAS_funcoes_do_mestre(helena, monkeypatch):
    """
    Mesmo contrato da tela de loja. Se alguém reimplementar a aplicação de
    escolha aqui, a regra passa a existir em dois lugares e um dos dois vai
    ficar para trás — foi assim que a recarga do chefe valeu na IA de NPC e
    não no caminho do mestre.
    """
    vistas = []

    def espiar(nome, real):
        # `nome` E `real` presos por argumento padrão. A primeira versão deste
        # teste prendeu só o nome, e as três funções acabaram embrulhando a
        # ÚLTIMA `real` do laço — set_feature_choice chamava choose_feat.
        def _wrap(*a, _n=nome, _r=real, **k):
            vistas.append((_n, a))
            return _r(*a, **k)
        return _wrap

    for nome in ("set_feature_choice", "apply_asi", "choose_feat"):
        monkeypatch.setattr(td, nome, espiar(nome, getattr(td, nome)))

    td.levelup_action("variante", char="Helena",
                      feature="Estilo de Combate", choice="Defesa")
    td.levelup_action("asi", char="Helena", choice="forca", points=1)

    assert ("set_feature_choice", ("Helena", "Estilo de Combate", "Defesa")) in vistas
    assert ("apply_asi", ("Helena", "forca", 1)) in vistas


def test_acao_desconhecida_nao_faz_nada(helena):
    antes = dict(helena["sheet"])
    r = td.levelup_action("trapacear", char="Helena", choice="forca")
    assert r["ok"] is False
    assert helena["sheet"]["forca"] == antes["forca"]


def test_a_acao_devolve_o_snapshot_junto(helena):
    r = td.levelup_action("variante", char="Helena",
                          feature="Estilo de Combate", choice="Defesa")
    assert r["ok"] is True
    rotulos = [p["rotulo"] for p in r["snapshot"]["pendencias"]]
    assert "Estilo de Combate" not in rotulos


def test_escolher_arquetipo_concede_a_sub_feature(helena):
    """O Campeão dá Crítico Aprimorado no 3º — quem faz isso é o motor."""
    td.levelup_action("variante", char="Helena",
                      feature="Arquétipo Marcial", choice="Campeão")
    nomes = [h["nome"] for h in helena["habilidades"]]
    assert "Crítico Aprimorado" in nomes


def test_as_rotas_do_nivel_estao_registradas():
    import server
    rotas = {r.rule for r in server.app.url_map.iter_rules()}
    assert "/api/levelup/state" in rotas
    assert "/api/levelup/action" in rotas


def test_apply_asi_esta_no_catalogo_do_agente():
    """O mestre também precisa poder aplicar ASI — a tela não é o único jeito."""
    assert "apply_asi" in {f.__name__ for f in td.DND_TOOLS}
