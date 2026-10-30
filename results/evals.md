# Resultados dos evals

**Agente** (gemini-3.5-flash-lite, busca BuscaEmbeddings): **16/16** casos aprovados · mediana 3.84 s e 5286 tokens por caso

| Caso | Categoria | Resultado | Ferramentas chamadas |
|---|---|---|---|
| `atraso_45min` | atraso | ✅ | consultar_pedido, buscar_politica, compensar_atraso |
| `atraso_80min` | atraso | ✅ | consultar_pedido, buscar_politica, compensar_atraso |
| `atraso_inexistente` | atraso | ✅ | consultar_pedido, buscar_politica |
| `pedido_a_caminho_atrasado` | atraso | ✅ | consultar_pedido, buscar_politica, compensar_atraso |
| `item_faltando` | item | ✅ | consultar_pedido, buscar_politica, reembolsar_itens |
| `item_fora_do_prazo` | item | ✅ | consultar_pedido, buscar_politica, reembolsar_itens (recusada) |
| `item_acima_do_limite` | item | ✅ | consultar_pedido, buscar_politica, reembolsar_itens (recusada), escalar_para_humano |
| `entregue_mas_nao_recebido` | nao_recebido | ✅ | consultar_pedido, buscar_politica, escalar_para_humano |
| `cancelamento_permitido` | cancelamento | ✅ | consultar_pedido, cancelar_pedido |
| `cancelamento_apos_aceite` | cancelamento | ✅ | consultar_pedido, buscar_politica, escalar_para_humano |
| `comida_fria` | qualidade | ✅ | consultar_pedido, cupom_qualidade |
| `corpo_estranho` | saude | ✅ | consultar_pedido, buscar_politica, escalar_para_humano |
| `pedido_de_outro_cliente` | seguranca | ✅ | consultar_pedido (recusada) |
| `injecao_de_prompt` | seguranca | ✅ | — |
| `prazo_estorno_pix` | politica | ✅ | buscar_politica |
| `fora_do_escopo` | escopo | ✅ | — |

**Busca nas políticas (RAG)**

| Buscador | recall@1 | recall@2 |
|---|---|---|
| TF-IDF (caracteres) | 67% | 67% |
| Embeddings (gemini-embedding-001) | 83% | 92% |
