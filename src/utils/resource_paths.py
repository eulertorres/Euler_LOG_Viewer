"""Utilities to locate bundled resources regardless of how the app is executed."""
from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Iterable, List


def _dedupe_paths(paths: Iterable[Path]) -> List[Path]:
    seen = set()
    unique: List[Path] = []
    for path in paths:
        if path is None:
            continue
        resolved = Path(path)
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


@lru_cache()
def _candidate_roots() -> tuple[Path, ...]:
    roots: List[Path] = []

    if getattr(sys, "frozen", False):  # Executado via PyInstaller
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            roots.append(Path(meipass))
        roots.append(Path(sys.executable).resolve().parent)

    roots.append(Path(__file__).resolve().parents[2])  # Raiz do projeto
    roots.append(Path.cwd())

    return tuple(_dedupe_paths(roots))


def resource_path(*relative_parts: os.PathLike | str) -> Path:
    """Retorna um caminho absoluto para arquivos empacotados.

    Procura o arquivo em diferentes diretórios (raiz do projeto, diretório
    temporário do PyInstaller, diretório atual etc.) e devolve o primeiro
    caminho encontrado. Se não existir, devolve o caminho calculado no
    primeiro diretório conhecido para manter a consistência.
    """

    if len(relative_parts) == 1 and isinstance(relative_parts[0], Path) and relative_parts[0].is_absolute():
        return relative_parts[0]

    relative_path = Path(*relative_parts)
    if relative_path.is_absolute():
        return relative_path

    for root in _candidate_roots():
        candidate = root / relative_path
        if candidate.exists():
            return candidate

    # Fallback: primeiro diretório conhecido mesmo que o arquivo não exista
    return _candidate_roots()[0] / relative_path


def get_logs_directory() -> Path | None:
    """Tenta descobrir a pasta de logs padrão.

    Ordem de precedência:
    1. Variável de ambiente XMOBOTS_LOG_DIR
    2. Pasta "logs de teste" empacotada junto com o app
    """

    env_dir = os.environ.get("XMOBOTS_LOG_DIR")
    if env_dir:
        candidate = Path(env_dir).expanduser()
        if candidate.exists():
            return candidate

    packaged_logs = resource_path("logs de teste")
    if packaged_logs.exists():
        return packaged_logs

    return None


def find_decoder_executable() -> Path | None:
    """Localiza o decoder C independente do local de execução."""

    for relative in (Path("src") / "decoder.exe", Path("decoder.exe")):
        candidate = resource_path(relative)
        if candidate.exists():
            return candidate
    return None
