"""
personagens.py
A ficha de um personagem para a tela: quem é, onde está, a relação com o
grupo e as ligações com a história.

Quase tudo já existia e não aparecia em lugar nenhum do jogo:
  • a atitude (-100 a +100) e o histórico do porquê, de adjust_attitude;
  • as missões que ele encomendou (quests[...]["quem_deu"]);
  • os eventos em que aparece (events[...]["characters_involved"]);
  • o lugar onde está (local) e, se é uma loja, onde trabalha.

O que é novo: "o que o grupo sabe" (`conhecido`, lista de fatos que o
mestre registra com add_character_knowledge). As `notes` ficam como caderno
do mestre e NÃO entram na ficha: o editor sugeria "objetivos secretos" ali,
e mostrar isso ao jogador era spoiler.
"""
from rpg import entre, locais, memory

_FORA_DE_ALCANCE = ("morto", "desaparecido", "preso", "exilado", "fugiu")
MAX_CONHECIDO = 30
MAX_CENAS = 5


def limpar_conhecido(fatos) -> list[str]:
    """
    O que o grupo sabe, como vem dos editores ou da ferramenta: uma lista (ou
    um texto com um fato por linha) sem vazios nem repetidos, os mais recentes
    no fim e no máximo MAX_CONHECIDO.
    """
    if isinstance(fatos, str):
        fatos = fatos.splitlines()
    vistos, saida = set(), []
    for f in fatos or []:
        texto = " ".join(str(f).split()) if isinstance(f, (str, int, float)) else ""
        if texto and locais.norm(texto) not in vistos:
            vistos.add(locais.norm(texto))
            saida.append(texto)
    return saida[-MAX_CONHECIDO:]


def _personagem(nome: str) -> dict | None:
    chars = memory.campaign.get("characters") or {}
    achado = chars.get(memory.char_key(nome or ""))
    if achado:
        return achado
    alvo = locais.norm(nome)
    return next((c for c in chars.values()
                 if isinstance(c, dict) and locais.norm(c.get("name", "")) == alvo), None)


def _cita(texto: str, nome: str) -> bool:
    """O nome aparece como item de uma lista "Brom, Lyra" ou no texto?"""
    alvo = locais.norm(nome)
    if not alvo:
        return False
    partes = [locais.norm(p) for p in (texto or "").replace(";", ",").split(",")]
    return alvo in partes or f" {alvo} " in f" {locais.norm(texto)} "


def _loja_do_personagem(nome: str, local: str) -> dict | None:
    """
    A loja em que ele atende, com o estoque: a que tem o nome dele como dono
    (open_shop(owner=...)) ou, na falta disso, a do lugar onde ele está.

    A ficha dizia só "Trabalha em X" e mandava o jogador até a tela da loja
    para saber o que havia à venda — quando a tela abre, que é só no local.
    """
    from rpg import tools_dnd as td

    lojas = (memory.campaign.get("lojas") or {}).values()
    escolhida = next((l for l in lojas
                      if locais.norm(l.get("dono", "") or "") == locais.norm(nome)), None)
    dono = escolhida is not None
    if not escolhida and local:
        lugar = locais.lugar(local)
        if lugar and lugar.get("tipo") == "loja":
            escolhida = next((l for l in lojas
                              if locais.norm(l.get("nome", "")) == locais.norm(lugar["name"])), None)
            if not escolhida:
                # A loja existe como LUGAR, mas sem estoque aberto ainda.
                return {"nome": lugar["name"], "dono": False, "estoque": [], "local": lugar["name"]}
    if not escolhida:
        return None
    return {
        "nome":  escolhida.get("nome", ""),
        "dono":  dono,
        "local": escolhida.get("local", "") or "",
        "estoque": [{"nome": i.get("nome", ""),
                     "preco": td._preco_com_atitude(int(i.get("preco", 0) or 0), escolhida),
                     "tabela": int(i.get("preco", 0) or 0),
                     "qtd": int(i.get("qtd", 0) or 0)}
                    for i in (escolhida.get("estoque") or [])],
    }


def _efeitos_da_atitude(valor: int) -> list[str]:
    """
    O que a atitude faz na mesa, em número. Ela já mexia na CD dos testes
    sociais e agora mexe no preço da loja, e nada disso aparecia na ficha:
    o jogador via "leal" e não sabia o que ganhava com isso.
    """
    from rpg import tools_dnd as td

    passos = td._passos_de_atitude(valor)
    if not passos:
        return []
    cd  = -passos
    pct = -passos * int(td._PASSO_DE_PRECO * 100)
    return [f"{cd:+d} na CD de testes sociais com ele",
            f"{pct:+d}% no preço da loja dele"]


