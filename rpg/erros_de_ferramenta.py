"""
erros_de_ferramenta.py
O que acontece quando uma chamada de ferramenta do mestre dá errado.

POR QUE EXISTE
──────────────
Sem isto, o ADK trata dois casos como fatais e derruba o TURNO INTEIRO:

• A LLM chama uma ferramenta que não existe ("modify_amount", nome
  inventado) ou que saiu do conjunto deste turno (attack_roll no combate da
  tela). O ADK levanta ValueError("Tool '...' not found").
• A ferramenta levanta uma exceção por dentro (um personagem salvo sem
  ficha, um campo gravado como null).

Nos dois, o jogador via "O RPG AGENT silenciou: ..." com a mensagem crua em
inglês, e o que o mestre já tinha feito naquele turno ficava sem narração.

O `on_tool_error_callback` do Agent recebe a falha antes de o ADK desistir.
Devolvendo uma resposta, a falha vira o RESULTADO da chamada: o mestre lê
"Erro: ..." como leria uma recusa do motor e segue a cena (troca de
ferramenta, confere o estado ou narra sem ela). O traceback vai para o log do
servidor, que é onde dá para descobrir a causa depois.
"""

from __future__ import annotations

import difflib
import traceback


def _nomes_conhecidos() -> list[str]:
    from rpg.tools import ALL_TOOLS
    return sorted({getattr(f, "__name__", "") for f in ALL_TOOLS} - {""})


def _ferramenta_inexistente(nome: str, erro: Exception) -> bool:
    return isinstance(erro, ValueError) and str(erro).startswith(f"Tool '{nome}' not found")


def _parecidas(nome: str, nomes: list[str]) -> list[str]:
    """Nomes parecidos com o inventado (modify_amount → modify_hp, modify_mana...)."""
    return difflib.get_close_matches(nome, nomes, n=4, cutoff=0.55)


def mensagem_de_ferramenta_inexistente(nome: str) -> str:
    from rpg import memory
    from rpg.toolsets import FERRAMENTAS_SO_DO_MODO_DND, FERRAMENTAS_SO_DO_MODO_NARRADO

    camp = memory.campaign
    # Tudo aqui é conversa com o mestre. Vai dentro de [[llm]]…[[/llm]], que o
    # servidor tira do que chega à tela: o jogador não precisa ler o nome da
    # ferramenta que a IA tentou usar e não podia (server.py, tool_result).
    if nome in FERRAMENTAS_SO_DO_MODO_NARRADO and camp.get("combat_mode") == "tela":
        return (f"[[llm]]Erro: {nome} não está disponível agora: o combate é resolvido na "
                f"tela tática, e o jogador age por lá. Não tente de novo; espere "
                f"[COMBATE RESOLVIDO NA TELA TÁTICA] para narrar.[[/llm]]")
    if nome in FERRAMENTAS_SO_DO_MODO_DND:
        return (f"[[llm]]Erro: {nome} não está disponível nesta campanha, que não usa as "
                f"regras de D&D. Resolva a cena pela narração.[[/llm]]")

    sugestoes = _parecidas(nome, _nomes_conhecidos())
    dica = (f" Talvez você queira: {', '.join(sugestoes)}." if sugestoes else "")
    return (f"[[llm]]Erro: a ferramenta {nome} não existe.{dica} Use apenas as ferramentas "
            f"da sua lista; se nenhuma serve, narre sem ferramenta.[[/llm]]")


def ao_falhar_ferramenta(tool, args, tool_context, error):
    """
    on_tool_error_callback do Agent. Devolve {"result": "Erro: ..."} para
    a falha virar resposta da ferramenta em vez de derrubar o turno.
    """
    nome = getattr(tool, "name", "") or "?"

    if _ferramenta_inexistente(nome, error):
        texto = mensagem_de_ferramenta_inexistente(nome)
        print(f"[FERRAMENTA] chamada inexistente: {nome}({_resumo(args)})", flush=True)
        return {"result": texto}

    print(f"[FERRAMENTA] {nome}({_resumo(args)}) falhou:", flush=True)
    print("".join(traceback.format_exception(type(error), error, error.__traceback__)),
          flush=True)
    # A primeira frase é para o jogador: alguma coisa falhou, e a cena segue.
    # O diagnóstico e a ordem de não repetir são do mestre ([[llm]]).
    return {"result": (
        f"Aviso: uma ação do mestre não funcionou e foi ignorada; a cena continua."
        f"[[llm]] Erro: {nome} falhou por um problema interno ({type(error).__name__}: {error}). "
        f"Não repita a mesma chamada. Confira o estado (get_character_sheet ou "
        f"get_scene_context) antes de decidir, e siga a cena.[[/llm]]"
    )}


def _resumo(args) -> str:
    try:
        return ", ".join(f"{k}={str(v)[:60]}" for k, v in dict(args or {}).items())
    except Exception:
        return "?"
