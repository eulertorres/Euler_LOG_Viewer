import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView

from src.widgets.all_plots_widget import DebugWebPage


class StandardPlotsWidget(QWidget):
    """Standard charts rendered via Plotly (JavaScript) for responsiveness."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.df = pd.DataFrame()
        self.current_log_name = ""

        self._web_ready = False
        self._pending_js: List[str] = []
        self._last_cursor_ms: Optional[float] = None
        self._last_window: Optional[tuple[float, float]] = None

        layout = QVBoxLayout(self)

        self.plot_selector_group = QGroupBox("Gráficos")
        plot_selector_layout = QHBoxLayout()
        self.radio_position = QRadioButton("Posicionamento")
        self.radio_wind_variability = QRadioButton("Variabilidade Vento (Vel/Dir)")
        self.radio_rpy = QRadioButton("Roll / Pitch / Yaw")
        self.radio_variance = QRadioButton("Variância RPY/Alt")
        self.radios = [
            self.radio_position,
            self.radio_wind_variability,
            self.radio_rpy,
            self.radio_variance,
        ]
        self.radio_position.setChecked(True)
        for r in self.radios:
            r.toggled.connect(self.update_plot)
            plot_selector_layout.addWidget(r)
        self.plot_selector_group.setLayout(plot_selector_layout)
        layout.addWidget(self.plot_selector_group)

        self.webview = QWebEngineView()
        self.webview.setPage(DebugWebPage(self._debug, self.webview))
        self.webview.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        self.webview.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
        )
        self.webview.loadFinished.connect(self._on_webview_ready)
        layout.addWidget(self.webview, 1)

        self._render_empty()

    # -------- public API --------
    def load_dataframe(self, df, log_name=""):
        self.df = df if isinstance(df, pd.DataFrame) else pd.DataFrame()
        self.current_log_name = log_name
        self.update_plot()

    def show_position_plot(self):
        if not self.radio_position.isChecked():
            self.radio_position.setChecked(True)

    def update_cursor(self, timestamp):
        ts_ms = self._to_epoch_ms(timestamp)
        self._last_cursor_ms = ts_ms
        self._run_js(f"window.updateCursor && window.updateCursor({json.dumps(ts_ms)});")

    def set_time_window(self, start_ts, end_ts):
        start_ms = self._to_epoch_ms(start_ts)
        end_ms = self._to_epoch_ms(end_ts)
        self._last_window = (start_ms, end_ms)
        self._run_js(
            (
                "if (window.setTimeWindow) {"
                f"setTimeWindow({json.dumps(start_ms)}, {json.dumps(end_ms)});"
                "}"
            )
        )

    # -------- rendering --------
    def _render_empty(self, message: str | None = None):
        msg = message or "Carregue um arquivo de log para ver os gráficos."
        html = f"""
        <html><body style='font-family: sans-serif; background:#fafafa;'>
            <div style='padding:20px; color:#666;'>{msg}</div>
        </body></html>
        """
        self._web_ready = False
        self.webview.setHtml(html)

    def update_plot(self):
        if self.df.empty:
            self._render_empty()
            return

        df_plot = self.df.copy()
        if "Timestamp" not in df_plot.columns and isinstance(df_plot.index, pd.DatetimeIndex):
            df_plot = df_plot.reset_index().rename(columns={"index": "Timestamp"})
        if "Timestamp" not in df_plot.columns:
            self._render_empty("Log sem coluna de Timestamp para plotar.")
            return

        df_plot["_ts_ms_"] = df_plot["Timestamp"].map(self._to_epoch_ms)
        if df_plot["_ts_ms_"].dropna().empty:
            self._render_empty("Log sem timestamps válidos para plotar.")
            return

        selection = self._current_selection()
        traces, layout = self._build_traces(selection, df_plot)
        if not traces:
            self._render_empty("Nenhum dado disponível para este gráfico.")
            return

        payload = {"traces": traces, "layout": layout, "cursorMs": self._last_cursor_ms}
        html = self._build_html(payload)
        self._web_ready = False
        self.webview.setHtml(html, baseUrl=QUrl.fromLocalFile(str(Path.cwd())))

    def _current_selection(self):
        if self.radio_wind_variability.isChecked():
            return "wind"
        if self.radio_rpy.isChecked():
            return "rpy"
        if self.radio_variance.isChecked():
            return "variance"
        return "position"

    def _build_traces(self, selection: str, df_plot: pd.DataFrame):
        traces: List[Dict[str, Any]] = []
        layout: Dict[str, Any] = {
            "title": self._title_for_selection(selection),
            "margin": {"l": 60, "r": 60, "t": 40, "b": 40},
            "hovermode": "x unified",
            "xaxis": {
                "type": "date",
                "showspikes": True,
                "spikemode": "across",
                "spikecolor": "#d32f2f",
                "spikethickness": 1,
            },
            "legend": {"orientation": "h", "x": 0, "y": 1.12},
        }

        def add_trace(col: str, name: Optional[str] = None, axis: str = "y", color: Optional[str] = None):
            if col not in df_plot.columns:
                return
            series = df_plot[["_ts_ms_", col]].dropna()
            if series.empty:
                return
            traces.append(
                {
                    "name": name or col,
                    "x": series["_ts_ms_"].to_list(),
                    "y": series[col].to_list(),
                    "mode": "lines",
                    "line": {"width": 2, **({"color": color} if color else {})},
                    "yaxis": axis,
                }
            )

        if selection == "position":
            add_trace("AltitudeAbs", "Altitude Abs (m)")
            add_trace("QNE", "QNE (m)")
            add_trace("VSI", "Vel. Vertical (m/s)", axis="y2", color="rgb(244,67,54)")
            layout["yaxis"] = {"title": "Altitude (m)"}
            layout["yaxis2"] = {"title": "Vel. Vertical (m/s)", "overlaying": "y", "side": "right", "showgrid": False}
        elif selection == "rpy":
            add_trace("Roll", "Roll (°)")
            add_trace("Pitch", "Pitch (°)")
            add_trace("Yaw", "Yaw (°)")
            layout["yaxis"] = {"title": "Ângulos (°)"}
        elif selection == "variance":
            cols = [c for c in ["Roll", "Pitch", "Yaw", "AltitudeAbs"] if c in df_plot.columns]
            if not cols:
                return [], {}
            rolling = df_plot[cols].rolling(window=30).var()
            for col in cols:
                series = pd.concat([df_plot["_ts_ms_"], rolling[col]], axis=1).dropna()
                if series.empty:
                    continue
                traces.append(
                    {
                        "name": f"Var {col}",
                        "x": series["_ts_ms_"].to_list(),
                        "y": series[col].to_list(),
                        "mode": "lines",
                        "line": {"width": 2},
                    }
                )
            layout["yaxis"] = {"title": "Variância (janela 30)"}
        elif selection == "wind":
            required_wind = ["WSI", "WindDirection"]
            has_wind = all(c in df_plot.columns for c in required_wind)
            has_path = "Path_angle" in df_plot.columns
            if not has_wind and not has_path:
                return [], {}
            window = 30
            if has_wind:
                d_wind = df_plot.dropna(subset=required_wind)
                wsi_var = d_wind["WSI"].rolling(window).var()
                wsi_std = d_wind["WSI"].rolling(window).std()

                wind_rad = np.deg2rad(d_wind["WindDirection"])
                wind_cos = np.cos(wind_rad)
                wind_sin = np.sin(wind_rad)
                mean_cos = wind_cos.rolling(window).mean()
                mean_sin = wind_sin.rolling(window).mean()
                r = np.sqrt(np.clip(mean_cos**2 + mean_sin**2, 0, 1))
                winddir_var_circular = 1 - r
                winddir_std_deg = np.rad2deg(np.sqrt(-2 * np.log(r + 1e-15)))

                def merge(series):
                    return pd.concat([d_wind["_ts_ms_"], series], axis=1).dropna()

                series_var = merge(wsi_var)
                if not series_var.empty:
                    traces.append(
                        {
                            "name": f"Var WSI (J={window})",
                            "x": series_var["_ts_ms_"].to_list(),
                            "y": series_var[wsi_var.name].to_list(),
                            "mode": "lines",
                            "line": {"width": 2, "color": "rgb(33,150,243)"},
                        }
                    )

                series_std = merge(wsi_std)
                if not series_std.empty:
                    traces.append(
                        {
                            "name": f"Std Dev WSI (J={window})",
                            "x": series_std["_ts_ms_"].to_list(),
                            "y": series_std[wsi_std.name].to_list(),
                            "mode": "lines",
                            "line": {"width": 2, "dash": "dash", "color": "rgb(0,188,212)"},
                            "yaxis": "y2",
                        }
                    )

                series_var_dir = merge(winddir_var_circular)
                if not series_var_dir.empty:
                    traces.append(
                        {
                            "name": f"Var Dir Circular (J={window})",
                            "x": series_var_dir["_ts_ms_"].to_list(),
                            "y": series_var_dir[winddir_var_circular.name].to_list(),
                            "mode": "lines",
                            "line": {"width": 2, "color": "rgb(244,67,54)"},
                            "yaxis": "y3",
                        }
                    )

                series_std_dir = merge(winddir_std_deg)
                if not series_std_dir.empty:
                    traces.append(
                        {
                            "name": f"Std Dev Dir (°) (J={window})",
                            "x": series_std_dir["_ts_ms_"].to_list(),
                            "y": series_std_dir[winddir_std_deg.name].to_list(),
                            "mode": "lines",
                            "line": {"width": 2, "dash": "dot", "color": "rgb(255,152,0)"},
                            "yaxis": "y4",
                        }
                    )

            if has_path:
                series_path = df_plot[["_ts_ms_", "Path_angle"]].dropna()
                if not series_path.empty:
                    traces.append(
                        {
                            "name": "Path Angle",
                            "x": series_path["_ts_ms_"].to_list(),
                            "y": series_path["Path_angle"].to_list(),
                            "mode": "lines",
                            "line": {"width": 2, "color": "rgb(76,175,80)"},
                            "yaxis": "y5",
                        }
                    )

            layout["yaxis"] = {"title": "Var WSI"}
            layout["yaxis2"] = {"title": "Std Dev WSI", "overlaying": "y", "side": "right", "showgrid": False}
            layout["yaxis3"] = {"title": "Var Dir", "anchor": "x", "side": "left", "position": 0.02}
            layout["yaxis4"] = {"title": "Std Dir (°)", "overlaying": "y3", "side": "right", "showgrid": False}
            layout["yaxis5"] = {"title": "Path Angle (°)", "overlaying": "y", "side": "left", "showgrid": False, "position": 0.14}

        return traces, layout

    def _title_for_selection(self, selection: str) -> str:
        if selection == "rpy":
            return f"Roll / Pitch / Yaw ({self.current_log_name})"
        if selection == "variance":
            return f"Variância RPY/Alt ({self.current_log_name})"
        if selection == "wind":
            return f"Variabilidade do Vento ({self.current_log_name})"
        return f"Posicionamento ({self.current_log_name})"

    def _build_html(self, payload: Dict[str, Any]) -> str:
        data_json = json.dumps(payload, ensure_ascii=False, default=str)
        return f"""
