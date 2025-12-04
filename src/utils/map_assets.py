from __future__ import annotations

import shutil
import time
from pathlib import Path
from string import Template
from typing import Any, Dict

from src.utils.resource_paths import resource_path


class MapAssetManager:
    """Gerencia cópia e geração de assets (ícones e JS) para o servidor local."""

    def __init__(self, map_server):
        self.map_server = map_server

    def copy_asset(self, asset_path: str | Path | None) -> str | None:
        """Copia ``asset_path`` para o diretório temporário do servidor e devolve apenas o nome do arquivo."""

        try:
            if not asset_path:
                return None

            source_icon_path = Path(asset_path)
            if not source_icon_path.exists():
                print(f"AVISO: Arquivo '{source_icon_path}' não encontrado. O asset pode não aparecer.")
                return None

            dest_dir = Path(self.map_server.get_temp_dir())
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_path = dest_dir / source_icon_path.name
            shutil.copy2(source_icon_path, dest_path)
            return source_icon_path.name
        except Exception as exc:  # noqa: BLE001 - captura genérica para feedback ao usuário
            print(f"ERRO CRÍTICO ao copiar assets para o servidor: {exc}")
            return None

    def render_js(self, template_name: str, context: Dict[str, Any]) -> Path:
        """Renderiza um arquivo JS a partir de um template em ``assets/js`` para o diretório temporário."""

        template_path = resource_path("assets", "js", template_name)
        template_text = Path(template_path).read_text(encoding="utf-8")
        rendered = Template(template_text).safe_substitute(context)
        output_name = f"{Path(template_name).stem}_{int(time.time() * 1000)}.js"
        output_path = Path(self.map_server.get_temp_dir()) / output_name
        output_path.write_text(rendered, encoding="utf-8")
        return output_path

    def build_asset_url(self, file_path: Path) -> str:
        """Retorna a URL HTTP servida pelo ``MapServer`` para um arquivo do diretório temporário."""

        return f"http://127.0.0.1:{self.map_server.get_port()}/{file_path.name}"

    def render_map2d_script(self, aircraft_name: str, wind_name: str) -> Path:
        """Gera o script do mapa 2D com os identificadores dos marcadores."""

        return self.render_js(
            "map2d.js",
            {
                "AIRCRAFT_MARKER_NAME": aircraft_name,
                "WIND_MARKER_NAME": wind_name,
            },
        )

    def render_cesium_viewer_script(
        self,
        plane_url_literal: str,
        imagery_json: str,
        default_imagery: str,
        samples_json: str,
        mode_paths_json: str,
    ) -> Path:
        """Gera o script principal do Cesium com os datasets fornecidos já serializados."""

        return self.render_js(
            "cesium_viewer.js",
            {
                "PLANE_LITERAL": plane_url_literal,
                "IMAGERY_CONFIG_JSON": imagery_json,
                "DEFAULT_IMAGERY_KEY": default_imagery,
                "SAMPLES_JSON": samples_json,
                "MODE_PATHS_JSON": mode_paths_json,
            },
        )

    def render_cesium_timeline_script(self, samples_json: str) -> Path:
        """Gera o script da timeline 3D com as amostras do log."""

        return self.render_js(
            "cesium_timeline.js",
            {"SAMPLES_JSON": samples_json},
        )
