"""Ferramentas para listar e copiar logs a partir da pasta local do SharePoint."""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Sequence

SHAREPOINT_ENSAIOS_FOLDER = "[01] Ensaios"
FLIGHT_FOLDER_RE = re.compile(
    r"^(?P<class>[A-Z]{2})(?P<program>[A-Z0-9]{2})-(?P<date>\d{8})-(?P<flight>\d+)-(?P<serial>[A-Za-z0-9]+)$"
)
CONFIG_DIR = Path.home() / ".config" / "xmobots"
PROGRAMS_ROOT_FILE = CONFIG_DIR / "programs_root.json"
PROGRAMS_ROOT_KEY = "programs_root"


class SharePointCredentialError(RuntimeError):
    """Erro disparado quando a pasta sincronizada não está configurada."""


@dataclass(slots=True)
class SharePointProgram:
    code: str
    name: str
    folder_name: str
    icon_name: str | None = None


@dataclass(slots=True)
class SharePointFlight:
    program: SharePointProgram
    name: str
    relative_path: Path
    serial_folder: str | None
    date: datetime | None

    def local_subpath(self) -> Path:
        parts = [self.program.code]
        if self.serial_folder:
            parts.append(self.serial_folder)
        parts.append(self.name)
        return Path(*parts)

    def human_label(self) -> str:
        date_text = self.date.strftime("%d/%m/%Y") if self.date else "Data desconhecida"
        serial = self.serial_folder or "Serial não identificado"
        return f"{self.name} — {serial} — {date_text}"


DEFAULT_PROGRAMS: Sequence[SharePointProgram] = (
    SharePointProgram(code="FW1000", name="FW1000", folder_name="[00] FW1000", icon_name="fw1000.png"),
    SharePointProgram(code="FW150", name="FW150", folder_name="[01] FW150", icon_name="fw150.png"),
    SharePointProgram(code="FW25", name="FW25", folder_name="[02] FW25", icon_name="fw25.png"),
    SharePointProgram(code="FW7", name="FW7", folder_name="[03] FW7", icon_name="fw7.png"),
    SharePointProgram(code="DJI", name="DJI", folder_name="[04] DJI", icon_name="dji.png"),
    SharePointProgram(code="RW25", name="RW25", folder_name="[06] RW25", icon_name="rw25.png"),
    SharePointProgram(code="SAGRO", name="SAGRO", folder_name="[07] SAGRO", icon_name="sagro.png"),
    SharePointProgram(code="SAMA", name="SAMA", folder_name="[08] SAMA", icon_name="sama.png"),
    SharePointProgram(code="SAMB", name="SAMB", folder_name="[09] SAMB", icon_name="samb.png"),
)


