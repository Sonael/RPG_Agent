"""
test_renomear_no_wizard.py

"quando eu criei a campanha, pedi para a IA gerar, ela gerou personagens com
nomes que eu não gostei, eu troquei os nomes dos meus personagens e quando eu
iniciei a campanha os eventos no diário ainda estavam com os nomes antigos."

O wizard gera o mundo inteiro de uma vez, e tudo ali fala de todo mundo pelo
nome. Trocar o nome no campo do personagem trocava só ali.
"""
import pytest

from rpg import renomear


MUNDO = {
    "story_summary": "Thalion e Mirna chegam a Valenport atrás do irmão de Thalion.",
    "current_scene": "Thalion examina o portão enquanto Mirna conversa com o guarda.",
    "characters": {
        "thalion": {"name": "Thalion", "description": "Mago curioso.",
                    "traits": "Calculista.", "notes": "Irmão de Mirna."},
        "mirna": {"name": "Mirna", "description": "Guerreira. Protege Thalion.",
                  "traits": "Direta."},
    },
    "party": [{"name": "Thalion", "role": "mago", "notes": "Lidera o grupo."}],
    "events": [{"index": 1, "summary": "Thalion e Mirna entraram na guilda.",
                "characters_involved": "Thalion, Mirna",
                "location": "Valenport", "consequence": "Thalion virou membro."}],
    "locations": {"valenport": {"name": "Valenport",
                                "description": "Cidade onde Thalion nasceu."}},
}


def test_o_evento_deixa_de_falar_do_nome_antigo():
    novo = renomear.aplicar(MUNDO, [["Thalion", "Sonael"]])
    evento = novo["events"][0]
    assert evento["summary"] == "Sonael e Mirna entraram na guilda."
    assert evento["consequence"] == "Sonael virou membro."
    assert evento["characters_involved"] == "Sonael, Mirna"


def test_troca_em_todo_o_mundo_escrito():
    novo = renomear.aplicar(MUNDO, [["Thalion", "Sonael"]])
    assert "Thalion" not in novo["story_summary"]
    assert "Sonael" in novo["current_scene"]
    assert novo["characters"]["thalion"]["name"] == "Sonael"
    assert "Sonael" in novo["characters"]["mirna"]["description"]
    assert "Sonael" in novo["locations"]["valenport"]["description"]
    assert novo["party"][0]["name"] == "Sonael"


def test_dois_nomes_de_uma_vez():
    novo = renomear.aplicar(MUNDO, [["Thalion", "Sonael"], ["Mirna", "Helena"]])
    assert novo["events"][0]["summary"] == "Sonael e Helena entraram na guilda."


def test_a_chave_do_personagem_nao_e_mexida():
    """Quem monta a campanha é que decide a chave; aqui só o texto muda."""
    novo = renomear.aplicar(MUNDO, [["Thalion", "Sonael"]])
    assert "thalion" in novo["characters"]


def test_o_original_nao_e_alterado():
    renomear.aplicar(MUNDO, [["Thalion", "Sonael"]])
    assert "Thalion" in MUNDO["story_summary"]


def test_so_palavra_inteira():
    dados = {"t": "Ana entrou. Anabel ficou. Mariana saiu. A ANA gritou."}
    novo = renomear.aplicar(dados, [["Ana", "Lia"]])
    assert novo["t"] == "Lia entrou. Anabel ficou. Mariana saiu. A Lia gritou."


def test_nome_com_pontuacao_em_volta():
    dados = {"t": "— Selene? — chamou ele. (Selene, de novo.)"}
    assert renomear.aplicar(dados, [["Selene", "Íris"]])["t"] == \
        "— Íris? — chamou ele. (Íris, de novo.)"


def test_nome_com_acento():
    dados = {"t": "Aelín corre. Aelínia fica."}
    assert renomear.aplicar(dados, [["Aelín", "Nara"]])["t"] == "Nara corre. Aelínia fica."


def test_nome_de_duas_palavras():
    dados = {"t": "Mestre Faelar abriu a porta para Faelar."}
    novo = renomear.aplicar(dados, [["Mestre Faelar", "Velho Bram"]])
    assert novo["t"] == "Velho Bram abriu a porta para Faelar."


@pytest.mark.parametrize("renomes", [
    None, [], [["", "Sonael"]], [["Thalion", ""]], [["Thalion", "Thalion"]],
    [["T", "Sonael"]],          # nome de uma letra trocaria qualquer coisa
])
def test_pedido_vazio_ou_perigoso_nao_muda_nada(renomes):
    assert renomear.aplicar(MUNDO, renomes)["story_summary"] == MUNDO["story_summary"]


def test_nome_de_uma_letra_e_ignorado():
    """Uma letra sozinha é artigo, conjunção, inicial — trocaria a prosa toda."""
    dados = {"t": "A porta range. E ela entra, com o punhal na mão."}
    assert renomear.aplicar(dados, [["A", "Nara"]])["t"] == dados["t"]
    assert renomear.aplicar(dados, [["E", "Bram"]])["t"] == dados["t"]


def test_lixo_na_lista_nao_derruba():
    novo = renomear.aplicar(MUNDO, [None, ["Thalion"], 42, ["Thalion", "Sonael"]])
    assert "Sonael" in novo["story_summary"]


def test_numeros_e_nulos_atravessam_inteiros():
    dados = {"chapter": 2, "dnd_mode": True, "nada": None, "lista": [1, "Thalion"]}
    novo = renomear.aplicar(dados, [["Thalion", "Sonael"]])
    assert novo["chapter"] == 2 and novo["dnd_mode"] is True and novo["nada"] is None
    assert novo["lista"] == [1, "Sonael"]


def test_a_rota_de_criacao_usa_isto():
    import inspect
    import server
    fonte = inspect.getsource(server.create_campaign)
    assert "renomear.aplicar" in fonte
    assert 'data.get("renomes")' in fonte
