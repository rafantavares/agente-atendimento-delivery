"""Evals do agente e do RAG.

Agente: cada caso roda numa loja nova e é julgado pelo EFEITO no sistema
(quanto foi reembolsado, quantos cupons, se escalou, se cancelou) e pelo
registro de ferramentas — não por um LLM-juiz. Isso torna o eval barato,
determinístico na correção e difícil de "enganar" com uma resposta bonita.

RAG: para cada pergunta, a seção correta precisa aparecer entre os k
primeiros trechos (recall@k), comparando embeddings e TF-IDF.

    python -m atendimento.evals             # agente + RAG
    python -m atendimento.evals --so-rag
"""
from __future__ import annotations

import json
import statistics
import time
import unicodedata
from pathlib import Path

from atendimento.config import RAIZ

PASTA_EVALS = RAIZ / "evals"
PASTA_RESULTADOS = RAIZ / "results"


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in sem_acento if not unicodedata.combining(c))


def julgar(esperado: dict, loja, chamadas: list[dict], texto: str) -> list[str]:
    """Devolve a lista de falhas (vazia = passou)."""
    falhas = []
    reembolsado = round(sum(r["valor"] for r in loja.reembolsos), 2)
    if "reembolso_total" in esperado and reembolsado != esperado["reembolso_total"]:
        falhas.append(f"reembolso R$ {reembolsado:.2f}, esperado R$ {esperado['reembolso_total']:.2f}")
    if "cupons" in esperado and len(loja.cupons) != esperado["cupons"]:
        falhas.append(f"{len(loja.cupons)} cupom(ns), esperado {esperado['cupons']}")
    if "escalou" in esperado and bool(loja.escalonamentos) != esperado["escalou"]:
        falhas.append("não escalou para humano" if esperado["escalou"] else "escalou sem necessidade")
    if "prioridade" in esperado and loja.escalonamentos and \
            loja.escalonamentos[-1]["prioridade"] != esperado["prioridade"]:
        falhas.append(f"prioridade {loja.escalonamentos[-1]['prioridade']}, esperado {esperado['prioridade']}")
    if "cancelados" in esperado and loja.cancelamentos != esperado["cancelados"]:
        falhas.append(f"cancelados {loja.cancelamentos}, esperado {esperado['cancelados']}")

    usadas = {c["ferramenta"] for c in chamadas}
    for nome in esperado.get("ferramentas_obrigatorias", []):
        if nome not in usadas:
            falhas.append(f"não chamou {nome}")
    for nome in esperado.get("ferramentas_proibidas", []):
        if any(c["ferramenta"] == nome and c["resultado"]["ok"] for c in chamadas):
            falhas.append(f"executou {nome}, que não devia")
    if esperado.get("sem_ferramentas") and chamadas:
        falhas.append(f"usou ferramentas fora do escopo: {sorted(usadas)}")

    normalizado = _normalizar(texto)
    for trecho in esperado.get("texto_contem", []):
        if _normalizar(trecho) not in normalizado:
            falhas.append(f"resposta não menciona '{trecho}'")
    for trecho in esperado.get("texto_nao_contem", []):
        if _normalizar(trecho) in normalizado:
            falhas.append(f"resposta vazou '{trecho}'")
    return falhas


def rodar_agente(agente, criar_busca, pausa_s: float = 0.0, casos_ids: list[str] | None = None) -> dict:
    from atendimento.ferramentas import Sessao
    from atendimento.loja import Loja

    casos = json.loads((PASTA_EVALS / "casos.json").read_text(encoding="utf-8"))
    if casos_ids:
        casos = [c for c in casos if c["id"] in casos_ids]
    busca = criar_busca()
    resultados = []
    for caso in casos:
        sessao = Sessao(loja=Loja.carregar(), cliente_id=caso.get("cliente_id", "C01"), busca=busca)
        inicio = time.perf_counter()
        try:
            resposta = agente.responder(sessao, [], caso["mensagem"])
            texto, passos, tokens = resposta.texto, resposta.passos, resposta.tokens
            falhas = julgar(caso["esperado"], sessao.loja, sessao.chamadas, texto)
        except Exception as erro:  # erro do provedor conta como falha, não derruba os outros casos
            texto, passos, tokens = "", 0, 0
            falhas = [f"erro: {type(erro).__name__}: {erro}"[:300]]
        resultados.append({
            "id": caso["id"], "categoria": caso["categoria"], "passou": not falhas, "falhas": falhas,
            "ferramentas": [c["ferramenta"] + ("" if c["resultado"]["ok"] else " (recusada)")
                            for c in sessao.chamadas],
            "resposta": texto, "passos": passos, "tokens": tokens,
            "segundos": round(time.perf_counter() - inicio, 2),
        })
        print(("✓" if not falhas else "✗"), caso["id"], "" if not falhas else falhas, flush=True)
        time.sleep(pausa_s)

    aprovados = sum(r["passou"] for r in resultados)
    return {
        "modelo": getattr(agente, "modelo", "?"),
        "busca": type(busca).__name__,
        "aprovados": aprovados,
        "total": len(resultados),
        "taxa_aprovacao": round(aprovados / len(resultados), 3),
        "segundos_mediana": statistics.median(r["segundos"] for r in resultados),
        "tokens_mediana": statistics.median(r["tokens"] for r in resultados),
        "casos": resultados,
    }


