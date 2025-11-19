"""Ferramentas de alto nível para gerar relatórios PDF ricos e analíticos."""
from __future__ import annotations

import io
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from geopy.distance import geodesic
from PyQt6.QtCore import QBuffer, QIODevice, QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas

from .pdf_reporter import PdfReportWorker


def _safe_title_from_axes(canvas: FigureCanvas) -> str:
    titles: List[str] = []
    for ax in canvas.figure.axes:
        title = ax.get_title()
        if title:
            titles.append(title.strip())
    if not titles and canvas.figure._suptitle is not None:  # type: ignore[attr-defined]
        titles.append(canvas.figure._suptitle.get_text())  # type: ignore[attr-defined]
    return "; ".join(titles) if titles else "Captura automática do painel"


@dataclass
class ImageSection:
    title: str
    description: str
    group: str
    buffer: io.BytesIO


@dataclass
class LogAnalytics:
    name: str
    duration_s: float
    distance_km: float
    sample_count: int
    max_altitude: Optional[float]
    min_altitude: Optional[float]
    max_roll: Optional[float]
    max_pitch: Optional[float]
    max_yaw_rate: Optional[float]
    vertical_speed_peak: Optional[float]
    min_voltage: Optional[float]
    max_cht: Optional[float]
    avg_asi: Optional[float]
    wind_std: Optional[float]
    fuel_used: Optional[float]
    gnss_error: Optional[float]
    anomalies: List[str]


