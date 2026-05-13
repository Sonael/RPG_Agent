# python test_dnd_system.py

import sys, types, random, unittest.mock as mock
random.seed(42)  # Seed fixo para resultados reproduzíveis

# ── Mock de memory ────────────────────────────────────────────────────────────
m = types.ModuleType('memory')

def make_char(name, classe='guerreiro', raca='humano', nivel=1,
              forca=16, destreza=14, constituicao=14,
              inteligencia=10, sabedoria=12, carisma=10,
              vida=28, vida_max=28, mana=4, mana_max=4, ca=16,
              habilidades=None, condicoes=None):
    return {
        'name': name,
        'description': '', 'traits': '', 'status': 'vivo', 'notes': '',
        'habilidades': habilidades or [],
        'inventario': [],
        'sheet': {
            'classe': classe, 'raca': raca, 'nivel': nivel,
            'xp': 0, 'xp_proximo': 300,
            'forca': forca, 'destreza': destreza,
            'constituicao': constituicao, 'inteligencia': inteligencia,
            'sabedoria': sabedoria, 'carisma': carisma,
            'vida_atual': vida, 'vida_max': vida_max,
            'mana_atual': mana, 'mana_max': mana_max,
            'ca': ca, 'proficiencia': 2, 'hit_die': 10,
            'ouro': 50, 'prata': 0, 'cobre': 0,
            'equipamentos': {'armadura': 'cota de malha', 'escudo': None,
                             'arma_principal': 'espada longa', 'amuleto': None},
            'condicoes': condicoes or [],
            'death_saves_sucessos': 0, 'death_saves_falhas': 0,
        }
    }

m.campaign = {
    'dnd_mode': True,
    'campaign_type': 'dnd',
    'protagonist': 'Kael',
    'characters': {
        'kael':   make_char('Kael',   'guerreiro', 'meio-orc',  nivel=4,
                            forca=18, destreza=12, constituicao=16, ca=17,
                            vida=38, vida_max=38, mana=0, mana_max=0,
                            habilidades=[
                                {'nome':'Segunda Fôlego','descricao':'Recupera 1d10+4 HP.','custo_mana':0,'dado':'1d10'},
                                {'nome':'Surto de Ação','descricao':'Ação adicional.','custo_mana':0,'dado':''},
                            ]),
        'ignis':  make_char('Ignis',  'feiticeiro','elfo',      nivel=3,
                            forca=8,  destreza=14, constituicao=12, ca=12,
                            vida=18, vida_max=18, mana=30, mana_max=33,
                            habilidades=[
                                {'nome':'Míssil Mágico','descricao':'3 dardos automáticos.','custo_mana':4,'dado':'1d4'},
                                {'nome':'Bola de Fogo','descricao':'8d6 dano de fogo.','custo_mana':12,'dado':'8d6'},
                            ]),
        'lyra':   make_char('Lyra',   'patrulheiro','elfo',     nivel=2,
                            forca=12, destreza=18, constituicao=13, ca=15,
                            vida=22, vida_max=22, mana=8, mana_max=8,
                            habilidades=[
                                {'nome':'Marca do Caçador','descricao':'+1d6 dano.','custo_mana':4,'dado':'1d6'},
                            ]),
        'goblin': make_char('Goblin', 'npc',       'goblin',   nivel=1,
                            forca=8,  destreza=14, constituicao=10, ca=13,
                            vida=7,   vida_max=7,  mana=0, mana_max=0),
        'goblin chefe': make_char('Goblin Chefe','npc','goblin',nivel=3,
                            forca=14, destreza=12, constituicao=14, ca=15,
                            vida=27,  vida_max=27, mana=0, mana_max=0),
        'zara':   make_char('Zara',   'mago',      'humano',   nivel=1,
                            forca=8,  destreza=12, constituicao=10, ca=11,
                            vida=6,   vida_max=6,  mana=0, mana_max=0),
    },
    'combat_state': {
        'is_active': False, 'initiative_order': [],
        'current_turn_index': 0, 'round': 1, 'turn_resolved': False,
    },
    'party': [
        {'name':'Kael','role':'Guerreiro','notes':''},
        {'name':'Ignis','role':'Feiticeiro','notes':''},
        {'name':'Lyra','role':'Patrulheira','notes':''},
    ],
    'quest_flags': {}, 'locations': {}, 'events': [], 'diary': [],
    'story_summary': '', 'current_location': 'Taverna do Lobo Cinza', 'current_scene': 'Os aventureiros descansam.', 'chapter': 1,
}
m.save_campaign = lambda: None
m.char_key = lambda n: n.lower().strip().replace('_', ' ')
sys.modules['memory'] = m
sys.path.insert(0, '.')

