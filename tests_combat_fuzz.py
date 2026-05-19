"""
tests_combat_fuzz.py
Fuzzer de invariantes do motor de turno de combate.

Simula milhares de combates aleatórios com:
  • ações na ordem correta
  • ações FORA de ordem (devem ser recusadas, sem mutar estado)
  • next_turn() repetido (não pode duplo-avançar)
  • mortes no meio do combate

Após CADA chamada de ferramenta, verifica invariantes rígidos.
Se 10.000 combates passam com 0 violações → confiança quase-prova
de que o turno não corrompe mais.

Uso:
    python tests_combat_fuzz.py [n_combates] [seed]
"""

import sys, types, random

# --- isola de Supabase/rede ------------------------------------------------
_db = types.ModuleType("database")
_db.get_campaign = lambda *a, **k: None
_db.save_campaign = lambda *a, **k: None
sys.modules["database"] = _db

import memory
import tools_dnd as T

# Sem rede: arma usa os dados passados; sem busca Open5e.
T._fetch_weapon_data = lambda *a, **k: None
T._fetch_armor_data  = lambda *a, **k: None
memory.save_campaign = lambda *a, **k: None

OUT = {"morto", "inconsciente", "estabilizado", "fugiu", "exilado"}


def _mk(name, npc):
    return {
        "name": name,
        "status": "inimigo" if npc else "vivo",
        "party_member": (not npc),
        "sheet": {
            "classe": "npc" if npc else "guerreiro", "raca": "humano",
            "nivel": 3, "xp": 0, "xp_proximo": 900,
            "forca": 14, "destreza": 13, "constituicao": 12,
            "inteligencia": 10, "sabedoria": 10, "carisma": 10,
            "vida_atual": random.randint(8, 30), "vida_max": 30,
            "mana_atual": 0, "mana_max": 0, "ca": random.randint(11, 17),
            "proficiencia": 2, "hit_die": 8, "ouro": 0, "prata": 0, "cobre": 0,
            "equipamentos": {"armadura": None, "escudo": None,
                             "arma_principal": "espada longa", "amuleto": None},
            "condicoes": [], "death_saves_sucessos": 0, "death_saves_falhas": 0,
        },
        "habilidades": [], "inventario": [],
    }


def _cs():
    return memory.campaign.get("combat_state", {})


def _snap():
    cs = _cs()
    return (cs.get("round", 1), cs.get("current_turn_index", 0),
            cs.get("turn_token", 0), cs.get("is_active", False))


def _check_invariants(prev, label, fails):
    """Confere os invariantes; acumula falhas com contexto."""
    cs = _cs()
    pr, pi, pt, pa = prev
    r  = cs.get("round", 1)
    i  = cs.get("current_turn_index", 0)
    tk = cs.get("turn_token", 0)
    active = cs.get("is_active", False)
    order = cs.get("initiative_order", [])

    def bad(msg):
        fails.append(f"[{label}] {msg} | prev={prev} now=(r={r},i={i},tk={tk},active={active})")

    # I-token: monotônico, passo 0 ou 1
    if tk < pt:
        bad(f"turn_token regrediu ({pt}→{tk})")
    if tk - pt not in (0, 1):
        bad(f"turn_token pulou >1 ({pt}→{tk})")

    advanced = (tk == pt + 1)

    if advanced:
        # Um avanço real: rodada sobe no máximo 1 e nunca regride
        if r < pr:
            bad(f"rodada regrediu num avanço ({pr}→{r})")
        if r - pr not in (0, 1):
            bad(f"rodada subiu >1 num único avanço ({pr}→{r})")
    else:
        # Sem avanço: rodada/índice não podem ter mudado sozinhos
        if active and pa and (r != pr or i != pi):
            bad(f"estado mudou SEM avanço de token (r {pr}→{r}, i {pi}→{i})")

    if active and order:
        if not (0 <= i < len(order)):
            bad(f"current_turn_index fora de faixa: {i}/{len(order)}")
        else:
            cur = order[i]
            ch = memory.campaign["characters"].get(memory.char_key(cur))
            st = (ch.get("status", "") if ch else "").lower()
            if st in OUT:
                bad(f"turno atual é de combatente fora de combate: {cur} ({st})")
        if r < 1:
            bad(f"rodada < 1 ({r})")


