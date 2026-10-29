"""Servidor MCP: expõe as mesmas ferramentas do agente para qualquer cliente
MCP (Claude Desktop, Cursor, VS Code...). Assim o backend de atendimento
não fica preso a um modelo ou a um framework de agente.

O cliente atendido vem da variável de ambiente CLIENTE_ID (padrão: C01),
fazendo o papel da sessão autenticada.

Para rodar:  python -m atendimento.servidor_mcp   (transporte stdio)
"""
from __future__ import annotations

import os

from mcp.server.mcpserver import MCPServer

from atendimento.ferramentas import Sessao, executar
from atendimento.loja import Loja
from atendimento.rag import criar_busca


def criar_servidor(sessao: Sessao | None = None) -> MCPServer:
    sessao = sessao or Sessao(loja=Loja.carregar(), cliente_id=os.environ.get("CLIENTE_ID", "C01"),
                              busca=criar_busca())
    servidor = MCPServer(
        name="panela-express-atendimento",
        instructions="Ferramentas de atendimento da Panela Express (empresa fictícia): consultar "
                     "pedidos, buscar políticas, compensar atrasos, reembolsar itens, emitir cupons, "
                     "cancelar e escalar para humano. As regras de negócio são aplicadas pelo servidor.",
    )

    @servidor.tool()
    def consultar_pedido(pedido_id: str) -> dict:
        """Consulta um pedido do cliente: itens, valores, status, horários e minutos de atraso."""
        return executar(sessao, "consultar_pedido", {"pedido_id": pedido_id})

    @servidor.tool()
    def buscar_politica(pergunta: str) -> dict:
        """Busca nas políticas oficiais de atendimento os trechos mais relevantes para a pergunta."""
        return executar(sessao, "buscar_politica", {"pergunta": pergunta})

    @servidor.tool()
    def compensar_atraso(pedido_id: str) -> dict:
        """Aplica a compensação por atraso prevista na política; o servidor calcula atraso e valor."""
        return executar(sessao, "compensar_atraso", {"pedido_id": pedido_id})

    @servidor.tool()
    def reembolsar_itens(pedido_id: str, itens: list[str]) -> dict:
        """Reembolsa itens faltando ou errados; o servidor confere prazo, valor e limite."""
        return executar(sessao, "reembolsar_itens", {"pedido_id": pedido_id, "itens": itens})

    @servidor.tool()
    def cupom_qualidade(pedido_id: str) -> dict:
        """Emite o cupom previsto para reclamações de qualidade (comida fria, sabor ruim)."""
        return executar(sessao, "cupom_qualidade", {"pedido_id": pedido_id})

    @servidor.tool()
    def cancelar_pedido(pedido_id: str) -> dict:
        """Cancela um pedido que o restaurante ainda não aceitou, com reembolso total."""
        return executar(sessao, "cancelar_pedido", {"pedido_id": pedido_id})

    @servidor.tool()
    def escalar_para_humano(motivo: str, prioridade: str = "normal", pedido_id: str | None = None) -> dict:
        """Encaminha o caso para a equipe humana (prioridade 'normal' ou 'alta') e gera protocolo."""
        argumentos = {"motivo": motivo, "prioridade": prioridade}
        if pedido_id:
            argumentos["pedido_id"] = pedido_id
        return executar(sessao, "escalar_para_humano", argumentos)

    return servidor


if __name__ == "__main__":
    from atendimento.config import carregar_env

    carregar_env()
    criar_servidor().run("stdio")
