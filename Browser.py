import json
import os
import sys
from fnmatch import fnmatch
from datetime import datetime
from pathlib import Path

if "QTWEBENGINE_DISABLE_SANDBOX" not in os.environ:
    os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"

from PySide6.QtCore import QStandardPaths, QSize, Qt, QUrl
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWebEngineCore import (
    QWebEngineDownloadRequest,
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineSettings,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QToolBar,
)


APP_NAME = "CodexBrowser"
MAX_HISTORY_ITEMS = 5000
MAX_BOOKMARKS = 3000
START_PAGE_URL = QUrl("codex://start")
MAX_CLOSED_TABS = 25


class BrowserPage(QWebEnginePage):
    def __init__(self, profile, browser_window, parent=None):
        super().__init__(profile, parent)
        self.browser_window = browser_window

    def chooseFiles(self, mode, old_files, accepted_mime_types):
        del accepted_mime_types
        start_path = old_files[0] if old_files else str(Path.home())

        if mode == QWebEnginePage.FileSelectionMode.FileSelectOpenMultiple:
            files, _ = QFileDialog.getOpenFileNames(
                self.browser_window, "Dateien hochladen", start_path, "Alle Dateien (*)"
            )
            return files

        if mode == QWebEnginePage.FileSelectionMode.FileSelectUploadFolder:
            folder = QFileDialog.getExistingDirectory(
                self.browser_window, "Ordner hochladen", start_path
            )
            return [folder] if folder else []

        if mode == QWebEnginePage.FileSelectionMode.FileSelectSave:
            file_path, _ = QFileDialog.getSaveFileName(
                self.browser_window, "Datei speichern", start_path, "Alle Dateien (*)"
            )
            return [file_path] if file_path else []

        file_path, _ = QFileDialog.getOpenFileName(
            self.browser_window, "Datei hochladen", start_path, "Alle Dateien (*)"
        )
        return [file_path] if file_path else []

    def createWindow(self, window_type):
        del window_type
        view = self.browser_window.add_new_tab(self.browser_window.home_url, switch=True)
        if not view:
            return None
        return view.page()