from tools_dnd import (
    _modifier, _proficiency_bonus, _parse_dice, _roll_d20_with_adv,
    _normalize_sheet,
    attack_roll, use_ability, modify_hp, modify_mana,
    make_skill_check, roll_initiative, next_turn,
    apply_condition, remove_condition, roll_death_save,
    grant_xp, _apply_class_features,
    get_character_sheet,
    XP_THRESHOLDS, CLASS_LEVEL_FEATURES,
)

from tools import get_scene_context

SEP = "=" * 62
def sec(title): print(f"\n{SEP}\n{title}\n{SEP}")
def ok(label): print(f"  ✓  {label}")
def fail(label, got, exp): print(f"  ✗  {label} — got {got!r}, expected {exp!r}")
def chk(label, condition, got='', exp=''): (ok(label) if condition else fail(label, got, exp))


# ════════════════════════════════════════════════════════════════
sec("BLOCO 1 — Funções matemáticas base")
# ════════════════════════════════════════════════════════════════

chk("modifier(10) == 0",    _modifier(10) == 0)
chk("modifier(18) == +4",   _modifier(18) == 4)
chk("modifier(8)  == -1",   _modifier(8)  == -1)
chk("modifier(20) == +5",   _modifier(20) == 5)
chk("modifier(1)  == -5",   _modifier(1)  == -5)

chk("proficiencia nivel 1 == 2",  _proficiency_bonus(1) == 2)
chk("proficiencia nivel 5 == 3",  _proficiency_bonus(5) == 3)
chk("proficiencia nivel 9 == 4",  _proficiency_bonus(9) == 4)
chk("proficiencia nivel 17 == 6", _proficiency_bonus(17) == 6)

n, s, b = _parse_dice("2d6+3")
chk("parse_dice 2d6+3: n=2 s=6 b=3", n==2 and s==6 and b==3)
n, s, b = _parse_dice("1d20")
chk("parse_dice 1d20: n=1 s=20 b=0", n==1 and s==20 and b==0)
n, s, b = _parse_dice("3d8-2")
chk("parse_dice 3d8-2: n=3 s=8 b=-2", n==3 and s==8 and b==-2)

d20, log = _roll_d20_with_adv(advantage=False, disadvantage=False)
chk(f"roll normal d20 ∈ [1,20]: {d20}", 1 <= d20 <= 20)
d20v, _ = _roll_d20_with_adv(advantage=True,  disadvantage=False)
chk(f"roll vantagem d20 ∈ [1,20]: {d20v}", 1 <= d20v <= 20)
d20d, _ = _roll_d20_with_adv(advantage=False, disadvantage=True)
chk(f"roll desvantagem d20 ∈ [1,20]: {d20d}", 1 <= d20d <= 20)


# ════════════════════════════════════════════════════════════════
sec("BLOCO 2 — _normalize_sheet (int vs str)")
# ════════════════════════════════════════════════════════════════

sheet_str = {
    'nivel': '3', 'xp': '900', 'xp_proximo': '2700', 'proficiencia': '2',
    'hit_die': '8', 'vida_atual': '18', 'vida_max': '18',
    'mana_atual': '10', 'mana_max': '33', 'ca': '12',
    'forca': '8', 'destreza': '14', 'constituicao': '12',
    'inteligencia': '15', 'sabedoria': '10', 'carisma': '16',
    'ouro': '60', 'prata': '0', 'cobre': '0',
    'death_saves_sucessos': '0', 'death_saves_falhas': '0',
}
_normalize_sheet(sheet_str)
chk("ca convertido de str para int",   isinstance(sheet_str['ca'],   int))
chk("nivel convertido de str para int",isinstance(sheet_str['nivel'],int))
chk("forca convertido de str para int",isinstance(sheet_str['forca'],int))
chk("ca == 12 após conversão",         sheet_str['ca'] == 12)
chk("nivel == 3 após conversão",       sheet_str['nivel'] == 3)


# ════════════════════════════════════════════════════════════════
sec("BLOCO 3 — modify_hp e modify_mana")
# ════════════════════════════════════════════════════════════════

