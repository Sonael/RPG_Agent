"""
itens.py
Os itens do SRD 5.1 em tabela local: as armas, armaduras, equipamento de
aventura, ferramentas, mercadorias e venenos, e os itens mágicos.

POR QUE EXISTE
──────────────
O motor sabia de itens por umas quinze tabelas feitas à mão, cada uma com um
pedaço, e completava o resto perguntando ao Open5e em tempo de jogo, com nome
em português. Sem rede toda arma causava 1d6; com rede, "Espada Longa +1"
causava 1d6+1 (o "+1" quebrava a busca) e a Mochila esperava duas consultas
de 4 s por item desconhecido.

Os dados ficam em rpg/dados/srd_itens.json, gerado por scripts/gerar_itens.py
a partir do Open5e v2 e de scripts/srd_itens_pt.json (nomes em português,
apelidos e correções, revisados à mão). Aqui só se carrega e se procura, sem
rede.

COMO UM NOME VIRA ITEM
──────────────────────
  • O bônus mágico sai do nome antes de tudo: "Espada Longa +1" é a espada
    longa com +1 ("+1" no fim, no meio ou entre parênteses).
  • Nome exato (português, inglês, apelido, sem acento, plural ou singular,
    com ou sem o parêntese final: "Ração", "Rações", "Ração (1 dia)").
  • Para arma e armadura, o nome de um item mágico que é feito delas: a
    "Defensora" é uma espada longa +3, o "Arco do Juramento" um arco longo.
  • Por fim, o nome de uma arma ou armadura DENTRO do nome, a mais longa
    primeiro: "Espada Curta de Prata" é espada curta; "Cota de Malha de
    Mithral", cota de malha. Item conhecido que não é arma (o Bastão Imóvel,
    a Bolsa de Contenção) não vira arma por ter "bastão" ou "bolsa" no nome.

LICENÇA
───────
Material do System Reference Document 5.1 da Wizards of the Coast, sob a
Creative Commons Atribuição 4.0 Internacional. A atribuição completa vai no
campo `_licenca` do JSON.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache

from rpg.compendio import DADOS, norm

# Os doze espaços de equipamento da ficha, na ordem de toda a interface. Os
# cinco primeiros são os de sempre; os outros recebem os itens mágicos de
# vestir (anel, manto, botas...), para que dois mantos não deem +2 de CA. A
# mesma lista está em static/js/utils.js (SLOTS_DE_EQUIPAMENTO); o teste
# test_espacos_de_equipamento confere que as duas não se separam.
SLOTS = ("armadura", "escudo", "arma_principal", "arma_secundaria", "amuleto",
         "anel_1", "anel_2", "capa", "botas", "luvas", "cabeca", "cinto")


def equipamentos_vazios(**ocupados) -> dict:
    """O dicionário de equipamentos de uma ficha nova, com os doze espaços."""
    return {**{s: None for s in SLOTS}, **ocupados}

# "+1" no fim, no meio ("Espada +1 de Prata") ou entre parênteses ("(+2)").
_BONUS = re.compile(r"\(?\s*\+\s*([123])\s*\)?(?=\s|$|\))")
# "Flechas (20)", "Flechas x20", "20x Flechas", "Flechas ×20".
_QUANTIDADE = (re.compile(r"\s*\(\s*[x×]?\s*\d+\s*\)\s*$"),
               re.compile(r"\s*[x×]\s*\d+\s*$"),
               re.compile(r"^\s*\d+\s*[x×]?\s+"))
_PARENTESE_FINAL = re.compile(r"\s*\([^)]*\)\s*$")


# ---------------------------------------------------------------------------
# Carga
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _arquivo() -> dict:
    caminho = DADOS / "srd_itens.json"
    if not caminho.exists():
        return {}
    return json.loads(caminho.read_text(encoding="utf-8"))


def comuns() -> dict[str, dict]:
    return _arquivo().get("itens", {})


def magicos() -> dict[str, dict]:
    return _arquivo().get("magicos", {})


def _singular_palavra(p: str) -> str:
    if len(p) <= 3:
        return p
    for fim, troca in (("oes", "ao"), ("aes", "ao"), ("ais", "al"), ("eis", "el"), ("ns", "m")):
        if p.endswith(fim):
            return p[: -len(fim)] + troca
    return p[:-1] if p.endswith("s") else p


def _singular(n: str) -> str:
    """'racoes de viagem' → 'racao de viagem'; 'flechas' → 'flecha'."""
    return " ".join(_singular_palavra(p) for p in n.split())


def _formas(nome: str) -> set[str]:
    """As formas normalizadas de um nome: inteiro, sem o parêntese final, no singular."""
    formas = set()
    for t in (nome, _PARENTESE_FINAL.sub("", nome or "")):
        n = norm(t)
        if n:
            formas |= {n, _singular(n)}
    return formas


@lru_cache(maxsize=1)
def _indice() -> dict[str, tuple[str, str]]:
    """Nome normalizado → ("comum" | "magico", chave). O comum vence o empate."""
    idx: dict[str, tuple[str, str]] = {}
    for fonte, tabela in (("comum", comuns()), ("magico", magicos())):
        for chave, e in tabela.items():
            for nome in (e["nome"], e["nome_srd"], chave.replace("-", " "),
                         *e.get("aliases", []), *e.get("nomes_en", [])):
                for f in _formas(nome):
                    idx.setdefault(f, (fonte, chave))
    return idx


@lru_cache(maxsize=1)
def _contidos() -> dict[str, list[tuple[str, str, str]]]:
    """
    Para achar a arma ou a armadura DENTRO de um nome: (forma, fonte, chave),
    da forma mais longa para a mais curta, separado por grupo.
    """
    grupos: dict[str, list[tuple[str, str, str]]] = {"arma": [], "armadura": []}
    for chave, e in comuns().items():
        grupo = {"arma": "arma", "armadura": "armadura", "escudo": "armadura"}.get(e["categoria"])
        if not grupo:
            continue
        for nome in (e["nome"], e["nome_srd"], *e.get("aliases", []), *e.get("nomes_en", [])):
            for f in _formas(nome):
                grupos[grupo].append((f, "comum", chave))
    for chave, e in magicos().items():
        for campo, grupo in (("base_arma", "arma"), ("base_armadura", "armadura")):
            if e.get(campo):
                for nome in (e["nome"], e["nome_srd"], *e.get("aliases", [])):
                    for f in _formas(nome):
                        grupos[grupo].append((f, "magico", chave))
    for lista in grupos.values():
        lista.sort(key=lambda t: -len(t[0]))
    return grupos


@lru_cache(maxsize=1)
def _prefixos_magicos() -> list[tuple[str, str]]:
    """(forma, chave) dos itens mágicos, da forma mais longa para a mais curta."""
    saida = []
    for chave, e in magicos().items():
        if e.get("sintetico"):
            continue
        for nome in (e["nome"], e["nome_srd"], *e.get("aliases", [])):
            for f in _formas(nome):
                if len(f.split()) >= 2:          # "Defensora" sozinho não é prefixo
                    saida.append((f, chave))
    saida.sort(key=lambda t: -len(t[0]))
    return saida


# ---------------------------------------------------------------------------
# Nome
# ---------------------------------------------------------------------------

def separar_bonus(nome: str) -> tuple[str, int]:
    """'Espada Longa +1' → ('Espada Longa', 1). Sem bônus, (nome, 0)."""
    achado = _BONUS.search(nome or "")
    if not achado:
        return (nome or "").strip(), 0
    limpo = (nome[:achado.start()] + " " + nome[achado.end():]).strip()
    return re.sub(r"\s+", " ", limpo), int(achado.group(1))


def _sem_quantidade(nome: str) -> str:
    for rx in _QUANTIDADE:
        nome = rx.sub("", nome)
    return nome.strip()


def _exato(nome: str) -> tuple[str, dict] | None:
    """(fonte, entrada) do nome exato, sem tirar bônus."""
    idx = _indice()
    for tentativa in (nome, _sem_quantidade(nome)):
        n = norm(tentativa)
        if not n:
            continue
        achado = idx.get(n) or idx.get(_singular(n))
        if achado:
            fonte, chave = achado
            return fonte, (comuns() if fonte == "comum" else magicos())[chave]
    return None


def _contido(nome: str, grupo: str) -> tuple[str, dict] | None:
    alvo = f" {_singular(norm(nome))} "
    for forma, fonte, chave in _contidos()[grupo]:
        if f" {_singular(forma)} " in alvo:
            return fonte, (comuns() if fonte == "comum" else magicos())[chave]
    return None


# ---------------------------------------------------------------------------
# Procura
# ---------------------------------------------------------------------------

def comum(nome: str) -> dict | None:
    """O item comum do SRD com este nome. Item com +N não é comum: é mágico."""
    base, bonus = separar_bonus(nome)
    if bonus:
        return None
    achado = _exato(base)
    return achado[1] if achado and achado[0] == "comum" else None


def magico(nome: str) -> dict | None:
    """
    O item mágico do SRD com este nome, com o bônus do nome em `bonus` e a
    raridade que ele dá. "Espada Longa +2" é a entrada "Arma +N" (rara) com
    base na espada longa; "Defensora" é a Defensora.
    """
    base, bonus = separar_bonus(nome)
    achado = _exato(base)
    if achado and achado[0] == "magico":
        e = dict(achado[1])
        if bonus:
            e["bonus"] = max(bonus, int(e.get("bonus", 0) or 0))
        return e
    if not achado:
        # "Peitoral de Adamante", "Espada Curta Língua de Fogo": o item
        # mágico feito daquela armadura ou arma.
        for procura in (armadura, arma):
            dados = procura(base)
            if dados and dados.get("item_magico"):
                e = dict(magicos()[dados["item_magico"]])
                if bonus:
                    e["bonus"] = max(bonus, int(e.get("bonus", 0) or 0))
                return e
        # "Anel de Resistência ao Fogo", "Pedra Ioun da Proteção": o nome do
        # item seguido do que escolhe a variante.
        alvo = f"{_singular(norm(base))} "
        for forma, chave in _prefixos_magicos():
            if alvo.startswith(forma + " "):
                e = dict(magicos()[chave])
                if bonus:
                    e["bonus"] = max(bonus, int(e.get("bonus", 0) or 0))
                return e
    if not bonus:
        return None
    if achado and achado[1].get("categoria") == "municao":
        chave, campo = "ammunition-plus", ""
    else:
        a = arma(base)
        if a:
            chave, campo, alvo = "weapon-plus", "base_arma", a["chave"]
        else:
            r = armadura(base)
            if not r:
                return None
            chave = "shield-plus" if r["tipo"] == "escudo" else "armor-plus"
            campo, alvo = "base_armadura", r["chave"]
    e = dict(magicos()[chave])
    e["bonus"] = bonus
    e["raridade"] = e["raridade_por_bonus"][str(bonus)]
    if campo:
        e[campo] = alvo
    return e


def _arma_de(entrada: dict, bonus: int, magica: dict | None) -> dict:
    dados = dict(entrada["arma"])
    dados.update({"chave": entrada["chave"], "nome": entrada["nome"],
                  "nome_srd": entrada["nome_srd"], "preco_pc": entrada["preco_pc"],
                  "peso_kg": entrada["peso_kg"], "bonus": bonus,
                  "magica": bool(magica or bonus),
                  "item_magico": (magica or {}).get("chave", "")})
    return dados


def arma(nome: str) -> dict | None:
    """
    A arma do SRD por trás deste nome, com o bônus mágico:
    {chave, nome, nome_srd, dado, tipo_dano, grupo, distancia, propriedades,
     versatil?, alcance_m?, municao?, preco_pc, peso_kg, bonus, magica}.
    None quando o nome não é de arma do SRD.
    """
    if not nome:
        return None
    base, bonus = separar_bonus(nome)
    achado = _exato(base)
    if achado:
        fonte, e = achado
        if fonte == "comum":
            return _arma_de(e, bonus, None) if e["categoria"] == "arma" else None
        if e.get("base_arma"):
            return _arma_de(comuns()[e["base_arma"]], max(bonus, int(e.get("bonus", 0) or 0)), e)
        if not (e.get("qualquer_arma") or e.get("sintetico")):
            return None                    # item mágico que não é arma
    achado = _contido(base, "arma")
    if not achado:
        return None
    fonte, e = achado
    if fonte == "comum":
        return _arma_de(e, bonus, None)
    return _arma_de(comuns()[e["base_arma"]], max(bonus, int(e.get("bonus", 0) or 0)), e)


def _armadura_de(entrada: dict, bonus: int, magica: dict | None) -> dict:
    dados = dict(entrada["armadura"])
    dados.update({"chave": entrada["chave"], "nome": entrada["nome"],
                  "nome_srd": entrada["nome_srd"], "preco_pc": entrada["preco_pc"],
                  "peso_kg": entrada["peso_kg"], "bonus": bonus,
                  "magica": bool(magica or bonus),
                  "item_magico": (magica or {}).get("chave", "")})
    return dados


def armadura(nome: str) -> dict | None:
    """
    A armadura ou o escudo do SRD por trás deste nome, com o bônus mágico:
    {chave, nome, nome_srd, tipo, ca_base, dex, forca_min,
     furtividade_desvantagem, preco_pc, peso_kg, bonus, magica}.
    """
    if not nome:
        return None
    base, bonus = separar_bonus(nome)
    achado = _exato(base)
    if achado:
        fonte, e = achado
        if fonte == "comum":
            return _armadura_de(e, bonus, None) if e["categoria"] in ("armadura", "escudo") else None
        if e.get("base_armadura"):
            return _armadura_de(comuns()[e["base_armadura"]],
                                max(bonus, int(e.get("bonus", 0) or 0)), e)
        if not (e.get("qualquer_armadura") or e.get("sintetico")):
            return None
    achado = _contido(base, "armadura")
    if not achado:
        return None
    fonte, e = achado
    if fonte == "comum":
        return _armadura_de(e, bonus, _material(base))
    return _armadura_de(comuns()[e["base_armadura"]], max(bonus, int(e.get("bonus", 0) or 0)), e)


def _material(nome: str) -> dict | None:
    """
    "Cota de Malha de Mithral": o item mágico que vale para qualquer armadura
    (Mithral, Adamante, Resistência), pela palavra que o distingue.
    """
    alvo = f" {norm(nome)} "
    for m in magicos().values():
        if not m.get("qualquer_armadura"):
            continue
        for nome_m in (m["nome"], *m.get("aliases", [])):
            palavra = norm(nome_m).split(" de ")[-1]      # "armadura de mithral" → "mithral"
            if palavra and f" {palavra} " in alvo:
                return m
    return None


def preco_pc(nome: str) -> int | None:
    """
    Preço de tabela em peças de cobre. Só o que o SRD (ou o Livro do Jogador,
    no caso da Poção de Cura) tabela: arma +1 não tem preço de espada comum.
    """
    base, bonus = separar_bonus(nome)
    if bonus:
        return None
    achado = _exato(base)
    if not achado:
        return None
    preco = int(achado[1].get("preco_pc") or 0)
    return preco if preco > 0 else None


def peso_kg(nome: str) -> float | None:
    """Peso de uma unidade em kg: o do item, ou o da arma ou armadura de que ele é feito."""
    base, _bonus = separar_bonus(nome)
    achado = _exato(base)
    if achado and float(achado[1].get("peso_kg") or 0) > 0:
        return float(achado[1]["peso_kg"])
    for procura in (arma, armadura):
        dados = procura(nome)
        if dados and float(dados.get("peso_kg") or 0) > 0:
            return float(dados["peso_kg"])
    if achado and achado[0] == "comum":
        return float(achado[1].get("peso_kg") or 0)   # o SRD diz "—": não pesa
    return None


def nome_em_ingles(nome: str) -> str:
    """O nome do SRD (em inglês, minúsculo) de uma arma, armadura ou item; '' se não há."""
    for procura in (arma, armadura):
        dados = procura(nome)
        if dados:
            return dados["nome_srd"].lower()
    achado = _exato(separar_bonus(nome)[0])
    return achado[1]["nome_srd"].lower() if achado else ""


def texto_srd(entrada: dict, nome: str = "") -> str:
    """O texto do SRD de um item mágico; o da variante quando o nome a escolhe."""
    alvo = norm(nome)
    for v in entrada.get("variantes") or []:
        dentro = re.search(r"\(([^)]*)\)", v["nome_srd"])
        if dentro and alvo and norm(dentro.group(1)) in alvo and v.get("texto_srd"):
            return v["texto_srd"]
    return entrada.get("texto_srd", "")


# ---------------------------------------------------------------------------
# Busca (o editor de ficha)
# ---------------------------------------------------------------------------

_TIPO_DE_DANO_PT = {
    "acid": "ácido", "bludgeoning": "concussão", "cold": "frio", "fire": "fogo",
    "force": "força", "lightning": "elétrico", "necrotic": "necrótico",
    "piercing": "perfurante", "poison": "veneno", "psychic": "psíquico",
    "radiant": "radiante", "slashing": "cortante", "thunder": "trovejante",
}
_PROPRIEDADE_PT = {
    "acuidade": "acuidade", "alcance": "alcance", "arremesso": "arremesso",
    "duas_maos": "duas mãos", "especial": "especial", "leve": "leve",
    "municao": "munição", "pesada": "pesada", "recarga": "recarga", "versatil": "versátil",
}
_TIPO_DE_ARMADURA_PT = {"leve": "leve", "media": "média", "pesada": "pesada", "escudo": "escudo"}


_TIPOS_FEMININOS = {"arma", "armadura", "poção", "varinha", "munição"}
_RARIDADE_FEMININA = {"raro": "rara", "muito raro": "muito rara", "lendário": "lendária"}


def raridade_concordada(e: dict) -> str:
    """A raridade concordando com o tipo: 'Arma — muito rara', 'Anel — raro'."""
    r = e.get("raridade", "")
    return _RARIDADE_FEMININA.get(r, r) if e.get("tipo") in _TIPOS_FEMININOS else r


def resumo_magico(e: dict) -> str:
    """'Anel — raro, requer sintonização.' A linha que a Mochila mostra, em português."""
    partes = [raridade_concordada(e)]
    if e.get("sintonizacao"):
        partes.append("requer sintonização")
    return f"{(e.get('tipo') or 'item').capitalize()} — {', '.join(p for p in partes if p)}."


def resumo(e: dict) -> str:
    """Uma linha em português sobre o item: dano e propriedades, CA, ou raridade."""
    if e.get("arma"):
        a = e["arma"]
        props = [_PROPRIEDADE_PT.get(p, p) for p in a["propriedades"]]
        if a.get("versatil"):
            props = [f"versátil ({a['versatil']})" if p == "versátil" else p for p in props]
        dano = f"{a['dado']} {_TIPO_DE_DANO_PT.get(a['tipo_dano'], '')}".strip() if a["dado"] else "sem dano"
        return f"Dano {dano}" + (f"; {', '.join(props)}" if props else "") + "."
    if e.get("armadura"):
        r = e["armadura"]
        if r["tipo"] == "escudo":
            return "+2 na CA."
        dex = {"full": " + DES", "cap2": " + DES (máx. 2)", "none": ""}[r["dex"]]
        extra = [f"FOR {r['forca_min']}" if r["forca_min"] else "",
                 "desvantagem em Furtividade" if r["furtividade_desvantagem"] else ""]
        extra = [x for x in extra if x]
        return (f"Armadura {_TIPO_DE_ARMADURA_PT[r['tipo']]}: CA {r['ca_base']}{dex}"
                + (f"; {', '.join(extra)}" if extra else "") + ".")
    if "raridade" in e:
        return resumo_magico(e)
    partes = []
    if e.get("preco_pc"):
        po, resto = divmod(int(e["preco_pc"]), 100)
        pp, pc = divmod(resto, 10)
        partes.append(" ".join(x for x in (f"{po} po" if po else "", f"{pp} pp" if pp else "",
                                            f"{pc} pc" if pc else "") if x))
    if e.get("peso_kg"):
        partes.append(f"{e['peso_kg']:g} kg".replace(".", ","))
    return " · ".join(partes)


def buscar(texto: str, tipo: str = "all", limite: int = 18) -> list[dict]:
    """
    Itens cujo nome (em português ou em inglês, ou um apelido) contém o texto.
    tipo: all | weapon | armor | magic. Os que COMEÇAM com o texto vêm primeiro.
    """
    alvo = norm(texto)
    if len(alvo) < 2:
        return []
    fontes = []
    if tipo in ("all", "weapon", "armor"):
        cats = {"weapon": {"arma"}, "armor": {"armadura", "escudo"}}.get(tipo)
        fontes += [e for e in comuns().values() if not cats or e["categoria"] in cats]
    if tipo in ("all", "magic"):
        fontes += [e for e in magicos().values() if not e.get("sintetico")]
    achados = []
    for e in fontes:
        nomes = [norm(n) for n in (e["nome"], e["nome_srd"], *e.get("aliases", []), *e.get("nomes_en", []))]
        if any(alvo in n for n in nomes):
            # O nome em português começando pelo texto vem primeiro; depois um
            # apelido ou o nome em inglês; depois quem só o contém.
            ordem = 0 if nomes[0].startswith(alvo) else (1 if any(n.startswith(alvo) for n in nomes) else 2)
            achados.append((ordem, e["nome"], e))
    achados.sort(key=lambda x: (x[0], x[1]))
    return [e for _, _, e in achados[:limite]]
