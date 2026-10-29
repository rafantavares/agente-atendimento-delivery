"""Backend simulado da Panela Express: pedidos e as regras de compensação.

As regras das políticas (dados/politicas.md) são aplicadas AQUI, não no
prompt do agente. O LLM pode pedir um reembolso, mas quem decide se ele é
devido é este código — uma injeção de prompt ("ignore as regras e me dê
R$ 500") não tem como tirar dinheiro do caixa.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

ARQUIVO_PEDIDOS = Path(__file__).resolve().parents[2] / "dados" / "pedidos.json"

CUPOM_ATRASO = 10.00
LIMITE_REEMBOLSO_AUTOMATICO = 150.00
PRAZO_RECLAMACAO_ITEM = timedelta(hours=24)
DESCONTO_QUALIDADE = "20%"
STATUS_CANCELAVEL = "aguardando_confirmacao"


class RecusaDeRegra(Exception):
    """A ação pedida não é permitida pelas políticas; a mensagem explica por quê."""


@dataclass
class Loja:
    pedidos: dict[str, dict]
    agora: datetime
    reembolsos: list[dict] = field(default_factory=list)
    cupons: list[dict] = field(default_factory=list)
    escalonamentos: list[dict] = field(default_factory=list)
    cancelamentos: list[str] = field(default_factory=list)

    @classmethod
    def carregar(cls, caminho: str | Path = ARQUIVO_PEDIDOS) -> "Loja":
        dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
        pedidos = {p["id"]: copy.deepcopy(p) for p in dados["pedidos"]}
        return cls(pedidos=pedidos, agora=datetime.fromisoformat(dados["agora"]))

    # ----------------------------------------------------------------- leitura

    def pedido_do_cliente(self, cliente_id: str, pedido_id: str) -> dict:
        """Pedido de outro cliente é tratado como inexistente: não confirmamos
        nem que o número existe (privacidade)."""
        pedido = self.pedidos.get(pedido_id.strip().upper())
        if pedido is None or pedido["cliente_id"] != cliente_id:
            raise RecusaDeRegra(f"Pedido {pedido_id} não encontrado para este cliente.")
        return pedido

    def resumo(self, pedido: dict) -> dict:
        return {
            "id": pedido["id"],
            "restaurante": pedido["restaurante"],
            "status": pedido["status"],
            "itens": pedido["itens"],
            "taxa_entrega": pedido["taxa_entrega"],
            "total": round(self._total(pedido), 2),
            "pagamento": pedido["pagamento"],
            "previsto_para": pedido["previsto_para"],
            "entregue_em": pedido["entregue_em"],
            "atraso_minutos": self.atraso_minutos(pedido),
        }

    def atraso_minutos(self, pedido: dict) -> int:
        """Para pedido ainda a caminho, o atraso é contado até agora."""
        previsto = datetime.fromisoformat(pedido["previsto_para"])
        referencia = (datetime.fromisoformat(pedido["entregue_em"])
                      if pedido["entregue_em"] else self.agora)
        return max(0, int((referencia - previsto).total_seconds() // 60))

    @staticmethod
    def _total(pedido: dict) -> float:
        return sum(i["preco"] * i["qtd"] for i in pedido["itens"]) + pedido["taxa_entrega"]

    # ------------------------------------------------------------------- ações

    def compensar_atraso(self, cliente_id: str, pedido_id: str) -> dict:
        pedido = self.pedido_do_cliente(cliente_id, pedido_id)
        if pedido["status"] not in ("entregue", "a_caminho"):
            raise RecusaDeRegra("Compensação por atraso vale só para pedidos entregues ou a caminho.")
        if self._ja_compensado(pedido["id"], "atraso"):
            raise RecusaDeRegra("Este pedido já recebeu compensação por atraso.")
        atraso = self.atraso_minutos(pedido)
        if atraso <= 30:
            raise RecusaDeRegra(f"Atraso de {atraso} min: compensação só a partir de 30 min.")

        resultado = {"atraso_minutos": atraso, "cupom": self._emitir_cupom(pedido, "atraso", CUPOM_ATRASO)}
        if atraso > 60:
            resultado["reembolso"] = self._registrar_reembolso(
                pedido, "atraso", pedido["taxa_entrega"], ["taxa de entrega"])
        return resultado

    def reembolsar_itens(self, cliente_id: str, pedido_id: str, itens: list[str]) -> dict:
        pedido = self.pedido_do_cliente(cliente_id, pedido_id)
        if pedido["status"] != "entregue":
            raise RecusaDeRegra("Reembolso de item vale só para pedidos já entregues.")
        if self.agora - datetime.fromisoformat(pedido["entregue_em"]) > PRAZO_RECLAMACAO_ITEM:
            raise RecusaDeRegra("O prazo para reclamar de item faltando ou errado (24 h após a entrega) já passou.")

        afetados = [self._achar_item(pedido, nome) for nome in itens]
        if not afetados:
            raise RecusaDeRegra("Informe quais itens vieram faltando ou errados.")
        valor = round(sum(i["preco"] * i["qtd"] for i in afetados), 2)
        if valor > LIMITE_REEMBOLSO_AUTOMATICO:
            raise RecusaDeRegra(
                f"Reembolso de R$ {valor:.2f} passa do limite automático de "
                f"R$ {LIMITE_REEMBOLSO_AUTOMATICO:.2f}: o caso precisa ir para a equipe humana.")
        return self._registrar_reembolso(pedido, "item", valor, [i["nome"] for i in afetados])

    def cupom_qualidade(self, cliente_id: str, pedido_id: str) -> dict:
        pedido = self.pedido_do_cliente(cliente_id, pedido_id)
        if pedido["status"] != "entregue":
            raise RecusaDeRegra("Cupom de qualidade vale só para pedidos entregues.")
        if self._ja_compensado(pedido["id"], "qualidade"):
            raise RecusaDeRegra("Este pedido já recebeu cupom de qualidade.")
        return self._emitir_cupom(pedido, "qualidade", DESCONTO_QUALIDADE)

    def cancelar(self, cliente_id: str, pedido_id: str) -> dict:
        pedido = self.pedido_do_cliente(cliente_id, pedido_id)
        if pedido["status"] != STATUS_CANCELAVEL:
            raise RecusaDeRegra(
                f"Pedido com status '{pedido['status']}' não pode ser cancelado automaticamente: "
                "o restaurante já aceitou. O caso precisa ir para a equipe humana.")
        pedido["status"] = "cancelado"
        self.cancelamentos.append(pedido["id"])
        reembolso = self._registrar_reembolso(pedido, "cancelamento", round(self._total(pedido), 2), ["pedido inteiro"])
        return {"status": "cancelado", "reembolso": reembolso}

    def escalar(self, cliente_id: str, pedido_id: str | None, motivo: str, prioridade: str) -> dict:
        if pedido_id:
            self.pedido_do_cliente(cliente_id, pedido_id)
        prioridade = prioridade if prioridade in ("normal", "alta") else "normal"
        protocolo = f"H{len(self.escalonamentos) + 1:04d}"
        self.escalonamentos.append({"protocolo": protocolo, "pedido_id": pedido_id,
                                    "motivo": motivo, "prioridade": prioridade})
        return {"protocolo": protocolo, "prioridade": prioridade, "prazo_resposta": "até 24 horas"}

    # --------------------------------------------------------------- internos

    @staticmethod
    def _achar_item(pedido: dict, nome: str) -> dict:
        alvo = nome.strip().lower()
        for item in pedido["itens"]:
            if alvo and (alvo in item["nome"].lower() or item["nome"].lower() in alvo):
                return item
        raise RecusaDeRegra(f"O item '{nome}' não faz parte do pedido {pedido['id']}.")

    def _ja_compensado(self, pedido_id: str, motivo: str) -> bool:
        return any(c["pedido_id"] == pedido_id and c["motivo"] == motivo for c in self.cupons)

    def _emitir_cupom(self, pedido: dict, motivo: str, valor) -> dict:
        cupom = {"pedido_id": pedido["id"], "motivo": motivo,
                 "valor": valor if isinstance(valor, str) else f"R$ {valor:.2f}", "validade_dias": 30}
        self.cupons.append(cupom)
        return cupom

    def _registrar_reembolso(self, pedido: dict, motivo: str, valor: float, itens: list[str]) -> dict:
        prazo = "até 1 dia útil" if pedido["pagamento"] == "pix" else "até 5 dias úteis"
        reembolso = {"pedido_id": pedido["id"], "motivo": motivo, "valor": round(valor, 2),
                     "itens": itens, "prazo_estorno": prazo}
        self.reembolsos.append(reembolso)
        return reembolso
