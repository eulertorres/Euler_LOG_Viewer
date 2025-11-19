"""Diálogo moderno para baixar logs diretamente do SharePoint."""
from __future__ import annotations

from pathlib import Path
from typing import List

from PyQt6.QtCore import QDate, QSize, QThread, Qt, pyqtSignal, QObject
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.utils.resource_paths import get_appdata_logs_dir, resource_path
from src.utils.sharepoint_downloader import (
    SharePointClient,
    SharePointFlight,
    SharePointProgram,
    available_programs,
)


class SharePointListWorker(QObject):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, client: SharePointClient, program: SharePointProgram):
        super().__init__()
        self.client = client
        self.program = program

    def run(self):
        try:
            flights = self.client.list_flights(self.program)
            self.finished.emit(flights)
        except Exception as exc:  # pragma: no cover - depende da API
            self.error.emit(str(exc))


class SharePointDownloadWorker(QObject):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    progress = pyqtSignal(int, str)

    def __init__(self, client: SharePointClient, flights: List[SharePointFlight], destination: Path):
        super().__init__()
        self.client = client
        self.flights = flights
        self.destination = destination

    def run(self):
        try:
            ctx = self.client.create_context()
            total = len(self.flights)
            downloaded_paths: List[Path] = []
            if total == 0:
                self.finished.emit(downloaded_paths)
                return
            for idx, flight in enumerate(self.flights, start=1):
                percent = int((idx - 1) / total * 100)
                self.progress.emit(percent, f"Baixando {flight.name} ({idx}/{total})")
                local_path = self.client.download_flight(ctx, flight, self.destination)
                downloaded_paths.append(local_path)
            self.progress.emit(100, "Download concluído")
            self.finished.emit(downloaded_paths)
        except Exception as exc:  # pragma: no cover - depende da API
            self.error.emit(str(exc))


