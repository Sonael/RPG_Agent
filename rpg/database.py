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
# O histórico em tabela própria: uma linha por mensagem
# ---------------------------------------------------------------------------
# A coluna `historico` resolveu o peso da gravação, mas não isto:
# memory.MAX_HISTORY_SAVED corta a conversa nas últimas 200 mensagens A CADA
# GRAVAÇÃO. O turno 300 de uma campanha apaga o turno 100 — de vez. O jogador
# não tem como reler a cena em que conheceu alguém, e o sistema não tem como
# procurar "onde foi mesmo que a gente deixou o cavalo".
#
# Uma linha por mensagem resolve os dois: nada é apagado, a janela de trabalho
# continua sendo as últimas 200 (é isso que o mestre lê e a tela desenha), e o
# que ficou para trás se alcança por página ou por busca.
#
#     create table if not exists historico_mensagens (
#       id             bigserial primary key,
#       user_id        text    not null,
#       campaign_name  text    not null,
#       ordem          integer not null,
#       role           text    not null,
#       content        text    not null default '',
#       interno        text,
#       created_at     timestamptz not null default now(),
#       unique (user_id, campaign_name, ordem)
#     );
#     create index if not exists historico_mensagens_campanha
#       on historico_mensagens (user_id, campaign_name, ordem desc);
#     create index if not exists historico_mensagens_busca
#       on historico_mensagens using gin (to_tsvector('portuguese', content));
#     alter table historico_mensagens enable row level security;
#
# ENQUANTO O SQL NÃO RODAR, nada muda: a primeira tentativa falha, o módulo
# anota isso e a conversa continua na coluna `historico`, como está hoje. É a
# mesma tolerância da coluna, pelo mesmo motivo — ambiente sem a DDL não pode
# parar de gravar.
_TABELA_HISTORICO = "historico_mensagens"
# None = ainda não se sabe; True/False = descoberto na primeira tentativa.
_tem_tabela_historico: Optional[bool] = None
# Quantas mensagens a leitura traz para a janela de trabalho. É o mesmo teto
# de memory.MAX_HISTORY_SAVED; aqui o resto não some, só fica fora da janela.
JANELA_HISTORICO = 200


def _erro_de_tabela_ausente(erro: Exception) -> bool:
    texto = str(erro).lower()
    return (_TABELA_HISTORICO in texto and
            any(m in texto for m in ("relation", "table", "42p01", "pgrst205",
                                     "does not exist", "schema cache",
                                     "not find the table")))


def _sem_tabela(erro: Exception) -> bool:
    """
    True (e anota, avisando UMA vez) quando o erro é a tabela não existir.
    Qualquer outro erro devolve False e quem chamou torna a levantá-lo — erro
    de rede não pode ser confundido com ambiente sem DDL.
    """
    global _tem_tabela_historico
    if not _erro_de_tabela_ausente(erro):
        return False
    if _tem_tabela_historico is not False:
        print(f"Aviso: tabela '{_TABELA_HISTORICO}' não existe — a conversa "
              f"continua na coluna 'historico' (rode o SQL para guardar a "
              f"campanha inteira, e não só as últimas 200 mensagens).")
    _tem_tabela_historico = False
    return True


def _mensagens(user_id: str):
    """SELECT na tabela de mensagens JÁ filtrado por user_id."""
    _require_uid(user_id)
    return _client().from_(_TABELA_HISTORICO)


def _linha_de_mensagem(user_id: str, name: str, ordem: int, msg) -> dict:
    if not isinstance(msg, dict):
        msg = {"role": "user", "text": str(msg)}
    return {
        "user_id": user_id, "campaign_name": name, "ordem": ordem,
        "role": (msg.get("role") or "user")[:20],
        "content": msg.get("text") or msg.get("content") or "",
        "interno": (msg.get("interno") or None),
    }


def _mensagem_para_a_memoria(linha: dict) -> dict:
    msg = {"role": linha.get("role") or "user", "text": linha.get("content") or ""}
    if linha.get("interno"):
        msg["interno"] = linha["interno"]
    return msg


def _mesma_mensagem(msg, linha: dict) -> bool:
    if not isinstance(msg, dict):
        msg = {"role": "user", "text": str(msg)}
    return ((msg.get("text") or msg.get("content") or "") == (linha.get("content") or "")
            and (msg.get("role") or "user") == (linha.get("role") or "user"))