def _mundo_da_pessoa(ch: dict) -> dict:
    from rpg import faccoes, lacos
    if (memory.campaign.get("campaign_type") or "") not in faccoes.GENEROS:
        return {"laco": None, "titulos": []}
    return {"laco": lacos.do_companheiro(ch), "titulos": faccoes.titulos(ch.get("name", ""))}


def _usa_regras() -> bool:
    """
    Os efeitos da atitude (CD dos testes sociais, preço da loja) são regras de
    D&D: numa campanha narrativa eles não existem, e a ficha os prometia.
    """
    from rpg.toolsets import _campanha_usa_dnd
    return _campanha_usa_dnd(memory.campaign)


def ficha(nome: str) -> dict:
    from rpg.tools import _faixa_atitude, atitude_de

    ch = _personagem(nome)
    if not ch:
        return {"existe": False, "nome": (nome or "").strip()}

    nome_real = ch.get("name", nome)
    status = ch.get("status", "") or "vivo"
    do_grupo = bool(memory.is_party_member(ch))
    protagonista = (locais.norm(memory.campaign.get("protagonist", "") or "")
                    == locais.norm(nome_real))

    valor = atitude_de(ch)
    rotulo, conduta = _faixa_atitude(valor)
    historico = [{"delta": int(h.get("delta", 0) or 0), "motivo": h.get("motivo", ""),
                  "capitulo": h.get("cap")}
                 for h in reversed(ch.get("atitude_historico") or []) if isinstance(h, dict)]

    local = ch.get("local", "") or ""
    if do_grupo:
        local = memory.campaign.get("current_location", "") or ""
    alcance = locais.alcance(local) if local else ""

    missoes = []
    for q in (memory.campaign.get("quests") or {}).values():
        if isinstance(q, dict) and q.get("quem_deu") and locais.norm(q["quem_deu"]) == locais.norm(nome_real):
            missoes.append({"titulo": q.get("titulo", ""), "status": q.get("status", "")})

    # As cenas em que ele aparece, da mais recente para trás. Antes a ficha
    # mostrava oito, das mais antigas para a frente e sem capítulo nem
    # consequência: o jogador que tinha acabado de conversar com ele lia
    # primeiro o encontro de três capítulos atrás.
    cenas = [{"resumo": e.get("summary", ""), "local": e.get("location", ""),
              "capitulo": e.get("chapter"), "consequencia": e.get("consequence", "") or ""}
             for e in (memory.campaign.get("events") or [])
             if isinstance(e, dict) and _cita(e.get("characters_involved", ""), nome_real)]
    eventos = list(reversed(cenas))

    loja = _loja_do_personagem(nome_real, local)

    # No romance a ficha mostra a relação (afeto, confiança e vínculo) no lugar
    # da atitude, e para todos: as pessoas próximas são justamente as que mais
    # importam, e a atitude escondia a relação de quem é do grupo.
    romance = (memory.campaign.get("campaign_type") or "") == "romance"
    relacao = None
    if romance:
        from rpg import relacoes
        relacao = relacoes._pessoa(ch)

    return {
        "existe": True,
        "nome": nome_real,
        "status": status,
        "do_grupo": do_grupo,
        "descricao": ch.get("description", "") or "",
        "tracos": ch.get("traits", "") or "",
        "conhecido": [f for f in (ch.get("conhecido") or []) if isinstance(f, str) and f.strip()],
        "local": {"nome": locais.nome_canonico(local), "alcance": alcance} if local else None,
        # Relação só faz sentido para quem não é do grupo.
        "relacao": relacao,
        # Fantasia: o laço do companheiro (lealdade, objetivo, arco) e os
        # títulos que o mundo deu a ele.
        **_mundo_da_pessoa(ch),
        # A atitude de quem é do GRUPO também aparece: o jogador via a relação
        # do companheiro só na tela do Mundo, e a ficha — que é onde ele olha
        # antes de falar com alguém — não dizia nada. Os efeitos de regra (CD
        # dos testes sociais, preço da loja) continuam só para quem não é do
        # grupo, porque é só lá que eles valem.
        #
        # O protagonista fica de fora: atitude dele com o próprio grupo não
        # quer dizer nada.
        "atitude": None if (romance or protagonista) else {
            "valor": valor, "rotulo": rotulo, "conduta": conduta,
            "historico": historico,
            "efeitos": [] if do_grupo else (_efeitos_da_atitude(valor) if _usa_regras() else []),
        },
        # O que esta pessoa sente por CADA outra (rpg/entre.py). A atitude
        # acima é o sentimento pelo grupo; esta lista é o que acontece entre
        # duas pessoas, que era o buraco: "Helena odiou a sugestão de Selene"
        # descontava do número do grupo por falta de lugar melhor.
        #
        # No romance, o par com o protagonista NÃO aparece aqui: ele tem casa
        # própria logo acima (afeto e confiança). Duas caixas para a mesma
        # relação, com números diferentes, é pior do que uma.
        "entre": [r for r in entre.de_quem(nome_real)
                  if not (romance and locais.norm(r["nome"])
                          == locais.norm(memory.campaign.get("protagonist", "") or ""))],
        "missoes": missoes,
        # A lista curta é a da tela; `encontros` diz quantas existem ao todo,
        # para ela poder dizer "as 5 mais recentes de 12".
        "eventos": eventos[:MAX_CENAS],
        "encontros": len(eventos),
        "ultima_cena": eventos[0] if eventos else None,
        "loja": loja,
        "pode_falar": (not do_grupo and bool(alcance)
                       and status.lower() not in _FORA_DE_ALCANCE),
    }


