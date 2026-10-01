"""
compendio.py
O SRD 5.1 do D&D em tabela local: as 319 magias e as 12 classes com as suas
subclasses e características.

POR QUE EXISTE
──────────────
O motor buscava cada magia no Open5e em tempo de jogo e interpretava a prosa
em inglês com expressões regulares, em seis lugares diferentes. Quando dois
palpites discordavam, a tela dizia uma coisa e o motor fazia outra.

Os dados ficam em rpg/dados/srd_magias.json e srd_classes.json, gerados por
scripts/gerar_compendio.py a partir do Open5e v2 e REVISADOS à mão — o
gerador guarda o porquê de cada correção. Aqui só se carrega e se procura.

ONDE ESTÁ GUARDADO E POR QUÊ
────────────────────────────
No repositório, e não no Supabase. É dado de referência, igual para todos os
jogadores e congelado (o SRD 5.1 não muda): versionado junto com o código,
funciona sem rede e não ocupa a cota do banco.

LICENÇA
───────
Material do System Reference Document 5.1 da Wizards of the Coast, sob a
Creative Commons Atribuição 4.0 Internacional. A atribuição completa vai no
campo `_licenca` de cada JSON. Só o SRD é aberto: o resto do D&D é conteúdo
protegido e não entra aqui.
"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

DADOS = Path(__file__).resolve().parent / "dados"

# Os nomes que as FICHAS do jogo usam e que não batem com o nome oficial.
# Vieram de DEFAULT_SPELLS_BY_CLASS e das fichas reais; sem eles a ficha antiga
# não casa com o compêndio e cai na leitura de texto, que é o que causava erro.
APELIDOS_DE_MAGIA = {
    "guia divino": "Guiding Bolt",
    "insulto cruel": "Vicious Mockery",
    "golpe mistico": "Eldritch Blast",
    "cura ferimentos": "Cure Wounds",
    "chamas sagradas": "Sacred Flame",
}

# "Truque Bônus (Chamas Sagradas)" é a MESMA Chama Sagrada, ganha por uma
# característica de subclasse. A ficha da Selene tinha as duas, e a tela
# mostrava duas vezes.
_EMBRULHO = re.compile(
    r"^\s*(?:truque\s+b[oô]nus|magia\s+b[oô]nus|bonus\s+cantrip|truque\s+adicional)"
    r"\s*\((?P<dentro>.+)\)\s*$", re.IGNORECASE)


def norm(texto: str) -> str:
    """Minúsculo, sem acento, sem pontuação, espaço simples."""
    t = unicodedata.normalize("NFD", (texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-z0-9/]+", " ", t)
    return " ".join(t.split())


def _sem_plural(n: str) -> str:
    """'chamas sagradas' e 'chama sagrada' são o mesmo nome escrito de dois jeitos."""
    return " ".join(p[:-1] if len(p) > 3 and p.endswith("s") else p for p in n.split())


def desembrulhar(nome: str) -> str:
    """'Truque Bônus (Chamas Sagradas)' → 'Chamas Sagradas'."""
    m = _EMBRULHO.match(nome or "")
    return m.group("dentro").strip() if m else (nome or "")


# ---------------------------------------------------------------------------
# Carga
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _arquivo(nome: str) -> dict:
    caminho = DADOS / nome
    if not caminho.exists():
        return {}
    return json.loads(caminho.read_text(encoding="utf-8"))


def magias() -> dict[str, dict]:
    return _arquivo("srd_magias.json").get("magias", {})


def classes() -> dict[str, dict]:
    return _arquivo("srd_classes.json").get("classes", {})


@lru_cache(maxsize=1)
def _indice_magias() -> dict[str, dict]:
    idx: dict[str, dict] = {}

    def pôr(chave: str, m: dict) -> None:
        n = norm(chave)
        if n:
            idx.setdefault(n, m)
            idx.setdefault(_sem_plural(n), m)

    por_en = {}
    for m in magias().values():
        por_en[norm(m["nome_srd"])] = m
        for chave in (m["chave"], m["nome"], m["nome_srd"]):
            pôr(chave, m)

    # Os mapas antigos de português → inglês continuam valendo como apelido:
    # quem digitar "guia espiritual" (o nome errado que o jogo usava para Raio
    # Guia) ainda encontra a magia. Lidos com atraso para não criar ciclo de
    # importação com tools_dnd.
    try:
        from rpg import tools_dnd as _td
        for pt, en in list(_td._SPELL_PT_TO_EN.items()) + list(_td.SPELL_PT_TO_EN.items()):
            m = por_en.get(norm(en))
            if m:
                pôr(pt, m)
    except Exception:                                            # pragma: no cover
        pass
    for apelido, en in APELIDOS_DE_MAGIA.items():
        m = por_en.get(norm(en))
        if m:
            pôr(apelido, m)
    return idx


@lru_cache(maxsize=1)
def _indice_caracteristicas() -> dict[str, list[dict]]:
    idx: dict[str, list[dict]] = {}

    def pôr(chave: str, f: dict) -> None:
        n = norm(chave)
        if n and f not in idx.setdefault(n, []):
            idx[n].append(f)

    for c in classes().values():
        todas = list(c["caracteristicas"])
        for s in c["subclasses"].values():
            todas += s["caracteristicas"]
        for f in todas:
            for chave in (f["nome"], f["nome_srd"], *f.get("apelidos", [])):
                pôr(chave, f)
    return idx


# ---------------------------------------------------------------------------
# Procura
# ---------------------------------------------------------------------------

def magia(nome: str) -> dict | None:
    """A magia do SRD com este nome (português, inglês, chave ou apelido)."""
    if not nome:
        return None
    idx = _indice_magias()
    for tentativa in (nome, desembrulhar(nome)):
        n = norm(tentativa)
        achada = idx.get(n) or idx.get(_sem_plural(n))
        if achada:
            return achada
    return None


def caracteristica(nome: str, classe: str = "", exato: bool = False) -> dict | None:
    """
    A característica de classe do SRD com este nome. Com `classe`, prefere a
    daquela classe — Canalizar Divindade existe no clérigo E no paladino, com
    usos diferentes.

    Com `exato`, NÃO cai na característica-mãe. "Canalizar Divindade
    (Radiância do Amanhecer)" não é do SRD; devolver "Canalizar Divindade" no
    lugar troca o efeito específico (dano radiante em criaturas hostis) por
    um resumo genérico — que é a falta de informação que levou a fogo amigo.
    """
    if not nome:
        return None
    idx = _indice_caracteristicas()
    candidatas = idx.get(norm(nome))
    if not candidatas:
        # "Canalizar Divindade (Preservar Vida)" → "Canalizar Divindade: Preservar Vida",
        # e na falta dela (só fora do modo exato), a característica-mãe.
        m = re.match(r"^(.+?)\s*\((.+)\)\s*$", nome)
        if m:
            candidatas = idx.get(norm(f"{m.group(1)}: {m.group(2)}"))
            if not candidatas and not exato:
                candidatas = idx.get(norm(m.group(1)))
    if not candidatas:
        return None
    if classe:
        alvo = norm(classe)
        da_classe = [f for f in candidatas if norm(f["classe"]) == alvo]
        if da_classe:
            return da_classe[0]
    return candidatas[0]


def classe(chave: str) -> dict | None:
    alvo = norm(chave)
    return next((c for c in classes().values()
                 if norm(c["chave"]) == alvo or norm(c["nome_srd"]) == alvo), None)


def magias_da_classe(chave_classe: str, nivel_max: int = 9) -> list[dict]:
    """As magias do SRD que a classe pode aprender, até um nível de magia."""
    alvo = norm(chave_classe)
    return sorted((m for m in magias().values()
                   if any(norm(c) == alvo for c in m["classes"])
                   and m["nivel"] <= nivel_max),
                  key=lambda m: (m["nivel"], m["nome"]))


def progressao_no_nivel(progressao: dict, nivel: int) -> str:
    """O valor de uma progressão ('1': '1d6', '3': '2d6'...) no nível dado."""
    if not progressao:
        return ""
    validos = [int(k) for k in progressao if str(k).isdigit() and int(k) <= nivel]
    return progressao[str(max(validos))] if validos else ""