def _gravar_mensagens(user_id: str, name: str, historico: list) -> int:
    """
    Manda para a tabela só o que ainda não está lá e devolve o total gravado.

    O que chega aqui é a JANELA (as últimas 200), e ela ANDA: no turno
    seguinte a primeira mensagem caiu fora e uma nova entrou no fim. Contar
    pelo tamanho não serve — janela de 200 depois de 200 gravadas não teria
    novidade nenhuma, e a mensagem nova se perderia em silêncio.

    Quem diz onde a janela se encaixa é a ÚLTIMA linha gravada: procurada de
    trás para a frente na janela, tudo o que vem depois dela é novo. Se ela
    não aparecer na janela (conversa reiniciada, ou mais de 200 mensagens
    entre duas gravações), a janela inteira é acrescentada ao fim: repetir é
    ruim, perder é pior.
    """
    global _tem_tabela_historico
    if _tem_tabela_historico is False:
        return 0

    ultima = _ultima_mensagem(user_id, name)
    if ultima is None:
        novas_msgs, proxima = list(historico), 0
    else:
        corte = -1
        for j in range(len(historico) - 1, -1, -1):
            if _mesma_mensagem(historico[j], ultima):
                corte = j
                break
        novas_msgs = list(historico[corte + 1:])
        proxima = int(ultima["ordem"]) + 1

    if not novas_msgs:
        return proxima
    linhas = [_linha_de_mensagem(user_id, name, proxima + i, m)
              for i, m in enumerate(novas_msgs)]
    try:
        _mensagens(user_id).upsert(
            linhas, on_conflict="user_id,campaign_name,ordem").execute()
    except Exception as e:
        if not _sem_tabela(e):
            raise
        return 0
    _tem_tabela_historico = True
    total = proxima + len(linhas)
    _TOTAL_GRAVADO[(user_id, name)] = total
    _ULTIMA_GRAVADA[(user_id, name)] = dict(linhas[-1])
    return total


# Cache de processo: quantas mensagens cada campanha tem e qual é a última.
# A resposta certa está sempre no banco — quando não se sabe, pergunta-se.
_TOTAL_GRAVADO: dict = {}
_ULTIMA_GRAVADA: dict = {}


def _ultima_mensagem(user_id: str, name: str) -> Optional[dict]:
    """A última linha gravada desta campanha, ou None se não há nenhuma."""
    global _tem_tabela_historico
    chave = (user_id, name)
    if chave in _ULTIMA_GRAVADA:
        return _ULTIMA_GRAVADA[chave]
    if _tem_tabela_historico is False:
        return None
    try:
        r = (_mensagens(user_id).select("ordem, role, content")
             .eq("user_id", user_id).eq("campaign_name", name)
             .order("ordem", desc=True).limit(1).execute())
        _tem_tabela_historico = True
    except Exception as e:
        if not _sem_tabela(e):
            raise
        return None
    linha = dict(r.data[0]) if r.data else None
    _ULTIMA_GRAVADA[chave] = linha
    _TOTAL_GRAVADO[chave] = (int(linha["ordem"]) + 1) if linha else 0
    return linha


def _total_gravado(user_id: str, name: str) -> int:
    chave = (user_id, name)
    if chave not in _TOTAL_GRAVADO:
        _ultima_mensagem(user_id, name)
    return _TOTAL_GRAVADO.get(chave, 0)


def _ler_janela(user_id: str, name: str) -> Optional[list]:
    """
    As últimas JANELA_HISTORICO mensagens, na ordem em que foram ditas.

    None quando a tabela não existe (quem chama volta para a coluna) ou
    quando esta campanha ainda não tem linha nenhuma lá.
    """
    global _tem_tabela_historico
    if _tem_tabela_historico is False:
        return None
    try:
        r = (_mensagens(user_id)
             .select("ordem, role, content, interno")
             .eq("user_id", user_id).eq("campaign_name", name)
             .order("ordem", desc=True).limit(JANELA_HISTORICO).execute())
        _tem_tabela_historico = True
    except Exception as e:
        if not _sem_tabela(e):
            raise
        return None
    linhas = list(reversed(r.data or []))
    if not linhas:
        return None
    _TOTAL_GRAVADO[(user_id, name)] = int(linhas[-1]["ordem"]) + 1
    _ULTIMA_GRAVADA[(user_id, name)] = {
        "ordem": linhas[-1]["ordem"], "role": linhas[-1].get("role"),
        "content": linhas[-1].get("content"),
    }
    return [_mensagem_para_a_memoria(l) for l in linhas]


def total_de_mensagens(user_id: str, name: str) -> int:
    """
    Quantas mensagens esta campanha tem guardadas. 0 quando a tabela não
    existe — e é assim que a tela sabe que não há nada atrás da janela.
    """
    try:
        return _total_gravado(user_id, name)
    except Exception:
        return 0


