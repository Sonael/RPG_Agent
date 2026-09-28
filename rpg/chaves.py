"""
chaves.py
A chave de API do jogador, guardada no servidor e presa ao usuário.

POR QUE EXISTE
──────────────
A chave morava no `localStorage` do navegador, e o menu a injetava em
/api/session/start a cada início de sessão. Dois problemas, um relatado e um
estrutural:

  • RELATADO: o logout não a apagava, então a conta seguinte no mesmo
    navegador herdava a chave da anterior — e gastava a cota dela. Isso já foi
    corrigido no cliente (utils.limparDadosDoUsuario), mas o conserto custava
    um "colar de novo" a cada logout.

  • ESTRUTURAL: credencial no localStorage é credencial que qualquer XSS lê, e
    que viaja pela rede em toda chamada de início de sessão.

Aqui ela passa a viver numa linha por usuário. O navegador nunca mais a vê: o
menu mostra só se existe e os quatro últimos caracteres, e o servidor a lê
direto quando precisa. Trocar de aparelho leva a chave junto, e o logout volta
a ser trivialmente seguro porque não há nada local para esquecer.

    create table if not exists usuario_chaves (
      user_id           uuid primary key,
      google_api_key    text,
      deepseek_api_key  text,
      updated_at        timestamptz not null default now()
    );
    alter table usuario_chaves enable row level security;

CIFRADA EM REPOUSO, e o que isso quer dizer de verdade
──────────────────────────────────────────────────────
O valor é gravado com Fernet, e a chave de cifra é derivada do
SUPABASE_SERVICE_KEY (ou de RPG_SEGREDO_CHAVES, se preferir separar os dois).

O que isso protege: um vazamento do BANCO — um dump, um backup extraviado, um
olhar por cima do ombro no painel do Supabase — não entrega chaves usáveis.

O que isso NÃO protege: quem tem a service key tem tudo, porque é dela que a
cifra nasce. Não é teatro — é a diferença entre "vazou o banco" e "vazou o
servidor", que são incidentes de tamanhos bem diferentes —, mas é honesto
dizer onde a linha está.

Derivar do que já existe é de propósito: uma variável nova para configurar é
uma variável nova para esquecer, e o dia em que ela mudasse sem aviso todas as
chaves viravam lixo ilegível.

ENQUANTO O SQL NÃO RODAR, nada quebra: guardar responde que não deu, ler
devolve vazio, e o caminho antigo (a chave vinda no corpo do pedido) continua
atendendo. É a mesma tolerância das outras tabelas, pelo mesmo motivo.
"""

from __future__ import annotations

import base64
import hashlib
import os
from typing import Optional

_TABELA = "usuario_chaves"
# None = ainda não se sabe; True/False = descoberto na primeira tentativa.
_tem_tabela: Optional[bool] = None

CAMPOS = {"google": "google_api_key", "deepseek": "deepseek_api_key"}


# ---------------------------------------------------------------------------
# Cifra
# ---------------------------------------------------------------------------

_PREFIXO = "f1:"        # marca o que está cifrado, para conviver com o que não está
_fernet = None


def _cifrador():
    """O Fernet desta instalação, derivado do segredo que já existe."""
    global _fernet
    if _fernet is not None:
        return _fernet
    segredo = (os.environ.get("RPG_SEGREDO_CHAVES")
               or os.environ.get("SUPABASE_SERVICE_KEY") or "")
    if not segredo:
        return None
    from cryptography.fernet import Fernet
    # sha256 do segredo + um sal fixo do domínio: sempre 32 bytes, e o mesmo
    # segredo usado para outra coisa não gera a mesma chave de cifra.
    bruta = hashlib.sha256(f"rpg-chaves-de-api::{segredo}".encode()).digest()
    _fernet = Fernet(base64.urlsafe_b64encode(bruta))
    return _fernet


def _cifrar(valor: str) -> str:
    f = _cifrador()
    if not f or not valor:
        return valor
    return _PREFIXO + f.encrypt(valor.encode()).decode()