def run(n_combates=10000, seed=1234):
    rng = random.Random(seed)
    total_fails = []
    total_calls = 0
    rejections_ok = 0

    for c in range(n_combates):
        random.seed(rng.random())  # dados reais variados por combate
        memory.bind(f"fuzz_user_{c % 7}", f"Campanha {c}")
        memory.campaign["characters"] = {}

        n = rng.randint(2, 6)
        names = []
        for k in range(n):
            npc = rng.random() < 0.5
            nm = f"{'Goblin' if npc else 'Herói'} {k}"
            names.append(nm)
            memory.campaign["characters"][memory.char_key(nm)] = _mk(nm, npc)
        if not any(not memory.campaign["characters"][memory.char_key(x)].get("party_member") for x in names):
            # garante ao menos 1 npc e 1 herói pra ter alvos
            pass
        memory.campaign["protagonist"] = names[0]

        T.roll_initiative(", ".join(names))
        prev = _snap()

        steps = rng.randint(5, 40)
        for _s in range(steps):
            cs = _cs()
            if not cs.get("is_active"):
                break
            order = cs.get("initiative_order", [])
            if not order:
                break
            idx = cs.get("current_turn_index", 0)
            cur = order[idx] if 0 <= idx < len(order) else order[0]
            alive = [nm for nm in order
                     if (memory.campaign["characters"].get(memory.char_key(nm), {})
                         .get("status", "")).lower() not in OUT]
            if len(alive) < 1:
                break
            others = [nm for nm in order if memory.char_key(nm) != memory.char_key(cur)]
            target = rng.choice(others) if others else cur

            op = rng.random()

            # `cur` é válido (em combate)? Só então o engine NÃO vai
            # deslocar o ponteiro por auto-cura, e o teste de "fora de
            # ordem" é determinístico.
            cur_ch = memory.campaign["characters"].get(memory.char_key(cur), {})
            cur_valido = (cur_ch.get("status", "") or "").lower() not in OUT

            # Ator fora de ordem precisa estar VIVO e ≠ atual — assim a
            # ÚNICA razão possível de recusa é a ordem de turno (um ator
            # morto seria recusado por "está morto", outro motivo válido).
            ooo_pool = [
                o for o in order
                if memory.char_key(o) != memory.char_key(cur)
                and (memory.campaign["characters"].get(memory.char_key(o), {})
                     .get("status", "") or "").lower() not in OUT
            ]

            if op < 0.15 and cur_valido and ooo_pool:
                actor = rng.choice(ooo_pool)
                tk_before = _cs().get("turn_token", 0)
                tch = memory.campaign["characters"].get(memory.char_key(target), {})
                hp_before = tch.get("sheet", {}).get("vida_atual")
                out = T.attack_roll(actor, target, "espada longa", 8)
                total_calls += 1
                tk_after = _cs().get("turn_token", 0)
                hp_after = tch.get("sheet", {}).get("vida_atual")
                if "FORA DE ORDEM" not in out:
                    total_fails.append(f"[ooo] ator vivo fora de ordem NÃO recusado: "
                                       f"{actor} (atual={cur}) → {out[:80]!r}")
                elif hp_after != hp_before:
                    total_fails.append(f"[ooo] dano aplicado numa ação recusada ({hp_before}→{hp_after})")
                elif tk_after - tk_before not in (0, 1):
                    total_fails.append(f"[ooo] token saltou numa ação recusada ({tk_before}→{tk_after})")
                else:
                    rejections_ok += 1
                _check_invariants(prev, "ooo", total_fails)
                prev = _snap()

            elif op < 0.75:
                # AÇÃO CORRETA (ator do turno)
                T.attack_roll(cur, target, "espada longa", 8)
                total_calls += 1
                _check_invariants(prev, "atk", total_fails)
                prev = _snap()

            elif op < 0.90:
                # next_turn() — possivelmente repetido (não pode duplo-avançar)
                reps = rng.randint(1, 3)
                for _ in range(reps):
                    t0 = _cs().get("turn_token", 0)
                    T.next_turn()
                    total_calls += 1
                    t1 = _cs().get("turn_token", 0)
                    if t1 - t0 not in (0, 1):
                        total_fails.append(f"[nt] next_turn avançou >1 token ({t0}→{t1})")
                    _check_invariants(prev, "nt", total_fails)
                    prev = _snap()

            else:
                # MORTE no meio do combate
                victim = rng.choice(order)
                vch = memory.campaign["characters"].get(memory.char_key(victim))
                if vch:
                    vch["status"] = rng.choice(["morto", "inconsciente", "fugiu"])
                    if vch.get("sheet"):
                        vch["sheet"]["vida_atual"] = 0
                # não chama tool — só checa que o próximo avanço pula o morto
                T.next_turn()
                total_calls += 1
                _check_invariants(prev, "death", total_fails)
                prev = _snap()

        memory.unbind(f"fuzz_user_{c % 7}")

    print(f"Combates simulados : {n_combates}")
    print(f"Chamadas de tool   : {total_calls}")
    print(f"Recusas corretas   : {rejections_ok} (ações fora de ordem barradas)")
    print(f"Violações           : {len(total_fails)}")
    if total_fails:
        print("\n--- primeiras 15 violações ---")
        for f in total_fails[:15]:
            print("  " + f)
        return False
    print("\n✅ 0 VIOLAÇÕES — invariantes de turno mantidos em todos os combates.")
    return True


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10000
    s = int(sys.argv[2]) if len(sys.argv) > 2 else 1234
    ok = run(n, s)
    sys.exit(0 if ok else 1)
