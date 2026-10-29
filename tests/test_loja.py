import pytest

from atendimento.loja import Loja, RecusaDeRegra


@pytest.fixture
def loja():
    return Loja.carregar()


def test_pedido_de_outro_cliente_parece_inexistente(loja):
    with pytest.raises(RecusaDeRegra, match="não encontrado"):
        loja.pedido_do_cliente("C01", "P2001")


def test_numero_do_pedido_aceita_minusculas_e_espacos(loja):
    assert loja.pedido_do_cliente("C01", " p1001 ")["id"] == "P1001"


@pytest.mark.parametrize("pedido, atraso", [("P1001", 45), ("P1002", 80), ("P1003", 0), ("P1008", 40)])
def test_atraso_em_minutos(loja, pedido, atraso):
    assert loja.atraso_minutos(loja.pedidos[pedido]) == atraso


def test_atraso_entre_30_e_60_min_gera_so_cupom(loja):
    r = loja.compensar_atraso("C01", "P1001")
    assert r["cupom"]["valor"] == "R$ 10.00"
    assert "reembolso" not in r and loja.reembolsos == []


def test_atraso_acima_de_60_min_reembolsa_a_taxa(loja):
    r = loja.compensar_atraso("C01", "P1002")
    assert r["reembolso"]["valor"] == 12.00
    assert r["reembolso"]["prazo_estorno"] == "até 5 dias úteis"  # cartão


def test_atraso_pequeno_nao_compensa(loja):
    with pytest.raises(RecusaDeRegra, match="só a partir de 30 min"):
        loja.compensar_atraso("C01", "P1003")


def test_compensacao_por_atraso_so_uma_vez(loja):
    loja.compensar_atraso("C01", "P1001")
    with pytest.raises(RecusaDeRegra, match="já recebeu"):
        loja.compensar_atraso("C01", "P1001")


def test_reembolso_de_item_pelo_valor_do_item(loja):
    r = loja.reembolsar_itens("C01", "P1003", ["milkshake"])
    assert r["valor"] == 19.00 and r["itens"] == ["Milkshake"]


def test_reembolso_de_item_considera_quantidade(loja):
    assert loja.reembolsar_itens("C01", "P1003", ["Smash duplo"])["valor"] == 72.00


def test_item_que_nao_esta_no_pedido_e_recusado(loja):
    with pytest.raises(RecusaDeRegra, match="não faz parte"):
        loja.reembolsar_itens("C01", "P1003", ["pizza"])


def test_reclamacao_de_item_depois_de_24h_e_recusada(loja):
    with pytest.raises(RecusaDeRegra, match="24 h"):
        loja.reembolsar_itens("C01", "P1004", ["smash simples"])


def test_reembolso_acima_do_limite_vai_para_humano(loja):
    with pytest.raises(RecusaDeRegra, match="limite automático"):
        loja.reembolsar_itens("C01", "P1007", ["rodízio"])
    assert loja.reembolsos == []


def test_cancelamento_antes_do_aceite_reembolsa_tudo(loja):
    r = loja.cancelar("C01", "P1005")
    assert r["reembolso"]["valor"] == 69.50
    assert loja.pedidos["P1005"]["status"] == "cancelado"


def test_cancelamento_depois_do_aceite_e_recusado(loja):
    with pytest.raises(RecusaDeRegra, match="não pode ser cancelado"):
        loja.cancelar("C01", "P1006")


def test_cupom_de_qualidade(loja):
    assert loja.cupom_qualidade("C01", "P1003")["valor"] == "20%"


def test_escalar_gera_protocolo_e_normaliza_prioridade(loja):
    r = loja.escalar("C01", "P1002", "corpo estranho", "urgentissima")
    assert r["protocolo"] == "H0001" and r["prioridade"] == "normal"


def test_carregar_nao_compartilha_estado_entre_lojas():
    a, b = Loja.carregar(), Loja.carregar()
    a.cancelar("C01", "P1005")
    assert b.pedidos["P1005"]["status"] == "aguardando_confirmacao"
