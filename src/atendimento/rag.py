"""Busca nas políticas de atendimento (RAG).

O documento é dividido por seção (`## Título`): cada seção é uma regra
completa e curta, então dividir no meio só separaria a condição da exceção.

Dois buscadores com a mesma interface:
- `BuscaEmbeddings`: embeddings do Gemini (gemini-embedding-001) e
  similaridade do cosseno. Os vetores dos trechos ficam em cache no disco,
  indexados pelo hash do texto: só trechos novos ou alterados são recalculados.
- `BuscaTfidf`: sem rede nem chave. Usada nos testes e como reserva.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parents[2]
ARQUIVO_POLITICAS = RAIZ / "dados" / "politicas.md"
CACHE_EMBEDDINGS = RAIZ / "dados" / "indice_embeddings.json"
MODELO_EMBEDDING = "gemini-embedding-001"


@dataclass(frozen=True)
class Trecho:
    titulo: str
    texto: str

    @property
    def conteudo(self) -> str:
        return f"{self.titulo}\n{self.texto}"


def dividir_em_trechos(markdown: str) -> list[Trecho]:
    trechos = []
    for bloco in re.split(r"^## ", markdown, flags=re.MULTILINE)[1:]:
        titulo, _, corpo = bloco.partition("\n")
        trechos.append(Trecho(titulo.strip(), corpo.strip()))
    return trechos


def carregar_trechos(caminho: str | Path = ARQUIVO_POLITICAS) -> list[Trecho]:
    return dividir_em_trechos(Path(caminho).read_text(encoding="utf-8"))


def _normalizar(matriz: np.ndarray) -> np.ndarray:
    return matriz / np.linalg.norm(matriz, axis=-1, keepdims=True)


class BuscaTfidf:
    def __init__(self, trechos: list[Trecho]):
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.trechos = trechos
        self.vetorizador = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
        self.matriz = self.vetorizador.fit_transform(t.conteudo for t in trechos)

    def buscar(self, pergunta: str, k: int = 2) -> list[tuple[Trecho, float]]:
        notas = (self.matriz @ self.vetorizador.transform([pergunta]).T).toarray().ravel()
        return [(self.trechos[i], float(notas[i])) for i in np.argsort(-notas)[:k]]


class BuscaEmbeddings:
    def __init__(self, trechos: list[Trecho], cache: str | Path = CACHE_EMBEDDINGS):
        from google import genai

        self.trechos = trechos
        self.cliente = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self.cache = Path(cache)
        self.matriz = _normalizar(np.array(self._vetores_dos_trechos()))

    def _embed(self, textos: list[str], tarefa: str) -> list[list[float]]:
        from google.genai import types

        resposta = self.cliente.models.embed_content(
            model=MODELO_EMBEDDING, contents=textos,
            config=types.EmbedContentConfig(task_type=tarefa),
        )
        return [e.values for e in resposta.embeddings]

    def _vetores_dos_trechos(self) -> list[list[float]]:
        cache = json.loads(self.cache.read_text(encoding="utf-8")) if self.cache.exists() else {}
        chaves = [hashlib.sha256(t.conteudo.encode()).hexdigest()[:16] for t in self.trechos]
        faltando = [(c, t) for c, t in zip(chaves, self.trechos) if c not in cache]
        if faltando:
            novos = self._embed([t.conteudo for _, t in faltando], "RETRIEVAL_DOCUMENT")
            cache.update({c: v for (c, _), v in zip(faltando, novos)})
            atuais = {c: cache[c] for c in chaves}  # descarta trechos que saíram do documento
            self.cache.write_text(json.dumps(atuais), encoding="utf-8")
        return [cache[c] for c in chaves]

    def buscar(self, pergunta: str, k: int = 2) -> list[tuple[Trecho, float]]:
        consulta = _normalizar(np.array(self._embed([pergunta], "RETRIEVAL_QUERY")[0]))
        notas = self.matriz @ consulta
        return [(self.trechos[i], float(notas[i])) for i in np.argsort(-notas)[:k]]


def criar_busca(preferir_embeddings: bool = True):
    trechos = carregar_trechos()
    if preferir_embeddings and os.environ.get("GEMINI_API_KEY"):
        return BuscaEmbeddings(trechos)
    return BuscaTfidf(trechos)
