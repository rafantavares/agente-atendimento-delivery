"""Agente e evals com um "LLM" roteirizado: testa o laço de function calling,
o limite de passos e o juiz dos evals sem rede nem chave."""
import asyncio
from types import SimpleNamespace

from google.genai import types

from atendimento.agente import MAX_PASSOS, Agente
from atendimento.evals import julgar
from atendimento.ferramentas import Sessao
from atendimento.loja import Loja
from atendimento.rag import BuscaTfidf, carregar_trechos
from atendimento.servidor_mcp import criar_servidor


def _resposta(chamadas=None, texto=""):
    partes = [types.Part.from_function_call(name=n, args=a) for n, a in (chamadas or [])] \
        or [types.Part.from_text(text=texto)]
    return SimpleNamespace(
        candidates=[SimpleNamespace(content=types.Content(role="model", parts=partes))],
        function_calls=[SimpleNamespace(name=n, args=a) for n, a in (chamadas or [])] or None,
        text=texto, usage_metadata=SimpleNamespace(total_token_count=10),
    )


def _agente_roteirizado(roteiro):
    agente = Agente.__new__(Agente)
    agente.types, agente.modelo = types, "roteiro"
    respostas = iter(roteiro)
    agente._gerar = lambda conteudos: next(respostas)
    return agente


def _sessao():
    return Sessao(loja=Loja.carregar(), cliente_id="C01", busca=BuscaTfidf(carregar_trechos()))


def test_laco_executa_ferramentas_e_devolve_texto():
    agente = _agente_roteirizado([
        _resposta([("consultar_pedido", {"pedido_id": "P1002"})]),
        _resposta([("compensar_atraso", {"pedido_id": "P1002"})]),
        _resposta(texto="Pronto: reembolsei a taxa e enviei um cupom."),
    ])
    sessao, historico = _sessao(), []
    r = agente.responder(sessao, historico, "atrasou muito")
    assert [c["ferramenta"] for c in r.chamadas] == ["consultar_pedido", "compensar_atraso"]
    assert r.passos == 3 and r.tokens == 30 and "reembolsei" in r.texto
    assert sessao.loja.reembolsos[0]["valor"] == 12.00
    assert len(historico) == 6  # usuário + (modelo, ferramenta) x2 + resposta final


def test_limite_de_passos_escala_para_humano():
    agente = _agente_roteirizado([_resposta([("consultar_pedido", {"pedido_id": "P1001"})])] * MAX_PASSOS)
    sessao = _sessao()
    r = agente.responder(sessao, [], "?")
    assert r.passos == MAX_PASSOS
    assert sessao.loja.escalonamentos and "limite de passos" in sessao.loja.escalonamentos[0]["motivo"]


def test_juiz_aprova_efeito_correto_e_reprova_o_resto():
    loja = Loja.carregar()
    loja.compensar_atraso("C01", "P1002")
    assert julgar({"reembolso_total": 12.0, "cupons": 1}, loja, [], "ok") == []
    falhas = julgar({"reembolso_total": 0, "escalou": True, "texto_contem": ["1 dia útil"]}, loja, [], "x")
    assert len(falhas) == 3


def test_juiz_ignora_acento_e_caixa_no_texto():
    assert julgar({"texto_contem": ["1 dia útil"]}, Loja.carregar(), [], "Cai em até 1 DIA UTIL.") == []


def test_juiz_ferramenta_proibida_so_conta_se_executou_com_sucesso():
    recusada = [{"ferramenta": "cupom_qualidade", "resultado": {"ok": False}}]
    assert julgar({"ferramentas_proibidas": ["cupom_qualidade"]}, Loja.carregar(), recusada, "") == []


def test_servidor_mcp_expoe_as_ferramentas_e_aplica_as_regras():
    sessao = _sessao()
    servidor = criar_servidor(sessao)

    async def cenario():
        nomes = {t.name for t in await servidor.list_tools()}
        await servidor.call_tool("cancelar_pedido", {"pedido_id": "P1005"})
        return nomes

    nomes = asyncio.run(cenario())
    assert {"consultar_pedido", "buscar_politica", "escalar_para_humano"} <= nomes and len(nomes) == 7
    assert sessao.loja.cancelamentos == ["P1005"]
