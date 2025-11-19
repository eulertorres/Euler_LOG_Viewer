"""Ferramentas para listar e baixar logs diretamente do SharePoint."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Sequence
from urllib.parse import quote

try:
    from office365.runtime.auth.user_credential import UserCredential
    from office365.sharepoint.client_context import ClientContext

    HAS_OFFICE365 = True
except ImportError:  # pragma: no cover - biblioteca externa
    UserCredential = None  # type: ignore
    ClientContext = None  # type: ignore
    HAS_OFFICE365 = False

SHAREPOINT_SITE_URL = "https://xmobotsaeroespacial.sharepoint.com/sites/ensaiosemvoo"
SHAREPOINT_PROGRAMS_ROOT = "/sites/ensaiosemvoo/Shared Documents/[00] PROGRAMAS"
SHAREPOINT_ENSAIOS_FOLDER = "[01] Ensaios"
FLIGHT_FOLDER_RE = re.compile(
    r"^(?P<class>[A-Z]{2})(?P<program>[A-Z0-9]{2})-(?P<date>\d{8})-(?P<flight>\d+)-(?P<serial>[A-Za-z0-9]+)$"
)


class SharePointCredentialError(RuntimeError):
    """Erro disparado quando as credenciais não estão configuradas."""


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
    server_relative_url: str
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


def _encode_sharepoint_path_part(part: str) -> str:
    stripped = part.strip("/")
    # Mantém colchetes, pois fazem parte da nomenclatura oficial das pastas
    return quote(stripped, safe="[] -_")


def build_sharepoint_path(*parts: str) -> str:
    cleaned = [p for p in parts if p]
    if not cleaned:
        return SHAREPOINT_PROGRAMS_ROOT
    sanitized = [_encode_sharepoint_path_part(p) for p in cleaned]
    joined = "/".join(sanitized)
    if cleaned[0].startswith("/"):
        return "/" + joined.lstrip("/")
    return "/" + joined


def load_sharepoint_credentials() -> tuple[str, str]:
    username = os.environ.get("XMOBOTS_SP_USERNAME")
    password = os.environ.get("XMOBOTS_SP_PASSWORD")
    if username and password:
        return username, password

    config_path = Path.home() / ".config" / "xmobots" / "sharepoint.json"
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        username = payload.get("username")
        password = payload.get("password")
        if username and password:
            return username, password

    raise SharePointCredentialError(
        "Defina XMOBOTS_SP_USERNAME e XMOBOTS_SP_PASSWORD ou configure ~/.config/xmobots/sharepoint.json"
    )


class SharePointClient:
    """Cliente simples para varrer a estrutura de diretórios do SharePoint."""

    def __init__(self, username: str | None = None, password: str | None = None):
        if not HAS_OFFICE365:
            raise SharePointCredentialError(
                "Instale o pacote Office365-REST-Python-Client para usar o downloader de logs."
            )
        self.username: str
        self.password: str
        if username and password:
            self.username = username
            self.password = password
        else:
            self.username, self.password = load_sharepoint_credentials()

    def create_context(self) -> ClientContext:
        return ClientContext(SHAREPOINT_SITE_URL).with_credentials(
            UserCredential(self.username, self.password)
        )

    def list_flights(self, program: SharePointProgram) -> List[SharePointFlight]:
        ctx = self.create_context()
        ensaios_path = build_sharepoint_path(
            SHAREPOINT_PROGRAMS_ROOT,
            program.folder_name,
            SHAREPOINT_ENSAIOS_FOLDER,
        )
        flights: List[SharePointFlight] = []
        self._walk_program(ctx, program, ensaios_path, None, flights)
        flights.sort(key=lambda flight: (flight.date or datetime.min), reverse=True)
        return flights

    def _walk_program(
        self,
        ctx: ClientContext,
        program: SharePointProgram,
        folder_url: str,
        serial_hint: str | None,
        flights: List[SharePointFlight],
    ) -> None:
        folder = ctx.web.get_folder_by_server_relative_url(folder_url)
        sub_folders = folder.folders.get().execute_query()
        for sub in sub_folders:
            name = sub.properties.get("Name")
            server_relative_url = sub.serverRelativeUrl
            if not name:
                continue
            match = FLIGHT_FOLDER_RE.match(name)
            if match:
                date = datetime.strptime(match.group("date"), "%Y%m%d")
                flights.append(
                    SharePointFlight(
                        program=program,
                        name=name,
                        server_relative_url=server_relative_url,
                        serial_folder=serial_hint,
                        date=date,
                    )
                )
                continue

            next_serial = serial_hint
            if name.upper().startswith("NS"):
                next_serial = name
            self._walk_program(ctx, program, server_relative_url, next_serial, flights)

    def download_flight(
        self,
        ctx: ClientContext,
        flight: SharePointFlight,
        destination_root: Path,
        progress_callback: Callable[[str], None] | None = None,
    ) -> Path:
        target_dir = destination_root / flight.local_subpath()
        target_dir.mkdir(parents=True, exist_ok=True)
        self._download_folder(ctx, flight.server_relative_url, target_dir, progress_callback)
        return target_dir

    def _download_folder(
        self,
        ctx: ClientContext,
        folder_url: str,
        local_path: Path,
        progress_callback: Callable[[str], None] | None,
    ) -> None:
        local_path.mkdir(parents=True, exist_ok=True)
        folder = ctx.web.get_folder_by_server_relative_url(folder_url)
        files = folder.files.get().execute_query()
        for sp_file in files:
            file_url = sp_file.serverRelativeUrl
            file_name = sp_file.properties.get("Name")
            if not file_name:
                continue
            destination = local_path / file_name
            with destination.open("wb") as fh:
                ctx.web.get_file_by_server_relative_url(file_url).download(fh).execute_query()
            if progress_callback:
                progress_callback(file_name)

        sub_folders = folder.folders.get().execute_query()
        for sub in sub_folders:
            name = sub.properties.get("Name")
            if not name:
                continue
            self._download_folder(ctx, sub.serverRelativeUrl, local_path / name, progress_callback)


def available_programs() -> Sequence[SharePointProgram]:
    return DEFAULT_PROGRAMS
