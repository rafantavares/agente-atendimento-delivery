"""Chat no terminal com o agente, mostrando as ferramentas chamadas.

    python -m atendimento.chat            (cliente C01)
"""
import sys

from atendimento.agente import Agente
from atendimento.config import carregar_env
from atendimento.ferramentas import Sessao
from atendimento.loja import Loja
from atendimento.rag import criar_busca


def main(cliente_id: str = "C01") -> None:
    carregar_env()
    sessao = Sessao(loja=Loja.carregar(), cliente_id=cliente_id, busca=criar_busca())
    agente, historico = Agente(), []
    print(f"Panela Express — atendimento (cliente {cliente_id}). Ctrl+C para sair.\n")
    while True:
        try:
            mensagem = input("você> ").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if not mensagem:
            continue
        resposta = agente.responder(sessao, historico, mensagem)
        for chamada in resposta.chamadas:
            situacao = "ok" if chamada["resultado"]["ok"] else "recusado"
            print(f"  · {chamada['ferramenta']}({chamada['argumentos']}) → {situacao}")
        print(f"agente> {resposta.texto}\n")


if __name__ == "__main__":
    main(*sys.argv[1:2])
