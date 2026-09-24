"""
test_auth_cliente.py
O cliente de autenticação do servidor não pode ter vida própria.

POR QUÊ
───────
O gotrue foi portado do JavaScript e traz o hábito do navegador: ao guardar
uma sessão ele liga um cronômetro em segundo plano para renovar o token
sozinho (`_start_auto_refresh_token`) e guarda a sessão numa gaveta interna.

No navegador isso faz sentido — a aba é dona da sessão. Aqui não: quem é dono
do refresh token é o JOGADOR, no localStorage dele. Um cronômetro do lado do
servidor gastando o mesmo papel produziria exatamente o erro que tirou o
jogador do meio da partida:

    Falha no refresh: Invalid Refresh Token: Already Used

Cada requisição ainda cria um cliente novo, então o cronômetro também seria
uma linha (Thread) viva por login, sem ninguém para desligá-la.

Este arquivo tranca as duas portas: sem renovação automática, sem sessão
guardada, e o que o Supabase responde chega inteiro a quem chamou.
"""
import pytest

from rpg import auth


@pytest.fixture
def ambiente(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://exemplo.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "chave-de-mentira")


def test_cliente_nao_renova_por_conta_propria(ambiente):
    cliente = auth._client()
    # Atributos internos do gotrue de propósito: é justamente o comportamento
    # escondido dele que precisa ficar desligado. Se um dia mudarem o nome,
    # este teste cai — e cair é o certo, porque a proteção teria sumido junto.
    assert cliente._auto_refresh_token is False
    assert cliente._persist_session is False
    assert cliente._refresh_token_timer is None


class _Sessao:
    access_token = "acesso-novo"
    refresh_token = "refresh-novo"


class _Resultado:
    session = _Sessao()


class _ClienteFalso:
    def __init__(self):
        self.recebeu = None

    def refresh_session(self, token):
        self.recebeu = token
        return _Resultado()


def test_refresh_devolve_o_par_novo(monkeypatch):
    falso = _ClienteFalso()
    monkeypatch.setattr(auth, "_client", lambda: falso)

    assert auth.refresh_session("refresh-velho") == {
        "access_token": "acesso-novo",
        "refresh_token": "refresh-novo",
    }
    # O papel do jogador é o que vai para o Supabase — o servidor não tem um
    # seu para usar no lugar.
    assert falso.recebeu == "refresh-velho"


def test_recusa_do_supabase_chega_inteira(monkeypatch):
    class _Recusa:
        def refresh_session(self, token):
            raise Exception("Invalid Refresh Token: Already Used")

    monkeypatch.setattr(auth, "_client", lambda: _Recusa())

    with pytest.raises(ValueError) as erro:
        auth.refresh_session("gasto")
    # O motivo aparece no log do servidor; é por ele que se descobre a
    # diferença entre "venceu" e "alguém já gastou este papel".
    assert "Already Used" in str(erro.value)