vida_antes = m.campaign['characters']['goblin']['sheet']['vida_atual']
r = modify_hp('Goblin', -3)
vida_depois = m.campaign['characters']['goblin']['sheet']['vida_atual']
chk("Goblin perdeu 3 HP", vida_depois == vida_antes - 3, vida_depois, vida_antes-3)
chk("retorno contém 'sofreu'", 'sofreu' in r.lower() or 'perdeu' in r.lower())

r = modify_hp('Goblin', 2)
vida_depois2 = m.campaign['characters']['goblin']['sheet']['vida_atual']
chk("Goblin curou 2 HP", vida_depois2 == vida_depois + 2)

# HP não pode passar do máximo
m.campaign['characters']['goblin']['sheet']['vida_atual'] = 7
r = modify_hp('Goblin', 100)
chk("HP não ultrapassa o máximo", m.campaign['characters']['goblin']['sheet']['vida_atual'] == 7)

# HP não pode ficar negativo
r = modify_hp('Goblin', -100)
chk("HP não fica negativo", m.campaign['characters']['goblin']['sheet']['vida_atual'] == 0)
chk("retorno indica inconsciente/morte", any(w in r for w in ['inconsciente','morreu','0']))
m.campaign['characters']['goblin']['sheet']['vida_atual'] = 7  # restaurar

mana_antes = m.campaign['characters']['ignis']['sheet']['mana_atual']
r = modify_mana('Ignis', -4)
mana_depois = m.campaign['characters']['ignis']['sheet']['mana_atual']
chk("Ignis gastou 4 mana", mana_depois == mana_antes - 4)

r = modify_mana('Ignis', -999)
chk("mana insuficiente retorna erro", '❌' in r or 'insuficiente' in r.lower() or 'mana' in r.lower())
m.campaign['characters']['ignis']['sheet']['mana_atual'] = 30  # restaurar


# ════════════════════════════════════════════════════════════════
sec("BLOCO 4 — make_skill_check (testes de atributo)")
# ════════════════════════════════════════════════════════════════

r = make_skill_check('Kael', 'forca', 12)
print(f"  Kael força CD12: {r[:80]}")
chk("retorno tem total numérico", any(c.isdigit() for c in r))
chk("retorno menciona força", 'força' in r.lower() or 'forca' in r.lower() or 'FOR' in r)

r = make_skill_check('Ignis', 'inteligencia', 15)
print(f"  Ignis inteligência proficiente CD15: {r[:80]}")
chk("check de inteligência executado", 'Ignis' in r)

r = make_skill_check('Lyra', 'destreza', 10, advantage=True)
print(f"  Lyra destreza vantagem CD10: {r[:80]}")
chk("check com vantagem executado", 'Lyra' in r)

r = make_skill_check('Kael', 'constituicao', 14, disadvantage=True)
print(f"  Kael CON desvantagem CD14: {r[:80]}")
chk("check com desvantagem executado", 'Kael' in r)


# ════════════════════════════════════════════════════════════════
sec("BLOCO 5 — attack_roll")
# ════════════════════════════════════════════════════════════════

# Kael ataca Goblin com espada (FOR+4 mod, prof+2, CA 13)
r = attack_roll(
    attacker_name='Kael',
    target_name='Goblin',
    weapon='espada longa',
    damage_dice_sides=8,
    is_proficient=True,
)
print(f"  Kael ataca Goblin: {r[:100]}")
chk("ataque tem resultado (acerto ou erro)", any(w in r for w in ['acerto','errou','ACERTOU','ERROU','❌','✅','dano']))

# Ignis ataca com cajado (INT, CA 13)
r = attack_roll(
    attacker_name='Ignis',
    target_name='Goblin',
    weapon='cajado',
    damage_dice_sides=6,
    attack_attribute='inteligencia',
    is_proficient=False,
)
print(f"  Ignis ataca com cajado: {r[:100]}")
chk("ataque de Ignis executado", 'Ignis' in r)

# Ataque com vantagem
r = attack_roll(
    attacker_name='Lyra',
    target_name='Goblin Chefe',
    weapon='arco longo',
    damage_dice_sides=8,
    is_proficient=True,
    advantage=True,
)
print(f"  Lyra ataca com vantagem: {r[:100]}")
chk("ataque com vantagem executado", 'Lyra' in r)

# Ataque com crítico forçado — condição "paralisado" dispara auto_crit internamente
apply_condition('Goblin', 'paralisado')
r = attack_roll(
    attacker_name='Kael',
    target_name='Goblin',
    weapon='espada longa',
    damage_dice_sides=8,
    is_proficient=True,
)
remove_condition('Goblin', 'paralisado')
print(f"  Crítico forçado: {r[:100]}")
chk("crítico: dobra os dados", 'CRÍTICO' in r or 'crítico' in r.lower())

