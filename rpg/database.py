"""
database.py
Camada de acesso ao Supabase para persistência de campanhas.
Toda operação de banco passa por aqui — o resto do sistema não conhece Supabase.

SEGURANÇA — escopo de usuário estrutural:
  O backend usa a SERVICE KEY (service role), que ignora Row-Level Security.
  Portanto o isolamento entre usuários depende de TODA query ser filtrada por
  `user_id`. Para tornar isso impossível de esquecer, NENHUMA função acessa a
  tabela `campaigns` diretamente: todo acesso passa pelos helpers
  `_scoped_select` / `_scoped_delete` / `_scoped_update` / `_scoped_upsert`,
  que (1) exigem um `user_id` válido — levantam erro se vier vazio — e
  (2) já embutem o filtro `.eq("user_id", user_id)`. A RLS habilitada no
  Supabase é a camada extra de defesa em profundidade.
"""

import os
import json
from typing import Optional
from postgrest import SyncPostgrestClient


def _client() -> SyncPostgrestClient:
    """Cria e retorna um cliente Postgrest direto."""
    url = f"{os.environ['SUPABASE_URL']}/rest/v1"
    headers = {
        "apikey": os.environ["SUPABASE_SERVICE_KEY"],
        "Authorization": f"Bearer {os.environ['SUPABASE_SERVICE_KEY']}"
    }
    return SyncPostgrestClient(url, headers=headers)


# ---------------------------------------------------------------------------
# Guard de escopo de usuário — único caminho de acesso à tabela `campaigns`
# ---------------------------------------------------------------------------

_TABLE = "campaigns"


def _require_uid(user_id: str) -> str:
    """
    Valida o user_id. Levanta PermissionError se vier vazio/None/tipo
    errado — torna estruturalmente impossível rodar uma query sem escopo
    de usuário (que vazaria ou apagaria dados de terceiros).
    """
    if not isinstance(user_id, str) or not user_id.strip():
        raise PermissionError(
            "Operação no banco sem user_id válido — bloqueada por segurança."
        )
    return user_id


def _scoped_select(user_id: str, columns: str):
    """SELECT na tabela campaigns JÁ filtrado por user_id."""
    _require_uid(user_id)
    return _client().from_(_TABLE).select(columns).eq("user_id", user_id)


def _scoped_delete(user_id: str):
    """DELETE na tabela campaigns JÁ filtrado por user_id."""
    _require_uid(user_id)
    return _client().from_(_TABLE).delete().eq("user_id", user_id)


def _scoped_update(user_id: str, patch: dict):
    """UPDATE na tabela campaigns JÁ filtrado por user_id."""
    _require_uid(user_id)
    return _client().from_(_TABLE).update(patch).eq("user_id", user_id)


def _scoped_upsert(user_id: str, name: str, linha: dict):
    """UPSERT garantindo user_id no payload e na chave de conflito."""
    _require_uid(user_id)
    return _client().from_(_TABLE).upsert(
        {"user_id": user_id, "name": name, **linha},
        on_conflict="user_id,name",
    )


# ---------------------------------------------------------------------------
# O histórico mora em coluna própria
# ---------------------------------------------------------------------------
# Medido na campanha real: o documento tinha 219 KB e 180 KB deles eram
# conversation_history — 82% que viajavam em TODA gravação, e um turno grava.
# Pior: list_campaigns (a tela de escolher campanha) faz `select name, data` e
# baixava o histórico INTEIRO de todas as campanhas só para montar a lista.
#
# Agora o histórico sai do `data` e vai para a coluna `historico`:
#
#     alter table campaigns add column if not exists historico jsonb
#       default '[]'::jsonb;
#
# O PostgREST grava só as colunas que recebe, então uma gravação de turno
# deixa de carregar a conversa inteira.
#
# TOLERA OS DOIS MUNDOS, de propósito: se a coluna não existir (ambiente onde
# o SQL não rodou), a primeira tentativa falha, o módulo anota isso e volta ao
# formato antigo — sem derrubar o turno de ninguém. E, na leitura, campanha
# gravada no formato ANTIGO continua abrindo: o histórico é procurado na
# coluna e, se ela estiver vazia, dentro do `data`.
_COLUNA_HISTORICO = "historico"
_CHAVE_HISTORICO = "conversation_history"
# None = ainda não se sabe; True/False = descoberto na primeira tentativa.
_tem_coluna_historico: Optional[bool] = None