class ReportGenerationManager(QObject):
    """Coordena a captura de dados e delega a escrita do PDF para uma thread dedicada."""

    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    status = pyqtSignal(str)
    started = pyqtSignal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._thread: Optional[QThread] = None
        self._worker: Optional[PdfReportWorker] = None

    def generate_pdf(
        self,
        *,
        file_path: str,
        current_log_name: str,
        log_data: Dict[str, pd.DataFrame],
        standard_tab,
        all_tab,
        map_widget,
        map_js_name: str,
        map_is_ready: bool,
    ) -> None:
        if not log_data:
            self.error.emit("Nenhum log carregado para compor o relatório.")
            return

        self.status.emit("Capturando imagens dos painéis analíticos...")
        QApplication.processEvents()
        plot_sections = self._capture_plot_sections(standard_tab, all_tab)

        self.status.emit("Gerando mosaicos de trajetória e vento...")
        QApplication.processEvents()
        map_sections = self._capture_map_sections(map_widget, map_js_name, map_is_ready)

        self.status.emit("Compilando análises estatísticas de todos os logs...")
        QApplication.processEvents()
        analytics_payload = self._build_analytics(log_data, current_log_name)

        metadata = {
            "active_log": current_log_name,
            "log_count": len(log_data),
        }

        self._thread = QThread()
        self._worker = PdfReportWorker(
            file_path=file_path,
            metadata=metadata,
            plot_sections=plot_sections,
            map_sections=map_sections,
            analytics=analytics_payload,
        )
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self.finished.emit)
        self._worker.error.connect(self.error.emit)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)

        self.started.emit()
        self._thread.start()

    # ------------------------------------------------------------------
    # Captura de imagens dos painéis
    # ------------------------------------------------------------------
    def _capture_plot_sections(self, standard_tab, all_tab) -> List[ImageSection]:
        sections: List[ImageSection] = []
        canvases_map = [
            ("Gráficos padrão", getattr(standard_tab, "findChildren", None)),
            ("Todos os gráficos", getattr(all_tab, "findChildren", None)),
        ]
        for group_name, finder in canvases_map:
            if finder is None:
                continue
            canvases = finder(FigureCanvas)
            for idx, canvas in enumerate(canvases, start=1):
                buf = io.BytesIO()
                canvas.figure.savefig(buf, format="png", dpi=200, bbox_inches="tight", facecolor="white")
                buf.seek(0)
                title = f"{group_name} #{idx}"
                description = _safe_title_from_axes(canvas)
                sections.append(
                    ImageSection(
                        title=title,
                        description=description,
                        group=group_name,
                        buffer=buf,
                    )
                )
        return sections

    def _capture_map_sections(self, map_widget, map_js_name: str, map_is_ready: bool) -> List[ImageSection]:
        sections: List[ImageSection] = []
        if not (map_widget and map_js_name and map_is_ready):
            return sections

        target_zoom = [18, 16, 13]
        for zoom in target_zoom:
            map_widget.page().runJavaScript(f"{map_js_name}.setZoom({zoom});")
            start = time.time()
            while time.time() - start < 1.5:
                QApplication.processEvents()
            pixmap = map_widget.grab()
            qbuffer = QBuffer()
            qbuffer.open(QIODevice.OpenModeFlag.ReadWrite)
            pixmap.save(qbuffer, "PNG")
            buffer = io.BytesIO(bytes(qbuffer.data()))
            buffer.seek(0)
            sections.append(
                ImageSection(
                    title=f"Trajetória no mapa - Zoom {zoom}",
                    description="Plano de voo, vento embarcado e dispersão de pontos em diferentes escalas.",
                    group="Mapas",
                    buffer=buffer,
                )
            )
        map_widget.page().runJavaScript(f"{map_js_name}.setZoom(15);")
        return sections

    # ------------------------------------------------------------------
    # Análises estatísticas
    # ------------------------------------------------------------------
    def _build_analytics(self, log_data: Dict[str, pd.DataFrame], active_log: str):
        per_log: List[LogAnalytics] = []
        global_anomalies: List[str] = []
        durations = []
        distances = []

        for log_name, df in log_data.items():
            metrics = self._compute_metrics_for_df(log_name, df)
            per_log.append(metrics)
            durations.append(metrics.duration_s)
            distances.append(metrics.distance_km)
            global_anomalies.extend(f"{log_name}: {msg}" for msg in metrics.anomalies)

        fleet_summary = {
            "total_logs": len(per_log),
            "total_hours": sum(durations) / 3600.0,
            "total_distance": sum(distances),
            "active_log": active_log,
            "max_distance": max(distances) if distances else 0.0,
        }

        return {
            "fleet_summary": fleet_summary,
            "per_log": per_log,
            "global_anomalies": global_anomalies,
        }

    def _compute_metrics_for_df(self, log_name: str, df: pd.DataFrame) -> LogAnalytics:
        if df is None or df.empty:
            return LogAnalytics(
                name=log_name,
                duration_s=0.0,
                distance_km=0.0,
                sample_count=0,
                max_altitude=None,
                min_altitude=None,
                max_roll=None,
                max_pitch=None,
                max_yaw_rate=None,
                vertical_speed_peak=None,
                min_voltage=None,
                max_cht=None,
                avg_asi=None,
                wind_std=None,
                fuel_used=None,
                gnss_error=None,
                anomalies=["Arquivo sem dados válidos."],
            )

        duration_s = 0.0
        if "Timestamp" in df.columns and len(df["Timestamp"].dropna()) >= 2:
            duration_s = (
                df["Timestamp"].dropna().iloc[-1] - df["Timestamp"].dropna().iloc[0]
            ).total_seconds()

        distance_km = self._compute_distance(df)
        max_altitude = self._safe_series_max(df, "AltitudeAbs")
        min_altitude = self._safe_series_min(df, "AltitudeAbs")
        max_roll = self._safe_series_absmax(df, "Roll")
        max_pitch = self._safe_series_absmax(df, "Pitch")
        max_yaw_rate = self._compute_rate(df, "Yaw")
        vertical_speed_peak = self._compute_rate(df, "AltitudeAbs")
        min_voltage = self._safe_series_min(df, "Voltage")
        max_cht = self._safe_series_max(df, "CHT")
        avg_asi = self._safe_series_mean(df, "ASI")
        wind_std = self._safe_series_std(df, "WSI")
        fuel_used = self._compute_fuel(df)
        gnss_error = self._safe_series_max(df, "GNSS_AltError")

        anomalies = self._detect_anomalies(
            max_roll=max_roll,
            max_pitch=max_pitch,
            max_yaw_rate=max_yaw_rate,
            vertical_speed_peak=vertical_speed_peak,
            min_voltage=min_voltage,
            max_cht=max_cht,
            wind_std=wind_std,
            gnss_error=gnss_error,
            fuel_used=fuel_used,
        )

        return LogAnalytics(
            name=log_name,
            duration_s=duration_s,
            distance_km=distance_km,
            sample_count=len(df),
            max_altitude=max_altitude,
            min_altitude=min_altitude,
            max_roll=max_roll,
            max_pitch=max_pitch,
            max_yaw_rate=max_yaw_rate,
            vertical_speed_peak=vertical_speed_peak,
            min_voltage=min_voltage,
            max_cht=max_cht,
            avg_asi=avg_asi,
            wind_std=wind_std,
            fuel_used=fuel_used,
            gnss_error=gnss_error,
            anomalies=anomalies,
        )

    @staticmethod
    def _compute_distance(df: pd.DataFrame) -> float:
        if not {"Latitude", "Longitude"}.issubset(df.columns):
            return 0.0
        subset = df[["Latitude", "Longitude"]].dropna()
        if len(subset) < 2:
            return 0.0
        coords = list(zip(subset["Latitude"], subset["Longitude"]))
        total = 0.0
        for p0, p1 in zip(coords, coords[1:]):
            try:
                total += geodesic(p0, p1).kilometers
            except ValueError:
                continue
        return total

    @staticmethod
    def _compute_rate(df: pd.DataFrame, column: str) -> Optional[float]:
        if not {column, "Timestamp"}.issubset(df.columns):
            return None
        series = df[["Timestamp", column]].dropna()
        if len(series) < 2:
            return None
        values = pd.to_numeric(series[column], errors="coerce").to_numpy()
        timestamps = pd.to_datetime(series["Timestamp"]).to_numpy()
        diffs = np.diff(values)
        dt = np.diff(timestamps.astype("datetime64[ns]").astype(np.int64) / 1e9)
        dt[dt == 0] = np.nan
        rates = diffs / dt
        rates = rates[np.isfinite(rates)]
        if rates.size == 0:
            return None
        return float(np.nanmax(np.abs(rates)))

    @staticmethod
    def _safe_series_max(df: pd.DataFrame, column: str) -> Optional[float]:
        if column not in df.columns:
            return None
        series = pd.to_numeric(df[column], errors="coerce")
        if series.dropna().empty:
            return None
        return float(series.max())

    @staticmethod
    def _safe_series_min(df: pd.DataFrame, column: str) -> Optional[float]:
        if column not in df.columns:
            return None
        series = pd.to_numeric(df[column], errors="coerce")
        if series.dropna().empty:
            return None
        return float(series.min())

    @staticmethod
    def _safe_series_absmax(df: pd.DataFrame, column: str) -> Optional[float]:
        if column not in df.columns:
            return None
        series = pd.to_numeric(df[column], errors="coerce").abs()
        if series.dropna().empty:
            return None
        return float(series.max())

    @staticmethod
    def _safe_series_mean(df: pd.DataFrame, column: str) -> Optional[float]:
        if column not in df.columns:
            return None
        series = pd.to_numeric(df[column], errors="coerce")
        if series.dropna().empty:
            return None
        return float(series.mean())

    @staticmethod
    def _safe_series_std(df: pd.DataFrame, column: str) -> Optional[float]:
        if column not in df.columns:
            return None
        series = pd.to_numeric(df[column], errors="coerce")
        series = series.dropna()
        if series.empty:
            return None
        return float(series.std())

    @staticmethod
    def _compute_fuel(df: pd.DataFrame) -> Optional[float]:
        for col in ["FuelLevel_anag", "FuelLevel_dig"]:
            if col in df.columns:
                series = pd.to_numeric(df[col], errors="coerce").dropna()
                if series.empty:
                    continue
                return float(series.iloc[0] - series.iloc[-1])
        return None

    @staticmethod
    def _detect_anomalies(
        *,
        max_roll: Optional[float],
        max_pitch: Optional[float],
        max_yaw_rate: Optional[float],
        vertical_speed_peak: Optional[float],
        min_voltage: Optional[float],
        max_cht: Optional[float],
        wind_std: Optional[float],
        gnss_error: Optional[float],
        fuel_used: Optional[float],
    ) -> List[str]:
        anomalies: List[str] = []
        if max_roll is not None and max_roll > 60:
            anomalies.append(f"Bancos elevados ({max_roll:.1f}°)")
        if max_pitch is not None and max_pitch > 30:
            anomalies.append(f"Ângulo de arfagem agressivo ({max_pitch:.1f}°)")
        if max_yaw_rate is not None and max_yaw_rate > 45:
            anomalies.append(f"Taxa de guinada acima do nominal ({max_yaw_rate:.1f}°/s)")
        if vertical_speed_peak is not None and vertical_speed_peak > 8:
            anomalies.append(f"Razão de subida/descida crítica ({vertical_speed_peak:.1f} m/s)")
        if min_voltage is not None and min_voltage < 21:
            anomalies.append(f"Tensão mínima perigosa ({min_voltage:.1f} V)")
        if max_cht is not None and max_cht > 180:
            anomalies.append(f"CHT elevado ({max_cht:.1f} °C)")
        if wind_std is not None and wind_std > 5:
            anomalies.append(f"Variabilidade de vento alta (σ={wind_std:.1f} m/s)")
        if gnss_error is not None and gnss_error > 5:
            anomalies.append(f"Erro GNSS vertical acima do limite ({gnss_error:.1f} m)")
        if fuel_used is not None and fuel_used < 0:
            anomalies.append("Sensor de combustível invertido")
        return anomalies
*** End of File
