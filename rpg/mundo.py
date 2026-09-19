"""
mundo.py
A tela "O Mundo" da fantasia e o bloco de cena que o mestre recebe.

Junta o que é da fantasia e não do D&D: renome, facções e títulos
(faccoes.py), mudanças no mundo (mudancas.py), laços dos companheiros
(lacos.py), lendas e profecias (lendas.py) e o bestiário (bestiario.py). Vale
para a fantasia e o dark fantasy, com e sem as regras de D&D. Na tela, só o
que o grupo sabe; no bloco do mestre, tudo.
"""
from rpg import bestiario, faccoes, lacos, lendas, memory, mudancas

GENEROS = ("fantasia", "dark_fantasy")


def e_do_genero() -> bool:
    return (memory.campaign.get("campaign_type") or "") in GENEROS


def estado() -> dict:
    return {
        "renome": faccoes.renome(),
        "faccoes": faccoes.faccoes_visiveis(),
        "titulos": faccoes.titulos(),
        "companheiros": lacos.companheiros(),
        "lendas": lendas.visiveis(),
        "bestiario": bestiario.visiveis(),
        "mudancas": mudancas.todas(),
    }


def bloco_de_cena() -> str:
    if not e_do_genero():
        return ""
    partes = []
    reputacao = faccoes.resumo_para_o_mestre()
    tem_renome = memory.campaign.get("renome") or memory.campaign.get("faccoes") or memory.campaign.get("titulos")
    if tem_renome:
        partes.append("RENOME, FACÇÕES E TÍTULOS — a fama chega antes do grupo; guardas, nobres e "
                      "taverneiros reagem a isso.\n" + reputacao)
    lugar = mudancas.resumo_para_o_mestre(memory.campaign.get("current_location", "") or "")
    if lugar:
        partes.append("COMO ESTE LUGAR MUDOU pelo que o grupo fez — mostre na descrição.\n" + lugar)
    laco = lacos.resumo_para_o_mestre()
    if laco:
        partes.append("LAÇOS DOS COMPANHEIROS — eles têm vontade própria; lealdade baixa pode "
                      "virar abandono ou traição, e os arcos pedem cenas.\n" + laco)
    lenda = lendas.resumo_para_o_mestre()
    if lenda:
        partes.append("LENDAS EM ABERTO — a verdade é só sua; revele em fragmentos, pela "
                      "boca do mundo (um livro, um bardo, uma ruína).\n" + lenda)
    bicho = bestiario.resumo_para_o_mestre()
    if bicho:
        partes.append("BESTIÁRIO — o que o grupo já sabe das criaturas; se usarem uma fraqueza, "
                      "ela funciona.\n" + bicho)
    if not partes:
        return ""
    return ("\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "O MUNDO (o que o grupo construiu e o que ainda está oculto)\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n" + "\n\n".join(partes))