def _erro_de_coluna_ausente(erro: Exception) -> bool:
    texto = str(erro).lower()
    return ("historico" in texto and
            any(m in texto for m in ("column", "coluna", "pgrst204", "42703",
                                     "does not exist", "schema cache")))


def _separar_historico(data: dict) -> tuple[dict, list]:
    """(data sem a conversa, conversa). Não altera o dict recebido."""
    resto = dict(data or {})
    historico = resto.pop(_CHAVE_HISTORICO, None) or []
    # A tela de campanhas precisa saber se HÁ conversa sem baixar a conversa.
    resto["_n_historico"] = len(historico)
    return resto, list(historico)


def _juntar_historico(data: dict, historico) -> dict:
    """
    Devolve a campanha inteira para quem lê. A coluna manda; sem ela, vale o
    que estiver no `data` (campanha ainda no formato antigo).
    """
    completo = dict(data or {})
    if historico:
        completo[_CHAVE_HISTORICO] = list(historico)
    else:
        completo.setdefault(_CHAVE_HISTORICO, [])
    completo.pop("_n_historico", None)
    return completo


def versao_de(data: dict):
    """A versão que veio do banco, para a sessão devolver na gravação."""
    return (data or {}).get(CAMPO_VERSAO)


# ---------------------------------------------------------------------------
# Campanhas
# ---------------------------------------------------------------------------

def list_campaigns(user_id: str) -> list[dict]:
    """
    Lista todas as campanhas de um usuário com metadados resumidos.
    """
    result = (
        _scoped_select(user_id, "name, data")
        .order("updated_at", desc=True)
        .execute()
    )
    rows = result.data or []
    out  = []
    for row in rows:
        d = row.get("data", {})
        out.append({
            "name":        row["name"],
            "chapter":     d.get("chapter", 1),
            "location":    d.get("current_location", ""),
            "characters":  len(d.get("characters", {})),
            "events":      len(d.get("events", [])),
            "diary":       len(d.get("diary", [])),
            # A conversa não vem mais no `data` (ela tem coluna própria), e
            # baixá-la para montar o MENU era o desperdício mais caro do
            # sistema: todas as campanhas inteiras para desenhar uma lista.
            # O contador é gravado junto e responde a mesma pergunta de graça.
            # `or` para a campanha ainda no formato antigo.
            "has_history": bool(d.get("_n_historico")
                                or d.get("conversation_history")),
        })
    return out


def get_campaign(user_id: str, name: str) -> Optional[dict]:
    """
    Carrega os dados completos de uma campanha — inclusive o histórico, que
    hoje mora em coluna própria e antes morava dentro do `data`.
    """
    global _tem_coluna_historico

    colunas = "data" if _tem_coluna_historico is False else f"data, {_COLUNA_HISTORICO}"
    try:
        result = _scoped_select(user_id, colunas).eq("name", name).limit(1).execute()
        if _tem_coluna_historico is None and colunas != "data":
            _tem_coluna_historico = True
    except Exception as e:
        if not _erro_de_coluna_ausente(e):
            raise
        _tem_coluna_historico = False
        result = _scoped_select(user_id, "data").eq("name", name).limit(1).execute()

    if not result.data:
        return None
    linha = result.data[0]
    return _juntar_historico(linha.get("data") or {}, linha.get(_COLUNA_HISTORICO))


# ---------------------------------------------------------------------------
# Escrita perdida: detectar em vez de descobrir tarde
# ---------------------------------------------------------------------------
# Duas abas na mesma campanha, ou o chat gravando enquanto a tela de saque
# grava: quem termina por último apaga o turno do outro, em silêncio e no
# documento inteiro. O `_version` dentro do `data` transforma isso em fato
# conhecido — a gravação só vale se a versão que está no banco ainda for a que
# esta sessão leu.
#
# Sem DDL: a condição é um filtro no caminho do JSON, que o PostgREST entende.
# E com desconfiança: se a condição NÃO pegar nenhuma linha, a gravação não é
# descartada antes de conferir se houve conflito de verdade — um filtro que se
# comporte diferente do esperado neste Postgrest travaria TODAS as gravações,
# que é muito pior do que o problema que ele resolve.
CAMPO_VERSAO = "_version"
_versao_condicional = True      # desligado sozinho se o filtro não servir


