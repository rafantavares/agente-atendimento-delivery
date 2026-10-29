import json

import pytest

from atendimento.ferramentas import FERRAMENTAS, Sessao, executar
from atendimento.loja import Loja
from atendimento.rag import BuscaTfidf, carregar_trechos, dividir_em_trechos


@pytest.fixture
def sessao():
    return Sessao(loja=Loja.carregar(), cliente_id="C01", busca=BuscaTfidf(carregar_trechos()))


def test_toda_ferramenta_tem_esquema_valido():
    for f in FERRAMENTAS:
        assert f.parametros["type"] == "object"
        assert set(f.parametros["required"]) <= set(f.parametros["properties"])


def test_executar_registra_sucesso(sessao):
    r = executar(sessao, "consultar_pedido", {"pedido_id": "P1001"})
    assert r["ok"] and r["atraso_minutos"] == 45
    assert sessao.chamadas[-1]["ferramenta"] == "consultar_pedido"


def test_executar_converte_regra_em_recusa(sessao):
    r = executar(sessao, "cancelar_pedido", {"pedido_id": "P1006"})
    assert r == {"ok": False, "recusa": r["recusa"]} and "não pode ser cancelado" in r["recusa"]


def test_cliente_vem_da_sessao_e_nao_do_modelo(sessao):
    # o modelo não tem como passar cliente_id: o argumento extra é rejeitado
    r = executar(sessao, "consultar_pedido", {"pedido_id": "P2001", "cliente_id": "C02"})
    assert not r["ok"]


def test_ferramenta_desconhecida(sessao):
    assert not executar(sessao, "apagar_banco", {})["ok"]


def test_resultado_e_serializavel_em_json(sessao):
    for nome, args in [("consultar_pedido", {"pedido_id": "P1002"}),
                       ("buscar_politica", {"pergunta": "estorno no pix"}),
                       ("compensar_atraso", {"pedido_id": "P1002"})]:
        json.dumps(executar(sessao, nome, args))


def test_divide_politicas_por_secao():
    trechos = dividir_em_trechos("# Título\n\n## A\ntexto a\n\n## B\ntexto b\n")
    assert [(t.titulo, t.texto) for t in trechos] == [("A", "texto a"), ("B", "texto b")]


def test_busca_tfidf_encontra_a_secao_certa():
    busca = BuscaTfidf(carregar_trechos())
    assert busca.buscar("prazo do estorno no pix", k=1)[0][0].titulo == "Prazo de estorno"
    assert busca.buscar("quero cancelar meu pedido", k=1)[0][0].titulo == "Cancelamento"