<!DOCTYPE html>
<html lang='pt-BR'>
<head>
  <meta charset='utf-8'>
  <title>Gráficos</title>
  <script src='https://cdn.plot.ly/plotly-2.31.1.min.js'></script>
  <style>
    html, body {{ margin: 0; padding: 0; width: 100%; height: 100%; background: #fafafa; }}
    #chartRoot {{ width: 100%; height: 100%; }}
  </style>
</head>
<body>
  <div id='chartRoot'></div>
  <script>
    const payload = {data_json};
    const root = document.getElementById('chartRoot');
    const layout = payload.layout || {{}};
    layout.height = window.innerHeight - 10;
    function render() {{
      Plotly.newPlot(root, payload.traces || [], layout, {{displayModeBar: false, responsive: true}}).then(() => {{
        if (payload.cursorMs) {{
          updateCursor(payload.cursorMs);
        }}
      }});
    }}
    window.updateCursor = function(tsMs) {{
      const line = {{
        type: 'line', x0: tsMs, x1: tsMs, yref: 'paper', y0: 0, y1: 1,
        line: {{ color: 'red', width: 1 }}
      }};
      Plotly.relayout(root, {{ shapes: [line] }});
    }};
    window.setTimeWindow = function(startMs, endMs) {{
      Plotly.relayout(root, {{ 'xaxis.range': [startMs, endMs] }});
    }};
    window.addEventListener('resize', () => {{ Plotly.Plots.resize(root); }});
    render();
  </script>
</body>
</html>
        """

    # -------- helpers --------
    def _run_js(self, script: str):
        if not self.webview:
            return
        if self._web_ready:
            try:
                self.webview.page().runJavaScript(script)
            except RuntimeError:
                pass
        else:
            self._pending_js.append(script)

    def _on_webview_ready(self, ok: bool):
        self._web_ready = ok
        if not ok:
            return
        if self._last_cursor_ms is not None:
            self.update_cursor(self._last_cursor_ms)
        if self._last_window is not None:
            self.set_time_window(*self._last_window)
        while self._pending_js:
            js = self._pending_js.pop(0)
            try:
                self.webview.page().runJavaScript(js)
            except RuntimeError:
                break

    @staticmethod
    def _to_epoch_ms(ts) -> float:
        if isinstance(ts, (int, float, np.integer, np.floating)):
            return float(ts) * 1000.0 if float(ts) < 1e12 else float(ts)
        try:
            if isinstance(ts, pd.Timestamp):
                return ts.to_datetime64().astype("datetime64[ns]").astype(np.int64) / 1e6
            return pd.Timestamp(ts).to_datetime64().astype("datetime64[ns]").astype(np.int64) / 1e6
        except Exception:
            return 0.0

    def _debug(self, message: str, **context: Any):
        payload = {"msg": message}
        if context:
            payload.update(context)
        try:
            print("[StandardPlotsWidget]" + json.dumps(payload, ensure_ascii=False, default=str))
        except Exception:
            print(f"[StandardPlotsWidget]{message} | {context}")
