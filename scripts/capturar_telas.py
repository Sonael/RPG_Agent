#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
capturar_telas.py — tira print de TODAS as telas do RPG Agent.

Como funciona
-------------
1. Sobe o servidor Flask REAL (server.py) numa porta livre, dentro do próprio
   processo. Nada de produção é alterado.
2. Troca só as duas dependências externas por dublês:
      • Supabase / auth  → usuário falso já confirmado (nenhuma chamada de rede)
      • Supabase / banco → campanha de exemplo carregada de um arquivo JSON
   Todo o resto — rotas, /api/memory, combat_snapshot, HTML, CSS e JS — é o
   código de produção. O print mostra a tela de verdade, não uma maquete.
3. Abre o Chromium (Playwright), semeia o localStorage com token e sessão de
   jogo, navega até cada tela, dispara o que precisa ser aberto (aba, modal,
   bandeja de dados, combate tático…) e salva o PNG.

Uso
---
    python capturar_telas.py                     # tudo, desktop + mobile
    python capturar_telas.py --lista             # só lista os nomes das telas
    python capturar_telas.py --apenas combate    # filtra por parte do nome
    python capturar_telas.py --viewport desktop  # desktop | mobile | ambos
    python capturar_telas.py --tema noite-tinta  # ver TEMAS mais abaixo
    python capturar_telas.py --saida prints
    python capturar_telas.py --pagina-inteira    # captura além da dobra

Saída: screenshots/<viewport>/<NN-nome>.png

Requisitos (uma vez só):
    pip install playwright && python -m playwright install chromium
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path

# O script vive em scripts/, mas opera sobre a raiz do repositório (é lá que
# ficam server.py, static/ e o pacote rpg/).
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

# O servidor não deve cuspir os logs de debug do agente durante a captura.
os.environ.setdefault("RPG_DEBUG", "0")
# Nenhuma delas é usada de verdade (os clientes são dublês), mas o import de
# database.py/auth.py fica mais previsível com as variáveis presentes.
os.environ.setdefault("SUPABASE_URL", "http://localhost/supabase-falso")
os.environ.setdefault("SUPABASE_ANON_KEY", "chave-falsa")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "chave-falsa")

USER_ID = "00000000-0000-4000-8000-000000000000"
EMAIL = "capturas@exemplo.local"
TOKEN = "token-de-captura"

TEMAS = [
    "pergaminho", "noite-tinta", "ardosia", "floresta",
    "oceano", "sangue-dragao", "poeira-ouro",
]

VIEWPORTS = {
    "desktop": {"width": 1440, "height": 900},
    "mobile": {"width": 390, "height": 844},
}


# ═══════════════════════════════════════════════════════════════════════
#  Dublês: só o que fala com o mundo externo (Supabase)
# ═══════════════════════════════════════════════════════════════════════

class _UsuarioFalso:
    """Espelha o que require_auth lê do objeto de usuário do Supabase."""

    def __init__(self):
        self.id = USER_ID
        self.email = EMAIL
        self.email_confirmed_at = "2024-01-01T00:00:00Z"


class _RespostaFalsa:
    def __init__(self):
        self.user = _UsuarioFalso()


class _ClienteAuthFalso:
    def get_user(self, token=None):
        return _RespostaFalsa()


# Funções reais trocadas pelos dublês, para devolver quando o servidor para.
# Sem isso os dublês ficavam para sempre no processo: dentro do pytest, um teste
# de navegador deixava memory.save_campaign sem gravar nada, e o teste de
# persistência que rodasse depois dele via "a missão sumiu". Passou despercebido
# enquanto os testes de navegador rodavam por último na ordem alfabética.
_ORIGINAIS: list = []


def _trocar(modulo, nome, novo) -> None:
    if not any(m is modulo and n == nome for m, n, _ in _ORIGINAIS):
        _ORIGINAIS.append((modulo, nome, getattr(modulo, nome)))
    setattr(modulo, nome, novo)


def _remover_dubles() -> None:
    while _ORIGINAIS:
        modulo, nome, original = _ORIGINAIS.pop()
        setattr(modulo, nome, original)


def _instalar_dubles(campanha: dict, nome_campanha: str) -> None:
    """Substitui auth e database por versões locais, sem rede."""
    from rpg import auth
    from rpg import database
    from rpg import memory

    _trocar(auth, "_client", lambda: _ClienteAuthFalso())

    resumo = {
        "name": nome_campanha,
        "chapter": campanha.get("chapter", 1),
        "location": campanha.get("current_location", ""),
        "characters": len(campanha.get("characters", {})),
        "events": len(campanha.get("events", [])),
    }
    # Uma segunda campanha só para a lista do menu não ficar com um item só.
    outra = {
        "name": "O Silêncio de Vharn",
        "chapter": 1,
        "location": "Portos de Vharn",
        "characters": 2,
        "events": 1,
    }

    _trocar(database, "list_campaigns", lambda user_id: [resumo, outra])
    _trocar(database, "get_campaign", lambda user_id, name: copy.deepcopy(campanha))
    _trocar(database, "save_campaign", lambda user_id, name, data: None)
    _trocar(database, "delete_campaign", lambda user_id, name: None)
    _trocar(database, "rename_campaign", lambda user_id, old_name, new_name: None)
    _trocar(database, "campaign_exists", lambda user_id, name: True)

    # Nenhuma tela de captura deve tentar persistir nada.
    _trocar(memory, "save_campaign", lambda: None)


# ═══════════════════════════════════════════════════════════════════════
#  Servidor
# ═══════════════════════════════════════════════════════════════════════

def _porta_livre() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _mesclar(destino: dict, patch: dict) -> None:
    """Merge recursivo: dicts se fundem, o resto substitui."""
    for chave, valor in patch.items():
        if isinstance(valor, dict) and isinstance(destino.get(chave), dict):
            _mesclar(destino[chave], valor)
        else:
            destino[chave] = valor


# Servidor compartilhado entre chamadas. O Flask RECUSA registrar uma rota
# depois que o app atendeu a primeira requisição, então uma segunda chamada a
# _subir_servidor explodia com "The setup method 'route' can no longer be
# called". Isso não aparecia no script de captura, que sobe o servidor uma vez
# só — apareceu quando dois arquivos de teste de navegador passaram a subi-lo,
# e cada um passava sozinho.
_SERVIDOR: tuple | None = None      # (url, funcao que para de verdade)
_REFS = 0                           # quantos chamadores ainda estão usando
_BASE: dict = {}                    # campanha-base, trocável a cada chamada
# O que o Flask proíbe é REGISTRAR A ROTA duas vezes, não subir o servidor
# duas vezes. São coisas separadas: reusar o servidor é otimização, e esta
# guarda é a correção. Contar referências sozinho não bastava — o primeiro
# módulo de teste solta o servidor antes de o segundo pedir, e aí o segundo
# tentava registrar de novo.
_ROTA_REGISTRADA = False


def _soltar_servidor() -> None:
    """Só para de verdade quando o último chamador solta."""
    global _SERVIDOR, _REFS
    _REFS = max(0, _REFS - 1)
    if _REFS == 0 and _SERVIDOR is not None:
        _SERVIDOR[1]()
        _SERVIDOR = None
        _remover_dubles()


def _completar_campanha_base(campanha: dict) -> None:
    """
    Ajustes na campanha de exemplo que valem para TODAS as capturas e testes
    de navegador, sem mexer no JSON local.

    A Helena é clériga de nível 3 e no exemplo só tem dois poderes com nome
    próprio. Sem magias do SRD na ficha sobram 3 truques e 5 magias, e a
    pílula do Grimório aparece em toda captura do jogo — por uma vaga que é
    artefato do arquivo de exemplo, não do que a captura quer mostrar.
    """
    helena = (campanha.get("characters") or {}).get("helena")
    if not helena or "clérigo" not in str((helena.get("sheet") or {}).get("classe", "")).lower():
        return

    def magia(nome, nivel, escola, desc, dado=""):
        return {"nome": nome, "descricao": f"[{escola}] {desc}",
                "custo_mana": {0: 0, 1: 2, 2: 3}[nivel], "dado": dado, "nivel_magia": nivel}

    completas = [
        magia("Luz", 0, "Evocação", "Um objeto tocado brilha como uma tocha por uma hora."),
        magia("Orientação", 0, "Adivinhação", "O alvo soma 1d4 a um teste de atributo.", "1d4"),
        magia("Taumaturgia", 0, "Transmutação", "Uma manifestação menor de poder divino."),
        magia("Cura Ferimentos", 1, "Evocação", "Toque que cura 1d8 + modificador de Sabedoria.", "1d8"),
        magia("Bênção", 1, "Encantamento", "Até três aliados somam 1d4 em ataques e saves.", "1d4"),
        magia("Escudo da Fé", 1, "Abjuração", "Um aliado ganha +2 de CA por dez minutos."),
        magia("Palavra Curativa", 1, "Evocação", "Ação bônus: cura 1d4 + modificador à distância.", "1d4"),
        magia("Arma Espiritual", 2, "Evocação", "Arma espectral que golpeia como ação bônus.", "1d8"),
    ]
    habs = helena.setdefault("habilidades", [])
    ja = {str(h.get("nome", "")).lower() for h in habs}
    habs.extend(m for m in completas if m["nome"].lower() not in ja)


