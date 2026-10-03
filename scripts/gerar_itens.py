"""
gerar_itens.py
Gera o compêndio local de ITENS do SRD 5.1 a partir dos dados brutos do
Open5e v2 e dos nomes em português revisados à mão.

    python scripts/gerar_itens.py            # gera rpg/dados/srd_itens.json
    python scripts/gerar_itens.py --baixar   # baixa o SRD de novo antes

POR QUE EXISTE
──────────────
O motor sabia de itens por umas quinze tabelas feitas à mão, cada uma com um
pedaço (o preço das armas sem o dano, a CA das armaduras sem o peso, os nomes
dos itens mágicos sem a raridade), e completava o resto perguntando ao Open5e
v1 EM TEMPO DE JOGO, com nome em português numa API em inglês. Medido antes
desta troca:

  • sem rede, TODA arma causava 1d6 (a tabela local tinha preço, não dano);
  • "Espada Longa +1" causava 1d6+1: o "+1" quebrava a busca pelo nome, e a
    arma mágica batia menos que a comum (1d8);
  • Mangual, Maça-Estrela, Azagaia, Machadinha e Rede não tinham tradução;
  • "Chain Mail" com o slot informado equipava como CA 10 + DES inteira;
  • tocha, corda, ração e Poção de Cura não tinham preço;
  • a Mochila e a Loja faziam até duas consultas de 4 s por item desconhecido.

Aqui a leitura acontece UMA vez, fora do jogo, e o resultado é revisável, como
o compêndio de magias (scripts/gerar_compendio.py).

DE ONDE VEM CADA VALOR
──────────────────────
  • Dano, tipo, propriedades e alcance das armas; CA, FOR mínima e furtividade
    das armaduras: os campos do Open5e v2 (documento srd-2014).
  • Preço e peso: o Open5e v2, em peças de cobre e quilos.
  • Nomes, apelidos e as bases das armas e armaduras mágicas: à mão, em
    scripts/srd_itens_pt.json, junto com cada correção e o seu porquê.
  • O texto em inglês dos itens mágicos fica em `texto_srd`: é o que o Mestre
    recebe ao identificar um item. A Mochila nunca mostra esse texto.

Toda correção aplicada vai para scripts/srd_itens_relatorio.txt.

LICENÇA
───────
Este material vem do System Reference Document 5.1 da Wizards of the Coast,
disponível sob a licença Creative Commons Atribuição 4.0 Internacional
(https://creativecommons.org/licenses/by/4.0/legalcode).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BRUTO = RAIZ / "scripts" / "srd_bruto"
DESTINO = RAIZ / "rpg" / "dados"
NOMES_PT = RAIZ / "scripts" / "srd_itens_pt.json"
RELATORIO = RAIZ / "scripts" / "srd_itens_relatorio.txt"

ATRIBUICAO = (
    "Este trabalho inclui material do System Reference Document 5.1 (\"SRD "
    "5.1\") da Wizards of the Coast LLC, disponível em "
    "https://dnd.wizards.com/resources/systems-reference-document. O SRD 5.1 é "
    "licenciado sob a Creative Commons Atribuição 4.0 Internacional, disponível "
    "em https://creativecommons.org/licenses/by/4.0/legalcode. Nomes em "
    "português e a estrutura dos campos são obra derivada."
)

LB_PARA_KG = 0.4536
PES_PARA_M = 0.3            # convenção do D&D em português: 5 pés = 1,5 m

CATEGORIA = {
    "weapon": "arma", "armor": "armadura", "shield": "escudo", "ammunition": "municao",
    "adventuring-gear": "equipamento", "tools": "ferramenta", "trade-good": "mercadoria",
    "poison": "veneno", "land-vehicle": "veiculo", "waterborne-vehicle": "veiculo",
    "ring": "equipamento", "rod": "equipamento", "staff": "equipamento", "wand": "equipamento",
}

PROPRIEDADE = {
    "Ammunition": "municao", "Finesse": "acuidade", "Heavy": "pesada", "Light": "leve",
    "Loading": "recarga", "Reach": "alcance", "Thrown": "arremesso",
    "Two-Handed": "duas_maos", "Versatile": "versatil",
    "Special (Lance)": "especial", "Special (Net)": "especial",
}

# O Open5e v2 não marca "Heavy" em nenhuma arma do srd-2014. No SRD 5.1 estas
# oito são pesadas (criatura Pequena ataca com desvantagem).
PESADAS = {"glaive", "greataxe", "greatsword", "halberd", "maul", "pike",
           "crossbow-heavy", "longbow"}

# Armas à distância do SRD. As de arremesso (adaga, azagaia) são corpo a corpo.
A_DISTANCIA = {"crossbow-light", "dart", "shortbow", "sling", "blowgun",
               "crossbow-hand", "crossbow-heavy", "longbow", "net"}
SIMPLES = {"club", "dagger", "greatclub", "handaxe", "javelin", "light-hammer", "mace",
           "quarterstaff", "sickle", "spear", "crossbow-light", "dart", "shortbow", "sling"}

MUNICAO_DA_ARMA = {"shortbow": "arrow-bow", "longbow": "arrow-bow",
                   "crossbow-light": "crossbow-bolt", "crossbow-hand": "crossbow-bolt",
                   "crossbow-heavy": "crossbow-bolt", "sling": "sling-bullets",
                   "blowgun": "blowgun-needles"}

RARIDADE = {"common": "comum", "uncommon": "incomum", "rare": "raro",
            "very-rare": "muito raro", "legendary": "lendário", "artifact": "artefato"}
ORDEM_RARIDADE = ["comum", "incomum", "raro", "muito raro", "lendário", "artefato"]

# Onde se usa o item mágico, pelo começo do nome no SRD. O SRD 5.1 não tem
# slots; o motor tem, para que dois mantos não deem +2 de CA. Pedra Ioun e
# Pedra da Sorte valem carregadas ("carregado").
SLOT_POR_NOME = (
    ("Ring of", "anel"),
    ("Cloak of", "capa"), ("Cape of", "capa"), ("Mantle of", "capa"), ("Robe of", "capa"),
    ("Boots of", "botas"), ("Winged Boots", "botas"), ("Slippers of", "botas"),
    ("Gloves of", "luvas"), ("Gauntlets of", "luvas"), ("Bracers of", "luvas"),
    ("Helm of", "cabeca"), ("Hat of", "cabeca"), ("Circlet of", "cabeca"),
    ("Headband of", "cabeca"), ("Goggles of", "cabeca"), ("Eyes of", "cabeca"),
    ("Belt of", "cinto"),
    ("Amulet of", "amuleto"), ("Necklace of", "amuleto"), ("Medallion of", "amuleto"),
    ("Periapt of", "amuleto"), ("Talisman of", "amuleto"), ("Scarab of", "amuleto"),
    ("Brooch of", "amuleto"),
    ("Stone of Good Luck", "carregado"), ("Ioun Stone", "carregado"),
)


def _slot_do_magico(nome_srd: str) -> str:
    return next((slot for prefixo, slot in SLOT_POR_NOME if nome_srd.startswith(prefixo)), "")


TIPO_MAGICO = {"Armor": "armadura", "Weapon": "arma", "Shield": "escudo", "Ring": "anel",
               "Rod": "cetro", "Staff": "cajado", "Wand": "varinha", "Potion": "poção",
               "Scroll": "pergaminho", "Wondrous Item": "item maravilhoso",
               "Ammunition": "munição"}


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", t).strip()


def _so_letras(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _norm(t))


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _metros(pes: float) -> float:
    return round(pes * PES_PARA_M, 1)


def _sem_parentese(nome: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*$", "", nome).strip()


def _carregar(nome: str) -> list[dict]:
    return json.loads((BRUTO / f"{nome}.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Itens comuns
# ---------------------------------------------------------------------------

def gerar_comuns(pt: dict, relatorio: list[str]) -> dict:
    armas = {x["key"][4:]: x for x in _carregar("armas")}
    armaduras = {x["key"][4:]: x for x in _carregar("armaduras")}
    revisoes = pt["revisoes_comuns"]
    saida = {}
    for bruto in _carregar("itens"):
        chave = bruto["key"][4:]
        if chave in pt["ignorar"]:
            continue
        nomes = pt["comuns"].get(chave)
        if not nomes:
            relatorio.append(f"SEM NOME EM PORTUGUÊS: {chave} ({bruto['name']})")
            continue
        cat = CATEGORIA.get(bruto["category"]["key"], "equipamento")
        rev = revisoes.get(chave, {})
        peso_lb = rev.get("peso_lb", _num(bruto.get("weight")))
        if "peso_lb" in rev:
            relatorio.append(f"{chave}: peso {bruto.get('weight')} lb -> {rev['peso_lb']} lb ({rev['_porque']})")
        entrada = {
            "chave": chave,
            "nome": nomes["nome"],
            "nome_srd": rev.get("nome_srd", bruto["name"]),
            "aliases": list(nomes["aliases"]),
            "categoria": cat,
            "preco_pc": int(round(_num(bruto.get("cost")) * 100)),
            "peso_kg": round(peso_lb * LB_PARA_KG, 2),
        }
        if cat == "arma":
            entrada["arma"] = _arma(chave, armas[chave], relatorio)
            _revisar_arma(entrada["arma"], rev)
        elif cat in ("armadura", "escudo"):
            entrada["armadura"] = _armadura(chave, armaduras, bruto)
            # O nome do endpoint de armaduras ("Hide", "Studded leather") é
            # o que os stat blocks escrevem e o que a tabela de CA usava.
            entrada["nome_srd"] = entrada["armadura"].pop("_nome_srd", entrada["nome_srd"])
        if bruto["name"] != entrada["nome_srd"]:
            # Outro nome em inglês ("Plate Armor" na lista de itens, "Plate"
            # na de armaduras). Separado dos apelidos em português, que o
            # assistente de criação de personagem também conhece.
            entrada["nomes_en"] = [bruto["name"]]
        if "_porque" in rev and "peso_lb" not in rev:
            relatorio.append(f"{chave}: {rev['_porque']}")
        saida[chave] = entrada
    return saida


def _arma(chave: str, x: dict, relatorio: list[str]) -> dict:
    props, versatil = [], ""
    for p in x.get("properties") or []:
        nome = p["property"]["name"]
        prop = PROPRIEDADE.get(nome)
        if not prop:
            relatorio.append(f"{chave}: propriedade desconhecida {nome}")
            continue
        props.append(prop)
        if prop == "versatil":
            versatil = p.get("detail") or ""
    if chave in PESADAS:
        props.append("pesada")
    dado = str(x.get("damage_dice") or "")
    arma = {
        "dado": dado if "d" in dado else ("1" if dado == "1" else ""),
        "tipo_dano": (x.get("damage_type") or {}).get("key", "") if dado != "0" else "",
        "grupo": "simples" if chave in SIMPLES else "marcial",
        "distancia": chave in A_DISTANCIA,
        "propriedades": sorted(set(props)),
    }
    if versatil:
        arma["versatil"] = versatil
    if x.get("range"):
        arma["alcance_m"] = [_metros(x["range"]), _metros(x.get("long_range") or x["range"])]
    if chave in MUNICAO_DA_ARMA:
        arma["municao"] = MUNICAO_DA_ARMA[chave]
    return arma


def _revisar_arma(arma: dict, rev: dict) -> None:
    """As correções da tabela de armas do SRD 5.1 que o Open5e v2 erra."""
    props = set(arma["propriedades"]) | set(rev.get("propriedades_mais", []))
    props -= set(rev.get("propriedades_menos", []))
    arma["propriedades"] = sorted(props)
    if rev.get("tipo_dano"):
        arma["tipo_dano"] = rev["tipo_dano"]


def _armadura(chave: str, armaduras: dict, bruto: dict) -> dict:
    if chave == "shield":
        return {"tipo": "escudo", "ca_base": 2, "dex": "shield", "forca_min": 0,
                "furtividade_desvantagem": False}
    a = armaduras.get(chave) or armaduras.get(chave.replace("-armor", ""))
    tipo = {"light": "leve", "medium": "media", "heavy": "pesada"}[a["category"]]
    if not a.get("ac_add_dexmod"):
        dex = "none"
    elif a.get("ac_cap_dexmod") == 2:
        dex = "cap2"
    else:
        dex = "full"
    return {"tipo": tipo, "ca_base": int(a["ac_base"]), "dex": dex,
            "forca_min": int(a.get("strength_score_required") or 0),
            "furtividade_desvantagem": bool(a.get("grants_stealth_disadvantage")),
            "_nome_srd": a["name"]}


# ---------------------------------------------------------------------------
# Itens mágicos
# ---------------------------------------------------------------------------

def gerar_magicos(pt: dict, comuns: dict, relatorio: list[str]) -> dict:
    nomes_de_arma = {_so_letras(e["nome_srd"]): k for k, e in comuns.items() if e["categoria"] == "arma"}
    nomes_de_arma.update({_so_letras(k): k for k, e in comuns.items() if e["categoria"] == "arma"})
    por_srd = {_norm(e["nome_srd"]): k for k, e in comuns.items() if e["categoria"] in ("arma", "armadura", "escudo")}

    grupos: dict[str, list[dict]] = defaultdict(list)
    for x in _carregar("itens_magicos"):
        grupos[_sem_parentese(x["name"])].append(x)

    saida = {}
    for base, variantes in grupos.items():
        if _so_letras(base) in nomes_de_arma:
            continue                        # "Longsword (+1)": coberta por weapon-plus
        nomes = pt["magicos"].get(base)
        if not nomes:
            relatorio.append(f"SEM NOME EM PORTUGUÊS (mágico): {base}")
            continue
        raridades = sorted({RARIDADE[v["rarity"]["key"]] for v in variantes},
                           key=ORDEM_RARIDADE.index)
        primeira = variantes[0]
        tipo = TIPO_MAGICO.get(nomes.get("tipo") or primeira["category"]["name"], "item maravilhoso")
        sintoniza = any(v.get("requires_attunement") for v in variantes)
        detalhe = next((v.get("attunement_detail") for v in variantes if v.get("attunement_detail")), "")
        entrada = {
            "chave": _so_letras(base) and re.sub(r"[^a-z0-9]+", "-", _norm(base)).strip("-"),
            "nome": nomes["nome"],
            "nome_srd": base,
            "aliases": list(nomes.get("aliases") or []),
            "tipo": tipo,
            "raridade": raridades[0],
            "sintonizacao": sintoniza,
            "peso_kg": round(_num(primeira.get("weight")) * LB_PARA_KG, 2),
            "texto_srd": " ".join((primeira.get("desc") or "").split()),
        }
        if len(raridades) > 1:
            entrada["raridades"] = raridades
        if detalhe:
            entrada["sintonizacao_detalhe"] = detalhe
        if nomes.get("preco_po"):
            entrada["preco_pc"] = int(nomes["preco_po"]) * 100
            relatorio.append(f"{base}: preço {nomes['preco_po']} po (Livro do Jogador; o SRD não dá preço)")
        for campo in ("base_arma", "base_armadura"):
            if nomes.get(campo):
                alvo = por_srd.get(_norm(nomes[campo]))
                if not alvo:
                    relatorio.append(f"{base}: {campo} '{nomes[campo]}' não existe")
                    continue
                entrada[campo] = alvo
        if _slot_do_magico(base):
            entrada["slot"] = _slot_do_magico(base)
        if nomes.get("efeito"):
            entrada["efeito"] = nomes["efeito"]
        if nomes.get("uso"):
            entrada["uso"] = nomes["uso"]
        for campo in ("bonus", "qualquer_arma", "qualquer_armadura"):
            if nomes.get(campo):
                entrada[campo] = nomes[campo]
        if len(variantes) > 1:
            entrada["variantes"] = []
            for v in variantes:
                var = {"nome_srd": v["name"], "raridade": RARIDADE[v["rarity"]["key"]]}
                texto = " ".join((v.get("desc") or "").split())
                if texto != entrada["texto_srd"]:
                    var["texto_srd"] = texto
                entrada["variantes"].append(var)
        saida[entrada["chave"]] = entrada

    for chave, s in pt["sinteticos"].items():
        saida[chave] = {"chave": chave, "nome": s["nome"], "nome_srd": s["nome_srd"],
                        "aliases": [], "tipo": s["tipo"],
                        "raridade": s["raridade_por_bonus"]["1"],
                        "raridade_por_bonus": s["raridade_por_bonus"],
                        "sintonizacao": False, "peso_kg": 0.0, "texto_srd": s["texto_srd"],
                        "sintetico": True}
    sem_uso = sorted(set(pt["magicos"]) - set(grupos))
    if sem_uso:
        relatorio.append(f"NOMES SEM ITEM NO SRD: {sem_uso}")
    return saida


def conferir_apelidos(comuns: dict, magicos: dict, relatorio: list[str]) -> None:
    """O mesmo nome apontando para dois itens é ambiguidade: vai para o relatório."""
    donos: dict[str, list[str]] = defaultdict(list)
    for fonte, tabela in (("comum", comuns), ("magico", magicos)):
        for k, e in tabela.items():
            for n in {_norm(e["nome"]), _norm(e["nome_srd"]),
                      *(_norm(a) for a in e["aliases"] + e.get("nomes_en", []))}:
                donos[n].append(f"{fonte}:{k}")
    for n, quem in sorted(donos.items()):
        if len(set(quem)) > 1:
            relatorio.append(f"NOME AMBÍGUO '{n}': {sorted(set(quem))}")


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------

def baixar() -> None:
    BRUTO.mkdir(parents=True, exist_ok=True)
    for nome, caminho in (("armas", "weapons/?limit=100"), ("armaduras", "armor/?limit=100"),
                          ("itens", "items/?limit=100"),
                          ("itens_magicos", "magicitems/?document__key=srd-2014&limit=100")):
        url, tudo = f"https://api.open5e.com/v2/{caminho}", []
        while url:
            pedido = urllib.request.Request(url, headers={"User-Agent": "rpg-agent-srd/1.0"})
            with urllib.request.urlopen(pedido, timeout=60) as r:
                pagina = json.loads(r.read())
            tudo.extend(pagina.get("results") or [])
            url = pagina.get("next")
            time.sleep(0.2)
        # O filtro por documento não vale em todas as rotas: filtra aqui.
        tudo = [x for x in tudo if (x.get("document") or {}).get("key") == "srd-2014"]
        (BRUTO / f"{nome}.json").write_text(
            json.dumps(tudo, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"baixado: {nome} ({len(tudo)})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--baixar", action="store_true", help="baixa o SRD de novo antes")
    ap.add_argument("--destino", default="", help="pasta de saída (padrão: rpg/dados)")
    args = ap.parse_args()
    if args.baixar:
        baixar()

    destino = Path(args.destino) if args.destino else DESTINO
    relatorio_arq = destino / "srd_itens_relatorio.txt" if args.destino else RELATORIO
    destino.mkdir(parents=True, exist_ok=True)

    pt = json.loads(NOMES_PT.read_text(encoding="utf-8"))
    relatorio: list[str] = []
    comuns = gerar_comuns(pt, relatorio)
    magicos = gerar_magicos(pt, comuns, relatorio)
    conferir_apelidos(comuns, magicos, relatorio)

    (destino / "srd_itens.json").write_text(json.dumps(
        {"_licenca": ATRIBUICAO, "_fonte": "Open5e v2, documento srd-2014",
         "itens": comuns, "magicos": magicos}, ensure_ascii=False, indent=1), encoding="utf-8")

    cats = Counter(e["categoria"] for e in comuns.values())
    tipos = Counter(e["tipo"] for e in magicos.values())
    cabeca = [f"itens comuns: {len(comuns)}  {dict(cats)}",
              f"itens mágicos: {len(magicos)}  {dict(tipos)}", ""]
    relatorio_arq.write_text("\n".join(cabeca + relatorio) + "\n", encoding="utf-8")
    print("\n".join(cabeca[:2]))
    print(f"relatório: {len(relatorio)} linhas em {relatorio_arq}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
