"""
open5e.py
Camada única de acesso ao SRD de D&D 5e (api.open5e.com).

POR QUE EXISTE
──────────────
Antes, cada consulta ao SRD era um `requests.get` solto, espalhado por mais
de dez pontos do motor: sem sessão (handshake TLS novo a cada chamada), sem
retry, sem cache e com `except: pass` engolindo a falha. Um único turno de
combate podia disparar dezenas de round-trips SERIAIS dentro do tempo de
resposta do chat — e, quando a API demorava ou caía, o motor degradava em
silêncio para valores genéricos (1d6 de dano, CA 12) sem ninguém perceber.

O QUE ESTA CAMADA DÁ
────────────────────
• Sessão HTTP reaproveitada, com pool de conexões e retry/backoff em erros
  transitórios (429/5xx).
• Cache em memória + em disco. O SRD é estático: uma vez buscado, um goblin
  é o mesmo goblin para sempre. A segunda partida não toca a rede.
• Cache NEGATIVO curto: "bite" não é uma arma do SRD e nunca será; sem isso,
  todo ataque de monstro repetiria o mesmo 404 de 4 segundos.
• Modo offline explícito (`set_offline`, env `RPG_SRD_OFFLINE=1`) para testes
  e para rodar sem rede.
• Contadores (`stats()`) para que a degradação deixe de ser invisível.

COMO USAR
─────────
Substituto direto de `requests` nos pontos de consulta ao SRD — a resposta
devolvida expõe `.ok` e `.json()`, então os call sites existentes não mudam:

    from app.open5e import http as _req
    r = _req.get("https://api.open5e.com/v1/monsters/goblin/", timeout=5)
    if r.ok:
        data = r.json()
"""

from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from urllib.parse import urlencode

import requests
from requests.adapters import HTTPAdapter

try:                                     # urllib3 2.x e 1.x
    from urllib3.util.retry import Retry
except Exception:                        # pragma: no cover - ambiente exótico
    Retry = None


# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

BASE_URL = "https://api.open5e.com"

# O SRD não muda. TTL longo para acertos; curto para falhas, de modo que uma
# indisponibilidade temporária da API não fique "grudada" no cache por um mês.
TTL_HIT_S  = int(os.environ.get("RPG_SRD_TTL",     30 * 24 * 3600))   # 30 dias
TTL_MISS_S = int(os.environ.get("RPG_SRD_TTL_MISS",          3600))   # 1 hora

_CACHE_PATH = os.environ.get(
    "RPG_SRD_CACHE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache", "open5e.json"),
)
_CACHE_DISABLED = os.environ.get("RPG_SRD_CACHE_DISABLED", "0").strip().lower() in (
    "1", "true", "yes", "on",
)
_OFFLINE = os.environ.get("RPG_SRD_OFFLINE", "0").strip().lower() in (
    "1", "true", "yes", "on",
)

# Grava em disco no máximo a cada N segundos (evita I/O a cada consulta).
_FLUSH_EVERY_S = 5.0

_lock = threading.RLock()
_mem: dict[str, tuple[float, bool, dict | None]] = {}   # key -> (expira_em, ok, data)
_loaded = False
_dirty = False
_last_flush = 0.0

_stats = {
    "hits":     0,   # servidos do cache (memória ou disco)
    "misses":   0,   # foram à rede
    "errors":   0,   # rede falhou (timeout, DNS, 5xx após retry)
    "not_found": 0,  # rede respondeu, mas sem o recurso (404 / lista vazia)
    "offline":  0,   # recusados por modo offline
}
_last_error: str = ""


# ---------------------------------------------------------------------------
# Sessão HTTP
# ---------------------------------------------------------------------------

