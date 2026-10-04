"""
test_condicao_narrada.py

Condição narrada é condição na ficha.

Na campanha Teste3 (04/10/2026) o arquimago Estradivarius pôs a Lyra para
dormir com Sono, e a narração foi literal:

    "Lyra é atingida pelo feitiço Sono de Estradivarius e adormece
     profundamente no pátio do cartório."

O verificador do servidor já cobrava condição narrada sem apply_condition,
mas o padrão era um só, no masculino singular ("ficou paralisado"), e não
conhecia o sono: a frase passou, e a Lyra continuou acordada na ficha.

Agora: feminino e plural, voz passiva, sono e desmaio; e a cobrança olha a
ficha de quem a frase cita. Se alguém citado já tem a condição (o Mestre
chamou apply_condition, ou o motor aplicou), está certo.
"""
import pytest

from rpg import memory

from conftest import criar_ficha


@pytest.fixture
def mesa(campanha, povoar):
    memory.campaign["dnd_mode"] = True
    povoar(criar_ficha("Lyra", grupo=True, classe="mago"),
           criar_ficha("Alden", grupo=True),
           criar_ficha("Estradivarius", classe="mago", nivel=20),
           criar_ficha("Kaelen Vane"))
    return memory.campaign


def _checar(texto, ferramentas=frozenset()):
    import server
    return [v for v in server._verify_agent_response(
        texto, set(ferramentas), combat_was_active=False, dead_before=set())
        if "condição" in v.lower()]


def _condicao(nome, cond):
    memory.campaign["characters"][nome]["sheet"].setdefault("condicoes", []).append(
        {"nome": cond, "duracao": 10})


FRASE_DA_TESTE3 = ("Desafiando o arquimago a provar seu poder por completo, Lyra é atingida "
                   "pelo feitiço Sono de Estradivarius e adormece profundamente no pátio do cartório.")


def test_a_frase_da_teste3_e_cobrada_e_diz_quem_foi_citado(mesa):
    v = _checar(FRASE_DA_TESTE3)
    assert len(v) == 1
    assert "Inconsciente" in v[0] and "Lyra" in v[0] and "apply_condition" in v[0]


def test_com_a_condicao_na_ficha_nao_cobra(mesa):
    _condicao("lyra", "Inconsciente")
    assert _checar(FRASE_DA_TESTE3, {"apply_condition"}) == []


def test_apply_condition_em_outra_pessoa_nao_basta(mesa):
    """Chamar a ferramenta para o Alden não põe a Lyra para dormir."""
    _condicao("alden", "Envenenado")
    assert _checar(FRASE_DA_TESTE3, {"apply_condition"})


@pytest.mark.parametrize("texto, cond", [
    ("Com um gesto, Lyra ficou paralisada no meio do passo.", "Paralisado"),
    ("Os dardos acertam e Alden e Lyra foram envenenados.", "Envenenado"),
    ("Lyra é enfeitiçada pelo olhar do vampiro.", "Enfeitiçado"),
    ("A luz explode e Kaelen ficou cego.", "Cego"),
    ("Lyra desmaiou sobre as pedras frias.", "Inconsciente"),
    ("Alden cai num sono sem sonhos ali mesmo.", "Inconsciente"),
    ("As raízes se fecham e Alden foi imobilizado.", "Contido"),
    ("Lyra ficou inconsciente depois do golpe.", "Inconsciente"),
])
def test_feminino_plural_passiva_e_sono(mesa, texto, cond):
    v = _checar(texto)
    assert v and cond in v[0], texto


@pytest.mark.parametrize("texto", [
    # Estado que já existia, não mudança.
    "Lyra está envenenada desde ontem e respira com dificuldade.",
    # Descrição, não condição nova.
    "O velho sentado à porta é cego de nascença.",
    # Admiração, não a condição.
    "Lyra ficou encantada com o brilho da joia.",
    # Ninguém citado e a palavra tem outro sentido.
    "O incêndio foi contido pelos guardas antes do amanhecer.",
    "A cidade adormece sob a neblina.",
])
def test_o_que_nao_e_condicao_nova_nao_cobra(mesa, texto):
    assert _checar(texto) == [], texto


def test_dormir_no_descanso_nao_e_a_condicao(mesa):
    assert _checar("Alden e Lyra adormecem no Javali Trôpego.", {"long_rest"}) == []
    assert _checar("Alden e Lyra adormecem no Javali Trôpego.")    # sem descanso, cobra


def test_status_dormindo_conta(mesa):
    memory.campaign["characters"]["lyra"]["status"] = "dormindo"
    assert _checar(FRASE_DA_TESTE3) == []


def test_frase_sem_nome_cobra_so_sem_a_ferramenta(mesa):
    texto = "O veneno corre rápido: ela ficou paralisada."
    assert _checar(texto)
    assert _checar(texto, {"apply_condition"}) == []


def test_primeiro_nome_conta(mesa):
    v = _checar("A espada brilha e Kaelen ficou atordoado.")
    assert v and "Kaelen Vane" in v[0]


def test_fora_das_regras_de_dnd_nao_cobra(mesa):
    memory.campaign["dnd_mode"] = False
    assert _checar(FRASE_DA_TESTE3) == []
