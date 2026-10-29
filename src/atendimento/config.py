import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]


def carregar_env(caminho: str | Path = RAIZ / ".env") -> None:
    """Lê `CHAVE=valor` de um .env sem sobrescrever variáveis já definidas."""
    arquivo = Path(caminho)
    if not arquivo.exists():
        return
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        if "=" in linha and not linha.lstrip().startswith("#"):
            chave, valor = linha.split("=", 1)
            os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))