def historico_pagina(user_id: str, name: str, antes_de: Optional[int] = None,
                     limite: int = 50) -> dict:
    """
    Uma página da conversa, para trás. `antes_de` é a `ordem` da mensagem mais
    antiga que a tela já tem; sem ela, a página começa no fim.

    Devolve {"mensagens": [...], "tem_mais": bool, "primeira_ordem": int|None}.
    A tela usa `primeira_ordem` como `antes_de` do próximo pedido.
    """
    limite = max(1, min(int(limite or 50), 200))
    q = (_mensagens(user_id)
         .select("ordem, role, content, interno")
         .eq("user_id", user_id).eq("campaign_name", name))
    if antes_de is not None:
        q = q.lt("ordem", int(antes_de))
    try:
        r = q.order("ordem", desc=True).limit(limite + 1).execute()
    except Exception as e:
        if not _sem_tabela(e):
            raise
        return {"mensagens": [], "tem_mais": False, "primeira_ordem": None}
    linhas = list(r.data or [])
    tem_mais = len(linhas) > limite
    linhas = list(reversed(linhas[:limite]))
    return {
        "mensagens": [dict(_mensagem_para_a_memoria(l), ordem=l.get("ordem"))
                      for l in linhas],
        "tem_mais": tem_mais,
        "primeira_ordem": linhas[0]["ordem"] if linhas else None,
    }


def historico_busca(user_id: str, name: str, termo: str,
                    limite: int = 30) -> list[dict]:
    """
    Mensagens desta campanha que contêm `termo`, da mais recente para a mais
    antiga. Busca literal (ilike): é o que responde "onde a gente deixou o
    cavalo" sem depender de dicionário de idioma no banco.
    """
    termo = (termo or "").strip()
    if len(termo) < 2:
        return []
    limite = max(1, min(int(limite or 30), 100))
    # `%` e `_` são curingas do LIKE: escapados, a busca procura o que o
    # jogador digitou.
    seguro = termo.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    try:
        r = (_mensagens(user_id)
             .select("ordem, role, content, interno")
             .eq("user_id", user_id).eq("campaign_name", name)
             .ilike("content", f"%{seguro}%")
             .order("ordem", desc=True).limit(limite).execute())
    except Exception as e:
        if not _sem_tabela(e):
            raise
        return []
    return [dict(_mensagem_para_a_memoria(l), ordem=l.get("ordem"))
            for l in (r.data or [])]


def _apagar_historico(user_id: str, name: str) -> None:
    if _tem_tabela_historico is False:
        return
    try:
        (_mensagens(user_id).delete()
         .eq("user_id", user_id).eq("campaign_name", name).execute())
    except Exception as e:
        if not _sem_tabela(e):
            raise


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
    # A tabela manda quando existe e já tem linha desta campanha; a coluna é
    # o que sobra para campanha antiga e para ambiente sem o SQL rodado.
    janela = _ler_janela(user_id, name)
    return _juntar_historico(linha.get("data") or {},
                             janela if janela is not None
                             else linha.get(_COLUNA_HISTORICO))


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

    # A conversa inteira vai para a tabela, uma linha por mensagem: é o que
    # impede o corte das últimas 200 de apagar o começo da campanha. A coluna
    # continua recebendo a janela, para o ambiente onde a tabela não existe e
    # para quem abrir a campanha por outro caminho.
    if historico is not None:
        gravadas = _gravar_mensagens(user_id, name, historico)
        if gravadas:
            resto["_n_historico"] = gravadas

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
    """Remove uma campanha do banco — inclusive a conversa dela."""
    _scoped_delete(user_id).eq("name", name).execute()
    _apagar_historico(user_id, name)
    _TOTAL_GRAVADO.pop((user_id, name), None)


def rename_campaign(user_id: str, old_name: str, new_name: str) -> None:
    """
    Renomeia uma campanha. As mensagens são ligadas pelo NOME, então elas
    mudam junto — sem isto, renomear largava a conversa inteira órfã.
    """
    global _tem_tabela_historico
    _scoped_update(user_id, {"name": new_name}).eq("name", old_name).execute()
    if _tem_tabela_historico is False:
        return
    try:
        (_mensagens(user_id).update({"campaign_name": new_name})
         .eq("user_id", user_id).eq("campaign_name", old_name).execute())
    except Exception as e:
        if not _sem_tabela(e):
            raise
        _tem_tabela_historico = False
    _TOTAL_GRAVADO[(user_id, new_name)] = _TOTAL_GRAVADO.pop(
        (user_id, old_name), 0)


def campaign_exists(user_id: str, name: str) -> bool:
    """Verifica se uma campanha com esse nome já existe."""
    result = (
        _scoped_select(user_id, "name")
        .eq("name", name)
        .limit(1)
        .execute()
    )
    return bool(result.data)