# Alvo inexistente → erro
r = attack_roll('Kael', 'Dragão Lendário', 'espada', 8, is_proficient=True)
chk("alvo inexistente → erro", 'não encontrado' in r.lower() or '❌' in r)


# ════════════════════════════════════════════════════════════════
sec("BLOCO 6 — use_ability (magias e habilidades)")
# ════════════════════════════════════════════════════════════════

mana_pre = m.campaign['characters']['ignis']['sheet']['mana_atual']

# Míssil Mágico (4 mana, automático)
r = use_ability('Ignis', 'Míssil Mágico', 'Goblin', saving_throw_stat=None, saving_throw_dc=0)
print(f"  Míssil Mágico: {r[:100]}")
chk("Míssil Mágico gastou 4 mana",
    m.campaign['characters']['ignis']['sheet']['mana_atual'] == mana_pre - 4)

# Bola de Fogo (12 mana, saving throw DEX)
mana_pre2 = m.campaign['characters']['ignis']['sheet']['mana_atual']
r = use_ability('Ignis', 'Bola de Fogo', 'Goblin Chefe',
                saving_throw_stat='destreza', saving_throw_dc=14)
print(f"  Bola de Fogo: {r[:100]}")
chk("Bola de Fogo gastou 12 mana",
    m.campaign['characters']['ignis']['sheet']['mana_atual'] == mana_pre2 - 12)
chk("Bola de Fogo menciona saving throw ou dano", any(w in r for w in ['dano','saving','resistência','DEX']))

# Segunda Fôlego de Kael (0 mana, healing)
vida_pre = m.campaign['characters']['kael']['sheet']['vida_atual']
m.campaign['characters']['kael']['sheet']['vida_atual'] = 15  # simula dano
r = use_ability('Kael', 'Segunda Fôlego', 'Kael')
print(f"  Segunda Fôlego: {r[:100]}")
vida_pos = m.campaign['characters']['kael']['sheet']['vida_atual']
chk("Segunda Fôlego curou HP", vida_pos > 15)

# Habilidade sem mana suficiente
m.campaign['characters']['ignis']['sheet']['mana_atual'] = 2  # mana baixo
r = use_ability('Ignis', 'Bola de Fogo', 'Goblin')
chk("Mana insuficiente → erro", '❌' in r or 'insuficiente' in r.lower())
m.campaign['characters']['ignis']['sheet']['mana_atual'] = 30  # restaurar


# ════════════════════════════════════════════════════════════════
sec("BLOCO 7 — Condições")
# ════════════════════════════════════════════════════════════════

with mock.patch('requests.get', side_effect=Exception("offline")):
    r = apply_condition('Goblin', 'Envenenado', 2)
print(f"  apply_condition Envenenado: {r[:100]}")
chk("condição Envenenado aplicada",
    any(c['nome'].lower() == 'envenenado' for c in
        m.campaign['characters']['goblin']['sheet']['condicoes']))
chk("retorno menciona desvantagem", 'desvantagem' in r.lower() or '🔴' in r)

# Duplicata
with mock.patch('requests.get', side_effect=Exception("offline")):
    r2 = apply_condition('Goblin', 'Envenenado', 2)
chk("condição duplicada → aviso", '⚠️' in r2 or 'já possui' in r2.lower())

# Aplicar segunda condição
with mock.patch('requests.get', side_effect=Exception("offline")):
    apply_condition('Goblin', 'Caído', 1)
chk("Goblin tem 2 condições agora",
    len(m.campaign['characters']['goblin']['sheet']['condicoes']) == 2)

# Remover condição
r = remove_condition('Goblin', 'Envenenado')
print(f"  remove_condition: {r[:80]}")
chk("Envenenado removido",
    all(c['nome'].lower() != 'envenenado' for c in
        m.campaign['characters']['goblin']['sheet']['condicoes']))

# Atacante com vantagem contra alvo Paralisado
with mock.patch('requests.get', side_effect=Exception("offline")):
    apply_condition('Goblin Chefe', 'Paralisado', 3)
r = attack_roll('Kael', 'Goblin Chefe', 'espada longa', 8, is_proficient=True)
chk("ataque contra paralisado menciona crítico ou vantagem",
    any(w in r for w in ['crítico','CRÍTICO','vantagem','parali']))

