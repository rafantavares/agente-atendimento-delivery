"""Ferramentas do atendimento: uma definição só, usada pelo agente (function
calling do Gemini) e pelo servidor MCP.

Cada ferramenta recebe a `Sessao` — o cliente autenticado vem da sessão,
nunca de um argumento que o modelo possa inventar — e devolve um dicionário
com `ok: true` ou `ok: false` + `recusa` explicando o motivo, para o modelo
repassar ao cliente em vez de "tentar de novo de outro jeito".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from atendimento.loja import Loja, RecusaDeRegra


@dataclass
class Sessao:
    loja: Loja
    cliente_id: str
    busca: Any  # BuscaEmbeddings ou BuscaTfidf
    chamadas: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class Ferramenta:
    nome: str
    descricao: str
    parametros: dict
    executar: Callable[..., dict]


def _pedido(descricao="Número do pedido, ex.: P1001."):
    return {"type": "string", "description": descricao}


def _objeto(propriedades: dict, obrigatorios: list[str]) -> dict:
    return {"type": "object", "properties": propriedades, "required": obrigatorios}


def _buscar_politica(s: Sessao, pergunta: str) -> dict:
    return {"trechos": [{"secao": t.titulo, "texto": t.texto, "relevancia": round(n, 3)}
                        for t, n in s.busca.buscar(pergunta, k=2)]}


FERRAMENTAS = [
    Ferramenta(
        "consultar_pedido",
        "Consulta um pedido do cliente: itens, valores, status, horário previsto, horário de "
        "entrega e minutos de atraso. Use antes de qualquer ação sobre o pedido.",
        _objeto({"pedido_id": _pedido()}, ["pedido_id"]),
        lambda s, pedido_id: s.loja.resumo(s.loja.pedido_do_cliente(s.cliente_id, pedido_id)),
    ),
    Ferramenta(
        "buscar_politica",
        "Busca nas políticas oficiais de atendimento (atrasos, itens faltando, cancelamento, "
        "qualidade, prazos de estorno, privacidade). Use para fundamentar a resposta.",
        _objeto({"pergunta": {"type": "string", "description": "O que você quer saber da política."}},
                ["pergunta"]),
        _buscar_politica,
    ),
    Ferramenta(
        "compensar_atraso",
        "Aplica a compensação por atraso prevista na política (cupom e, se o atraso for grande, "
        "reembolso da taxa de entrega). O sistema calcula o atraso e o valor.",
        _objeto({"pedido_id": _pedido()}, ["pedido_id"]),
        lambda s, pedido_id: s.loja.compensar_atraso(s.cliente_id, pedido_id),
    ),
    Ferramenta(
        "reembolsar_itens",
        "Reembolsa itens que vieram faltando ou errados. Informe os nomes dos itens afetados, "
        "como aparecem no pedido. O sistema calcula o valor e confere prazo e limite.",
        _objeto({"pedido_id": _pedido(),
                 "itens": {"type": "array", "items": {"type": "string"},
                           "description": "Nomes dos itens afetados."}},
                ["pedido_id", "itens"]),
        lambda s, pedido_id, itens: s.loja.reembolsar_itens(s.cliente_id, pedido_id, itens),
    ),
    Ferramenta(
        "cupom_qualidade",
        "Emite o cupom de desconto previsto para reclamações de qualidade da comida "
        "(fria, sabor ruim). Não use para problemas de saúde ou corpo estranho.",
        _objeto({"pedido_id": _pedido()}, ["pedido_id"]),
        lambda s, pedido_id: s.loja.cupom_qualidade(s.cliente_id, pedido_id),
    ),
    Ferramenta(
        "cancelar_pedido",
        "Cancela um pedido que o restaurante ainda não aceitou, com reembolso total.",
        _objeto({"pedido_id": _pedido()}, ["pedido_id"]),
        lambda s, pedido_id: s.loja.cancelar(s.cliente_id, pedido_id),
    ),
    Ferramenta(
        "escalar_para_humano",
        "Encaminha o caso para a equipe humana e gera um protocolo. Use quando a política "
        "mandar (pedido não recebido, saúde, valores acima do limite, cancelamento após aceite) "
        "ou quando o cliente pedir.",
        _objeto({"motivo": {"type": "string", "description": "Resumo do problema."},
                 "prioridade": {"type": "string", "enum": ["normal", "alta"]},
                 "pedido_id": _pedido("Número do pedido, se houver.")},
                ["motivo", "prioridade"]),
        lambda s, motivo, prioridade, pedido_id=None:
            s.loja.escalar(s.cliente_id, pedido_id, motivo, prioridade),
    ),
]

POR_NOME = {f.nome: f for f in FERRAMENTAS}


def executar(sessao: Sessao, nome: str, argumentos: dict) -> dict:
    """Executa a ferramenta e registra a chamada (usado pelos evals)."""
    ferramenta = POR_NOME.get(nome)
    if ferramenta is None:
        resultado = {"ok": False, "recusa": f"Ferramenta desconhecida: {nome}"}
    else:
        try:
            resultado = {"ok": True, **ferramenta.executar(sessao, **argumentos)}
        except RecusaDeRegra as recusa:
            resultado = {"ok": False, "recusa": str(recusa)}
        except TypeError as erro:  # argumentos faltando ou inventados pelo modelo
            resultado = {"ok": False, "recusa": f"Argumentos inválidos: {erro}"}
    sessao.chamadas.append({"ferramenta": nome, "argumentos": argumentos, "resultado": resultado})
    return resultado