class ConflitoDeGravacao(Exception):
    """Alguém gravou esta campanha depois de a sessão tê-la lido."""

    def __init__(self, esperada, encontrada):
        super().__init__(f"versão esperada {esperada}, encontrada {encontrada}")
        self.esperada, self.encontrada = esperada, encontrada


def _versao_gravada(user_id: str, name: str):
    """A versão que está no banco agora, ou None se a linha não existe."""
    r = _scoped_select(user_id, "data").eq("name", name).limit(1).execute()
    if not r.data:
        return None
    return (r.data[0].get("data") or {}).get(CAMPO_VERSAO)


def save_campaign(user_id: str, name: str, data: dict,
                  versao_esperada=None) -> int:
    """
    Salva (insert ou update) os dados de uma campanha. Devolve a versão
    gravada.

    O histórico de conversa vai para a coluna própria; o resto, para `data`.
    Quando a coluna não existe, grava tudo junto como antes.

    `versao_esperada` liga a trava contra escrita perdida: a gravação só
    acontece se o banco ainda estiver nessa versão. Levanta
    ConflitoDeGravacao quando não estiver. Sem ela, grava como sempre.
    """
    global _tem_coluna_historico, _versao_condicional

    usa_coluna = _tem_coluna_historico is not False
    resto, historico = (_separar_historico(data) if usa_coluna
                        else (dict(data or {}), None))
    nova = int(versao_esperada or resto.get(CAMPO_VERSAO) or 0) + 1
    resto[CAMPO_VERSAO] = nova
    linha = {"data": resto} if historico is None else {"data": resto,
                                                       _COLUNA_HISTORICO: historico}

    def _gravar_sem_trava():
        _scoped_upsert(user_id, name, linha).execute()
        return nova

    try:
        if versao_esperada is None or not _versao_condicional:
            resultado = _gravar_sem_trava()
        else:
            r = (_scoped_update(user_id, linha)
                 .eq("name", name)
                 .eq(f"data->>{CAMPO_VERSAO}", str(versao_esperada))
                 .execute())
            if r.data:
                resultado = nova
            else:
                # Zero linhas: pode ser conflito de verdade, pode ser linha
                # nova, pode ser o filtro não servir neste Postgrest. Conferir
                # custa uma leitura, e só acontece neste caso raro.
                atual = _versao_gravada(user_id, name)
                if atual is None:
                    resultado = _gravar_sem_trava()
                elif str(atual) == str(versao_esperada):
                    _versao_condicional = False
                    print("Aviso: a trava de versão não filtrou nada neste "
                          "Postgrest — desligada, gravando como antes.")
                    resultado = _gravar_sem_trava()
                else:
                    raise ConflitoDeGravacao(versao_esperada, atual)
        if usa_coluna:
            _tem_coluna_historico = True
        return resultado
    except ConflitoDeGravacao:
        raise
    except Exception as e:
        if not _erro_de_coluna_ausente(e):
            raise
        # Ambiente sem a coluna: volta ao formato antigo e não tenta de novo.
        _tem_coluna_historico = False
        print("Aviso: coluna 'historico' não existe — gravando no formato "
              "antigo (rode o ALTER TABLE para aliviar as gravações).")
        antigo = dict(data or {})
        antigo[CAMPO_VERSAO] = nova
        _scoped_upsert(user_id, name, {"data": antigo}).execute()
        return nova


def delete_campaign(user_id: str, name: str) -> None:
    """Remove uma campanha do banco."""
    _scoped_delete(user_id).eq("name", name).execute()


def rename_campaign(user_id: str, old_name: str, new_name: str) -> None:
    """Renomeia uma campanha."""
    _scoped_update(user_id, {"name": new_name}).eq("name", old_name).execute()


def campaign_exists(user_id: str, name: str) -> bool:
    """Verifica se uma campanha com esse nome já existe."""
    result = (
        _scoped_select(user_id, "name")
        .eq("name", name)
        .limit(1)
        .execute()
    )
    return bool(result.data)