def _subir_servidor(campanha: dict, nome_campanha: str):
    """
    Sobe o app real numa thread e devolve (url_base, parar).

    Registra também a rota /__estado, que existe SÓ aqui: ela recarrega a
    campanha base e aplica um patch por cima, para que cada tela possa pedir
    o estado de mundo que quer retratar (combate ativo, vitória, etc.).

    Reentrante: chamar de novo reusa o servidor que já está no ar e apenas
    troca a campanha-base.
    """
    global _SERVIDOR, _REFS, _BASE, _ROTA_REGISTRADA

    from rpg import memory
    from flask import jsonify, request
    from werkzeug.serving import make_server

    _completar_campanha_base(campanha)
    _instalar_dubles(campanha, nome_campanha)

    import server  # noqa: E402  (precisa vir depois dos dublês)

    _BASE = copy.deepcopy(campanha)

    # A rota lê _BASE (global) e não uma variável de fechamento: é o que
    # permite a segunda chamada trocar a campanha sem registrar nada de novo.
    if _SERVIDOR is not None:
        memory.bind(USER_ID, nome_campanha)
        memory.campaign.clear()
        memory.campaign.update(copy.deepcopy(_BASE))
        _REFS += 1
        return _SERVIDOR[0], _soltar_servidor

    if not _ROTA_REGISTRADA:
        # Um teste com app.test_client() rodando ANTES (na mesma sessão do
        # pytest) já fez o Flask atender a primeira requisição, e daí ele
        # recusa registrar rota nova. Isto é só o harness de captura: a rota
        # /__estado não existe no app de verdade, então liberar o registro
        # aqui não esconde nada do servidor real.
        if getattr(server.app, "_got_first_request", False):
            server.app._got_first_request = False
        @server.app.route("/__estado", methods=["POST"])
        def __estado():  # noqa: ANN202
            patch = request.get_json(silent=True) or {}
            memory.bind(USER_ID, nome_campanha)
            camp = memory.campaign
            camp.clear()
            camp.update(copy.deepcopy(_BASE))
            _mesclar(camp, patch)
            return jsonify({"ok": True})
        _ROTA_REGISTRADA = True

    # Estado inicial (a thread principal também precisa do vínculo).
    memory.bind(USER_ID, nome_campanha)
    memory.campaign.clear()
    memory.campaign.update(copy.deepcopy(_BASE))

    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    server.app.logger.setLevel(logging.ERROR)

    porta = _porta_livre()
    srv = make_server("127.0.0.1", porta, server.app, threaded=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{porta}"
    for _ in range(50):                     # espera o servidor responder
        try:
            with socket.create_connection(("127.0.0.1", porta), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)

    _SERVIDOR = (url, srv.shutdown)
    _REFS += 1
    return url, _soltar_servidor


# ═══════════════════════════════════════════════════════════════════════
#  Estados de mundo usados por algumas telas
# ═══════════════════════════════════════════════════════════════════════

# Combate na tela tática: Stelar (grupo) na vez, Victoria como inimiga.
# O turno atual é de um membro do grupo de propósito — se fosse do inimigo,
# a tela dispararia a jogada automática dele e o print sairia no meio da ação.
COMBATE_ATIVO = {
    "combat_mode": "tela",
    "characters": {
        "stelar": {"sheet": {"vida_atual": 19}},
        "helena": {"sheet": {"vida_atual": 14}},
        "victoria": {"sheet": {"vida_atual": 21}},
    },
    "combat_state": {
        "is_active": True,
        "initiative_order": ["Stelar", "Victoria", "Helena", "Natasha"],
        "current_turn_index": 0,
        "round": 3,
        "turn_economy": {"acao_usada": False, "bonus_usada": False},
        "result": None,
        "log": [
            {"round": 1, "type": "initiative", "actor": "", "target": "",
             "msg": "Iniciativa rolada — Stelar, Victoria, Helena, Natasha"},
            {"round": 1, "type": "attack", "actor": "Stelar", "target": "Victoria",
             "msg": "Stelar ataca Victoria com Montante Rúnico: 17 vs CA 16 — acerta, 8 de dano"},
            {"round": 2, "type": "ability", "actor": "Helena", "target": "Stelar",
             "msg": "Helena conjura Curar Ferimentos em Stelar: +7 PV"},
            {"round": 2, "type": "attack", "actor": "Victoria", "target": "Helena",
             "msg": "Victoria ataca Helena com Adaga: 19 vs CA 12 — acerta, 7 de dano"},
            {"round": 3, "type": "turn", "actor": "Stelar", "target": "",
             "msg": "Rodada 3 — é a vez de Stelar"},
        ],
    },
}

# Mundo da onda 4: relógio andando e duas missões na barra lateral.
MUNDO_ONDA4 = {
    "relogio": {"dia": 4, "hora": 19},
    "quests": {
        "escoltar a princesa elara": {
            "titulo": "Escoltar a Princesa Elara",
            "descricao": "Levar Elara a Luminas em segurança.",
            "status": "ativa",
            "quem_deu": "Princesa Elara",
            "recompensa": "200 po",
            "cap_inicio": 2,
            "objetivos": [
                {"texto": "Sair de Oakhaven", "feito": True},
                {"texto": "Atravessar o Passo de Vhar", "feito": True},
                {"texto": "Entregar em Luminas", "feito": False},
            ],
        },
        "a divida de torbin": {
            "titulo": "A dívida de Torbin",
            "descricao": "O ferreiro deve a agiotas do porto.",
            "status": "ativa",
            "quem_deu": "Torbin",
            "recompensa": "a espada do pai dele",
            "cap_inicio": 3,
            "objetivos": [
                {"texto": "Descobrir quem cobra a dívida", "feito": False},
            ],
        },
    },
}

# LIVRO DE MISSÕES. As duas ativas do MUNDO_ONDA4 (a da princesa, dada por
# Elara, que é uma ficha: o nome vira link), uma pronta para entregar e duas
# encerradas, para as abas terem o que mostrar.
MISSOES = copy.deepcopy(MUNDO_ONDA4)
MISSOES["quests"]["escoltar a princesa elara"]["quem_deu"] = "Elara"
MISSOES["quests"].update({
    "o mapa de kaelen": {
        "titulo": "O mapa de Kaelen", "descricao": "Recuperar o mapa roubado da torre.",
        "status": "ativa", "quem_deu": "Kaelen", "recompensa": "passagem livre pelo Passo",
        "cap_inicio": 1,
        "objetivos": [{"texto": "Entrar na torre", "feito": True},
                      {"texto": "Pegar o mapa", "feito": True}],
    },
    "ratos no porao": {
        "titulo": "Ratos no porão", "descricao": "O taverneiro ouviu barulho no porão.",
        "status": "concluida", "quem_deu": "Taverneiro", "recompensa": "uma noite de graça",
        "cap_inicio": 1, "cap_fim": 1, "desfecho": "Eram só três ratos e um gato.",
        "objetivos": [{"texto": "Descer ao porão", "feito": True}],
    },
    "a vila em chamas": {
        "titulo": "A vila em chamas", "descricao": "Fumaça no horizonte ao norte.",
        "status": "falhou", "quem_deu": "", "recompensa": "", "cap_inicio": 2, "cap_fim": 2,
        "desfecho": "O grupo chegou tarde demais.", "objetivos": [],
    },
})


# A LOJA. O local do grupo tem que bater com o `local` da loja: é esse
# casamento que faz a tela abrir sozinha (loja é estado que persiste, e
# reabrir em toda cena só porque existe uma ferraria em outra cidade seria
# intromissão).
#
# A bolsa e o peso são escolhidos para a captura MOSTRAR a decisão: 96 po
# compram a cota de malha (50) ou a meia armadura (nem isso), e a barra de
# carga já está perto da metade, onde começa a desvantagem. Uma loja onde
# tudo cabe e tudo é barato não retrata nada.
LOJA = {
    "current_location": "Oakhaven",
    "characters": {
        "helena": {
            "sheet": {"ouro": 96, "prata": 8, "cobre": 0, "forca": 12},
            "inventario": [
                {"nome": "Espada Curta", "qtd": 2, "descricao": ""},
                {"nome": "Adaga", "qtd": 1, "descricao": ""},
                {"nome": "Armadura de Couro", "qtd": 1, "descricao": ""},
                {"nome": "Corda de Cânhamo", "qtd": 1, "descricao": "15 metros"},
            ],
        },
        "stelar": {
            "sheet": {"ouro": 240, "prata": 0, "cobre": 0, "forca": 16},
            "inventario": [{"nome": "Espada Longa", "qtd": 1, "descricao": ""}],
        },
    },
    "lojas": {
        "forja do torbin": {
            "nome": "Forja do Torbin",
            "local": "Oakhaven",
            "estoque": [
                {"nome": "Espada Longa",       "preco": 15,  "qtd": 99,
                 "descricao": ""},
                {"nome": "Machado de Batalha", "preco": 10,  "qtd": 3,
                 "descricao": ""},
                {"nome": "Escudo",             "preco": 10,  "qtd": 2,
                 "descricao": ""},
                {"nome": "Cota de Malha",      "preco": 75,  "qtd": 1,
                 "descricao": ""},
                {"nome": "Meia Armadura",      "preco": 750, "qtd": 1,
                 "descricao": ""},
                {"nome": "Martelo do Velho Torbin", "preco": 40, "qtd": 1,
                 "descricao": "o martelo do pai dele; não faz nada, é lembrança"},
            ],
        },
    },
}


# SUBIDA DE NÍVEL. A guerreira acabou de chegar ao 4 e deve TRÊS coisas: o
# estilo de combate que nunca escolheu (nível 1), o arquétipo (nível 3) e os
# dois pontos de atributo do nível 4.
#
# Três de uma vez não é exagero de cenário — é o caso comum. As duas
# primeiras ficavam pendentes para sempre porque nada as cobrava: o motor
# dizia "escolha um Estilo de Combate" no fim do texto de level-up e, se
# ninguém escolhesse, a campanha seguia sem o bônus.
NIVEL = {
    "characters": {
        "helena": {
            "sheet": {
                "classe": "guerreiro", "nivel": 4, "xp": 3100,
                "xp_proximo": 6500, "proficiencia": 2,
                "forca": 16, "destreza": 14, "constituicao": 15,
                "inteligencia": 10, "sabedoria": 12, "carisma": 8,
                "vida_max": 38, "vida_atual": 38, "ca": 16,
                "asi_pontos_gastos": 0,
                "feature_choices": {},
            },
            "habilidades": [
                {"nome": "Estilo de Combate", "descricao": "", "custo_mana": 0, "dado": ""},
                {"nome": "Segunda Fôlego", "descricao": "Recupera 1d10+nível PV.",
                 "custo_mana": 0, "dado": "1d10"},
                {"nome": "Surto de Ação", "descricao": "Uma ação extra, uma vez por descanso.",
                 "custo_mana": 0, "dado": ""},
                {"nome": "Arquétipo Marcial", "descricao": "", "custo_mana": 0, "dado": ""},
            ],
        },
        # A Stelar já resolveu as dela: serve para a tela mostrar o estado
        # "nada pendente", que é metade do que ela comunica.
        "stelar": {
            "sheet": {"classe": "guerreiro", "nivel": 3, "xp": 1200,
                      "xp_proximo": 2700, "asi_pontos_gastos": 0,
                      "feature_choices": {"Estilo de Combate": "Duelo",
                                          "Arquétipo Marcial": "Campeão"}},
            "habilidades": [
                {"nome": "Estilo de Combate", "descricao": "", "custo_mana": 0, "dado": ""},
                {"nome": "Arquétipo Marcial", "descricao": "", "custo_mana": 0, "dado": ""},
            ],
        },
    },
}


# Duas lojas no mesmo local. A tela só conhecia a primeira: o boticário era
# inalcançável. A captura mostra o seletor que resolve isso.
LOJA_DUAS = copy.deepcopy(LOJA)
LOJA_DUAS["lojas"]["boticario da mira"] = {
    "nome": "Boticário da Mira", "local": "Oakhaven",
    "estoque": [
        {"nome": "Poção de Cura", "preco": 50, "qtd": 3,
         "descricao": "recupera 2d4+2 pontos de vida"},
        {"nome": "Antídoto", "preco": 50, "qtd": 2,
         "descricao": "vantagem contra veneno por 1 hora"},
    ],
}

# Selo "NÍVEL!" da ficha: XP suficiente, nível ainda não subido, nada
# pendente. O popup não promete mais PV calculado no navegador.
NIVEL_SELO = copy.deepcopy(NIVEL)
NIVEL_SELO["characters"]["helena"]["sheet"].update({
    "nivel": 3, "xp": 2800, "xp_proximo": 2700, "asi_pontos_gastos": 0,
    "feature_choices": {"Estilo de Combate": "Defesa", "Arquétipo Marcial": "Campeão"},
})


# GRIMÓRIO. Helena, clériga de nível 3 (3 truques e 5 magias no máximo), conhece
# 2 truques e 3 magias: sobra 1 truque e 2 magias para aprender, e é por isso
# que a tela abre sozinha. As magias conhecidas cobrem três círculos para a
# coluna da direita mostrar o agrupamento.
def _magia_de_captura(nome, nivel, escola, desc, dado=""):
    custo = {0: 0, 1: 2, 2: 3}[nivel]
    return {"nome": nome, "descricao": f"[{escola}] {desc}", "custo_mana": custo,
            "dado": dado, "nivel_magia": nivel}


GRIMORIO = {
    "characters": {
        "helena": {
            "sheet": {"classe": "clérigo", "nivel": 3, "mana_atual": 14, "mana_max": 14},
            "habilidades": [
                _magia_de_captura("Chamas Sagradas", 0, "Evocação",
                                  "Chama radiante desce sobre o alvo.", "1d8"),
                _magia_de_captura("Luz", 0, "Evocação", "Objeto brilha como uma tocha."),
                _magia_de_captura("Cura Ferimentos", 1, "Evocação",
                                  "Toque cura 1d8 + modificador.", "1d8"),
                _magia_de_captura("Bênção", 1, "Encantamento",
                                  "Até três aliados somam 1d4 em ataques e saves.", "1d4"),
                _magia_de_captura("Arma Espiritual", 2, "Evocação",
                                  "Uma arma espectral golpeia como ação bônus.", "1d8"),
            ],
        },
    },
}

# Mesma Helena com as 5 magias ocupadas: só o truque ainda cabe, e a lista
# precisa mostrar o botão travado dizendo "Sem vaga de magia".
GRIMORIO_CHEIO = copy.deepcopy(GRIMORIO)
GRIMORIO_CHEIO["characters"]["helena"]["habilidades"] += [
    _magia_de_captura("Palavra Curativa", 1, "Evocação", "Cura à distância.", "1d4"),
    _magia_de_captura("Silêncio", 2, "Ilusão", "Esfera onde nenhum som existe."),
]


# MOCHILA. Stelar veste um camisão de malha (CA 14 com DES 12) e carrega uma
# cota de malha e um escudo sem usar: os botões mostram a prévia "CA 14 → 16",
# que é o que a tela existe para mostrar. Uma adaga só (não cabe nas duas
# mãos), um manto élfico nunca conferido no SRD e coisas comuns de viagem.
MOCHILA = {
    "characters": {
        "stelar": {
            "sheet": {"forca": 16, "destreza": 12, "ca": 14,
                      "ouro": 38, "prata": 6, "cobre": 0,
                      "equipamentos": {"armadura": "Camisão de Malha", "escudo": None,
                                       "arma_principal": "Espada Longa",
                                       "arma_secundaria": None, "amuleto": None}},
            "inventario": [
                {"nome": "Espada Longa", "qtd": 1, "descricao": ""},
                {"nome": "Camisão de Malha", "qtd": 1, "descricao": ""},
                {"nome": "Cota de Malha", "qtd": 1, "descricao": "tirada do cavaleiro caído"},
                {"nome": "Escudo", "qtd": 1, "descricao": ""},
                {"nome": "Adaga", "qtd": 1, "descricao": ""},
                {"nome": "Manto Élfico", "qtd": 1,
                 "descricao": "tecido cinza que muda de tom com a luz"},
                {"nome": "Poção de Cura", "qtd": 2, "descricao": "recupera 2d4+2 PV"},
                {"nome": "Tocha", "qtd": 5, "descricao": ""},
                {"nome": "Corda de Cânhamo", "qtd": 1, "descricao": "15 metros"},
            ],
        },
    },
}

# A mesma mochila numa Stelar de Força 8: capacidade de 54 kg, metade em 27 —
# a cota de malha que ela carregou do campo de batalha a deixa sobrecarregada.
MOCHILA_PESADA = copy.deepcopy(MOCHILA)
MOCHILA_PESADA["characters"]["stelar"]["sheet"]["forca"] = 8


# CIDADE. O grupo está na Praça de Cliviate, que fica dentro da cidade; a Forja
# e o Boticário (lojas de Cliviate) ficam ao lado. O grupo NÃO está no local
# das lojas de propósito: senão a tela de loja abriria sozinha por cima da
# ficha do local. A Floresta é longe — sem "Ir até lá".
def _npc(nome, descricao, local, status="vivo"):
    return {"name": nome, "description": descricao, "traits": "", "status": status,
            "notes": "", "local": local, "sheet": None, "inventario": [], "habilidades": []}


CIDADE = {
    "current_location": "Praça de Cliviate",
    "locations": {
        "cliviate": {"name": "Cliviate", "details": "", "notes": "",
                     "description": "Cidade de muralhas baixas de pedra na borda da floresta. "
                                    "Cheira a fumaça de chaminé e pão assado."},
        "praça de cliviate": {"name": "Praça de Cliviate", "dentro_de": "Cliviate",
                              "details": "", "notes": "",
                              "description": "Uma praça de pedras irregulares em volta de um poço antigo."},
        "taverna do caldeirão": {"name": "Taverna do Caldeirão", "dentro_de": "Cliviate",
                                 "details": "", "notes": "",
                                 "description": "Mesas compridas, um caldeirão de ensopado sempre no fogo."},
        "floresta das brumas": {"name": "Floresta das Brumas", "details": "", "notes": "",
                                "description": "Neblina que não se desfaz nem ao meio-dia."},
    },
    "lojas": {
        "forja de cliviate": {"nome": "Forja de Cliviate", "local": "Cliviate",
                              "estoque": [{"nome": "Espada Longa", "preco": 15, "qtd": 99, "descricao": ""}]},
        "boticario da mira": {"nome": "Boticário da Mira", "local": "Cliviate",
                              "estoque": [{"nome": "Poção de Cura", "preco": 50, "qtd": 3, "descricao": ""}]},
    },
    "characters": {
        # Brom tem ficha cheia: atitude com o porquê, o que o grupo sabe, a
        # missão que deu e os eventos em que aparece. As notas são segredo do
        # mestre e não podem aparecer na ficha do personagem.
        "brom": {**_npc("Brom", "Ferreiro corpulento, braços cobertos de fuligem.", "Forja de Cliviate"),
                 "traits": "Desconfiado com forasteiros, leal a quem cumpre a palavra.",
                 "notes": "SEGREDO: forja as lâminas dos bandidos da estrada em troca do filho.",
                 "atitude": 35,
                 "atitude_historico": [
                     {"delta": -10, "motivo": "Lyra pechinchou demais pela espada", "cap": 1},
                     {"delta": 25, "motivo": "O grupo trouxe o martelo do avô de volta", "cap": 2},
                     {"delta": 20, "motivo": "Alden defendeu a forja dos guardas", "cap": 2},
                 ],
                 "conhecido": ["O filho dele sumiu na estrada do norte",
                               "Aprendeu o ofício com o avô, em Oakhaven"]},
        "mira": _npc("Mira", "Boticária de óculos redondos e mãos manchadas de ervas.", "Boticário da Mira"),
        "tiel": _npc("Guarda Tiel", "Guarda da praça, entediado e atento a forasteiros.", "Praça de Cliviate"),
        "velha nana": _npc("Velha Nana", "Vende maçãs e segredos por uma moeda de cobre.", "Praça de Cliviate"),
        "eremita": _npc("Eremita", "Vive na neblina e não gosta de visitas.", "Floresta das Brumas"),
    },
    "quests": {
        "o filho do ferreiro": {"titulo": "O filho do ferreiro", "status": "ativa",
                                "descricao": "Encontrar o filho de Brom na estrada do norte.",
                                "objetivos": [], "quem_deu": "brom", "recompensa": "Uma espada sob medida",
                                "cap_inicio": 2},
    },
    "events": [
        {"summary": "O grupo devolveu o martelo do avô a Brom.", "characters_involved": "Brom, Lyra, Alden",
         "location": "Forja de Cliviate", "consequence": ""},
        {"summary": "Guardas tentaram fechar a forja por dívida de impostos.", "characters_involved": "Brom; Guarda Tiel",
         "location": "Forja de Cliviate", "consequence": ""},
    ],
}


# MAPA DO MUNDO. A cidade de CIDADE com um nível a mais (o porão dentro da
# taverna), alguém sem paradeiro e um porto citado mas nunca registrado.
MAPA = copy.deepcopy(CIDADE)
MAPA["locations"]["porão da taverna"] = {
    "name": "Porão da Taverna", "dentro_de": "Taverna do Caldeirão", "details": "", "notes": "",
    "description": "Barris, teias e uma porta trancada no fundo."}
MAPA["characters"].update({
    "velho osric": _npc("Velho Osric", "Contrabandista aposentado.", "Porão da Taverna", status="morto"),
    "andarilho": _npc("Andarilho", "Aparece e some sem aviso.", ""),
    "pescador": _npc("Pescador Ivo", "Diz que viu luzes no mar.", "Porto de Vhar"),
})

# SAQUE depois da emboscada. A cota de malha é a escolha: pesa 25 kg, e com
# ela a Helena (FOR 10, sobrecarregada acima de 34 kg) passa da metade da
# capacidade. Só com o que ela carrega no temp.json (6,9 kg) a cota a deixava
# em 31,9 kg, ainda livre, e a captura saque-divisao nunca achava o estado
# piorando: por isso ela leva também o relicário do templo.
SAQUE = {
    "combat_state": {"is_active": False, "initiative_order": []},
    "characters": {
        "helena": {"inventario": [
            {"nome": "armadura de couro batido", "qtd": 1,
             "descricao": "Sedas sagradas sobrepostas com couro leve protetor."},
            {"nome": "Cajado de Madeira Rúnica", "qtd": 1, "descricao": "Canalizador divino."},
            {"nome": "Pingente de Cristal da Alvorada", "qtd": 1,
             "descricao": "Brilha conforme suas emoções."},
            {"nome": "Relicário do Templo", "qtd": 1, "peso": 4,
             "descricao": "Caixa de bronze com as relíquias de Lathander."},
        ]},
    },
    "saque_proposto": {
        "id": 7, "origem": "os bandidos da estrada", "moedas_para": "igual",
        "proximo_item": 4,
        "moedas": {"ouro": 25, "prata": 8, "cobre": 0},
        "itens": [
            {"id": 1, "nome": "Cota de Malha", "qtd": 1, "descricao": "tirada do chefe dos bandidos",
             "peso": 24.95, "divisao": {}},
            {"id": 2, "nome": "Poção de Cura", "qtd": 2, "descricao": "", "peso": 0.25, "divisao": {}},
            {"id": 3, "nome": "Adaga", "qtd": 1, "descricao": "", "peso": 0.45, "divisao": {}},
        ],
    },
}


# FICHA DO HERÓI. Stelar é um Campeão de Grande Arma com XP para subir:
# o ataque mostra as notas do estilo e do crítico, e o botão de nível aparece.
# Helena está envenenada e concentrada em Bênção, com PV temporários.
HEROI = {
    "characters": {
        "stelar": {
            "habilidades": [
                {"nome": "Crítico Aprimorado", "descricao": "Acerto crítico com 19 ou 20 no d20.",
                 "custo_mana": 0, "dado": ""},
                {"nome": "Retomar o Fôlego", "descricao": "Ação bônus: recupera 1d10 + nível de PV. Uma vez por descanso.",
                 "custo_mana": 0, "dado": "1d10"},
            ],
            "sheet": {"xp": 2700, "feature_choices": {"Estilo de Combate": "Grande Arma"},
                      "equipamentos": {"arma_principal": "Espada Grande"}},
        },
        "helena": {
            "sheet": {"condicoes": [{"nome": "envenenado", "duracao": 2}],
                      "concentracao": {"magia": "Bênção"}, "vida_temp": 4},
        },
    },
}


# VISÃO GERAL DO GRUPO. O que a tela ajuda a decidir, um de cada:
#   • Helena ferida, envenenada e sem dado de vida: só o descanso longo a cura;
#   • Stelar ferido com dados sobrando (o curto ajuda), XP para subir de nível
#     e sem poder dormir de novo (descansou há 10 horas);
#   • Natasha com a vida cheia e a mochila perto do limite de carga.
GRUPO = {
    "relogio": {"dia": 4, "hora": 20},
    "characters": {
        "helena":  {"sheet": {"vida_atual": 9, "mana_atual": 6, "hit_dice_remaining": 0,
                              "condicoes": [{"nome": "envenenado", "duracao": 2}]}},
        "stelar":  {"sheet": {"vida_atual": 18, "xp": 2700, "hit_dice_remaining": 2,
                              "ultimo_descanso_longo": 4 * 24 + 10}},
        "natasha": {"sheet": {"vida_atual": 21},
                    "inventario": [
                        {"nome": "Baú de Ferramentas", "qtd": 1, "descricao": "", "peso": 28},
                        {"nome": "Adaga", "qtd": 2, "descricao": ""},
                    ]},
    },
}

# O DIÁRIO COMO LIVRO. As entradas e os eventos do temp.json, com o capítulo de
# cada evento (os gravados antes da regra não tinham). O quarto fica sem
# capítulo de propósito: é a página "Sem capítulo". A audiência real começou
# no capítulo 2, para a página dele mostrar a missão.
DIARIO = {
    "chapter": 2,
    "events": [
        {"index": 1, "chapter": 1,
         "summary": "O Duelo das Pétalas: Elowen humilha Kaelen ao transformar seu ataque de plasma "
                    "azul em uma explosão de jasmins e cerejeiras.",
         "characters_involved": "Elowen, Kaelen, Helena, Stelar", "location": "Planícies Queimadas",
         "consequence": "Elowen atrai a atenção indesejada dos altos escalões de Luminas."},
        {"index": 2, "chapter": 2,
         "summary": "O Recrutamento das Sombras: Natasha intercepta o grupo na estrada.",
         "characters_involved": "Elowen, Natasha, Helena, Stelar", "location": "Estrada para Luminas",
         "consequence": "Natasha entra no grupo, e com ela a tensão entre as companheiras."},
        {"index": 3, "chapter": 2,
         "summary": "O Teste de Infiltração: Natasha invade a Villa Ravenhurst durante a noite.",
         "characters_involved": "Natasha, Helena, Stelar, Elowen", "location": "Villa Ravenhurst",
         "consequence": "Stelar e Helena passam a treinar com Natasha."},
        {"index": 4,
         "summary": "O Reconhecimento Real: a Princesa Elara para a carruagem diante de Elowen.",
         "characters_involved": "Elowen, Princesa Elara, Helena, Stelar, Natasha",
         "location": "Avenida dos Mil Sóis",
         "consequence": "O grupo recebe um convite para uma audiência privada."},
    ],
    "quests": {
        "a audiencia real": {"titulo": "A audiência real", "status": "ativa",
                             "descricao": "Comparecer à audiência privada com a Princesa Elara.",
                             "objetivos": [], "quem_deu": "Princesa Elara", "recompensa": "",
                             "cap_inicio": 2},
    },
}

# DESCANSO CURTO depois de uma emboscada. Cada um do grupo retrata um estado do
# botão de dado, porque é isso que a tela comunica:
#   • Helena, muito ferida e com a reserva cheia — o caso de gastar;
#   • Stelar, já gastou um dado AGORA e tem só mais um — o caso de guardar;
#   • Natasha, com a vida cheia — o botão travado dizendo por quê.
# O mestre abriu o descanso (offer_rest), então não há `js` para abrir a tela.
_HORA_DESCANSO = 4 * 24 + 16
DESCANSO_CURTO = {
    "relogio": {"dia": 4, "hora": 16},
    "descansos_oferecidos": 7,
    "descanso_proposto": {
        "id": 7, "tipo": "curto", "hora": _HORA_DESCANSO,
        "motivo": "à sombra das ruínas, depois da emboscada",
        "gastos": {"Stelar": 1},
    },
    "characters": {
        "helena":  {"sheet": {"vida_atual": 6,  "hit_dice_remaining": 3}},
        "stelar":  {"sheet": {"vida_atual": 18, "hit_dice_remaining": 1}},
        "natasha": {"sheet": {"vida_atual": 21, "hit_dice_remaining": 2}},
    },
}

# DESCANSO LONGO com as duas coisas que a tela precisa deixar claras: quem NÃO
# pode dormir ainda (Stelar descansou há 15 horas) e o que a noite devolve a
# quem pode — inclusive um nível de exaustão.
DESCANSO_LONGO = {
    "relogio": {"dia": 4, "hora": 22},
    "descansos_oferecidos": 8,
    "descanso_proposto": {
        "id": 8, "tipo": "longo", "hora": 4 * 24 + 22,
        "motivo": "na estalagem do Passo de Vhar", "gastos": {},
    },
    "characters": {
        "helena":  {"sheet": {"vida_atual": 9, "mana_atual": 6,
                              "hit_dice_remaining": 0, "exaustao": 2}},
        "stelar":  {"sheet": {"vida_atual": 25, "ultimo_descanso_longo": 4 * 24 + 7}},
        "natasha": {"sheet": {"vida_atual": 12, "hit_dice_remaining": 1}},
    },
}


# Combate COM ZONAS (onda 3): o campo dividido em trilha, cada um em sua zona.
COMBATE_ZONAS = copy.deepcopy(COMBATE_ATIVO)
COMBATE_ZONAS["characters"]["natasha"] = {"sheet": {"vida_atual": 21}}
COMBATE_ZONAS["combat_state"].update({
    "zonas": ["Portão", "Pátio", "Sacada"],
    "zona_desc": {
        "Portão":  "portas de ferro arrombadas",
        "Pátio":   "lama, barris tombados",
        "Sacada":  "arqueiros no alto",
    },
    "posicoes": {
        "stelar":   "Pátio",
        "helena":   "Portão",
        "natasha":  "Portão",
        "victoria": "Sacada",
    },
    "turn_economy": {"acao_usada": False, "bonus_usada": False,
                     "movimento_usado": False},
})

# ITENS NA TELA TÁTICA. Stelar no Pátio com uma poção, um frasco de ácido, uma
# água benta e um item que o motor não conhece. Helena e Natasha no Portão
# (vizinho): a poção não chega a elas, o ácido chega. Victoria na Sacada
# (vizinha): o ácido chega; a água benta não faz nada nela, que não é morta-viva.
COMBATE_ITENS = copy.deepcopy(COMBATE_ZONAS)
COMBATE_ITENS["characters"]["stelar"] = {
    "sheet": {"vida_atual": 19},
    "inventario": [
        {"nome": "Poção de Cura", "qtd": 2, "descricao": "2d4+2 PV"},
        {"nome": "Frasco de Ácido", "qtd": 1, "descricao": ""},
        {"nome": "Água Benta", "qtd": 1, "descricao": ""},
        {"nome": "Poção de Força de Gigante", "qtd": 1, "descricao": ""},
    ],
}


# Painel de fim de combate (vitória do grupo).
COMBATE_ENCERRADO = copy.deepcopy(COMBATE_ATIVO)
COMBATE_ENCERRADO["combat_state"].update({
    "is_active": False,
    "result": {
        "outcome": "vitoria",
        "title": "Vitória!",
        "sobreviventes": [
            {"name": "Stelar", "is_party": True, "hp": 19, "hp_max": 31, "status": "vivo"},
            {"name": "Helena", "is_party": True, "hp": 14, "hp_max": 21, "status": "vivo"},
            {"name": "Natasha", "is_party": True, "hp": 21, "hp_max": 21, "status": "vivo"},
        ],
        "caidos": [
            {"name": "Victoria", "is_party": False, "hp": 0, "hp_max": 38, "status": "inconsciente"},
        ],
    },
})

# Combate narrado: não abre a tela tática, mas acende a régua de turnos.
COMBATE_NARRADO = {
    "combat_mode": "narrado",
    "combat_state": {
        "is_active": True,
        "initiative_order": ["Stelar", "Victoria", "Helena", "Natasha"],
        "current_turn_index": 1,
        "round": 2,
    },
}


# ═══════════════════════════════════════════════════════════════════════
#  Roteiro das telas
# ═══════════════════════════════════════════════════════════════════════
#
#  nome     nome do arquivo (sem extensão)
#  pagina   rota a abrir
#  estado   patch de campanha aplicado ANTES de carregar a página
#  js       JavaScript rodado depois do carregamento (abre modal, aba…)
#  estado2  segundo patch, aplicado depois do js (para transições)
#  js2      JavaScript rodado depois do estado2
#  espera   ms extras antes do clique do obturador
#  viewport restringe a um viewport ("desktop" ou "mobile")
#  bloquear lista de padrões de URL que a página não deve conseguir buscar
#  carregar critério do goto ("networkidle" por padrão)
#  exigir   seletor que precisa estar visível antes do print. Sem isso, um
#           modal que silenciosamente não abriu viraria um print da tela de
#           trás — parecendo certo e mentindo. Com isso, a tela falha e diz.

_ABRIR_FICHA_NO_EDITOR_DA_CAMPANHA = """
    (async () => {
      await openEditCampaign(new Event('click'), window.__campanha);
      editGoTo(2);
      const i = edChars.findIndex(c => (c.name || '').toLowerCase() === 'helena');
      edChars[i]._open = true;
      edRenderChars();
      if (%s) document.querySelector('#ed-dnd-sections-' + i + ' input.ed-correcao').click();
      setTimeout(() => document.querySelector('#ed-dnd-sections-' + i)
        .scrollIntoView({block: 'start'}), 150);
    })()
"""

TELAS = [
    # ── Login ────────────────────────────────────────────────────────
    {"nome": "login-entrar", "pagina": "/login.html"},
    {"nome": "login-criar-conta", "pagina": "/login.html",
     "js": "switchTab('register')"},
    {"nome": "login-erro", "pagina": "/login.html",
     "js": "document.getElementById('auth-error').textContent = "
           "'Email ou senha incorretos.'; "
           "document.getElementById('auth-error').style.display = 'block';"},
    {"nome": "login-dialogo", "pagina": "/login.html",
     "exigir": "#dialog-overlay:not(.hidden)",
     "js": "showAlert('Conta criada', 'Confirme seu email antes de entrar.', 'info')"},

    # ── Menu ─────────────────────────────────────────────────────────
    {"nome": "menu-lista", "pagina": "/menu.html"},
    {"nome": "menu-campanha-selecionada", "pagina": "/menu.html",
     "js": "document.querySelector('.campaign-item').click()"},
    {"nome": "menu-wizard-1-mundo", "pagina": "/menu.html",
     "exigir": "#wizard-overlay:not(.hidden)",
     "js": "openWizard()"},
    {"nome": "menu-wizard-1-ia", "pagina": "/menu.html",
     "exigir": "#wizard-overlay:not(.hidden)",
     "js": "openWizard(); document.getElementById('wz-ai-toggle').click();"},
    {"nome": "menu-wizard-1-preenchido", "pagina": "/menu.html",
     "exigir": "#wizard-overlay:not(.hidden)",
     "js": """
        openWizard();
        document.getElementById('wz-name').value = 'A Coroa Partida';
        document.getElementById('wz-type').value = 'dnd';
        onWizardTypeChange();
        document.getElementById('wz-summary').value =
          'O reino de Oakhaven perdeu seu herdeiro. Tres mercenarios aceitam '
          + 'escoltar a princesa ate a capital antes que a coroa seja fundida.';
        document.getElementById('wz-scene').value =
          'Uma taverna encharcada de chuva, na fronteira das Planicies Queimadas.';
        document.getElementById('wz-location').value = 'Oakhaven';
        wizardValidate();
     """},
    {"nome": "menu-wizard-2-personagens", "pagina": "/menu.html",
     "exigir": "#wizard-overlay:not(.hidden)",
     "js": """
        openWizard();
        document.getElementById('wz-name').value = 'A Coroa Partida';
        wizardValidate();
        wizardGoTo(2);
     """},
    {"nome": "menu-importar", "pagina": "/menu.html",
     "exigir": "#import-overlay:not(.hidden)",
     "js": "openImportModal()"},
    {"nome": "menu-editar-campanha", "pagina": "/menu.html",
     "js": "openEditCampaign(new Event('click'), window.__campanha)",
     "espera": 900, "exigir": "#edit-overlay:not(.hidden)"},
    # Ficha em jogo no editor da campanha: construção travada, com o aviso de
    # qual tela cuida de cada coisa. E a mesma ficha no Modo de correção.
    {"nome": "menu-editar-ficha-travada", "pagina": "/menu.html",
     "js": _ABRIR_FICHA_NO_EDITOR_DA_CAMPANHA % "false",
     # Os personagens fechados também têm o aviso, escondido: só o visível serve.
     "espera": 900, "exigir": ".ed-aviso-regras >> visible=true"},
    {"nome": "menu-editar-ficha-correcao", "pagina": "/menu.html",
     "js": _ABRIR_FICHA_NO_EDITOR_DA_CAMPANHA % "true",
     "espera": 900, "exigir": ".ed-aviso-correcao"},
    {"nome": "menu-confirmar", "pagina": "/menu.html",
     "exigir": "#dialog-overlay:not(.hidden)",
     "js": "deleteCampaign(new Event('click'), window.__campanha)"},
    {"nome": "menu-configuracoes", "pagina": "/menu.html",
     "exigir": "#settings-panel.open",
     "js": "toggleSettingsPanel()"},
    {"nome": "menu-guia", "pagina": "/menu.html",
     "exigir": "#guide-overlay",
     "js": "openGuide()"},

    # ── Jogo ─────────────────────────────────────────────────────────
    {"nome": "jogo-mundo", "pagina": "/game.html"},
    {"nome": "jogo-enciclopedia", "pagina": "/game.html",
     "js": "switchTab('enciclopedia')"},
    {"nome": "jogo-diario", "pagina": "/game.html",
     "js": "switchTab('diario')"},
    {"nome": "jogo-bandeja-dados", "pagina": "/game.html",
     "js": "toggleDiceTray()"},
    {"nome": "jogo-menu-comandos", "pagina": "/game.html",
     "js": "document.getElementById('chat-input').value = '/'; openCmdMenu('');"},
    {"nome": "jogo-modal-personagem", "pagina": "/game.html",
     "exigir": "#edit-overlay:not(.hidden)",
     "js": "openEditModal('character', 'stelar', window._lastMem.party[1])"},
    # A ficha D&D fica abaixo da dobra do modal: sem rolar, as duas capturas
    # seriam o topo do modal, iguais à de cima.
    {"nome": "jogo-modal-ficha-travada", "pagina": "/game.html",
     "exigir": "#edit-body .ed-aviso-regras", "espera": 500,
     "js": "openEditModal('character', 'stelar', window._lastMem.party[1])"
           ".then(() => document.querySelector('#edit-body .ed-correcao-toggle')"
           ".scrollIntoView({block: 'start'}))"},
    {"nome": "jogo-modal-ficha-correcao", "pagina": "/game.html",
     "exigir": "#edit-body .ed-aviso-correcao", "espera": 500,
     "js": "openEditModal('character', 'stelar', window._lastMem.party[1])"
           ".then(() => { document.querySelector('#edit-body input.ed-correcao').click();"
           " setTimeout(() => document.querySelector('#edit-body .ed-correcao-toggle')"
           ".scrollIntoView({block: 'start'}), 100); })"},
    {"nome": "jogo-modal-mundo", "pagina": "/game.html",
     "exigir": "#edit-overlay:not(.hidden)",
     "js": "openWorldEdit()"},
    {"nome": "jogo-modal-local", "pagina": "/game.html",
     "exigir": "#edit-overlay:not(.hidden)",
     "js": "switchTab('enciclopedia'); "
           "openEditModal('location', 'oakhaven', window._lastMem.locations[0]);"},
    {"nome": "jogo-modal-diario", "pagina": "/game.html",
     "exigir": "#edit-overlay:not(.hidden)",
     "js": "switchTab('diario'); "
           "openEditModal('diary', null, window._lastMem.diary[0], 0);"},
    {"nome": "jogo-configuracoes", "pagina": "/game.html",
     "exigir": "#settings-panel.open",
     "js": "toggleSettingsPanel()"},
    {"nome": "jogo-guia", "pagina": "/game.html",
     "exigir": "#guide-overlay",
     "js": "openGuide()"},
    {"nome": "jogo-sidebar-mobile", "pagina": "/game.html",
     "js": "toggleSidebar()", "viewport": "mobile"},

    {"nome": "jogo-missoes-e-tempo", "pagina": "/game.html",
     "estado": MUNDO_ONDA4, "espera": 900,
     # Duas coisas atrapalhavam o print. No MOBILE a lateral é uma gaveta
     # fechada — sem abrir, a captura chamada "missões" saía sem nenhuma
     # missão à vista. E no desktop o painel nasce abaixo da dobra da
     # lateral, que tem rolagem própria.
     # 900px é o mesmo corte que o game.js usa para decidir se a lateral é
     # gaveta (ver toggleSidebar(true) ao abrir um modal).
     "js": "if (window.innerWidth <= 900) toggleSidebar();"
           "setTimeout(() => document.getElementById('sb-missoes-secao')"
           ".scrollIntoView({block:'center'}), 250)",
     "exigir": "#sb-missoes-secao:not(.hidden)"},

    # ── Loja ─────────────────────────────────────────────────────────
    # A tela abre SOZINHA quando o grupo entra num local que tem loja, então
    # não há `js` para abri-la: se precisasse de um, o gatilho estaria
    # quebrado e a captura não denunciaria.
    {"nome": "loja-balcao", "pagina": "/game.html",
     "estado": LOJA, "espera": 700,
     "exigir": "#shop-overlay:not(.hidden)"},
    {"nome": "loja-vender", "pagina": "/game.html",
     "estado": LOJA, "espera": 700,
     "js": "window.Shop._aba('vender')",
     "exigir": "#shop-overlay:not(.hidden)"},
    {"nome": "loja-fechada-pilula", "pagina": "/game.html",
     "estado": LOJA, "espera": 700,
     "js": "window.Shop._close()",
     "exigir": "#shp-reopen:not(.hidden)"},
    {"nome": "loja-duas-no-local", "pagina": "/game.html",
     "estado": LOJA_DUAS, "espera": 700,
     "exigir": ".shp-loja-sel"},

    # ── Subida de nível ──────────────────────────────────────────────
    # Sem `js` para abrir: o gatilho automático (alguém está devendo escolha)
    # É a feature, e uma captura que precisasse de empurrão não denunciaria
    # se ele quebrasse.
    {"nome": "nivel-ascensao", "pagina": "/game.html",
     "estado": NIVEL, "espera": 700,
     "exigir": "#levelup-overlay:not(.hidden)"},
    {"nome": "nivel-incremento-atributo", "pagina": "/game.html",
     "estado": NIVEL, "espera": 700,
     # Um ponto já posto em Força: o print precisa mostrar o stepper NO MEIO
     # do uso — o − habilitado só onde há ponto do rascunho, a linha "16 +1"
     # e o Confirmar ainda bloqueado pedindo o segundo ponto. Uma captura com
     # tudo zerado não mostraria nenhuma dessas três coisas.
     # Rola até o bloco, que nasce abaixo da dobra.
     "js": "window.LevelUp._passo('forca', 1);"
           "setTimeout(() => document.querySelector('.lvl-bloco-asi')"
           ".scrollIntoView({block:'center'}), 150)",
     "exigir": ".lvl-step-alterado"},
    {"nome": "nivel-sem-pendencia", "pagina": "/game.html",
     "estado": NIVEL, "espera": 700,
     "js": "window.LevelUp._trocar('Stelar')",
     "exigir": ".lvl-ok"},
    {"nome": "nivel-selo-da-ficha", "pagina": "/game.html",
     "estado": NIVEL_SELO, "espera": 400,
     # O selo mora no cartão do grupo, na aba Enciclopédia.
     "js": "switchTab('enciclopedia');"
           "setTimeout(() => document.querySelector('.levelup-badge').click(), 300)",
     "exigir": "#levelup-popup"},

    # ── Grimório ─────────────────────────────────────────────────────
    # Aqui há `js` para abrir, ao contrário das outras telas: o Grimório só
    # abre sozinho quando surge vaga NOVA desde a última visita, e cada
    # captura começa com a memória das telas limpa — para ele, é a primeira
    # visita, que mostra só a pílula. O gatilho automático é coberto por
    # test_grimorio_navegador.py.
    {"nome": "grimorio", "pagina": "/game.html",
     "estado": GRIMORIO, "espera": 1200,
     "js": "window.Grimoire._abrir()",
     "exigir": ".grm-magia"},
    {"nome": "grimorio-magia-aprendida", "pagina": "/game.html",
     "estado": GRIMORIO, "espera": 1400,
     # Aprende a primeira magia livre da lista: o print mostra a mensagem do
     # motor no rodapé e a vaga descontada no cabeçalho.
     "js": "window.Grimoire._abrir();"
           "setTimeout(() => { const b = [...document.querySelectorAll('.grm-aprender-btn')]"
           ".find(x => !x.disabled); if (b) b.click(); }, 900)",
     "exigir": "#grm-msg:not(:empty)"},
    {"nome": "grimorio-sem-vaga-de-magia", "pagina": "/game.html",
     "estado": GRIMORIO_CHEIO, "espera": 1600,
     # Filtra o 1º círculo: é onde o botão travado "Sem vaga de magia" aparece
     # (a lista começa pelos truques, que ainda cabem).
     "js": "window.Grimoire._abrir(); setTimeout(() => window.Grimoire._filtro(1), 900)",
     "exigir": ".grm-magia"},
    {"nome": "grimorio-fechado-pilula", "pagina": "/game.html",
     "estado": GRIMORIO, "espera": 900,
     "js": "window.Grimoire._abrir(); setTimeout(() => window.Grimoire._close(), 500)",
     "exigir": "#grm-reopen:not(.hidden)"},

    # ── Mochila ──────────────────────────────────────────────────────
    # Não abre sozinha (nada no mundo pede "arrume a mochila"): o `js` faz o
    # que o atalho do cartão do grupo faz.
    {"nome": "mochila", "pagina": "/game.html",
     "estado": MOCHILA, "espera": 900,
     "js": "window.Inventory._abrir('Stelar')",
     "exigir": ".inv-item"},
    {"nome": "mochila-armadura-trocada", "pagina": "/game.html",
     "estado": MOCHILA, "espera": 1200,
     # Veste a cota de malha: o print mostra a CA nova no cabeçalho, a linha
     # "CA 14 → 16" no rodapé e o camisão de volta à mochila com a prévia.
     "js": "window.Inventory._abrir('Stelar');"
           "setTimeout(() => window.Inventory._equipar('Cota de Malha', 'armadura'), 700)",
     "exigir": "#inv-msg:not(:empty)"},
    {"nome": "mochila-sobrecarregada", "pagina": "/game.html",
     "estado": MOCHILA_PESADA, "espera": 900,
     "js": "window.Inventory._abrir('Stelar')",
     "exigir": ".inv-carga-cheia"},

    # ── Descanso ─────────────────────────────────────────────────────
    # Abre sozinha pela proposta do mestre, como a loja e o nível.
    {"nome": "descanso-curto", "pagina": "/game.html",
     "estado": DESCANSO_CURTO, "espera": 700,
     "exigir": "#rest-overlay:not(.hidden)"},
    {"nome": "descanso-curto-dado-gasto", "pagina": "/game.html",
     "estado": DESCANSO_CURTO, "espera": 900,
     # A Helena gasta um dado: o print mostra a rolagem no rodapé, um marcador
     # esvaziado e o "Não descansar" travado (já há dado gasto).
     "js": "setTimeout(() => window.Rest._dado('Helena'), 200)",
     "exigir": ".rst-card[data-nome='Helena'] .rst-gastos:not(:empty)"},
    {"nome": "descanso-longo", "pagina": "/game.html",
     "estado": DESCANSO_LONGO, "espera": 700,
     "exigir": "#rest-overlay:not(.hidden)"},
    {"nome": "descanso-fechado-pilula", "pagina": "/game.html",
     "estado": DESCANSO_CURTO, "espera": 700,
     "js": "window.Rest._close()",
     "exigir": "#rst-reopen:not(.hidden)"},

    # ── Ficha do local ───────────────────────────────────────────────
    # Abre pelo clique no local (Enciclopédia ou "Local:" da barra lateral).
    # A cidade vista da praça: lojas e taverna ao lado, com "Ir até lá".
    {"nome": "local-cidade", "pagina": "/game.html",
     "estado": CIDADE, "espera": 800,
     "js": "window.Locais._abrir('Cliviate')",
     "exigir": "#local-overlay:not(.hidden) .lcl-item"},
    # Onde o grupo está: o grupo em destaque e quem mais está na praça.
    {"nome": "local-onde-o-grupo-esta", "pagina": "/game.html",
     "estado": CIDADE, "espera": 800,
     "js": "window.Locais._abrir('')",
     "exigir": "#local-overlay:not(.hidden) .lcl-grupo-nome"},
    # A forja: quem trabalha lá, com "Falar com".
    {"nome": "local-loja", "pagina": "/game.html",
     "estado": CIDADE, "espera": 800,
     "js": "window.Locais._abrir('Forja de Cliviate')",
     "exigir": "#local-overlay:not(.hidden) .lcl-item"},

    # ── Ficha do personagem ──────────────────────────────────────────
    # Abre pelo cartão da Enciclopédia ou pelo "Ver ficha" na ficha do local.
    # Brom: a relação com o grupo e o porquê, o que o grupo sabe, a missão
    # que deu e os eventos. Está ao lado da praça: "Falar com" e "Ir até".
    {"nome": "personagem-ficha", "pagina": "/game.html",
     "estado": CIDADE, "espera": 800,
     "js": "window.Personagens._abrir('Brom')",
     "exigir": "#pessoa-overlay:not(.hidden) .psn-atitude"},
    # Longe do grupo e sem histórico: "Falar com" travado, listas vazias.
    {"nome": "personagem-longe", "pagina": "/game.html",
     "estado": CIDADE, "espera": 800,
     "js": "window.Personagens._abrir('Eremita')",
     "exigir": "#pessoa-overlay:not(.hidden) .psn-atitude"},

    # ── Mapa do mundo ────────────────────────────────────────────────
    # Abre pelo "Ver o mapa" da barra lateral. O caminho até a praça aberto,
    # o que está a um passo e quem está em cada lugar.
    {"nome": "mapa-mundo", "pagina": "/game.html",
     "estado": MAPA, "espera": 800,
     "js": "window.Mapa._abrir('')",
     "exigir": "#mapa-overlay:not(.hidden) .map-no-grupo"},
    # Busca por pessoa: só o ramo onde o Brom está, aberto e destacado.
    {"nome": "mapa-busca", "pagina": "/game.html",
     "estado": MAPA, "espera": 800,
     "js": "window.Mapa._abrir('').then(() => { document.getElementById('map-busca').value = 'Brom';"
           " window.Mapa._buscar('Brom'); })",
     "exigir": "#mapa-overlay:not(.hidden) .map-pessoa.map-casou"},

    # ── Visão geral do grupo ─────────────────────────────────────────
    # Abre pelo "Visão geral" do título do grupo na barra lateral.
    {"nome": "grupo-visao-geral", "pagina": "/game.html",
     "estado": GRUPO, "espera": 800,
     "js": "window.Grupo._abrir()",
     "exigir": "#grupo-overlay:not(.hidden) .grp-cartao"},

    # ── O diário como livro ──────────────────────────────────────────
    # Abre pelo "Ler o diário" da aba Diário. O capítulo 2 com as entradas,
    # os eventos, os personagens, os locais e a missão que começou nele.
    {"nome": "diario-capitulo", "pagina": "/game.html",
     "estado": DIARIO, "espera": 800,
     "js": "window.Diario._abrir(2)",
     "exigir": "#diario-overlay:not(.hidden) .dia-entrada"},
    # Os eventos gravados antes de o capítulo ser guardado, com "Pôr no capítulo".
    {"nome": "diario-sem-capitulo", "pagina": "/game.html",
     "estado": DIARIO, "espera": 800,
     "js": "window.Diario._abrir('sem')",
     "exigir": "#diario-overlay:not(.hidden) .dia-mover"},

    # ── Índice de personagens ────────────────────────────────────────
    # Todos os personagens, o grupo e quem está na praça primeiro.
    {"nome": "personagens-indice", "pagina": "/game.html",
     "estado": MAPA, "espera": 800,
     "js": "window.Elenco._abrir('todos')",
     "exigir": "#elenco-overlay:not(.hidden) .elc-cartao"},
    # Filtro "Aqui": quem está no mesmo lugar que o grupo.
    {"nome": "personagens-aqui", "pagina": "/game.html",
     "estado": MAPA, "espera": 800,
     "js": "window.Elenco._abrir('aqui')",
     "exigir": "#elenco-overlay:not(.hidden) .elc-cartao"},

    # ── Missões ──────────────────────────────────────────────────────
    # Abre pelo "Ver todas" das missões na barra lateral.
    {"nome": "missoes-ativas", "pagina": "/game.html",
     "estado": MISSOES, "espera": 900,
     "js": "window.Missoes._abrir('')",
     "exigir": "#missoes-overlay:not(.hidden) .msn-cartao"},
    {"nome": "missoes-encerradas", "pagina": "/game.html",
     "estado": MISSOES, "espera": 900,
     "js": "window.Missoes._abrir('Ratos no porão')",
     "exigir": "#missoes-overlay:not(.hidden) .msn-concluida"},

    # ── Saque ────────────────────────────────────────────────────────
    # Abre sozinha pela fila, com tudo no chão.
    {"nome": "saque-no-chao", "pagina": "/game.html",
     "estado": SAQUE, "espera": 900,
     "exigir": "#loot-overlay:not(.hidden) .lot-item"},
    # A cota para a Helena: a barra dela passa da metade, o estado piora.
    {"nome": "saque-divisao", "pagina": "/game.html",
     "estado": SAQUE, "espera": 900,
     "js": "window.Loot._dar('1', 'Helena').then(() => window.Loot._dar('2', 'Stelar'))",
     "exigir": "#loot-overlay:not(.hidden) .lot-estado-piora"},

    # ── Ficha do herói ───────────────────────────────────────────────
    # Abre pelo cartão do grupo. Leitura: todo número vem do motor.
    {"nome": "heroi-ficha", "pagina": "/game.html",
     "estado": HEROI, "espera": 800,
     "js": "window.Herois._abrir('Stelar')",
     "exigir": "#heroi-overlay:not(.hidden) .hro-atributo"},
    # Conjuradora com condição, concentração e PV temporários.
    {"nome": "heroi-conjuradora", "pagina": "/game.html",
     "estado": HEROI, "espera": 800,
     "js": "window.Herois._abrir('Helena')",
     "exigir": "#heroi-overlay:not(.hidden) .hro-atributo"},

    # ── Combate ──────────────────────────────────────────────────────
    {"nome": "combate-regua-de-turnos", "pagina": "/game.html",
     "estado": COMBATE_NARRADO},
    {"nome": "combate-tela-tatica", "pagina": "/game.html",
     "estado": COMBATE_ATIVO, "espera": 700, "exigir": "#combat-overlay:not(.hidden)"},
    {"nome": "combate-escolher-alvo", "pagina": "/game.html",
     "estado": COMBATE_ATIVO, "espera": 700,
     "js": "window.Combat._sel('attack')", "exigir": "#cbt-targets:not(.hidden)"},
    {"nome": "combate-zonas", "pagina": "/game.html",
     "estado": COMBATE_ZONAS, "espera": 700,
     "exigir": "#cbt-zonas:not(.hidden)"},
    # Stelar no Pátio escolhe a arma de corpo-a-corpo: Victoria, na Sacada,
    # aparece desabilitada e marcada "fora de alcance".
    {"nome": "combate-alvo-fora-de-alcance", "pagina": "/game.html",
     "estado": COMBATE_ZONAS, "espera": 700,
     "js": "window.Combat._sel('attack');"
           "setTimeout(() => document.querySelector('#cbt-targets .cbt-btn').click(), 50)",
     "exigir": "#cbt-targets .cbt-fora"},
    {"nome": "combate-escolher-zona", "pagina": "/game.html",
     "estado": COMBATE_ZONAS, "espera": 700,
     "js": "window.Combat._sel('move')", "exigir": "#cbt-targets:not(.hidden)"},
    # Itens: o que o motor não conhece aparece travado, com o motivo.
    {"nome": "combate-itens", "pagina": "/game.html",
     "estado": COMBATE_ITENS, "espera": 700,
     "js": "window.Combat._sel('item')", "exigir": "#cbt-targets .cbt-item-desconhecido"},
    # Poção: Helena e Natasha estão em outra zona, só Stelar alcança.
    {"nome": "combate-pocao-alcance", "pagina": "/game.html",
     "estado": COMBATE_ITENS, "espera": 700,
     "js": "window.Combat._sel('item'); window.Combat._selItem('Poção de Cura', 'heal')",
     "exigir": "#cbt-targets .cbt-fora"},
    # Água Benta: Victoria não é morta-viva, fica "sem efeito".
    {"nome": "combate-agua-benta", "pagina": "/game.html",
     "estado": COMBATE_ITENS, "espera": 700,
     "js": "window.Combat._sel('item'); window.Combat._selItem('Água Benta', 'arremesso')",
     "exigir": "#cbt-targets .cbt-fora"},
    {"nome": "combate-vitoria", "pagina": "/game.html",
     "estado": COMBATE_ATIVO, "espera": 700,
     "estado2": COMBATE_ENCERRADO, "js2": "window.Combat.sync()",
     "exigir": "#cbt-end-overlay:not(.hidden)"},

    # ── PWA ──────────────────────────────────────────────────────────
    # A tela de espera dá ping em /healthz de 3 em 3 segundos e recarrega
    # assim que o servidor responde. Para retratá-la é preciso cortar esse
    # ping — senão ela salta para o jogo antes do print.
    {"nome": "offline-cold-start", "pagina": "/offline.html",
     "bloquear": ["**/healthz"], "carregar": "domcontentloaded",
     "espera": 800},
]


# ═══════════════════════════════════════════════════════════════════════
#  Captura
# ═══════════════════════════════════════════════════════════════════════

def _script_de_semente(nome_campanha: str, tema: str, historico: list,
                       limpar_memoria_de_telas: bool = True) -> str:
    """
    Roda antes de qualquer script da página: finge um usuário logado e uma
    sessão de jogo em andamento, para que login/menu/jogo não redirecionem.
    """
    sessao = {
        "campaign": nome_campanha,
        "model": "Gemini 3.1 Flash-Lite",
        "campaign_type": "dnd",
        "has_history": True,
        "opening": "",                       # vazio: não dispara o agente
        "campaign_config": None,
        "model_limits": {"rpm": 15, "rpd": 500},
        "conversation_history": historico,
    }
    return f"""
      try {{
        localStorage.setItem('rpg_theme', {json.dumps(tema)});
        window.__campanha = {json.dumps(nome_campanha)};

        // As telas de loja e nível lembram "já abri" no localStorage, e o
        // localStorage sobrevive entre as capturas deste mesmo navegador: sem
        // limpar, a captura 30 acharia que a loja já abriu na 29 e não abriria.
        // Os testes de navegador que provam essa memória desligam a limpeza.
        if ({'true' if limpar_memoria_de_telas else 'false'}) {{
          Object.keys(localStorage)
            .filter(k => k.startsWith('rpg_telas::'))
            .forEach(k => localStorage.removeItem(k));
        }}

        // A tela de login pula direto para o menu quando encontra um token
        // salvo. Como o localStorage sobrevive entre as capturas, aqui a
        // sessão é APAGADA nas páginas de login e semeada nas demais.
        var _p = location.pathname;
        if (_p === '/' || _p === '/login.html') {{
          localStorage.removeItem('rpg_access_token');
          localStorage.removeItem('rpg_refresh_token');
          localStorage.removeItem('rpg_session');
        }} else {{
          localStorage.setItem('rpg_access_token', {json.dumps(TOKEN)});
          localStorage.setItem('rpg_refresh_token', {json.dumps(TOKEN)});
          localStorage.setItem('rpg_session', {json.dumps(json.dumps(sessao))});
        }}
      }} catch (e) {{}}
    """


HISTORICO = [
    {"role": "assistant", "text":
        "A chuva bate no telhado da taverna em Oakhaven. Victoria ainda "
        "observa o grupo do fundo do salão, e a Princesa Elara espera uma "
        "resposta: vocês aceitam escoltá-la até Luminas?"},
    {"role": "user", "text": "Pergunto quanto ela pretende pagar."},
    {"role": "assistant", "text":
        "**Elara sorri**, sem desviar o olhar.\n\n"
        "— O bastante para que vocês não precisem perguntar de novo. "
        "Trezentas peças de ouro, metade adiantada.\n\n"
        "Stelar cruza os braços. Natasha já está contando as moedas com os "
        "olhos. A decisão é de vocês."},
]


def _sanear(pagina) -> None:
    """
    Deixa o print estável: desliga animações e o cursor piscando, para que
    duas execuções seguidas não gerem imagens diferentes.
    """
    pagina.add_style_tag(content="""
        *, *::before, *::after {
          animation-duration: 0s !important;
          animation-delay: 0s !important;
          transition-duration: 0s !important;
          transition-delay: 0s !important;
          caret-color: transparent !important;
        }
    """)


def capturar(url_base: str, telas: list, nomes_viewports: list,
             saida: Path, nome_campanha: str, tema: str,
             pagina_inteira: bool) -> list:
    from playwright.sync_api import sync_playwright
    import requests

    feitos, falhas = [], []
    semente = _script_de_semente(nome_campanha, tema, HISTORICO)

    with sync_playwright() as p:
        navegador = p.chromium.launch()
        try:
            for nome_vp in nomes_viewports:
                pasta = saida / nome_vp
                pasta.mkdir(parents=True, exist_ok=True)

                contexto = navegador.new_context(
                    viewport=VIEWPORTS[nome_vp],
                    device_scale_factor=2,
                    locale="pt-BR",
                    # O service worker guardaria páginas em cache entre as
                    # capturas e mostraria a tela de offline no lugar da real.
                    service_workers="block",
                )
                contexto.add_init_script(semente)
                pagina = contexto.new_page()

                for tela in telas:
                    if tela.get("viewport") and tela["viewport"] != nome_vp:
                        continue

                    # A numeração vem da posição no roteiro COMPLETO, não na
                    # lista filtrada: assim `--apenas combate` regrava os
                    # mesmos arquivos de sempre, em vez de criar 01, 02, 03…
                    # ao lado dos antigos.
                    i = TELAS.index(tela) + 1

                    destino = pasta / f"{i:02d}-{tela['nome']}.png"
                    try:
                        requests.post(f"{url_base}/__estado",
                                      json=tela.get("estado") or {}, timeout=10)

                        for padrao in tela.get("bloquear") or []:
                            pagina.route(padrao, lambda rota: rota.abort())

                        pagina.goto(url_base + tela["pagina"],
                                    wait_until=tela.get("carregar", "networkidle"))
                        _sanear(pagina)
                        pagina.wait_for_timeout(350)

                        if tela.get("js"):
                            pagina.evaluate(f"() => {{ {tela['js']} }}")
                            pagina.wait_for_timeout(350)

                        if tela.get("estado2"):
                            requests.post(f"{url_base}/__estado",
                                          json=tela["estado2"], timeout=10)
                        if tela.get("js2"):
                            pagina.evaluate(f"() => {{ {tela['js2']} }}")
                            pagina.wait_for_timeout(350)

                        pagina.wait_for_timeout(tela.get("espera", 0))

                        if tela.get("exigir"):
                            pagina.wait_for_selector(tela["exigir"],
                                                     state="visible",
                                                     timeout=5000)

                        pagina.screenshot(path=str(destino),
                                          full_page=pagina_inteira)
                    except Exception as e:
                        # Uma tela quebrada não pode derrubar a captura inteira:
                        # anota o motivo e segue para a próxima.
                        motivo = str(e).splitlines()[0][:120]
                        falhas.append(f"{nome_vp}/{tela['nome']}: {motivo}")
                        print(f"  ✗ {nome_vp:<7} {tela['nome']} — {motivo}")
                        continue
                    finally:
                        # Um bloqueio de URL vale só para a tela que o pediu.
                        if tela.get("bloquear"):
                            pagina.unroute_all()

                    feitos.append(destino)
                    print(f"  ✓ {nome_vp:<7} {destino.name}")

                contexto.close()
        finally:
            navegador.close()

    return feitos, falhas


# ═══════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Tira print de todas as telas do RPG Agent.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--saida", default="screenshots",
                    help="pasta de destino (padrão: screenshots)")
    ap.add_argument("--fixture", default="scripts/temp.json",
                    help="JSON da campanha de exemplo (padrão: temp.json)")
    ap.add_argument("--nome", default="",
                    help="nome da campanha mostrado nas telas "
                         "(padrão: o do JSON, ou 'Crônicas de Oakhaven')")
    ap.add_argument("--apenas", default="",
                    help="captura só as telas cujo nome contém este texto")
    ap.add_argument("--viewport", default="ambos",
                    choices=["desktop", "mobile", "ambos"])
    ap.add_argument("--tema", default="pergaminho", choices=TEMAS)
    ap.add_argument("--pagina-inteira", action="store_true",
                    help="captura a página toda, não só a parte visível")
    ap.add_argument("--lista", action="store_true",
                    help="lista os nomes das telas e sai")
    args = ap.parse_args()

    telas = TELAS
    if args.apenas:
        alvo = args.apenas.lower()
        telas = [t for t in TELAS if alvo in t["nome"].lower()]
        if not telas:
            print(f"Nenhuma tela com '{args.apenas}' no nome. "
                  f"Use --lista para ver as disponíveis.")
            return 1

    if args.lista:
        print(f"{len(TELAS)} telas:\n")
        for t in TELAS:
            restr = f"  [só {t['viewport']}]" if t.get("viewport") else ""
            print(f"  {t['nome']:<28} {t['pagina']}{restr}")
        return 0

    fixture = Path(args.fixture)
    if not fixture.is_absolute():
        fixture = RAIZ / fixture
    if not fixture.exists():
        print(f"Fixture não encontrada: {fixture}\n"
              f"Aponte outra com --fixture (qualquer JSON de campanha serve).")
        return 1

    campanha = json.loads(fixture.read_text(encoding="utf-8"))
    nome_campanha = (args.nome or campanha.get("name")
                     or "Crônicas de Oakhaven")
    campanha["name"] = nome_campanha

    saida = Path(args.saida)
    if not saida.is_absolute():
        saida = RAIZ / saida

    vps = ["desktop", "mobile"] if args.viewport == "ambos" else [args.viewport]

    print(f"Campanha de exemplo : {nome_campanha}  ({fixture.name})")
    print(f"Tema                : {args.tema}")
    print(f"Telas               : {len(telas)}")
    print(f"Destino             : {saida}\n")

    url, parar = _subir_servidor(campanha, nome_campanha)
    print(f"Servidor de captura em {url}\n")

    try:
        feitos, falhas = capturar(url, telas, vps, saida, nome_campanha,
                                  args.tema, args.pagina_inteira)
    finally:
        parar()

    # Numeração é POSIÇÃO na lista: inserir uma tela no meio renomeia todas as
    # seguintes, e a versão antiga fica na pasta para sempre. O resultado são
    # duas cópias da mesma tela com números diferentes, uma delas
    # desatualizada — e quem abrir a pasta não tem como saber qual é qual.
    #
    # Só na captura COMPLETA: com --apenas ou --viewport, o que não foi gerado
    # é o que o filtro deixou de fora, não lixo.
    if not args.apenas and args.viewport == "ambos" and not falhas:
        gerados = {Path(f).resolve() for f in feitos}
        sobrando = [f for f in sorted(saida.rglob("*.png"))
                    if f.resolve() not in gerados]
        for f in sobrando:
            f.unlink()
        if sobrando:
            print(f"\n{len(sobrando)} imagem(ns) de uma numeração antiga "
                  f"apagada(s):")
            for f in sobrando:
                print(f"  - {f.relative_to(saida)}")

    print(f"\n{len(feitos)} imagem(ns) em {saida}")
    if falhas:
        print(f"{len(falhas)} tela(s) não capturada(s):")
        for f in falhas:
            print(f"  • {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