def _inteiro(valor, campo: str):
    """Devolve (numero, erro). Vazio e texto não viram 0 calado."""
    try:
        return max(-100, min(100, int(valor))), ""
    except (TypeError, ValueError):
        return 0, f"O valor de {campo} precisa ser um número de -100 a 100."


def editar_relacao(nome: str, dados: dict) -> dict:
    """
    O jogador mexendo na relação, pela ficha. Três coisas, uma por chamada:

      {"atitude": 35, "motivo": "..."}           o que ele sente pelo GRUPO
      {"lealdade": 90, "motivo": "..."}          se ele fica quando custa caro
      {"para": "Selene", "valor": -25, ...}      o que ele sente por ALGUÉM
      {"para": "Selene", "apagar": true}

    Por que isso é do jogador e não só do mestre: a mesa dele é quem sabe o
    que aconteceu. Na partida medida, o mestre pôs Helena em "neutro" por uma
    briga com Selene enquanto a lealdade dela era 90 — e não havia como
    corrigir sem abrir o editor de ficha inteiro.

    O motivo entra no histórico como qualquer outra mudança: daqui a dez
    capítulos ninguém lembra por que o número é esse.
    """
    from rpg.tools import adjust_attitude, atitude_de
    from rpg import lacos

    ch = _personagem(nome)
    if not ch:
        return {"erro": f"Personagem '{nome}' não encontrado."}
    nome_real = ch.get("name", nome)
    motivo = " ".join(str(dados.get("motivo") or "").split()) or "ajustado pelo jogador"

    if dados.get("para"):
        alvo = str(dados["para"]).strip()
        # No romance, a relação com o protagonista é o afeto da tela de
        # Relações. Gravá-la em entre.py deixaria o jogador editando um número
        # que nenhuma tela mostra — ele mexeria e nada mudaria à frente dele.
        romance_com_voce = (
            (memory.campaign.get("campaign_type") or "") == "romance"
            and locais.norm(memory.campaign.get("protagonist", "") or "")
            in (locais.norm(nome_real), locais.norm(alvo))
        )
        if romance_com_voce and not dados.get("apagar"):
            from rpg import relacoes
            outro = (alvo if locais.norm(nome_real)
                     == locais.norm(memory.campaign.get("protagonist", "") or "") else nome_real)
            ch_outro = _personagem(outro)
            if not ch_outro:
                return {"erro": f"Personagem '{outro}' não encontrado."}
            valor, erro = _inteiro(dados.get("valor"), "relação")
            if erro:
                return {"erro": erro}
            delta = valor - relacoes.afeto_de(ch_outro)
            if delta:
                relacoes.ajustar(outro, afeto=delta, motivo=motivo)
            return ficha(nome_real)
        if dados.get("apagar"):
            # Some dos dois lados: meia relação registrada é justamente o que
            # fazia a ficha de uma parecer vazia enquanto a da outra tinha
            # tudo.
            resposta = entre.remover(nome_real, alvo)
            if entre.existe(alvo, nome_real):
                entre.remover(alvo, nome_real)
        else:
            valor, erro = _inteiro(dados.get("valor"), "relação")
            if erro:
                return {"erro": erro}
            # Relação nova nasce dos dois lados, como no fechamento do turno:
            # é a relação DAS DUAS pessoas. O que já existe do outro lado não
            # é mexido — se ela gosta dele e ele não gosta dela, isso é a
            # história deles, não engano.
            if not entre.existe(alvo, nome_real):
                entre.definir(alvo, nome_real, valor, motivo)
            resposta = entre.definir(nome_real, alvo, valor, motivo)
        if str(resposta).startswith("Erro:"):
            return {"erro": resposta[6:].strip()}
        return ficha(nome_real)

    if "atitude" in dados:
        valor, erro = _inteiro(dados.get("atitude"), "atitude")
        if erro:
            return {"erro": erro}
        # Pelo delta, de propósito: é o mesmo caminho da ferramenta do mestre,
        # então o histórico e o afeto do romance continuam coerentes.
        adjust_attitude(nome_real, valor - atitude_de(ch), motivo)
        return ficha(nome_real)

    if "lealdade" in dados:
        valor, erro = _inteiro(dados.get("lealdade"), "lealdade")
        if erro:
            return {"erro": erro}
        try:
            atual = int(ch.get("lealdade") or 0)
        except (TypeError, ValueError):
            atual = 0
        if valor != atual:
            # A recusa do laço vem em frases ("Lealdade e arco são dos
            # companheiros, não do protagonista."), sem prefixo fixo. Quem diz
            # se pegou é o número: se não mudou, a frase É o motivo.
            resposta = lacos.ajustar_lealdade(nome_real, valor - atual, motivo)
            if int(ch.get("lealdade") or 0) != valor:
                return {"erro": str(resposta)}
        return ficha(nome_real)

    return {"erro": "Nada para mudar."}