class LogDownloadDialog(QDialog):
    """Interface guiada para baixar logs do SharePoint com poucos cliques."""

    logs_downloaded = pyqtSignal(Path, list)

    def __init__(self, client: SharePointClient, parent=None):
        super().__init__(parent)
        self.client = client
        self.setWindowTitle("Baixar logs do SharePoint")
        self.resize(1000, 720)

        self.programs = list(available_programs())
        self.selected_program: SharePointProgram | None = None
        self.all_flights: List[SharePointFlight] = []

        self._list_thread: QThread | None = None
        self._download_thread: QThread | None = None
        self._is_busy = False
        self._current_destination: Path | None = None

        self._build_ui()

    # ------------------------------ UI ---------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        header = QLabel(
            "<h2>Download inteligente de logs</h2>"
            "<p>Escolha um programa, filtre os voos desejados e baixe tudo direto para sua pasta de Logs.</p>"
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        self.program_page = self._build_program_page()
        self.selection_page = self._build_selection_page()
        self.stack.addWidget(self.program_page)
        self.stack.addWidget(self.selection_page)

        buttons_layout = QHBoxLayout()
        self.btn_back = QPushButton("⬅️ Voltar")
        self.btn_back.clicked.connect(self._go_to_program_page)
        self.btn_back.setEnabled(False)
        buttons_layout.addWidget(self.btn_back)

        buttons_layout.addStretch(1)

        self.btn_close = QPushButton("Fechar")
        self.btn_close.clicked.connect(self.reject)
        buttons_layout.addWidget(self.btn_close)

        layout.addLayout(buttons_layout)

    def _build_program_page(self) -> QWidget:
        widget = QWidget()
        page_layout = QVBoxLayout(widget)
        page_layout.addWidget(QLabel("Escolha o programa da aeronave:"))

        self.program_list = QListWidget()
        self.program_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.program_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.program_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.program_list.setGridSize(QSize(180, 180))
        self.program_list.setIconSize(QSize(120, 120))
        self.program_list.itemSelectionChanged.connect(self._on_program_selected)

        for program in self.programs:
            item = QListWidgetItem(program.name)
            icon = self._load_program_icon(program)
            if icon:
                item.setIcon(icon)
            item.setData(Qt.ItemDataRole.UserRole, program)
            item.setToolTip(program.folder_name)
            self.program_list.addItem(item)

        page_layout.addWidget(self.program_list, 1)

        self.btn_program_continue = QPushButton("Continuar ➜")
        self.btn_program_continue.setEnabled(False)
        self.btn_program_continue.clicked.connect(self._go_to_selection_page)
        page_layout.addWidget(self.btn_program_continue)
        return widget

    def _build_selection_page(self) -> QWidget:
        widget = QWidget()
        page_layout = QVBoxLayout(widget)

        self.program_title = QLabel("Programa selecionado")
        self.program_title.setStyleSheet("font-size: 18px; font-weight: bold;")
        page_layout.addWidget(self.program_title)

        filter_layout = QGridLayout()
        filter_layout.addWidget(QLabel("Pesquisar"), 0, 0)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Nome do voo, NS ou qualquer parte do texto...")
        self.search_edit.textChanged.connect(self._apply_filters)
        filter_layout.addWidget(self.search_edit, 0, 1, 1, 3)

        filter_layout.addWidget(QLabel("Data inicial"), 1, 0)
        self.start_date_edit = QDateEdit()
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.dateChanged.connect(self._apply_filters)
        filter_layout.addWidget(self.start_date_edit, 1, 1)

        filter_layout.addWidget(QLabel("Data final"), 1, 2)
        self.end_date_edit = QDateEdit()
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.dateChanged.connect(self._apply_filters)
        filter_layout.addWidget(self.end_date_edit, 1, 3)

        page_layout.addLayout(filter_layout)

        action_layout = QHBoxLayout()
        self.btn_select_all = QPushButton("Selecionar tudo")
        self.btn_select_all.clicked.connect(self._select_all)
        action_layout.addWidget(self.btn_select_all)

        self.btn_clear_selection = QPushButton("Limpar seleção")
        self.btn_clear_selection.clicked.connect(self._clear_selection)
        action_layout.addWidget(self.btn_clear_selection)

        action_layout.addStretch(1)

        page_layout.addLayout(action_layout)

        self.flight_list = QListWidget()
        self.flight_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.flight_list.setAlternatingRowColors(True)
        self.flight_list.itemSelectionChanged.connect(self._update_selection_label)
        page_layout.addWidget(self.flight_list, 1)

        self.selection_label = QLabel("Nenhum voo selecionado")
        page_layout.addWidget(self.selection_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        page_layout.addWidget(self.progress_bar)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        page_layout.addWidget(self.status_label)

        download_layout = QHBoxLayout()
        download_layout.addStretch(1)
        self.btn_download = QPushButton("⬇️ Baixar voos selecionados")
        self.btn_download.setEnabled(False)
        self.btn_download.clicked.connect(self._start_download)
        download_layout.addWidget(self.btn_download)
        page_layout.addLayout(download_layout)

        return widget

    # --------------------------- Programas -------------------------------
    def _load_program_icon(self, program: SharePointProgram) -> QIcon | None:
        if not program.icon_name:
            return None
        icon_path = resource_path("assets", "programs", program.icon_name)
        if not icon_path.exists():
            return None
        pixmap = QPixmap(str(icon_path))
        if pixmap.isNull():
            return None
        return QIcon(pixmap)

    def _on_program_selected(self):
        self.btn_program_continue.setEnabled(bool(self.program_list.selectedItems()))

    def _go_to_selection_page(self):
        items = self.program_list.selectedItems()
        if not items:
            return
        program = items[0].data(Qt.ItemDataRole.UserRole)
        if not isinstance(program, SharePointProgram):
            return
        self.selected_program = program
        self.program_title.setText(f"Programa selecionado: {program.name}")
        self.stack.setCurrentWidget(self.selection_page)
        self.btn_back.setEnabled(True)
        self._load_flights()

    def _go_to_program_page(self):
        if self._is_busy:
            return
        self.stack.setCurrentWidget(self.program_page)
        self.btn_back.setEnabled(False)
        self.status_label.clear()
        self.progress_bar.hide()

    # ---------------------------- Listagem ------------------------------
    def _load_flights(self):
        if not self.selected_program:
            return
        self.flight_list.clear()
        self.all_flights = []
        self._set_busy_state(True)
        self.progress_bar.show()
        self.progress_bar.setRange(0, 0)
        self.status_label.setText("Conectando ao SharePoint e listando voos...")
        self.btn_download.setEnabled(False)

        self.list_worker = SharePointListWorker(self.client, self.selected_program)
        self._list_thread = QThread()
        self.list_worker.moveToThread(self._list_thread)
        self._list_thread.started.connect(self.list_worker.run)
        self.list_worker.finished.connect(self._on_flights_loaded)
        self.list_worker.error.connect(self._on_worker_error)
        self.list_worker.error.connect(self._list_thread.quit)
        self.list_worker.error.connect(self.list_worker.deleteLater)
        self.list_worker.finished.connect(self._list_thread.quit)
        self.list_worker.finished.connect(self.list_worker.deleteLater)
        self._list_thread.finished.connect(self._list_thread.deleteLater)
        self._list_thread.start()

    def _on_flights_loaded(self, flights: List[SharePointFlight]):
        self.all_flights = flights
        if not flights:
            self.status_label.setText("Nenhum voo encontrado nesse programa.")
        else:
            self.status_label.setText(f"{len(flights)} voos encontrados. Selecione um intervalo ou use a busca.")
        self.progress_bar.hide()
        self._set_busy_state(False)
        self._configure_date_filters(flights)
        self._apply_filters()

    def _configure_date_filters(self, flights: List[SharePointFlight]):
        valid_dates = [flight.date for flight in flights if flight.date]
        if not valid_dates:
            today = QDate.currentDate()
            self.start_date_edit.setDate(today)
            self.end_date_edit.setDate(today)
            self.start_date_edit.setEnabled(False)
            self.end_date_edit.setEnabled(False)
            return
        min_date = min(valid_dates)
        max_date = max(valid_dates)
        self.start_date_edit.setEnabled(True)
        self.end_date_edit.setEnabled(True)
        self.start_date_edit.setDate(QDate(min_date.year, min_date.month, min_date.day))
        self.end_date_edit.setDate(QDate(max_date.year, max_date.month, max_date.day))

    def _set_busy_state(self, busy: bool):
        self._is_busy = busy
        self.btn_close.setEnabled(not busy)
        self.btn_back.setEnabled(not busy and self.stack.currentWidget() == self.selection_page)
        self.btn_program_continue.setEnabled(not busy and bool(self.program_list.selectedItems()))
        if not busy:
            self.progress_bar.setRange(0, 100)

    def _on_worker_error(self, message: str):
        self.progress_bar.hide()
        self._set_busy_state(False)
        QMessageBox.critical(self, "Erro ao acessar o SharePoint", message)

    # ------------------------------ Filtros ------------------------------
    def _apply_filters(self):
        if not self.all_flights:
            self.flight_list.clear()
            return
        text_filter = self.search_edit.text().strip().lower()
        start_date = self.start_date_edit.date()
        end_date = self.end_date_edit.date()
        if start_date > end_date:
            start_date, end_date = end_date, start_date
        self.flight_list.clear()

        for flight in self.all_flights:
            if flight.date:
                flight_qdate = QDate(flight.date.year, flight.date.month, flight.date.day)
                if flight_qdate < start_date or flight_qdate > end_date:
                    continue
            if text_filter:
                normalized = f"{flight.name} {flight.serial_folder or ''}".lower()
                if text_filter not in normalized:
                    continue
            item = QListWidgetItem(flight.human_label())
            item.setData(Qt.ItemDataRole.UserRole, flight)
            self.flight_list.addItem(item)

        self.status_label.setText(f"Mostrando {self.flight_list.count()} voos dentro do filtro.")
        self._update_selection_label()

    def _select_all(self):
        self.flight_list.selectAll()

    def _clear_selection(self):
        self.flight_list.clearSelection()

    def _update_selection_label(self):
        count = len(self.flight_list.selectedItems())
        if count == 0:
            text = "Nenhum voo selecionado."
        elif count == 1:
            text = "1 voo selecionado."
        else:
            text = f"{count} voos selecionados."
        self.selection_label.setText(text)
        self.btn_download.setEnabled(count > 0 and not self._is_busy)

    # ------------------------------ Download ----------------------------
    def _selected_flights(self) -> List[SharePointFlight]:
        flights: List[SharePointFlight] = []
        for item in self.flight_list.selectedItems():
            flight = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(flight, SharePointFlight):
                flights.append(flight)
        return flights

    def _start_download(self):
        if self._is_busy:
            return
        flights = self._selected_flights()
        if not flights:
            QMessageBox.information(self, "Nada selecionado", "Escolha ao menos um voo para baixar.")
            return
        destination = get_appdata_logs_dir(create=True)
        destination.mkdir(parents=True, exist_ok=True)
        self._current_destination = destination
        self.progress_bar.show()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.status_label.setText(f"Preparando download de {len(flights)} voos...")
        self._set_busy_state(True)

        self.download_worker = SharePointDownloadWorker(self.client, flights, destination)
        self._download_thread = QThread()
        self.download_worker.moveToThread(self._download_thread)
        self._download_thread.started.connect(self.download_worker.run)
        self.download_worker.progress.connect(self._on_download_progress)
        self.download_worker.finished.connect(self._on_download_finished)
        self.download_worker.error.connect(self._on_worker_error)
        self.download_worker.error.connect(self._download_thread.quit)
        self.download_worker.error.connect(self.download_worker.deleteLater)
        self.download_worker.finished.connect(self._download_thread.quit)
        self.download_worker.finished.connect(self.download_worker.deleteLater)
        self._download_thread.finished.connect(self._download_thread.deleteLater)
        self._download_thread.start()

    def _on_download_progress(self, percent: int, message: str):
        self.progress_bar.setValue(percent)
        self.status_label.setText(message)

    def _on_download_finished(self, local_paths: List[Path]):
        self._set_busy_state(False)
        self.progress_bar.hide()
        self.status_label.setText(
            f"Download finalizado. {len(local_paths)} voos foram salvos na pasta de logs."
        )
        destination = self._current_destination or get_appdata_logs_dir(create=True)
        QMessageBox.information(
            self,
            "Download concluído",
            f"{len(local_paths)} voos foram salvos em {destination}",
        )
        self.logs_downloaded.emit(destination, local_paths)
        self._current_destination = None

    # ------------------------------ Qt Events ---------------------------
    def closeEvent(self, event):
        if self._is_busy:
            QMessageBox.information(
                self,
                "Download em andamento",
                "Aguarde o término do processamento antes de fechar esta janela.",
            )
            event.ignore()
            return
        super().closeEvent(event)