class BrowserWindow(QMainWindow):
    def __init__(self, private_mode=False):
        super().__init__()
        self.private_mode = private_mode
        self.home_url = START_PAGE_URL
        self.webgl_enabled = True
        self.dark_mode_enabled = False
        self.current_zoom = 1.0
        self.data = {"bookmarks": [], "history": []}
        self.data_file = self._resolve_data_file()
        self.profile_dir = self._resolve_profile_dir()
        self.download_dir = self._resolve_download_dir()
        self.open_downloads = {}
        self.closed_tabs = []
        self.profile = self._create_profile()

        self._load_data()
        self._apply_webgl_setting()
        self._build_ui()
        self._create_actions()
        self._create_menus()
        self._create_toolbar()
        self._connect_signals()
        self.add_new_tab(self.home_url, switch=True)
        self._refresh_sidebar()
        self._update_window_title()

    def _resolve_data_file(self):
        if self.private_mode:
            return None
        base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
        if not base:
            base = str(Path.home() / f".{APP_NAME.lower()}")
        data_dir = Path(base)
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / "browser_data.json"

    def _resolve_download_dir(self):
        download = QStandardPaths.writableLocation(QStandardPaths.DownloadLocation)
        if not download:
            download = str(Path.home() / "Downloads")
        return Path(download)

    def _resolve_profile_dir(self):
        if self.private_mode:
            return None
        base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
        if not base:
            base = str(Path.home() / f".{APP_NAME.lower()}")
        profile_dir = Path(base) / "web_profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        return profile_dir

    def _create_profile(self):
        if self.private_mode:
            profile = QWebEngineProfile(self)
            profile.setHttpCacheType(QWebEngineProfile.MemoryHttpCache)
            profile.setPersistentCookiesPolicy(QWebEngineProfile.NoPersistentCookies)
            profile.downloadRequested.connect(self._on_download_requested)
            return profile

        profile = QWebEngineProfile("CodexBrowserProfile", self)
        if self.profile_dir is not None:
            profile.setPersistentStoragePath(str(self.profile_dir / "storage"))
            profile.setCachePath(str(self.profile_dir / "cache"))
        profile.setHttpCacheType(QWebEngineProfile.DiskHttpCache)
        profile.setPersistentCookiesPolicy(QWebEngineProfile.ForcePersistentCookies)
        profile.downloadRequested.connect(self._on_download_requested)
        return profile

    def _load_data(self):
        if self.private_mode or self.data_file is None:
            return
        if not self.data_file.exists():
            return
        try:
            self.data = json.loads(self.data_file.read_text(encoding="utf-8"))
            if not isinstance(self.data, dict):
                self.data = {"bookmarks": [], "history": []}
        except Exception:
            self.data = {"bookmarks": [], "history": []}
        self._sanitize_data()
        self._load_settings()

    def _save_data(self):
        if self.private_mode or self.data_file is None:
            return
        try:
            self.data_file.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    def _sanitize_data(self):
        if not isinstance(self.data, dict):
            self.data = {"bookmarks": [], "history": []}
            return

        bookmarks = self.data.get("bookmarks", [])
        history = self.data.get("history", [])
        settings = self.data.get("settings", {})
        extensions = self.data.get("extensions", [])
        downloads = self.data.get("downloads", [])
        self.data["bookmarks"] = bookmarks if isinstance(bookmarks, list) else []
        self.data["history"] = history if isinstance(history, list) else []
        self.data["settings"] = settings if isinstance(settings, dict) else {}
        self.data["extensions"] = extensions if isinstance(extensions, list) else []
        self.data["downloads"] = downloads if isinstance(downloads, list) else []

    def _load_settings(self):
        settings = self.data.get("settings", {})
        home_raw = settings.get("home_url", "")
        if home_raw:
            parsed = QUrl(home_raw)
            if parsed.isValid():
                self.home_url = parsed

        download_raw = settings.get("download_dir", "")
        if download_raw:
            candidate = Path(download_raw)
            if candidate.exists() and candidate.is_dir():
                self.download_dir = candidate

        self.webgl_enabled = bool(settings.get("webgl_enabled", True))
        self.dark_mode_enabled = bool(settings.get("dark_mode_enabled", False))

    def _persist_setting(self, key, value):
        if self.private_mode:
            return
        self.data.setdefault("settings", {})[key] = value
        self._save_data()

    def _build_ui(self):
        self.resize(1400, 900)
        self.setUnifiedTitleAndToolBarOnMac(True)
        mode = "Privat" if self.private_mode else "Standard"
        self.setWindowTitle(f"{APP_NAME} ({mode})")

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.progress_label = QLabel("")
        self.progress_label.setMinimumWidth(90)
        self.progress_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.status_bar.addPermanentWidget(self.progress_label)

        self.splitter = QSplitter(Qt.Horizontal)
        self.sidebar = QListWidget()
        self.sidebar.setMinimumWidth(240)
        self.sidebar.setMaximumWidth(360)
        self.sidebar.setAlternatingRowColors(True)
        self.sidebar.hide()

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setElideMode(Qt.ElideRight)

        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.tabs)
        self.splitter.setSizes([280, 1120])

        self.setCentralWidget(self.splitter)

        self.urlbar = QLineEdit()
        self.urlbar.setClearButtonEnabled(True)
        self.urlbar.setMinimumWidth(520)
        self.urlbar.setPlaceholderText("Suchbegriff oder URL eingeben")
        self._apply_styles()

    def _create_actions(self):
        self.back_action = QAction("◀ Zurück", self)
        self.back_action.setStatusTip("Zurück")
        self.back_action.setShortcut(QKeySequence.StandardKey.Back)
        self.back_action.triggered.connect(lambda: self.current_view().back())

        self.forward_action = QAction("▶ Vorwärts", self)
        self.forward_action.setStatusTip("Vorwärts")
        self.forward_action.setShortcut(QKeySequence.StandardKey.Forward)
        self.forward_action.triggered.connect(lambda: self.current_view().forward())

        self.reload_action = QAction("⟳ Neu laden", self)
        self.reload_action.setStatusTip("Neu laden")
        self.reload_action.setShortcut(QKeySequence.StandardKey.Refresh)
        self.reload_action.triggered.connect(lambda: self.current_view().reload())

        self.stop_action = QAction("⨯ Stopp", self)
        self.stop_action.setStatusTip("Stopp")
        self.stop_action.triggered.connect(lambda: self.current_view().stop())

        self.home_action = QAction("⌂ Start", self)
        self.home_action.setStatusTip("Startseite")
        self.home_action.triggered.connect(self.navigate_home)

        self.new_tab_action = QAction("Neuer Tab", self)
        self.new_tab_action.setShortcut(QKeySequence("Ctrl+T"))
        self.new_tab_action.triggered.connect(lambda: self.add_new_tab(self.home_url, switch=True))

        self.close_tab_action = QAction("Tab schließen", self)
        self.close_tab_action.setShortcut(QKeySequence.StandardKey.Close)
        self.close_tab_action.triggered.connect(lambda: self.close_tab(self.tabs.currentIndex()))

        self.new_window_action = QAction("Neues Fenster", self)
        self.new_window_action.setShortcut(QKeySequence("Ctrl+N"))
        self.new_window_action.triggered.connect(self.open_new_window)

        self.private_window_action = QAction("Neues privates Fenster", self)
        self.private_window_action.setShortcut(QKeySequence("Ctrl+Shift+N"))
        self.private_window_action.triggered.connect(self.open_private_window)

        self.find_action = QAction("Auf Seite suchen", self)
        self.find_action.setShortcut(QKeySequence.Find)
        self.find_action.triggered.connect(self.find_in_page)

        self.focus_urlbar_action = QAction("Adressleiste fokussieren", self)
        self.focus_urlbar_action.setShortcut(QKeySequence("Ctrl+L"))
        self.focus_urlbar_action.triggered.connect(self.focus_urlbar)

        self.zoom_in_action = QAction("Zoom +", self)
        self.zoom_in_action.setShortcut(QKeySequence.ZoomIn)
        self.zoom_in_action.triggered.connect(lambda: self.change_zoom(0.1))

        self.zoom_out_action = QAction("Zoom -", self)
        self.zoom_out_action.setShortcut(QKeySequence.ZoomOut)
        self.zoom_out_action.triggered.connect(lambda: self.change_zoom(-0.1))

        self.zoom_reset_action = QAction("Zoom zurücksetzen", self)
        self.zoom_reset_action.setShortcut(QKeySequence("Ctrl+0"))
        self.zoom_reset_action.triggered.connect(self.reset_zoom)

        self.add_bookmark_action = QAction("★ Lesezeichen", self)
        self.add_bookmark_action.setStatusTip("Lesezeichen hinzufügen")
        self.add_bookmark_action.setShortcut(QKeySequence("Ctrl+D"))
        self.add_bookmark_action.triggered.connect(self.add_bookmark)

        self.toggle_sidebar_action = QAction("Seitenleiste zeigen/verstecken", self)
        self.toggle_sidebar_action.setShortcut(QKeySequence("Ctrl+B"))
        self.toggle_sidebar_action.triggered.connect(self.toggle_sidebar)

        self.clear_history_action = QAction("Verlauf löschen", self)
        self.clear_history_action.triggered.connect(self.clear_history)

        self.show_download_history_action = QAction("Download-Verlauf anzeigen", self)
        self.show_download_history_action.triggered.connect(self.show_download_history)

        self.clear_download_history_action = QAction("Download-Verlauf löschen", self)
        self.clear_download_history_action.triggered.connect(self.clear_download_history)

        self.clear_bookmarks_action = QAction("Lesezeichen löschen", self)
        self.clear_bookmarks_action.triggered.connect(self.clear_bookmarks)

        self.set_home_action = QAction("Startseite festlegen", self)
        self.set_home_action.triggered.connect(self.set_homepage)

        self.downloads_action = QAction("Download-Ziel ändern", self)
        self.downloads_action.triggered.connect(self.set_download_folder)

        self.clear_site_data_action = QAction("Cookies/Webdaten löschen", self)
        self.clear_site_data_action.triggered.connect(self.clear_site_data)

        self.toggle_webgl_action = QAction("WebGL aktivieren", self)
        self.toggle_webgl_action.setCheckable(True)
        self.toggle_webgl_action.setChecked(self.webgl_enabled)
        self.toggle_webgl_action.triggered.connect(self.set_webgl_enabled)

        self.dark_mode_action = QAction("Dark Mode", self)
        self.dark_mode_action.setCheckable(True)
        self.dark_mode_action.setChecked(self.dark_mode_enabled)
        self.dark_mode_action.triggered.connect(self.set_dark_mode_enabled)

        self.save_page_action = QAction("Seite speichern unter...", self)
        self.save_page_action.setShortcut(QKeySequence.Save)
        self.save_page_action.triggered.connect(self.save_current_page)

        self.save_pdf_action = QAction("Als PDF speichern...", self)
        self.save_pdf_action.setShortcut(QKeySequence("Ctrl+Shift+P"))
        self.save_pdf_action.triggered.connect(self.save_current_pdf)

        self.screenshot_action = QAction("Screenshot speichern...", self)
        self.screenshot_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.screenshot_action.triggered.connect(self.save_page_screenshot)

        self.upload_action = QAction("Datei hochladen...", self)
        self.upload_action.setShortcut(QKeySequence("Ctrl+Shift+U"))
        self.upload_action.triggered.connect(self.trigger_upload_dialog)

        self.open_file_action = QAction("Datei öffnen", self)
        self.open_file_action.setShortcut(QKeySequence.Open)
        self.open_file_action.triggered.connect(self.open_local_file)

        self.install_extension_action = QAction("Erweiterung installieren (.js)", self)
        self.install_extension_action.triggered.connect(self.install_extension)

        self.list_extensions_action = QAction("Erweiterungen anzeigen", self)
        self.list_extensions_action.triggered.connect(self.show_extensions)

        self.toggle_extension_action = QAction("Erweiterung aktivieren/deaktivieren", self)
        self.toggle_extension_action.triggered.connect(self.toggle_extension_enabled)

        self.remove_extension_action = QAction("Erweiterung entfernen", self)
        self.remove_extension_action.triggered.connect(self.remove_extension)

        self.duplicate_tab_action = QAction("Tab duplizieren", self)
        self.duplicate_tab_action.setShortcut(QKeySequence("Ctrl+Shift+D"))
        self.duplicate_tab_action.triggered.connect(self.duplicate_current_tab)

        self.reopen_tab_action = QAction("Geschlossenen Tab wiederherstellen", self)
        self.reopen_tab_action.setShortcut(QKeySequence("Ctrl+Shift+T"))
        self.reopen_tab_action.triggered.connect(self.reopen_last_closed_tab)

        self.pin_tab_action = QAction("Tab anheften", self)
        self.pin_tab_action.setCheckable(True)
        self.pin_tab_action.setShortcut(QKeySequence("Ctrl+Shift+L"))
        self.pin_tab_action.triggered.connect(self.set_current_tab_pinned)

        self.copy_url_action = QAction("URL kopieren", self)
        self.copy_url_action.setShortcut(QKeySequence("Ctrl+Shift+C"))
        self.copy_url_action.triggered.connect(self.copy_current_url)

        self.view_source_action = QAction("Seitenquelltext anzeigen", self)
        self.view_source_action.setShortcut(QKeySequence("Ctrl+U"))
        self.view_source_action.triggered.connect(self.open_page_source)

        self.toggle_mute_action = QAction("Tab stummschalten", self)
        self.toggle_mute_action.setCheckable(True)
        self.toggle_mute_action.setShortcut(QKeySequence("Ctrl+M"))
        self.toggle_mute_action.triggered.connect(self.set_current_tab_muted)

        self.fullscreen_action = QAction("Vollbild", self)
        self.fullscreen_action.setCheckable(True)
        self.fullscreen_action.setShortcut(QKeySequence("F11"))
        self.fullscreen_action.triggered.connect(self.toggle_fullscreen)

        self.reader_mode_action = QAction("Lesemodus", self)
        self.reader_mode_action.setCheckable(True)
        self.reader_mode_action.setShortcut(QKeySequence("Ctrl+Alt+R"))
        self.reader_mode_action.triggered.connect(self.toggle_reader_mode)

        self.reload_all_tabs_action = QAction("Alle Tabs neu laden", self)
        self.reload_all_tabs_action.setShortcut(QKeySequence("Ctrl+Shift+R"))
        self.reload_all_tabs_action.triggered.connect(self.reload_all_tabs)

    def _create_menus(self):
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("Datei")
        file_menu.addAction(self.new_tab_action)
        file_menu.addAction(self.new_window_action)
        file_menu.addAction(self.private_window_action)
        file_menu.addSeparator()
        file_menu.addAction(self.open_file_action)
        file_menu.addAction(self.save_page_action)
        file_menu.addAction(self.save_pdf_action)
        file_menu.addAction(self.screenshot_action)
        file_menu.addAction(self.upload_action)
        file_menu.addSeparator()
        file_menu.addAction(self.duplicate_tab_action)
        file_menu.addAction(self.reopen_tab_action)
        file_menu.addSeparator()
        file_menu.addAction(self.close_tab_action)

        nav_menu = menu_bar.addMenu("Navigation")
        nav_menu.addAction(self.back_action)
        nav_menu.addAction(self.forward_action)
        nav_menu.addAction(self.reload_action)
        nav_menu.addAction(self.stop_action)
        nav_menu.addAction(self.home_action)
        nav_menu.addSeparator()
        nav_menu.addAction(self.find_action)
        nav_menu.addAction(self.focus_urlbar_action)
        nav_menu.addAction(self.copy_url_action)
        nav_menu.addAction(self.view_source_action)
        nav_menu.addAction(self.reload_all_tabs_action)

        view_menu = menu_bar.addMenu("Ansicht")
        view_menu.addAction(self.zoom_in_action)
        view_menu.addAction(self.zoom_out_action)
        view_menu.addAction(self.zoom_reset_action)
        view_menu.addSeparator()
        view_menu.addAction(self.pin_tab_action)
        view_menu.addAction(self.toggle_mute_action)
        view_menu.addAction(self.reader_mode_action)
        view_menu.addAction(self.fullscreen_action)
        view_menu.addSeparator()
        view_menu.addAction(self.toggle_sidebar_action)

        bookmarks_menu = menu_bar.addMenu("Lesezeichen")
        bookmarks_menu.addAction(self.add_bookmark_action)
        bookmarks_menu.addAction(self.clear_bookmarks_action)

        history_menu = menu_bar.addMenu("Verlauf")
        history_menu.addAction(self.clear_history_action)
        history_menu.addAction(self.show_download_history_action)
        history_menu.addAction(self.clear_download_history_action)

        ext_menu = menu_bar.addMenu("Erweiterungen")
        ext_menu.addAction(self.install_extension_action)
        ext_menu.addAction(self.list_extensions_action)
        ext_menu.addAction(self.toggle_extension_action)
        ext_menu.addAction(self.remove_extension_action)

        settings_menu = menu_bar.addMenu("Einstellungen")
        settings_menu.addAction(self.set_home_action)
        settings_menu.addAction(self.downloads_action)
        settings_menu.addAction(self.toggle_webgl_action)
        settings_menu.addAction(self.dark_mode_action)
        settings_menu.addAction(self.clear_site_data_action)

    def _create_toolbar(self):
        nav = QToolBar("Navigation")
        self.nav_toolbar = nav
        nav.setMovable(False)
        nav.setIconSize(QSize(16, 16))
        self.addToolBar(nav)

        nav.addAction(self.back_action)
        nav.addAction(self.forward_action)
        nav.addAction(self.reload_action)
        nav.addAction(self.stop_action)
        nav.addAction(self.home_action)
        nav.addSeparator()
        nav.addWidget(self.urlbar)
        nav.addSeparator()
        nav.addAction(self.new_tab_action)
        nav.addAction(self.add_bookmark_action)

    def _apply_styles(self):
        if self.dark_mode_enabled:
            self.setStyleSheet(
                """
                * {
                    font-family: "Avenir Next", "Avenir", "Helvetica Neue", "Segoe UI", sans-serif;
                }
                QMainWindow { background: #0f172a; }
                QMenuBar {
                    background: #111c33;
                    border-bottom: 1px solid #24344e;
                    padding: 4px 6px;
                    color: #dbe7ff;
                }
                QMenuBar::item { padding: 6px 10px; border-radius: 7px; }
                QMenuBar::item:selected { background: #223454; }
                QToolBar {
                    background: #111c33;
                    border-bottom: 1px solid #24344e;
                    spacing: 8px;
                    padding: 10px 8px;
                }
                QToolButton {
                    background: #1a2944;
                    border: 1px solid #2f456a;
                    border-radius: 11px;
                    padding: 8px 13px;
                    font-weight: 600;
                    color: #d9e8ff;
                    min-width: 30px;
                }
                QToolButton:hover { background: #233657; border: 1px solid #4a6798; }
                QToolButton:pressed { background: #30486f; }
                QLineEdit {
                    background: #131f36;
                    border: 1px solid #344c73;
                    border-radius: 14px;
                    padding: 10px 14px;
                    color: #ecf3ff;
                    selection-background-color: #2f6fda;
                }
                QLineEdit:focus { border: 1px solid #68a0ff; }
                QTabWidget::pane {
                    border: 1px solid #263751;
                    border-top: none;
                    background: #101a2f;
                }
                QTabBar::tab {
                    background: #1a2a46;
                    border: 1px solid #304766;
                    border-bottom: none;
                    border-top-left-radius: 11px;
                    border-top-right-radius: 11px;
                    padding: 10px 15px;
                    margin-right: 5px;
                    color: #bdd2f6;
                }
                QTabBar::tab:selected {
                    background: #101a2f;
                    color: #eef4ff;
                    border-color: #5d83be;
                }
                QListWidget {
                    background: #111b30;
                    border: 1px solid #24344e;
                    border-right: 1px solid #2d3f5f;
                    outline: none;
                    padding: 8px;
                    color: #dbe8ff;
                }
                QListWidget::item {
                    padding: 8px 10px;
                    border-radius: 8px;
                    color: #dbe8ff;
                }
                QListWidget::item:selected {
                    background: #26406a;
                    color: #ffffff;
                }
                QSplitter::handle { background: #2b3f5f; width: 2px; }
                QStatusBar {
                    background: #111c33;
                    border-top: 1px solid #24344e;
                    color: #bcd0f0;
                }
                """
            )
            return
        self.setStyleSheet(
            """
            * {
                font-family: "Avenir Next", "Avenir", "Helvetica Neue", "Segoe UI", sans-serif;
            }
            QMainWindow {
                background: #e7edf7;
            }
            QMenuBar {
                background: #f8fbff;
                border-bottom: 1px solid #c7d4e7;
                padding: 4px 6px;
            }
            QMenuBar::item {
                padding: 6px 10px;
                border-radius: 7px;
                color: #0f1f3d;
            }
            QMenuBar::item:selected {
                background: #dce9fb;
            }
            QToolBar {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #f8fbff, stop: 1 #edf4ff
                );
                border-bottom: 1px solid #c9d8ee;
                spacing: 8px;
                padding: 10px 8px;
            }
            QToolButton {
                background: #ffffff;
                border: 1px solid #c4d4ea;
                border-radius: 11px;
                padding: 8px 13px;
                font-weight: 600;
                color: #11284d;
                min-width: 30px;
            }
            QToolButton:hover {
                background: #edf4ff;
                border: 1px solid #96b4e1;
            }
            QToolButton:pressed {
                background: #d4e5ff;
            }
            QLineEdit {
                background: #ffffff;
                border: 1px solid #bfd0e8;
                border-radius: 14px;
                padding: 10px 14px;
                color: #0f1f3d;
                selection-background-color: #2f6fda;
            }
            QLineEdit:focus {
                border: 1px solid #2f6fda;
                background: #fdfefe;
            }
            QTabWidget::pane {
                border: 1px solid #c7d4e7;
                border-top: none;
                background: #fbfdff;
            }
            QTabBar::tab {
                background: #e9f1ff;
                border: 1px solid #c8d6eb;
                border-bottom: none;
                border-top-left-radius: 11px;
                border-top-right-radius: 11px;
                padding: 10px 15px;
                margin-right: 5px;
                color: #31496e;
            }
            QTabBar::tab:selected {
                background: #fbfdff;
                color: #0f1f3d;
                border-color: #a7bfdf;
            }
            QListWidget {
                background: #f3f8ff;
                border: 1px solid #c9d8eb;
                border-right: 1px solid #bdcde2;
                outline: none;
                padding: 8px;
            }
            QListWidget::item {
                padding: 8px 10px;
                border-radius: 8px;
                color: #1d355a;
            }
            QListWidget::item:selected {
                background: #d3e5ff;
                color: #0f1f3d;
            }
            QSplitter::handle {
                background: #d5e1f1;
                width: 2px;
            }
            QStatusBar {
                background: #f8fbff;
                border-top: 1px solid #c9d8eb;
                color: #3a5378;
            }
            """
        )

    def _connect_signals(self):
        self.urlbar.returnPressed.connect(self.navigate_to_input)
        self.tabs.currentChanged.connect(self._on_current_tab_changed)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.sidebar.itemActivated.connect(self._open_sidebar_item)

    def _update_window_title(self):
        current = self.current_view()
        page_title = current.title() if current else APP_NAME
        mode = "Privat" if self.private_mode else "Standard"
        self.setWindowTitle(f"{page_title} - {APP_NAME} ({mode})")

    def current_view(self):
        widget = self.tabs.currentWidget()
        if isinstance(widget, QWebEngineView):
            return widget
        return None

    def add_new_tab(self, url=None, switch=True, label="Neuer Tab"):
        if url is None:
            url = self.home_url
        if isinstance(url, str):
            url = self._normalize_input_to_url(url)
        if not isinstance(url, QUrl):
            url = self.home_url

        view = QWebEngineView()
        page = BrowserPage(self.profile, self, view)
        page.settings().setAttribute(QWebEngineSettings.LocalStorageEnabled, True)
        page.settings().setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        page.settings().setAttribute(QWebEngineSettings.AutoLoadImages, True)
        page.settings().setAttribute(QWebEngineSettings.WebGLEnabled, self.webgl_enabled)
        view.setPage(page)
        view.setZoomFactor(self.current_zoom)
        view.loadFinished.connect(lambda ok, v=view: self._on_load_finished(v, ok))
        view.urlChanged.connect(lambda qurl, v=view: self._on_url_changed(v, qurl))
        view.titleChanged.connect(lambda _, v=view: self._update_tab_title(v))
        view.loadProgress.connect(self._on_load_progress)
        view.setProperty("reader_mode", False)
        self._open_url(view, url)

        idx = self.tabs.addTab(view, label)
        if switch:
            self.tabs.setCurrentIndex(idx)
        return view

    def close_tab(self, index):
        if index < 0 or index >= self.tabs.count():
            return
        if self.tabs.count() <= 1:
            self.close()
            return
        view = self.tabs.widget(index)
        if isinstance(view, QWebEngineView):
            if bool(view.property("pinned")):
                self.status_bar.showMessage("Angeheftete Tabs zuerst lösen.", 2200)
                return
            closed_url = view.url().toString()
            if closed_url:
                self.closed_tabs.insert(0, closed_url)
                self.closed_tabs = self.closed_tabs[:MAX_CLOSED_TABS]
        self.tabs.removeTab(index)
        if view is not None:
            view.deleteLater()

    def _on_current_tab_changed(self, _index):
        view = self.current_view()
        if not view:
            return
        self.urlbar.setText(view.url().toString())
        self.toggle_mute_action.setChecked(view.page().isAudioMuted())
        self.pin_tab_action.setChecked(bool(view.property("pinned")))
        self.reader_mode_action.setChecked(bool(view.property("reader_mode")))
        self._update_window_title()

    def _update_tab_title(self, view):
        idx = self.tabs.indexOf(view)
        if idx == -1:
            return
        title = self._tab_label_text(view)
        self.tabs.setTabText(idx, title[:32])
        if view is self.current_view():
            self._update_window_title()

    def _tab_label_text(self, view):
        base_title = view.title().strip() or "Neuer Tab"
        if bool(view.property("pinned")):
            return f"📌 {base_title}"
        return base_title

    def _on_url_changed(self, view, qurl):
        if view is self.current_view():
            self.urlbar.setText(qurl.toString())
            self.reader_mode_action.setChecked(False)
        view.setProperty("reader_mode", False)
        self._update_tab_title(view)

    def _normalize_input_to_url(self, text):
        raw = text.strip()
        if not raw:
            return self.home_url
        if raw == "codex://start":
            return START_PAGE_URL
        if raw.startswith(("http://", "https://", "file://")):
            return QUrl(raw)
        if "://" in raw:
            parsed = QUrl(raw)
            if parsed.isValid():
                return parsed
        if " " in raw:
            query = QUrl.toPercentEncoding(raw).data().decode("utf-8")
            return QUrl(f"https://www.google.com/search?q={query}")
        if "." in raw:
            return QUrl(f"https://{raw}")
        query = QUrl.toPercentEncoding(raw).data().decode("utf-8")
        return QUrl(f"https://www.google.com/search?q={query}")

    def navigate_to_input(self):
        url = self._normalize_input_to_url(self.urlbar.text())
        view = self.current_view()
        if view:
            self._open_url(view, url)

    def navigate_home(self):
        view = self.current_view()
        if view:
            self._open_url(view, self.home_url)

    def focus_urlbar(self):
        self.urlbar.setFocus()
        self.urlbar.selectAll()

    def open_local_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Datei öffnen", str(Path.home()), "Alle Dateien (*)"
        )
        if file_path:
            self._open_url(self.current_view(), QUrl.fromLocalFile(file_path))

    def save_current_page(self):
        view = self.current_view()
        if not view:
            return

        title = view.title().strip() or "seite"
        safe_name = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in title).strip()
        if not safe_name:
            safe_name = "seite"
        default_path = str(self.download_dir / f"{safe_name}.html")
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Seite speichern unter",
            default_path,
            "HTML komplett (*.html);;MHTML Archiv (*.mhtml)",
        )
        if not file_path:
            return

        save_format = QWebEngineDownloadRequest.SavePageFormat.CompleteHtmlSaveFormat
        if selected_filter.startswith("MHTML") or file_path.lower().endswith((".mhtml", ".mht")):
            save_format = QWebEngineDownloadRequest.SavePageFormat.MimeHtmlSaveFormat
        view.page().save(file_path, save_format)
        self.status_bar.showMessage("Seite wird gespeichert...", 2500)

    def save_current_pdf(self):
        view = self.current_view()
        if not view:
            return
        title = view.title().strip() or "seite"
        safe_name = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in title).strip()
        if not safe_name:
            safe_name = "seite"
        default_path = str(self.download_dir / f"{safe_name}.pdf")
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Als PDF speichern", default_path, "PDF (*.pdf)"
        )
        if not file_path:
            return
        if not file_path.lower().endswith(".pdf"):
            file_path += ".pdf"
        view.page().printToPdf(file_path)
        self.status_bar.showMessage("PDF wird erzeugt...", 2500)

    def save_page_screenshot(self):
        view = self.current_view()
        if not view:
            return
        title = view.title().strip() or "seite"
        safe_name = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in title).strip()
        if not safe_name:
            safe_name = "seite"
        default_path = str(self.download_dir / f"{safe_name}.png")
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Screenshot speichern", default_path, "PNG Bild (*.png)"
        )
        if not file_path:
            return
        if not file_path.lower().endswith(".png"):
            file_path += ".png"
        if view.grab().save(file_path, "PNG"):
            self.status_bar.showMessage("Screenshot gespeichert.", 2500)
        else:
            self.status_bar.showMessage("Screenshot konnte nicht gespeichert werden.", 3000)

    def trigger_upload_dialog(self):
        view = self.current_view()
        if not view:
            return
        script = """
        (() => {
          const el = document.querySelector('input[type="file"]');
          if (!el) return false;
          el.click();
          return true;
        })();
        """
        view.page().runJavaScript(script, self._upload_trigger_result)

    def _upload_trigger_result(self, found):
        if found:
            self.status_bar.showMessage("Dateiauswahl geöffnet.", 2000)
        else:
            self.status_bar.showMessage(
                "Kein Upload-Feld gefunden. Öffne eine Seite mit Datei-Upload.", 3500
            )

    def find_in_page(self):
        search_text, ok = QInputDialog.getText(self, "Suche", "Text auf Seite suchen:")
        view = self.current_view()
        if ok and search_text and view:
            view.findText("")
            view.findText(search_text)

    def change_zoom(self, delta):
        self.current_zoom = max(0.3, min(3.0, self.current_zoom + delta))
        view = self.current_view()
        if view:
            view.setZoomFactor(self.current_zoom)
        self.status_bar.showMessage(f"Zoom: {int(self.current_zoom * 100)}%", 2000)

    def reset_zoom(self):
        self.current_zoom = 1.0
        view = self.current_view()
        if view:
            view.setZoomFactor(self.current_zoom)
        self.status_bar.showMessage("Zoom: 100%", 2000)

    def add_bookmark(self):
        view = self.current_view()
        if not view:
            return
        item = {
            "title": view.title() or view.url().toString(),
            "url": view.url().toString(),
            "saved_at": datetime.now().isoformat(timespec="seconds"),
        }
        if not item["url"]:
            return
        known = {entry.get("url", "") for entry in self.data.get("bookmarks", [])}
        if item["url"] in known:
            self.status_bar.showMessage("Lesezeichen existiert bereits.", 2000)
            return
        self.data.setdefault("bookmarks", []).insert(0, item)
        self.data["bookmarks"] = self.data["bookmarks"][:MAX_BOOKMARKS]
        self._save_data()
        self._refresh_sidebar()
        self.status_bar.showMessage("Lesezeichen gespeichert.", 2000)

    def _record_history(self, view):
        url = view.url().toString()
        if self.private_mode or not url or view.url().scheme() == "codex":
            return
        title = view.title() or url
        history = self.data.setdefault("history", [])
        if history and history[0].get("url") == url:
            return
        entry = {
            "title": title,
            "url": url,
            "visited_at": datetime.now().isoformat(timespec="seconds"),
        }
        history.insert(0, entry)
        self.data["history"] = self.data["history"][:MAX_HISTORY_ITEMS]
        self._save_data()
        self._refresh_sidebar()

    def _on_load_finished(self, view, ok):
        if not ok:
            return
        self._record_history(view)
        self._run_extensions_for_view(view)

    def _url_matches_pattern(self, url_text, pattern):
        if not pattern or pattern == "*":
            return True
        normalized = pattern.strip()
        if normalized.startswith(("http://", "https://", "file://")):
            return fnmatch(url_text, normalized)
        return fnmatch(url_text, f"*://{normalized}*") or fnmatch(url_text, f"*{normalized}*")

    def _run_extensions_for_view(self, view):
        url_text = view.url().toString()
        if not url_text:
            return
        executed = 0
        for ext in self.data.get("extensions", []):
            path = ext.get("path", "")
            pattern = ext.get("match", "*")
            if not ext.get("enabled", True):
                continue
            if not path or not self._url_matches_pattern(url_text, pattern):
                continue
            script_path = Path(path)
            if not script_path.exists() or not script_path.is_file():
                continue
            try:
                code = script_path.read_text(encoding="utf-8")
            except Exception:
                continue
            if code.strip():
                view.page().runJavaScript(code)
                executed += 1
        if executed:
            self.status_bar.showMessage(f"Erweiterungen aktiv: {executed}", 2000)

    def install_extension(self):
        script_path, _ = QFileDialog.getOpenFileName(
            self, "Erweiterung auswählen", str(Path.home()), "JavaScript (*.js)"
        )
        if not script_path:
            return
        default_name = Path(script_path).stem
        name, ok = QInputDialog.getText(
            self, "Erweiterungsname", "Name der Erweiterung:", text=default_name
        )
        if not ok or not name.strip():
            return
        pattern, ok = QInputDialog.getText(
            self,
            "URL-Muster",
            "Für welche Seiten? Beispiel: *.youtube.com* (leer = alle):",
            text="*",
        )
        if not ok:
            return
        entry = {
            "name": name.strip(),
            "path": script_path,
            "match": pattern.strip() or "*",
            "enabled": True,
            "installed_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.data.setdefault("extensions", []).insert(0, entry)
        self._save_data()
        self.status_bar.showMessage("Erweiterung installiert.", 2500)

    def show_extensions(self):
        extensions = self.data.get("extensions", [])
        if not extensions:
            self.status_bar.showMessage("Keine Erweiterungen installiert.", 2500)
            return
        lines = [
            f"{idx + 1}. [{'AN' if ext.get('enabled', True) else 'AUS'}] "
            f"{ext.get('name', 'Ohne Name')}  [{ext.get('match', '*')}]"
            for idx, ext in enumerate(extensions)
        ]
        QInputDialog.getMultiLineText(
            self,
            "Installierte Erweiterungen",
            "Liste (nur Anzeige):",
            "\n".join(lines),
        )

    def remove_extension(self):
        extensions = self.data.get("extensions", [])
        if not extensions:
            self.status_bar.showMessage("Keine Erweiterungen installiert.", 2500)
            return
        options = [f"{ext.get('name', 'Ohne Name')} [{ext.get('match', '*')}]" for ext in extensions]
        selected, ok = QInputDialog.getItem(
            self, "Erweiterung entfernen", "Bitte auswählen:", options, 0, False
        )
        if not ok or not selected:
            return
        selected_idx = options.index(selected)
        extensions.pop(selected_idx)
        self._save_data()
        self.status_bar.showMessage("Erweiterung entfernt.", 2500)

    def toggle_extension_enabled(self):
        extensions = self.data.get("extensions", [])
        if not extensions:
            self.status_bar.showMessage("Keine Erweiterungen installiert.", 2500)
            return
        options = [
            f"{ext.get('name', 'Ohne Name')} [{'AN' if ext.get('enabled', True) else 'AUS'}]"
            for ext in extensions
        ]
        selected, ok = QInputDialog.getItem(
            self, "Erweiterung umschalten", "Bitte auswählen:", options, 0, False
        )
        if not ok or not selected:
            return
        idx = options.index(selected)
        current = bool(extensions[idx].get("enabled", True))
        extensions[idx]["enabled"] = not current
        self._save_data()
        state = "aktiviert" if extensions[idx]["enabled"] else "deaktiviert"
        self.status_bar.showMessage(
            f"Erweiterung '{extensions[idx].get('name', 'Unbenannt')}' {state}.", 2500
        )

    def clear_history(self):
        self.data["history"] = []
        self._save_data()
        self._refresh_sidebar()
        self.status_bar.showMessage("Verlauf gelöscht.", 2000)

    def show_download_history(self):
        entries = self.data.get("downloads", [])
        if not entries:
            self.status_bar.showMessage("Kein Download-Verlauf vorhanden.", 2500)
            return
        lines = [
            f"{idx + 1}. {e.get('file', 'download')} ({e.get('status', 'unbekannt')}) - {e.get('at', '')}"
            for idx, e in enumerate(entries[:200])
        ]
        QInputDialog.getMultiLineText(
            self,
            "Download-Verlauf",
            "Letzte Downloads:",
            "\n".join(lines),
        )

    def clear_download_history(self):
        self.data["downloads"] = []
        self._save_data()
        self.status_bar.showMessage("Download-Verlauf gelöscht.", 2500)

    def clear_bookmarks(self):
        self.data["bookmarks"] = []
        self._save_data()
        self._refresh_sidebar()
        self.status_bar.showMessage("Lesezeichen gelöscht.", 2000)

    def _refresh_sidebar(self):
        self.sidebar.clear()
        self._add_sidebar_section("Lesezeichen")
        for b in self.data.get("bookmarks", []):
            text = b.get("title", "Ohne Titel")
            item = QListWidgetItem(f"  {text}")
            item.setData(Qt.UserRole, b.get("url", ""))
            self.sidebar.addItem(item)
        self._add_sidebar_section("Verlauf")
        for h in self.data.get("history", [])[:200]:
            text = h.get("title", "Ohne Titel")
            item = QListWidgetItem(f"  {text}")
            item.setData(Qt.UserRole, h.get("url", ""))
            self.sidebar.addItem(item)

    def _add_sidebar_section(self, title):
        item = QListWidgetItem(title)
        item.setFlags(Qt.NoItemFlags)
        self.sidebar.addItem(item)

    def _open_sidebar_item(self, item):
        url = item.data(Qt.UserRole)
        if url:
            self.add_new_tab(url, switch=True)

    def _open_url(self, view, url):
        if not view:
            return
        if isinstance(url, str):
            url = self._normalize_input_to_url(url)
        if isinstance(url, QUrl) and url.scheme() == "codex":
            view.setHtml(self._start_page_html(), baseUrl=START_PAGE_URL)
            return
        view.setUrl(url)

    def _apply_webgl_setting(self):
        self.profile.settings().setAttribute(
            QWebEngineSettings.WebGLEnabled, self.webgl_enabled
        )

    def set_webgl_enabled(self, enabled):
        self.webgl_enabled = bool(enabled)
        self._apply_webgl_setting()

        for idx in range(self.tabs.count()):
            tab = self.tabs.widget(idx)
            if isinstance(tab, QWebEngineView):
                tab.page().settings().setAttribute(
                    QWebEngineSettings.WebGLEnabled, self.webgl_enabled
                )

        self._persist_setting("webgl_enabled", self.webgl_enabled)
        state = "aktiviert" if self.webgl_enabled else "deaktiviert"
        self.status_bar.showMessage(f"WebGL {state}.", 3000)

    def set_dark_mode_enabled(self, enabled):
        self.dark_mode_enabled = bool(enabled)
        self._apply_styles()
        self._persist_setting("dark_mode_enabled", self.dark_mode_enabled)
        state = "aktiviert" if self.dark_mode_enabled else "deaktiviert"
        self.status_bar.showMessage(f"Dark Mode {state}.", 2500)

    def duplicate_current_tab(self):
        view = self.current_view()
        if not view:
            return
        target = view.url().toString() or self.home_url.toString()
        self.add_new_tab(target, switch=True, label=view.title() or "Duplikat")

    def reopen_last_closed_tab(self):
        if not self.closed_tabs:
            self.status_bar.showMessage("Kein geschlossener Tab verfügbar.", 2200)
            return
        self.add_new_tab(self.closed_tabs.pop(0), switch=True)

    def copy_current_url(self):
        view = self.current_view()
        if not view:
            return
        url_text = view.url().toString()
        if not url_text:
            return
        QApplication.clipboard().setText(url_text)
        self.status_bar.showMessage("URL kopiert.", 1800)

    def open_page_source(self):
        view = self.current_view()
        if not view:
            return
        url_text = view.url().toString()
        if not url_text:
            return
        self.add_new_tab(QUrl(f"view-source:{url_text}"), switch=True, label="Quelltext")

    def set_current_tab_muted(self, muted):
        view = self.current_view()
        if not view:
            return
        view.page().setAudioMuted(bool(muted))
        state = "stumm" if muted else "mit Ton"
        self.status_bar.showMessage(f"Tab ist jetzt {state}.", 1800)

    def set_current_tab_pinned(self, pinned):
        view = self.current_view()
        if not view:
            return
        pinned = bool(pinned)
        idx = self.tabs.indexOf(view)
        if idx == -1:
            return
        view.setProperty("pinned", pinned)
        self.tabs.setTabText(idx, self._tab_label_text(view)[:32])
        self.tabs.setTabToolTip(idx, "Angeheftet" if pinned else "")
        state = "angeheftet" if pinned else "gelöst"
        self.status_bar.showMessage(f"Tab {state}.", 1800)

    def toggle_fullscreen(self, enabled):
        if enabled:
            self.showFullScreen()
        else:
            self.showNormal()

    def toggle_reader_mode(self, enabled):
        view = self.current_view()
        if not view:
            return
        if enabled:
            script = """
            (() => {
              let style = document.getElementById('codex-reader-style');
              if (!style) {
                style = document.createElement('style');
                style.id = 'codex-reader-style';
                style.textContent = `
                  body {
                    max-width: 860px !important;
                    margin: 0 auto !important;
                    padding: 24px 20px !important;
                    line-height: 1.65 !important;
                    font-size: 18px !important;
                    background: #f8fafc !important;
                  }
                  header, nav, aside, footer,
                  [role="banner"], [role="navigation"], [role="complementary"] {
                    display: none !important;
                  }
                  img, video { max-width: 100% !important; height: auto !important; }
                `;
                document.documentElement.appendChild(style);
              }
              return true;
            })();
            """
            view.page().runJavaScript(script)
            view.setProperty("reader_mode", True)
            self.status_bar.showMessage("Lesemodus aktiviert.", 2200)
            return

        script = """
        (() => {
          const style = document.getElementById('codex-reader-style');
          if (style) style.remove();
          return true;
        })();
        """
        view.page().runJavaScript(script)
        view.setProperty("reader_mode", False)
        self.status_bar.showMessage("Lesemodus deaktiviert.", 2200)

    def reload_all_tabs(self):
        loaded = 0
        for idx in range(self.tabs.count()):
            tab = self.tabs.widget(idx)
            if isinstance(tab, QWebEngineView):
                tab.reload()
                loaded += 1
        self.status_bar.showMessage(f"{loaded} Tabs werden neu geladen.", 2200)

    def _start_page_html(self):
        cards = [
            ("Google", "https://www.google.com"),
            ("YouTube", "https://www.youtube.com"),
            ("Wikipedia", "https://www.wikipedia.org"),
            ("GitHub", "https://github.com"),
            ("Gmail", "https://mail.google.com"),
            ("ChatGPT", "https://chatgpt.com"),
        ]
        card_html = "".join(
            f'<a class="card" href="{url}"><span>{label}</span><small>{url.replace("https://", "")}</small></a>'
            for label, url in cards
        )
        return f"""
<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Startseite</title>
  <style>
    :root {{
      color-scheme: light;
      font-family: "Avenir Next", "Avenir", "Helvetica Neue", "Segoe UI", sans-serif;
    }}
    body {{
      margin: 0;
      min-height: 100vh;
      background:
        radial-gradient(1200px 520px at 10% -10%, #d7e8ff 10%, transparent 58%),
        radial-gradient(900px 450px at 100% 0%, #cde8ff 0%, transparent 50%),
        linear-gradient(165deg, #e8f1ff 0%, #f6fbff 55%, #e6effc 100%);
      display: grid;
      place-items: center;
      color: #0f1f3d;
    }}
    main {{
      width: min(980px, 93vw);
      background: rgba(255, 255, 255, 0.82);
      border: 1px solid #c5d6ec;
      border-radius: 28px;
      box-shadow: 0 24px 60px rgba(15, 33, 64, 0.16);
      padding: 36px;
      backdrop-filter: blur(10px);
    }}
    h1 {{
      margin: 0 0 6px;
      font-size: clamp(2.1rem, 4vw, 2.9rem);
      letter-spacing: -0.025em;
      font-weight: 760;
    }}
    p {{
      margin: 0 0 18px;
      color: #385171;
      font-size: 1.02rem;
    }}
    .pill {{
      display: inline-block;
      padding: 8px 14px;
      background: #e6f1ff;
      border: 1px solid #b8d0f0;
      border-radius: 999px;
      color: #224d8f;
      font-size: 0.92rem;
      margin-bottom: 24px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
    }}
    .card {{
      text-decoration: none;
      color: inherit;
      background: linear-gradient(180deg, #ffffff 0%, #f4f9ff 100%);
      border: 1px solid #c8d9ee;
      border-radius: 15px;
      padding: 15px 16px;
      display: grid;
      gap: 4px;
      transition: 160ms ease;
    }}
    .card span {{
      font-weight: 700;
      font-size: 1.02rem;
    }}
    .card small {{
      color: #547091;
      font-size: .84rem;
    }}
    .card:hover {{
      transform: translateY(-3px);
      border-color: #87abd9;
      box-shadow: 0 14px 28px rgba(27, 66, 120, .16);
      background: linear-gradient(180deg, #ffffff 0%, #edf5ff 100%);
    }}
  </style>
</head>
<body>
  <main>
    <h1>CodexBrowser</h1>
    <p>Schneller Start mit deinen wichtigsten Seiten.</p>
    <div class="pill">Cookies und Website-Logins werden gespeichert (außer im privaten Modus)</div>
    <section class="grid">{card_html}</section>
  </main>
</body>
</html>
"""

    def toggle_sidebar(self):
        self.sidebar.setVisible(not self.sidebar.isVisible())

    def _on_load_progress(self, value):
        self.progress_label.setText(f"{value}%")
        if value >= 100:
            self.progress_label.setText("")

    def _on_download_requested(self, download: QWebEngineDownloadRequest):
        if download.state() != QWebEngineDownloadRequest.DownloadState.DownloadRequested:
            return

        if download.isSavePageDownload():
            download.accept()
            self.open_downloads[id(download)] = download
            download.receivedBytesChanged.connect(
                lambda d=download: self._update_download_status(d)
            )
            download.isFinishedChanged.connect(
                lambda d=download: self._finish_download(d, id(download))
            )
            self.status_bar.showMessage("Seite wird gespeichert...", 2500)
            return

        suggested = download.downloadFileName() or "download"
        default_path = str(self.download_dir / suggested)
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Download speichern unter", default_path, "Alle Dateien (*)"
        )
        if not file_path:
            download.cancel()
            self.status_bar.showMessage("Download abgebrochen.", 2000)
            return

        final_path = Path(file_path)
        download.setDownloadDirectory(str(final_path.parent))
        download.setDownloadFileName(final_path.name)
        download.accept()
        self.open_downloads[id(download)] = download
        download.receivedBytesChanged.connect(
            lambda d=download: self._update_download_status(d)
        )
        download.isFinishedChanged.connect(
            lambda d=download: self._finish_download(d, id(download))
        )
        self.status_bar.showMessage(f"Download gestartet: {final_path.name}", 3000)

    def _update_download_status(self, download):
        total = download.totalBytes()
        got = download.receivedBytes()
        if total > 0:
            pct = int((got / total) * 100)
            self.status_bar.showMessage(f"Download: {pct}%")
        else:
            self.status_bar.showMessage(f"Download: {got} Bytes")

    def _finish_download(self, download, key):
        status = "abgebrochen"
        if download.state() == QWebEngineDownloadRequest.DownloadState.DownloadCompleted:
            status = "fertig"
            self.status_bar.showMessage(
                f"Download fertig: {download.downloadFileName()}", 4000
            )
        elif download.state() == QWebEngineDownloadRequest.DownloadState.DownloadInterrupted:
            status = "fehler"
            self.status_bar.showMessage(
                f"Download fehlgeschlagen: {download.downloadFileName()}", 4000
            )
        elif download.state() == QWebEngineDownloadRequest.DownloadState.DownloadCancelled:
            self.status_bar.showMessage("Download abgebrochen.", 3000)

        self.data.setdefault("downloads", []).insert(
            0,
            {
                "file": download.downloadFileName() or "download",
                "url": download.url().toString(),
                "status": status,
                "at": datetime.now().isoformat(timespec="seconds"),
            },
        )
        self.data["downloads"] = self.data["downloads"][:500]
        self._save_data()
        self.open_downloads.pop(key, None)

    def set_homepage(self):
        view = self.current_view()
        current = view.url().toString() if view else ""
        text, ok = QInputDialog.getText(
            self,
            "Startseite festlegen",
            "URL für Startseite (leer = interne Startseite):",
            text=current if current and current != START_PAGE_URL.toString() else "",
        )
        if not ok:
            return
        if not text.strip():
            self.home_url = START_PAGE_URL
            self._persist_setting("home_url", self.home_url.toString())
            self.status_bar.showMessage("Startseite auf interne Seite gesetzt.", 3000)
            return
        self.home_url = self._normalize_input_to_url(text.strip())
        self._persist_setting("home_url", self.home_url.toString())
        self.status_bar.showMessage(
            f"Neue Startseite: {self.home_url.toString()}", 3000
        )

    def clear_site_data(self):
        if self.private_mode:
            self.status_bar.showMessage("Privater Modus speichert keine Cookies.", 3500)
            return
        self.profile.cookieStore().deleteAllCookies()
        self.profile.clearHttpCache()
        self.status_bar.showMessage("Cookies und Web-Cache wurden gelöscht.", 3500)

    def set_download_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Download-Ordner wählen", str(self.download_dir)
        )
        if folder:
            self.download_dir = Path(folder)
            self._persist_setting("download_dir", str(self.download_dir))
            self.status_bar.showMessage(f"Download-Ordner: {folder}", 3000)

    def open_new_window(self):
        window = BrowserWindow(private_mode=False)
        window.show()
        _WINDOWS.append(window)

    def open_private_window(self):
        window = BrowserWindow(private_mode=True)
        window.show()
        _WINDOWS.append(window)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction(self.new_tab_action)
        menu.addAction(self.duplicate_tab_action)
        menu.addAction(self.reopen_tab_action)
        menu.addAction(self.close_tab_action)
        menu.addSeparator()
        menu.addAction(self.reload_action)
        menu.addAction(self.reload_all_tabs_action)
        menu.addAction(self.pin_tab_action)
        menu.addAction(self.toggle_mute_action)
        menu.addAction(self.copy_url_action)
        menu.addAction(self.find_action)
        menu.exec(event.globalPos())


_WINDOWS = []


def main():
    QApplication.setApplicationName(APP_NAME)
    app = QApplication(sys.argv)
    browser = BrowserWindow(private_mode=False)
    _WINDOWS.append(browser)
    browser.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
