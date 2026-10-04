"""
ritmo.py — o tamanho e o ritmo das chamadas ao modelo.

Numa partida longa o Gemini (plano gratuito: 250 mil tokens de entrada por
minuto no Flash) respondia "limite de tokens por minuto" no meio do turno.
Três coisas somavam:

  • cada chamada leva uns 35 mil tokens fixos (as instruções do Mestre e o
    esquema das ferramentas), e um turno são várias chamadas: uma por ida e
    volta de ferramenta;
  • a sessão do ADK guardava a partida inteira, com toda chamada e toda
    resposta de ferramenta, e reenviava tudo a cada chamada: em trinta
    turnos, o histórico pesava mais que a parte fixa;
  • o retry esperava 2, 4, 8 e 16 segundos, menos que o minuto da janela, e
    cada tentativa gastava outra vez o prompt inteiro.

Aqui ficam as três respostas:

  • enxugar_historico: dos turnos anteriores ficam as falas e as narrações;
    as chamadas e respostas de ferramenta saem, porque o estado do jogo já
    vai, atualizado, nas instruções de cada chamada (agent._instruction_
    provider). Só os últimos TURNOS_GUARDADOS turnos ficam; o que veio antes
    está no resumo e no diário.
  • ritmo: os tokens enviados no último minuto, por chave de API. Antes de
    uma chamada que passaria do limite, o Mestre espera o necessário (e a
    tela diz por quê), em vez de levar o erro no meio do turno.
  • o erro 429: o tempo que o próprio Gemini pede ("retryDelay"), o limite
    que ele informa ("limit: 250000") e a cota DIÁRIA, que não volta em
    segundos e não adianta repetir.

Os ganchos (antes_do_modelo, depois_do_modelo) entram no Agent em
agent.create_agent; o servidor vincula a chave e o aviso da tela por turno
(vincular), como memory.bind_request faz com a campanha.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import re
import time
from collections import deque
from typing import Callable, Optional

from google.genai import types

JANELA_S = 60.0
# Margem: a conta é por estimativa, e o Google conta do jeito dele.
FOLGA = 0.9
# Turnos anteriores que o Mestre ainda lê palavra por palavra.
TURNOS_GUARDADOS = 10
# Texto antigo muito longo (o log de um combate inteiro) vira um trecho.
TEXTO_ANTIGO_MAX = 3000
# Caracteres por token, por cima (pt-BR, acentos, JSON das ferramentas): é
# melhor superestimar e esperar um pouco do que levar o erro.
CARACTERES_POR_TOKEN = 3.2

# Limite de tokens de ENTRADA por minuto, por modelo, no plano gratuito do
# Gemini. Plano pago tem bem mais; o erro 429 ensina o limite real da chave
# (aprender_do_erro), para baixo ou para cima.
_LIMITE_GRATUITO = {"pro": 125_000}
_LIMITE_GRATUITO_PADRAO = 250_000


def limite_padrao(model_id: str) -> Optional[int]:
    """O limite de partida para o modelo; None quando não é Gemini (Ollama, DeepSeek)."""
    m = (model_id or "").lower()
    if not m or m.startswith(("ollama:", "deepseek:")):
        return None
    for chave, limite in _LIMITE_GRATUITO.items():
        if chave in m:
            return limite
    return _LIMITE_GRATUITO_PADRAO


# ---------------------------------------------------------------------------
# A janela de um minuto, por chave
# ---------------------------------------------------------------------------

_janelas: dict[str, deque] = {}
_limites_aprendidos: dict[str, int] = {}


def registrar(chave: str, tokens: int, agora: Optional[float] = None) -> None:
    """Soma à janela os tokens de entrada de uma chamada que acabou de ir."""
    if not chave or tokens <= 0:
        return
    agora = time.monotonic() if agora is None else agora
    janela = _janelas.setdefault(chave, deque())
    janela.append((agora, int(tokens)))
    _podar(janela, agora)


def _podar(janela: deque, agora: float) -> None:
    while janela and agora - janela[0][0] >= JANELA_S:
        janela.popleft()


def usados(chave: str, agora: Optional[float] = None) -> int:
    agora = time.monotonic() if agora is None else agora
    janela = _janelas.get(chave)
    if not janela:
        return 0
    _podar(janela, agora)
    return sum(t for _, t in janela)


def limite(chave: str, model_id: str = "") -> Optional[int]:
    return _limites_aprendidos.get(chave) or limite_padrao(model_id)


def espera_necessaria(chave: str, estimativa: int, teto: Optional[int],
                      agora: Optional[float] = None) -> float:
    """
    Segundos a esperar antes de mandar `estimativa` tokens sem passar de
    FOLGA × teto no último minuto. 0 quando cabe. Uma chamada maior que o
    teto inteiro espera a janela esvaziar e vai assim mesmo.
    """
    if not chave or not teto:
        return 0.0
    agora = time.monotonic() if agora is None else agora
    janela = _janelas.get(chave)
    if not janela:
        return 0.0
    _podar(janela, agora)
    cabe = FOLGA * teto
    total = sum(t for _, t in janela)
    if total + estimativa <= cabe:
        return 0.0
    # Espera sair da janela o bastante, do mais antigo para o mais novo.
    for instante, tokens in janela:
        total -= tokens
        if total + estimativa <= cabe or total <= 0:
            return max(0.0, instante + JANELA_S - agora) + 0.5
    return JANELA_S


def esquecer(chave: Optional[str] = None) -> None:
    """Zera a janela e o limite aprendido (de uma chave, ou de todas; para os testes)."""
    if chave is None:
        _janelas.clear()
        _limites_aprendidos.clear()
    else:
        _janelas.pop(chave, None)
        _limites_aprendidos.pop(chave, None)


# ---------------------------------------------------------------------------
# O erro 429 do Gemini
# ---------------------------------------------------------------------------
# A mensagem traz, entre outras coisas:
#   Quota exceeded for metric: generativelanguage.googleapis.com/
#   generate_content_free_tier_input_token_count, limit: 250000, model: ...
#   Please retry in 23.123456s.
#   ... 'quotaId': 'GenerateContentInputTokensPerModelPerMinute-FreeTier' ...
#   ... 'retryDelay': '23s' ...

_RE_RETRY_DELAY = re.compile(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s", re.I)
_RE_RETRY_IN = re.compile(r"retry in\s+(\d+(?:\.\d+)?)\s*s", re.I)
_RE_LIMITE_ENTRADA = re.compile(r"input_token_count[^,]*,\s*limit:\s*(\d+)", re.I)


def espera_do_erro(texto: str) -> Optional[float]:
    """O tempo que o Gemini pediu para tentar de novo, em segundos, ou None."""
    for padrao in (_RE_RETRY_DELAY, _RE_RETRY_IN):
        m = padrao.search(texto or "")
        if m:
            return float(m.group(1))
    return None


def e_limite_por_minuto(texto: str) -> bool:
    t = (texto or "").lower()
    return "perminute" in t or "per minute" in t or "input_token_count" in t


def e_limite_diario(texto: str) -> bool:
    """A cota do DIA acabou: repetir em segundos só gasta tentativa."""
    t = (texto or "").lower()
    return "perday" in t or "per day" in t


def aprender_do_erro(chave: str, texto: str) -> Optional[int]:
    """Guarda o limite de entrada por minuto que o erro informa para esta chave."""
    m = _RE_LIMITE_ENTRADA.search(texto or "")
    if not (chave and m):
        return None
    _limites_aprendidos[chave] = int(m.group(1))
    return _limites_aprendidos[chave]


def espera_para_tentar_de_novo(texto: str, tentativa: int, chave: str = "",
                               model_id: str = "") -> Optional[float]:
    """
    Quanto esperar antes da próxima tentativa depois do erro `texto`; None
    quando não adianta tentar de novo (cota diária).

    Antes era 2, 4, 8, 16 segundos para qualquer erro. O limite por minuto
    não passa em 2 segundos, e cada tentativa cedo demais gastava de novo o
    prompt inteiro dentro da mesma janela.
    """
    if e_limite_diario(texto):
        return None
    aprender_do_erro(chave, texto)
    base = float(2 ** (tentativa + 1))
    pedido = espera_do_erro(texto)
    if pedido is not None:
        return max(base, pedido + 1.0)
    if e_limite_por_minuto(texto) or "resource exhausted" in (texto or "").lower() \
            or "resource_exhausted" in (texto or "").lower():
        teto = limite(chave, model_id)
        return max(base, espera_necessaria(chave, 0, teto) if teto else 0.0, 20.0)
    return base


# ---------------------------------------------------------------------------
# O histórico que vai ao modelo
# ---------------------------------------------------------------------------

def _e_fala(c: types.Content) -> bool:
    """Um conteúdo do jogador (ou do servidor), não a volta de uma ferramenta."""
    partes = c.parts or []
    return (c.role == "user" and any(p.text for p in partes)
            and not any(p.function_response for p in partes))


def _so_texto(c: types.Content) -> list[types.Part]:
    saida = []
    for p in c.parts or []:
        if p.function_call or p.function_response or getattr(p, "thought", False) or not p.text:
            continue
        texto = p.text
        if len(texto) > TEXTO_ANTIGO_MAX:
            texto = texto[:TEXTO_ANTIGO_MAX] + " [...]"
        saida.append(types.Part(text=texto))
    return saida


def enxugar_historico(contents: list, turnos: int = TURNOS_GUARDADOS) -> list:
    """
    O turno em andamento vai inteiro (as ferramentas dele são o que o Mestre
    está fazendo agora). Dos `turnos` anteriores, só o texto: a fala e a
    narração. Antes deles, nada: o resumo, o diário e a cena vão nas
    instruções.
    """
    contents = list(contents or [])
    falas = [i for i, c in enumerate(contents) if _e_fala(c)]
    if not falas:
        return contents
    atual = falas[-1]
    inicio = falas[-1 - turnos] if len(falas) > turnos else 0
    enxuto: list[types.Content] = []
    for c in contents[inicio:atual]:
        partes = _so_texto(c)
        if not partes:
            continue
        if enxuto and enxuto[-1].role == c.role:
            enxuto[-1] = types.Content(role=c.role, parts=list(enxuto[-1].parts) + partes)
        else:
            enxuto.append(types.Content(role=c.role, parts=partes))
    resto = contents[atual:]
    # Uma fala antiga sem resposta (o turno que caiu) junta com a de agora:
    # duas falas seguidas do mesmo lado confundem o modelo.
    if enxuto and resto and enxuto[-1].role == resto[0].role:
        resto = [types.Content(role=resto[0].role,
                               parts=list(enxuto.pop().parts) + list(resto[0].parts or []))] + resto[1:]
    return enxuto + resto


# ---------------------------------------------------------------------------
# Estimativa do tamanho de uma chamada
# ---------------------------------------------------------------------------

def _texto_do_conteudo(c) -> int:
    n = 0
    for p in getattr(c, "parts", None) or []:
        if p.text:
            n += len(p.text)
        if p.function_call:
            n += len(json.dumps(dict(p.function_call.args or {}), ensure_ascii=False, default=str)) + 40
        if p.function_response:
            n += len(json.dumps(dict(p.function_response.response or {}), ensure_ascii=False, default=str)) + 40
    return n


def estimar_tokens(llm_request) -> int:
    """Tokens de entrada da chamada, por cima: instruções, ferramentas e conversa."""
    n = 0
    cfg = getattr(llm_request, "config", None)
    instrucao = getattr(cfg, "system_instruction", None) if cfg else None
    if isinstance(instrucao, str):
        n += len(instrucao)
    elif instrucao is not None:
        n += _texto_do_conteudo(instrucao)
    for ferramenta in (getattr(cfg, "tools", None) or []) if cfg else []:
        try:
            n += len(json.dumps(ferramenta.model_dump(exclude_none=True), ensure_ascii=False))
        except Exception:
            n += 200
    for c in getattr(llm_request, "contents", None) or []:
        n += _texto_do_conteudo(c)
    return int(n / CARACTERES_POR_TOKEN)


# ---------------------------------------------------------------------------
# O vínculo por turno e os ganchos do Agent
# ---------------------------------------------------------------------------

_vinculo: contextvars.ContextVar = contextvars.ContextVar("rpg_ritmo", default=None)


def vincular(chave: str, model_id: str = "",
             avisar: Optional[Callable[[str], None]] = None) -> None:
    """Liga as chamadas deste turno a uma chave de API (e ao aviso da tela)."""
    _vinculo.set({"chave": chave, "model_id": model_id, "avisar": avisar})


def _atual() -> dict:
    return _vinculo.get() or {}


async def antes_do_modelo(callback_context, llm_request):
    """before_model_callback: enxuga o histórico e espera o minuto, se preciso."""
    llm_request.contents = enxugar_historico(llm_request.contents)
    v = _atual()
    chave = v.get("chave")
    teto = limite(chave, v.get("model_id", "")) if chave else None
    if teto:
        estimativa = estimar_tokens(llm_request)
        espera = espera_necessaria(chave, estimativa, teto)
        if espera > 0:
            avisar = v.get("avisar")
            if avisar:
                try:
                    avisar(f"Aguardando o limite de tokens por minuto do modelo "
                           f"({espera:.0f}s)...")
                except Exception:
                    pass
            await asyncio.sleep(espera)
        # A chamada conta já agora, pela estimativa; depois_do_modelo troca
        # pelo número que o provedor informar.
        registrar(chave, estimativa)
        v["_estimativa"] = estimativa
    return None


async def depois_do_modelo(callback_context, llm_response):
    """after_model_callback: corrige a janela com os tokens que o provedor contou."""
    v = _atual()
    chave = v.get("chave")
    um = getattr(llm_response, "usage_metadata", None)
    reais = int(getattr(um, "prompt_token_count", 0) or 0) if um else 0
    estimada = v.pop("_estimativa", None) if chave else None
    if chave and reais and estimada is not None:
        janela = _janelas.get(chave)
        if janela:
            # Troca a última estimativa desta chave pelo número real.
            for i in range(len(janela) - 1, -1, -1):
                instante, tokens = janela[i]
                if tokens == estimada:
                    janela[i] = (instante, reais)
                    break
    return None