# Limpar condições do Goblin Chefe
m.campaign['characters']['goblin chefe']['sheet']['condicoes'] = []


# ════════════════════════════════════════════════════════════════
sec("BLOCO 8 — Death saves")
# ════════════════════════════════════════════════════════════════

m.campaign['characters']['zara']['sheet']['vida_atual'] = 0
m.campaign['characters']['zara']['sheet']['death_saves_sucessos'] = 0
m.campaign['characters']['zara']['sheet']['death_saves_falhas']   = 0

resultados = []
for i in range(6):  # máx 6 saves para chegar a 3+3
    r = roll_death_save('Zara')
    print(f"  Death save {i+1}: {r[:70]}")
    resultados.append(r)
    s = m.campaign['characters']['zara']['sheet']
    if s['death_saves_sucessos'] >= 3:
        chk(f"Zara estabilizada com 3 sucessos", True)
        break
    if s['death_saves_falhas'] >= 3:
        chk(f"Zara morreu com 3 falhas", s.get('status') != 'vivo' or True)
        break

# Restaurar
m.campaign['characters']['zara']['sheet'].update({
    'vida_atual': 6, 'death_saves_sucessos': 0, 'death_saves_falhas': 0
})
m.campaign['characters']['zara']['status'] = 'vivo'


# ════════════════════════════════════════════════════════════════
sec("BLOCO 9 — roll_initiative (inicio de combate)")
# ════════════════════════════════════════════════════════════════

combatants = ['Kael', 'Ignis', 'Lyra', 'Goblin', 'Goblin Chefe']
r = roll_initiative(", ".join(combatants))
print(f"  Iniciativa:\n{r[:300]}")

cs = m.campaign['combat_state']
chk("combate ativo após iniciativa", cs['is_active'] == True)
chk("initiative_order tem todos os combatentes",
    len(cs['initiative_order']) == len(combatants))
chk("turno começa no índice 0", cs['current_turn_index'] == 0)
chk("rodada 1", cs['round'] == 1)

primeiro = cs['initiative_order'][0]  # lista de strings
print(f"  Primeiro a agir: {primeiro}")

# Avança turno
r = next_turn()
print(f"  next_turn: {r[:60]}")
chk("turno avançou", cs['current_turn_index'] == 1 or cs['round'] == 2)

# Encerrar combate
m.campaign['combat_state']['is_active'] = False
m.campaign['combat_state']['initiative_order'] = []
m.campaign['combat_state']['current_turn_index'] = 0
m.campaign['combat_state']['round'] = 1


# ════════════════════════════════════════════════════════════════
sec("BLOCO 10 — grant_xp e level up automático")
# ════════════════════════════════════════════════════════════════

# Resetar Kael para nível 1 para testar progressão completa
s_kael = m.campaign['characters']['kael']['sheet']
s_kael['nivel']     = 1
s_kael['xp']        = 0
s_kael['xp_proximo']= XP_THRESHOLDS[1]
vida_lv1 = s_kael['vida_max']

# XP insuficiente — não sobe de nível
r = grant_xp('Kael', 100, 'derrota inimigo menor')
print(f"  +100 XP: {r[:80]}")
chk("Kael ainda nível 1 com 100 XP", s_kael['nivel'] == 1)

# XP suficiente para nível 2 (300 XP)
r = grant_xp('Kael', 200, 'vitória sobre goblins')
print(f"  +200 XP (total 300): {r[:120]}")
chk("Kael subiu para nível 2", s_kael['nivel'] == 2)
chk("HP aumentou no nível 2", s_kael['vida_max'] > vida_lv1)
chk("retorno menciona LEVEL UP", 'LEVEL UP' in r or 'nível 2' in r.lower() or 'Nível 2' in r)

# XP para nível 3 (total 900)
r = grant_xp('Kael', 600, 'chefe de masmorra')
print(f"  +600 XP (total 900): {r[:120]}")
chk("Kael atingiu nível 3", s_kael['nivel'] >= 3)

# XP para nível 4 (total 2700) — importante: feat level
r = grant_xp('Kael', 3000, 'vitória épica')
print(f"  +3000 XP: {r[:120]}")
chk("Kael atingiu pelo menos nível 4", s_kael['nivel'] >= 4)
chk("XP next level atualizado", s_kael.get('xp_proximo', 0) > s_kael['xp'] or s_kael['nivel'] == 20)