def _decifrar(valor: str) -> str:
    if not valor or not valor.startswith(_PREFIXO):
        return valor or ""          # gravado antes da cifra: vale como está
    f = _cifrador()
    if not f:
        return ""
    try:
        return f.decrypt(valor[len(_PREFIXO):].encode()).decode()
    except Exception:
        # Segredo trocado: a chave virou ilegível. Melhor pedir de novo do que
        # mandar lixo para a API do Google e o jogador não entender o erro.
        print("Aviso: não foi possível decifrar uma chave de API guardada — "
              "o segredo do servidor mudou? O jogador precisa informá-la de novo.")
        return ""


# ---------------------------------------------------------------------------
# Acesso
# ---------------------------------------------------------------------------

def _erro_de_tabela_ausente(erro: Exception) -> bool:
    texto = str(erro).lower()
    return (_TABELA in texto and
            any(m in texto for m in ("relation", "table", "42p01", "pgrst205",
                                     "does not exist", "schema cache",
                                     "not find the table")))


def _sem_tabela(erro: Exception) -> bool:
    global _tem_tabela
    if not _erro_de_tabela_ausente(erro):
        return False
    if _tem_tabela is not False:
        print(f"Aviso: tabela '{_TABELA}' não existe — a chave de API não será "
              f"guardada no servidor (rode o SQL). O caminho antigo continua "
              f"atendendo.")
    _tem_tabela = False
    return True


def _tabela(user_id: str):
    from rpg import database
    database._require_uid(user_id)
    return database._client().from_(_TABELA)


def ler(user_id: str) -> dict:
    """
    As chaves em claro, para o servidor usar. Nunca vão para o navegador.
    Devolve {"google": str, "deepseek": str} — vazio para o que não existe.
    """
    global _tem_tabela
    vazio = {nome: "" for nome in CAMPOS}
    if _tem_tabela is False or not user_id:
        return vazio
    try:
        r = (_tabela(user_id).select("google_api_key, deepseek_api_key")
             .eq("user_id", user_id).limit(1).execute())
        _tem_tabela = True
    except Exception as e:
        if not _sem_tabela(e):
            raise
        return vazio
    if not r.data:
        return vazio
    linha = r.data[0]
    return {nome: _decifrar(linha.get(coluna) or "") for nome, coluna in CAMPOS.items()}


def salvar(user_id: str, **novas) -> bool:
    """
    Grava as chaves informadas. `salvar(uid, google="abc")` muda só a do
    Google; `google=""` apaga a do Google; o que não vier fica como está.

    Devolve False quando a tabela ainda não existe — quem chama decide se isso
    é erro para o jogador ou apenas o caminho antigo seguindo em frente.
    """
    global _tem_tabela
    if _tem_tabela is False or not user_id:
        return False
    linha = {"user_id": user_id}
    for nome, coluna in CAMPOS.items():
        valor = novas.get(nome)
        if valor is None:
            continue
        linha[coluna] = _cifrar(valor.strip()) if valor.strip() else None
    if len(linha) == 1:
        return True                      # nada a mudar
    try:
        _tabela(user_id).upsert(linha, on_conflict="user_id").execute()
        _tem_tabela = True
        return True
    except Exception as e:
        if not _sem_tabela(e):
            raise
        return False


def apagar(user_id: str) -> None:
    """Tira as chaves deste usuário. Usado quando ele apaga a conta."""
    if _tem_tabela is False or not user_id:
        return
    try:
        _tabela(user_id).delete().eq("user_id", user_id).execute()
    except Exception as e:
        if not _sem_tabela(e):
            raise


def resumo(user_id: str) -> dict:
    """
    O que a TELA pode saber: se existe, e o fim dela para o jogador se
    reconhecer. A chave inteira nunca volta ao navegador — é isso que faz a
    mudança valer a pena.
    """
    guardadas = ler(user_id)
    saida = {}
    for nome, valor in guardadas.items():
        saida[nome] = {"definida": bool(valor),
                       "fim": valor[-4:] if len(valor) >= 4 else ""}
    return saida
