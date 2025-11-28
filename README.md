# Xmobots Log Viewer

Xmobots Log Viewer is a PyQt6 desktop application for exploring UAV telemetry logs with synchronized maps, timelines, and plotting tools. It supports multiple log formats, lets you visualize flights on interactive folium and Cesium maps, compare metrics across datasets, and export reports for sharing.

## Key features
- Load datalogger CSVs, embedded `.mat` files, and `.spi` binaries (decoded via the bundled `decoder.exe`).
- Interactive positioning tab with folium maps, aircraft and wind indicators, and a synchronized timestamp slider.
- Standard, all-in-one, and custom plotting tabs with PyQtGraph/Matplotlib visualizations and cursor-synced timelines.
- Multi-log analysis so you can overlay and compare signals from several logs at once.
- Built-in SharePoint download dialog for grabbing new logs without leaving the app.
- Optional PDF report generation for quick summaries.

## Requirements
- Python 3.10 or newer.
- System packages required by PyQt6 and PyQt6-WebEngine (ensure Qt WebEngine is available on your platform).
- A local copy of `decoder.exe` when opening `.spi` logs (the app searches under `src/decoder.exe` or the working directory).

All Python dependencies are pinned in [`requirements.txt`](requirements.txt).

## Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/your-org/XmobotsLogViewer.git
   cd XmobotsLogViewer
   ```
2. (Optional) Create and activate a virtual environment.
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Running the application
1. Place your telemetry files in the default logs directory. The app prefers `XmobotsLogViewer/Logs` inside your user data folder, but you can override it with the `XMOBOTS_LOG_DIR` environment variable. If neither exists, the bundled `logs de teste` folder is used as a fallback.
2. Launch the viewer:
   ```bash
   python run.py
   ```
3. Use the file picker to select a log or the SharePoint dialog to download new logs. The window opens on the positioning tab, and switching logs keeps the view centered there for quick inspection.

## Supported data sources
- **Datalogger CSV (`log**.csv`)**: Parsed directly for plotting and mapping.
- **Embedded MATLAB (`*.mat`)**: Loaded for standard and custom plots.
- **Embedded SPI (`*.spi`)**: Decoded through `decoder.exe` before being processed into Pandas DataFrames.

## Tips for using the UI
- Use the timeline slider to scrub through the flight; indicators update on both the map and plots.
- The "Todos Gráficos" tab offers quick access to combined plots, while the comparison tool lets you pick the X-axis and stack signals from multiple logs.
- Custom plots allow you to mix signals from different logs when you need specialized diagnostics.
- When PDF export is enabled, start the export and wait for the progress dialog to finish before closing the app.

## Project structure
- `run.py` – application entry point that launches the Qt event loop.
- `src/main_window.py` – main window wiring together tabs, map server, timeline, and worker threads.
- `src/data_parser.py` – log parsing and decoding helpers for CSV, MAT, and SPI sources.
- `src/widgets/` – UI widgets for standard plots, all-plots view, custom plots, and dialogs.
- `src/utils/` – helpers for resource discovery, SharePoint downloads, PDF reporting, and the local folium map server.
- `assets/` – icons, 3D models, and supporting static files for the map and timeline views.

## Changelog
See [`changelog.txt`](changelog.txt) for a history of notable changes.