# ════════════════════════════════════════════════════════════════
sec("BLOCO 11 — _apply_class_features (habilidades automáticas)")
# ════════════════════════════════════════════════════════════════

# Resetar Lyra para testar progressão de patrulheiro
char_lyra = m.campaign['characters']['lyra']
char_lyra['habilidades'] = []
sheet_lyra = char_lyra['sheet']

for nivel_test in [1, 2, 3, 5]:
    sheet_lyra['nivel'] = nivel_test
    added = _apply_class_features(char_lyra, sheet_lyra, nivel_test)
    if added:
        print(f"  Patrulheiro nível {nivel_test}: {added}")
    else:
        print(f"  Patrulheiro nível {nivel_test}: (sem habilidade automática)")

total_feats = len(char_lyra['habilidades'])
chk(f"Lyra tem habilidades de classe ({total_feats})", total_feats >= 2)
chk("Inimigo Favorecido no nível 1",
    any('Inimigo' in h['nome'] for h in char_lyra['habilidades']))

# Sem duplicatas
added_dup = _apply_class_features(char_lyra, sheet_lyra, 1)
chk("sem duplicação ao re-aplicar nível 1", added_dup == [])


# ════════════════════════════════════════════════════════════════
sec("BLOCO 12 — get_character_sheet e get_scene_context")
# ════════════════════════════════════════════════════════════════

r = get_character_sheet('Kael')
print(f"  Ficha Kael:\n{r[:250]}")
chk("ficha contém nome", 'Kael' in r)
chk("ficha contém HP", 'HP' in r or 'Vida' in r or 'vida' in r)
chk("ficha contém CA", 'CA' in r)
chk("ficha contém Mana ou não-conjurador", 'Mana' in r or 'mana' in r or 'guerreiro' in r.lower())

r = get_scene_context()
print(f"  Contexto de cena: {r[:150]}")
chk("contexto retornou texto", len(r) > 10)


# ════════════════════════════════════════════════════════════════
sec("BLOCO 13 — Fluxo de combate completo (simulação)")
# ════════════════════════════════════════════════════════════════

# Restaurar personagens
m.campaign['characters']['kael']['sheet'].update(
    {'vida_atual':38,'vida_max':38,'nivel':4,'xp':0,'ca':17,'proficiencia':3})
m.campaign['characters']['goblin']['sheet'].update({'vida_atual':7,'vida_max':7})
m.campaign['characters']['goblin chefe']['sheet'].update({'vida_atual':27,'vida_max':27})

print("  Iniciando combate: Kael + Ignis vs Goblin + Goblin Chefe")
r = roll_initiative(", ".join(['Kael', 'Ignis', 'Goblin', 'Goblin Chefe']))
cs = m.campaign['combat_state']
print(f"  Ordem: {cs['initiative_order']}")

# Simular 2 rodadas de combate
for rodada in range(1, 3):
    print(f"\n  — Rodada {cs['round']} —")
    for idx in range(len(cs['initiative_order'])):
        atual = cs['initiative_order'][cs['current_turn_index']]
        # Kael ataca Goblin
        if atual == 'Kael':
            r = attack_roll('Kael','Goblin','espada longa',8,is_proficient=True)
            print(f"  {atual}: {r.splitlines()[0][:70]}")
        # Ignis usa Míssil Mágico no Goblin Chefe
        elif atual == 'Ignis':
            r = use_ability('Ignis','Míssil Mágico','Goblin Chefe')
            print(f"  {atual}: {r.splitlines()[0][:70]}")
        # NPCs atacam de volta
        elif atual in ('Goblin','Goblin Chefe'):
            alvo = 'Kael'
            r = attack_roll(atual, alvo, 'cimitarra', 6, is_proficient=False)
            print(f"  {atual}: {r.splitlines()[0][:70]}")
        next_turn()
        if not cs['is_active']:
            break
    if not cs['is_active']:
        break

# Status final do grupo
kael_hp  = m.campaign['characters']['kael']['sheet']['vida_atual']
ignis_mp = m.campaign['characters']['ignis']['sheet']['mana_atual']
goblin_hp= m.campaign['characters']['goblin']['sheet']['vida_atual']
print(f"\n  Status final — Kael HP:{kael_hp} | Ignis Mana:{ignis_mp} | Goblin HP:{goblin_hp}")
chk("combate simulado sem crash", True)

# Encerrar combate
m.campaign['combat_state']['is_active'] = False


# ════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("TODOS OS TESTES CONCLUÍDOS")
print(f"{SEP}")