def _dedupe_paths(paths: List[Path]) -> List[Path]:
    seen = set()
    unique: List[Path] = []
    for path in paths:
        resolved = Path(path).expanduser()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def _load_saved_programs_root() -> Path | None:
    if PROGRAMS_ROOT_FILE.exists():
        try:
            payload = json.loads(PROGRAMS_ROOT_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        saved = payload.get(PROGRAMS_ROOT_KEY)
        if saved:
            candidate = Path(saved).expanduser()
            if candidate.exists():
                return candidate
    return None


def _default_programs_root_candidates() -> List[Path]:
    candidates: List[Path] = []
    env_dir = os.environ.get("XMOBOTS_PROGRAMS_DIR")
    if env_dir:
        candidates.append(Path(env_dir))

    saved = _load_saved_programs_root()
    if saved:
        candidates.append(saved)

    home = Path.home()
    onedrive_hints = [
        "OneDrive - XMOBOTS AEROESPACIAL E DEFESA LTDA",
        "OneDrive - XMOBOTS AEROSPACIAL E DEFESA LTDA",
        "OneDrive - XMOBOTS AEROSPACEIAL E DEFESA LTDA",
    ]
    for hint in onedrive_hints:
        base = home / hint
        candidates.append(base / "Departamento de Ensaios em voo" / "[00] PROGRAMAS")
        candidates.append(base / "[00] PROGRAMAS")

    for folder in home.glob("OneDrive*XMOBOTS*"):
        candidates.append(folder / "Departamento de Ensaios em voo" / "[00] PROGRAMAS")
        candidates.append(folder / "[00] PROGRAMAS")

    candidates.append(home / "Departamento de Ensaios em voo" / "[00] PROGRAMAS")
    candidates.append(home / "[00] PROGRAMAS")

    return _dedupe_paths([c for c in candidates if c])


def _save_programs_root(path: Path) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {PROGRAMS_ROOT_KEY: str(path)}
    PROGRAMS_ROOT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class SharePointClient:
    """Cliente simples que trabalha sobre a pasta local sincronizada."""

    def __init__(self, programs_root: Path | None = None):
        self.programs_root: Path | None = None
        if programs_root:
            self.set_programs_root(programs_root, persist=False)
        else:
            for candidate in _default_programs_root_candidates():
                if candidate.exists():
                    self.programs_root = candidate
                    break

    def has_valid_programs_root(self) -> bool:
        return self.programs_root is not None and self.programs_root.exists()

    def require_programs_root(self) -> Path:
        if not self.has_valid_programs_root():
            raise SharePointCredentialError(
                "Selecione a pasta '[00] PROGRAMAS' sincronizada com o SharePoint no OneDrive."
            )
        return Path(self.programs_root)

    def set_programs_root(self, path: Path, persist: bool = True) -> None:
        resolved = Path(path).expanduser()
        if not resolved.exists() or not resolved.is_dir():
            raise FileNotFoundError(f"Pasta inválida: {resolved}")
        self.programs_root = resolved
        if persist:
            _save_programs_root(resolved)

    def list_flights(self, program: SharePointProgram) -> List[SharePointFlight]:
        root = self.require_programs_root()
        ensaios_path = root / program.folder_name / SHAREPOINT_ENSAIOS_FOLDER
        flights: List[SharePointFlight] = []
        if not ensaios_path.exists():
            return flights
        self._walk_program(program, root, ensaios_path, None, flights)
        flights.sort(key=lambda flight: (flight.date or datetime.min), reverse=True)
        return flights

    def _walk_program(
        self,
        program: SharePointProgram,
        root: Path,
        folder_path: Path,
        serial_hint: str | None,
        flights: List[SharePointFlight],
    ) -> None:
        if not folder_path.exists():
            return
        for entry in sorted(folder_path.iterdir()):
            if not entry.is_dir():
                continue
            name = entry.name
            match = FLIGHT_FOLDER_RE.match(name)
            if match:
                date = datetime.strptime(match.group("date"), "%Y%m%d")
                flights.append(
                    SharePointFlight(
                        program=program,
                        name=name,
                        relative_path=entry.relative_to(root),
                        serial_folder=serial_hint,
                        date=date,
                    )
                )
                continue

            next_serial = serial_hint
            if name.upper().startswith("NS"):
                next_serial = name
            self._walk_program(program, root, entry, next_serial, flights)

    def download_flight(
        self,
        flight: SharePointFlight,
        destination_root: Path,
        progress_callback: Callable[[str], None] | None = None,
    ) -> Path:
        root = self.require_programs_root()
        source_dir = root / flight.relative_path
        if not source_dir.exists():
            raise FileNotFoundError(f"Voo não encontrado em {source_dir}")
        target_dir = destination_root / flight.local_subpath()
        self._copy_folder(source_dir, target_dir, progress_callback)
        return target_dir

    def _copy_folder(
        self,
        source: Path,
        destination: Path,
        progress_callback: Callable[[str], None] | None,
    ) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        for entry in source.iterdir():
            target = destination / entry.name
            if entry.is_dir():
                self._copy_folder(entry, target, progress_callback)
            elif entry.is_file():
                shutil.copy2(entry, target)
                if progress_callback:
                    progress_callback(entry.name)


def available_programs() -> Sequence[SharePointProgram]:
    return DEFAULT_PROGRAMS
