"""
menus.py
Menus interativos: gerenciamento de campanhas e seleção de modelo.
"""

import json
import os
import shutil
from pathlib import Path

from google.adk.models.lite_llm import LiteLlm

import memory


GEMINI_MODELS = {
    "1": ("gemini-2.5-flash",      "Gemini 2.5 Flash      — rápido, 500 req/dia grátis"),
    "2": ("gemini-2.5-flash-lite", "Gemini 2.5 Flash-Lite — mais leve, 1000 req/dia grátis"),
    "3": ("gemini-2.5-pro",        "Gemini 2.5 Pro        — mais capaz, 100 req/dia grátis"),
}

SEP = "=" * 60


def _listar_saves() -> list[Path]:
    """Retorna lista de arquivos de save ordenados por nome."""
    memory.SAVES_DIR.mkdir(exist_ok=True)
    return sorted(memory.SAVES_DIR.glob("*.json"))


def _info_save(path: Path) -> str:
    """Retorna string com resumo de uma campanha salva."""
    try:
        data  = json.loads(path.read_text(encoding="utf-8"))
        chars = len(data.get("characters", {}))
        evts  = len(data.get("events", []))
        diary = len(data.get("diary", []))
        cap   = data.get("chapter", 1)
        loc   = data.get("current_location", "") or "local desconhecido"
        return f"Cap.{cap} | {loc} | {chars} personagens, {evts} eventos, {diary} entradas no diário"
    except Exception:
        return "erro ao ler"


def _nome_valido(nome: str) -> str:
    """Sanitiza um nome de campanha para uso como nome de arquivo."""
    return "".join(c for c in nome if c.isalnum() or c in " _-").strip()


def selecionar_campanha() -> None:
    """
    Exibe o menu de campanhas e define memory.SAVE_FILE.
    Opções: carregar existente, criar nova, renomear, deletar.
    """
    while True:
        saves = _listar_saves()

        print(SEP)
        print("  RPG com Memória Persistente — Google ADK")
        print(SEP)
        print("\nCampanhas salvas:\n")

        if saves:
            for i, f in enumerate(saves, 1):
                print(f"  {i:>2}  {f.stem}")
                print(f"       {_info_save(f)}")
        else:
            print("  Nenhuma campanha encontrada.")

        print()
        print("   N  — Nova campanha")
        if saves:
            print("   R  — Renomear campanha")
            print("   D  — Deletar campanha")
        print()

        escolha = input("Escolha: ").strip().upper()

        # --- Nova campanha ---
        if escolha == "N":
            while True:
                nome = input("Nome da nova campanha: ").strip()
                nome_limpo = _nome_valido(nome)
                if not nome_limpo:
                    print("Nome inválido. Use letras, números, espaços ou _ e -.")
                    continue
                destino = memory.SAVES_DIR / f"{nome_limpo}.json"
                if destino.exists():
                    print("Já existe uma campanha com esse nome.")
                    continue
                memory.SAVE_FILE = destino
                print(f"\nNova campanha criada: '{nome_limpo}'")
                return

        # --- Renomear ---
        if escolha == "R" and saves:
            saves = _listar_saves()
            for i, f in enumerate(saves, 1):
                print(f"  {i}  {f.stem}")
            idx_str = input("Número da campanha a renomear: ").strip()
            if idx_str.isdigit() and 1 <= int(idx_str) <= len(saves):
                alvo = saves[int(idx_str) - 1]
                novo_nome = _nome_valido(input("Novo nome: ").strip())
                if novo_nome:
                    novo_path = memory.SAVES_DIR / f"{novo_nome}.json"
                    alvo.rename(novo_path)
                    # renomeia também o diário se existir
                    diario_antigo = alvo.with_suffix("").with_suffix(".diario.md")
                    if diario_antigo.exists():
                        diario_antigo.rename(novo_path.with_suffix("").with_suffix(".diario.md"))
                    print(f"Campanha renomeada para '{novo_nome}'.")
                else:
                    print("Nome inválido.")
            else:
                print("Número inválido.")
            continue

        # --- Deletar ---
        if escolha == "D" and saves:
            saves = _listar_saves()
            for i, f in enumerate(saves, 1):
                print(f"  {i}  {f.stem}")
            idx_str = input("Número da campanha a deletar: ").strip()
            if idx_str.isdigit() and 1 <= int(idx_str) <= len(saves):
                alvo = saves[int(idx_str) - 1]
                confirma = input(f"Deletar '{alvo.stem}' permanentemente? [s/N]: ").strip().lower()
                if confirma == "s":
                    alvo.unlink()
                    diario = alvo.with_suffix("").with_suffix(".diario.md")
                    if diario.exists():
                        diario.unlink()
                    print("Campanha deletada.")
            else:
                print("Número inválido.")
            continue

        # --- Carregar existente ---
        if escolha.isdigit():
            idx = int(escolha) - 1
            if 0 <= idx < len(saves):
                memory.SAVE_FILE = saves[idx]
                print(f"\nCampanha selecionada: '{memory.SAVE_FILE.stem}'")
                return

        print("Opção inválida.\n")


def selecionar_modelo() -> tuple[object, str]:
    """
    Exibe o menu de seleção de backend e modelo.
    Retorna (model, label) onde model é string (Gemini) ou LiteLlm (Ollama).
    """
    print("\nEscolha o backend do modelo:")
    print("  1  — Google Gemini (API)")
    print("  2  — Ollama (modelo local)")
    print()

    while True:
        backend = input("Backend [1/2]: ").strip()
        if backend in ("1", "2"):
            break
        print("Digite 1 ou 2.")

    if backend == "1":
        print("\nModelos Gemini disponíveis:")
        for key, (_, desc) in GEMINI_MODELS.items():
            print(f"  {key}  — {desc}")
        print("  4  — digitar nome do modelo manualmente")
        print()

        while True:
            escolha = input("Modelo [1/2/3/4]: ").strip()
            if escolha in GEMINI_MODELS:
                model_id, _ = GEMINI_MODELS[escolha]
                return model_id, f"Gemini — {model_id}"
            if escolha == "4":
                model_id = input("Nome do modelo (ex: gemini-2.0-flash): ").strip()
                return model_id, f"Gemini — {model_id}"
            print("Opção inválida.")

    else:  # Ollama
        print("\nCertifique-se de que o Ollama está rodando (ollama serve).")
        print("Modelos com bom suporte a tool calling:")
        print("  llama3.2   qwen2.5   mistral   qwen2.5-coder")
        print()

        model_name  = input("Nome do modelo Ollama: ").strip() or "llama3.2"
        ollama_base = os.environ.get("OLLAMA_API_BASE", "http://localhost:11434")
        os.environ.setdefault("OLLAMA_API_BASE", ollama_base)
        print(f"Usando Ollama em: {ollama_base}")
        return LiteLlm(model=f"ollama_chat/{model_name}"), f"Ollama — {model_name}"