def _build_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Accept": "application/json", "User-Agent": "rpg-agent/1.0"})
    if Retry is not None:
        retry = Retry(
            total=2,
            connect=2,
            read=1,
            backoff_factor=0.3,           # 0.3s, 0.6s
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
    return s


_session = _build_session()


# ---------------------------------------------------------------------------
# Cache em disco
# ---------------------------------------------------------------------------

def _load_disk() -> None:
    """Carrega o cache de disco uma única vez, por preguiça. Nunca levanta."""
    global _loaded
    if _loaded or _CACHE_DISABLED:
        _loaded = True
        return
    _loaded = True
    try:
        with open(_CACHE_PATH, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception:
        return
    if not isinstance(raw, dict):
        return
    agora = time.time()
    for key, entry in raw.items():
        try:
            exp, ok, data = entry["exp"], entry["ok"], entry["data"]
        except Exception:
            continue
        if exp > agora:
            _mem[key] = (float(exp), bool(ok), data)


def _flush_disk(force: bool = False) -> None:
    """Persiste o cache. Escrita atômica; falha em silêncio (cache é best-effort)."""
    global _dirty, _last_flush
    if _CACHE_DISABLED or not _dirty:
        return
    agora = time.time()
    if not force and (agora - _last_flush) < _FLUSH_EVERY_S:
        return
    _last_flush = agora
    payload = {
        key: {"exp": exp, "ok": ok, "data": data}
        for key, (exp, ok, data) in _mem.items()
        if exp > agora
    }
    try:
        os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
        tmp = f"{_CACHE_PATH}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        os.replace(tmp, _CACHE_PATH)
        _dirty = False
    except Exception:
        pass


def _cache_key(url: str, params: dict | None) -> str:
    if not params:
        return url
    itens = sorted((str(k), str(v)) for k, v in params.items() if v is not None)
    return f"{url}?{urlencode(itens)}"


# ---------------------------------------------------------------------------
# Resposta (compatível com o que os call sites já esperam de `requests`)
# ---------------------------------------------------------------------------

class Response:
    """Mínimo que o motor usa de uma resposta: `.ok` e `.json()`."""

    __slots__ = ("ok", "status_code", "from_cache", "_data")

    def __init__(self, ok: bool, data: dict | None,
                 status_code: int = 0, from_cache: bool = False):
        self.ok          = bool(ok)
        self.status_code = status_code
        self.from_cache  = from_cache
        self._data       = data if isinstance(data, dict) else {}

    def json(self) -> dict:
        return self._data

    def __repr__(self) -> str:                                # pragma: no cover
        origem = "cache" if self.from_cache else "rede"
        return f"<open5e.Response ok={self.ok} status={self.status_code} {origem}>"


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def get(url: str, params: dict | None = None, timeout: float = 5.0) -> Response:
    """
    GET com cache no SRD. NUNCA levanta exceção: em qualquer falha devolve
    uma Response com `ok=False`, para que o motor siga pelo caminho de
    fallback que ele já tem.
    """
    global _dirty, _last_error

    with _lock:
        _load_disk()
        key   = _cache_key(url, params)
        agora = time.time()
        hit   = _mem.get(key)
        if hit and hit[0] > agora:
            _stats["hits"] += 1
            return Response(ok=hit[1], data=hit[2],
                            status_code=200 if hit[1] else 404, from_cache=True)

    if _OFFLINE:
        with _lock:
            _stats["offline"] += 1
        return Response(ok=False, data=None, status_code=0)

    ok, data, status = False, None, 0
    try:
        r = _session.get(url, params=params or None, timeout=timeout)
        status = r.status_code
        if r.ok:
            try:
                parsed = r.json()
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                ok, data = True, parsed
        with _lock:
            _stats["misses"] += 1
            if not ok:
                _stats["not_found"] += 1
    except Exception as exc:
        with _lock:
            _stats["errors"] += 1
            _last_error = f"{type(exc).__name__}: {exc}"
        # Erro de REDE não vira cache: a próxima chamada deve tentar de novo.
        return Response(ok=False, data=None, status_code=0)

    with _lock:
        ttl = TTL_HIT_S if ok else TTL_MISS_S
        _mem[_cache_key(url, params)] = (time.time() + ttl, ok, data)
        _dirty = True
        _flush_disk()

    return Response(ok=ok, data=data, status_code=status)


class _HttpShim:
    """
    Fachada com a mesma cara de `requests` para os call sites do motor:
        from app.open5e import http as _req
        r = _req.get(url, params={...}, timeout=4)
    """

    @staticmethod
    def get(url: str, params: dict | None = None, timeout: float = 5.0) -> Response:
        return get(url, params=params, timeout=timeout)


http = _HttpShim()


def stats() -> dict:
    """Contadores acumulados. `hit_rate` em [0,1]; None quando não houve consulta."""
    with _lock:
        s = dict(_stats)
    total = s["hits"] + s["misses"] + s["offline"]
    s["total"]        = total
    s["hit_rate"]     = (s["hits"] / total) if total else None
    s["cached_keys"]  = len(_mem)
    s["last_error"]   = _last_error
    s["offline_mode"] = _OFFLINE
    return s


def reset_stats() -> None:
    with _lock:
        for k in _stats:
            _stats[k] = 0


def set_offline(value: bool) -> None:
    """Liga/desliga o modo offline (usado em testes e para rodar sem rede)."""
    global _OFFLINE
    _OFFLINE = bool(value)


@contextmanager
def offline():
    """Contexto que força modo offline — o jeito de simular 'API fora' nos testes."""
    anterior = _OFFLINE
    set_offline(True)
    try:
        yield
    finally:
        set_offline(anterior)


def clear_cache(disk: bool = False) -> None:
    """Esvazia o cache em memória (e opcionalmente o arquivo em disco)."""
    global _dirty
    with _lock:
        _mem.clear()
        _dirty = True
        if disk:
            try:
                os.remove(_CACHE_PATH)
                _dirty = False
            except OSError:
                pass


def flush() -> None:
    """Força a gravação do cache em disco (ex.: no encerramento do processo)."""
    with _lock:
        _flush_disk(force=True)