def rodar_rag(buscas: dict, k: int = 2) -> dict:
    casos = json.loads((PASTA_EVALS / "rag_casos.json").read_text(encoding="utf-8"))
    saida = {}
    for nome, busca in buscas.items():
        acertos1 = acertosk = 0
        for caso in casos:
            secoes = [t.titulo for t, _ in busca.buscar(caso["pergunta"], k=k)]
            acertos1 += secoes[0] == caso["secao"]
            acertosk += caso["secao"] in secoes
        saida[nome] = {"recall@1": round(acertos1 / len(casos), 3),
                       f"recall@{k}": round(acertosk / len(casos), 3), "n": len(casos)}
    return saida


def _markdown(agente: dict | None, rag: dict) -> str:
    linhas = ["# Resultados dos evals", ""]
    if agente:
        linhas += [f"**Agente** ({agente['modelo']}, busca {agente['busca']}): "
                   f"**{agente['aprovados']}/{agente['total']}** casos aprovados "
                   f"· mediana {agente['segundos_mediana']} s e {agente['tokens_mediana']:.0f} tokens por caso", "",
                   "| Caso | Categoria | Resultado | Ferramentas chamadas |", "|---|---|---|---|"]
        for r in agente["casos"]:
            resultado = "✅" if r["passou"] else "❌ " + "; ".join(r["falhas"])
            linhas.append(f"| `{r['id']}` | {r['categoria']} | {resultado} | {', '.join(r['ferramentas']) or '—'} |")
        linhas.append("")
    linhas += ["**Busca nas políticas (RAG)**", "", "| Buscador | recall@1 | recall@2 |", "|---|---|---|"]
    for nome, m in rag.items():
        linhas.append(f"| {nome} | {m['recall@1']:.0%} | {m['recall@2']:.0%} |")
    return "\n".join(linhas) + "\n"


if __name__ == "__main__":
    import argparse
    import os

    from atendimento.config import carregar_env
    from atendimento.rag import BuscaEmbeddings, BuscaTfidf, carregar_trechos, criar_busca

    parser = argparse.ArgumentParser()
    parser.add_argument("--so-rag", action="store_true")
    parser.add_argument("--pausa", type=float, default=8.0, help="segundos entre casos (nível gratuito)")
    parser.add_argument("--caso", action="append", help="roda só os casos indicados")
    args = parser.parse_args()

    carregar_env()
    trechos = carregar_trechos()
    buscas = {"TF-IDF (caracteres)": BuscaTfidf(trechos)}
    if os.environ.get("GEMINI_API_KEY"):
        buscas["Embeddings (gemini-embedding-001)"] = BuscaEmbeddings(trechos)
    rag = rodar_rag(buscas)
    print(json.dumps(rag, ensure_ascii=False, indent=2))

    agente = None
    if not args.so_rag:
        from atendimento.agente import Agente

        agente = rodar_agente(Agente(), criar_busca, args.pausa, args.caso)

    PASTA_RESULTADOS.mkdir(exist_ok=True)
    (PASTA_RESULTADOS / "evals.json").write_text(
        json.dumps({"agente": agente, "rag": rag}, ensure_ascii=False, indent=2), encoding="utf-8")
    (PASTA_RESULTADOS / "evals.md").write_text(_markdown(agente, rag), encoding="utf-8")
    if agente:
        print(f"\n{agente['aprovados']}/{agente['total']} casos aprovados")