# ---------------------------------------------------------------------------
# Índice de personagens
# ---------------------------------------------------------------------------
# A Enciclopédia da barra lateral era o único lugar que listava todos os
# personagens, espremida numa coluna estreita e sem busca. O índice é a lista
# para a tela: cada um com a categoria (grupo, conhecido, inimigo, morto), se
# está aqui com o grupo, onde está e a relação com o grupo. A ficha de cada
# um continua sendo ficha().

# Ordem da lista: o grupo, depois quem está aqui, depois o resto por categoria.
_ORDEM_DA_CATEGORIA = {"conhecido": 0, "inimigo": 1, "morto": 2}
_TAMANHO_DA_DESCRICAO = 140


def _categoria(ch: dict) -> str:
    status = (ch.get("status") or "").lower()
    if memory.is_party_member(ch) and status != "morto":
        return "grupo"
    if status == "morto":
        return "morto"
    if status == "inimigo":
        return "inimigo"
    return "conhecido"


def indice() -> dict:
    """Todos os personagens da campanha, na ordem da tela, com a contagem por filtro."""
    from rpg.tools import _faixa_atitude, atitude_de

    atual = memory.campaign.get("current_location", "") or ""
    pessoas = []
    for ch in (memory.campaign.get("characters") or {}).values():
        if not isinstance(ch, dict) or not ch.get("name"):
            continue
        categoria = _categoria(ch)
        do_grupo = categoria == "grupo"
        local = atual if do_grupo else (ch.get("local", "") or "")
        descricao = " ".join((ch.get("description", "") or "").split())
        if len(descricao) > _TAMANHO_DA_DESCRICAO:
            descricao = descricao[:_TAMANHO_DA_DESCRICAO].rsplit(" ", 1)[0] + "…"
        pessoas.append({
            "nome": ch["name"],
            "status": ch.get("status", "") or "vivo",
            "categoria": categoria,
            "do_grupo": do_grupo,
            "aqui": categoria != "morto" and bool(local) and locais.alcance(local) == "aqui",
            "local": locais.nome_canonico(local) if local else "",
            "descricao": descricao,
            # A relação só aparece para quem o mestre já mexeu: um "neutro"
            # em todo mundo seria ruído.
            "atitude": (_faixa_atitude(atitude_de(ch))[0]
                        if not do_grupo and "atitude" in ch else ""),
            "tem_ficha": bool(ch.get("sheet")),
        })

    def _posicao(p):
        if p["categoria"] == "grupo":
            return 0
        if p["aqui"]:
            return 1
        return 2 + _ORDEM_DA_CATEGORIA[p["categoria"]]

    pessoas.sort(key=lambda p: (_posicao(p), locais.norm(p["nome"])))
    contagem = {
        "todos": len(pessoas),
        "aqui": sum(p["aqui"] for p in pessoas),
        "grupo": sum(p["categoria"] == "grupo" for p in pessoas),
        "conhecidos": sum(p["categoria"] == "conhecido" for p in pessoas),
        "inimigos": sum(p["categoria"] == "inimigo" for p in pessoas),
        "mortos": sum(p["categoria"] == "morto" for p in pessoas),
    }
    return {"personagens": pessoas, "contagem": contagem, "local_atual": atual}
