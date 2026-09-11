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


def _instalar_dubles(campanha: dict, nome_campanha: str) -> None:
    """Substitui auth e database por versões locais, sem rede."""
    from rpg import auth
    from rpg import database
    from rpg import memory

    auth._client = lambda: _ClienteAuthFalso()

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

    database.list_campaigns = lambda user_id: [resumo, outra]
    database.get_campaign = lambda user_id, name: copy.deepcopy(campanha)
    database.save_campaign = lambda user_id, name, data: None
    database.delete_campaign = lambda user_id, name: None
    database.rename_campaign = lambda user_id, old_name, new_name: None
    database.campaign_exists = lambda user_id, name: True

    # Nenhuma tela de captura deve tentar persistir nada.
    memory.save_campaign = lambda: None


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
             "msg": "Stelar ataca Victoria com Espada Longa: 17 vs CA 16 — acerta, 8 de dano"},
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

    # ── Subida de nível ──────────────────────────────────────────────
    # Sem `js` para abrir: o gatilho automático (alguém está devendo escolha)
    # É a feature, e uma captura que precisasse de empurrão não denunciaria
    # se ele quebrasse.
    {"nome": "nivel-ascensao", "pagina": "/game.html",
     "estado": NIVEL, "espera": 700,
     "exigir": "#levelup-overlay:not(.hidden)"},
    {"nome": "nivel-incremento-atributo", "pagina": "/game.html",
     "estado": NIVEL, "espera": 700,
     # Rola até o bloco do incremento, que nasce abaixo da dobra por vir
     # depois das duas escolhas de feature.
     "js": "document.querySelector('.lvl-bloco-asi')"
           ".scrollIntoView({block:'center'})",
     "exigir": ".lvl-bloco-asi"},
    {"nome": "nivel-sem-pendencia", "pagina": "/game.html",
     "estado": NIVEL, "espera": 700,
     "js": "window.LevelUp._trocar('Stelar')",
     "exigir": ".lvl-ok"},

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
    {"nome": "combate-escolher-zona", "pagina": "/game.html",
     "estado": COMBATE_ZONAS, "espera": 700,
     "js": "window.Combat._sel('move')", "exigir": "#cbt-targets:not(.hidden)"},
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

def _script_de_semente(nome_campanha: str, tema: str, historico: list) -> str:
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
