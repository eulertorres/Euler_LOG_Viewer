import textwrap
from datetime import datetime
from typing import Any, Dict, Iterable, List

from PyQt6.QtCore import QObject, pyqtSignal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


class PdfReportWorker(QObject):
    """Gera o relatório PDF rico em análises e imagens."""

    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(
        self,
        *,
        file_path: str,
        metadata: Dict[str, Any],
        plot_sections: Iterable,
        map_sections: Iterable,
        analytics: Dict[str, Any],
    ) -> None:
        super().__init__()
        self.file_path = file_path
        self.metadata = metadata
        self.plot_sections = list(plot_sections)
        self.map_sections = list(map_sections)
        self.analytics = analytics

    def run(self) -> None:
        try:
            pdf = canvas.Canvas(self.file_path, pagesize=landscape(A4))
            width, height = landscape(A4)

            sections = [
                "Resumo executivo",
                "Indicadores de integridade e falhas",
                "Diagnóstico detalhado por log",
            ]
            if self.plot_sections:
                sections.append("Painel visual - gráficos padrão e completos")
            if self.map_sections:
                sections.append("Mapas, vento e trajetória consolidada")

            self._create_title_page(pdf, width, height)
            self._create_table_of_contents(pdf, width, height, sections)
            self._create_summary_page(pdf, width, height)
            self._create_faults_page(pdf, width, height)
            self._create_per_log_pages(pdf, width, height)
            self._add_image_collection(pdf, width, height, self.plot_sections, "Painel visual")
            self._add_image_collection(pdf, width, height, self.map_sections, "Mapas e trajetórias")

            pdf.save()
            self.finished.emit(self.file_path)
        except Exception as exc:  # pragma: no cover - protegido por UI
            self.error.emit(f"Ocorreu um erro ao gerar o PDF: {exc}")

    # ------------------------------------------------------------------
    # Páginas de texto
    # ------------------------------------------------------------------
    def _create_title_page(self, pdf, width, height) -> None:
        pdf.setFillColor(colors.HexColor("#0f172a"))
        pdf.rect(0, 0, width, height, stroke=0, fill=1)
        pdf.setFillColor(colors.white)
        pdf.setFont("Helvetica-Bold", 32)
        pdf.drawCentredString(width / 2, height - 2.0 * inch, "Relatório Analítico de Aeronave")
        pdf.setFont("Helvetica", 16)
        pdf.drawCentredString(
            width / 2,
            height - 2.8 * inch,
            f"Log ativo: {self.metadata.get('active_log', 'N/D')} | Total de logs: {self.metadata.get('log_count', 0)}",
        )
        pdf.setFont("Helvetica", 12)
        pdf.drawCentredString(
            width / 2,
            inch,
            f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
        )
        pdf.showPage()

    def _create_table_of_contents(self, pdf, width, height, sections: List[str]) -> None:
        pdf.setFont("Helvetica-Bold", 24)
        pdf.drawString(inch, height - inch, "Índice")
        pdf.setFont("Helvetica", 13)
        y = height - 1.5 * inch
        for idx, section in enumerate(sections, start=1):
            pdf.drawString(inch, y, f"{idx}. {section}")
            y -= 0.4 * inch
        pdf.showPage()

    def _create_summary_page(self, pdf, width, height) -> None:
        summary = self.analytics.get("fleet_summary", {})
        pdf.setFont("Helvetica-Bold", 22)
        pdf.drawString(inch, height - inch, "Resumo executivo")
        pdf.setFont("Helvetica", 12)
        y = height - 1.7 * inch
        paragraphs = [
            f"Logs analisados: {summary.get('total_logs', 0)}",
            f"Horas totais de voo: {summary.get('total_hours', 0):.2f} h",
            f"Distância acumulada: {summary.get('total_distance', 0):.1f} km",
            f"Maior perna individual: {summary.get('max_distance', 0):.1f} km",
            f"Log em foco (UI): {summary.get('active_log', 'N/D')}",
        ]
        for text in paragraphs:
            y = self._draw_wrapped_text(pdf, text, inch, y, width - 2 * inch, 16)
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(inch, y - 0.4 * inch, "Indicadores derivados")
        derived = [
            "✓ Energia: monitora tensão mínima e tendência de consumo",
            "✓ Estrutural: acompanha envelopes de Roll/Pitch/Yaw rate",
            "✓ Navegação: distância percorrida + erro GNSS vertical",
            "✓ Meio externo: variabilidade de vento (desvio padrão)",
        ]
        y -= inch
        pdf.setFont("Helvetica", 11)
        for item in derived:
            pdf.drawString(inch + 0.2 * inch, y, f"• {item}")
            y -= 0.3 * inch
        pdf.showPage()

    def _create_faults_page(self, pdf, width, height) -> None:
        anomalies = self.analytics.get("global_anomalies", [])
        pdf.setFont("Helvetica-Bold", 22)
        pdf.drawString(inch, height - inch, "Indicadores de integridade e falhas")
        pdf.setFont("Helvetica", 12)
        y = height - 1.5 * inch
        if not anomalies:
            y = self._draw_wrapped_text(
                pdf,
                "Nenhum indicador crítico foi encontrado. Continue monitorando tensão, GNSS e envelope aerodinâmico.",
                inch,
                y,
                width - 2 * inch,
                16,
            )
        else:
            pdf.setFillColor(colors.HexColor("#fee2e2"))
            pdf.rect(inch - 0.2 * inch, y - 0.2 * inch, width - 2 * inch + 0.4 * inch, 0.4 * inch + 0.3 * inch * len(anomalies), fill=1, stroke=0)
            pdf.setFillColor(colors.black)
            pdf.setFont("Helvetica", 12)
            y -= 0.1 * inch
            for item in anomalies:
                pdf.drawString(inch, y, f"⚠ {item}")
                y -= 0.3 * inch
        pdf.showPage()

    def _create_per_log_pages(self, pdf, width, height) -> None:
        per_log = self.analytics.get("per_log", [])
        for entry in per_log:
            pdf.setFont("Helvetica-Bold", 20)
            pdf.drawString(inch, height - inch, f"Diagnóstico: {getattr(entry, 'name', 'N/D')}")
            y = height - 1.6 * inch
            rows = [
                ("Duração", self._format_duration(getattr(entry, "duration_s", 0))),
                ("Distância estimada", self._format_float(getattr(entry, "distance_km", None), "km")),
                ("Altitude", self._format_interval(entry.max_altitude, entry.min_altitude, "m")),
                ("Roll/Pitch máximo", self._format_pair(entry.max_roll, entry.max_pitch, "°")),
                ("Taxa de guinada pico", self._format_float(entry.max_yaw_rate, "°/s")),
                ("Razão vertical pico", self._format_float(entry.vertical_speed_peak, "m/s")),
                ("Tensão mínima", self._format_float(entry.min_voltage, "V")),
                ("CHT máximo", self._format_float(entry.max_cht, "°C")),
                ("Velocidade média (ASI)", self._format_float(entry.avg_asi, "m/s")),
                ("Variabilidade do vento", self._format_float(entry.wind_std, "σ m/s")),
                ("Combustível consumido", self._format_float(entry.fuel_used, "unid")),
                ("Erro GNSS alt", self._format_float(entry.gnss_error, "m")),
            ]
            pdf.setFont("Helvetica", 12)
            for label, value in rows:
                pdf.drawString(inch, y, f"{label}:")
                pdf.drawString(inch + 3.3 * inch, y, value)
                y -= 0.35 * inch

            anomalies = getattr(entry, "anomalies", [])
            if anomalies:
                pdf.setFont("Helvetica-Bold", 13)
                pdf.drawString(inch, y - 0.2 * inch, "Possíveis falhas e recomendações:")
                pdf.setFont("Helvetica", 12)
                y -= 0.6 * inch
                for warning in anomalies:
                    y = self._draw_wrapped_text(pdf, f"• {warning}", inch + 0.3 * inch, y, width - 2.2 * inch, 14)
            pdf.showPage()

    # ------------------------------------------------------------------
    # Páginas de imagem
    # ------------------------------------------------------------------
    def _add_image_collection(self, pdf, width, height, sections, group_title: str) -> None:
        for idx, section in enumerate(sections, start=1):
            pdf.setFont("Helvetica-Bold", 18)
            pdf.drawString(
                inch,
                height - inch,
                f"{group_title} – {getattr(section, 'group', '')} ({idx}/{len(sections)})",
            )
            pdf.setFont("Helvetica", 11)
            pdf.drawString(inch, height - 1.4 * inch, getattr(section, "title", ""))
            self._draw_wrapped_text(pdf, getattr(section, "description", ""), inch, height - 1.8 * inch, width - 2 * inch, 14)
            img_buffer = getattr(section, "buffer", None)
            if img_buffer:
                img_buffer.seek(0)
                reader = ImageReader(img_buffer)
                img_w, img_h = reader.getSize()
                aspect = img_h / float(img_w)
                draw_width = width - 2 * inch
                draw_height = draw_width * aspect
                max_height = height - 3 * inch
                if draw_height > max_height:
                    draw_height = max_height
                    draw_width = draw_height / aspect
                x = (width - draw_width) / 2
                y = (height - draw_height) / 2 - 0.5 * inch
                pdf.drawImage(reader, x, y, draw_width, draw_height, preserveAspectRatio=True)
            pdf.showPage()

    # ------------------------------------------------------------------
    # Helpers de formatação
    # ------------------------------------------------------------------
    @staticmethod
    def _draw_wrapped_text(pdf, text: str, x: float, y: float, max_width: float, leading: float) -> float:
        if not text:
            return y
        pdf.setFont("Helvetica", 12)
        char_width = 0.18 * inch
        max_chars = max(10, int(max_width / char_width))
        for line in textwrap.wrap(text, width=max_chars):
            pdf.drawString(x, y, line)
            y -= leading
        return y

    @staticmethod
    def _format_duration(seconds: float) -> str:
        if not seconds or seconds <= 0:
            return "N/D"
        mins, sec = divmod(seconds, 60)
        hours, mins = divmod(int(mins), 60)
        return f"{hours:02d}h {mins:02d}min {sec:04.1f}s"

    @staticmethod
    def _format_float(value, unit: str) -> str:
        if value is None or (isinstance(value, float) and not value == value):
            return "N/D"
        return f"{value:.2f} {unit}"

    @staticmethod
    def _format_interval(max_value, min_value, unit: str) -> str:
        if max_value is None and min_value is None:
            return "N/D"
        if min_value is None:
            return f"Até {max_value:.1f} {unit}"
        if max_value is None:
            return f"A partir de {min_value:.1f} {unit}"
        return f"{min_value:.1f} – {max_value:.1f} {unit}"

    @staticmethod
    def _format_pair(first, second, unit: str) -> str:
        if first is None and second is None:
            return "N/D"
        left = "N/D" if first is None else f"{first:.1f}"
        right = "N/D" if second is None else f"{second:.1f}"
        return f"{left}/{right} {unit}"
