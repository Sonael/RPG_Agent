"""
test_compendio_srd.py

O SRD 5.1 inteiro em tabela local: 319 magias, 12 classes, 12 subclasses.

O motor buscava cada magia no Open5e em tempo de jogo e interpretava a prosa
em inglês com expressões regulares, em seis lugares diferentes. A tabela é
gerada uma vez (scripts/gerar_compendio.py), revisada à mão, e versionada.

Estes testes prendem duas coisas:
  • a COMPLETUDE — tudo o que o SRD tem está lá, com nome em português;
  • a CORREÇÃO das magias que a revisão pegou erradas. Cada caso abaixo foi
    um erro real do Open5e ou da primeira versão do gerador, e conjurar a
    magia teria feito outra coisa.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from rpg import compendio

RAIZ = Path(__file__).resolve().parent.parent


def _m(nome_srd):
    m = compendio.magia(nome_srd)
    assert m, f"{nome_srd} não está no compêndio"
    return m


# ---------------------------------------------------------------------------
# 1. Completude
# ---------------------------------------------------------------------------

def test_todas_as_magias_do_srd():
    assert len(compendio.magias()) == 319


def test_todas_as_classes_e_subclasses_do_srd():
    classes = compendio.classes()
    assert len(classes) == 12
    assert sum(len(c["subclasses"]) for c in classes.values()) == 12
    total = sum(len(c["caracteristicas"]) + sum(len(s["caracteristicas"])
                                                for s in c["subclasses"].values())
                for c in classes.values())
    assert total >= 180


def test_toda_magia_tem_nome_em_portugues():
    sem = [m["nome_srd"] for m in compendio.magias().values() if m["nome"] == m["nome_srd"]
           and m["nome_srd"] not in ("Clone",)]
    assert not sem, sem


def test_toda_caracteristica_tem_nome_em_portugues():
    nomes = json.loads((RAIZ / "scripts" / "srd_classes_pt.json").read_text(encoding="utf-8"))
    for c in compendio.classes().values():
        for f in c["caracteristicas"]:
            assert f["nome_srd"] in nomes["caracteristicas"], f["nome_srd"]


def test_os_nomes_oficiais_substituem_os_errados():
    """O jogo chamava Raio Guia de 'guia espiritual' e Palavra Curativa de 'cura'."""
    assert _m("Guiding Bolt")["nome"] == "Raio Guia"
    assert _m("Healing Word")["nome"] == "Palavra Curativa"
    assert _m("Spiritual Weapon")["nome"] == "Arma Espiritual"
    assert _m("Charm Person")["nome"] == "Enfeitiçar Pessoa"


def test_o_nome_antigo_continua_achando_a_magia():
    """Apelido de busca: quem digitar o nome errado de antes ainda encontra."""
    assert compendio.magia("guia espiritual")["nome_srd"] == "Guiding Bolt"
    assert compendio.magia("Guia Divino")["nome_srd"] == "Guiding Bolt"
    assert compendio.magia("Golpe Místico")["nome_srd"] == "Eldritch Blast"


def test_o_truque_bonus_e_a_mesma_magia():
    assert compendio.magia("Truque Bônus (Chamas Sagradas)")["nome_srd"] == "Sacred Flame"


def test_a_licenca_vai_junto():
    for arq in ("srd_magias.json", "srd_classes.json"):
        dados = json.loads((RAIZ / "rpg" / "dados" / arq).read_text(encoding="utf-8"))
        assert "Creative Commons" in dados["_licenca"], arq
        assert "System Reference Document 5.1" in dados["_licenca"], arq


# ---------------------------------------------------------------------------
# 2. Quem a magia atinge — o campo cuja falta queimou aliados
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nome, alvos", [
    ("Fireball", "todos"),             # o fogo amigo é regra: pega quem estiver
    ("Burning Hands", "todos"),
    ("Sleep", "todos"),                # no SRD o Sono atinge aliados
    ("Web", "todos"),                  # "um ponto à sua escolha" é ONDE, não QUEM
    ("Spirit Guardians", "escolha"),   # você designa quem fica de fora
    ("Mass Cure Wounds", "escolha"),
    ("Slow", "escolha"),
    ("Guardian of Faith", "hostis"),   # só fere criaturas hostis
])
def test_quem_cada_area_atinge(nome, alvos):
    assert _m(nome)["alvos"] == alvos


def test_nenhuma_magia_de_dano_atinge_quem_conjura():
    """
    Alcance "pessoal" não é alvo "si": Toque Vampírico nasce em você e fere o
    inimigo. Com alvo "si" o motor poderia aplicar o dano em quem conjura.
    """
    perigo = [m["nome_srd"] for m in compendio.magias().values()
              if m["efeito"] == "dano" and m["alvos"] == "si"]
    assert not perigo, perigo


# ---------------------------------------------------------------------------
# 3. Os erros que a revisão pegou — cada um faria a magia fazer outra coisa
# ---------------------------------------------------------------------------

def test_infligir_ferimentos_tem_dado_e_ataque():
    """O Open5e diz attack_roll=False; o texto pede ataque corpo a corpo."""
    m = _m("Inflict Wounds")
    assert m["dado"] == "3d10" and m["tipo_dano"] == "necrotic"
    assert m["ataque"] == "corpo"


def test_teia_nao_queima():
    """O 2d4 de fogo é se a teia PEGAR fogo. A magia prende."""
    m = _m("Web")
    assert m["efeito"] == "condicao" and m["dado"] == "" and m["tipo_dano"] == ""


@pytest.mark.parametrize("nome", ["Meld into Stone", "Dimension Door",
                                  "Contact Other Plane", "Wish", "Teleport"])
def test_dano_em_quem_conjura_nao_vira_dano_no_alvo(nome):
    assert _m(nome)["efeito"] != "dano", nome


def test_espiritos_guardioes_e_radiante_ou_necrotico_nao_os_dois():
    m = _m("Spirit Guardians")
    assert m["dado"] == "3d8" and m["dano_extra"] == []


def test_coluna_de_chamas_e_fogo_e_radiante_de_verdade():
    m = _m("Flame Strike")
    assert m["tipo_dano"] == "fire"
    assert [d["tipo"] for d in m["dano_extra"]] == ["radiant"]


@pytest.mark.parametrize("nome, forma, metros", [
    ("Shatter", "esfera", 3),          # o hífen invisível do SRD escondia esta
    ("Confusion", "esfera", 3),        # e esta escrevia "10 foot", sem hífen
    ("Flaming Sphere", "esfera", 1.5), # o campo trazia 20 pés: era a LUZ
    ("Call Lightning", "esfera", 1.5), # o campo trazia a nuvem de 18 m
    ("Lightning Bolt", "linha", 30),
    ("Flame Strike", "cilindro", 3),   # a busca parava no "10-foot-radius"
    ("Reverse Gravity", "cilindro", 15),  # o campo trazia a altura, 100 pés
])
def test_areas_corrigidas(nome, forma, metros):
    area = _m(nome)["area"]
    assert area and area["forma"] == forma and area["tamanho_m"] == metros


def test_utilidades_nao_ganham_area():
    """Luz, Detectar Magia: o raio é da luz e da percepção, não atinge ninguém."""
    for nome in ("Light", "Detect Magic", "Warding Bond", "Disintegrate"):
        assert _m(nome)["area"] is None, nome


def test_bencao_guarda_o_dado_de_bonus():
    """O ajuste de resumo apagava o 1d4 da Bênção."""
    assert _m("Bless")["dado"] == "1d4"
    assert _m("Bane")["dado"] == "1d4"
    assert _m("Blink")["dado"] == "", "o d20 do Piscar é teste, não bônus"


def test_curas_completas():
    curas = {m["nome_srd"]: m["dado"] for m in compendio.magias().values()
             if m["efeito"] == "cura"}
    assert curas["Cure Wounds"] == "1d8"
    assert curas["Regenerate"] == "4d8+15"
    assert curas["Mass Heal"] == "700"
    assert "Power Word Kill" not in curas, "'pontos de vida' no texto não é cura"


def test_truque_cresce_com_o_nivel():
    assert _m("Fire Bolt")["escala_personagem"] == {"5": "2d10", "11": "3d10", "17": "4d10"}


def test_sem_hifen_invisivel_no_texto():
    assert not any("­" in m["descricao_en"] for m in compendio.magias().values())


# ---------------------------------------------------------------------------
# 4. Classes
# ---------------------------------------------------------------------------

def test_furias_por_nivel_da_tabela():
    furias = compendio.classe("bárbaro")["tabela"]["furias"]
    assert furias["1"] == "2" and furias["6"] == "4" and furias["20"] == "Unlimited"


def test_ataque_furtivo_por_nivel():
    furtivo = compendio.caracteristica("Ataque Furtivo")["progressao"]
    assert compendio.progressao_no_nivel(furtivo, 1) == "1d6"
    assert compendio.progressao_no_nivel(furtivo, 19) == "10d6"


def test_canalizar_divindade_do_paladino_nao_escala():
    """Só o do clérigo vai a 2 e 3 usos. O motor dava 2 ao paladino de nível 6."""
    pal = compendio.caracteristica("Canalizar Divindade", "paladino")
    assert pal["usos"] == {"max": 1, "descanso": "curto"}


def test_feiticaria_volta_no_descanso_longo():
    assert compendio.caracteristica("Fonte de Magia")["usos"]["descanso"] == "longo"
    assert compendio.caracteristica("Ki")["usos"]["descanso"] == "curto"


def test_os_nomes_das_fichas_antigas_sao_reconhecidos():
    assert compendio.caracteristica("Segunda Fôlego")["nome_srd"] == "Second Wind"
    assert compendio.caracteristica("Defesa Sem Armadura")["nome_srd"] == "Unarmored Defense"


def test_o_modo_exato_nao_cai_na_caracteristica_mae():
    """
    "Canalizar Divindade (Radiância do Amanhecer)" não é do SRD. Devolver a mãe
    trocaria o efeito específico por um resumo genérico — a falta de
    informação que levou a fogo amigo.
    """
    nome = "Canalizar Divindade (Radiância do Amanhecer)"
    assert compendio.caracteristica(nome, exato=True) is None
    assert compendio.caracteristica(nome) is not None


# ---------------------------------------------------------------------------
# 5. O gerador é a fonte: o JSON não pode ser editado à mão
# ---------------------------------------------------------------------------

def test_o_gerador_reproduz_o_compendio_versionado(tmp_path):
    """
    Correção feita direto no JSON some na próxima geração. Se este teste
    falhar, a correção foi parar no lugar errado: ela pertence aos ajustes
    revisados de scripts/gerar_compendio.py.
    """
    # Gera numa pasta temporária: no lugar, reescreveria o JSON enquanto os
    # outros testes, em paralelo, o leem.
    r = subprocess.run([sys.executable, str(RAIZ / "scripts" / "gerar_compendio.py"),
                        "--destino", str(tmp_path)],
                       cwd=RAIZ, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    for arq in ("srd_magias.json", "srd_classes.json"):
        assert (tmp_path / arq).read_bytes() == (RAIZ / "rpg" / "dados" / arq).read_bytes(), (
            f"{arq} não bate com o que o gerador produz"
        )
