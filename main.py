import sys
import json
import random
import time
import os
import math
import re
import logging
import urllib.request
from urllib.parse import urlparse
from pathlib import Path
import threading
import html
from copy import deepcopy
from collections import deque
from datetime import datetime
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt, QEvent, QTimer, QThread, Signal, Slot, QLocale, QUrl, QObject, QPoint
from PySide6.QtGui import (
    QFont, QAction, QCursor, QIcon, QDoubleValidator, QIntValidator,
    QDesktopServices, QColor, QPalette,
    QPainter, QPen, QGuiApplication,
)
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QLineEdit, QComboBox,
    QTextEdit, QFrame, QCheckBox, QMessageBox, QRadioButton,
    QMenu, QDialog, QDialogButtonBox, QFormLayout, QSizePolicy, QScrollArea,
    QTextBrowser, QFileDialog, QStyle, QStyleOptionButton, QGroupBox,
    QListWidget, QWizard, QWizardPage,
)

from pynput import keyboard, mouse


MAX_SCENARIO_ACTIONS = 100000


class CoordinateScreenUnavailable(ValueError):
    pass


def interpolate_cursor_position(start, end, progress):
    progress = min(1.0, max(0.0, progress))
    eased = progress * progress * (3 - 2 * progress)
    return tuple(
        round(source + (target - source) * eased)
        for source, target in zip(start, end)
    )


def has_coordinate_swipe(actions):
    return any(
        isinstance(action, dict) and action.get("type") == "swipe"
        for action in actions
    )


class IntervalValidator(QDoubleValidator):
    def __init__(self, parent=None):
        super().__init__(0.0, 999999999.0, 6, parent)
        self.setNotation(QDoubleValidator.StandardNotation)
        self.setLocale(QLocale.c())

    def validate(self, text, position):
        if not text:
            return QValidator.Intermediate, text, position
        normalized = text.replace(",", ".")
        state, _, _ = super().validate(normalized, position)
        return state, text, position


class CoordinateOverlay(QDialog):
    def __init__(self, screen, points, translate, swipe_button, parent=None):
        super().__init__(parent)
        self.screen = screen
        self.points = points
        self.translate = translate
        self.swipe_button = swipe_button
        self.swipe_drawing = False
        self.swipe_path = []
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)
        self.setGeometry(screen.geometry())
        self._application = QApplication.instance()
        if self._application is not None:
            self._application.installEventFilter(self)
        self.finished.connect(self._remove_application_event_filter)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._activate_for_recording)

    def _activate_for_recording(self):
        if self.isVisible():
            self.activateWindow()
            self.setFocus(Qt.ActiveWindowFocusReason)

    def _remove_application_event_filter(self, result):
        if self._application is not None:
            self._application.removeEventFilter(self)

    def _handle_recording_key(self, event):
        if event.key() == Qt.Key_Escape:
            self.accept()
            return True
        if event.key() == Qt.Key_F8:
            position = QCursor.pos()
            geometry = self.screen.geometry()
            if geometry.contains(position):
                self._append_click_point(
                    position.x() - geometry.x(),
                    position.y() - geometry.y(),
                )
            return True
        if event.key() == Qt.Key_Backspace:
            if self.points:
                self.points.pop()
                self.update()
            return True
        return False

    def eventFilter(self, watched, event):
        if (
            event.type() == QEvent.KeyPress
            and self.isVisible()
            and QApplication.activeModalWidget() is self
            and self._handle_recording_key(event)
        ):
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(5, 12, 24, 90))
        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("Segoe UI", 14, QFont.Bold))
        painter.drawText(
            self.rect().adjusted(16, 16, -16, -self.height() + 72),
            Qt.AlignCenter,
            self.translate("coordinate_overlay_instructions"),
        )
        for index, action in enumerate(self.points, start=1):
            if action.get("type") == "swipe":
                path = action["points"]
                painter.setPen(QPen(QColor("#ffd35c"), 4))
                for start, end in zip(path, path[1:]):
                    start_x, start_y = self._point_to_pixel(start)
                    end_x, end_y = self._point_to_pixel(end)
                    painter.drawLine(
                        start_x,
                        start_y,
                        end_x,
                        end_y,
                    )
                if path:
                    self._draw_marker(
                        painter,
                        self._point_to_pixel(path[0]),
                        index,
                        QColor("#e99600"),
                    )
            else:
                point = action.get("point", action)
                self._draw_marker(
                    painter,
                    self._point_to_pixel(point),
                    index,
                    QColor("#7c5cfc"),
                )
        if self.swipe_drawing and len(self.swipe_path) > 1:
            painter.setPen(QPen(QColor("#ffd35c"), 4))
            for start, end in zip(self.swipe_path, self.swipe_path[1:]):
                start_x, start_y = self._point_to_pixel(start)
                end_x, end_y = self._point_to_pixel(end)
                painter.drawLine(
                    start_x,
                    start_y,
                    end_x,
                    end_y,
                )

    def _point_to_pixel(self, point):
        return (
            round(point["x"] * max(0, self.width() - 1)),
            round(point["y"] * max(0, self.height() - 1)),
        )

    @staticmethod
    def _draw_marker(painter, position, index, color):
        x, y = position
        painter.setBrush(color)
        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.drawEllipse(x - 18, y - 18, 36, 36)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(x - 18, y - 18, 36, 36, Qt.AlignCenter, str(index))

    def _make_point(self, local_x, local_y):
        geometry = self.screen.geometry()
        if not geometry.width() or not geometry.height():
            return None
        return {
            "screen": self.screen.name(),
            "x": min(1.0, max(0.0, local_x / max(1, geometry.width() - 1))),
            "y": min(1.0, max(0.0, local_y / max(1, geometry.height() - 1))),
        }

    def _append_click_point(self, local_x, local_y):
        point = self._make_point(local_x, local_y)
        if point is None:
            return
        self.points.append(point)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            position = event.position()
            if event.modifiers() & Qt.ShiftModifier:
                self.swipe_drawing = True
                self.swipe_path = []
                point = self._make_point(position.x(), position.y())
                if point is not None:
                    self.swipe_path.append(point)
                self.update()
            else:
                self._append_click_point(position.x(), position.y())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.swipe_drawing and event.buttons() & Qt.LeftButton:
            position = event.position()
            point = self._make_point(position.x(), position.y())
            if point is not None:
                previous = self.swipe_path[-1]
                dx = point["x"] - previous["x"]
                dy = point["y"] - previous["y"]
                if dx * dx + dy * dy >= 0.000004:
                    self.swipe_path.append(point)
                    self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.swipe_drawing:
            position = event.position()
            final_point = self._make_point(position.x(), position.y())
            if final_point is not None and (
                not self.swipe_path
                or final_point != self.swipe_path[-1]
            ):
                self.swipe_path.append(final_point)
            if len(self.swipe_path) > 1:
                self.points.append({
                    "type": "swipe",
                    "button": self.swipe_button,
                    "points": self.swipe_path,
                })
            elif self.swipe_path:
                self.points.append(self.swipe_path[0])
            self.swipe_path = []
            self.swipe_drawing = False
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if not self._handle_recording_key(event):
            super().keyPressEvent(event)


class CoordinateRecorderDialog(QDialog):
    def __init__(self, points, translate, parent=None):
        super().__init__(parent)
        self.translate = translate
        self.points = deepcopy(points)
        self.screens = QGuiApplication.screens()
        self.setWindowTitle(translate("coordinate_recorder_title"))
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)

        self.monitor_combo = QComboBox()
        for index, screen in enumerate(self.screens, start=1):
            geometry = screen.geometry()
            self.monitor_combo.addItem(
                f'{index}. {screen.name()} '
                f'({geometry.width()}×{geometry.height()})',
                screen,
            )
        last_action = self.points[-1] if self.points else {}
        last_point = last_action
        if (
            isinstance(last_action, dict)
            and last_action.get("type") == "swipe"
        ):
            path = last_action.get("points", [])
            last_point = path[-1] if isinstance(path, list) and path else {}
        last_screen_name = (
            last_point.get("screen")
            if isinstance(last_point, dict)
            else None
        )
        selected_screen = next(
            (
                screen
                for screen in self.screens
                if screen.name() == last_screen_name
            ),
            QGuiApplication.primaryScreen(),
        )
        primary_index = self.monitor_combo.findData(selected_screen)
        if primary_index >= 0:
            self.monitor_combo.setCurrentIndex(primary_index)
        layout.addWidget(QLabel(translate("coordinate_monitor")))
        layout.addWidget(self.monitor_combo)

        self.instructions_label = QLabel(
            translate("coordinate_recorder_instructions")
        )
        self.instructions_label.setWordWrap(True)
        layout.addWidget(self.instructions_label)

        self.points_label = QLabel()
        self.points_label.setWordWrap(True)
        layout.addWidget(self.points_label)
        self._refresh_points_label()

        self.swipe_button_combo = QComboBox()
        for button, label in (
            ("left", "coordinate_swipe_left"),
            ("right", "coordinate_swipe_right"),
            ("middle", "coordinate_swipe_middle"),
            ("x1", "coordinate_swipe_x1"),
            ("x2", "coordinate_swipe_x2"),
        ):
            self.swipe_button_combo.addItem(translate(label), button)
        layout.addWidget(QLabel(translate("coordinate_swipe_button")))
        layout.addWidget(self.swipe_button_combo)

        actions = QHBoxLayout()
        self.record_button = QPushButton(
            translate("coordinate_start_recording")
        )
        self.record_button.clicked.connect(self._record_points)
        actions.addWidget(self.record_button)
        self.clear_button = QPushButton(translate("button_clear"))
        self.clear_button.clicked.connect(self._clear_points)
        actions.addWidget(self.clear_button)
        layout.addLayout(actions)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Ok).setText(
            translate("dialog_ok")
        )
        buttons.button(QDialogButtonBox.Cancel).setText(
            translate("dialog_cancel")
        )
        layout.addWidget(buttons)
        self._application = QApplication.instance()
        if self._application is not None:
            self._application.installEventFilter(self)
        self.finished.connect(self._remove_application_event_filter)

    def _record_points(self):
        screen = self.monitor_combo.currentData()
        if screen is None:
            return
        main_window = self.parentWidget().window()
        was_visible = main_window.isVisible()
        was_minimized = main_window.isMinimized()
        was_maximized = main_window.isMaximized()
        overlay = CoordinateOverlay(
            screen,
            self.points,
            self.translate,
            self.swipe_button_combo.currentData(),
        )
        if self.parent() is not None:
            self.parent().coordinate_recording_active = True
        try:
            if was_visible and not was_minimized:
                main_window.showMinimized()
            overlay.exec()
        finally:
            if self.parent() is not None:
                self.parent().coordinate_recording_active = False
            if was_visible and not was_minimized:
                if was_maximized:
                    main_window.showMaximized()
                else:
                    main_window.showNormal()
                main_window.activateWindow()
        self._refresh_points_label()
        self.activateWindow()
        self.raise_()
        self.setFocus(Qt.OtherFocusReason)

    def eventFilter(self, watched, event):
        is_editor_input = (
            isinstance(watched, QWidget)
            and (watched is self or self.isAncestorOf(watched))
        )
        if (
            not is_editor_input
            and self.isVisible()
            and QApplication.activeModalWidget() is self
        ):
            is_editor_input = True
        if (
            event.type() == QEvent.KeyPress
            and is_editor_input
        ):
            if event.key() == Qt.Key_Escape:
                self.reject()
                event.accept()
                return True
            if event.key() == Qt.Key_Backspace:
                self._undo_last_action()
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def _remove_application_event_filter(self, result):
        if self._application is not None:
            self._application.removeEventFilter(self)

    def _undo_last_action(self):
        if self.points:
            self.points.pop()
            self._refresh_points_label()

    def _clear_points(self):
        self.points.clear()
        self._refresh_points_label()

    def _refresh_points_label(self):
        if not self.points:
            self.points_label.setText(
                self.translate("coordinate_points_empty")
            )
            return
        self.points_label.setText(
            self.translate("coordinate_points_count", len(self.points))
        )


def format_interval_value(value):
    return format(Decimal(str(value)), "f")


def interval_fields_match(minimum_edit, maximum_edit):
    minimum_text = minimum_edit.text().strip().replace(",", ".")
    maximum_text = maximum_edit.text().strip().replace(",", ".")
    if not minimum_text or not maximum_text:
        return False
    try:
        minimum = Decimal(minimum_text)
        maximum = Decimal(maximum_text)
    except InvalidOperation:
        return False
    return minimum.is_finite() and maximum.is_finite() and minimum == maximum


# Для корректного отображения в панели задач Windows
if sys.platform == "win32":
    import ctypes
    myappid = "mycompany.zloyclicker.version.2.0"
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
# ============================================================
# APP SETTINGS
# ============================================================

APP_NAME = "Lim0n4ikzGames Clicker"
APP_VERSION = "2.18.10"
BUG_REPORT_URL = "https://forms.gle/MZvS2rtF4Sae8eAV6"
PROFILE_FILE_FORMAT = "lim0n4ikz-clicker-profiles"
MAX_PROFILE_FILE_SIZE = 5 * 1024 * 1024
VERSION_MANIFEST_URL = (
    "https://raw.githubusercontent.com/lim0n4ikz/"
    "Lim0n4ikzGamesClicker/main/versions.json"
)
APP_DIR = Path(__file__).resolve().parent
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
LEGACY_SETTINGS_FILE = APP_DIR / "settings.json"
configured_data_dir = os.environ.get("LIM0N4KZ_CLICKER_DATA_DIR")
if configured_data_dir:
    DATA_DIR = Path(configured_data_dir).expanduser()
    SETTINGS_FILE = DATA_DIR / "settings.json"
    PROFILES_FILE = DATA_DIR / "profiles.json"
elif getattr(sys, "frozen", False):
    DATA_DIR = (
        Path(os.environ.get("LOCALAPPDATA", APP_DIR))
        / "Lim0n4ikzGamesClicker"
    )
    SETTINGS_FILE = DATA_DIR / "settings.json"
    PROFILES_FILE = DATA_DIR / "profiles.json"
else:
    DATA_DIR = APP_DIR
    SETTINGS_FILE = LEGACY_SETTINGS_FILE
    PROFILES_FILE = APP_DIR / "profiles.json"
SCENARIO_FILE = DATA_DIR / "scenario.json"
LEGACY_PROFILES_FILE = APP_DIR / "profiles.json"
ICON_FILE = RESOURCE_DIR / "lim0n4ikzgames.ico"
FALLBACK_ICON_FILE = RESOURCE_DIR / "lim0n4ikzgames.ico"


def version_key(version):
    if not isinstance(version, str) or not re.fullmatch(r"\d+(?:\.\d+){1,2}", version):
        raise ValueError(f"Invalid application version: {version!r}")
    parts = tuple(int(part) for part in version.split("."))
    return parts + (0,) * (3 - len(parts))


def parse_update_manifest(manifest, current_version):
    if not isinstance(manifest, dict):
        raise ValueError("Update manifest must be a JSON object")

    latest = manifest.get("latest_version")
    latest_key = version_key(latest)
    current_key = version_key(current_version)
    download_url = manifest.get("download_url")
    parsed_url = urlparse(download_url) if isinstance(download_url, str) else None
    if (
        parsed_url is None
        or parsed_url.scheme != "https"
        or parsed_url.hostname != "github.com"
    ):
        raise ValueError("Update manifest contains an invalid download URL")

    releases = manifest.get("releases")
    if not isinstance(releases, list):
        raise ValueError("Update manifest releases must be a list")

    validated_releases = []
    for release in releases:
        if not isinstance(release, dict):
            raise ValueError("Update manifest contains an invalid release")
        release_version = release.get("version")
        release_key = version_key(release_version)
        changes = release.get("changes")
        if not isinstance(changes, dict):
            raise ValueError(f"Release {release_version} has no localized changelog")
        localized_changes = {}
        for language in ("ru", "en"):
            items = changes.get(language)
            if not isinstance(items, list) or not all(
                isinstance(item, str) and item.strip() for item in items
            ):
                raise ValueError(
                    f"Release {release_version} has an invalid {language} changelog"
                )
            localized_changes[language] = items
        validated_releases.append(
            (release_key, {"version": release_version, "changes": localized_changes})
        )

    if latest_key <= current_key:
        return None

    updates = [
        release for release_key, release in validated_releases
        if current_key < release_key <= latest_key
    ]
    if not updates or not any(release["version"] == latest for release in updates):
        raise ValueError("Update manifest has no complete changelog up to latest_version")
    updates.sort(key=lambda release: version_key(release["version"]))
    return {
        "current_version": current_version,
        "latest_version": latest,
        "download_url": download_url,
        "releases": updates,
    }


class UpdateCheckSignals(QObject):
    check_finished = Signal(object)
    check_failed = Signal(str)


class UpdateDialog(QDialog):
    def __init__(self, update, language, parent=None):
        super().__init__(parent)
        is_russian = language == "ru"
        self.setWindowTitle(
            "Доступно обновление" if is_russian else "Update available"
        )
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        heading = QLabel(
            f"{'Версия' if is_russian else 'Version'} "
            f"{update['current_version']} → {update['latest_version']}"
        )
        heading.setStyleSheet("font-size: 16px; font-weight: 700;")
        layout.addWidget(heading)

        changelog = QTextBrowser()
        changelog.setOpenExternalLinks(False)
        changelog.setMinimumHeight(220)
        sections = []
        language_key = "ru" if is_russian else "en"
        for release in update["releases"]:
            items = "".join(
                f"<li>{html.escape(item)}</li>"
                for item in release["changes"][language_key]
            )
            sections.append(
                f"<h3>v{html.escape(release['version'])}</h3><ul>{items}</ul>"
            )
        changelog.setHtml("".join(sections))
        layout.addWidget(changelog)

        buttons = QDialogButtonBox()
        update_button = buttons.addButton(
            "Обновить" if is_russian else "Update",
            QDialogButtonBox.AcceptRole,
        )
        later_button = buttons.addButton(
            "Позже" if is_russian else "Later",
            QDialogButtonBox.RejectRole,
        )
        update_button.clicked.connect(self.accept)
        later_button.clicked.connect(self.reject)
        layout.addWidget(buttons)

if sys.platform == "win32":
    import ctypes
    myappid = "mycompany.zloyclicker.version.2.0"
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

# ============================================================
# STYLE
# ============================================================

STYLE = """
QMainWindow { background: #060d16; }
QDialog { background: #060d16; }
QWizard { background: #060d16; }
QWizardPage { background-color: #060d16; color: #eef5ff; }
QWizardPage QLabel { background: transparent; color: #eef5ff; }
QWidget { color: #eef5ff; font-family: "Segoe UI"; font-size: 13px; }
QFrame#panel { background: #0b1725; border: 1px solid #223952; border-radius: 14px; }
QLabel#title { font-size: 23px; font-weight: 700; }
QLabel#subtitle { color: #91a4ba; font-size: 12px; }
QLabel#section { color: #75aaff; font-size: 13px; font-weight: 700; padding-top: 4px; }
QLineEdit, QComboBox, QTextEdit {
    background: #06111c; border: 1px solid #29425e; border-radius: 9px;
    padding: 9px; color: #eef5ff; selection-background-color: #286bd0;
}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus { border: 1px solid #4d91ff; }
QComboBox::drop-down { border: none; width: 28px; }
QPushButton { background: #102238; border: 1px solid #335271; border-radius: 9px; padding: 10px 15px; font-weight: 600; }
QPushButton:hover { background: #17304d; }
QPushButton#blue { background: #286bd2; border: 1px solid #5b9cff; }
QPushButton#blue:hover { background: #347be8; }
QPushButton#green { background: #126d3a; border: 1px solid #38d77c; }
QPushButton#green:hover { background: #17844a; }
QPushButton#red { background: #9c2938; border: 1px solid #ff6873; }
QPushButton#red:hover { background: #b63242; }
QPushButton#yellow { background: #30270f; border: 1px solid #80651d; color: #ffd35c; }
QCheckBox { spacing: 9px; color: #dce7f5; }
QCheckBox::indicator { width: 20px; height: 20px; border-radius: 6px; background: #17283a; border: 1px solid #34516d; }
QCheckBox::indicator:checked { background: #286bd2; border: 1px solid #5b9cff; }

QPushButton#menu-btn { background: #1a2d44; border: 1px solid #3a5a7a; border-radius: 6px; font-size: 18px; color: #b0ccee; }
QPushButton#menu-btn:hover { background: #2a4060; }
QPushButton#settings-btn { background: #102238; border: 1px solid #335271; border-radius: 19px; color: #b0ccee; padding: 0; }
QPushButton#settings-btn:hover { background: #17304d; border-color: #5b9cff; }
"""

def build_color_theme(
    background,
    panel,
    input_background,
    border,
    muted,
    accent,
    accent_hover,
    button_background,
    button_hover,
    secondary_text,
):
    return {
        "#060d16": background,
        "#eef5ff": "#e8edf5",
        "#0b1725": panel,
        "#223952": border,
        "#91a4ba": muted,
        "#75aaff": accent,
        "#06111c": input_background,
        "#29425e": border,
        "#286bd0": accent,
        "#286bd2": accent,
        "#4d91ff": accent_hover,
        "#102238": button_background,
        "#335271": border,
        "#17304d": button_hover,
        "#5b9cff": accent_hover,
        "#347be8": accent_hover,
        "#dce7f5": secondary_text,
        "#17283a": button_background,
        "#34516d": border,
        "#1a2d44": button_background,
        "#3a5a7a": border,
        "#b0ccee": accent_hover,
        "#2a4060": button_hover,
        "#07111d": input_background,
        "#2b435d": border,
        "#b9c9dc": secondary_text,
        "#091622": panel,
        "#6196df": accent,
        "#e8edf5": secondary_text,
        "#9aaec9": muted,
        "#8b9bb5": muted,
        "#6a7d9b": muted,
        "#cdd9ec": secondary_text,
    }


THEME_COLOR_MAPS = {
    "dark": {},
    "ocean": build_color_theme(
        "#07151d", "#0d2530", "#091d26", "#28616b", "#9bb9c2",
        "#54d4c4", "#35b8c2", "#123542", "#1a4755", "#d2eaf0",
    ),
    "purple": build_color_theme(
        "#100d1c", "#1b1530", "#140f24", "#3c315d", "#b2a7c9",
        "#b49aff", "#c7b5ff", "#241c3d", "#302650", "#e0d9f0",
    ),
    "forest": build_color_theme(
        "#0b1711", "#12251a", "#0e1c14", "#315440", "#a1b9a5",
        "#83d99a", "#a0e8ad", "#183522", "#21472d", "#d5e8d8",
    ),
    "sunset": build_color_theme(
        "#1b1010", "#2b1918", "#211312", "#69403a", "#c5a9a0",
        "#ff9d76", "#ffc09c", "#3a211d", "#4b2b25", "#f0d8cf",
    ),
    "gray": build_color_theme(
        "#121416", "#1d2023", "#17191c", "#41464b", "#a4abb2",
        "#b5bec7", "#d0d6dc", "#272b2f", "#343a40", "#e0e4e8",
    ),
    "blue": build_color_theme(
        "#0d1420", "#151f30", "#101a29", "#344d70", "#a5b8d2",
        "#8ab4f8", "#a8c7fa", "#1c2a40", "#263854", "#dce7f5",
    ),
    "red": build_color_theme(
        "#1a1012", "#291719", "#201315", "#62383d", "#c5a5a8",
        "#ff8a8a", "#ffaaaa", "#382023", "#4b2a2e", "#f0d9dc",
    ),
    "pink": build_color_theme(
        "#1a1018", "#291725", "#20131d", "#613652", "#c5a5bc",
        "#ff8acb", "#ffaddb", "#382033", "#4b2b45", "#f0d9e8",
    ),
}

THEME_BUTTON_TEXT_COLORS = {
    "ocean": "#07151d",
    "purple": "#100d1c",
    "forest": "#0b1711",
    "sunset": "#1b1010",
    "gray": "#121416",
    "blue": "#0d1420",
    "red": "#1a1012",
    "pink": "#1a1018",
}


def theme_stylesheet(theme, font_size=None):
    color_map = THEME_COLOR_MAPS[theme]
    stylesheet = re.sub(
        r"#[0-9a-fA-F]{6}",
        lambda match: color_map.get(match.group().lower(), match.group()),
        STYLE,
    )
    button_text_color = THEME_BUTTON_TEXT_COLORS.get(theme)
    if button_text_color:
        stylesheet += (
            "\nQPushButton#blue, QPushButton#blue:hover "
            f"{{ color: {button_text_color}; }}"
        )
    if font_size is not None:
        stylesheet += f"\nQWidget {{ font-size: {font_size}px; }}"
    return stylesheet


def theme_local_stylesheet(stylesheet, theme):
    color_map = THEME_COLOR_MAPS[theme]
    return re.sub(
        r"#[0-9a-fA-F]{6}",
        lambda match: color_map.get(match.group().lower(), match.group()),
        stylesheet,
    )

class ScenarioActionEditDialog(QDialog):
    ACTIONS = (
        ("key_press", "scenario_type_key_press"),
        ("key_release", "scenario_type_key_release"),
        ("mouse_press", "scenario_type_mouse_press"),
        ("mouse_release", "scenario_type_mouse_release"),
        ("mouse_move", "scenario_type_mouse_move"),
        ("scroll", "scenario_type_scroll"),
    )

    def __init__(self, action, parent):
        super().__init__(parent)
        self.editor = parent
        self.main_window = (
            parent if hasattr(parent, "MODE_SCENARIO") else parent.parent
        )
        self.action = deepcopy(action)
        self.setWindowTitle(self.main_window.tr("scenario_action_title"))
        layout = QFormLayout(self)

        self.type_combo = QComboBox()
        for action_type, translation_key in self.ACTIONS:
            self.type_combo.addItem(
                self.main_window.tr(translation_key),
                action_type,
            )
        current_type = self.action.get("type", "key_press")
        index = self.type_combo.findData(current_type)
        self.type_combo.setCurrentIndex(max(0, index))
        layout.addRow(
            self.main_window.tr("scenario_action_type"),
            self.type_combo,
        )

        self.value_label = QLabel()
        self.value_edit = QLineEdit()
        layout.addRow(self.value_label, self.value_edit)

        self.x_label = QLabel(self.main_window.tr("scenario_action_x"))
        self.x_edit = QLineEdit()
        self.x_edit.setValidator(QIntValidator(-100000, 100000, self.x_edit))
        layout.addRow(self.x_label, self.x_edit)
        self.y_label = QLabel(self.main_window.tr("scenario_action_y"))
        self.y_edit = QLineEdit()
        self.y_edit.setValidator(QIntValidator(-100000, 100000, self.y_edit))
        layout.addRow(self.y_label, self.y_edit)

        self.dx_label = QLabel(self.main_window.tr("scenario_action_dx"))
        self.dx_edit = QLineEdit()
        self.dx_edit.setValidator(QIntValidator(-10000, 10000, self.dx_edit))
        layout.addRow(self.dx_label, self.dx_edit)
        self.dy_label = QLabel(self.main_window.tr("scenario_action_dy"))
        self.dy_edit = QLineEdit()
        self.dy_edit.setValidator(QIntValidator(-10000, 10000, self.dy_edit))
        layout.addRow(self.dy_label, self.dy_edit)

        self.delay_edit = QLineEdit(
            format_interval_value(self.action.get("delay", 0.0))
        )
        self.delay_edit.setValidator(IntervalValidator(self.delay_edit))
        layout.addRow(
            self.main_window.tr("scenario_action_delay"),
            self.delay_edit,
        )

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        self.type_combo.currentIndexChanged.connect(self.update_field_visibility)
        self._load_action()
        self.update_field_visibility()

    def _load_action(self):
        action_type = self.type_combo.currentData()
        if action_type in ("key_press", "key_release"):
            self.value_edit.setText(self.action.get("key", ""))
        elif action_type in ("mouse_press", "mouse_release"):
            self.value_edit.setText(self.action.get("button", "LMB"))
        self.x_edit.setText(str(self.action.get("x", 0)))
        self.y_edit.setText(str(self.action.get("y", 0)))
        self.dx_edit.setText(str(self.action.get("dx", 0)))
        self.dy_edit.setText(str(self.action.get("dy", 0)))

    def update_field_visibility(self):
        action_type = self.type_combo.currentData()
        has_value = action_type in (
            "key_press",
            "key_release",
            "mouse_press",
            "mouse_release",
        )
        has_position = action_type in (
            "mouse_press",
            "mouse_release",
            "mouse_move",
            "scroll",
        )
        has_scroll = action_type == "scroll"
        self.value_label.setText(
            self.main_window.tr(
                "scenario_action_button"
                if action_type in ("mouse_press", "mouse_release")
                else "scenario_action_key"
            )
        )
        self.value_label.setVisible(has_value)
        self.value_edit.setVisible(has_value)
        self.x_label.setVisible(has_position)
        self.x_edit.setVisible(has_position)
        self.y_label.setVisible(has_position)
        self.y_edit.setVisible(has_position)
        self.dx_label.setVisible(has_scroll)
        self.dx_edit.setVisible(has_scroll)
        self.dy_label.setVisible(has_scroll)
        self.dy_edit.setVisible(has_scroll)

    def accept(self):
        action_type = self.type_combo.currentData()
        try:
            delay = float(self.delay_edit.text().replace(",", "."))
        except ValueError:
            delay = -1
        if not math.isfinite(delay) or delay < 0:
            QMessageBox.warning(
                self,
                self.main_window.tr("error_title"),
                self.main_window.tr("scenario_invalid_delay"),
            )
            return

        action = {"type": action_type, "delay": delay}
        if action_type in ("key_press", "key_release"):
            key = self.main_window._normalize_key_name(
                self.value_edit.text()
            )
            parsed = self.main_window.parse_key_token(key)
            reserved = (
                set(self.main_window.start_hotkey)
                | set(self.main_window.stop_hotkey)
                | {self.main_window.emergency_stop_key}
            )
            if (
                not key
                or parsed is None
                or isinstance(parsed, mouse.Button)
                or key in reserved
            ):
                QMessageBox.warning(
                    self,
                    self.main_window.tr("error_title"),
                    self.main_window.tr("scenario_invalid_key"),
                )
                return
            action["key"] = key
        elif action_type in ("mouse_press", "mouse_release"):
            button = self.value_edit.text().strip().upper()
            parsed = self.main_window.parse_key_token(button)
            reserved = (
                set(self.main_window.start_hotkey)
                | set(self.main_window.stop_hotkey)
                | {self.main_window.emergency_stop_key}
            )
            if (
                not isinstance(parsed, mouse.Button)
                or self.main_window._button_to_str(parsed) in reserved
            ):
                QMessageBox.warning(
                    self,
                    self.main_window.tr("error_title"),
                    self.main_window.tr("scenario_invalid_button"),
                )
                return
            action["button"] = self.main_window._button_to_str(parsed)

        if action_type in (
            "mouse_press",
            "mouse_release",
            "mouse_move",
            "scroll",
        ):
            try:
                action["x"] = int(self.x_edit.text())
                action["y"] = int(self.y_edit.text())
            except ValueError:
                QMessageBox.warning(
                    self,
                    self.main_window.tr("error_title"),
                    self.main_window.tr("scenario_invalid_position"),
                )
                return
            if any(
                not -100000 <= action[coordinate] <= 100000
                for coordinate in ("x", "y")
            ):
                QMessageBox.warning(
                    self,
                    self.main_window.tr("error_title"),
                    self.main_window.tr("scenario_invalid_position"),
                )
                return

        if action_type == "scroll":
            try:
                action["dx"] = int(self.dx_edit.text())
                action["dy"] = int(self.dy_edit.text())
            except ValueError:
                QMessageBox.warning(
                    self,
                    self.main_window.tr("error_title"),
                    self.main_window.tr("scenario_invalid_scroll"),
                )
                return
            if action["dx"] == 0 and action["dy"] == 0:
                QMessageBox.warning(
                    self,
                    self.main_window.tr("error_title"),
                    self.main_window.tr("scenario_invalid_scroll"),
                )
                return
            if any(
                not -100000 <= action[direction] <= 100000
                for direction in ("dx", "dy")
            ):
                QMessageBox.warning(
                    self,
                    self.main_window.tr("error_title"),
                    self.main_window.tr("scenario_invalid_scroll"),
                )
                return

        self.action = action
        super().accept()

class ModeTutorialSelectionDialog(QDialog):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.selected_modes = []
        self.setWindowTitle(main_window.tr("mode_tutorial_select_title"))
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        description = QLabel(
            main_window.tr("mode_tutorial_select_description")
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        for mode in main_window.available_modes():
            button = QPushButton(main_window.tr_mode(mode))
            button.clicked.connect(
                lambda _checked=False, selected_mode=mode:
                    self._select_modes([selected_mode])
            )
            layout.addWidget(button)

        self.show_all_button = QPushButton(
            main_window.tr("mode_tutorial_show_all")
        )
        self.show_all_button.setObjectName("blue")
        self.show_all_button.clicked.connect(
            lambda: self._select_modes(main_window.available_modes())
        )
        layout.addWidget(self.show_all_button)

        cancel_button = QPushButton(main_window.tr("dialog_cancel"))
        cancel_button.clicked.connect(self.reject)
        layout.addWidget(cancel_button)
        self.setMinimumWidth(360)

    def _select_modes(self, modes):
        self.selected_modes = list(modes)
        self.accept()


class ModeTutorialWizard(QWizard):
    def __init__(self, main_window, modes):
        super().__init__(
            main_window,
            Qt.Tool | Qt.WindowStaysOnTopHint,
        )
        self.main_window = main_window
        self.modes = list(modes)
        self.page_targets = []
        self.setWizardStyle(QWizard.ClassicStyle)
        self.setModal(False)

        theme_colors = THEME_COLOR_MAPS.get(main_window.theme, {})
        background_color = theme_colors.get("#060d16", "#060d16")
        text_color = theme_colors.get("#eef5ff", "#eef5ff")
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor(background_color))
        palette.setColor(QPalette.Base, QColor(background_color))
        palette.setColor(QPalette.WindowText, QColor(text_color))
        palette.setColor(QPalette.Text, QColor(text_color))
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        self.setWindowTitle(main_window.tr("mode_tutorial_title"))
        self.setButtonText(QWizard.BackButton, main_window.tr("tutorial_back"))
        self.setButtonText(QWizard.NextButton, main_window.tr("tutorial_next"))
        self.setButtonText(
            QWizard.FinishButton,
            main_window.tr("dialog_close"),
        )
        self.setButtonText(
            QWizard.CancelButton,
            main_window.tr("dialog_close"),
        )

        for mode in self.modes:
            for title_key, body, targets in self._steps_for_mode(mode):
                page = QWizardPage()
                page_palette = page.palette()
                page_palette.setColor(
                    QPalette.Window,
                    QColor(background_color),
                )
                page_palette.setColor(
                    QPalette.Base,
                    QColor(background_color),
                )
                page_palette.setColor(
                    QPalette.WindowText,
                    QColor(text_color),
                )
                page_palette.setColor(QPalette.Text, QColor(text_color))
                page.setPalette(page_palette)
                page.setAttribute(Qt.WA_StyledBackground, True)
                page.setStyleSheet(
                    f"background-color: {background_color}; "
                    f"color: {text_color};"
                )
                page.setTitle(
                    f"{main_window.tr_mode(mode)} — "
                    f"{main_window.tr(title_key)}"
                )
                label = QLabel(body)
                label.setWordWrap(True)
                label.setStyleSheet(
                    f"background-color: {background_color}; "
                    f"color: {text_color};"
                )
                page_layout = QVBoxLayout(page)
                page_layout.addWidget(label)
                self.addPage(page)
                self.page_targets.append((mode, targets))

        self.currentIdChanged.connect(self._highlight_current_step)
        self.finished.connect(
            lambda _result: main_window.clear_mode_tutorial_highlights()
        )
        self.resize(520, 360)
        self._position_next_to_main_window()
        self._highlight_current_step(self.currentId())

    def _steps_for_mode(self, mode):
        main_window = self.main_window
        mode_keys = {
            main_window.MODE_INSTANT: "instant",
            main_window.MODE_HOLD: "hold",
            main_window.MODE_COMBO: "combo",
            main_window.MODE_SEQUENCE: "sequence",
            main_window.MODE_COORDINATES: "coordinates",
            main_window.MODE_SCENARIO: "scenario",
        }
        mode_key = mode_keys[mode]
        mode_targets = {
            main_window.MODE_INSTANT: [
                main_window.hotkey_edit,
                main_window.assign_btn,
            ],
            main_window.MODE_HOLD: [
                main_window.hotkey_edit,
                main_window.assign_btn,
            ],
            main_window.MODE_COMBO: [
                main_window.sequence_edit,
                main_window.sequence_assign_btn,
                main_window.sequence_clear_btn,
            ],
            main_window.MODE_SEQUENCE: [
                main_window.sequence_edit,
                main_window.sequence_assign_btn,
                main_window.sequence_clear_btn,
            ],
            main_window.MODE_COORDINATES: [
                main_window.coordinate_record_button,
                main_window.coordinate_clear_button,
            ],
            main_window.MODE_SCENARIO: [
                main_window.main_scenario_record_button,
                main_window.main_scenario_edit_button,
            ],
        }
        timing_targets = {
            main_window.MODE_INSTANT: [
                main_window.min_interval_edit,
                main_window.max_interval_edit,
                main_window.random_interval,
            ],
            main_window.MODE_HOLD: [
                main_window.hold_time_edit,
                main_window.between_edit,
            ],
            main_window.MODE_COMBO: [
                main_window.min_interval_edit,
                main_window.max_interval_edit,
                main_window.random_interval,
            ],
            main_window.MODE_SEQUENCE: [
                main_window.between_edit,
                main_window.min_interval_edit,
                main_window.max_interval_edit,
                main_window.random_interval,
            ],
            main_window.MODE_COORDINATES: [
                main_window.coordinate_movement_group,
                main_window.coordinate_smooth_checkbox,
                main_window.coordinate_random_move_duration_checkbox,
                main_window.coordinate_move_duration_edit,
                main_window.coordinate_move_duration_min_edit,
                main_window.coordinate_move_duration_max_edit,
                main_window.coordinate_random_click_interval_checkbox,
                main_window.coordinate_cycle_interval_edit,
                main_window.coordinate_cycle_interval_max_edit,
                main_window.random_interval,
            ],
            main_window.MODE_SCENARIO: [
                main_window.main_scenario_summary,
                main_window.main_scenario_edit_button,
            ],
        }
        timing_targets[main_window.MODE_HOLD].append(
            main_window.random_interval
        )
        timing_targets[main_window.MODE_HOLD].extend(
            [
                main_window.min_interval_edit,
                main_window.max_interval_edit,
            ]
        )
        if mode == main_window.MODE_SCENARIO:
            limit_body = (
                main_window.tr("mode_tutorial_body_limits")
                + "\n\n"
                + main_window.tr("mode_tutorial_body_scenario_limit")
            )
            limit_targets = [
                main_window.duration_limit_checkbox,
                main_window.duration_limit_edit,
                main_window.scenario_run_limit_checkbox,
                main_window.scenario_run_limit_edit,
            ]
        else:
            limit_body = (
                main_window.tr("mode_tutorial_body_limits")
                + "\n\n"
                + main_window.tr("mode_tutorial_body_click_limit")
            )
            limit_targets = [
                main_window.duration_limit_checkbox,
                main_window.duration_limit_edit,
                main_window.click_limit_checkbox,
                main_window.click_limit_edit,
            ]
        return (
            (
                "mode_tutorial_step_choose",
                main_window.tr("mode_tutorial_body_choose").format(
                    main_window.tr_mode(mode)
                ),
                [main_window.mode],
            ),
            (
                "mode_tutorial_step_controls",
                main_window.tr(f"mode_tutorial_controls_{mode_key}"),
                mode_targets[mode],
            ),
            (
                "mode_tutorial_step_timing",
                main_window.tr(f"mode_tutorial_timing_{mode_key}"),
                timing_targets[mode],
            ),
            (
                "mode_tutorial_step_limits",
                limit_body,
                limit_targets,
            ),
            (
                "mode_tutorial_step_hotkeys",
                main_window.tr("mode_tutorial_body_hotkeys"),
                [
                    main_window.hk_start_edit,
                    main_window.assign_hk_start,
                    main_window.hk_stop_edit,
                    main_window.assign_hk_stop,
                    main_window.enable_hk_btn,
                    main_window.disable_hk_btn,
                ],
            ),
            (
                "mode_tutorial_step_run",
                main_window.tr("mode_tutorial_body_run"),
                [
                    main_window.start_btn,
                    main_window.stop_btn,
                    main_window.profiles_title_label,
                    main_window.add_profile_btn,
                ],
            ),
        )

    def _position_next_to_main_window(self):
        screen = self.main_window.screen()
        if screen is None:
            return
        available = screen.availableGeometry()
        main_rect = self.main_window.frameGeometry()
        x = main_rect.right() + 12
        if x + self.width() > available.right():
            x = main_rect.left() - self.width() - 12
        if x < available.left():
            x = available.right() - self.width()
        y = min(
            max(main_rect.top(), available.top()),
            available.bottom() - self.height(),
        )
        self.move(x, y)

    def _highlight_current_step(self, page_id):
        if 0 <= page_id < len(self.page_targets):
            mode, targets = self.page_targets[page_id]
            self.main_window.mode.setCurrentIndex(
                self.main_window.available_modes().index(mode)
            )
            self.main_window.highlight_mode_tutorial_targets(targets)

    def closeEvent(self, event):
        self.main_window.clear_mode_tutorial_highlights()
        super().closeEvent(event)


class ScenarioEditorDialog(QDialog):
    def __init__(self, actions, parent):
        super().__init__(parent)
        self.parent_editor = parent
        self.main_window = (
            parent if hasattr(parent, "MODE_SCENARIO") else parent.parent
        )
        self.actions = deepcopy(actions)
        self.setWindowTitle(self.main_window.tr("scenario_editor_title"))
        self.resize(620, 480)

        layout = QVBoxLayout(self)
        self.actions_list = QListWidget()
        layout.addWidget(self.actions_list)

        buttons = QHBoxLayout()
        self.add_button = QPushButton(
            self.main_window.tr("scenario_action_add")
        )
        self.edit_button = QPushButton(
            self.main_window.tr("scenario_action_edit")
        )
        self.delete_button = QPushButton(
            self.main_window.tr("scenario_action_delete")
        )
        self.up_button = QPushButton(
            self.main_window.tr("scenario_action_up")
        )
        self.down_button = QPushButton(
            self.main_window.tr("scenario_action_down")
        )
        for button in (
            self.add_button,
            self.edit_button,
            self.delete_button,
            self.up_button,
            self.down_button,
        ):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        dialog_buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        dialog_buttons.accepted.connect(self.accept)
        dialog_buttons.rejected.connect(self.reject)
        layout.addWidget(dialog_buttons)
        dialog_buttons.button(QDialogButtonBox.Save).setText(
            self.main_window.tr("scenario_editor_save_button")
        )
        dialog_buttons.button(QDialogButtonBox.Cancel).setText(
            self.main_window.tr("dialog_cancel")
        )

        self.add_button.clicked.connect(self.add_action)
        self.edit_button.clicked.connect(self.edit_action)
        self.delete_button.clicked.connect(self.delete_action)
        self.up_button.clicked.connect(lambda: self.move_action(-1))
        self.down_button.clicked.connect(lambda: self.move_action(1))
        self.actions_list.currentRowChanged.connect(self.update_buttons)
        self.refresh_actions()

    def action_summary(self, action):
        translate = self.main_window.tr
        action_type = action["type"]
        type_names = dict(ScenarioActionEditDialog.ACTIONS)
        summary = translate(type_names[action_type])
        if "key" in action:
            summary += f": {action['key']}"
        elif "button" in action:
            summary += f": {action['button']}"
        elif action_type == "mouse_move":
            summary += f": {action['x']}, {action['y']}"
        elif action_type == "scroll":
            summary += (
                f": {action['dx']}, {action['dy']} "
                f"({action['x']}, {action['y']})"
            )
        summary += f" · {format_interval_value(action['delay'])} s"
        return summary

    def refresh_actions(self, row=0):
        self.actions_list.clear()
        for action in self.actions:
            self.actions_list.addItem(self.action_summary(action))
        if self.actions:
            self.actions_list.setCurrentRow(
                min(max(row, 0), len(self.actions) - 1)
            )
        self.update_buttons()

    def update_buttons(self):
        row = self.actions_list.currentRow()
        selected = 0 <= row < len(self.actions)
        self.edit_button.setEnabled(selected)
        self.delete_button.setEnabled(selected)
        self.up_button.setEnabled(selected and row > 0)
        self.down_button.setEnabled(selected and row < len(self.actions) - 1)

    def add_action(self):
        if len(self.actions) >= MAX_SCENARIO_ACTIONS:
            QMessageBox.warning(
                self,
                self.main_window.tr("error_title"),
                self.main_window.tr("scenario_action_limit"),
            )
            return
        dialog = ScenarioActionEditDialog(
            {"type": "key_press", "key": "A", "delay": 0.0},
            self.parent_editor,
        )
        if dialog.exec() == QDialog.Accepted:
            row = self.actions_list.currentRow() + 1
            self.actions.insert(row, dialog.action)
            self.refresh_actions(row)

    def edit_action(self):
        row = self.actions_list.currentRow()
        if not 0 <= row < len(self.actions):
            return
        dialog = ScenarioActionEditDialog(
            self.actions[row],
            self.parent_editor,
        )
        if dialog.exec() == QDialog.Accepted:
            self.actions[row] = dialog.action
            self.refresh_actions(row)

    def delete_action(self):
        row = self.actions_list.currentRow()
        if 0 <= row < len(self.actions):
            self.actions.pop(row)
            self.refresh_actions(row)

    def move_action(self, offset):
        row = self.actions_list.currentRow()
        target = row + offset
        if 0 <= row < len(self.actions) and 0 <= target < len(self.actions):
            self.actions[row], self.actions[target] = (
                self.actions[target],
                self.actions[row],
            )
            self.refresh_actions(target)

    def accept(self):
        super().accept()


# ============================================================
# DIALOG FOR EDITING PROFILE
# ============================================================
class ProfileEditDialog(QDialog):
    def __init__(self, profile_data, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle(parent.tr('profile_edit_title') if parent else "Edit Profile")
        self.setModal(True)
        self.profile = profile_data.copy()
        self.binding_recording = False
        self.scenario_actions = deepcopy(self.profile.get("scenario", []))
        self.scenario_record_state = "idle"

        layout = QFormLayout(self)

        self.name_edit = QLineEdit(self.profile.get("name", ""))
        self.icon_edit = QLineEdit(self.profile.get("icon", "✨"))
        self.key_edit = QLineEdit(parent.display_key_token(self.profile.get("key", "SPACE")))
        self.key_edit.setReadOnly(True)
        self.key_assign_btn = QPushButton(parent.tr('button_assign'))
        self.key_assign_btn.setObjectName("blue")
        self.key_assign_btn.setFocusPolicy(Qt.NoFocus)
        self.key_assign_btn.clicked.connect(self.bind_key)
        key_box = QHBoxLayout()
        key_box.addWidget(self.key_edit)
        key_box.addWidget(self.key_assign_btn)
        self.name_label = QLabel()
        self.icon_label = QLabel()
        self.mode_combo = QComboBox()
        modes = [
            parent.tr('mode_instant'),
            parent.tr('mode_hold'),
            parent.tr('mode_combo'),
            parent.tr('mode_sequence'),
            parent.tr('mode_coordinates'),
            parent.tr('mode_scenario'),
        ]
        self.mode_combo.addItems(modes)
        mode_names = {
            parent.MODE_INSTANT: parent.tr('mode_instant'),
            parent.MODE_HOLD: parent.tr('mode_hold'),
            parent.MODE_COMBO: parent.tr('mode_combo'),
            parent.MODE_SEQUENCE: parent.tr('mode_sequence'),
            parent.MODE_COORDINATES: parent.tr('mode_coordinates'),
            parent.MODE_SCENARIO: parent.tr('mode_scenario'),
            "Instant press": parent.tr('mode_instant'),
            "Hold key": parent.tr('mode_hold'),
            "Instant combo": parent.tr('mode_combo'),
            "Sequence press": parent.tr('mode_sequence'),
            "Coordinate clicks": parent.tr('mode_coordinates'),
            "Recorded scenario": parent.tr('mode_scenario'),
            "Обычный клик": parent.tr('mode_instant'),
        }
        current_mode = mode_names.get(
            self.profile.get("mode", parent.MODE_INSTANT),
            parent.tr('mode_instant')
        )
        idx = self.mode_combo.findText(current_mode)
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)
        else:
            self.mode_combo.setCurrentIndex(0)

        self.min_edit = self._create_interval_edit(self.profile.get("min", 1.0))
        self.max_edit = self._create_interval_edit(self.profile.get("max", 1.0))
        self.hold_edit = self._create_interval_edit(self.profile.get("hold", 1.0))
        self.between_edit = self._create_interval_edit(self.profile.get("between", 0.2))
        self.random_interval = QCheckBox(parent.tr('label_random_interval'))
        is_coordinate_profile = self.mode_combo.currentIndex() == 4
        same_bounds = float(self.profile.get("min", 1.0)) == float(
            self.profile.get("max", 1.0)
        )
        self.random_interval.setChecked(
            (
                self.profile.get(
                    "coordinate_random_cycle_interval",
                    False,
                )
                if is_coordinate_profile
                else self.profile.get("random", True) and not same_bounds
            )
        )
        self.random_interval.stateChanged.connect(self.update_interval_ui)
        self.coordinate_random_click_interval_checkbox = QCheckBox(
            parent.tr('label_coordinate_random_interval')
        )
        self.coordinate_random_click_interval_checkbox.setChecked(
            self.profile.get(
                "coordinate_random_click_interval",
                self.profile.get("random", True),
            )
            and not same_bounds
        )
        self.coordinate_random_click_interval_checkbox.stateChanged.connect(
            self.update_interval_ui
        )
        self.min_edit.textChanged.connect(self.update_interval_ui)
        self.max_edit.textChanged.connect(self.update_interval_ui)
        self.sequence_edit = QTextEdit(self.profile.get("sequence", ""))
        self.sequence_edit.setMaximumHeight(90)
        self.sequence_edit.installEventFilter(self)
        self.recording = False
        self.record_btn = QPushButton(parent.tr('button_record'))
        self.record_btn.setCheckable(True)
        self.record_btn.clicked.connect(self.toggle_recording)
        self.clear_btn = QPushButton(parent.tr('button_clear'))
        self.clear_btn.clicked.connect(self.sequence_edit.clear)
        sequence_box = QVBoxLayout()
        sequence_box.addWidget(self.sequence_edit)
        sequence_buttons = QHBoxLayout()
        sequence_buttons.addWidget(self.record_btn)
        sequence_buttons.addWidget(self.clear_btn)
        sequence_box.addLayout(sequence_buttons)
        sequence_widget = QWidget()
        sequence_widget.setLayout(sequence_box)
        self.sequence_widget = sequence_widget
        self.coordinate_points = deepcopy(
            self.profile.get("coordinates", [])
        )
        self.coordinate_label = QLabel()
        self.coordinate_points_label = QLabel()
        self.coordinate_points_label.setWordWrap(True)
        self.coordinate_record_button = QPushButton()
        self.coordinate_record_button.clicked.connect(
            self.open_coordinate_recorder
        )
        self.coordinate_clear_button = QPushButton(
            parent.tr('button_clear')
        )
        self.coordinate_clear_button.clicked.connect(
            self.clear_coordinate_points
        )
        coordinate_layout = QVBoxLayout()
        coordinate_layout.addWidget(self.coordinate_points_label)
        coordinate_buttons = QHBoxLayout()
        coordinate_buttons.addWidget(self.coordinate_record_button)
        coordinate_buttons.addWidget(self.coordinate_clear_button)
        coordinate_layout.addLayout(coordinate_buttons)

        self.coordinate_movement_group = QGroupBox()
        movement_layout = QVBoxLayout(self.coordinate_movement_group)
        self.coordinate_smooth_checkbox = QCheckBox(
            parent.tr('coordinate_smooth_move')
        )
        self.coordinate_smooth_checkbox.setChecked(
            self.profile.get("coordinate_smooth", False)
        )
        self.coordinate_smooth_checkbox.stateChanged.connect(
            self.update_coordinate_move_ui
        )
        self.coordinate_random_move_duration_checkbox = QCheckBox(
            parent.tr('coordinate_random_move_duration')
        )
        self.coordinate_random_move_duration_checkbox.setChecked(
            self.profile.get("coordinate_random_move_duration", False)
        )
        self.coordinate_random_move_duration_checkbox.stateChanged.connect(
            self.update_coordinate_move_ui
        )
        self.coordinate_move_duration_edit = self._create_interval_edit(
            self.profile.get("coordinate_move_duration", 0.3)
        )
        self.coordinate_move_duration_label = QLabel()
        self.coordinate_move_duration_min_edit = self._create_interval_edit(
            self.profile.get("coordinate_move_duration", 0.3)
        )
        self.coordinate_move_duration_min_label = QLabel()
        self.coordinate_move_duration_max_edit = self._create_interval_edit(
            self.profile.get(
                "coordinate_move_duration_max",
                max(
                    0.5,
                    self.profile.get("coordinate_move_duration", 0.3),
                ),
            )
        )
        self.coordinate_move_duration_max_label = QLabel()
        movement_layout.addWidget(self.coordinate_smooth_checkbox)
        movement_layout.addWidget(
            self.coordinate_random_move_duration_checkbox
        )
        coordinate_duration_row = QHBoxLayout()
        coordinate_duration_row.addWidget(
            self.coordinate_move_duration_label
        )
        coordinate_duration_row.addWidget(
            self.coordinate_move_duration_edit
        )
        movement_layout.addLayout(coordinate_duration_row)
        coordinate_random_duration_row = QHBoxLayout()
        coordinate_random_duration_row.addWidget(
            self.coordinate_move_duration_min_label
        )
        coordinate_random_duration_row.addWidget(
            self.coordinate_move_duration_min_edit
        )
        coordinate_random_duration_row.addWidget(
            self.coordinate_move_duration_max_label
        )
        coordinate_random_duration_row.addWidget(
            self.coordinate_move_duration_max_edit
        )
        movement_layout.addLayout(coordinate_random_duration_row)
        coordinate_layout.addWidget(self.coordinate_movement_group)

        self.coordinate_cycle_interval_edit = self._create_interval_edit(
            self.profile.get("coordinate_cycle_interval", 0.5)
        )
        self.coordinate_cycle_interval_label = QLabel()
        self.coordinate_cycle_interval_max_edit = self._create_interval_edit(
            self.profile.get(
                "coordinate_cycle_interval_max",
                max(
                    1.0,
                    self.profile.get("coordinate_cycle_interval", 0.5),
                ),
            )
        )
        self.coordinate_cycle_interval_max_label = QLabel()
        coordinate_cycle_row = QHBoxLayout()
        coordinate_cycle_row.addWidget(
            self.coordinate_cycle_interval_label
        )
        coordinate_cycle_row.addWidget(
            self.coordinate_cycle_interval_edit
        )
        coordinate_layout.addLayout(coordinate_cycle_row)
        coordinate_cycle_max_row = QHBoxLayout()
        coordinate_cycle_max_row.addWidget(
            self.coordinate_cycle_interval_max_label
        )
        coordinate_cycle_max_row.addWidget(
            self.coordinate_cycle_interval_max_edit
        )
        coordinate_layout.addLayout(coordinate_cycle_max_row)
        coordinate_widget = QWidget()
        coordinate_widget.setLayout(coordinate_layout)
        self.coordinate_widget = coordinate_widget

        self.scenario_widget = QWidget()
        scenario_layout = QVBoxLayout(self.scenario_widget)
        scenario_layout.setContentsMargins(0, 0, 0, 0)
        self.scenario_summary = QLabel()
        self.scenario_summary.setWordWrap(True)
        scenario_layout.addWidget(self.scenario_summary)
        scenario_buttons = QHBoxLayout()
        self.scenario_record_button = QPushButton()
        self.scenario_record_button.clicked.connect(
            lambda: parent.arm_scenario_recording(self)
        )
        self.scenario_edit_button = QPushButton()
        self.scenario_edit_button.clicked.connect(self.edit_scenario)
        self.scenario_clear_button = QPushButton()
        self.scenario_clear_button.clicked.connect(self.clear_scenario)
        for button in (
            self.scenario_record_button,
            self.scenario_edit_button,
            self.scenario_clear_button,
        ):
            scenario_buttons.addWidget(button)
        scenario_layout.addLayout(scenario_buttons)

        layout.addRow(self.name_label, self.name_edit)
        layout.addRow(self.icon_label, self.icon_edit)
        self.key_edit.installEventFilter(self)
        self.key_label = QLabel(parent.tr('label_click_key') + ":")
        layout.addRow(self.key_label, key_box)
        self.mode_label = QLabel()
        layout.addRow(self.mode_label, self.mode_combo)
        self.sequence_label = QLabel(parent.tr('label_sequence') + ":")
        layout.addRow(self.sequence_label, sequence_widget)
        layout.addRow(self.coordinate_label, self.coordinate_widget)
        layout.addRow(self.scenario_widget)
        layout.addRow(self.random_interval)
        self.min_label = QLabel()
        self.max_label = QLabel()
        self.hold_label = QLabel()
        self.between_label = QLabel()
        layout.addRow(self.min_label, self.min_edit)
        layout.addRow(self.max_label, self.max_edit)
        layout.addRow(self.coordinate_random_click_interval_checkbox)
        layout.addRow(self.hold_label, self.hold_edit)
        layout.addRow(self.between_label, self.between_edit)
        self._last_mode_index = self.mode_combo.currentIndex()
        self.update_interval_ui()
        self.update_coordinate_move_ui()
        self.update_mode_ui(self.mode_combo.currentIndex())
        self.mode_combo.currentIndexChanged.connect(self.update_mode_ui)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        self.dialog_buttons = buttons
        self.update_language()

    def update_language(self):
        self.setWindowTitle(self.parent.tr('profile_edit_title'))
        self.name_label.setText(self.parent.tr('profile_name') + ":")
        self.icon_label.setText(self.parent.tr('profile_icon') + ":")
        self.key_label.setText(self.parent.tr('label_click_key') + ":")
        self.mode_label.setText(self.parent.tr('label_mode') + ":")
        self.sequence_label.setText(self.parent.tr('label_sequence') + ":")
        self.coordinate_label.setText(
            self.parent.tr('coordinate_points_label') + ":"
        )
        self.coordinate_record_button.setText(
            self.parent.tr('coordinate_record_button')
        )
        self.coordinate_clear_button.setText(
            self.parent.tr('button_clear')
        )
        if self.scenario_record_state == "armed":
            record_button_text = self.parent.tr(
                "scenario_record_armed",
                self.parent._hotkey_name(self.parent.start_hotkey),
            )
        elif self.scenario_record_state == "recording":
            record_button_text = self.parent.tr(
                "scenario_recording_status",
                len(self.scenario_actions),
                self.parent._hotkey_name(self.parent.stop_hotkey),
            )
        else:
            record_button_text = self.parent.tr("scenario_record_button")
        self.scenario_record_button.setText(record_button_text)
        self.scenario_record_button.setEnabled(
            self.scenario_record_state not in ("armed", "recording")
        )
        self.scenario_edit_button.setText(
            self.parent.tr("scenario_action_edit")
        )
        self.scenario_clear_button.setText(
            self.parent.tr("button_clear")
        )
        self._refresh_scenario_summary()
        self.coordinate_smooth_checkbox.setText(
            self.parent.tr('coordinate_smooth_move')
        )
        self.coordinate_move_duration_label.setText(
            self.parent.tr('coordinate_move_duration') + ":"
        )
        self.coordinate_random_move_duration_checkbox.setText(
            self.parent.tr('coordinate_random_move_duration')
        )
        self.coordinate_move_duration_min_label.setText(
            self.parent.tr('coordinate_move_duration_min') + ":"
        )
        self.coordinate_move_duration_max_label.setText(
            self.parent.tr('coordinate_move_duration_max') + ":"
        )
        self.coordinate_cycle_interval_label.setText(
            self.parent.tr('coordinate_cycle_interval') + ":"
        )
        self.coordinate_cycle_interval_max_label.setText(
            self.parent.tr('coordinate_cycle_interval_max') + ":"
        )
        self.coordinate_movement_group.setTitle(
            self.parent.tr('coordinate_movement_group')
        )
        self._refresh_coordinate_summary()
        self.hold_label.setText(self.parent.tr('label_hold') + ":")
        self.between_label.setText(self.parent.tr('label_interval_seq') + ":")
        self.coordinate_random_click_interval_checkbox.setText(
            self.parent.tr('label_coordinate_random_interval')
        )
        self.update_interval_ui()
        self.record_btn.setText(
            self.parent.tr('button_stop_recording') if self.recording
            else self.parent.tr('button_record')
        )
        self.clear_btn.setText(self.parent.tr('button_clear'))
        self.dialog_buttons.button(QDialogButtonBox.Ok).setText(
            self.parent.tr('dialog_ok')
        )
        self.dialog_buttons.button(QDialogButtonBox.Cancel).setText(
            self.parent.tr('dialog_cancel')
        )

    @staticmethod
    def _create_interval_edit(value):
        edit = QLineEdit(format_interval_value(max(0.0, float(value))))
        edit.setValidator(IntervalValidator(edit))
        return edit

    @staticmethod
    def _interval_value(edit):
        try:
            return max(0.0, float(edit.text().replace(",", ".")))
        except ValueError:
            return 0.0

    def accept(self):
        if self.parent.scenario_record_dialog is self:
            QMessageBox.warning(
                self,
                self.parent.tr("scenario_editor_title"),
                self.parent.tr("scenario_record_busy"),
            )
            return
        if (
            self.mode_combo.currentIndex() == 4
            and (
                self.coordinate_smooth_checkbox.isChecked()
                or has_coordinate_swipe(self.coordinate_points)
            )
            and self.coordinate_random_move_duration_checkbox.isChecked()
            and self._interval_value(
                self.coordinate_move_duration_min_edit
            )
            > self._interval_value(self.coordinate_move_duration_max_edit)
        ):
            QMessageBox.warning(
                self,
                self.parent.tr('error_title'),
                self.parent.tr('coordinate_move_duration_order'),
            )
            return
        if (
            self.mode_combo.currentIndex() == 4
            and self.random_interval.isChecked()
            and self._interval_value(self.coordinate_cycle_interval_edit)
            > self._interval_value(
                self.coordinate_cycle_interval_max_edit
            )
        ):
            QMessageBox.warning(
                self,
                self.parent.tr('error_title'),
                self.parent.tr('coordinate_cycle_interval_order'),
            )
            return
        if (
            self.mode_combo.currentIndex() == 4
            and not self.coordinate_smooth_checkbox.isChecked()
            and self.coordinate_random_click_interval_checkbox.isChecked()
            and self._interval_value(self.min_edit)
            > self._interval_value(self.max_edit)
        ):
            QMessageBox.warning(
                self,
                self.parent.tr('error_title'),
                self.parent.tr('coordinate_click_interval_order'),
            )
            return
        super().accept()

    def reject(self):
        if self.parent is not None:
            self.parent._cancel_scenario_recording(self)
        super().reject()

    def get_profile(self):
        mode_names = [
            self.parent.tr('mode_instant'),
            self.parent.tr('mode_hold'),
            self.parent.tr('mode_combo'),
            self.parent.tr('mode_sequence'),
            self.parent.tr('mode_coordinates'),
            self.parent.tr('mode_scenario'),
        ]
        is_coordinate_mode = self.mode_combo.currentIndex() == 4
        random_click_interval = (
            self.coordinate_random_click_interval_checkbox.isChecked()
            and not self.coordinate_smooth_checkbox.isChecked()
            if is_coordinate_mode
            else self.random_interval.isChecked()
        )
        return {
            "icon": self.icon_edit.text(),
            "name": self.name_edit.text(),
            "mode": mode_names[self.mode_combo.currentIndex()],
            "min": self._interval_value(self.min_edit),
            "max": self._interval_value(self.max_edit),
            "hold": self._interval_value(self.hold_edit),
            "between": self._interval_value(self.between_edit),
            "key": self.parent.profile_key_to_storage(self.key_edit.text()),
            "sequence": self.sequence_edit.toPlainText(),
            "coordinates": deepcopy(self.coordinate_points),
            "scenario": deepcopy(self.scenario_actions),
            "coordinate_smooth": (
                self.coordinate_smooth_checkbox.isChecked()
            ),
            "coordinate_move_duration": self._interval_value(
                self.coordinate_move_duration_min_edit
                if self.coordinate_random_move_duration_checkbox.isChecked()
                else self.coordinate_move_duration_edit
            ),
            "coordinate_random_move_duration": (
                self.coordinate_random_move_duration_checkbox.isChecked()
            ),
            "coordinate_move_duration_max": self._interval_value(
                self.coordinate_move_duration_max_edit
            ),
            "coordinate_cycle_interval": self._interval_value(
                self.coordinate_cycle_interval_edit
            ),
            "coordinate_cycle_interval_max": self._interval_value(
                self.coordinate_cycle_interval_max_edit
            ),
            "coordinate_random_cycle_interval": (
                self.random_interval.isChecked()
            ),
            "coordinate_random_click_interval": (
                self.coordinate_random_click_interval_checkbox.isChecked()
            ),
            "random": (
                random_click_interval
                and not interval_fields_match(self.min_edit, self.max_edit)
            ),
        }

    def update_interval_ui(self):
        enabled = self.random_interval.isChecked()
        is_coordinate_mode = (
            self.mode_combo.currentIndex() == 4
        )
        click_random_enabled = (
            self.coordinate_random_click_interval_checkbox.isChecked()
        )
        show_click_interval = not (
            is_coordinate_mode
            and self.coordinate_smooth_checkbox.isChecked()
        )
        self.min_label.setText(
            self.parent.tr(
                'label_coordinate_min'
                if is_coordinate_mode and click_random_enabled
                else 'label_coordinate_single_interval'
                if is_coordinate_mode
                else 'label_min'
                if enabled
                else 'label_single_interval'
            ) + ":"
        )
        self.max_label.setText(
            self.parent.tr(
                'label_coordinate_max'
                if is_coordinate_mode
                else 'label_max'
            ) + ":"
        )
        self.min_label.setVisible(show_click_interval)
        self.min_edit.setVisible(show_click_interval)
        show_max_interval = (
            show_click_interval and click_random_enabled
            if is_coordinate_mode
            else self.random_interval.isChecked()
        )
        self.max_label.setVisible(show_max_interval)
        self.max_edit.setVisible(show_max_interval)
        self.coordinate_random_click_interval_checkbox.setVisible(
            is_coordinate_mode and show_click_interval
        )
        self.random_interval.setText(
            self.parent.tr(
                'label_coordinate_random_cycle_interval'
                if is_coordinate_mode
                else 'label_random_interval'
            )
        )
        self.random_interval.setVisible(True)
        if is_coordinate_mode:
            self.coordinate_cycle_interval_label.setText(
                self.parent.tr(
                    'coordinate_cycle_interval_min'
                    if self.random_interval.isChecked()
                    else 'coordinate_cycle_interval'
                ) + ":"
            )
        self.random_interval.setText(
            self.parent.tr(
                'label_coordinate_random_cycle_interval'
                if is_coordinate_mode
                else 'label_random_interval'
            )
        )
        self.random_interval.setVisible(True)
        self.coordinate_cycle_interval_max_label.setVisible(
            is_coordinate_mode and self.random_interval.isChecked()
        )
        self.coordinate_cycle_interval_max_edit.setVisible(
            is_coordinate_mode and self.random_interval.isChecked()
        )

    def update_coordinate_move_ui(self):
        is_coordinate_mode = self.mode_combo.currentIndex() == 4
        uses_coordinate_movement = (
            is_coordinate_mode
            and (
                self.coordinate_smooth_checkbox.isChecked()
                or has_coordinate_swipe(self.coordinate_points)
            )
        )
        show_duration = uses_coordinate_movement
        random_duration = (
            show_duration
            and self.coordinate_random_move_duration_checkbox.isChecked()
        )
        self.coordinate_move_duration_label.setVisible(
            show_duration and not random_duration
        )
        self.coordinate_random_move_duration_checkbox.setVisible(
            show_duration
        )
        self.coordinate_move_duration_edit.setVisible(
            show_duration and not random_duration
        )
        self.coordinate_move_duration_min_label.setVisible(random_duration)
        self.coordinate_move_duration_min_edit.setVisible(random_duration)
        self.coordinate_move_duration_max_label.setVisible(random_duration)
        self.coordinate_move_duration_max_edit.setVisible(random_duration)
        self.coordinate_movement_group.setVisible(
            is_coordinate_mode
        )
        self.coordinate_cycle_interval_label.setVisible(is_coordinate_mode)
        self.coordinate_cycle_interval_edit.setVisible(is_coordinate_mode)
        self.coordinate_cycle_interval_max_label.setVisible(
            is_coordinate_mode and self.random_interval.isChecked()
        )
        self.coordinate_cycle_interval_max_edit.setVisible(
            is_coordinate_mode and self.random_interval.isChecked()
        )
        self.update_interval_ui()

    def update_mode_ui(self, index):
        if index != self._last_mode_index:
            same_bounds = interval_fields_match(
                self.min_edit,
                self.max_edit,
            )
            if self._last_mode_index == 4:
                self.profile["coordinate_random_cycle_interval"] = (
                    self.random_interval.isChecked()
                )
                self.profile["coordinate_random_click_interval"] = (
                    self.coordinate_random_click_interval_checkbox.isChecked()
                )
                self.profile["random"] = (
                    self.coordinate_random_click_interval_checkbox.isChecked()
                    and not same_bounds
                )
            else:
                self.profile["random"] = (
                    self.random_interval.isChecked()
                    and not same_bounds
                )

            if index == 4:
                self.random_interval.setChecked(
                    self.profile.get(
                        "coordinate_random_cycle_interval",
                        False,
                    )
                )
                self.coordinate_random_click_interval_checkbox.setChecked(
                    self.profile.get(
                        "coordinate_random_click_interval",
                        self.profile.get("random", True),
                    )
                    and not same_bounds
                )
            else:
                self.random_interval.setChecked(
                    self.profile.get("random", True) and not same_bounds
                )
            self._last_mode_index = index

        is_sequence_mode = index in (2, 3)
        is_coordinate_mode = index == 4
        is_scenario_mode = index == 5
        needs_sequence_input = (
            is_sequence_mode or is_coordinate_mode or is_scenario_mode
        )
        self.key_edit.setVisible(not needs_sequence_input)
        self.key_assign_btn.setVisible(not needs_sequence_input)
        self.key_label.setVisible(not needs_sequence_input)
        self.sequence_label.setVisible(is_sequence_mode)
        self.sequence_widget.setVisible(is_sequence_mode)
        self.sequence_edit.setVisible(is_sequence_mode)
        self.record_btn.setVisible(is_sequence_mode)
        self.clear_btn.setVisible(is_sequence_mode)
        self.coordinate_label.setVisible(is_coordinate_mode)
        self.coordinate_widget.setVisible(is_coordinate_mode)
        self.scenario_widget.setVisible(is_scenario_mode)
        self.coordinate_smooth_checkbox.setVisible(is_coordinate_mode)
        self.update_interval_ui()
        self.update_coordinate_move_ui()
        is_hold_mode = index == 1
        self.hold_label.setVisible(is_hold_mode)
        self.hold_edit.setVisible(is_hold_mode)
        is_sequence_mode = index == 3
        self.between_label.setVisible(is_sequence_mode)
        self.between_edit.setVisible(is_sequence_mode)

    def open_coordinate_recorder(self):
        points = self.parent.record_coordinate_points(
            self.coordinate_points
        )
        if points is not None:
            self.coordinate_points = points
            self._refresh_coordinate_summary()
            self.update_coordinate_move_ui()

    def edit_scenario(self):
        dialog = ScenarioEditorDialog(self.scenario_actions, self)
        self.parent.apply_theme()
        if dialog.exec() == QDialog.Accepted:
            self.scenario_actions = dialog.actions
            self._refresh_scenario_summary()

    def clear_scenario(self):
        reply = QMessageBox.question(
            self,
            self.parent.tr("scenario_editor_title"),
            self.parent.tr("scenario_record_overwrite"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.scenario_actions.clear()
            self._refresh_scenario_summary()

    def handle_scenario_capture_update(self, state, actions=None):
        self.scenario_record_state = state
        if state == "finished" and actions is not None:
            self.scenario_actions = deepcopy(actions)
            self.scenario_record_state = "idle"
            self._refresh_scenario_summary()
        elif state == "cancelled":
            self.scenario_record_state = "idle"
        if state == "armed":
            text = self.parent.tr(
                "scenario_record_armed",
                self.parent._hotkey_name(self.parent.start_hotkey),
            )
        elif state == "recording":
            count = actions if isinstance(actions, int) else len(
                self.scenario_actions
            )
            text = self.parent.tr(
                "scenario_recording_status",
                count,
                self.parent._hotkey_name(self.parent.stop_hotkey),
            )
        else:
            text = self.parent.tr("scenario_record_button")
        self.scenario_record_button.setText(text)
        self.scenario_record_button.setEnabled(
            self.scenario_record_state not in ("armed", "recording")
        )

    def _refresh_scenario_summary(self):
        if not hasattr(self, "scenario_summary"):
            return
        self.scenario_summary.setText(
            self.parent.tr(
                "scenario_record_finished",
                len(self.scenario_actions),
            )
            if self.scenario_actions
            else self.parent.tr("scenario_actions_empty")
        )

    def clear_coordinate_points(self):
        self.coordinate_points.clear()
        self._refresh_coordinate_summary()
        self.update_coordinate_move_ui()

    def _refresh_coordinate_summary(self):
        self.coordinate_points_label.setText(
            self.parent.tr(
                'coordinate_points_count',
                len(self.coordinate_points),
            )
            if self.coordinate_points
            else self.parent.tr('coordinate_points_empty')
        )

    def bind_key(self):
        self.binding_recording = True
        self.key_edit.setText(self.parent.tr('button_record'))
        self.key_edit.setFocus()
        self.parent.profile_dialog = self

    def capture_key(self, key):
        if not self.binding_recording:
            return
        self.binding_recording = False
        self.key_edit.setText(self.parent.get_binding_name(key, "keyboard"))
        self.parent.profile_dialog = None

    def capture_key_token(self, token):
        if not token:
            return
        self.binding_recording = False
        self.key_edit.setText(self.parent.display_key_token(token))
        self.parent.profile_dialog = None

    def capture_mouse(self, button):
        if not self.binding_recording:
            return
        self.binding_recording = False
        self.key_edit.setText(self.parent.get_binding_name(button, "mouse"))
        self.parent.profile_dialog = None

    def toggle_recording(self):
        self.recording = self.record_btn.isChecked()
        self.sequence_edit.setReadOnly(not self.recording)
        self.record_btn.setText(
            self.parent.tr('button_stop_recording') if self.recording
            else self.parent.tr('button_record')
        )

    def closeEvent(self, event):
        if self.parent is not None:
            self.parent._cancel_scenario_recording(self)
        if self.parent.profile_dialog is self:
            self.parent.profile_dialog = None
        super().closeEvent(event)

    def _capture_token(self, token):
        if not self.recording or not token:
            return
        if self.mode_combo.currentIndex() == 2:
            current = [part.strip() for part in self.sequence_edit.toPlainText().split('+') if part.strip()]
            if token not in current:
                current.append(token)
            self.sequence_edit.setPlainText('+'.join(current))
        else:
            current = self.sequence_edit.toPlainText().strip()
            self.sequence_edit.setPlainText(f"{current}, {token}" if current else token)

    def eventFilter(self, watched, event):
        if watched is self.key_edit and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Escape:
                self.binding_recording = False
                self.parent.profile_dialog = None
                self.key_edit.clearFocus()
            elif self.binding_recording:
                self.capture_key_token(self.parent._qt_key_token(event))
            return True
        if watched is self.sequence_edit:
            if event.type() == QEvent.KeyPress and self.recording:
                if event.key() == Qt.Key_Escape:
                    self.record_btn.setChecked(False)
                    self.toggle_recording()
                    return True
                if event.key() == Qt.Key_Backspace:
                    separator = "+" if self.mode_combo.currentIndex() == 2 else ","
                    tokens = [part.strip() for part in self.sequence_edit.toPlainText().split(separator) if part.strip()]
                    if tokens:
                        tokens.pop()
                        self.sequence_edit.setPlainText(separator.join(tokens))
                    return True
                token = self.parent._qt_key_token(event)
                self._capture_token(token)
                return True
            if event.type() == QEvent.MouseButtonPress and self.recording:
                buttons = {
                    Qt.MouseButton.LeftButton: "LMB",
                    Qt.MouseButton.RightButton: "RMB",
                    Qt.MouseButton.MiddleButton: "MMB",
                    Qt.MouseButton.XButton1: "X1",
                    Qt.MouseButton.XButton2: "X2",
                }
                self._capture_token(buttons.get(event.button()))
                return True
            if event.type() == QEvent.ContextMenu and self.recording:
                return True
        return super().eventFilter(watched, event)

# ============================================================
# CLICKER THREAD WORKER
# ============================================================
class ClickerWorker(QThread):
    status_signal = Signal(str, str)
    limit_reached = Signal()
    duration_limit_reached = Signal()
    scenario_finished = Signal()

    def __init__(self, parent_clicker):
        super().__init__()
        self.c = parent_clicker
        self.stop_event = threading.Event()
        self.last_status_time = 0.0
        self.pending_clicks = 0
        self.last_click_flush = time.monotonic() - 0.1
        self.click_limit_enabled = self.c.click_limit_checkbox.isChecked()
        self.click_limit = int(self.c.click_limit_edit.text() or "0")
        self.run_click_count = 0
        self.scenario_playback = (
            self.c.current_mode == self.c.MODE_SCENARIO
        )
        self.scenario_run_limit_enabled = (
            self.scenario_playback
            and self.c.scenario_run_limit_checkbox.isChecked()
        )
        self.scenario_run_limit = int(
            self.c.scenario_run_limit_edit.text() or "0"
        )
        self.duration_limit_enabled = (
            self.c.duration_limit_checkbox.isChecked()
        )
        self.duration_limit_seconds = (
            int(self.c.duration_limit_edit.text() or "0") * 60
        )
        self.scenario_runs_completed = 0
        self.run_started_at = time.monotonic()

    def duration_limit_expired(self):
        return (
            self.duration_limit_enabled
            and time.monotonic() - self.run_started_at
            >= self.duration_limit_seconds
        )

    def remaining_duration(self):
        if not self.duration_limit_enabled:
            return None
        return max(
            0.0,
            self.duration_limit_seconds
            - (time.monotonic() - self.run_started_at),
        )

    def record_click(self):
        self.pending_clicks += 1
        self.run_click_count += 1
        now = time.monotonic()
        if (
            self.pending_clicks >= 32
            or now - self.last_click_flush >= 0.1
            or (
                self.click_limit_enabled
                and self.run_click_count >= self.click_limit
            )
        ):
            self.flush_click_count()
        if (
            self.click_limit_enabled
            and self.run_click_count >= self.click_limit
        ):
            self.stop_event.set()
            self.limit_reached.emit()
            return True
        return False

    def flush_click_count(self):
        if self.pending_clicks:
            self.c._record_click(self.pending_clicks)
            self.pending_clicks = 0
            self.last_click_flush = time.monotonic()

    def report_status(self, text, color):
        now = time.monotonic()
        if now - self.last_status_time >= 0.1:
            self.last_status_time = now
            self.status_signal.emit(text, color)

    def run(self):
        held = False
        random_enabled = self.c.random_interval.isChecked()
        min_interval = self.c.min_interval
        max_interval = self.c.max_interval
        pressed_status = self.c.tr(
            'status_pressed',
            self.c.get_binding_name(self.c.click_key, self.c.click_key_type)
        )
        try:
            while not self.stop_event.is_set():
                with self.c.click_lock:
                    if not self.c.clicking:
                        break
                if self.duration_limit_expired():
                    break

                mode = self.c.current_mode

                if mode == self.c.MODE_HOLD:
                    self.c.press_only(self.c.click_key, self.c.click_key_type)
                    if self.record_click():
                        return
                    held = True
                    self.report_status(
                        self.c.tr('status_held', self.c.get_binding_name(self.c.click_key, self.c.click_key_type)),
                        "red"
                    )
                    if not self.interruptible_sleep(self.c.hold_duration):
                        break
                    self.c.release_only(self.c.click_key, self.c.click_key_type)
                    held = False
                    self.report_status(self.c.tr('status_hold_released'), "red")

                elif mode == self.c.MODE_SEQUENCE:
                    for item in list(self.c.sequence_keys):
                        if (
                            self.stop_event.is_set()
                            or self.duration_limit_expired()
                        ):
                            return
                        with self.c.click_lock:
                            if not self.c.clicking:
                                return
                        self.c._press_and_release_item(item)
                        if self.record_click():
                            return
                        self.report_status(self.c.tr('status_pressed', self.c._item_to_string(item)), "red")
                        if not self.interruptible_sleep(self.c.sequence_interval):
                            return

                elif mode == self.c.MODE_COMBO:
                    combo = list(self.c.sequence_keys)
                    if combo:
                        self.c._press_combo(combo)
                        if self.record_click():
                            return
                        self.report_status(
                            self.c.tr('status_combo', '+'.join(self.c._item_to_string(x) for x in combo)),
                            "red"
                        )
                elif mode == self.c.MODE_COORDINATES:
                    actions = self.c.coordinate_click_positions
                    for index, action in enumerate(actions, start=1):
                        if (
                            self.stop_event.is_set()
                            or self.duration_limit_expired()
                        ):
                            return
                        with self.c.click_lock:
                            if not self.c.clicking:
                                return
                        if action["type"] == "swipe":
                            try:
                                if not self.perform_coordinate_swipe(action):
                                    return
                            except Exception as error:
                                logging.getLogger(__name__).exception(
                                    "Coordinate swipe failed"
                                )
                                self.status_signal.emit(
                                    self.c.tr(
                                        "status_coordinate_error",
                                        error,
                                    ),
                                    "red",
                                )
                                return
                            if self.record_click():
                                return
                            self.report_status(
                                self.c.tr(
                                    "status_coordinate_swipe",
                                    index,
                                    len(actions),
                                ),
                                "red",
                            )
                            if not self.c.coordinate_smooth_enabled:
                                interval = (
                                    random.uniform(
                                        min_interval,
                                        max_interval,
                                    )
                                    if self.c.coordinate_random_click_interval
                                    else min_interval
                                )
                                if not self.interruptible_sleep(interval):
                                    return
                            continue

                        x, y = action["position"]
                        try:
                            if self.c.coordinate_smooth_enabled:
                                move_duration = (
                                    random.uniform(
                                        self.c.coordinate_move_duration,
                                        self.c.coordinate_move_duration_max,
                                    )
                                    if self.c.coordinate_random_move_duration
                                    else self.c.coordinate_move_duration
                                )
                                if not self.move_cursor_smoothly(
                                    x,
                                    y,
                                    move_duration,
                                ):
                                    return
                            self.c.click_at_position(x, y)
                            if self.record_click():
                                return
                        except Exception as error:
                            logging.getLogger(__name__).exception(
                                "Coordinate click failed"
                            )
                            self.status_signal.emit(
                                self.c.tr(
                                    "status_coordinate_error",
                                    error,
                                ),
                                "red",
                            )
                            return
                        self.report_status(
                            self.c.tr(
                                'status_coordinate_click',
                                index,
                                len(actions),
                            ),
                            "red",
                        )
                        if not self.c.coordinate_smooth_enabled:
                            interval = (
                                random.uniform(
                                    min_interval,
                                    max_interval,
                                )
                                if self.c.coordinate_random_click_interval
                                else min_interval
                            )
                            if not self.interruptible_sleep(interval):
                                return
                    cycle_interval = (
                        random.uniform(
                            self.c.coordinate_cycle_interval,
                            self.c.coordinate_cycle_interval_max,
                        )
                        if self.c.coordinate_random_cycle_interval
                        else self.c.coordinate_cycle_interval
                    )
                    if not self.interruptible_sleep(cycle_interval):
                        return
                    continue
                elif mode == self.c.MODE_SCENARIO:
                    if not self.perform_scenario():
                        break
                    self.scenario_runs_completed += 1
                    if (
                        self.scenario_run_limit_enabled
                        and self.scenario_runs_completed
                        >= self.scenario_run_limit
                    ) or self.duration_limit_expired():
                        break
                    interval = (
                        random.uniform(min_interval, max_interval)
                        if random_enabled
                        else min_interval
                    )
                    remaining = self.remaining_duration()
                    if remaining is not None:
                        if remaining <= 0:
                            break
                        interval = min(interval, remaining)
                    if not self.interruptible_sleep(interval):
                        break
                    if self.duration_limit_expired():
                        break
                    continue
                else:  # Мгновенное нажатие
                    self.c.press_and_release(self.c.click_key, self.c.click_key_type)
                    if self.record_click():
                        return
                    self.report_status(pressed_status, "red")

                if random_enabled:
                    interval = random.uniform(
                        min_interval, max_interval
                    )
                else:
                    interval = min_interval
                if not self.interruptible_sleep(interval):
                    break
        finally:
            self.flush_click_count()
            if held:
                self.c.release_only(self.c.click_key, self.c.click_key_type)
            self.c.release_all()
            if self.scenario_playback:
                self.scenario_finished.emit()
            if self.duration_limit_expired():
                self.duration_limit_reached.emit()

    def perform_scenario(self):
        pressed_keys = []
        pressed_buttons = []
        completed = False
        with self.c._sim_lock:
            self.c._simulating = True
        try:
            for index, action in enumerate(self.c.scenario_actions, start=1):
                if self.duration_limit_expired():
                    return False
                if not self.interruptible_sleep(action["delay"]):
                    return False
                if self.duration_limit_expired():
                    return False
                action_type = action["type"]
                if action_type in ("key_press", "key_release"):
                    key = self.c.parse_key_token(action["key"])
                    if key is None or isinstance(key, mouse.Button):
                        raise ValueError(
                            self.c.tr("scenario_invalid_key")
                        )
                    if action_type == "key_press":
                        self.c.keyboard_controller.press(key)
                        if key not in pressed_keys:
                            pressed_keys.append(key)
                    else:
                        self.c.keyboard_controller.release(key)
                        if key in pressed_keys:
                            pressed_keys.remove(key)
                elif action_type in ("mouse_press", "mouse_release"):
                    button = self.c.parse_key_token(action["button"])
                    if not isinstance(button, mouse.Button):
                        raise ValueError(
                            self.c.tr("scenario_invalid_button")
                        )
                    self.c.mouse_controller.position = (
                        action["x"],
                        action["y"],
                    )
                    if action_type == "mouse_press":
                        self.c.mouse_controller.press(button)
                        if button not in pressed_buttons:
                            pressed_buttons.append(button)
                    else:
                        self.c.mouse_controller.release(button)
                        if button in pressed_buttons:
                            pressed_buttons.remove(button)
                elif action_type == "mouse_move":
                    self.c.mouse_controller.position = (
                        action["x"],
                        action["y"],
                    )
                elif action_type == "scroll":
                    self.c.mouse_controller.position = (
                        action["x"],
                        action["y"],
                    )
                    self.c.mouse_controller.scroll(
                        action["dx"],
                        action["dy"],
                    )
                self.report_status(
                    self.c.tr(
                        "scenario_playback_status",
                        index,
                        len(self.c.scenario_actions),
                    ),
                    "red",
                )
            completed = not self.stop_event.is_set()
        except Exception as error:
            logging.getLogger(__name__).exception(
                "Scenario playback failed"
            )
            self.status_signal.emit(
                self.c.tr("scenario_playback_error", error),
                "red",
            )
            return False
        finally:
            for key in reversed(pressed_keys):
                try:
                    self.c.keyboard_controller.release(key)
                except Exception:
                    logging.getLogger(__name__).exception(
                        "Could not release a scenario key"
                    )
            for button in reversed(pressed_buttons):
                try:
                    self.c.mouse_controller.release(button)
                except Exception:
                    logging.getLogger(__name__).exception(
                        "Could not release a scenario mouse button"
                    )
            with self.c._sim_lock:
                self.c._simulating = False
        return completed

    def perform_coordinate_swipe(self, action):
        points = action["points"]
        if (
            not points
            or self.stop_event.is_set()
            or self.duration_limit_expired()
        ):
            return False
        button = action["button"]
        self.c.mouse_controller.position = points[0]
        pressed = False
        with self.c._sim_lock:
            self.c._simulating = True
        try:
            self.c.mouse_controller.press(button)
            pressed = True
            if not self.interruptible_sleep(0.01):
                return False
            if len(points) < 2:
                return True

            segment_lengths = [
                math.dist(start, end)
                for start, end in zip(points, points[1:])
            ]
            total_length = sum(segment_lengths)
            duration = (
                random.uniform(
                    self.c.coordinate_move_duration,
                    self.c.coordinate_move_duration_max,
                )
                if self.c.coordinate_random_move_duration
                else self.c.coordinate_move_duration
            )
            if duration <= 0 or total_length <= 0:
                for point in points[1:]:
                    if (
                        self.stop_event.is_set()
                        or self.duration_limit_expired()
                    ):
                        return False
                    self.c.mouse_controller.position = point
                return not self.stop_event.is_set()

            started_at = time.perf_counter()
            travelled = 0.0
            segment_index = 0
            while True:
                if (
                    self.stop_event.is_set()
                    or self.duration_limit_expired()
                ):
                    return False
                elapsed = time.perf_counter() - started_at
                progress = min(1.0, elapsed / duration)
                target_distance = total_length * progress
                while (
                    segment_index < len(segment_lengths) - 1
                    and travelled + segment_lengths[segment_index]
                    < target_distance
                ):
                    travelled += segment_lengths[segment_index]
                    segment_index += 1
                segment_length = segment_lengths[segment_index]
                segment_progress = (
                    1.0
                    if segment_length <= 0
                    else min(
                        1.0,
                        max(
                            0.0,
                            (target_distance - travelled) / segment_length,
                        ),
                    )
                )
                position = interpolate_cursor_position(
                    points[segment_index],
                    points[segment_index + 1],
                    segment_progress,
                )
                self.c.mouse_controller.position = position
                if progress >= 1.0:
                    return not self.duration_limit_expired()
                if not self.interruptible_sleep(
                    min(1 / 60, max(0.0, duration - elapsed))
                ):
                    return False
        finally:
            try:
                if pressed:
                    self.c.mouse_controller.release(button)
            finally:
                with self.c._sim_lock:
                    self.c._simulating = False

    def interruptible_sleep(self, duration):
        with self.c.click_lock:
            if not self.c.clicking or self.stop_event.is_set():
                return False
        duration = max(0.0, duration)
        remaining = self.remaining_duration()
        if remaining is not None:
            if remaining <= 0:
                return False
            duration = min(duration, remaining)
        if duration < 0.01:
            deadline = time.perf_counter() + duration
            while time.perf_counter() < deadline:
                if self.stop_event.is_set() or self.duration_limit_expired():
                    return False
                time.sleep(0)
            return (
                not self.stop_event.is_set()
                and not self.duration_limit_expired()
            )
        return (
            not self.stop_event.wait(duration)
            and not self.duration_limit_expired()
        )

    def move_cursor_smoothly(self, x, y, duration):
        destination = (int(x), int(y))
        if duration <= 0:
            if self.stop_event.is_set() or self.duration_limit_expired():
                return False
            self.c.mouse_controller.position = destination
            return True

        start = self.c.mouse_controller.position
        started_at = time.perf_counter()
        with self.c._sim_lock:
            self.c._simulating = True
        try:
            while True:
                elapsed = time.perf_counter() - started_at
                progress = min(1.0, elapsed / duration)
                self.c.mouse_controller.position = interpolate_cursor_position(
                    start,
                    destination,
                    progress,
                )
                if progress >= 1.0:
                    return not self.duration_limit_expired()
                if not self.interruptible_sleep(
                    min(1 / 60, duration - elapsed)
                ):
                    return False
        finally:
            with self.c._sim_lock:
                self.c._simulating = False

    def stop(self):
        self.stop_event.set()

class CheckmarkCheckBox(QCheckBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.isChecked():
            return

        option = QStyleOptionButton()
        self.initStyleOption(option)
        indicator = self.style().subElementRect(
            QStyle.SubElement.SE_CheckBoxIndicator,
            option,
            self,
        )
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(
            QPen(
                QColor("#ffffff"),
                2.2,
                Qt.SolidLine,
                Qt.RoundCap,
                Qt.RoundJoin,
            )
        )
        painter.drawLine(
            indicator.left() + indicator.width() * 0.25,
            indicator.top() + indicator.height() * 0.52,
            indicator.left() + indicator.width() * 0.43,
            indicator.top() + indicator.height() * 0.70,
        )
        painter.drawLine(
            indicator.left() + indicator.width() * 0.43,
            indicator.top() + indicator.height() * 0.70,
            indicator.left() + indicator.width() * 0.77,
            indicator.top() + indicator.height() * 0.32,
        )


# ============================================================
# PROFILE SELECTION DIALOG
# ============================================================
class ProfileSelectionDialog(QDialog):
    def __init__(
        self,
        profiles,
        translate,
        parent=None,
        title_key='profiles_export',
        description=None,
        profile_details=None,
    ):
        super().__init__(parent)
        self.profiles = profiles
        self.profile_checkboxes = []
        self.setWindowTitle(translate(title_key))
        self.setMinimumWidth(500 if profile_details else 360)

        layout = QVBoxLayout(self)
        if description:
            description_label = QLabel(description)
            description_label.setObjectName("section")
            description_label.setWordWrap(True)
            layout.addWidget(description_label)

        self.select_all_checkbox = CheckmarkCheckBox(
            translate('profiles_select_all')
        )
        self.select_all_checkbox.setChecked(True)
        self.select_all_checkbox.clicked.connect(
            self._set_all_profiles_selected
        )
        layout.addWidget(self.select_all_checkbox)

        self.profile_scroll = QScrollArea()
        self.profile_scroll.setWidgetResizable(True)
        self.profile_scroll.setFrameShape(QFrame.NoFrame)
        profile_list = QWidget()
        profile_list_layout = QVBoxLayout(profile_list)
        profile_list_layout.setContentsMargins(0, 0, 0, 0)
        for profile in profiles:
            checkbox = CheckmarkCheckBox(
                f'{profile.get("icon", "✨")} {profile["name"]}'
            )
            checkbox.setChecked(True)
            checkbox.stateChanged.connect(self._update_selection_state)
            self.profile_checkboxes.append(checkbox)
            if profile_details:
                profile_row = QWidget()
                profile_row_layout = QVBoxLayout(profile_row)
                profile_row_layout.setContentsMargins(0, 3, 0, 6)
                details_label = QLabel(profile_details(profile))
                details_label.setWordWrap(True)
                details_label.setStyleSheet(
                    "color: #91a4ba; font-size: 11px; padding-left: 29px;"
                )
                profile_row_layout.addWidget(checkbox)
                profile_row_layout.addWidget(details_label)
                profile_list_layout.addWidget(profile_row)
            else:
                profile_list_layout.addWidget(checkbox)
        profile_list_layout.addStretch()
        self.profile_scroll.setWidget(profile_list)
        self.profile_scroll.setMinimumHeight(180)
        layout.addWidget(self.profile_scroll, 1)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.Ok).setText(
            translate('dialog_ok')
        )
        self.buttons.button(QDialogButtonBox.Cancel).setText(
            translate('dialog_cancel')
        )
        layout.addWidget(self.buttons)

    def _set_all_profiles_selected(self, checked):
        for checkbox in self.profile_checkboxes:
            checkbox.setChecked(checked)
        self._update_selection_state()

    def _update_selection_state(self, *_):
        selected = any(
            checkbox.isChecked() for checkbox in self.profile_checkboxes
        )
        self.select_all_checkbox.setChecked(
            bool(self.profile_checkboxes)
            and all(
                checkbox.isChecked()
                for checkbox in self.profile_checkboxes
            )
        )
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(selected)

    def selected_profiles(self):
        return [
            profile
            for profile, checkbox in zip(
                self.profiles,
                self.profile_checkboxes,
            )
            if checkbox.isChecked()
        ]


class ProfileManagementDialog(QDialog):
    def __init__(self, profiles, translate, parent=None):
        super().__init__(parent)
        self.profiles = profiles
        self.profile_checkboxes = []
        self.translate = translate
        self.setWindowTitle(translate('profiles_manage'))
        self.setMinimumSize(420, 400)

        layout = QVBoxLayout(self)
        selection_layout = QHBoxLayout()
        select_all_button = QPushButton(
            translate('profiles_manage_select_all')
        )
        select_all_button.clicked.connect(
            lambda: self._set_all_selected(True)
        )
        deselect_all_button = QPushButton(
            translate('profiles_manage_deselect_all')
        )
        deselect_all_button.clicked.connect(
            lambda: self._set_all_selected(False)
        )
        selection_layout.addWidget(select_all_button)
        selection_layout.addWidget(deselect_all_button)
        layout.addLayout(selection_layout)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            translate('profiles_search_placeholder')
        )
        self.search_edit.textChanged.connect(self._filter_profiles)
        layout.addWidget(self.search_edit)

        self.empty_label = QLabel(translate('profiles_manage_no_profiles'))
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet("color: #91a4ba; padding: 12px;")
        layout.addWidget(self.empty_label)

        self.search_empty_label = QLabel(
            translate('profiles_search_empty')
        )
        self.search_empty_label.setAlignment(Qt.AlignCenter)
        self.search_empty_label.setStyleSheet(
            "color: #91a4ba; padding: 12px;"
        )
        self.search_empty_label.hide()
        layout.addWidget(self.search_empty_label)

        profile_scroll = QScrollArea()
        profile_scroll.setWidgetResizable(True)
        profile_scroll.setFrameShape(QFrame.NoFrame)
        profile_list = QWidget()
        profile_list_layout = QVBoxLayout(profile_list)
        profile_list_layout.setContentsMargins(0, 0, 0, 0)
        for profile in profiles:
            checkbox = CheckmarkCheckBox(
                f'{profile.get("icon", "✨")} {profile.get("name", "")}'
            )
            checkbox.stateChanged.connect(self._update_selection_state)
            self.profile_checkboxes.append(checkbox)
            profile_list_layout.addWidget(checkbox)
        profile_list_layout.addStretch()
        profile_scroll.setWidget(profile_list)
        profile_scroll.setMinimumHeight(180)
        layout.addWidget(profile_scroll, 1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.delete_button = self.buttons.addButton(
            translate('profiles_manage_delete_selected').format(0),
            QDialogButtonBox.DestructiveRole,
        )
        self.delete_button.clicked.connect(self._confirm_delete)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.Cancel).setText(
            translate('dialog_cancel')
        )
        layout.addWidget(self.buttons)

        self._update_selection_state()

    def _set_all_selected(self, selected):
        for checkbox in self.profile_checkboxes:
            checkbox.setChecked(selected)
        self._update_selection_state()

    def _filter_profiles(self, query):
        normalized_query = query.strip().casefold()
        visible_count = 0
        for profile, checkbox in zip(
            self.profiles,
            self.profile_checkboxes,
        ):
            matches = normalized_query in profile.get("name", "").casefold()
            checkbox.setVisible(matches)
            visible_count += int(matches)
        self.empty_label.setVisible(not self.profiles)
        self.search_empty_label.setVisible(
            bool(normalized_query) and visible_count == 0
        )

    def _update_selection_state(self, *_):
        selected_count = sum(
            checkbox.isChecked() for checkbox in self.profile_checkboxes
        )
        self.delete_button.setText(
            self.translate('profiles_manage_delete_selected').format(
                selected_count
            )
        )
        self.delete_button.setEnabled(selected_count > 0)
        self.empty_label.setVisible(not self.profiles)

    def _confirm_delete(self):
        selected_count = sum(
            checkbox.isChecked() for checkbox in self.profile_checkboxes
        )
        if not selected_count:
            return
        confirmation = QMessageBox.question(
            self,
            self.translate('profiles_manage'),
            self.translate('profiles_manage_confirm_delete').format(
                selected_count
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirmation == QMessageBox.Yes:
            self.accept()

    def selected_profiles(self):
        return [
            profile
            for profile, checkbox in zip(
                self.profiles,
                self.profile_checkboxes,
            )
            if checkbox.isChecked()
        ]


# ============================================================
# PROFILE WIDGET (with menu)
# ============================================================
class ProfileWidget(QFrame):
    def __init__(self, profile, apply_callback, edit_callback, delete_callback, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.setMinimumHeight(96)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.setCursor(Qt.PointingHandCursor)
        self.profile = profile
        self.apply_callback = apply_callback
        self.edit_callback = edit_callback
        self.delete_callback = delete_callback
        self.parent = parent

        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 12, 15, 12)
        layout.setSpacing(13)

        icon = QLabel(profile.get("icon", "✨"))
        icon.setStyleSheet(
            'font-family: "Segoe UI Emoji"; font-size: 48pt;'
        )
        icon.setFixedSize(72, 72)
        icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon)

        text = QVBoxLayout()
        text.setSpacing(3)
        name = QLabel(profile["name"])
        name.setWordWrap(True)
        name.setStyleSheet("font-size: 15px; font-weight: 700;")

        mode = QLabel(f'<span style="color:#75aaff;">{self.parent.tr("mode")}:</span> {profile["mode"]}')
        minimum_interval = profile["min"]
        maximum_interval = profile["max"]
        if (
            not profile.get("random", True)
            or float(minimum_interval) == float(maximum_interval)
        ):
            interval_text = (
                f'{self.parent.tr("interval")}: '
                f'{format_interval_value(minimum_interval)} sec.'
            )
        else:
            interval_text = (
                f'{self.parent.tr("interval")}: '
                f'{format_interval_value(minimum_interval)} — '
                f'{format_interval_value(maximum_interval)} sec.'
            )
        interval = QLabel(interval_text)
        mode.setWordWrap(True)
        interval.setWordWrap(True)
        for label in (name, mode, interval):
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        mode.setStyleSheet("color:#91a4ba; font-size:12px;")
        interval.setStyleSheet("color:#91a4ba; font-size:12px;")

        text.addWidget(name)
        text.addWidget(mode)
        text.addWidget(interval)
        layout.addLayout(text, 1)

        mode_value = profile.get("mode")
        combo_modes = {
            self.parent.MODE_COMBO,
            self.parent.tr('mode_combo'),
            "Instant combo",
        }
        sequence_modes = {
            self.parent.MODE_SEQUENCE,
            self.parent.tr('mode_sequence'),
            "Sequence press",
        }
        coordinate_modes = {
            self.parent.MODE_COORDINATES,
            self.parent.tr('mode_coordinates'),
            "Coordinate clicks",
        }
        scenario_modes = {
            self.parent.MODE_SCENARIO,
            self.parent.tr('mode_scenario'),
            "Recorded scenario",
        }
        sequence = profile.get("sequence", "").strip()
        if mode_value in scenario_modes:
            actions = profile.get("scenario", [])
            key_text = (
                self.parent.tr("scenario_record_finished", len(actions))
                if actions
                else self.parent.tr("scenario_actions_empty")
            )
            key_tooltip = ""
        elif mode_value in coordinate_modes:
            points = profile.get("coordinates", [])
            key_text = (
                self.parent.tr(
                    'coordinate_profile_summary',
                    len(points),
                )
                if points
                else self.parent.tr('coordinate_points_empty')
            )
            key_tooltip = ""
        elif mode_value in combo_modes | sequence_modes:
            is_combo = mode_value in combo_modes
            if not sequence:
                key_text = self.parent.tr('profile_keys_empty')
                key_tooltip = ""
            else:
                if is_combo or "," in sequence:
                    separator = "+" if is_combo else ","
                    keys = [
                        part.strip()
                        for part in sequence.split(separator)
                        if part.strip()
                    ]
                elif sequence.upper() in {
                    "SPACE", "ПРОБЕЛ", "ENTER", "ESC", "TAB", "SHIFT",
                    "CTRL", "CONTROL", "ALT", "LEFT", "RIGHT", "UP", "DOWN",
                    "LMB", "RMB", "MMB", "X1", "X2",
                }:
                    keys = [sequence]
                else:
                    keys = list(sequence)
                visible_key_count = 2 if is_combo else 3
                key_text = ("+" if is_combo else ", ").join(
                    keys[:visible_key_count]
                )
                if len(keys) > visible_key_count:
                    key_text += " …"
                key_tooltip = sequence
        else:
            key_text = self.parent.display_key_token(profile["key"])
            key_tooltip = ""
        key = QLabel(key_text)
        key.setToolTip(key_tooltip)
        key.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        key.setStyleSheet("QLabel { background: #07111d; border: 1px solid #2b435d; border-radius: 7px; padding: 7px 10px; color: #b9c9dc; font-size: 11px; }")
        layout.addWidget(key)

        # Кнопка меню (карандаш)
        menu_btn = QPushButton("✏️")
        menu_btn.setObjectName("menu-btn")
        menu_btn.setFixedSize(36, 36)
        menu_btn.setStyleSheet("padding: 0px;")
        menu_btn.setFont(QFont("Segoe UI Emoji", 20))
        menu_btn.setToolTip(self.parent.tr("edit_profile"))
        menu_btn.clicked.connect(self.show_menu)
        layout.addWidget(menu_btn)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.apply_callback(self.profile)

    def show_menu(self):
        menu = QMenu(self)
        edit_action = QAction(self.parent.tr('edit_profile'), self)
        delete_action = QAction(self.parent.tr('delete_profile'), self)
        edit_action.triggered.connect(lambda: self.edit_callback(self.profile))
        delete_action.triggered.connect(lambda: self.delete_callback(self.profile))
        menu.addAction(edit_action)
        menu.addAction(delete_action)
        menu.exec(QCursor.pos())

# ============================================================
# MAIN WINDOW
# ============================================================
class MainWindow(QMainWindow):
    MODE_HOLD = "Зажатие клавиши"
    MODE_SEQUENCE = "Последовательное нажатие"
    MODE_INSTANT = "Мгновенное нажатие"
    MODE_COMBO = "Мгновенная комбинация"
    MODE_COORDINATES = "Клики по координатам"
    MODE_SCENARIO = "Записанный сценарий"

    # Сигналы для потокобезопасного обновления GUI
    hotkey_label_signal = Signal(str)
    start_label_signal = Signal(str)
    stop_label_signal = Signal(str)
    emergency_stop_key_signal = Signal(str)
    status_signal = Signal(str, str)
    update_language_signal = Signal()
    start_request_signal = Signal()
    stop_request_signal = Signal()
    sequence_input_signal = Signal(str)
    sequence_recording_signal = Signal(bool)
    settings_save_signal = Signal()
    scenario_capture_signal = Signal(str, object)

    def __init__(self):
        super().__init__()
        icon_path = ICON_FILE if ICON_FILE.exists() else FALLBACK_ICON_FILE
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setWindowTitle(APP_NAME)
        self.resize(1200, 780)
        self.setMinimumSize(760, 600)
        self._responsive_font_size = 13

        # Переменные логики автокликера
        self.clicking = False
        self._click_count = 0
        self._click_stats_lock = threading.Lock()
        self._click_rate_samples = deque()
        self._click_run_started_at = None
        self._average_clicks_per_second = 0.0
        self._status_text = ""
        self.profile_dialog = None
        self.hotkeys_enabled = True   # по умолчанию включены
        self.click_lock = threading.Lock()
        self.hotkey_lock = threading.RLock()  # ре-энтерабельная блокировка для pressed_keys и захвата биндов
        self.listeners_started = False

        # --- Защита от самонажатия (shimming) ---
        self._simulating = False
        self._sim_lock = threading.Lock()

        self.waiting_for_click_key = False
        self.waiting_for_sequence_input = False
        self.sequence_input_active = False
        self.sequence_recording_keys = []
        self.sequence_recording_down = set()
        self.coordinate_recording_active = False
        self.coordinate_points = []
        self.scenario_capture_lock = threading.RLock()
        self.scenario_record_state = "idle"
        self.scenario_record_dialog = None
        self.scenario_record_actions = []
        self.scenario_record_last_at = 0.0
        self.scenario_last_mouse_move_at = 0.0
        self.scenario_last_mouse_position = None
        self.scenario_actions = []
        self.standalone_scenario_actions = []
        self._mode_tutorial_dialog = None
        self._mode_tutorial_highlights = []
        self._tutorial_offer_version = None
        self._tutorial_offer_dismissed = False
        self._tutorial_prompt_pending = True
        self.coordinate_click_positions = []
        self.coordinate_smooth_enabled = False
        self.coordinate_move_duration = 0.3
        self.coordinate_move_duration_max = 0.5
        self.coordinate_random_move_duration = False
        self.coordinate_cycle_interval = 0.5
        self.coordinate_cycle_interval_max = 1.0
        self.coordinate_random_cycle_interval = False
        self.coordinate_random_click_interval = False
        self.waiting_for_start_key = False
        self.waiting_for_stop_key = False

        # ---- ИСПРАВЛЕНИЕ: храним множества строк, а не объектов ----
        self.start_hotkey = {"F6"}
        self.stop_hotkey = {"F7"}
        self.emergency_stop_key = "ESC"
        self.waiting_for_emergency_key = False
        self.pressed_keys = set()          # строки
        self.binding_capture_keys = set()  # строки (во время захвата)
        self.sequence_capture_keys = []
        self.hotkey_fired = set()

        self.click_key = keyboard.Key.space
        self.click_key_type = "keyboard"

        self.keyboard_controller = keyboard.Controller()
        self.mouse_controller = mouse.Controller()

        self.min_interval = 0.5
        self.max_interval = 1.0
        self.hold_duration = 1.0
        self.sequence_keys = [keyboard.Key.space, keyboard.Key.enter]
        self.sequence_interval = 0.2
        self.current_mode = self.MODE_INSTANT

        self.language = 'ru'
        self.theme = "dark"
        self.init_translations()
        self.update_check_signals = UpdateCheckSignals()
        self.update_check_started = False
        self.manual_update_check_pending = False

        self.profiles = self.load_profiles()
        self.build_ui()
        self.load_settings()
        self.standalone_scenario_actions = self.load_standalone_scenario()
        if self.current_mode == self.MODE_SCENARIO:
            self.scenario_actions = deepcopy(
                self.standalone_scenario_actions
            )
        self.update_language()
        QApplication.instance().installEventFilter(self)

        self.keyboard_listener = None
        self.mouse_listener = None
        self.worker = None

        # Подключаем сигналы к слотам
        self.hotkey_label_signal.connect(self._set_hotkey_label)
        self.start_label_signal.connect(self._set_start_label)
        self.stop_label_signal.connect(self._set_stop_label)
        self.emergency_stop_key_signal.connect(
            self._set_emergency_stop_key_label
        )
        self.status_signal.connect(self._set_status)
        self.update_check_signals.check_finished.connect(
            self.handle_update_check_finished
        )
        self.update_check_signals.check_failed.connect(
            self.log_update_check_failure
        )
        self.update_language_signal.connect(self.update_language)
        self.start_request_signal.connect(self.start_clicker)
        self.stop_request_signal.connect(self.stop_clicker)
        self.sequence_input_signal.connect(self._append_sequence_input)
        self.sequence_recording_signal.connect(self._set_sequence_recording)
        self.scenario_capture_signal.connect(
            self._handle_scenario_capture_update
        )
        self.settings_save_signal.connect(self.save_settings)
        self._click_stats_timer = QTimer(self)
        self._click_stats_timer.setInterval(250)
        self._click_stats_timer.timeout.connect(self._refresh_click_stats)
        self._click_stats_timer.start()

        # Запускаем слушатели сразу
        self._ensure_listeners_started()

        # Обновляем состояние кнопок управления горячими клавишами
        self.update_hotkey_ui()
        QTimer.singleShot(1000, self.check_for_updates)
        if self._tutorial_prompt_pending:
            QTimer.singleShot(1500, self._offer_tutorial_on_first_launch)

    def check_for_updates(self, manual=False):
        if manual:
            self.manual_update_check_pending = True
        if self.update_check_started:
            return
        self.update_check_started = True
        signals = self.update_check_signals

        def check():
            try:
                request = urllib.request.Request(
                    VERSION_MANIFEST_URL,
                    headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"},
                )
                with urllib.request.urlopen(request, timeout=8) as response:
                    manifest = json.loads(response.read().decode("utf-8"))
                update = parse_update_manifest(manifest, APP_VERSION)
                if (
                    update is None
                    and version_key(APP_VERSION)
                    > version_key(manifest["latest_version"])
                ):
                    update = {
                        "local_version_is_newer": True,
                        "latest_version": manifest["latest_version"],
                    }
                signals.check_finished.emit(update)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
                signals.check_failed.emit(str(error))

        threading.Thread(
            target=check,
            name="update-check",
            daemon=True,
        ).start()

    @Slot(object)
    def handle_update_check_finished(self, update):
        self.update_check_started = False
        manual_check = self.manual_update_check_pending
        self.manual_update_check_pending = False
        if update and update.get("local_version_is_newer"):
            if manual_check:
                QMessageBox.information(
                    self,
                    self.tr("update_check_title"),
                    self.tr("update_custom_version").format(
                        APP_VERSION,
                        update["latest_version"],
                    ),
                )
            return
        if update:
            self.show_update_dialog(update)
        elif manual_check:
            QMessageBox.information(
                self,
                self.tr("update_check_title"),
                self.tr("update_current_version").format(APP_VERSION),
            )

    @Slot(dict)
    def show_update_dialog(self, update):
        dialog = UpdateDialog(update, self.language, self)
        self.apply_theme()
        if dialog.exec() == QDialog.Accepted:
            if not QDesktopServices.openUrl(QUrl(update["download_url"])):
                QMessageBox.warning(
                    self,
                    self.tr("update_error_title"),
                    self.tr("update_open_error"),
                )

    @Slot()
    def open_bug_report_form(self):
        if not QDesktopServices.openUrl(QUrl(BUG_REPORT_URL)):
            QMessageBox.warning(
                self,
                self.tr("update_error_title"),
                self.tr("bug_report_open_error"),
            )

    @Slot(str)
    def log_update_check_failure(self, error):
        self.update_check_started = False
        logging.getLogger(__name__).warning("Could not check for updates: %s", error)
        if self.manual_update_check_pending:
            self.manual_update_check_pending = False
            QMessageBox.warning(
                self,
                self.tr("update_error_title"),
                self.tr("update_check_error"),
            )

    def _ensure_listeners_started(self):
        if self.listeners_started:
            return
        self.keyboard_listener = keyboard.Listener(
            on_press=self.on_key_press,
            on_release=self.on_key_release
        )
        self.keyboard_listener.start()
        self.mouse_listener = mouse.Listener(
            on_move=self.on_mouse_move,
            on_click=self.on_mouse_click,
            on_scroll=self.on_mouse_scroll,
        )
        self.mouse_listener.start()
        self.listeners_started = True

    def arm_scenario_recording(self, dialog):
        is_main_mode = dialog is self
        if is_main_mode:
            if self.current_mode != self.MODE_SCENARIO:
                return
            current_actions = self.scenario_actions
            binding_recording = False
        else:
            if dialog.mode_combo.currentText() != self.tr("mode_scenario"):
                return
            current_actions = dialog.scenario_actions
            binding_recording = dialog.binding_recording
        if not self.hotkeys_enabled:
            QMessageBox.warning(
                dialog,
                self.tr("scenario_editor_title"),
                self.tr("scenario_record_hotkeys_disabled"),
            )
            return
        if (
            self.clicking
            or self.coordinate_recording_active
            or self.sequence_input_active
            or self.waiting_for_sequence_input
            or self.waiting_for_click_key
            or self.waiting_for_start_key
            or self.waiting_for_stop_key
            or self.waiting_for_emergency_key
            or binding_recording
            or self.scenario_record_state != "idle"
            or self.scenario_record_dialog is not None
        ):
            QMessageBox.warning(
                dialog,
                self.tr("scenario_editor_title"),
                self.tr("scenario_record_busy"),
            )
            return
        if current_actions:
            reply = QMessageBox.question(
                dialog,
                self.tr("scenario_editor_title"),
                self.tr("scenario_record_overwrite"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        reply = QMessageBox.warning(
            dialog,
            self.tr("scenario_editor_title"),
            self.tr("scenario_record_warning"),
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if reply != QMessageBox.Yes:
            return

        with self.scenario_capture_lock:
            self.scenario_record_actions = []
            self.scenario_record_last_at = 0.0
            self.scenario_last_mouse_move_at = 0.0
            self.scenario_last_mouse_position = None
            self.scenario_record_dialog = dialog
            self.scenario_record_state = "armed"
        start_name = self._hotkey_name(self.start_hotkey)
        self.status_signal.emit(
            self.tr("scenario_record_armed", start_name),
            "#f0b429",
        )
        self.scenario_capture_signal.emit("armed", None)

    def _begin_scenario_recording(self):
        with self.scenario_capture_lock:
            if self.scenario_record_state != "armed":
                return
            self.scenario_record_actions = []
            self.scenario_record_last_at = time.monotonic()
            self.scenario_last_mouse_move_at = 0.0
            self.scenario_last_mouse_position = None
            self.scenario_record_state = "recording"
        self.scenario_capture_signal.emit("recording", 0)
        self.status_signal.emit(
            self.tr(
                "scenario_recording_status",
                0,
                self._hotkey_name(self.stop_hotkey),
            ),
            "#f0b429",
        )

    def _finish_scenario_recording(self):
        with self.scenario_capture_lock:
            if self.scenario_record_state != "recording":
                return
            actions = deepcopy(self.scenario_record_actions)
            self.scenario_record_state = "idle"
        self.scenario_capture_signal.emit("finished", actions)
        self.status_signal.emit(
            self.tr("scenario_record_finished", len(actions)),
            "#35d07f",
        )

    def _cancel_scenario_recording(self, dialog=None):
        with self.scenario_capture_lock:
            if (
                self.scenario_record_state == "idle"
                or (
                    dialog is not None
                    and self.scenario_record_dialog is not dialog
                )
            ):
                return
            self.scenario_record_state = "idle"
            self.scenario_record_actions = []
        self.scenario_capture_signal.emit("cancelled", None)
        self.status_signal.emit(self.tr("status_stopped"), "#91a4ba")

    def _record_scenario_event(self, event):
        finish_at_limit = False
        count = 0
        with self.scenario_capture_lock:
            if self.scenario_record_state != "recording":
                return
            if len(self.scenario_record_actions) >= MAX_SCENARIO_ACTIONS:
                finish_at_limit = True
            else:
                now = time.monotonic()
                event["delay"] = max(0.0, now - self.scenario_record_last_at)
                self.scenario_record_last_at = now
                self.scenario_record_actions.append(event)
                count = len(self.scenario_record_actions)
        if finish_at_limit:
            self._finish_scenario_recording()
            self.status_signal.emit(
                self.tr("scenario_record_limit"),
                "#f0b429",
            )
        elif count and count % 25 == 0:
            self.scenario_capture_signal.emit("recording", count)

    @Slot(str, object)
    def _handle_scenario_capture_update(self, state, actions):
        dialog = self.scenario_record_dialog
        if dialog is self:
            self.handle_scenario_capture_update(state, actions)
        elif dialog is not None:
            dialog.handle_scenario_capture_update(state, actions)
        if state in ("finished", "cancelled"):
            self.scenario_record_dialog = None

    def handle_scenario_capture_update(self, state, actions=None):
        if state == "finished" and actions is not None:
            try:
                normalized = self._normalize_scenario_actions(actions)
            except ValueError as error:
                QMessageBox.warning(
                    self,
                    self.tr("scenario_editor_title"),
                    str(error),
                )
            else:
                self.scenario_actions = normalized
                self.standalone_scenario_actions = deepcopy(normalized)
                self.save_standalone_scenario()
                self.status_signal.emit(
                    self.tr("scenario_record_finished", len(normalized)),
                    "#35d07f",
                )
        self._refresh_main_scenario_summary()
        self._update_main_scenario_controls()

    def _refresh_main_scenario_summary(self):
        if not hasattr(self, "main_scenario_summary"):
            return
        self.main_scenario_summary.setText(
            self.tr("scenario_standalone_summary", len(self.scenario_actions))
            if self.scenario_actions
            else self.tr("scenario_actions_empty")
        )

    def _update_main_scenario_controls(self):
        if not hasattr(self, "main_scenario_record_button"):
            return
        state = self.scenario_record_state
        if state == "armed":
            record_text = self.tr(
                "scenario_record_armed",
                self._hotkey_name(self.start_hotkey),
            )
        elif state == "recording":
            record_text = self.tr(
                "scenario_recording_status",
                len(self.scenario_record_actions),
                self._hotkey_name(self.stop_hotkey),
            )
        else:
            record_text = self.tr("scenario_record_button")
        self.main_scenario_record_button.setText(record_text)
        self.main_scenario_record_button.setEnabled(
            state not in ("armed", "recording")
        )
        self.main_scenario_edit_button.setText(
            self.tr("scenario_editor_button")
        )
        self.main_scenario_edit_button.setEnabled(
            state not in ("armed", "recording")
        )

    def edit_main_scenario(self):
        if self.scenario_record_dialog is not None:
            return
        dialog = ScenarioEditorDialog(self.scenario_actions, self)
        self.apply_theme()
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            normalized = self._normalize_scenario_actions(dialog.actions)
        except ValueError as error:
            QMessageBox.warning(
                self,
                self.tr("scenario_editor_title"),
                str(error),
            )
            return
        self.scenario_actions = normalized
        self.standalone_scenario_actions = deepcopy(normalized)
        self.save_standalone_scenario()
        self._refresh_main_scenario_summary()

    # ==========================================================
    # ЛОКАЛИЗАЦИЯ
    # ==========================================================
    def init_translations(self):
        self.translations = {
            'ru': {
                'title': APP_NAME,
                'subtitle': "Modern Auto Clicker",
                'settings_title': "Настройки",
                'settings_button_tooltip': "Открыть настройки",
                'dialog_close': "Закрыть",
                'settings_version': "Версия приложения: {}",
                'settings_developer': "Разработчик: lim0n4ikz",
                'settings_developer_discord': "Discord разработчика: lim0n4ikz",
                'settings_theme': "Тема оформления",
                'emergency_stop_title': "Аварийная остановка",
                'emergency_stop_warning': (
                    "Клавиша активна всегда, даже если бинды выключены или "
                    "окно свёрнуто. Рекомендуем Pause/Break или F12. Не "
                    "выбирайте клавишу запуска или часто используемую в игре."
                ),
                'emergency_stop_assign': "Назначить клавишу",
                'emergency_stop_capture': "Нажмите клавишу...",
                'settings_updates_section': "Обновления",
                'settings_general_section': "Основное",
                'settings_learning_section': "Интерактивное обучение",
                'mode_tutorial_settings_description': (
                    "Выберите один режим или пройдите обучение по всем."
                ),
                'tutorial_offer_title': "Пройти обучение?",
                'tutorial_offer_text': (
                    "Познакомьтесь с режимами кликера в коротком "
                    "интерактивном обучении."
                ),
                'tutorial_offer_details': (
                    "Обучение доступно в настройках через кнопку "
                    "«Показать обучение». «Пройти позже» напомнит при "
                    "следующем запуске, а «Не показывать снова» отключит "
                    "предложение навсегда."
                ),
                'tutorial_offer_start': "Пройти обучение",
                'tutorial_offer_later': "Пройти позже",
                'tutorial_offer_dismiss': "Не показывать снова",
                'mode_tutorial_open_button': "Показать обучение",
                'mode_tutorial_select_title': "Выберите обучение",
                'mode_tutorial_select_description': (
                    "Выберите режим, который хотите изучить, или запустите "
                    "обучение по всем режимам."
                ),
                'mode_tutorial_show_all': "Показать все режимы",
                'mode_tutorial_title': "Обучение режимам",
                'mode_tutorial_step_choose': "1. Выберите режим",
                'mode_tutorial_body_choose': (
                    "Вы выбрали режим «{}». Здесь, слева в главном окне, "
                    "находятся его настройки. На каждом шаге подсвечиваются "
                    "нужные элементы."
                ),
                'mode_tutorial_step_controls': "2. Настройте режим",
                'mode_tutorial_controls_instant': (
                    "Назначьте клавишу или кнопку мыши. Кликер будет "
                    "повторять нажатия с выбранным интервалом."
                ),
                'mode_tutorial_controls_hold': (
                    "Назначьте клавишу или кнопку мыши, которую нужно "
                    "удерживать во время каждого нажатия."
                ),
                'mode_tutorial_controls_combo': (
                    "Введите сочетание клавиш через «+» или задайте его "
                    "записью. Кнопка очистки сбрасывает сочетание."
                ),
                'mode_tutorial_controls_sequence': (
                    "Запишите или введите клавиши и кнопки мыши по порядку. "
                    "Кнопками рядом можно назначить или очистить список."
                ),
                'mode_tutorial_controls_coordinates': (
                    "Выберите монитор и нажмите «Записать координаты»: клик "
                    "добавляет точку, Shift+перетаскивание — свайп, F8 — "
                    "текущую позицию курсора. Backspace отменяет последнее "
                    "действие, Esc завершает запись."
                ),
                'mode_tutorial_controls_scenario': (
                    "«Записать сценарий» подготавливает запись: нажмите "
                    "горячую клавишу запуска, чтобы начать захват, и "
                    "остановки — чтобы завершить. Записываются клавиши, "
                    "клики и удержания мыши, движения курсора и прокрутка. "
                    "В редакторе можно менять действия, порядок и задержки; "
                    "сценарий хранится отдельно или в профиле. Запись "
                    "захватывает ввод во всех приложениях — не записывайте "
                    "пароли и конфиденциальный текст."
                ),
                'mode_tutorial_step_timing': "3. Настройте интервалы",
                'mode_tutorial_timing_instant': (
                    "Задайте паузу между нажатиями. Случайный интервал "
                    "выбирает задержку между указанными минимумом и максимумом."
                ),
                'mode_tutorial_timing_hold': (
                    "Настройте длительность удержания и паузу между "
                    "повторениями; для паузы можно включить случайный интервал."
                ),
                'mode_tutorial_timing_combo': (
                    "Задайте паузу между комбинациями. Случайный интервал "
                    "позволяет указать диапазон задержки."
                ),
                'mode_tutorial_timing_sequence': (
                    "Настройте паузу между действиями внутри последовательности "
                    "и задержку перед следующим циклом."
                ),
                'mode_tutorial_timing_coordinates': (
                    "Длительность перемещения и свайпа задаётся отдельно и "
                    "может быть случайной. При плавном движении пауза между "
                    "точками не используется; без него можно задать интервал "
                    "между действиями. Интервал цикла настраивается отдельно; "
                    "для доступных интервалов можно задать случайный диапазон."
                ),
                'mode_tutorial_timing_scenario': (
                    "После каждого полного воспроизведения сценарий повторяется. "
                    "Задайте фиксированный интервал или случайный диапазон "
                    "между повторами."
                ),
                'mode_tutorial_step_limits': "4. Лимиты и автоостановка",
                'mode_tutorial_body_limits': (
                    "Лимит времени работает во всех режимах. Включите его и "
                    "задайте длительность в минутах. Если вместе с ним "
                    "включён другой лимит, кликер остановится при первом "
                    "достигнутом условии."
                ),
                'mode_tutorial_body_click_limit': (
                    "В этом режиме также можно остановиться после заданного "
                    "числа кликов. Без лимитов работа продолжается до ручной "
                    "остановки."
                ),
                'mode_tutorial_body_scenario_limit': (
                    "Для сценариев вместо лимита кликов доступно ограничение "
                    "по числу полных выполнений. Без лимитов сценарий "
                    "повторяется до ручной остановки."
                ),
                'mode_tutorial_step_hotkeys': "5. Настройте горячие клавиши",
                'mode_tutorial_body_hotkeys': (
                    "Назначьте клавиши запуска и остановки (по умолчанию "
                    "F6 и F7) или временно выключите глобальные бинды. "
                    "Аварийная остановка настраивается отдельно в настройках."
                ),
                'mode_tutorial_step_run': "6. Запустите работу",
                'mode_tutorial_body_run': (
                    "Нажмите «Запустить» или горячую клавишу запуска. Для "
                    "остановки используйте кнопку или горячую клавишу "
                    "остановки. Быстрые профили справа позволяют сохранить "
                    "и повторно использовать настройки. Обучение только "
                    "показывает интерфейс и не запускает действия."
                ),
                'settings_bug_report_section': "Сообщить об ошибке",
                'settings_bug_report_description': (
                    "Обратная связь помогает нам становиться лучше. "
                    "Нашли ошибку или хотите предложить новую функцию? "
                    "Напишите нам!"
                ),
                'theme_dark': "Тёмная",
                'theme_ocean': "Бирюзовая",
                'theme_purple': "Фиолетовая",
                'theme_forest': "Зелёная",
                'theme_sunset': "Оранжевая",
                'theme_gray': "Серая",
                'theme_blue': "Синяя",
                'theme_red': "Красная",
                'theme_pink': "Розовая",
                'update_check_button': "Проверить обновления",
                'update_check_title': "Проверка обновлений",
                'update_current_version': "У вас установлена актуальная версия {}.",
                'update_custom_version': (
                    "Вы заглянули в будущее! У вас версия {}, а официальный "
                    "релиз пока только {}. Кажется, вы тестируете свежую сборку."
                ),
                'update_check_error': "Не удалось проверить обновления. Проверьте подключение к интернету и попробуйте ещё раз.",
                'bug_report_button': "Сообщить об ошибке",
                'bug_report_open_error': "Не удалось открыть форму сообщения об ошибке.",
                'profiles_transfer_title': "Профили",
                'profiles_manage': "Управление профилями",
                'profiles_manage_button': "Управление профилями",
                'profiles_manage_select_all': "Выбрать все",
                'profiles_manage_deselect_all': "Снять выделение",
                'profiles_manage_delete_selected': "Удалить выбранные ({})",
                'profiles_manage_confirm_delete': (
                    "Удалить выбранные профили: {}?"
                ),
                'profiles_manage_no_profiles': "Профилей пока нет.",
                'profile_keys_empty': "Пусто",
                'profiles_empty_title': "Здесь пока пусто",
                'profiles_empty_description': (
                    "Создайте первый профиль кнопкой «Добавить» или "
                    "импортируйте сохранённые профили."
                ),
                'profiles_manage_save_error': (
                    "Не удалось сохранить изменения профилей."
                ),
                'profiles_export': "Экспортировать профили",
                'profiles_import': "Импортировать профили",
                'profiles_export_success': "Профили экспортированы.",
                'profiles_export_empty': "Нет профилей для экспорта.",
                'profiles_select_all': "Выбрать все профили",
                'profiles_search_tooltip': "Найти профиль",
                'profiles_search_placeholder': "Поиск профиля...",
                'profiles_search_empty': "Профили не найдены.",
                'profiles_import_success': "Импортировано профилей: {}. Переименовано совпадающих профилей: {}.",
                'profiles_import_empty': "В файле нет профилей для импорта.",
                'profiles_import_confirm_many': (
                    "Будет импортировано профилей: {}. Продолжить?"
                ),
                'profiles_import_profile_details': (
                    "Клавиша: {} · Режим: {} · Интервал: {} сек."
                ),
                'profile_import_copy_suffix': " (импорт {})",
                'profiles_export_error': "Не удалось экспортировать профили:\n{}",
                'profiles_import_error': "Не удалось импортировать профили:\n{}",
                'profiles_import_save_error': "Не удалось сохранить импортированные профили.",
                'profiles_file_filter': "Файлы профилей (*.json)",
                'profile_object_invalid': "Каждый профиль должен быть объектом JSON",
                'profile_name_required': "У профиля должно быть непустое название",
                'profile_icon_invalid': "Некорректная иконка профиля «{}»",
                'profile_key_required': "У профиля «{}» должна быть указана клавиша",
                'profile_mode_unknown': "Неизвестный режим профиля «{}»",
                'profile_value_invalid': "Некорректное значение «{}» в профиле «{}»",
                'profile_random_invalid': "Некорректный случайный интервал в профиле «{}»",
                'profile_sequence_invalid': "Некорректная последовательность в профиле «{}»",
                'profile_coordinates_invalid': "Некорректные координаты в профиле «{}»",
                'profile_scenario_invalid': "Некорректный сценарий в профиле «{}»",
                'profile_coordinate_smooth_invalid': (
                    "Некорректный параметр плавного перемещения в профиле «{}»"
                ),
                'profile_file_too_large': "Размер файла профилей превышает 5 МБ",
                'profile_file_format_invalid': "Неподдерживаемый формат файла профилей",
                'profile_file_schema_invalid': "Неподдерживаемая версия файла профилей",
                'profile_file_list_invalid': "Файл должен содержать список профилей",
                'update_error_title': "Ошибка",
                'update_open_error': "Не удалось открыть страницу загрузки обновления.",
                'status_stopped': "● Остановлен",
                'status_running': "● Кликер работает",
                'status_click_stats': (
                    "Кликов: {} | КПС: {} | Средний КПС: {}"
                ),
                'status_error': "● Ошибка параметров",
                'status_hotkeys_enabled': "● Горячие клавиши включены",
                'status_hotkeys_disabled': "● Горячие клавиши отключены",
                'status_mode': "● Режим: {}",
                'status_held': "● Зажата {}",
                'status_pressed': "● Нажата {}",
                'status_combo': "● Выполнена комбинация: {}",
                'status_coordinate_click': "● Клик по точке {} из {}",
                'status_coordinate_swipe': "● Свайп {} из {}",
                'status_coordinate_error': "● Ошибка клика по координатам: {}",
                'status_hold_released': "● Кликер работает (зажатие отпущено)",
                'profiles_save_error': "● Не удалось сохранить профили",
                'mode_instant': "Мгновенное нажатие",
                'mode_hold': "Зажатие клавиши",
                'mode_sequence': "Последовательное нажатие",
                'mode_combo': "Мгновенная комбинация",
                'mode_coordinates': "Клики по координатам",
                'mode_scenario': "Записанный сценарий",
                'scenario_mode_hint': (
                    "Запишите или отредактируйте сценарий прямо здесь. "
                    "Start запускает его один раз, Stop останавливает."
                ),
                'scenario_editor_button': "Редактировать сценарий",
                'scenario_standalone_summary': "Действий в сценарии: {}",
                'scenario_record_button': "Записать сценарий",
                'scenario_record_armed': "Нажмите {} для начала записи.",
                'scenario_recording_status': (
                    "Запись: {} действий. Нажмите {} для остановки."
                ),
                'scenario_record_finished': "Записано действий: {}",
                'scenario_playback_status': "Сценарий: действие {} из {}",
                'scenario_playback_error': "Ошибка воспроизведения сценария: {}",
                'scenario_record_warning': (
                    "Запись будет захватывать клавиатуру, мышь и вводимый "
                    "текст во всех приложениях, пока не нажата клавиша Stop. "
                    "Не записывайте пароли и конфиденциальные данные."
                ),
                'scenario_record_overwrite': (
                    "Новая запись заменит текущий сценарий. Продолжить?"
                ),
                'scenario_record_busy': (
                    "Завершите текущую операцию и повторите запись."
                ),
                'scenario_record_limit': (
                    "Достигнут предел размера сценария. Запись остановлена."
                ),
                'scenario_action_limit': (
                    "В сценарии нельзя сохранить больше 100 000 действий."
                ),
                'scenario_save_error': (
                    "Не удалось сохранить отдельный сценарий."
                ),
                'scenario_record_hotkeys_disabled': (
                    "Сначала включите глобальные горячие клавиши."
                ),
                'scenario_actions_required': (
                    "Добавьте или запишите хотя бы одно действие."
                ),
                'scenario_editor_title': "Редактор сценария",
                'scenario_actions_empty': "Сценарий пока пуст.",
                'scenario_action_title': "Действие сценария",
                'scenario_action_add': "Добавить",
                'scenario_action_edit': "Изменить",
                'scenario_action_delete': "Удалить",
                'scenario_action_up': "Вверх",
                'scenario_action_down': "Вниз",
                'scenario_action_type': "Действие",
                'scenario_action_key': "Клавиша",
                'scenario_action_button': "Кнопка мыши",
                'scenario_action_x': "Позиция X",
                'scenario_action_y': "Позиция Y",
                'scenario_action_dx': "Прокрутка X",
                'scenario_action_dy': "Прокрутка Y",
                'scenario_action_delay': "Пауза перед действием (сек.)",
                'scenario_type_key_press': "Нажать клавишу",
                'scenario_type_key_release': "Отпустить клавишу",
                'scenario_type_mouse_press': "Нажать кнопку мыши",
                'scenario_type_mouse_release': "Отпустить кнопку мыши",
                'scenario_type_mouse_move': "Переместить курсор",
                'scenario_type_scroll': "Прокрутить колесо",
                'scenario_invalid_delay': "Укажите корректную паузу.",
                'scenario_invalid_key': "Укажите поддерживаемую клавишу.",
                'scenario_invalid_button': "Укажите кнопку мыши.",
                'scenario_invalid_position': "Укажите корректные координаты.",
                'scenario_invalid_scroll': "Укажите ненулевую прокрутку.",
                'scenario_editor_save_button': "Сохранить",
                'tutorial_back': "Назад",
                'tutorial_next': "Далее",
                'coordinate_monitor': "Монитор для записи",
                'coordinate_recorder_title': "Запись координат",
                'coordinate_recorder_instructions': (
                    "На оверлее кликайте, чтобы добавить точку, или "
                    "зажмите Shift и перетащите мышь, чтобы записать свайп. "
                    "Выберите кнопку, которая будет удерживаться при свайпе. "
                    "Backspace удаляет последнее действие и после записи."
                ),
                'coordinate_overlay_instructions': (
                    "Клик — точка · Shift+перетаскивание — свайп · "
                    "F8 — позиция курсора · Backspace — отменить · Esc — готово"
                ),
                'coordinate_start_recording': "Записать действия",
                'coordinate_record_button': "Записать координаты",
                'coordinate_swipe_button': "Кнопка мыши для свайпа",
                'coordinate_swipe_left': "Левая кнопка",
                'coordinate_swipe_right': "Правая кнопка",
                'coordinate_swipe_middle': "Средняя кнопка",
                'coordinate_swipe_x1': "Боковая кнопка X1",
                'coordinate_swipe_x2': "Боковая кнопка X2",
                'coordinate_points_label': "Действия",
                'coordinate_points_empty': "Действия не записаны",
                'coordinate_points_count': "Записано действий: {}",
                'coordinate_profile_summary': "Действий: {}",
                'coordinate_points_required': (
                    "Сначала запишите хотя бы одно действие для режима "
                    "«Клики по координатам»."
                ),
                'coordinate_points_invalid': "Некорректный список координат.",
                'coordinate_movement_group': "Перемещение курсора",
                'coordinate_smooth_move': "Плавно перемещать курсор между точками",
                'coordinate_move_duration': "Длительность перемещения, сек.",
                'coordinate_random_move_duration': "Случайная длительность перемещения",
                'coordinate_move_duration_min': "От, сек.",
                'coordinate_move_duration_max': "До, сек.",
                'coordinate_move_duration_order': (
                    "Максимальная длительность перемещения должна быть "
                    "не меньше минимальной."
                ),
                'coordinate_cycle_interval': "Интервал между циклами, сек.",
                'coordinate_cycle_interval_min': "Мин. интервал между циклами, сек.",
                'coordinate_cycle_interval_max': "Макс. интервал между циклами, сек.",
                'coordinate_cycle_interval_order': (
                    "Максимальный интервал между циклами должен быть не "
                    "меньше минимального."
                ),
                'coordinate_click_interval_order': (
                    "Максимальный интервал между кликами должен быть не "
                    "меньше минимального."
                ),
                'coordinate_screen_missing': (
                    "Монитор «{}» недоступен. Запишите точки заново для "
                    "подключённого монитора."
                ),
                'label_mode': "РЕЖИМ РАБОТЫ",
                'label_settings': "ПАРАМЕТРЫ",
                'label_click_key': "Клавиша / кнопка",
                'label_assigned': "Назначенная:",
                'button_assign': "⌨  Назначить",
                'button_record': "●  Запись",
                'button_stop_recording': "■  Остановить запись",
                'button_clear': "Очистить",
                'button_apply': "Применить",
                'label_interval': "Интервал между циклами",
                'label_min': "Min задержка, сек.",
                'label_max': "Max задержка, сек.",
                'label_single_interval': "Интервал, сек.",
                'label_coordinate_min': "Мин. интервал между действиями, сек.",
                'label_coordinate_max': "Макс. интервал между действиями, сек.",
                'label_coordinate_single_interval': "Интервал между действиями, сек.",
                'label_coordinate_random_interval': "Случайный интервал между действиями",
                'label_coordinate_random_cycle_interval': "Случайный интервал между циклами",
                'label_random_interval': "Включить случайный интервал",
                'scenario_interval': "Интервал между сценариями, сек.",
                'scenario_min_interval': "Мин. интервал между сценариями, сек.",
                'scenario_max_interval': "Макс. интервал между сценариями, сек.",
                'scenario_random_interval': "Случайный интервал между сценариями",
                'scenario_run_limit': "Остановиться после",
                'scenario_run_limit_suffix': "выполнений сценария",
                'duration_limit': "Остановиться через",
                'duration_limit_suffix': "мин.",
                'limits_hint': (
                    "Лимит времени действует во всех режимах. Если включено "
                    "несколько ограничений, кликер остановится при первом "
                    "достигнутом."
                ),
                'click_limit_enabled': "Остановиться после",
                'click_limit_suffix': "кликов",
                'label_sec': "сек.",
                'label_sequence': "Последовательность / комбинация",
                'label_keys': "Последовательность / комбинация",
                'label_interval_seq': "Между нажатиями, сек.",
                'label_hold': "Зажатие, сек.",
                'label_control': "УПРАВЛЕНИЕ",
                'button_start': "▶  ЗАПУСТИТЬ",
                'button_stop': "■  ОСТАНОВИТЬ ({})",
                'button_hotkeys_enable': "Включить бинды",
                'button_hotkeys_disable': "Выключить бинды",
                'label_hotkey_bindings': "ГОРЯЧИЕ КЛАВИШИ ЗАПУСКА И ОСТАНОВКИ",
                'label_start_binding': "Запуск:",
                'label_stop_binding': "Остановка:",
                'label_bindings_disabled': "Глобальные бинды выключены",
                'label_hotkey_info': "{} — запуск | {} — остановка",
                'placeholder_sequence': "Например: SPACE, ENTER, ЛКМ, W",
                'placeholder_combo': "Например: CTRL+SHIFT+W",
                'lang_ru': "Русский",
                'lang_en': "English",
                'error_sequence_parse': "Не удалось разобрать последовательность. Проверьте ввод.",
                'error_title': "Ошибка",
                'capture_click': "Нажмите кнопку...",
                'capture_hotkey': "Нажмите клавиши...",
                'profile_name': "Название",
                'profile_icon': "Иконка",
                'dialog_ok': "ОК",
                'dialog_cancel': "Отмена",
                'profiles_title': "БЫСТРЫЕ ПРОФИЛИ",
                'add_profile': "＋  Добавить",
                'profile_add_title': "Новый профиль",
                'profile_add_question': (
                    "Скопировать текущие настройки в новый профиль?"
                ),
                'profile_copy_settings': "Скопировать настройки",
                'profile_default_settings': "Стандартные настройки",
                'profile_new_name': "Новый профиль {}",
                'edit_profile': "Редактировать профиль",
                'delete_profile': "Удалить профиль",
                'profile_edit_title': "Редактировать профиль",
                'profile_delete_confirm': "Вы уверены, что хотите удалить профиль '{}'?",
                'mode': "Режим",
                'interval': "Интервал",
                'language': "Язык",
            },
            'en': {
                'title': APP_NAME,
                'subtitle': "Modern Auto Clicker",
                'settings_title': "Settings",
                'settings_button_tooltip': "Open settings",
                'dialog_close': "Close",
                'settings_version': "Application version: {}",
                'settings_developer': "Developer: lim0n4ikz",
                'settings_developer_discord': "Developer Discord: lim0n4ikz",
                'settings_theme': "Appearance theme",
                'emergency_stop_title': "Emergency stop",
                'emergency_stop_warning': (
                    "This key is always active, even when regular hotkeys are "
                    "disabled or the window is minimized. Use Pause/Break or "
                    "F12; avoid the start key and keys you use often in games."
                ),
                'emergency_stop_assign': "Assign key",
                'emergency_stop_capture': "Press a key...",
                'settings_updates_section': "Updates",
                'settings_general_section': "General",
                'settings_learning_section': "Interactive tutorials",
                'mode_tutorial_settings_description': (
                    "Choose one mode or take the tutorial for all modes."
                ),
                'tutorial_offer_title': "Would you like a tutorial?",
                'tutorial_offer_text': (
                    "Explore the clicker modes with a short interactive tutorial."
                ),
                'tutorial_offer_details': (
                    "You can open the tutorial later from Settings using "
                    "“Show tutorial”. “Later” will remind you next time you "
                    "launch the app; “Don't show again” permanently dismisses "
                    "this offer."
                ),
                'tutorial_offer_start': "Start tutorial",
                'tutorial_offer_later': "Later",
                'tutorial_offer_dismiss': "Don't show again",
                'mode_tutorial_open_button': "Show tutorial",
                'mode_tutorial_select_title': "Choose a tutorial",
                'mode_tutorial_select_description': (
                    "Choose a mode to learn or start the tutorial for all modes."
                ),
                'mode_tutorial_show_all': "Show all modes",
                'mode_tutorial_title': "Mode tutorials",
                'mode_tutorial_step_choose': "1. Choose a mode",
                'mode_tutorial_body_choose': (
                    "You selected {}. Its settings are on the left side of "
                    "the main window. Each step highlights the relevant controls."
                ),
                'mode_tutorial_step_controls': "2. Configure the mode",
                'mode_tutorial_controls_instant': (
                    "Assign a keyboard key or mouse button. The clicker "
                    "repeats the press using the selected interval."
                ),
                'mode_tutorial_controls_hold': (
                    "Assign the keyboard key or mouse button to hold during "
                    "each press."
                ),
                'mode_tutorial_controls_combo': (
                    "Enter a key combination separated by “+” or record it. "
                    "Use Clear to reset the combination."
                ),
                'mode_tutorial_controls_sequence': (
                    "Record or enter keyboard keys and mouse buttons in order. "
                    "Use the nearby buttons to record or clear the list."
                ),
                'mode_tutorial_controls_coordinates': (
                    "Choose a monitor and click Record coordinates: click to "
                    "add a point, Shift+drag to add a swipe, or F8 to capture "
                    "the cursor position. Backspace removes the last action; "
                    "Esc finishes recording."
                ),
                'mode_tutorial_controls_scenario': (
                    "Record scenario prepares a recording: press the Start "
                    "hotkey to begin capturing and the Stop hotkey to finish. "
                    "It captures keys, mouse clicks and holds, cursor movement, "
                    "and scrolling. Edit actions, order, and delays in the "
                    "editor; save scenarios separately or with a profile. "
                    "Recording captures input in every app, so do not record "
                    "passwords or sensitive text."
                ),
                'mode_tutorial_step_timing': "3. Set the timing",
                'mode_tutorial_timing_instant': (
                    "Set the pause between presses. Random interval chooses "
                    "a delay between the selected minimum and maximum."
                ),
                'mode_tutorial_timing_hold': (
                    "Set the hold duration and pause between repeats. You can "
                    "randomize the pause."
                ),
                'mode_tutorial_timing_combo': (
                    "Set the pause between combinations. Random interval "
                    "lets you define a delay range."
                ),
                'mode_tutorial_timing_sequence': (
                    "Set the pause between actions in the sequence and the "
                    "delay before the next cycle."
                ),
                'mode_tutorial_timing_coordinates': (
                    "Set cursor and swipe duration separately; it can be "
                    "randomized. Smooth movement disables the pause between "
                    "points; without it, configure the action interval. "
                    "The cycle interval is separate, and supported intervals "
                    "can use a random range."
                ),
                'mode_tutorial_timing_scenario': (
                    "The scenario repeats after each complete playback. "
                    "Set a fixed delay or random range between repeats."
                ),
                'mode_tutorial_step_limits': "4. Limits and automatic stop",
                'mode_tutorial_body_limits': (
                    "The time limit works in every mode. Enable it and set "
                    "the duration in minutes. If another limit is also "
                    "enabled, the clicker stops as soon as the first "
                    "condition is reached."
                ),
                'mode_tutorial_body_click_limit': (
                    "This mode also supports stopping after a set number of "
                    "clicks. Without limits, it keeps running until stopped "
                    "manually."
                ),
                'mode_tutorial_body_scenario_limit': (
                    "Scenario mode has a limit on the number of complete runs "
                    "instead of a click limit. With no limits, it repeats "
                    "until stopped manually."
                ),
                'mode_tutorial_step_hotkeys': "5. Set the hotkeys",
                'mode_tutorial_body_hotkeys': (
                    "Assign the Start and Stop keys (F6 and F7 by default) "
                    "or temporarily disable global hotkeys. Configure the "
                    "emergency stop key separately in Settings."
                ),
                'mode_tutorial_step_run': "6. Run the mode",
                'mode_tutorial_body_run': (
                    "Click Start or press the Start hotkey. Use the Stop "
                    "button or hotkey to finish. Quick profiles on the right "
                    "let you save and reuse settings. This tutorial only "
                    "shows the interface; it does not run any actions."
                ),
                'settings_bug_report_section': "Bug report",
                'settings_bug_report_description': (
                    "Your feedback helps us improve. Found a bug? "
                    "Want to suggest a new feature? Let us know!"
                ),
                'theme_dark': "Dark",
                'theme_ocean': "Turquoise",
                'theme_purple': "Purple",
                'theme_forest': "Green",
                'theme_sunset': "Orange",
                'theme_gray': "Gray",
                'theme_blue': "Blue",
                'theme_red': "Red",
                'theme_pink': "Pink",
                'update_check_button': "Check for updates",
                'update_check_title': "Update check",
                'update_current_version': "You are using the latest version {}.",
                'update_custom_version': (
                    "You're ahead of the future! You're running version {}, "
                    "while the latest official release is {}. Looks like "
                    "you're testing a fresh build."
                ),
                'update_check_error': "Could not check for updates. Check your internet connection and try again.",
                'bug_report_button': "Report a bug",
                'bug_report_open_error': "Could not open the bug report form.",
                'profiles_transfer_title': "Profiles",
                'profiles_manage': "Manage profiles",
                'profiles_manage_button': "Manage profiles",
                'profiles_manage_select_all': "Select all",
                'profiles_manage_deselect_all': "Clear selection",
                'profiles_manage_delete_selected': "Delete selected ({})",
                'profiles_manage_confirm_delete': (
                    "Delete selected profiles: {}?"
                ),
                'profiles_manage_no_profiles': "There are no profiles yet.",
                'profile_keys_empty': "Empty",
                'profiles_empty_title': "Nothing here yet",
                'profiles_empty_description': (
                    "Create your first profile with the Add button, or "
                    "import saved profiles."
                ),
                'profiles_manage_save_error': (
                    "Could not save the profile changes."
                ),
                'profiles_export': "Export profiles",
                'profiles_import': "Import profiles",
                'profiles_export_success': "Profiles exported.",
                'profiles_export_empty': "There are no profiles to export.",
                'profiles_select_all': "Select all profiles",
                'profiles_search_tooltip': "Search profiles",
                'profiles_search_placeholder': "Search profiles...",
                'profiles_search_empty': "No profiles found.",
                'profiles_import_success': "Imported profiles: {}. Renamed profiles with duplicate names: {}.",
                'profiles_import_empty': "There are no profiles to import.",
                'profiles_import_confirm_many': (
                    "Profiles to import: {}. Continue?"
                ),
                'profiles_import_profile_details': (
                    "Key: {} · Mode: {} · Interval: {} sec."
                ),
                'profile_import_copy_suffix': " (import {})",
                'profiles_export_error': "Could not export profiles:\n{}",
                'profiles_import_error': "Could not import profiles:\n{}",
                'profiles_import_save_error': "Could not save the imported profiles.",
                'profiles_file_filter': "Profile files (*.json)",
                'profile_object_invalid': "Each profile must be a JSON object",
                'profile_name_required': "Each profile must have a non-empty name",
                'profile_icon_invalid': "Invalid icon in profile \"{}\"",
                'profile_key_required': "Profile \"{}\" must specify a key",
                'profile_mode_unknown': "Unknown mode in profile \"{}\"",
                'profile_value_invalid': "Invalid \"{}\" value in profile \"{}\"",
                'profile_random_invalid': "Invalid random interval in profile \"{}\"",
                'profile_sequence_invalid': "Invalid sequence in profile \"{}\"",
                'profile_coordinates_invalid': "Invalid coordinates in profile \"{}\"",
                'profile_scenario_invalid': "Invalid scenario in profile \"{}\"",
                'profile_coordinate_smooth_invalid': (
                    "Invalid smooth-movement setting in profile \"{}\""
                ),
                'profile_file_too_large': "Profile file exceeds 5 MB",
                'profile_file_format_invalid': "Unsupported profile file format",
                'profile_file_schema_invalid': "Unsupported profile file version",
                'profile_file_list_invalid': "The file must contain a profile list",
                'update_error_title': "Error",
                'update_open_error': "Could not open the update download page.",
                'status_stopped': "● Stopped",
                'status_running': "● Clicker running",
                'status_click_stats': (
                    "Clicks: {} | CPS: {} | Avg. CPS: {}"
                ),
                'status_error': "● Parameter error",
                'status_hotkeys_enabled': "● Hotkeys enabled",
                'status_hotkeys_disabled': "● Hotkeys disabled",
                'status_mode': "● Mode: {}",
                'status_held': "● Held {}",
                'status_pressed': "● Pressed {}",
                'status_combo': "● Executed combination: {}",
                'status_coordinate_click': "● Clicked point {} of {}",
                'status_coordinate_swipe': "● Swipe {} of {}",
                'status_coordinate_error': "● Coordinate click failed: {}",
                'status_hold_released': "● Clicker running (hold released)",
                'profiles_save_error': "● Failed to save profiles",
                'mode_instant': "Instant press",
                'mode_hold': "Hold key",
                'mode_sequence': "Sequence press",
                'mode_combo': "Instant combo",
                'mode_coordinates': "Coordinate clicks",
                'mode_scenario': "Recorded scenario",
                'scenario_mode_hint': (
                    "Record or edit a scenario here. Start plays it once; "
                    "Stop interrupts playback."
                ),
                'scenario_editor_button': "Edit scenario",
                'scenario_standalone_summary': "Scenario actions: {}",
                'scenario_record_button': "Record scenario",
                'scenario_record_armed': "Press {} to start recording.",
                'scenario_recording_status': (
                    "Recording: {} actions. Press {} to stop."
                ),
                'scenario_record_finished': "Recorded actions: {}",
                'scenario_playback_status': "Scenario: action {} of {}",
                'scenario_playback_error': "Scenario playback failed: {}",
                'scenario_record_warning': (
                    "Recording captures keyboard, mouse, and typed text "
                    "across all applications until Stop is pressed. "
                    "Do not record passwords or sensitive information."
                ),
                'scenario_record_overwrite': (
                    "The new recording will replace the current scenario. Continue?"
                ),
                'scenario_record_busy': (
                    "Finish the current operation before recording."
                ),
                'scenario_record_limit': (
                    "The scenario size limit was reached. Recording stopped."
                ),
                'scenario_action_limit': (
                    "A scenario cannot contain more than 100,000 actions."
                ),
                'scenario_save_error': (
                    "Could not save the standalone scenario."
                ),
                'scenario_record_hotkeys_disabled': (
                    "Enable global hotkeys before recording."
                ),
                'scenario_actions_required': (
                    "Add or record at least one action."
                ),
                'scenario_editor_title': "Scenario editor",
                'scenario_actions_empty': "The scenario is empty.",
                'scenario_action_title': "Scenario action",
                'scenario_action_add': "Add",
                'scenario_action_edit': "Edit",
                'scenario_action_delete': "Delete",
                'scenario_action_up': "Up",
                'scenario_action_down': "Down",
                'scenario_action_type': "Action",
                'scenario_action_key': "Key",
                'scenario_action_button': "Mouse button",
                'scenario_action_x': "X position",
                'scenario_action_y': "Y position",
                'scenario_action_dx': "Scroll X",
                'scenario_action_dy': "Scroll Y",
                'scenario_action_delay': "Delay before action (sec.)",
                'scenario_type_key_press': "Press key",
                'scenario_type_key_release': "Release key",
                'scenario_type_mouse_press': "Press mouse button",
                'scenario_type_mouse_release': "Release mouse button",
                'scenario_type_mouse_move': "Move cursor",
                'scenario_type_scroll': "Scroll wheel",
                'scenario_invalid_delay': "Enter a valid delay.",
                'scenario_invalid_key': "Enter a supported key.",
                'scenario_invalid_button': "Enter a mouse button.",
                'scenario_invalid_position': "Enter valid coordinates.",
                'scenario_invalid_scroll': "Enter a non-zero scroll amount.",
                'scenario_editor_save_button': "Save",
                'tutorial_back': "Back",
                'tutorial_next': "Next",
                'coordinate_monitor': "Monitor for recording",
                'coordinate_recorder_title': "Record coordinates",
                'coordinate_recorder_instructions': (
                    "Click the overlay to add a point, or hold Shift and "
                    "drag to record a swipe. Select which mouse button is "
                    "held during swipe playback. Backspace removes the last "
                    "action, including after recording."
                ),
                'coordinate_overlay_instructions': (
                    "Click: point · Shift+drag: swipe · "
                    "F8: cursor position · Backspace: undo · Esc: finish"
                ),
                'coordinate_start_recording': "Record actions",
                'coordinate_record_button': "Record coordinates",
                'coordinate_swipe_button': "Mouse button for swipe",
                'coordinate_swipe_left': "Left button",
                'coordinate_swipe_right': "Right button",
                'coordinate_swipe_middle': "Middle button",
                'coordinate_swipe_x1': "Side button X1",
                'coordinate_swipe_x2': "Side button X2",
                'coordinate_points_label': "Actions",
                'coordinate_points_empty': "No actions recorded",
                'coordinate_points_count': "Recorded actions: {}",
                'coordinate_profile_summary': "Actions: {}",
                'coordinate_points_required': (
                    "Record at least one action for Coordinate clicks mode."
                ),
                'coordinate_points_invalid': "The coordinate point list is invalid.",
                'coordinate_movement_group': "Cursor movement",
                'coordinate_smooth_move': "Move the cursor smoothly between points",
                'coordinate_move_duration': "Movement duration, sec.",
                'coordinate_random_move_duration': "Randomize movement duration",
                'coordinate_move_duration_min': "Min, sec.",
                'coordinate_move_duration_max': "Max, sec.",
                'coordinate_move_duration_order': (
                    "Maximum movement duration must not be less than the minimum."
                ),
                'coordinate_cycle_interval': "Interval between cycles, sec.",
                'coordinate_cycle_interval_min': "Min interval between cycles, sec.",
                'coordinate_cycle_interval_max': "Max interval between cycles, sec.",
                'coordinate_cycle_interval_order': (
                    "Maximum interval between cycles must not be less than the minimum."
                ),
                'coordinate_click_interval_order': (
                    "Maximum interval between clicks must not be less than the minimum."
                ),
                'coordinate_screen_missing': (
                    "Monitor \"{}\" is unavailable. Record the points again "
                    "for a connected monitor."
                ),
                'label_mode': "WORK MODE",
                'label_settings': "PARAMETERS",
                'label_click_key': "Key / Button",
                'label_assigned': "Assigned:",
                'button_assign': "⌨  Assign",
                'button_record': "●  Record",
                'button_stop_recording': "■  Stop recording",
                'button_clear': "Clear",
                'button_apply': "Apply",
                'label_interval': "Cycle Interval",
                'label_min': "Min delay, sec.",
                'label_max': "Max delay, sec.",
                'label_single_interval': "Interval, sec.",
                'label_coordinate_min': "Min interval between actions, sec.",
                'label_coordinate_max': "Max interval between actions, sec.",
                'label_coordinate_single_interval': "Interval between actions, sec.",
                'label_coordinate_random_interval': "Randomize interval between actions",
                'label_coordinate_random_cycle_interval': "Randomize interval between cycles",
                'label_random_interval': "Enable random interval",
                'scenario_interval': "Interval between scenarios, sec.",
                'scenario_min_interval': "Min interval between scenarios, sec.",
                'scenario_max_interval': "Max interval between scenarios, sec.",
                'scenario_random_interval': "Random interval between scenarios",
                'scenario_run_limit': "Stop after",
                'scenario_run_limit_suffix': "scenario runs",
                'duration_limit': "Stop after",
                'duration_limit_suffix': "min.",
                'limits_hint': (
                    "The time limit applies to every mode. If multiple limits "
                    "are enabled, the clicker stops when the first is reached."
                ),
                'click_limit_enabled': "Stop after",
                'click_limit_suffix': "clicks",
                'label_sec': "sec.",
                'label_sequence': "Sequence / Combo",
                'label_keys': "Sequence / Combination",
                'label_interval_seq': "Between keys, sec.",
                'label_hold': "Hold, sec.",
                'label_control': "CONTROL",
                'button_start': "▶  START",
                'button_stop': "■  STOP ({})",
                'button_hotkeys_enable': "Enable hotkeys",
                'button_hotkeys_disable': "Disable hotkeys",
                'label_hotkey_bindings': "START & STOP HOTKEYS",
                'label_start_binding': "Start:",
                'label_stop_binding': "Stop:",
                'label_bindings_disabled': "Global hotkeys disabled",
                'label_hotkey_info': "{} — start | {} — stop",
                'placeholder_sequence': "E.g.: SPACE, ENTER, LMB, W",
                'placeholder_combo': "E.g.: CTRL+SHIFT+W",
                'lang_ru': "Russian",
                'lang_en': "English",
                'error_sequence_parse': "Failed to parse sequence. Check input.",
                'error_title': "Error",
                'capture_click': "Press a button...",
                'capture_hotkey': "Press keys...",
                'profile_name': "Name",
                'profile_icon': "Icon",
                'dialog_ok': "OK",
                'dialog_cancel': "Cancel",
                'profiles_title': "QUICK PROFILES",
                'add_profile': "＋  Add",
                'profile_add_title': "New profile",
                'profile_add_question': (
                    "Copy the current settings to the new profile?"
                ),
                'profile_copy_settings': "Copy current settings",
                'profile_default_settings': "Use default settings",
                'profile_new_name': "New profile {}",
                'edit_profile': "Edit Profile",
                'delete_profile': "Delete Profile",
                'profile_edit_title': "Edit Profile",
                'profile_delete_confirm': "Are you sure you want to delete profile '{}'?",
                'mode': "Mode",
                'interval': "Interval",
                'language': "Language",
            }
        }

    def tr(self, key, *args):
        text = self.translations[self.language].get(key, key)
        if args:
            return text.format(*args)
        return text

    def tr_mode(self, mode_key):
        mapping = {
            self.MODE_INSTANT: 'mode_instant',
            self.MODE_HOLD: 'mode_hold',
            self.MODE_SEQUENCE: 'mode_sequence',
            self.MODE_COMBO: 'mode_combo',
            self.MODE_COORDINATES: 'mode_coordinates',
            self.MODE_SCENARIO: 'mode_scenario',
        }
        return self.tr(mapping.get(mode_key, mode_key))

    @Slot()
    def update_language(self):
        # Заголовки и основные надписи
        self.title.setText(self.tr('title'))
        self.subtitle.setText(self.tr('subtitle'))
        self.settings_dialog.setWindowTitle(self.tr('settings_title'))
        self.settings_general_title_label.setText(
            self.tr('settings_general_section')
        )
        self.settings_version_label.setText(
            self.tr('settings_version').format(APP_VERSION)
        )
        self.settings_developer_label.setText(self.tr('settings_developer'))
        self.settings_developer_discord_label.setText(
            self.tr('settings_developer_discord')
        )
        self.settings_theme_label.setText(self.tr('settings_theme'))
        self.settings_learning_title_label.setText(
            self.tr("settings_learning_section")
        )
        self.mode_tutorial_description_label.setText(
            self.tr("mode_tutorial_settings_description")
        )
        self.mode_tutorial_button.setText(
            self.tr("mode_tutorial_open_button")
        )
        self.settings_updates_title_label.setText(
            self.tr('settings_updates_section')
        )
        self.settings_bug_report_title_label.setText(
            self.tr('settings_bug_report_section')
        )
        self.settings_bug_report_description_label.setText(
            self.tr('settings_bug_report_description')
        )
        self.emergency_stop_title_label.setText(
            self.tr('emergency_stop_title')
        )
        self.emergency_stop_warning_label.setText(
            self.tr('emergency_stop_warning')
        )
        self.emergency_stop_assign_button.setText(
            self.tr('emergency_stop_capture')
            if self.waiting_for_emergency_key
            else self.tr('emergency_stop_assign')
        )
        if not self.waiting_for_emergency_key:
            self.emergency_stop_key_edit.setText(self.emergency_stop_key)
        self.update_check_button.setText(self.tr('update_check_button'))
        self.bug_report_button.setText(self.tr('bug_report_button'))
        self.profiles_transfer_title_label.setText(
            self.tr('profiles_transfer_title')
        )
        self.profiles_manage_button.setText(
            self.tr('profiles_manage_button')
        )
        self.profiles_export_button.setText(self.tr('profiles_export'))
        self.profiles_import_button.setText(self.tr('profiles_import'))
        self.settings_close_button.setText(self.tr('dialog_close'))
        self.settings_button.setToolTip(self.tr('settings_button_tooltip'))
        self.settings_button.setAccessibleName(self.tr('settings_title'))
        self.section_mode.setText(self.tr('label_mode'))
        self.scenario_mode_label.setText(self.tr("scenario_mode_hint"))
        self._refresh_main_scenario_summary()
        self._update_main_scenario_controls()
        self.section_params.setText(self.tr('label_settings'))
        self.lbl_click_key.setText(self.tr('label_click_key'))
        self.assign_btn.setText(self.tr('button_assign'))
        self.lbl_min_interval.setText(
            self.tr('label_min') if self.random_interval.isChecked()
            else self.tr('label_single_interval')
        )
        self.lbl_max_interval.setText(self.tr('label_max'))
        self.lbl_hold_time.setText(self.tr('label_hold'))
        self.lbl_between.setText(self.tr('label_interval_seq'))
        self.sequence_label.setText(self.tr('label_sequence'))
        self._set_sequence_recording(self.waiting_for_sequence_input)
        self.sequence_clear_btn.setText(self.tr('button_clear'))
        self.sequence_apply_btn.setText(self.tr('button_apply'))
        self.coordinate_record_button.setText(
            self.tr('coordinate_record_button')
        )
        self.coordinate_smooth_checkbox.setText(
            self.tr('coordinate_smooth_move')
        )
        self.coordinate_random_move_duration_checkbox.setText(
            self.tr('coordinate_random_move_duration')
        )
        self.coordinate_move_duration_label.setText(
            self.tr('coordinate_move_duration')
        )
        self.coordinate_move_duration_min_label.setText(
            self.tr('coordinate_move_duration_min')
        )
        self.coordinate_move_duration_max_label.setText(
            self.tr('coordinate_move_duration_max')
        )
        self.coordinate_movement_group.setTitle(
            self.tr('coordinate_movement_group')
        )
        self.coordinate_cycle_interval_label.setText(
            self.tr('coordinate_cycle_interval')
        )
        self.coordinate_cycle_interval_max_label.setText(
            self.tr('coordinate_cycle_interval_max')
        )
        self.coordinate_random_click_interval_checkbox.setText(
            self.tr('label_coordinate_random_interval')
        )
        self.coordinate_points_label.setText(
            self.tr('coordinate_points_count', len(self.coordinate_points))
            if self.coordinate_points
            else self.tr('coordinate_points_empty')
        )
        self.start_btn.setText(self.tr('button_start'))
        self.stop_btn.setText(
            self.tr('button_stop').format(self.emergency_stop_key)
        )
        self.section_hk.setText(self.tr('label_hotkey_bindings'))
        self.lbl_hk_start.setText(self.tr('label_start_binding'))
        self.lbl_hk_stop.setText(self.tr('label_stop_binding'))
        self.assign_hk_start.setText(self.tr('button_assign'))
        self.assign_hk_stop.setText(self.tr('button_assign'))
        self.enable_hk_btn.setText(self.tr('button_hotkeys_enable'))
        self.disable_hk_btn.setText(self.tr('button_hotkeys_disable'))
        self.random_interval.setText(self.tr('label_random_interval'))
        self.click_limit_checkbox.setText(
            self.tr('click_limit_enabled')
        )
        self.click_limit_suffix.setText(
            self.tr('click_limit_suffix')
        )
        self.scenario_run_limit_checkbox.setText(
            self.tr("scenario_run_limit")
        )
        self.scenario_run_limit_suffix.setText(
            self.tr("scenario_run_limit_suffix")
        )
        self.duration_limit_checkbox.setText(
            self.tr("duration_limit")
        )
        self.duration_limit_suffix.setText(
            self.tr("duration_limit_suffix")
        )
        self.limits_hint_label.setText(
            self.tr("limits_hint")
        )
        self.update_random_interval_ui()
        self.profiles_title_label.setText(self.tr('profiles_title'))
        self.add_profile_btn.setText(self.tr('add_profile'))
        self.profiles_search_button.setToolTip(
            self.tr('profiles_search_tooltip')
        )
        self.profiles_search_edit.setPlaceholderText(
            self.tr('profiles_search_placeholder')
        )
        self.profiles_search_empty_label.setText(
            self.tr('profiles_search_empty')
        )
        self.profiles_empty_title_label.setText(
            self.tr('profiles_empty_title')
        )
        self.profiles_empty_description_label.setText(
            self.tr('profiles_empty_description')
        )
        self.lang_label.setText(self.tr('language'))
        # Обновление выпадающего списка режимов
        self.mode.blockSignals(True)
        self.mode.clear()
        self.mode.addItems([
            self.tr('mode_instant'),
            self.tr('mode_hold'),
            self.tr('mode_combo'),
            self.tr('mode_sequence'),
            self.tr('mode_coordinates'),
            self.tr('mode_scenario'),
        ])
        mode_map = {
            self.MODE_INSTANT: 0,
            self.MODE_HOLD: 1,
            self.MODE_COMBO: 2,
            self.MODE_SEQUENCE: 3,
            self.MODE_COORDINATES: 4,
            self.MODE_SCENARIO: 5,
        }
        self.mode.setCurrentIndex(mode_map.get(self.current_mode, 0))
        self.mode.blockSignals(False)
        self.update_info_label()
        self.update_mode_ui()
        self.update_hotkey_ui()

        # Обновление комбобокса языка (без срабатывания сигнала)
        self.lang_combo.blockSignals(True)
        self.lang_combo.clear()
        self.lang_combo.addItems([self.tr('lang_ru'), self.tr('lang_en')])
        if self.language == 'en':
            self.lang_combo.setCurrentText(self.tr('lang_en'))
        else:
            self.lang_combo.setCurrentText(self.tr('lang_ru'))
        self.lang_combo.blockSignals(False)
        self.theme_combo.blockSignals(True)
        self.theme_combo.clear()
        self.theme_combo.addItem(self.tr('theme_dark'), "dark")
        self.theme_combo.addItem(self.tr('theme_ocean'), "ocean")
        self.theme_combo.addItem(self.tr('theme_purple'), "purple")
        self.theme_combo.addItem(self.tr('theme_forest'), "forest")
        self.theme_combo.addItem(self.tr('theme_sunset'), "sunset")
        self.theme_combo.addItem(self.tr('theme_gray'), "gray")
        self.theme_combo.addItem(self.tr('theme_blue'), "blue")
        self.theme_combo.addItem(self.tr('theme_red'), "red")
        self.theme_combo.addItem(self.tr('theme_pink'), "pink")
        theme_index = self.theme_combo.findData(self.theme)
        self.theme_combo.setCurrentIndex(max(0, theme_index))
        self.theme_combo.blockSignals(False)

        # Перерисовываем профили, чтобы обновить текст меню и подписи
        self.refresh_profiles()
        if self.profile_dialog is not None:
            self.profile_dialog.update_language()

    def update_random_interval_ui(self):
        random_enabled = self.random_interval.isChecked()
        is_coordinate_mode = self.current_mode == self.MODE_COORDINATES
        is_scenario_mode = self.current_mode == self.MODE_SCENARIO
        random_click_enabled = (
            self.coordinate_random_click_interval_checkbox.isChecked()
        )
        self.lbl_min_interval.setText(
            self.tr(
                'scenario_min_interval'
                if is_scenario_mode and random_enabled
                else 'scenario_interval'
                if is_scenario_mode
                else 'label_coordinate_min'
                if is_coordinate_mode and random_click_enabled
                else 'label_coordinate_single_interval'
                if is_coordinate_mode
                else 'label_min'
                if random_enabled
                else 'label_single_interval'
            )
        )
        self.lbl_max_interval.setText(
            self.tr(
                'scenario_max_interval'
                if is_scenario_mode
                else 'label_coordinate_max'
                if is_coordinate_mode
                else 'label_max'
            )
        )
        self.random_interval.setText(
            self.tr(
                'scenario_random_interval'
                if is_scenario_mode
                else 'label_coordinate_random_cycle_interval'
                if is_coordinate_mode
                else 'label_random_interval'
            )
        )
        if is_coordinate_mode:
            self.coordinate_cycle_interval_label.setText(
                self.tr(
                    'coordinate_cycle_interval_min'
                    if random_enabled
                    else 'coordinate_cycle_interval'
                )
            )
        self.coordinate_random_click_interval_checkbox.setText(
            self.tr('label_coordinate_random_interval')
        )
        self.coordinate_cycle_interval_max_label.setVisible(
            is_coordinate_mode and random_enabled
        )
        self.coordinate_cycle_interval_max_edit.setVisible(
            is_coordinate_mode and random_enabled
        )
        self.update_random_interval_visibility()

    def _on_click_limit_toggled(self, enabled):
        self.click_limit_edit.setEnabled(enabled)
        self.save_settings()

    def _on_limit_toggled(self, edit, enabled):
        edit.setEnabled(enabled)
        self.save_settings()

    def update_coordinate_move_ui(self):
        is_coordinate_mode = self.current_mode == self.MODE_COORDINATES
        uses_coordinate_movement = (
            is_coordinate_mode
            and (
                self.coordinate_smooth_checkbox.isChecked()
                or has_coordinate_swipe(self.coordinate_points)
            )
        )
        show_duration = uses_coordinate_movement
        random_duration = (
            show_duration
            and self.coordinate_random_move_duration_checkbox.isChecked()
        )
        self.coordinate_move_duration_label.setVisible(
            show_duration and not random_duration
        )
        self.coordinate_random_move_duration_checkbox.setVisible(
            show_duration
        )
        self.coordinate_move_duration_edit.setVisible(
            show_duration and not random_duration
        )
        self.coordinate_move_duration_min_label.setVisible(random_duration)
        self.coordinate_move_duration_min_edit.setVisible(random_duration)
        self.coordinate_move_duration_max_label.setVisible(random_duration)
        self.coordinate_move_duration_max_edit.setVisible(random_duration)
        self.coordinate_movement_group.setVisible(
            is_coordinate_mode
        )
        show_cycle_interval = is_coordinate_mode
        self.coordinate_cycle_interval_label.setVisible(show_cycle_interval)
        self.coordinate_cycle_interval_edit.setVisible(show_cycle_interval)
        random_cycle = self.random_interval.isChecked()
        self.coordinate_cycle_interval_max_label.setVisible(
            show_cycle_interval and random_cycle
        )
        self.coordinate_cycle_interval_max_edit.setVisible(
            show_cycle_interval and random_cycle
        )
        self.update_random_interval_visibility()

    def update_random_interval_visibility(self):
        is_coordinate_mode = self.current_mode == self.MODE_COORDINATES
        self.random_interval.setVisible(True)
        random_click_enabled = (
            self.coordinate_random_click_interval_checkbox.isChecked()
            if is_coordinate_mode
            else self.random_interval.isChecked()
        )
        show_click_interval = not (
            is_coordinate_mode
            and self.coordinate_smooth_checkbox.isChecked()
        )
        self.lbl_min_interval.setVisible(show_click_interval)
        self.min_interval_edit.setVisible(show_click_interval)
        self.lbl_max_interval.setVisible(
            show_click_interval and random_click_enabled
        )
        self.max_interval_edit.setVisible(
            show_click_interval and random_click_enabled
        )
        self.coordinate_random_click_interval_checkbox.setVisible(
            is_coordinate_mode and show_click_interval
        )

    def update_hotkey_ui(self):
        # обновление внешнего вида кнопок включения/выключения хоткеев
        if self.hotkeys_enabled:
            self.enable_hk_btn.setEnabled(False)
            self.disable_hk_btn.setEnabled(True)
        else:
            self.enable_hk_btn.setEnabled(True)
            self.disable_hk_btn.setEnabled(False)
        self.assign_hk_start.setEnabled(True)
        self.assign_hk_stop.setEnabled(True)
        self.update_info_label()

    def apply_theme(self):
        if self.theme not in THEME_COLOR_MAPS:
            self.theme = "dark"
        app = QApplication.instance()
        if app:
            app.setStyleSheet(
                theme_stylesheet(self.theme, self._responsive_font_size)
            )
        if hasattr(self, "settings_dialog"):
            dialog_palette = self.settings_dialog.palette()
            dialog_palette.setColor(
                QPalette.Window,
                QColor(
                    THEME_COLOR_MAPS[self.theme].get(
                        "#060d16",
                        "#060d16",
                    )
                ),
            )
            self.settings_dialog.setPalette(dialog_palette)
            self.settings_dialog.setAutoFillBackground(True)
        for widget in self.findChildren(QWidget):
            if widget is self.status_label:
                continue
            base_stylesheet = widget.property("_base_theme_stylesheet")
            if base_stylesheet is None:
                base_stylesheet = widget.styleSheet()
                widget.setProperty("_base_theme_stylesheet", base_stylesheet)
            widget.setStyleSheet(theme_local_stylesheet(
                base_stylesheet,
                self.theme,
            ))
        if hasattr(self, "status_label"):
            status_color = THEME_COLOR_MAPS[self.theme].get(
                self._status_base_color.lower(),
                self._status_base_color,
            )
            self.status_label.setStyleSheet(
                f"color: {status_color}; font-weight: 600;"
            )
    def on_theme_changed(self, index):
        selected_theme = self.theme_combo.itemData(index)
        if selected_theme not in THEME_COLOR_MAPS:
            return
        self.theme = selected_theme
        self.apply_theme()
        self.save_settings()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        font_size = max(11, min(14, round(self.width() / 90)))
        if font_size != self._responsive_font_size:
            self._responsive_font_size = font_size
            app = QApplication.instance()
            if app:
                app.setStyleSheet(theme_stylesheet(self.theme, font_size))
        if hasattr(self, "status_label"):
            self._render_status_text()

    # ==========================================================
    # ИНТЕРФЕЙС UI
    # ==========================================================
    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 18, 20, 15)
        root.setSpacing(15)

        # ---------------- HEADER ----------------
        header = QHBoxLayout()
        logo = QLabel()
        logo.setFixedSize(68, 68)
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet("QLabel { background: transparent; padding: 6px; }")
        if self.windowIcon().isNull():
            icon_path = ICON_FILE if ICON_FILE.exists() else FALLBACK_ICON_FILE
            if icon_path.exists():
                self.setWindowIcon(QIcon(str(icon_path)))
        if not self.windowIcon().isNull():
            logo.setPixmap(self.windowIcon().pixmap(56, 56))
        header.addWidget(logo)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        self.title = QLabel(APP_NAME)
        self.title.setObjectName("title")
        self.subtitle = QLabel(self.tr('subtitle'))
        self.subtitle.setObjectName("subtitle")
        title_box.addWidget(self.title)
        title_box.addWidget(self.subtitle)
        header.addLayout(title_box)
        header.addStretch()

        self.click_stats_label = QLabel()
        self.click_stats_label.setMinimumWidth(0)
        self.click_stats_label.setMaximumWidth(280)
        self.click_stats_label.setSizePolicy(
            QSizePolicy.Maximum,
            QSizePolicy.Fixed,
        )
        header.addWidget(self.click_stats_label)
        self.status_label = QLabel(self.tr('status_stopped'))
        self.status_label.setMinimumWidth(125)
        self.status_label.setMaximumWidth(190)
        self.status_label.setSizePolicy(
            QSizePolicy.Preferred,
            QSizePolicy.Fixed,
        )
        self._status_base_color = "#ff6873"
        self.status_label.setStyleSheet("color:#ff6873; font-weight:600;")
        header.addWidget(self.status_label)
        self.settings_button = QPushButton("⚙")
        self.settings_button.setObjectName("settings-btn")
        self.settings_button.setFixedSize(38, 38)
        self.settings_button.setFont(QFont("Segoe UI Symbol", 18))
        self.settings_button.setToolTip(self.tr('settings_button_tooltip'))
        self.settings_button.setAccessibleName(self.tr('settings_title'))
        self.settings_button.clicked.connect(self.show_settings_dialog)
        header.addWidget(self.settings_button)
        root.addLayout(header)

        # ---------------- TABS ----------------
        settings_tab = QWidget()
        root.addWidget(settings_tab)

        # ---------------- SETTINGS TAB с разделителем -----------
        settings_layout = QHBoxLayout(settings_tab)
        self.settings_layout = settings_layout
        settings_layout.setContentsMargins(0, 8, 0, 0)
        settings_layout.setSpacing(18)

        # Левая панель (настройки)
        left_panel = self.create_settings_panel()
        # Правая панель (профили)
        right_panel = self.create_profiles_panel()

        self.settings_scroll = QScrollArea()
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setFrameShape(QFrame.NoFrame)
        self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.settings_scroll.setWidget(left_panel)

        settings_layout.addWidget(self.settings_scroll, 1)
        settings_layout.addWidget(right_panel, 1)
        left_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        right_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.build_settings_dialog()

    def show_settings_dialog(self):
        self.settings_dialog.exec()

    def available_modes(self):
        return [
            self.MODE_INSTANT,
            self.MODE_HOLD,
            self.MODE_COMBO,
            self.MODE_SEQUENCE,
            self.MODE_COORDINATES,
            self.MODE_SCENARIO,
        ]

    def open_mode_tutorial_from_settings(self):
        self.settings_dialog.accept()
        QTimer.singleShot(0, self.select_mode_tutorial)

    def select_mode_tutorial(self):
        selection_dialog = ModeTutorialSelectionDialog(self)
        if selection_dialog.exec() != QDialog.Accepted:
            return False
        self.show_mode_tutorial(selection_dialog.selected_modes)
        self._tutorial_offer_version = APP_VERSION
        self._tutorial_prompt_pending = False
        self.save_settings()
        return True

    def _offer_tutorial_on_first_launch(self):
        if not self._tutorial_prompt_pending or not self.isVisible():
            return
        if (
            self.update_check_started
            or QApplication.activeModalWidget() is not None
        ):
            QTimer.singleShot(
                500,
                self._offer_tutorial_on_first_launch,
            )
            return

        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setWindowTitle(self.tr("tutorial_offer_title"))
        dialog.setText(self.tr("tutorial_offer_text"))
        dialog.setInformativeText(self.tr("tutorial_offer_details"))
        selected_action = None

        def remember_action(action):
            nonlocal selected_action
            selected_action = action

        start_button = dialog.addButton(
            self.tr("tutorial_offer_start"),
            QMessageBox.ButtonRole.AcceptRole,
        )
        start_button.clicked.connect(
            lambda checked=False: remember_action("start")
        )
        later_button = dialog.addButton(
            self.tr("tutorial_offer_later"),
            QMessageBox.ButtonRole.ActionRole,
        )
        later_button.clicked.connect(
            lambda checked=False: remember_action("later")
        )
        dismiss_button = dialog.addButton(
            self.tr("tutorial_offer_dismiss"),
            QMessageBox.ButtonRole.RejectRole,
        )
        dismiss_button.clicked.connect(
            lambda checked=False: remember_action("dismiss")
        )
        dialog.setDefaultButton(start_button)
        dialog.exec()

        if selected_action == "start":
            self._tutorial_offer_version = APP_VERSION
            self._tutorial_prompt_pending = False
            self.save_settings()
            self.select_mode_tutorial()
        elif selected_action == "dismiss":
            self._tutorial_offer_version = APP_VERSION
            self._tutorial_offer_dismissed = True
            self._tutorial_prompt_pending = False
            self.save_settings()
        else:
            self.save_settings()

    def show_mode_tutorial(self, modes):
        available_modes = self.available_modes()
        if not modes or any(mode not in available_modes for mode in modes):
            return
        if self._mode_tutorial_dialog is not None:
            self._mode_tutorial_dialog.close()
        self.mode.setCurrentIndex(available_modes.index(modes[0]))
        self.settings_scroll.ensureWidgetVisible(self.mode, 16, 16)
        dialog = ModeTutorialWizard(self, modes)
        self._mode_tutorial_dialog = dialog
        dialog.finished.connect(
            lambda _result, wizard=dialog: self._finish_mode_tutorial(wizard)
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _finish_mode_tutorial(self, dialog):
        self.clear_mode_tutorial_highlights()
        if self._mode_tutorial_dialog is dialog:
            self._mode_tutorial_dialog = None

    def highlight_mode_tutorial_targets(self, targets):
        self.clear_mode_tutorial_highlights()
        if targets:
            self.settings_scroll.ensureWidgetVisible(targets[0], 16, 16)
        for target in targets:
            if not target.isVisible():
                continue
            position = target.mapTo(self, QPoint(0, 0))
            highlight = QFrame(self)
            highlight.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            highlight.setObjectName("modeTutorialHighlight")
            highlight.setStyleSheet(
                "QFrame { background: transparent; border: 3px solid "
                "#ffd35c; border-radius: 8px; }"
            )
            highlight.setGeometry(
                position.x() - 4,
                position.y() - 4,
                target.width() + 8,
                target.height() + 8,
            )
            highlight.show()
            highlight.raise_()
            self._mode_tutorial_highlights.append(highlight)

    def clear_mode_tutorial_highlights(self):
        for highlight in self._mode_tutorial_highlights:
            highlight.hide()
            highlight.deleteLater()
        self._mode_tutorial_highlights.clear()

    def manage_profiles(self):
        dialog = ProfileManagementDialog(
            self.profiles,
            self.tr,
            self,
        )
        self.apply_theme()
        if dialog.exec() != QDialog.Accepted:
            return

        selected_ids = {
            id(profile) for profile in dialog.selected_profiles()
        }
        updated_profiles = [
            profile
            for profile in self.profiles
            if id(profile) not in selected_ids
        ]
        if not self._write_profiles(updated_profiles):
            QMessageBox.warning(
                self,
                self.tr('profiles_transfer_title'),
                self.tr('profiles_manage_save_error'),
            )
            return

        self.profiles = updated_profiles
        self.refresh_profiles()

    def export_profiles(self):
        if not self.profiles:
            QMessageBox.information(
                self,
                self.tr('profiles_transfer_title'),
                self.tr('profiles_export_empty'),
            )
            return

        selection_dialog = ProfileSelectionDialog(
            self.profiles,
            self.tr,
            self,
        )
        self.apply_theme()
        if selection_dialog.exec() != QDialog.Accepted:
            return
        selected_profiles = selection_dialog.selected_profiles()
        if not selected_profiles:
            return
        timestamp = datetime.now().strftime("%d%m%y%H%M")
        filename = f"clicker-profiles-{timestamp}.json"
        self._export_profiles(selected_profiles, filename)

    def _export_profiles(self, profiles, filename):
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr('profiles_export'),
            filename,
            self.tr('profiles_file_filter'),
        )
        if not file_path:
            return

        payload = {
            "format": PROFILE_FILE_FORMAT,
            "schema_version": 1,
            "profiles": profiles,
        }
        try:
            with open(file_path, "w", encoding="utf-8") as profile_file:
                json.dump(payload, profile_file, ensure_ascii=False, indent=2)
        except (OSError, TypeError, ValueError) as error:
            QMessageBox.warning(
                self,
                self.tr('profiles_transfer_title'),
                self.tr('profiles_export_error').format(error),
            )
            return

        QMessageBox.information(
            self,
            self.tr('profiles_transfer_title'),
            self.tr('profiles_export_success'),
        )

    def _validate_imported_profile(self, profile):
        if not isinstance(profile, dict):
            raise ValueError(self.tr('profile_object_invalid'))

        name = profile.get("name")
        icon = profile.get("icon", "✨")
        mode = profile.get("mode")
        key = profile.get("key")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(self.tr('profile_name_required'))
        if not isinstance(icon, str):
            raise ValueError(self.tr('profile_icon_invalid', name))
        if not isinstance(key, str) or not key.strip():
            raise ValueError(self.tr('profile_key_required', name))

        supported_modes = {
            self.MODE_INSTANT,
            self.MODE_HOLD,
            self.MODE_SEQUENCE,
            self.MODE_COMBO,
            "Instant press",
            "Hold key",
            "Sequence press",
            "Instant combo",
            "Обычный клик",
            "Coordinate clicks",
            self.MODE_SCENARIO,
            "Recorded scenario",
        }
        for language in ("ru", "en"):
            supported_modes.update(
                self.translations[language][translation_key]
                for translation_key in (
                    "mode_instant",
                    "mode_hold",
                    "mode_sequence",
                    "mode_combo",
                    "mode_coordinates",
                    "mode_scenario",
                )
            )
        if not isinstance(mode, str) or mode not in supported_modes:
            raise ValueError(self.tr('profile_mode_unknown', name))
        coordinate_modes = {
            self.MODE_COORDINATES,
            "Coordinate clicks",
        }
        coordinate_modes.update(
            self.translations[language]["mode_coordinates"]
            for language in ("ru", "en")
        )
        is_coordinate_mode = mode in coordinate_modes

        def numeric_value(field, default=None):
            value = profile.get(field, default)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
            ):
                raise ValueError(self.tr('profile_value_invalid', field, name))
            try:
                normalized = float(value)
            except OverflowError as error:
                raise ValueError(
                    self.tr('profile_value_invalid', field, name)
                ) from error
            if not math.isfinite(normalized) or normalized < 0:
                raise ValueError(self.tr('profile_value_invalid', field, name))
            return normalized

        minimum = numeric_value("min")
        maximum = numeric_value("max")
        hold = numeric_value("hold", 1.0)
        between = numeric_value("between", 0.2)
        random_interval = profile.get("random", True)
        sequence = profile.get("sequence", "")
        coordinates = profile.get("coordinates", [])
        coordinate_smooth = profile.get("coordinate_smooth", False)
        coordinate_move_duration = numeric_value(
            "coordinate_move_duration",
            0.3,
        )
        coordinate_random_move_duration = profile.get(
            "coordinate_random_move_duration",
            False,
        )
        coordinate_move_duration_max = numeric_value(
            "coordinate_move_duration_max",
            max(0.5, coordinate_move_duration),
        )
        coordinate_cycle_interval = numeric_value(
            "coordinate_cycle_interval",
            0.5,
        )
        coordinate_cycle_interval_max = numeric_value(
            "coordinate_cycle_interval_max",
            max(1.0, coordinate_cycle_interval),
        )
        coordinate_random_cycle_interval = profile.get(
            "coordinate_random_cycle_interval",
            False,
        )
        coordinate_random_click_interval = profile.get(
            "coordinate_random_click_interval",
            random_interval,
        )
        if coordinate_move_duration > 999999999:
            raise ValueError(
                self.tr(
                    'profile_value_invalid',
                    "coordinate_move_duration",
                    name,
                )
            )
        if coordinate_cycle_interval > 999999999:
            raise ValueError(
                self.tr(
                    'profile_value_invalid',
                    "coordinate_cycle_interval",
                    name,
                )
            )
        if coordinate_cycle_interval_max > 999999999:
            raise ValueError(
                self.tr(
                    'profile_value_invalid',
                    "coordinate_cycle_interval_max",
                    name,
                )
            )
        if coordinate_move_duration_max > 999999999:
            raise ValueError(
                self.tr(
                    'profile_value_invalid',
                    "coordinate_move_duration_max",
                    name,
                )
            )
        if not isinstance(random_interval, bool):
            raise ValueError(self.tr('profile_random_invalid', name))
        if not isinstance(coordinate_smooth, bool):
            raise ValueError(
                self.tr('profile_coordinate_smooth_invalid', name)
            )
        if not isinstance(coordinate_random_move_duration, bool):
            raise ValueError(
                self.tr('profile_coordinate_smooth_invalid', name)
            )
        if (
            not isinstance(coordinate_random_cycle_interval, bool)
            or not isinstance(coordinate_random_click_interval, bool)
        ):
            raise ValueError(
                self.tr('profile_random_invalid', name)
            )
        if (
            coordinate_random_cycle_interval
            and coordinate_cycle_interval > coordinate_cycle_interval_max
        ):
            raise ValueError(
                self.tr(
                    'profile_value_invalid',
                    "coordinate_cycle_interval_max",
                    name,
                )
            )
        if (
            is_coordinate_mode
            and not coordinate_smooth
            and coordinate_random_click_interval
            and minimum > maximum
        ):
            raise ValueError(
                self.tr(
                    'profile_value_invalid',
                    "max",
                    name,
                )
            )
        if not isinstance(sequence, str):
            raise ValueError(self.tr('profile_sequence_invalid', name))
        if not isinstance(coordinates, list):
            raise ValueError(self.tr('profile_coordinates_invalid', name))
        normalized_coordinates = []
        swipe_buttons = {"left", "right", "middle", "x1", "x2"}

        def normalize_coordinate_point(point):
            if not isinstance(point, dict):
                raise ValueError(self.tr('profile_coordinates_invalid', name))
            screen = point.get("screen")
            x = point.get("x")
            y = point.get("y")
            if isinstance(x, bool) or isinstance(y, bool):
                raise ValueError(self.tr('profile_coordinates_invalid', name))
            try:
                x = float(x)
                y = float(y)
            except (TypeError, ValueError, OverflowError) as error:
                raise ValueError(
                    self.tr('profile_coordinates_invalid', name)
                ) from error
            if (
                not isinstance(screen, str)
                or not screen.strip()
                or not math.isfinite(x)
                or not math.isfinite(y)
                or not 0 <= x <= 1
                or not 0 <= y <= 1
            ):
                raise ValueError(self.tr('profile_coordinates_invalid', name))
            return {
                "screen": screen.strip(),
                "x": float(x),
                "y": float(y),
            }

        for action in coordinates:
            if not isinstance(action, dict):
                raise ValueError(self.tr('profile_coordinates_invalid', name))
            action_type = action.get("type")
            if action_type == "swipe":
                button = action.get("button")
                path = action.get("points")
                if (
                    not isinstance(button, str)
                    or button not in swipe_buttons
                    or not isinstance(path, list)
                    or len(path) < 2
                ):
                    raise ValueError(
                        self.tr('profile_coordinates_invalid', name)
                    )
                normalized_coordinates.append({
                    "type": "swipe",
                    "button": button,
                    "points": [
                        normalize_coordinate_point(point)
                        for point in path
                    ],
                })
            elif action_type in (None, "click"):
                point = action.get("point", action)
                normalized_coordinates.append(
                    normalize_coordinate_point(point)
                )
            else:
                raise ValueError(self.tr('profile_coordinates_invalid', name))

        scenario_actions = profile.get("scenario", [])
        if (
            not isinstance(scenario_actions, list)
            or len(scenario_actions) > MAX_SCENARIO_ACTIONS
        ):
            raise ValueError(self.tr("profile_scenario_invalid", name))
        normalized_scenario = []
        scenario_types = {
            "key_press",
            "key_release",
            "mouse_press",
            "mouse_release",
            "mouse_move",
            "scroll",
        }
        reserved_inputs = (
            set(self.start_hotkey)
            | set(self.stop_hotkey)
            | {self.emergency_stop_key}
        )

        def scenario_coordinate(value):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or int(value) != value
                or not -100000 <= value <= 100000
            ):
                raise ValueError(
                    self.tr("profile_scenario_invalid", name)
                )
            return int(value)

        for action in scenario_actions:
            if not isinstance(action, dict):
                raise ValueError(self.tr("profile_scenario_invalid", name))
            action_type = action.get("type")
            delay = action.get("delay")
            if (
                action_type not in scenario_types
                or isinstance(delay, bool)
                or not isinstance(delay, (int, float))
                or not math.isfinite(delay)
                or delay < 0
            ):
                raise ValueError(self.tr("profile_scenario_invalid", name))
            normalized_action = {
                "type": action_type,
                "delay": float(delay),
            }
            if action_type in ("key_press", "key_release"):
                key = action.get("key")
                if not isinstance(key, str) or not key.strip():
                    raise ValueError(
                        self.tr("profile_scenario_invalid", name)
                    )
                key = self._normalize_key_name(key)
                parsed_key = self.parse_key_token(key)
                if (
                    parsed_key is None
                    or isinstance(parsed_key, mouse.Button)
                    or key in reserved_inputs
                ):
                    raise ValueError(
                        self.tr("profile_scenario_invalid", name)
                    )
                normalized_action["key"] = key
            if action_type in ("mouse_press", "mouse_release"):
                button = action.get("button")
                if not isinstance(button, str):
                    raise ValueError(
                        self.tr("profile_scenario_invalid", name)
                    )
                parsed_button = self.parse_key_token(button)
                if (
                    not isinstance(parsed_button, mouse.Button)
                    or self._button_to_str(parsed_button) in reserved_inputs
                ):
                    raise ValueError(
                        self.tr("profile_scenario_invalid", name)
                    )
                normalized_action["button"] = self._button_to_str(
                    parsed_button
                )
            if action_type in (
                "mouse_press",
                "mouse_release",
                "mouse_move",
                "scroll",
            ):
                normalized_action["x"] = scenario_coordinate(action.get("x"))
                normalized_action["y"] = scenario_coordinate(action.get("y"))
            if action_type == "scroll":
                normalized_action["dx"] = scenario_coordinate(
                    action.get("dx")
                )
                normalized_action["dy"] = scenario_coordinate(
                    action.get("dy")
                )
                if (
                    normalized_action["dx"] == 0
                    and normalized_action["dy"] == 0
                ):
                    raise ValueError(
                        self.tr("profile_scenario_invalid", name)
                    )
            normalized_scenario.append(normalized_action)

        uses_coordinate_movement = (
            is_coordinate_mode
            and (
                coordinate_smooth
                or has_coordinate_swipe(normalized_coordinates)
            )
        )
        if (
            uses_coordinate_movement
            and coordinate_random_move_duration
            and coordinate_move_duration > coordinate_move_duration_max
        ):
            raise ValueError(
                self.tr(
                    'profile_value_invalid',
                    "coordinate_move_duration_max",
                    name,
                )
            )

        return {
            "icon": icon,
            "name": name.strip(),
            "mode": mode,
            "min": minimum,
            "max": maximum,
            "hold": hold,
            "between": between,
            "key": key.strip(),
            "sequence": sequence,
            "coordinates": normalized_coordinates,
            "scenario": normalized_scenario,
            "coordinate_smooth": coordinate_smooth,
            "coordinate_move_duration": coordinate_move_duration,
            "coordinate_random_move_duration": (
                coordinate_random_move_duration
            ),
            "coordinate_move_duration_max": coordinate_move_duration_max,
            "coordinate_cycle_interval": coordinate_cycle_interval,
            "coordinate_cycle_interval_max": coordinate_cycle_interval_max,
            "coordinate_random_cycle_interval": (
                coordinate_random_cycle_interval
            ),
            "coordinate_random_click_interval": (
                coordinate_random_click_interval
            ),
            "random": (
                coordinate_random_click_interval
                and minimum != maximum
            ),
        }

    def _normalize_scenario_actions(self, actions):
        return self._validate_imported_profile({
            "name": "Standalone scenario",
            "icon": "🎬",
            "key": "SPACE",
            "mode": self.MODE_SCENARIO,
            "min": 0.0,
            "max": 0.0,
            "scenario": actions,
        })["scenario"]

    def _format_import_profile_details(self, profile):
        mode_keys = {
            self.MODE_INSTANT: 'mode_instant',
            self.MODE_HOLD: 'mode_hold',
            self.MODE_SEQUENCE: 'mode_sequence',
            self.MODE_COMBO: 'mode_combo',
            self.MODE_COORDINATES: 'mode_coordinates',
            self.MODE_SCENARIO: 'mode_scenario',
        }
        mode_key = mode_keys.get(profile["mode"])
        if mode_key is None:
            for translation_key in mode_keys.values():
                if any(
                    profile["mode"] == self.translations[language][translation_key]
                    for language in ("ru", "en")
                ):
                    mode_key = translation_key
                    break
        mode = self.tr(mode_key) if mode_key else profile["mode"]
        minimum = profile["min"]
        maximum = profile["max"]
        interval = format_interval_value(minimum)
        if profile.get("random", True) and minimum != maximum:
            interval = (
                f'{interval} — {format_interval_value(maximum)}'
            )
        return self.tr('profiles_import_profile_details').format(
            self.display_key_token(profile["key"]),
            mode,
            interval,
        )

    def import_profiles(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr('profiles_import'),
            "",
            self.tr('profiles_file_filter'),
        )
        if not file_path:
            return

        try:
            profile_path = Path(file_path)
            if profile_path.stat().st_size > MAX_PROFILE_FILE_SIZE:
                raise ValueError(self.tr('profile_file_too_large'))
            raw_data = profile_path.read_bytes()
            if len(raw_data) > MAX_PROFILE_FILE_SIZE:
                raise ValueError(self.tr('profile_file_too_large'))
            payload = json.loads(raw_data.decode("utf-8"))
            if isinstance(payload, dict):
                if payload.get("format") != PROFILE_FILE_FORMAT:
                    raise ValueError(self.tr('profile_file_format_invalid'))
                if payload.get("schema_version") != 1:
                    raise ValueError(self.tr('profile_file_schema_invalid'))
                imported_profiles = payload.get("profiles")
            else:
                imported_profiles = payload
            if not isinstance(imported_profiles, list):
                raise ValueError(self.tr('profile_file_list_invalid'))
            profiles_to_import = [
                self._validate_imported_profile(profile)
                for profile in imported_profiles
            ]
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            QMessageBox.warning(
                self,
                self.tr('profiles_transfer_title'),
                self.tr('profiles_import_error').format(error),
            )
            return

        if len(profiles_to_import) >= 5:
            selection_dialog = ProfileSelectionDialog(
                profiles_to_import,
                self.tr,
                self,
                title_key='profiles_import',
                description=self.tr(
                    'profiles_import_confirm_many',
                    len(profiles_to_import),
                ),
                profile_details=self._format_import_profile_details,
            )
            self.apply_theme()
            if selection_dialog.exec() != QDialog.Accepted:
                return
            profiles_to_import = selection_dialog.selected_profiles()
            if not profiles_to_import:
                return

        existing_names = {
            profile.get("name", "").strip().casefold()
            for profile in self.profiles
            if isinstance(profile.get("name"), str)
        }
        updated_profiles = list(self.profiles)
        renamed = 0
        for profile in profiles_to_import:
            normalized_name = profile["name"].casefold()
            if normalized_name in existing_names:
                original_name = profile["name"]
                suffix_number = 2
                while True:
                    suffix = self.tr(
                        'profile_import_copy_suffix',
                        suffix_number,
                    )
                    candidate_name = f"{original_name}{suffix}"
                    normalized_candidate = candidate_name.casefold()
                    if normalized_candidate not in existing_names:
                        profile["name"] = candidate_name
                        normalized_name = normalized_candidate
                        renamed += 1
                        break
                    suffix_number += 1
            existing_names.add(normalized_name)
            updated_profiles.append(profile)

        added = len(updated_profiles) - len(self.profiles)
        if added:
            if not self._write_profiles(updated_profiles):
                QMessageBox.warning(
                    self,
                    self.tr('profiles_transfer_title'),
                    self.tr('profiles_import_save_error'),
                )
                return
            self.profiles = updated_profiles
            self.refresh_profiles()

        if added:
            message = self.tr('profiles_import_success').format(added, renamed)
        else:
            message = self.tr('profiles_import_empty')
        QMessageBox.information(
            self,
            self.tr('profiles_transfer_title'),
            message,
        )

    def build_settings_dialog(self):
        self.settings_dialog = QDialog(self)
        self.settings_dialog.setWindowTitle(self.tr('settings_title'))
        self.settings_dialog.setMinimumWidth(700)
        layout = QVBoxLayout(self.settings_dialog)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        columns_layout = QHBoxLayout()
        columns_layout.setSpacing(16)
        left_column = QVBoxLayout()
        right_column = QVBoxLayout()
        left_column.setSpacing(10)
        right_column.setSpacing(10)
        columns_layout.addLayout(left_column, 1)
        columns_layout.addLayout(right_column, 1)
        layout.addLayout(columns_layout, 1)

        def add_section(column, title_key, attribute):
            section = QVBoxLayout()
            section.setSpacing(4)
            title = QLabel(self.tr(title_key))
            title.setObjectName("section")
            setattr(self, attribute, title)
            section.addWidget(title)
            column.addLayout(section)
            return section

        general_section = add_section(
            left_column,
            'settings_general_section',
            'settings_general_title_label',
        )
        language_layout = QHBoxLayout()
        language_layout.setSpacing(6)
        self.lang_label = QLabel(self.tr('language'))
        self.lang_combo = QComboBox()
        self.lang_combo.addItems([self.tr('lang_ru'), self.tr('lang_en')])
        self.lang_combo.currentIndexChanged.connect(self.on_language_changed)
        language_layout.addWidget(self.lang_label, 1)
        language_layout.addWidget(self.lang_combo, 1)
        general_section.addLayout(language_layout)

        theme_layout = QHBoxLayout()
        theme_layout.setSpacing(6)
        self.settings_theme_label = QLabel(self.tr('settings_theme'))
        self.settings_theme_label.setObjectName("section")
        self.theme_combo = QComboBox()
        self.theme_combo.addItem(self.tr('theme_dark'), "dark")
        self.theme_combo.addItem(self.tr('theme_ocean'), "ocean")
        self.theme_combo.addItem(self.tr('theme_purple'), "purple")
        self.theme_combo.addItem(self.tr('theme_forest'), "forest")
        self.theme_combo.addItem(self.tr('theme_sunset'), "sunset")
        self.theme_combo.addItem(self.tr('theme_gray'), "gray")
        self.theme_combo.addItem(self.tr('theme_blue'), "blue")
        self.theme_combo.addItem(self.tr('theme_red'), "red")
        self.theme_combo.addItem(self.tr('theme_pink'), "pink")
        self.theme_combo.currentIndexChanged.connect(self.on_theme_changed)
        theme_layout.addWidget(self.settings_theme_label, 1)
        theme_layout.addWidget(self.theme_combo, 1)
        general_section.addLayout(theme_layout)

        learning_section = add_section(
            left_column,
            "settings_learning_section",
            "settings_learning_title_label",
        )
        self.mode_tutorial_description_label = QLabel(
            self.tr("mode_tutorial_settings_description")
        )
        self.mode_tutorial_description_label.setWordWrap(True)
        learning_section.addWidget(self.mode_tutorial_description_label)
        self.mode_tutorial_button = QPushButton(
            self.tr("mode_tutorial_open_button")
        )
        self.mode_tutorial_button.setObjectName("blue")
        self.mode_tutorial_button.clicked.connect(
            self.open_mode_tutorial_from_settings
        )
        learning_section.addWidget(self.mode_tutorial_button)

        emergency_section = add_section(
            left_column,
            'emergency_stop_title',
            'emergency_stop_title_label',
        )
        self.emergency_stop_warning_label = QLabel(
            self.tr('emergency_stop_warning')
        )
        self.emergency_stop_warning_label.setWordWrap(True)
        self.emergency_stop_warning_label.setSizePolicy(
            QSizePolicy.Ignored,
            QSizePolicy.Preferred,
        )
        self.emergency_stop_warning_label.setStyleSheet(
            "color: #ffd35c; font-size: 12px;"
        )
        emergency_section.addWidget(self.emergency_stop_warning_label)
        emergency_stop_layout = QHBoxLayout()
        emergency_stop_layout.setSpacing(6)
        self.emergency_stop_key_edit = QLineEdit(self.emergency_stop_key)
        self.emergency_stop_key_edit.setReadOnly(True)
        self.emergency_stop_assign_button = QPushButton(
            self.tr('emergency_stop_assign')
        )
        self.emergency_stop_assign_button.clicked.connect(
            self.bind_emergency_stop_key
        )
        emergency_stop_layout.addWidget(self.emergency_stop_key_edit, 1)
        emergency_stop_layout.addWidget(self.emergency_stop_assign_button)
        emergency_section.addLayout(emergency_stop_layout)

        profile_section = add_section(
            right_column,
            'profiles_transfer_title',
            'profiles_transfer_title_label',
        )
        self.profiles_manage_button = QPushButton(
            self.tr('profiles_manage_button')
        )
        self.profiles_manage_button.setObjectName("blue")
        self.profiles_manage_button.clicked.connect(self.manage_profiles)
        profile_section.addWidget(self.profiles_manage_button)
        profile_transfer_layout = QHBoxLayout()
        profile_transfer_layout.setSpacing(6)
        self.profiles_export_button = QPushButton(
            self.tr('profiles_export')
        )
        self.profiles_export_button.clicked.connect(self.export_profiles)
        self.profiles_import_button = QPushButton(
            self.tr('profiles_import')
        )
        self.profiles_import_button.clicked.connect(self.import_profiles)
        profile_transfer_layout.addWidget(self.profiles_export_button)
        profile_transfer_layout.addWidget(self.profiles_import_button)
        profile_section.addLayout(profile_transfer_layout)

        updates_section = add_section(
            right_column,
            'settings_updates_section',
            'settings_updates_title_label',
        )
        self.update_check_button = QPushButton(self.tr('update_check_button'))
        self.update_check_button.clicked.connect(
            lambda: self.check_for_updates(manual=True)
        )
        updates_section.addWidget(self.update_check_button)

        feedback_section = add_section(
            right_column,
            'settings_bug_report_section',
            'settings_bug_report_title_label',
        )
        self.bug_report_button = QPushButton(self.tr('bug_report_button'))
        self.bug_report_button.setObjectName("blue")
        self.bug_report_button.clicked.connect(self.open_bug_report_form)
        feedback_section.addWidget(self.bug_report_button)
        self.settings_bug_report_description_label = QLabel(
            self.tr('settings_bug_report_description')
        )
        self.settings_bug_report_description_label.setWordWrap(True)
        self.settings_bug_report_description_label.setSizePolicy(
            QSizePolicy.Ignored,
            QSizePolicy.Preferred,
        )
        self.settings_bug_report_description_label.setStyleSheet(
            "color: #91a4ba; font-size: 12px;"
        )
        feedback_section.addWidget(self.settings_bug_report_description_label)

        left_column.addStretch(1)
        right_column.addStretch(1)

        self.settings_developer_label = QLabel(self.tr('settings_developer'))
        self.settings_developer_discord_label = QLabel(
            self.tr('settings_developer_discord')
        )
        self.settings_developer_discord_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse
        )
        self.settings_version_label = QLabel(
            self.tr('settings_version').format(APP_VERSION)
        )
        self.settings_version_label.setStyleSheet("color: #91a4ba;")

        buttons = QDialogButtonBox()
        self.settings_close_button = buttons.addButton(
            self.tr('dialog_close'),
            QDialogButtonBox.RejectRole,
        )
        self.settings_close_button.clicked.connect(self.settings_dialog.reject)
        footer_layout = QHBoxLayout()
        footer_layout.setSpacing(8)
        developer_info = QVBoxLayout()
        developer_info.setSpacing(0)
        developer_info.addWidget(self.settings_developer_label)
        developer_info.addWidget(self.settings_developer_discord_label)
        developer_info.addWidget(self.settings_version_label)
        footer_layout.addLayout(developer_info, 1)
        footer_layout.addWidget(buttons)
        layout.addLayout(footer_layout)
        self.settings_dialog.setMinimumHeight(400)
        self.settings_dialog.resize(700, 400)
        self.settings_dialog.setStyleSheet(
            """
            QDialog QPushButton {
                padding: 6px 10px;
                min-height: 22px;
            }
            QDialog QLineEdit, QDialog QComboBox { padding: 5px 8px; }
            QDialog QLabel#section { padding-top: 1px; }
            """
        )
        self.apply_theme()

    def create_settings_panel(self):
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        # ---- Режим работы ----
        self.section_mode = QLabel()
        self.section_mode.setObjectName("section")
        layout.addWidget(self.section_mode)

        self.mode = QComboBox()
        self.mode.setMinimumWidth(300)
        self.mode.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.mode.view().setMinimumWidth(300)
        self.mode.currentIndexChanged.connect(self.on_mode_changed)
        layout.addWidget(self.mode)
        self.scenario_mode_label = QLabel(
            self.tr("scenario_mode_hint")
        )
        self.scenario_mode_label.setWordWrap(True)
        self.scenario_mode_label.setStyleSheet("color: #91a4ba;")
        layout.addWidget(self.scenario_mode_label)
        self.main_scenario_controls = QWidget()
        main_scenario_layout = QVBoxLayout(self.main_scenario_controls)
        main_scenario_layout.setContentsMargins(0, 0, 0, 0)
        main_scenario_layout.setSpacing(8)
        scenario_action_buttons = QHBoxLayout()
        scenario_action_buttons.setSpacing(8)
        self.main_scenario_record_button = QPushButton()
        self.main_scenario_record_button.setObjectName("blue")
        self.main_scenario_record_button.clicked.connect(
            lambda: self.arm_scenario_recording(self)
        )
        self.main_scenario_edit_button = QPushButton()
        self.main_scenario_edit_button.clicked.connect(
            self.edit_main_scenario
        )
        scenario_action_buttons.addWidget(self.main_scenario_record_button)
        scenario_action_buttons.addWidget(self.main_scenario_edit_button)
        main_scenario_layout.addLayout(scenario_action_buttons)
        self.main_scenario_controls.hide()
        layout.addWidget(self.main_scenario_controls)
        self.main_scenario_summary = QLabel()
        self.main_scenario_summary.setWordWrap(True)
        self.main_scenario_summary.setStyleSheet("color: #91a4ba;")
        self.main_scenario_summary.hide()
        layout.addWidget(self.main_scenario_summary)

        # ---- Параметры ----
        self.section_params = QLabel()
        self.section_params.setObjectName("section")
        layout.addWidget(self.section_params)

        self.lbl_click_key = QLabel()
        layout.addWidget(self.lbl_click_key)

        hotkey_row = QHBoxLayout()
        self.hotkey_edit = QLineEdit("SPACE")
        self.hotkey_edit.setReadOnly(True)
        self.assign_btn = QPushButton()
        self.assign_btn.setObjectName("blue")
        self.assign_btn.setFocusPolicy(Qt.NoFocus)
        self.assign_btn.clicked.connect(self.bind_click_key)
        hotkey_row.addWidget(self.hotkey_edit)
        hotkey_row.addWidget(self.assign_btn)
        layout.addLayout(hotkey_row)

        # Сеточная разметка числовых полей
        grid = QGridLayout()
        grid.setSpacing(10)
        self.min_interval_edit = self._create_interval_edit(0.5)
        self.max_interval_edit = self._create_interval_edit(1.0)
        self.hold_time_edit = self._create_interval_edit(1.0)
        self.between_edit = self._create_interval_edit(0.2)
        for interval_edit in (
            self.min_interval_edit,
            self.max_interval_edit,
            self.hold_time_edit,
            self.between_edit,
        ):
            interval_edit.setMinimumWidth(0)
            interval_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.lbl_min_interval = QLabel()
        self.lbl_max_interval = QLabel()
        self.lbl_hold_time = QLabel()
        self.lbl_between = QLabel()

        grid.addWidget(self.lbl_min_interval, 0, 0)
        grid.addWidget(self.lbl_max_interval, 0, 1)
        grid.addWidget(self.min_interval_edit, 1, 0)
        grid.addWidget(self.max_interval_edit, 1, 1)
        grid.addWidget(self.lbl_between, 2, 0)
        grid.addWidget(self.lbl_hold_time, 2, 1)
        grid.addWidget(self.between_edit, 3, 0)
        grid.addWidget(self.hold_time_edit, 3, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.interval_grid = grid
        self.coordinate_random_click_interval_checkbox = CheckmarkCheckBox()
        self.coordinate_random_click_interval_checkbox.stateChanged.connect(
            self.update_random_interval_ui
        )
        self.coordinate_random_click_interval_checkbox.setVisible(False)
        layout.addLayout(grid)
        layout.addWidget(self.coordinate_random_click_interval_checkbox)

        self.sequence_label = QLabel()
        layout.addWidget(self.sequence_label)

        self.sequence_edit = QTextEdit()
        self.sequence_edit.setMinimumHeight(50)
        self.sequence_edit.setMaximumHeight(120)
        self.sequence_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.sequence_edit.installEventFilter(self)
        self.sequence_edit.textChanged.connect(self._adjust_sequence_height)
        layout.addWidget(self.sequence_edit)

        sequence_buttons = QHBoxLayout()
        self.sequence_assign_btn = QPushButton()
        self.sequence_assign_btn.setObjectName("blue")
        self.sequence_assign_btn.setCheckable(True)
        self.sequence_assign_btn.setFocusPolicy(Qt.NoFocus)
        self.sequence_assign_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.sequence_record_button_pressed = False
        self.sequence_assign_btn.clicked.connect(self.bind_sequence_input)
        self.sequence_clear_btn = QPushButton()
        self.sequence_clear_btn.setFocusPolicy(Qt.NoFocus)
        self.sequence_clear_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.sequence_clear_btn.clicked.connect(self.clear_sequence_input)
        self.sequence_apply_btn = QPushButton()
        self.sequence_apply_btn.setObjectName("green")
        self.sequence_apply_btn.setFocusPolicy(Qt.NoFocus)
        self.sequence_apply_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.sequence_apply_btn.clicked.connect(self.apply_sequence_input)
        sequence_buttons.addWidget(self.sequence_assign_btn, 2)
        sequence_buttons.addWidget(self.sequence_clear_btn, 1)
        sequence_buttons.addWidget(self.sequence_apply_btn, 1)
        layout.addLayout(sequence_buttons)

        self.coordinate_points_label = QLabel(
            self.tr('coordinate_points_empty')
        )
        self.coordinate_record_button = QPushButton(
            self.tr('coordinate_record_button')
        )
        self.coordinate_record_button.setObjectName("blue")
        self.coordinate_record_button.clicked.connect(
            self.record_current_coordinates
        )
        self.coordinate_clear_button = QPushButton(
            self.tr('button_clear')
        )
        self.coordinate_clear_button.clicked.connect(
            self.clear_coordinate_points
        )
        layout.addWidget(self.coordinate_points_label)
        coordinate_buttons = QHBoxLayout()
        coordinate_buttons.addWidget(self.coordinate_record_button)
        coordinate_buttons.addWidget(self.coordinate_clear_button)
        layout.addLayout(coordinate_buttons)

        self.coordinate_movement_group = QGroupBox()
        coordinate_movement_layout = QVBoxLayout(
            self.coordinate_movement_group
        )
        self.coordinate_smooth_checkbox = CheckmarkCheckBox()
        self.coordinate_smooth_checkbox.stateChanged.connect(
            self.update_coordinate_move_ui
        )
        coordinate_movement_layout.addWidget(
            self.coordinate_smooth_checkbox
        )
        self.coordinate_random_move_duration_checkbox = CheckmarkCheckBox()
        self.coordinate_random_move_duration_checkbox.stateChanged.connect(
            self.update_coordinate_move_ui
        )
        coordinate_movement_layout.addWidget(
            self.coordinate_random_move_duration_checkbox
        )
        coordinate_duration_row = QHBoxLayout()
        self.coordinate_move_duration_label = QLabel()
        self.coordinate_move_duration_edit = self._create_interval_edit(0.3)
        self.coordinate_move_duration_min_label = QLabel()
        self.coordinate_move_duration_min_edit = self._create_interval_edit(
            0.3
        )
        self.coordinate_move_duration_max_label = QLabel()
        self.coordinate_move_duration_max_edit = self._create_interval_edit(0.5)
        self.coordinate_cycle_interval_label = QLabel()
        self.coordinate_cycle_interval_edit = self._create_interval_edit(0.5)
        coordinate_duration_row.addWidget(
            self.coordinate_move_duration_label
        )
        coordinate_duration_row.addWidget(
            self.coordinate_move_duration_edit
        )
        coordinate_movement_layout.addLayout(coordinate_duration_row)
        coordinate_random_duration_row = QHBoxLayout()
        coordinate_random_duration_row.addWidget(
            self.coordinate_move_duration_min_label
        )
        coordinate_random_duration_row.addWidget(
            self.coordinate_move_duration_min_edit
        )
        coordinate_random_duration_row.addWidget(
            self.coordinate_move_duration_max_label
        )
        coordinate_random_duration_row.addWidget(
            self.coordinate_move_duration_max_edit
        )
        coordinate_movement_layout.addLayout(
            coordinate_random_duration_row
        )
        layout.addWidget(self.coordinate_movement_group)
        coordinate_cycle_row = QHBoxLayout()
        coordinate_cycle_row.addWidget(
            self.coordinate_cycle_interval_label
        )
        coordinate_cycle_row.addWidget(
            self.coordinate_cycle_interval_edit
        )
        layout.addLayout(coordinate_cycle_row)
        coordinate_cycle_max_row = QHBoxLayout()
        self.coordinate_cycle_interval_max_label = QLabel()
        self.coordinate_cycle_interval_max_edit = self._create_interval_edit(
            1.0
        )
        coordinate_cycle_max_row.addWidget(
            self.coordinate_cycle_interval_max_label
        )
        coordinate_cycle_max_row.addWidget(
            self.coordinate_cycle_interval_max_edit
        )
        layout.addLayout(coordinate_cycle_max_row)

        self.random_interval = CheckmarkCheckBox(
            self.tr('label_random_interval')
        )
        self.random_interval.setChecked(True)
        self.random_interval.stateChanged.connect(self.update_random_interval_ui)
        self.min_interval_edit.textChanged.connect(
            self.update_random_interval_ui
        )
        self.max_interval_edit.textChanged.connect(
            self.update_random_interval_ui
        )
        layout.addWidget(self.random_interval)

        self.scenario_run_limit_row = QHBoxLayout()
        self.scenario_run_limit_checkbox = CheckmarkCheckBox()
        self.scenario_run_limit_checkbox.toggled.connect(
            lambda enabled: self._on_limit_toggled(
                self.scenario_run_limit_edit,
                enabled,
            )
        )
        self.scenario_run_limit_edit = QLineEdit("1")
        self.scenario_run_limit_edit.setValidator(
            QIntValidator(1, 999999999, self.scenario_run_limit_edit)
        )
        self.scenario_run_limit_edit.setMaximumWidth(110)
        self.scenario_run_limit_edit.setEnabled(False)
        self.scenario_run_limit_edit.editingFinished.connect(self.save_settings)
        self.scenario_run_limit_suffix = QLabel()
        self.scenario_run_limit_row.addWidget(
            self.scenario_run_limit_checkbox
        )
        self.scenario_run_limit_row.addWidget(self.scenario_run_limit_edit)
        self.scenario_run_limit_row.addWidget(
            self.scenario_run_limit_suffix
        )
        self.scenario_run_limit_row.addStretch()
        layout.addLayout(self.scenario_run_limit_row)

        self.duration_limit_row = QHBoxLayout()
        self.duration_limit_checkbox = CheckmarkCheckBox()
        self.duration_limit_checkbox.toggled.connect(
            lambda enabled: self._on_limit_toggled(
                self.duration_limit_edit,
                enabled,
            )
        )
        self.duration_limit_edit = QLineEdit("30")
        self.duration_limit_edit.setValidator(
            QIntValidator(
                1,
                999999999,
                self.duration_limit_edit,
            )
        )
        self.duration_limit_edit.setMaximumWidth(110)
        self.duration_limit_edit.setEnabled(False)
        self.duration_limit_edit.editingFinished.connect(
            self.save_settings
        )
        self.duration_limit_suffix = QLabel()
        self.duration_limit_row.addWidget(self.duration_limit_checkbox)
        self.duration_limit_row.addWidget(self.duration_limit_edit)
        self.duration_limit_row.addWidget(self.duration_limit_suffix)
        self.duration_limit_row.addStretch()
        layout.addLayout(self.duration_limit_row)

        self.limits_hint_label = QLabel()
        self.limits_hint_label.setWordWrap(True)
        self.limits_hint_label.setStyleSheet(
            "color: #91a4ba; font-size: 12px;"
        )
        layout.addWidget(self.limits_hint_label)

        click_limit_row = QHBoxLayout()
        self.click_limit_checkbox = CheckmarkCheckBox()
        self.click_limit_checkbox.toggled.connect(
            self._on_click_limit_toggled
        )
        self.click_limit_checkbox.setText(
            self.tr('click_limit_enabled')
        )
        self.click_limit_edit = QLineEdit("100")
        self.click_limit_edit.setValidator(
            QIntValidator(1, 999999999, self.click_limit_edit)
        )
        self.click_limit_edit.setMaximumWidth(110)
        self.click_limit_edit.setEnabled(False)
        self.click_limit_edit.editingFinished.connect(self.save_settings)
        self.click_limit_suffix = QLabel(
            self.tr('click_limit_suffix')
        )
        click_limit_row.addWidget(self.click_limit_checkbox)
        click_limit_row.addWidget(self.click_limit_edit)
        click_limit_row.addWidget(self.click_limit_suffix)
        click_limit_row.addStretch()
        layout.addLayout(click_limit_row)

        # ---- Бинды горячих клавиш ----
        self.section_hk = QLabel()
        self.section_hk.setObjectName("section")
        layout.addWidget(self.section_hk)

        hk_grid = QGridLayout()
        self.lbl_hk_start = QLabel()
        self.lbl_hk_stop = QLabel()
        self.hk_start_edit = QLineEdit("F6")
        self.hk_start_edit.setReadOnly(True)
        self.hk_stop_edit = QLineEdit("F7")
        self.hk_stop_edit.setReadOnly(True)
        self.assign_hk_start = QPushButton()
        self.assign_hk_start.setObjectName("blue")
        self.assign_hk_start.setFocusPolicy(Qt.NoFocus)
        self.assign_hk_start.clicked.connect(self.bind_start_key)
        self.assign_hk_stop = QPushButton()
        self.assign_hk_stop.setObjectName("blue")
        self.assign_hk_stop.setFocusPolicy(Qt.NoFocus)
        self.assign_hk_stop.clicked.connect(self.bind_stop_key)

        hk_grid.addWidget(self.lbl_hk_start, 0, 0)
        hk_grid.addWidget(self.hk_start_edit, 0, 1)
        hk_grid.addWidget(self.assign_hk_start, 0, 2)
        hk_grid.addWidget(self.lbl_hk_stop, 1, 0)
        hk_grid.addWidget(self.hk_stop_edit, 1, 1)
        hk_grid.addWidget(self.assign_hk_stop, 1, 2)
        hk_grid.setColumnStretch(1, 1)
        layout.addLayout(hk_grid)

        hk_btns = QHBoxLayout()
        self.enable_hk_btn = QPushButton()
        self.enable_hk_btn.setObjectName("blue")
        self.enable_hk_btn.clicked.connect(self.enable_hotkeys)
        self.disable_hk_btn = QPushButton()
        self.disable_hk_btn.setObjectName("red")
        self.disable_hk_btn.clicked.connect(self.disable_hotkeys)
        hk_btns.addWidget(self.enable_hk_btn)
        hk_btns.addWidget(self.disable_hk_btn)
        layout.addLayout(hk_btns)

        self.info_label = QLabel()
        self.info_label.setStyleSheet("color: #91a4ba; font-size: 12px;")
        layout.addWidget(self.info_label)

        layout.addStretch()

        # ---- Кнопки управления ----
        actions = QVBoxLayout()
        actions.setSpacing(8)

        main_actions = QHBoxLayout()
        main_actions.setSpacing(10)

        self.start_btn = QPushButton()
        self.start_btn.setObjectName("green")
        self.start_btn.clicked.connect(self.start_clicker)

        self.stop_btn = QPushButton()
        self.stop_btn.setObjectName("red")
        self.stop_btn.clicked.connect(self.stop_clicker)

        main_actions.addWidget(self.start_btn)
        main_actions.addWidget(self.stop_btn)
        actions.addLayout(main_actions)

        layout.addLayout(actions)

        return panel

    @staticmethod
    def _create_interval_edit(value):
        edit = QLineEdit(str(max(0.0, float(value))))
        edit.setValidator(IntervalValidator(edit))
        return edit

    @staticmethod
    def _interval_value(edit):
        try:
            return max(0.0, float(edit.text().replace(",", ".")))
        except ValueError:
            return 0.0

    def create_profiles_panel(self):
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        header = QHBoxLayout()
        self.profiles_title_label = QLabel(self.tr('profiles_title'))
        self.profiles_title_label.setObjectName("section")
        self.profiles_search_button = QPushButton("🔍")
        self.profiles_search_button.setFixedSize(44, 44)
        self.profiles_search_button.setStyleSheet("padding: 0px;")
        self.profiles_search_button.setFont(QFont("Segoe UI Emoji", 14))
        self.profiles_search_button.setToolTip(
            self.tr('profiles_search_tooltip')
        )
        self.profiles_search_button.clicked.connect(
            self.toggle_profile_search
        )
        self.add_profile_btn = QPushButton(self.tr('add_profile'))
        self.add_profile_btn.setObjectName("blue")
        self.add_profile_btn.clicked.connect(self.add_profile)
        header.addWidget(self.profiles_title_label)
        header.addWidget(self.profiles_search_button)
        header.addStretch()
        header.addWidget(self.add_profile_btn)
        layout.addLayout(header)

        self.profiles_search_edit = QLineEdit()
        self.profiles_search_edit.setPlaceholderText(
            self.tr('profiles_search_placeholder')
        )
        self.profiles_search_edit.textChanged.connect(self.filter_profiles)
        self.profiles_search_edit.hide()
        layout.addWidget(self.profiles_search_edit)

        self.profiles_search_empty_label = QLabel(
            self.tr('profiles_search_empty')
        )
        self.profiles_search_empty_label.setAlignment(Qt.AlignCenter)
        self.profiles_search_empty_label.setStyleSheet(
            "color: #91a4ba; padding: 8px;"
        )
        self.profiles_search_empty_label.hide()
        layout.addWidget(self.profiles_search_empty_label)

        self.profiles_empty_widget = QWidget()
        empty_layout = QVBoxLayout(self.profiles_empty_widget)
        empty_layout.addStretch()
        empty_icon = QLabel("🗂️")
        empty_icon.setAlignment(Qt.AlignCenter)
        empty_icon.setFont(QFont("Segoe UI Emoji", 30))
        empty_layout.addWidget(empty_icon)
        self.profiles_empty_title_label = QLabel(
            self.tr('profiles_empty_title')
        )
        self.profiles_empty_title_label.setObjectName("section")
        self.profiles_empty_title_label.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(self.profiles_empty_title_label)
        self.profiles_empty_description_label = QLabel(
            self.tr('profiles_empty_description')
        )
        self.profiles_empty_description_label.setAlignment(Qt.AlignCenter)
        self.profiles_empty_description_label.setWordWrap(True)
        self.profiles_empty_description_label.setStyleSheet(
            "color: #91a4ba; padding: 0 16px;"
        )
        empty_layout.addWidget(self.profiles_empty_description_label)
        empty_layout.addStretch()
        self.profiles_empty_widget.hide()
        layout.addWidget(self.profiles_empty_widget, 1)

        self.profile_scroll = QScrollArea()
        self.profile_scroll.setWidgetResizable(True)
        self.profile_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.profile_scroll.setFrameShape(QFrame.NoFrame)
        self.profile_scroll.viewport().setStyleSheet("background: #0b1725;")
        profile_content = QWidget()
        profile_content.setStyleSheet("background: #0b1725;")
        self.profile_container = QVBoxLayout(profile_content)
        self.profile_container.setSpacing(10)
        self.profile_container.setContentsMargins(0, 0, 0, 0)
        self.profile_container.addStretch()
        self.profile_scroll.setWidget(profile_content)
        layout.addWidget(self.profile_scroll, 1)

        self.refresh_profiles()
        return panel

    # ==========================================================
    # НОРМАЛИЗАЦИЯ КЛАВИШ В СТРОКИ (взято из tkinter)
    # ==========================================================
    def _key_to_str(self, key):
        if isinstance(key, str):
            return self._normalize_key_name(key)
        virtual_key = getattr(key, "vk", None)
        if virtual_key is not None:
            if 0x41 <= virtual_key <= 0x5A:
                return chr(virtual_key)
            if 0x30 <= virtual_key <= 0x39:
                return chr(virtual_key)
        if hasattr(key, 'char') and key.char is not None:
            char = key.char
            if len(char) == 1 and 1 <= ord(char) <= 26:
                return chr(ord(char) + ord("A") - 1)
            return char.upper()
        try:
            name = str(key).replace("Key.", "").upper()
            name = self._normalize_key_name(name)
            if name.startswith("F") and name[1:].isdigit():
                return name
            return name
        except Exception:
            return str(key)

    @staticmethod
    def _normalize_key_name(name):
        aliases = {
            "CONTROL": "CTRL", "CTRL_L": "CTRL", "CTRL_R": "CTRL",
            "SHIFT_L": "SHIFT", "SHIFT_R": "SHIFT",
            "ALT_L": "ALT", "ALT_R": "ALT",
            "CMD": "WIN", "CMD_L": "WIN", "CMD_R": "WIN",
        }
        normalized = str(name).replace("Key.", "").strip().upper()
        return aliases.get(normalized, normalized)

    def _button_to_str(self, button):
        if button == mouse.Button.left:
            return "LMB"
        elif button == mouse.Button.right:
            return "RMB"
        elif button == mouse.Button.middle:
            return "MMB"
        elif button == mouse.Button.x1:
            return "X1"
        elif button == mouse.Button.x2:
            return "X2"
        return str(button).upper()

    def display_key_token(self, token):
        if isinstance(token, str) and "+" in token:
            return "+".join(
                self._normalize_key_name(part)
                for part in token.split("+")
                if part.strip()
            )
        parsed = self.parse_key_token(token)
        if parsed is None:
            return token
        if isinstance(parsed, mouse.Button):
            return self.mouse_to_string(parsed)
        return self.key_to_string(parsed)

    def profile_key_to_storage(self, token):
        parsed = self.parse_key_token(token)
        if isinstance(parsed, mouse.Button):
            return self._button_to_str(parsed)
        if parsed is not None:
            return self._key_to_str(parsed)
        return token

    def _normalize_key_to_str(self, key_or_button):
        if isinstance(key_or_button, mouse.Button):
            return self._button_to_str(key_or_button)
        else:
            return self._key_to_str(key_or_button)

    def _cursor_over_widget(self, widget):
        global_top_left = widget.mapToGlobal(widget.rect().topLeft())
        return widget.rect().translated(global_top_left).contains(QCursor.pos())

    # ==========================================================
    # ОБРАБОТЧИКИ НАЖАТИЙ И СЛУШАТЕЛИ PYNPUT (исправлены)
    # ==========================================================
    def on_key_press(self, key):
        if self.coordinate_recording_active:
            return
        key_token = self._normalize_key_to_str(key)
        with self.hotkey_lock:
            if self.waiting_for_emergency_key:
                previous_key = self.emergency_stop_key
                self.emergency_stop_key = key_token
                self.waiting_for_emergency_key = False
                self.emergency_stop_key_signal.emit(key_token)
                self.settings_save_signal.emit()
                captured_emergency_key = True
                emergency_stop_pressed = key_token == previous_key
            else:
                captured_emergency_key = False
                emergency_stop_pressed = key_token == self.emergency_stop_key

        if emergency_stop_pressed:
            with self.hotkey_lock:
                self.waiting_for_click_key = False
                self.waiting_for_start_key = False
                self.waiting_for_stop_key = False
                self.binding_capture_keys.clear()
            if self.sequence_input_active or self.waiting_for_sequence_input:
                self._stop_sequence_recording()
            if self.scenario_record_state == "recording":
                self._finish_scenario_recording()
            elif self.scenario_record_state == "armed":
                self._cancel_scenario_recording()
            self._signal_worker_stop()
            self.stop_request_signal.emit()
            return
        if captured_emergency_key:
            return

        if key_token == "ESC":
            with self.hotkey_lock:
                self.waiting_for_click_key = False
                self.waiting_for_start_key = False
                self.waiting_for_stop_key = False
                self.binding_capture_keys.clear()
            return

        # Не запускаем бинды от синтетических событий, но продолжаем их отслеживать.
        with self._sim_lock:
            simulating = self._simulating

        with self.hotkey_lock:
            if (
                not simulating
                and self.scenario_record_state in ("armed", "recording")
            ):
                token = self._normalize_key_to_str(key)
                self.pressed_keys.add(token)
                reserved = self.start_hotkey.union(self.stop_hotkey)
                if self.scenario_record_state == "armed":
                    if self._hotkey_matches(self.start_hotkey):
                        self.hotkey_fired.add("start")
                        self._begin_scenario_recording()
                    elif self._hotkey_matches(self.stop_hotkey):
                        self.hotkey_fired.add("stop")
                        self._cancel_scenario_recording()
                elif self._hotkey_matches(self.stop_hotkey):
                    self.hotkey_fired.add("stop")
                    self._finish_scenario_recording()
                elif token not in reserved:
                    self._record_scenario_event({
                        "type": "key_press",
                        "key": token,
                    })
                return

            if self.profile_dialog and self.profile_dialog.binding_recording:
                self.profile_dialog.capture_key(key)
                return

            if self.waiting_for_click_key:
                self.click_key = key
                self.click_key_type = "keyboard"
                self.waiting_for_click_key = False
                self.hotkey_label_signal.emit(self.get_binding_name(key, "keyboard"))
                self.settings_save_signal.emit()
                return

            if self.sequence_input_active:
                self._record_sequence_token(self._normalize_key_to_str(key))
                return

            if self.waiting_for_sequence_input:
                token = self._normalize_key_to_str(key)
                if self.current_mode == self.MODE_COMBO:
                    if token not in self.sequence_recording_down:
                        self.sequence_recording_down.add(token)
                        if token not in self.sequence_recording_keys:
                            self.sequence_recording_keys.append(token)
                        self.sequence_input_signal.emit(
                            "+".join(self.sequence_recording_keys)
                        )
                elif token not in self.sequence_recording_down:
                    self.sequence_recording_down.add(token)
                    self.sequence_input_signal.emit(token)
                return

            # Обработка захвата горячих клавиш
            if self.waiting_for_start_key or self.waiting_for_stop_key:
                self.binding_capture_keys.add(self._normalize_key_to_str(key))
                return

            # Добавляем нажатую клавишу в множество (строкой)
            self.pressed_keys.add(self._normalize_key_to_str(key))

            if not self.hotkeys_enabled:
                return

            if self._hotkey_matches(self.stop_hotkey):
                if "stop" not in self.hotkey_fired:
                    self.hotkey_fired.add("stop")
                    self._signal_worker_stop()
                    self.stop_clicker_safe()
            elif not simulating and self._hotkey_matches(self.start_hotkey):
                if "start" not in self.hotkey_fired:
                    self.hotkey_fired.add("start")
                    self.start_clicker_safe()

    def on_key_release(self, key):
        if self.coordinate_recording_active:
            return
        with self.hotkey_lock:
            token = self._normalize_key_to_str(key)
            if self.scenario_record_state in ("armed", "recording"):
                self.pressed_keys.discard(token)
                if (
                    self.scenario_record_state == "recording"
                    and token not in self.start_hotkey.union(self.stop_hotkey)
                ):
                    self._record_scenario_event({
                        "type": "key_release",
                        "key": token,
                    })
                if not self.pressed_keys or self.pressed_keys.isdisjoint(
                    self.start_hotkey.union(self.stop_hotkey)
                ):
                    self.hotkey_fired.clear()
                return

            if self.waiting_for_sequence_input:
                self.sequence_recording_down.discard(
                    token
                )
                return

            if self.waiting_for_start_key or self.waiting_for_stop_key:
                target = "start" if self.waiting_for_start_key else "stop"
                self._finish_hotkey_capture(target)
                return

            self.pressed_keys.discard(token)

            # Сброс флага hotkey_fired, чтобы можно было заново нажать
            if not self.pressed_keys or self.pressed_keys.isdisjoint(
                self.start_hotkey.union(self.stop_hotkey)
            ):
                self.hotkey_fired.clear()

    def on_mouse_click(self, x, y, button, pressed):
        if self.coordinate_recording_active:
            return
        with self._sim_lock:
            simulating = self._simulating
        if simulating:
            token = self._normalize_key_to_str(button)
            with self.hotkey_lock:
                if pressed:
                    self.pressed_keys.add(token)
                    if self.hotkeys_enabled and self._hotkey_matches(self.stop_hotkey):
                        if "stop" not in self.hotkey_fired:
                            self.hotkey_fired.add("stop")
                            self._signal_worker_stop()
                            self.stop_clicker_safe()
                else:
                    self.pressed_keys.discard(token)
                    if not self.pressed_keys or self.pressed_keys.isdisjoint(
                        self.start_hotkey.union(self.stop_hotkey)
                    ):
                        self.hotkey_fired.clear()
            return

        with self.hotkey_lock:
            token = self._normalize_key_to_str(button)
            if self.scenario_record_state in ("armed", "recording"):
                if pressed:
                    self.pressed_keys.add(token)
                else:
                    self.pressed_keys.discard(token)
                reserved = self.start_hotkey.union(self.stop_hotkey)
                if self.scenario_record_state == "armed" and pressed:
                    if self._hotkey_matches(self.start_hotkey):
                        self.hotkey_fired.add("start")
                        self._begin_scenario_recording()
                    elif self._hotkey_matches(self.stop_hotkey):
                        self.hotkey_fired.add("stop")
                        self._cancel_scenario_recording()
                elif self.scenario_record_state == "recording":
                    if pressed and self._hotkey_matches(self.stop_hotkey):
                        self.hotkey_fired.add("stop")
                        self._finish_scenario_recording()
                    elif token not in reserved:
                        self._record_scenario_event({
                            "type": (
                                "mouse_press" if pressed else "mouse_release"
                            ),
                            "button": token,
                            "x": int(x),
                            "y": int(y),
                        })
                if not pressed and (
                    not self.pressed_keys
                    or self.pressed_keys.isdisjoint(reserved)
                ):
                    self.hotkey_fired.clear()
                return

            if self.profile_dialog and self.profile_dialog.binding_recording:
                if self._cursor_over_widget(self.profile_dialog.key_assign_btn):
                    return
                if pressed:
                    self.profile_dialog.capture_mouse(button)
                return

            if self.waiting_for_click_key and pressed:
                self.click_key = button
                self.click_key_type = "mouse"
                self.waiting_for_click_key = False
                self.hotkey_label_signal.emit(self.get_binding_name(button, "mouse"))
                self.settings_save_signal.emit()
                return

            if button == mouse.Button.left and self._cursor_over_widget(
                self.sequence_assign_btn
            ):
                return

            if self.sequence_input_active:
                token = self._normalize_key_to_str(button)
                if pressed:
                    self._record_sequence_token(token)
                else:
                    self.sequence_recording_down.discard(token)
                return

            if self.waiting_for_sequence_input:
                token = self._normalize_key_to_str(button)
                if pressed:
                    if token not in self.sequence_recording_down:
                        self.sequence_recording_down.add(token)
                        if self.current_mode == self.MODE_COMBO:
                            if token not in self.sequence_recording_keys:
                                self.sequence_recording_keys.append(token)
                            self.sequence_input_signal.emit(
                                "+".join(self.sequence_recording_keys)
                            )
                        else:
                            self.sequence_input_signal.emit(token)
                else:
                    self.sequence_recording_down.discard(token)
                return

            if self.waiting_for_start_key or self.waiting_for_stop_key:
                if pressed:
                    self.binding_capture_keys.add(self._normalize_key_to_str(button))
                else:
                    target = "start" if self.waiting_for_start_key else "stop"
                    self._finish_hotkey_capture(target)
                return

            if pressed:
                self.pressed_keys.add(self._normalize_key_to_str(button))
                if self.hotkeys_enabled:
                    if self._hotkey_matches(self.stop_hotkey):
                        if "stop" not in self.hotkey_fired:
                            self.hotkey_fired.add("stop")
                            self.stop_clicker_safe()
                    elif not simulating and self._hotkey_matches(self.start_hotkey):
                        if "start" not in self.hotkey_fired:
                            self.hotkey_fired.add("start")
                            self.start_clicker_safe()
            else:
                self.pressed_keys.discard(self._normalize_key_to_str(button))
                if not self.pressed_keys or self.pressed_keys.isdisjoint(
                    self.start_hotkey.union(self.stop_hotkey)
                ):
                    self.hotkey_fired.clear()

    def on_mouse_move(self, x, y):
        if self.coordinate_recording_active:
            return
        with self._sim_lock:
            if self._simulating:
                return
        now = time.monotonic()
        position = (int(x), int(y))
        with self.scenario_capture_lock:
            if self.scenario_record_state != "recording":
                return
            if (
                position == self.scenario_last_mouse_position
                or now - self.scenario_last_mouse_move_at < 0.02
            ):
                return
            self.scenario_last_mouse_position = position
            self.scenario_last_mouse_move_at = now
        self._record_scenario_event({
            "type": "mouse_move",
            "x": position[0],
            "y": position[1],
        })

    def on_mouse_scroll(self, x, y, dx, dy):
        if self.coordinate_recording_active:
            return
        with self._sim_lock:
            if self._simulating:
                return
        self._record_scenario_event({
            "type": "scroll",
            "x": int(x),
            "y": int(y),
            "dx": int(dx),
            "dy": int(dy),
        })

    def _finish_hotkey_capture(self, target):
        with self.hotkey_lock:
            captured = set(self.binding_capture_keys)  # строки
            self.binding_capture_keys.clear()
            if not captured:
                self.waiting_for_start_key = False
                self.waiting_for_stop_key = False
                self.update_language_signal.emit()
                return
            name = self._hotkey_name(captured)
            if target == "start":
                self.start_hotkey = captured
                self.start_label_signal.emit(name)
                self.waiting_for_start_key = False
            else:
                self.stop_hotkey = captured
                self.stop_label_signal.emit(name)
                self.waiting_for_stop_key = False
            self.update_info_label()
            self.settings_save_signal.emit()

    def _hotkey_name(self, hotkey_set):
        """Принимает множество строк, сортирует и возвращает красивое имя."""
        order = {"CTRL": 0, "SHIFT": 1, "ALT": 2}
        names = list(hotkey_set)
        names.sort(key=lambda n: (order.get(n, 20), n))
        return "+".join(names)

    def _hotkey_matches(self, hotkey):
        return bool(hotkey) and hotkey.issubset(self.pressed_keys)

    # ==========================================================
    # ПАРСИНГ И КЛИК-ЛОГИКА (с защитой от самонажатия)
    # ==========================================================
    def parse_key_token(self, token):
        if token == " ":
            return keyboard.Key.space
        token = token.strip().upper()
        mouse_map = {
            "ЛКМ": mouse.Button.left,
            "ПКМ": mouse.Button.right,
            "СКМ": mouse.Button.middle,
            "LMB": mouse.Button.left,
            "RMB": mouse.Button.right,
            "MMB": mouse.Button.middle,
            "X1": mouse.Button.x1,
            "X2": mouse.Button.x2,
            "BUTTON.X1": mouse.Button.x1,
            "BUTTON.X2": mouse.Button.x2,
        }
        if token in mouse_map:
            return mouse_map[token]
        special = {
            "SPACE": keyboard.Key.space,
            "ПРОБЕЛ": keyboard.Key.space,
            "ENTER": keyboard.Key.enter,
            "ESC": keyboard.Key.esc,
            "TAB": keyboard.Key.tab,
            "SHIFT": keyboard.Key.shift,
            "CTRL": keyboard.Key.ctrl,
            "CONTROL": keyboard.Key.ctrl,
            "ALT": keyboard.Key.alt,
            "LEFT": keyboard.Key.left,
            "RIGHT": keyboard.Key.right,
            "UP": keyboard.Key.up,
            "DOWN": keyboard.Key.down,
            "F1": keyboard.Key.f1, "F2": keyboard.Key.f2, "F3": keyboard.Key.f3,
            "F4": keyboard.Key.f4, "F5": keyboard.Key.f5, "F6": keyboard.Key.f6,
            "F7": keyboard.Key.f7, "F8": keyboard.Key.f8, "F9": keyboard.Key.f9,
            "F10": keyboard.Key.f10, "F11": keyboard.Key.f11, "F12": keyboard.Key.f12
        }
        for token_name, key_name in (
            ("BACKSPACE", "backspace"),
            ("DELETE", "delete"),
            ("HOME", "home"),
            ("END", "end"),
            ("PAGE_UP", "page_up"),
            ("PAGE_DOWN", "page_down"),
            ("INSERT", "insert"),
            ("CAPS_LOCK", "caps_lock"),
            ("PRINT_SCREEN", "print_screen"),
            ("SCROLL_LOCK", "scroll_lock"),
            ("PAUSE", "pause"),
            ("MENU", "menu"),
            ("NUM_LOCK", "num_lock"),
            ("CTRL_L", "ctrl_l"),
            ("CTRL_R", "ctrl_r"),
            ("SHIFT_L", "shift_l"),
            ("SHIFT_R", "shift_r"),
            ("ALT_L", "alt_l"),
            ("ALT_R", "alt_r"),
            ("CMD", "cmd"),
            ("CMD_L", "cmd_l"),
            ("CMD_R", "cmd_r"),
            ("WIN", "cmd"),
            ("ALT_GR", "alt_gr"),
        ):
            key_value = getattr(keyboard.Key, key_name, None)
            if key_value is not None:
                special[token_name] = key_value
        for function_number in range(13, 21):
            key_value = getattr(
                keyboard.Key,
                "f{}".format(function_number),
                None,
            )
            if key_value is not None:
                special["F{}".format(function_number)] = key_value
        if token in special:
            return special[token]
        if len(token) == 1 and token.isprintable():
            if token == " ":
                return keyboard.Key.space
            if sys.platform == "win32" and token.isascii() and token.isalnum():
                return keyboard.KeyCode.from_vk(ord(token.upper()))
            return token.lower()
        return None

    def parse_sequence(self, raw):
        if self.current_mode == self.MODE_COMBO:
            parts = raw.split("+")
        elif "," not in raw:
            named_tokens = {
                "SPACE", "ПРОБЕЛ", "ENTER", "ESC", "TAB", "SHIFT",
                "CTRL", "CONTROL", "ALT", "LEFT", "RIGHT", "UP", "DOWN",
                "LMB", "RMB", "MMB", "X1", "X2"
            }
            if raw.strip().upper() in named_tokens:
                parsed = self.parse_key_token(raw)
                return [parsed] if parsed is not None else []
            parsed = [self.parse_key_token(char) for char in raw]
            return parsed if all(item is not None for item in parsed) else None
        else:
            parts = raw.split(",")
        res = []
        for p in parts:
            parsed = self.parse_key_token(p.strip())
            if parsed is None:
                return None
            res.append(parsed)
        return res

    def _press_and_release_item(self, item):
        with self._sim_lock:
            self._simulating = True
        try:
            if isinstance(item, mouse.Button):
                self.mouse_controller.click(item)
            else:
                self.keyboard_controller.press(item)
                time.sleep(0.01)
                self.keyboard_controller.release(item)
        except Exception:
            pass
        finally:
            with self._sim_lock:
                self._simulating = False

    def _press_combo(self, items):
        pk, pm = [], []
        with self._sim_lock:
            self._simulating = True
        try:
            for item in items:
                if isinstance(item, mouse.Button):
                    self.mouse_controller.press(item)
                    pm.append(item)
                else:
                    self.keyboard_controller.press(item)
                    pk.append(item)
            time.sleep(0.01)
        except Exception:
            pass
        finally:
            for item in reversed(pk):
                try:
                    self.keyboard_controller.release(item)
                except Exception:
                    pass
            for item in reversed(pm):
                try:
                    self.mouse_controller.release(item)
                except Exception:
                    pass
            with self._sim_lock:
                self._simulating = False

    def press_only(self, binding, b_type):
        with self._sim_lock:
            self._simulating = True
        try:
            if b_type == "mouse":
                self.mouse_controller.press(binding)
            else:
                self.keyboard_controller.press(binding)
        except Exception:
            pass
        finally:
            with self._sim_lock:
                self._simulating = False

    def release_only(self, binding, b_type):
        with self._sim_lock:
            self._simulating = True
        try:
            if b_type == "mouse":
                self.mouse_controller.release(binding)
            else:
                self.keyboard_controller.release(binding)
        except Exception:
            pass
        finally:
            with self._sim_lock:
                self._simulating = False

    def press_and_release(self, binding, b_type):
        with self._sim_lock:
            self._simulating = True
        try:
            if b_type == "mouse":
                self.mouse_controller.click(binding)
            else:
                self.keyboard_controller.press(binding)
                self.keyboard_controller.release(binding)
        except Exception:
            pass
        finally:
            with self._sim_lock:
                self._simulating = False

    def click_at_position(self, x, y):
        with self._sim_lock:
            self._simulating = True
        try:
            self.mouse_controller.position = (int(x), int(y))
            self.mouse_controller.click(mouse.Button.left)
        finally:
            with self._sim_lock:
                self._simulating = False

    def release_all(self):
        with self._sim_lock:
            self._simulating = True
        try:
            # Освобождаем все распространённые клавиши и кнопки мыши (добавлены x1, x2)
            for k in [keyboard.Key.space, keyboard.Key.shift, keyboard.Key.ctrl,
                      keyboard.Key.alt, keyboard.Key.enter]:
                try:
                    self.keyboard_controller.release(k)
                except Exception:
                    pass
            for b in [mouse.Button.left, mouse.Button.right, mouse.Button.middle,
                      mouse.Button.x1, mouse.Button.x2]:
                try:
                    self.mouse_controller.release(b)
                except Exception:
                    pass
        finally:
            with self._sim_lock:
                self._simulating = False

    # ==========================================================
    # УПРАВЛЕНИЕ ЗАПУСКОМ КЛИКЕРА
    # ==========================================================
    def start_clicker(self):
        with self.click_lock:
            if self.clicking:
                return
            if self.scenario_record_state != "idle":
                return
            try:
                is_coordinate_mode = (
                    self.current_mode == self.MODE_COORDINATES
                )
                coordinate_smooth_enabled = (
                    is_coordinate_mode
                    and self.coordinate_smooth_checkbox.isChecked()
                )
                random_click_interval = (
                    self.coordinate_random_click_interval_checkbox.isChecked()
                    and not coordinate_smooth_enabled
                    if is_coordinate_mode
                    else self.random_interval.isChecked()
                )
                self.min_interval = self._interval_value(self.min_interval_edit)
                if random_click_interval:
                    self.max_interval = self._interval_value(self.max_interval_edit)
                else:
                    self.max_interval = self.min_interval
                if self.min_interval > self.max_interval:
                    raise ValueError
                if self.click_limit_checkbox.isChecked():
                    click_limit = int(self.click_limit_edit.text())
                    if not 1 <= click_limit <= 999999999:
                        raise ValueError
                if self.duration_limit_checkbox.isChecked():
                    duration_limit = int(self.duration_limit_edit.text())
                    if not 1 <= duration_limit <= 999999999:
                        raise ValueError
                if self.current_mode == self.MODE_HOLD:
                    self.hold_duration = self._interval_value(self.hold_time_edit)
                elif self.current_mode in (self.MODE_SEQUENCE, self.MODE_COMBO):
                    parsed = self.parse_sequence(self.sequence_edit.toPlainText())
                    if not parsed:
                        QMessageBox.critical(self, self.tr('error_title'), self.tr('error_sequence_parse'))
                        return
                    self.sequence_keys = parsed
                    self.sequence_interval = self._interval_value(self.between_edit)
                elif self.current_mode == self.MODE_COORDINATES:
                    if not self.coordinate_points:
                        QMessageBox.warning(
                            self,
                            self.tr('error_title'),
                            self.tr('coordinate_points_required'),
                        )
                        return
                    self.coordinate_click_positions = (
                        self.resolve_coordinate_points(self.coordinate_points)
                    )
                    self.coordinate_smooth_enabled = (
                        coordinate_smooth_enabled
                    )
                    self.coordinate_move_duration = self._interval_value(
                        self.coordinate_move_duration_min_edit
                        if self.coordinate_random_move_duration_checkbox.isChecked()
                        else self.coordinate_move_duration_edit
                    )
                    self.coordinate_move_duration_max = (
                        self._interval_value(
                            self.coordinate_move_duration_max_edit
                        )
                    )
                    self.coordinate_random_move_duration = (
                        self.coordinate_random_move_duration_checkbox.isChecked()
                    )
                    self.coordinate_cycle_interval = self._interval_value(
                        self.coordinate_cycle_interval_edit
                    )
                    self.coordinate_cycle_interval_max = (
                        self._interval_value(
                            self.coordinate_cycle_interval_max_edit
                        )
                    )
                    self.coordinate_random_cycle_interval = (
                        self.random_interval.isChecked()
                    )
                    self.coordinate_random_click_interval = (
                        self.coordinate_random_click_interval_checkbox.isChecked()
                        and not self.coordinate_smooth_enabled
                    )
                    if not math.isfinite(self.coordinate_move_duration):
                        raise ValueError
                    if not math.isfinite(
                        self.coordinate_move_duration_max
                    ):
                        raise ValueError
                    if not math.isfinite(self.coordinate_cycle_interval):
                        raise ValueError
                    if not math.isfinite(
                        self.coordinate_cycle_interval_max
                    ):
                        raise ValueError
                    if (
                        (
                            self.coordinate_smooth_enabled
                            or has_coordinate_swipe(
                                self.coordinate_click_positions
                            )
                        )
                        and self.coordinate_random_move_duration
                        and self.coordinate_move_duration
                        > self.coordinate_move_duration_max
                    ):
                        raise ValueError
                    if (
                        self.coordinate_random_cycle_interval
                        and self.coordinate_cycle_interval
                        > self.coordinate_cycle_interval_max
                    ):
                        raise ValueError
                elif self.current_mode == self.MODE_SCENARIO:
                    if (
                        self.scenario_record_state != "idle"
                        or self.scenario_record_dialog is not None
                    ):
                        return
                    if self.scenario_run_limit_checkbox.isChecked():
                        scenario_run_limit = int(
                            self.scenario_run_limit_edit.text()
                        )
                        if not 1 <= scenario_run_limit <= 999999999:
                            raise ValueError
                    scenario_profile = self._validate_imported_profile({
                        "name": "scenario",
                        "icon": "🎬",
                        "key": "SPACE",
                        "mode": self.MODE_SCENARIO,
                        "min": 0.0,
                        "max": 0.0,
                        "scenario": self.scenario_actions,
                    })
                    self.scenario_actions = scenario_profile["scenario"]
                    if not self.scenario_actions:
                        QMessageBox.warning(
                            self,
                            self.tr("error_title"),
                            self.tr("scenario_actions_required"),
                        )
                        return
            except CoordinateScreenUnavailable as error:
                QMessageBox.warning(
                    self,
                    self.tr('error_title'),
                    str(error),
                )
                return
            except ValueError:
                self.status_signal.emit(self.tr('status_error'), "red")
                return
            with self._click_stats_lock:
                self._click_count = 0
                self._click_run_started_at = time.monotonic()
                self._average_clicks_per_second = 0.0
            self._click_rate_samples.clear()
            self._click_rate_samples.append(
                (self._click_run_started_at, 0)
            )
            self._refresh_click_stats()
            self.clicking = True
            self.status_signal.emit(self.tr('status_running'), "#35d07f")
            self.worker = ClickerWorker(self)
            self.worker.status_signal.connect(self._set_worker_status)
            self.worker.limit_reached.connect(self.stop_clicker)
            self.worker.duration_limit_reached.connect(self.stop_clicker)
            if self.current_mode == self.MODE_SCENARIO:
                self.worker.scenario_finished.connect(self.stop_clicker)
            self.worker.start()

    def stop_clicker(self):
        with self.click_lock:
            if not self.clicking:
                return
            self.clicking = False
            self.pressed_keys.clear()
            self.hotkey_fired.clear()
            worker = self.worker
            self.worker = None
            if worker:
                worker.stop()
        if worker:
            worker.wait()
            worker.deleteLater()
        with self._click_stats_lock:
            if self._click_run_started_at is not None:
                elapsed = max(
                    0.001,
                    time.monotonic() - self._click_run_started_at,
                )
                self._average_clicks_per_second = (
                    self._click_count / elapsed
                )
                self._click_run_started_at = None
        self._refresh_click_stats()
        self.status_signal.emit(self.tr('status_stopped'), "#ff6873")

    def bind_click_key(self):
        self._ensure_listeners_started()
        if self.sequence_input_active:
            self._stop_sequence_recording()
        with self.hotkey_lock:
            self.waiting_for_start_key = False
            self.waiting_for_stop_key = False
            self.binding_capture_keys.clear()
        self.waiting_for_click_key = True
        self.hotkey_edit.setText(self.tr('capture_click'))
        self.hotkey_edit.setFocus()

    def bind_sequence_input(self):
        self._ensure_listeners_started()
        with self.hotkey_lock:
            self.waiting_for_sequence_input = not self.waiting_for_sequence_input
            self.sequence_input_active = self.waiting_for_sequence_input
            self.sequence_capture_keys.clear()
            if self.waiting_for_sequence_input:
                self.sequence_recording_keys.clear()
                self.sequence_recording_down.clear()
                self.sequence_edit.clear()
        self.sequence_recording_signal.emit(self.waiting_for_sequence_input)

    def record_coordinate_points(self, points):
        dialog = CoordinateRecorderDialog(points, self.tr, self)
        self.apply_theme()
        if dialog.exec() == QDialog.Accepted:
            return deepcopy(dialog.points)
        return None

    def resolve_coordinate_points(self, points):
        screens_by_name = {
            screen.name(): screen for screen in QGuiApplication.screens()
        }

        def resolve_point(point):
            if not isinstance(point, dict):
                raise ValueError(self.tr('coordinate_points_invalid'))
            screen_name = point.get("screen")
            if not isinstance(screen_name, str) or not screen_name:
                raise ValueError(self.tr('coordinate_points_invalid'))
            screen = screens_by_name.get(screen_name)
            if screen is None:
                raise CoordinateScreenUnavailable(
                    self.tr('coordinate_screen_missing', screen_name or "")
                )
            x = point.get("x")
            y = point.get("y")
            if isinstance(x, bool) or isinstance(y, bool):
                raise ValueError(self.tr('coordinate_points_invalid'))
            try:
                x = float(x)
                y = float(y)
            except (TypeError, ValueError, OverflowError) as error:
                raise ValueError(
                    self.tr('coordinate_points_invalid')
                ) from error
            if (
                not math.isfinite(x)
                or not math.isfinite(y)
                or not 0 <= x <= 1
                or not 0 <= y <= 1
            ):
                raise ValueError(self.tr('coordinate_points_invalid'))
            geometry = screen.geometry()
            if geometry.width() <= 0 or geometry.height() <= 0:
                raise ValueError(self.tr('coordinate_points_invalid'))
            return (
                geometry.x() + round(x * (geometry.width() - 1)),
                geometry.y() + round(y * (geometry.height() - 1)),
            )

        button_map = {
            "left": mouse.Button.left,
            "right": mouse.Button.right,
            "middle": mouse.Button.middle,
            "x1": mouse.Button.x1,
            "x2": mouse.Button.x2,
        }
        resolved = []
        for action in points:
            if not isinstance(action, dict):
                raise ValueError(self.tr('coordinate_points_invalid'))
            if action.get("type") == "swipe":
                button = button_map.get(action.get("button"))
                path = action.get("points")
                if button is None or not isinstance(path, list) or len(path) < 2:
                    raise ValueError(self.tr('coordinate_points_invalid'))
                resolved.append({
                    "type": "swipe",
                    "button": button,
                    "points": [resolve_point(point) for point in path],
                })
            else:
                point = action.get("point", action)
                resolved.append({
                    "type": "click",
                    "position": resolve_point(point),
                })
        return resolved

    def record_current_coordinates(self):
        points = self.record_coordinate_points(self.coordinate_points)
        if points is not None:
            self.coordinate_points = points
            self._refresh_coordinate_points_label()
            self.update_coordinate_move_ui()

    def clear_coordinate_points(self):
        self.coordinate_points.clear()
        self._refresh_coordinate_points_label()
        self.update_coordinate_move_ui()

    def _refresh_coordinate_points_label(self):
        self.coordinate_points_label.setText(
            self.tr(
                'coordinate_points_count',
                len(self.coordinate_points),
            )
            if self.coordinate_points
            else self.tr('coordinate_points_empty')
        )

    def _on_record_button_pressed(self):
        self.sequence_record_button_pressed = self.sequence_input_active
        if self.sequence_record_button_pressed:
            self._stop_sequence_recording()

    def _stop_sequence_recording(self):
        with self.hotkey_lock:
            self.waiting_for_sequence_input = False
            self.sequence_input_active = False
            self.sequence_recording_keys.clear()
            self.sequence_recording_down.clear()
        self.sequence_recording_signal.emit(False)

    def _qt_key_token(self, event):
        special = {
            Qt.Key_Space: "SPACE", Qt.Key_Return: "ENTER", Qt.Key_Enter: "ENTER",
            Qt.Key_Tab: "TAB", Qt.Key_Shift: "SHIFT", Qt.Key_Control: "CTRL",
            Qt.Key_Alt: "ALT", Qt.Key_Left: "LEFT", Qt.Key_Right: "RIGHT",
            Qt.Key_Up: "UP", Qt.Key_Down: "DOWN",
        }
        if event.key() in special:
            return special[event.key()]
        text = event.text()
        if text and text.isprintable() and text not in ("+", ","):
            return text.upper()
        if Qt.Key_F1 <= event.key() <= Qt.Key_F12:
            return f"F{event.key() - Qt.Key_F1 + 1}"
        return None

    def _record_sequence_token(self, token):
        if not token or token in self.sequence_recording_down:
            return
        self.sequence_recording_down.add(token)
        if self.current_mode == self.MODE_COMBO:
            if token not in self.sequence_recording_keys:
                self.sequence_recording_keys.append(token)
            self.sequence_input_signal.emit("+".join(self.sequence_recording_keys))
        else:
            self.sequence_input_signal.emit(token)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.MouseButtonPress:
            input_widgets = (QLineEdit, QTextEdit, QComboBox, QPushButton, QCheckBox)
            if not isinstance(watched, input_widgets):
                focused = QApplication.focusWidget()
                if focused:
                    focused.clearFocus()
        if watched is self.sequence_edit:
            if event.type() == QEvent.FocusIn:
                self.sequence_edit.setPlaceholderText("")
                with self.hotkey_lock:
                    self.waiting_for_sequence_input = True
                    self.sequence_input_active = True
                    if self.current_mode == self.MODE_COMBO:
                        self.sequence_recording_keys = [
                            token.strip()
                            for token in self.sequence_edit.toPlainText().split("+")
                            if token.strip()
                        ]
                    else:
                        self.sequence_recording_keys.clear()
                    self.sequence_recording_down.clear()
                self.sequence_recording_signal.emit(True)
            elif event.type() == QEvent.FocusOut:
                if not self.sequence_edit.toPlainText().strip():
                    self.sequence_edit.setPlaceholderText(
                        self.tr('placeholder_combo') if self.current_mode == self.MODE_COMBO
                        else self.tr('placeholder_sequence')
                    )
            elif event.type() == QEvent.KeyPress:
                if event.key() == Qt.Key_Escape:
                    if self.sequence_input_active:
                        self._stop_sequence_recording()
                    return True
                if event.key() == Qt.Key_Backspace:
                    self.remove_last_sequence_token()
                    return True
                return True
            elif event.type() == QEvent.KeyRelease and self.sequence_input_active:
                return True
            elif event.type() == QEvent.ContextMenu and self.sequence_input_active:
                return True
        return super().eventFilter(watched, event)

    def clear_sequence_input(self):
        self.sequence_edit.clear()
        with self.hotkey_lock:
            self.sequence_recording_keys.clear()
            self.sequence_recording_down.clear()

    def remove_last_sequence_token(self):
        value = self.sequence_edit.toPlainText().strip()
        separator = "+" if self.current_mode == self.MODE_COMBO else ","
        tokens = [token.strip() for token in value.split(separator) if token.strip()]
        if not tokens:
            return
        tokens.pop()
        self.sequence_edit.setPlainText(separator.join(tokens))
        with self.hotkey_lock:
            self.sequence_recording_keys = tokens
            self.sequence_recording_down.clear()

    def _adjust_sequence_height(self):
        self.sequence_edit.document().adjustSize()
        content_height = int(self.sequence_edit.document().size().height()) + 24
        self.sequence_edit.setFixedHeight(max(50, min(120, content_height)))

    def apply_sequence_input(self):
        if self.current_mode not in (self.MODE_SEQUENCE, self.MODE_COMBO):
            return
        parsed = self.parse_sequence(self.sequence_edit.toPlainText())
        if not parsed:
            QMessageBox.critical(self, self.tr('error_title'), self.tr('error_sequence_parse'))
            return
        self.sequence_keys = parsed
        self._stop_sequence_recording()
        self.sequence_edit.clearFocus()

    @Slot(bool)
    def _set_sequence_recording(self, recording):
        self.sequence_edit.setReadOnly(not recording)
        self.sequence_edit.setTextInteractionFlags(
            Qt.TextInteractionFlag.NoTextInteraction
            if recording
            else Qt.TextInteractionFlag.TextEditorInteraction
        )
        self.sequence_edit.setContextMenuPolicy(
            Qt.ContextMenuPolicy.NoContextMenu if recording
            else Qt.ContextMenuPolicy.DefaultContextMenu
        )
        self.sequence_assign_btn.setText(
            self.tr('button_stop_recording') if recording
            else self.tr('button_record')
        )
        self.sequence_assign_btn.setChecked(recording)

    @Slot(str)
    def _append_sequence_input(self, token):
        if self.current_mode == self.MODE_COMBO:
            self.sequence_edit.setPlainText(token)
            return
        current = self.sequence_edit.toPlainText().strip()
        self.sequence_edit.setPlainText(
            f"{current}, {token}" if current else token
        )

    def bind_start_key(self):
        self._ensure_listeners_started()
        with self.hotkey_lock:
            self.binding_capture_keys.clear()
            self.waiting_for_start_key = True
            self.waiting_for_stop_key = False
        self.hk_start_edit.setText(self.tr('capture_hotkey'))

    def bind_stop_key(self):
        self._ensure_listeners_started()
        with self.hotkey_lock:
            self.binding_capture_keys.clear()
            self.waiting_for_stop_key = True
            self.waiting_for_start_key = False
        self.hk_stop_edit.setText(self.tr('capture_hotkey'))

    def bind_emergency_stop_key(self):
        self._ensure_listeners_started()
        with self.hotkey_lock:
            self.binding_capture_keys.clear()
            self.waiting_for_emergency_key = True
            self.waiting_for_start_key = False
            self.waiting_for_stop_key = False
            self.waiting_for_click_key = False
        self.emergency_stop_key_edit.setText(
            self.tr('emergency_stop_capture')
        )
        self.emergency_stop_assign_button.setText(
            self.tr('emergency_stop_capture')
        )

    @Slot(str)
    def _set_emergency_stop_key_label(self, key_name):
        self.emergency_stop_key_edit.setText(key_name)
        self.emergency_stop_assign_button.setText(
            self.tr('emergency_stop_assign')
        )
        self.stop_btn.setText(
            self.tr('button_stop').format(self.emergency_stop_key)
        )

    def enable_hotkeys(self):
        self._ensure_listeners_started()
        self.hotkeys_enabled = True
        self.update_hotkey_ui()
        self.update_info_label()
        self.save_settings()

    def disable_hotkeys(self):
        if self.scenario_record_state != "idle":
            self._cancel_scenario_recording()
        self.hotkeys_enabled = False
        self.pressed_keys.clear()
        self.hotkey_fired.clear()
        self.waiting_for_start_key = False
        self.waiting_for_stop_key = False
        self.binding_capture_keys.clear()
        self.update_hotkey_ui()
        self.update_info_label()
        self.save_settings()

    # ==========================================================
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ И МЕНЕДЖМЕНТ ОКОН UI
    # ==========================================================
    def on_mode_changed(self, index):
        modes = [
            self.MODE_INSTANT,
            self.MODE_HOLD,
            self.MODE_COMBO,
            self.MODE_SEQUENCE,
            self.MODE_COORDINATES,
            self.MODE_SCENARIO,
        ]
        if self.waiting_for_sequence_input:
            self._stop_sequence_recording()
        self.current_mode = modes[index]
        if self.current_mode == self.MODE_SCENARIO:
            self.scenario_actions = deepcopy(
                self.standalone_scenario_actions
            )
        self._refresh_main_scenario_summary()
        self.update_mode_ui()

    def update_mode_ui(self):
        is_seq_or_combo = self.current_mode in (self.MODE_SEQUENCE, self.MODE_COMBO)
        is_coordinate_mode = self.current_mode == self.MODE_COORDINATES
        is_scenario_mode = self.current_mode == self.MODE_SCENARIO
        if self.current_mode == self.MODE_HOLD:
            self.interval_grid.addWidget(self.lbl_hold_time, 2, 0)
            self.interval_grid.addWidget(self.hold_time_edit, 3, 0)
            self.interval_grid.addWidget(self.lbl_between, 2, 1)
            self.interval_grid.addWidget(self.between_edit, 3, 1)
        else:
            self.interval_grid.addWidget(self.lbl_between, 2, 0)
            self.interval_grid.addWidget(self.between_edit, 3, 0)
            self.interval_grid.addWidget(self.lbl_hold_time, 2, 1)
            self.interval_grid.addWidget(self.hold_time_edit, 3, 1)
        self.sequence_edit.setVisible(is_seq_or_combo)
        self.sequence_label.setVisible(is_seq_or_combo)
        self.between_edit.setVisible(self.current_mode == self.MODE_SEQUENCE)
        self.lbl_between.setVisible(self.current_mode == self.MODE_SEQUENCE)
        self.hold_time_edit.setVisible(self.current_mode == self.MODE_HOLD)
        self.lbl_hold_time.setVisible(self.current_mode == self.MODE_HOLD)
        is_instant_or_hold = self.current_mode in (self.MODE_INSTANT, self.MODE_HOLD)
        self.hotkey_edit.setVisible(is_instant_or_hold)
        self.assign_btn.setVisible(is_instant_or_hold)
        self.lbl_click_key.setVisible(is_instant_or_hold)
        self.sequence_assign_btn.setVisible(is_seq_or_combo)
        self.sequence_clear_btn.setVisible(is_seq_or_combo)
        self.sequence_apply_btn.setVisible(False)
        self.scenario_mode_label.setVisible(is_scenario_mode)
        self.main_scenario_controls.setVisible(is_scenario_mode)
        self.main_scenario_summary.setVisible(is_scenario_mode)
        self.coordinate_points_label.setVisible(is_coordinate_mode)
        self.coordinate_record_button.setVisible(is_coordinate_mode)
        self.coordinate_clear_button.setVisible(is_coordinate_mode)
        self.coordinate_smooth_checkbox.setVisible(is_coordinate_mode)
        self.coordinate_movement_group.setVisible(is_coordinate_mode)
        self.random_interval.setVisible(True)
        self.click_limit_checkbox.setVisible(not is_scenario_mode)
        self.click_limit_edit.setVisible(not is_scenario_mode)
        self.click_limit_suffix.setVisible(not is_scenario_mode)
        self.scenario_run_limit_checkbox.setVisible(is_scenario_mode)
        self.scenario_run_limit_edit.setVisible(is_scenario_mode)
        self.scenario_run_limit_suffix.setVisible(is_scenario_mode)
        self.duration_limit_checkbox.setVisible(True)
        self.duration_limit_edit.setVisible(True)
        self.duration_limit_suffix.setVisible(True)
        self.limits_hint_label.setVisible(True)
        self.update_random_interval_ui()
        self.update_coordinate_move_ui()
        if self.current_mode == self.MODE_COMBO:
            self.sequence_edit.setPlaceholderText(self.tr('placeholder_combo'))
        else:
            self.sequence_edit.setPlaceholderText(self.tr('placeholder_sequence'))

    def on_language_changed(self, index):
        text = self.lang_combo.itemText(index)
        if text == self.tr('lang_ru'):
            self.language = 'ru'
        else:
            self.language = 'en'
        self.update_language()
        self.save_settings()

    def update_info_label(self):
        if self.hotkeys_enabled:
            info = self.tr('label_hotkey_info',
                           self._hotkey_name(self.start_hotkey),
                           self._hotkey_name(self.stop_hotkey))
            self.info_label.setText(info)
        else:
            self.info_label.setText(self.tr('label_bindings_disabled'))

    def key_to_string(self, key):
        return self._key_to_str(key)

    def mouse_to_string(self, button):
        if self.language == 'en':
            names = {
                mouse.Button.left: "LMB",
                mouse.Button.right: "RMB",
                mouse.Button.middle: "MMB",
                mouse.Button.x1: "X1",
                mouse.Button.x2: "X2",
            }
        else:
            names = {
                mouse.Button.left: "ЛКМ",
                mouse.Button.right: "ПКМ",
                mouse.Button.middle: "СКМ",
                mouse.Button.x1: "X1",
                mouse.Button.x2: "X2",
            }
        return names.get(button, str(button).upper())

    def get_binding_name(self, binding, b_type):
        if b_type == "keyboard":
            return self.key_to_string(binding)
        return self.mouse_to_string(binding)

    def _item_to_string(self, item):
        if isinstance(item, mouse.Button):
            return self.mouse_to_string(item)
        return self.key_to_string(item)

    @Slot(str, str)
    def _set_status(self, text, color):
        self._status_text = text
        self._render_status_text()
        self._status_base_color = color
        status_color = THEME_COLOR_MAPS[self.theme].get(
            color.lower(),
            color,
        )
        self.status_label.setStyleSheet(
            f"color: {status_color}; font-weight: 700;"
        )

    @Slot(str, str)
    def _set_worker_status(self, text, color):
        if not self.clicking or self.sender() is not self.worker:
            return
        self._set_status(text, color)

    def _record_click(self, count=1):
        with self._click_stats_lock:
            self._click_count += count

    @Slot()
    def _refresh_click_stats(self):
        now = time.monotonic()
        with self._click_stats_lock:
            click_count = self._click_count
            if self._click_run_started_at is not None:
                elapsed = max(
                    0.001,
                    now - self._click_run_started_at,
                )
                average_clicks_per_second = click_count / elapsed
            else:
                average_clicks_per_second = (
                    self._average_clicks_per_second
                )
        self._click_rate_samples.append((now, click_count))
        cutoff = now - 1.0
        while (
            len(self._click_rate_samples) > 1
            and self._click_rate_samples[1][0] <= cutoff
        ):
            self._click_rate_samples.popleft()
        sample_time, sample_count = self._click_rate_samples[0]
        elapsed = max(0.001, now - sample_time)
        clicks_per_second = max(
            0.0,
            (click_count - sample_count) / elapsed,
        )
        stats = self.tr(
            'status_click_stats',
            self._format_compact_number(click_count),
            self._format_compact_number(clicks_per_second),
            self._format_compact_number(average_clicks_per_second),
        )
        self.click_stats_label.setText(stats)
        self._render_status_text()

    @staticmethod
    def _format_compact_number(value):
        for threshold, suffix in (
            (1_000_000_000, "B"),
            (1_000_000, "M"),
            (1_000, "K"),
        ):
            if value >= threshold:
                return f"{value / threshold:.1f}{suffix}"
        return f"{value:.1f}" if isinstance(value, float) else str(value)

    def _render_status_text(self):
        if not hasattr(self, "status_label"):
            return
        available_width = self.status_label.width()
        if available_width <= 0:
            available_width = self.status_label.maximumWidth()
        self.status_label.setText(
            self.status_label.fontMetrics().elidedText(
                self._status_text,
                Qt.ElideRight,
                available_width,
            )
        )

    @Slot(str)
    def _set_hotkey_label(self, text):
        self.hotkey_edit.setText(text)

    @Slot(str)
    def _set_start_label(self, text):
        self.hk_start_edit.setText(text)

    @Slot(str)
    def _set_stop_label(self, text):
        self.hk_stop_edit.setText(text)

    def start_clicker_safe(self):
        self.start_request_signal.emit()

    def _signal_worker_stop(self):
        worker = self.worker
        if worker is not None:
            worker.stop()

    def stop_clicker_safe(self):
        self.stop_request_signal.emit()

    # ==========================================================
    # ПРОФИЛИ И СОХРАНЕНИЯ
    # ==========================================================
    def refresh_profiles(self):
        while self.profile_container.count():
            item = self.profile_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.profile_widgets = []
        has_profiles = bool(self.profiles)
        self.profiles_empty_widget.setVisible(not has_profiles)
        self.profile_scroll.setVisible(has_profiles)
        self.profiles_search_button.setVisible(has_profiles)
        if not has_profiles:
            self.profiles_search_edit.clear()
            self.profiles_search_edit.hide()
            self.profiles_search_empty_label.hide()
        for p in self.profiles:
            widget = ProfileWidget(p, self.apply_profile, self.edit_profile, self.delete_profile, parent=self)
            self.profile_widgets.append(widget)
            self.profile_container.addWidget(widget)
        self.profile_container.addStretch()
        self.filter_profiles(self.profiles_search_edit.text())
        self.apply_theme()

    def toggle_profile_search(self):
        if self.profiles_search_edit.isVisible():
            self.profiles_search_edit.clear()
            self.profiles_search_edit.hide()
            self.profiles_search_empty_label.hide()
            self.profiles_search_button.setFocus()
            return
        self.profiles_search_edit.show()
        self.profiles_search_edit.setFocus()

    def filter_profiles(self, query):
        normalized_query = query.strip().casefold()
        visible_count = 0
        for profile, widget in zip(self.profiles, self.profile_widgets):
            name = profile.get("name", "")
            matches = (
                not normalized_query
                or normalized_query in name.casefold()
            )
            widget.setVisible(matches)
            visible_count += int(matches)
        self.profiles_search_empty_label.setVisible(
            bool(normalized_query) and visible_count == 0
        )

    def add_profile(self):
        dialog = QMessageBox(self)
        dialog.setWindowTitle(self.tr('profile_add_title'))
        dialog.setText(self.tr('profile_add_question'))
        copy_button = dialog.addButton(
            self.tr('profile_copy_settings'),
            QMessageBox.YesRole,
        )
        defaults_button = dialog.addButton(
            self.tr('profile_default_settings'),
            QMessageBox.NoRole,
        )
        dialog.addButton(self.tr('dialog_cancel'), QMessageBox.RejectRole)
        self.apply_theme()
        dialog.exec()
        if dialog.clickedButton() not in (copy_button, defaults_button):
            return

        new_p = {
            "icon": "✨",
            "name": self.tr('profile_new_name').format(
                len(self.profiles) + 1
            ),
            "mode": self.tr('mode_instant'),
            "min": 1.0,
            "max": 1.0,
            "hold": 1.0,
            "between": 0.2,
            "key": "SPACE",
            "coordinates": [],
            "scenario": [],
            "coordinate_smooth": False,
            "coordinate_move_duration": 0.3,
            "coordinate_random_move_duration": False,
            "coordinate_move_duration_max": 0.5,
            "coordinate_cycle_interval": 0.5,
            "coordinate_cycle_interval_max": 1.0,
            "coordinate_random_cycle_interval": False,
            "coordinate_random_click_interval": False,
        }
        if dialog.clickedButton() == copy_button:
            mode_names = [
                self.MODE_INSTANT,
                self.MODE_HOLD,
                self.MODE_COMBO,
                self.MODE_SEQUENCE,
                self.MODE_COORDINATES,
                self.MODE_SCENARIO,
            ]
            new_p.update({
                "mode": mode_names[self.mode.currentIndex()],
                "min": self._interval_value(self.min_interval_edit),
                "max": self._interval_value(self.max_interval_edit),
                "hold": self._interval_value(self.hold_time_edit),
                "between": self._interval_value(self.between_edit),
                "key": (
                    self._button_to_str(self.click_key)
                    if self.click_key_type == "mouse"
                    else self._key_to_str(self.click_key)
                ),
                "sequence": self.sequence_edit.toPlainText(),
                "coordinates": deepcopy(self.coordinate_points),
                "scenario": deepcopy(self.scenario_actions),
                "coordinate_smooth": (
                    self.coordinate_smooth_checkbox.isChecked()
                ),
                "coordinate_move_duration": self._interval_value(
                    self.coordinate_move_duration_min_edit
                    if self.coordinate_random_move_duration_checkbox.isChecked()
                    else self.coordinate_move_duration_edit
                ),
                "coordinate_random_move_duration": (
                    self.coordinate_random_move_duration_checkbox.isChecked()
                ),
                "coordinate_move_duration_max": self._interval_value(
                    self.coordinate_move_duration_max_edit
                ),
                "coordinate_cycle_interval": self._interval_value(
                    self.coordinate_cycle_interval_edit
                ),
                "coordinate_cycle_interval_max": self._interval_value(
                    self.coordinate_cycle_interval_max_edit
                ),
                "coordinate_random_cycle_interval": (
                    self.random_interval.isChecked()
                ),
                "coordinate_random_click_interval": (
                    self.coordinate_random_click_interval_checkbox.isChecked()
                ),
                "random": (
                    (
                        self.coordinate_random_click_interval_checkbox.isChecked()
                        if self.current_mode == self.MODE_COORDINATES
                        else self.random_interval.isChecked()
                    )
                    and not interval_fields_match(
                        self.min_interval_edit,
                        self.max_interval_edit,
                    )
                ),
            })
        self.profiles.append(new_p)
        self.save_profiles()
        self.refresh_profiles()

    def edit_profile(self, profile):
        dialog = ProfileEditDialog(profile, self)
        self.apply_theme()
        if dialog.exec() == QDialog.Accepted:
            updated = dialog.get_profile()
            idx = self.profiles.index(profile)
            self.profiles[idx] = updated
            self.save_profiles()
            self.refresh_profiles()

    def delete_profile(self, profile):
        reply = QMessageBox.question(
            self,
            self.tr('delete_profile'),
            self.tr('profile_delete_confirm').format(profile["name"]),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.profiles.remove(profile)
            self.save_profiles()
            self.refresh_profiles()

    def apply_profile(self, profile):
        # Обновляем поля интерфейса
        min_signals_blocked = self.min_interval_edit.blockSignals(True)
        max_signals_blocked = self.max_interval_edit.blockSignals(True)
        try:
            self.min_interval_edit.setText(
                format_interval_value(max(0.0, float(profile["min"])))
            )
            self.max_interval_edit.setText(
                format_interval_value(max(0.0, float(profile["max"])))
            )
        finally:
            self.min_interval_edit.blockSignals(min_signals_blocked)
            self.max_interval_edit.blockSignals(max_signals_blocked)
        self.hold_time_edit.setText(
            str(max(0.0, float(profile.get("hold", 1.0))))
        )
        self.between_edit.setText(
            str(max(0.0, float(profile.get("between", 0.2))))
        )
        same_bounds = float(profile["min"]) == float(profile["max"])
        self.random_interval.setChecked(
            profile.get("random", True) and not same_bounds
        )
        self.update_random_interval_ui()
        m_str = profile["mode"]
        mode_aliases = {
            self.MODE_INSTANT: self.MODE_INSTANT,
            self.MODE_HOLD: self.MODE_HOLD,
            self.MODE_SEQUENCE: self.MODE_SEQUENCE,
            self.MODE_COMBO: self.MODE_COMBO,
            self.MODE_COORDINATES: self.MODE_COORDINATES,
            self.MODE_SCENARIO: self.MODE_SCENARIO,
            self.tr('mode_instant'): self.MODE_INSTANT,
            self.tr('mode_hold'): self.MODE_HOLD,
            self.tr('mode_sequence'): self.MODE_SEQUENCE,
            self.tr('mode_combo'): self.MODE_COMBO,
            self.tr('mode_coordinates'): self.MODE_COORDINATES,
            self.tr('mode_scenario'): self.MODE_SCENARIO,
            "Обычный клик": self.MODE_INSTANT,
            "Coordinate clicks": self.MODE_COORDINATES,
            "Recorded scenario": self.MODE_SCENARIO,
        }
        mode_key = mode_aliases.get(m_str, m_str)
        for i in range(self.mode.count()):
            item_mode = mode_aliases.get(self.mode.itemText(i), self.mode.itemText(i))
            if mode_key == item_mode:
                self.mode.setCurrentIndex(i)
                break

        if "sequence" in profile:
            self.sequence_edit.setPlainText(profile["sequence"])
        self.coordinate_points = deepcopy(
            profile.get("coordinates", [])
        )
        self.scenario_actions = deepcopy(profile.get("scenario", []))
        self._refresh_main_scenario_summary()
        self._refresh_coordinate_points_label()
        self.coordinate_smooth_checkbox.setChecked(
            profile.get("coordinate_smooth", False)
        )
        self.coordinate_random_move_duration_checkbox.setChecked(
            profile.get("coordinate_random_move_duration", False)
        )
        self.update_coordinate_move_ui()
        profile_move_duration = max(
            0.0,
            float(profile.get("coordinate_move_duration", 0.3)),
        )
        self.coordinate_move_duration_edit.setText(
            format_interval_value(profile_move_duration)
        )
        self.coordinate_move_duration_min_edit.setText(
            format_interval_value(profile_move_duration)
        )
        self.coordinate_move_duration_max_edit.setText(
            format_interval_value(
                max(
                    0.0,
                    float(
                        profile.get(
                            "coordinate_move_duration_max",
                            max(0.5, profile_move_duration),
                        )
                    ),
                )
            )
        )
        self.coordinate_cycle_interval_edit.setText(
            format_interval_value(
                max(0.0, float(profile.get("coordinate_cycle_interval", 0.5)))
            )
        )
        self.coordinate_cycle_interval_max_edit.setText(
            format_interval_value(
                max(
                    0.0,
                    float(
                        profile.get(
                            "coordinate_cycle_interval_max",
                            max(
                                1.0,
                                float(
                                    profile.get(
                                        "coordinate_cycle_interval",
                                        0.5,
                                    )
                                ),
                            ),
                        )
                    ),
                )
            )
        )
        is_coordinate_profile = mode_key == self.MODE_COORDINATES
        self.random_interval.setChecked(
            profile.get("coordinate_random_cycle_interval", False)
            if is_coordinate_profile
            else profile.get("random", True) and not same_bounds
        )
        self.coordinate_random_click_interval_checkbox.setChecked(
            profile.get(
                "coordinate_random_click_interval",
                profile.get("random", True),
            )
            and not same_bounds
        )
        self.update_coordinate_move_ui()

        # --- Интеграция клавиши из профиля ---
        key_str = profile["key"]
        parsed = self.parse_key_token(key_str)
        if parsed is not None:
            if isinstance(parsed, mouse.Button):
                self.click_key = parsed
                self.click_key_type = "mouse"
            else:
                self.click_key = parsed
                self.click_key_type = "keyboard"
            # Обновляем отображение назначенной клавиши
            self.hotkey_edit.setText(self.get_binding_name(self.click_key, self.click_key_type))
        else:
            # Если не удалось распарсить, оставляем текущее значение
            self.hotkey_edit.setText(key_str)  # на всякий случай

        self.save_settings()

    def load_profiles(self):
        profile_file = PROFILES_FILE
        if not profile_file.exists() and LEGACY_PROFILES_FILE.exists():
            profile_file = LEGACY_PROFILES_FILE

        if not profile_file.exists():
            return []

        try:
            with profile_file.open("r", encoding="utf-8") as f:
                profiles = json.load(f)
            if not isinstance(profiles, list) or not all(
                isinstance(profile, dict) for profile in profiles
            ):
                raise ValueError("profiles.json должен содержать список профилей")
            return profiles
        except (OSError, json.JSONDecodeError, ValueError):
            logging.getLogger(__name__).exception(
                "Could not load profiles from %s",
                profile_file,
            )
            return []

    def _write_profiles(self, profiles):
        temp_file = PROFILES_FILE.with_suffix(".tmp")
        try:
            PROFILES_FILE.parent.mkdir(parents=True, exist_ok=True)
            with temp_file.open("w", encoding="utf-8") as f:
                json.dump(profiles, f, ensure_ascii=False, indent=4)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_file, PROFILES_FILE)
            return True
        except OSError:
            try:
                if temp_file.exists():
                    temp_file.unlink()
            except OSError:
                pass
            return False

    def save_profiles(self):
        if not self._write_profiles(self.profiles):
            self._set_status(
                self.tr("profiles_save_error"),
                "#ff6873",
            )

    def load_standalone_scenario(self):
        if not SCENARIO_FILE.exists():
            return []
        try:
            with SCENARIO_FILE.open("r", encoding="utf-8") as file:
                data = json.load(file)
            if (
                not isinstance(data, dict)
                or data.get("format") != "lim0n4ikz-clicker-scenario"
                or type(data.get("version")) is not int
                or data.get("version") != 1
            ):
                raise ValueError("Unsupported standalone scenario format")
            return self._normalize_scenario_actions(data.get("actions"))
        except (OSError, TypeError, ValueError) as error:
            logging.getLogger(__name__).warning(
                "Could not load standalone scenario from %s: %s",
                SCENARIO_FILE,
                error,
            )
            return []

    def save_standalone_scenario(self):
        temp_file = SCENARIO_FILE.with_suffix(".tmp")
        try:
            actions = self._normalize_scenario_actions(
                self.standalone_scenario_actions
            )
            SCENARIO_FILE.parent.mkdir(parents=True, exist_ok=True)
            with temp_file.open("w", encoding="utf-8") as file:
                json.dump(
                    {
                        "format": "lim0n4ikz-clicker-scenario",
                        "version": 1,
                        "actions": actions,
                    },
                    file,
                    ensure_ascii=False,
                    indent=2,
                )
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_file, SCENARIO_FILE)
            return True
        except (OSError, TypeError, ValueError):
            try:
                if temp_file.exists():
                    temp_file.unlink()
            except OSError:
                pass
            logging.getLogger(__name__).exception(
                "Could not save standalone scenario to %s",
                SCENARIO_FILE,
            )
            self._set_status(
                self.tr("scenario_save_error"),
                "#ff6873",
            )
            return False

    def save_settings(self):
        temp_file = SETTINGS_FILE.with_suffix(".tmp")
        try:
            start_str = self._hotkey_name(self.start_hotkey)
            stop_str = self._hotkey_name(self.stop_hotkey)
            click_key_str = (
                self._button_to_str(self.click_key)
                if self.click_key_type == "mouse"
                else self._key_to_str(self.click_key)
            )
            click_limit_text = self.click_limit_edit.text()
            click_limit = (
                int(click_limit_text)
                if click_limit_text.isdecimal()
                else 100
            )
            if not 1 <= click_limit <= 999999999:
                click_limit = 100
            scenario_run_limit_text = (
                self.scenario_run_limit_edit.text().strip()
            )
            scenario_run_limit = (
                int(scenario_run_limit_text)
                if scenario_run_limit_text.isdecimal()
                else 1
            )
            if not 1 <= scenario_run_limit <= 999999999:
                scenario_run_limit = 1
            duration_limit_text = (
                self.duration_limit_edit.text().strip()
            )
            duration_limit = (
                int(duration_limit_text)
                if duration_limit_text.isdecimal()
                else 30
            )
            if not 1 <= duration_limit <= 999999999:
                duration_limit = 30
            data = {
                "settings_version": 12,
                "tutorial_offer_version": self._tutorial_offer_version,
                "tutorial_offer_dismissed": self._tutorial_offer_dismissed,
                "window": {"width": self.width(), "height": self.height()},
                "mode_idx": self.mode.currentIndex(),
                "min_int": self._interval_value(self.min_interval_edit),
                "max_int": self._interval_value(self.max_interval_edit),
                "hold_t": self._interval_value(self.hold_time_edit),
                "btw_t": self._interval_value(self.between_edit),
                "seq_raw": self.sequence_edit.toPlainText(),
                "coordinate_smooth": (
                    self.coordinate_smooth_checkbox.isChecked()
                ),
                "coordinate_move_duration": self._interval_value(
                    self.coordinate_move_duration_min_edit
                    if self.coordinate_random_move_duration_checkbox.isChecked()
                    else self.coordinate_move_duration_edit
                ),
                "coordinate_random_move_duration": (
                    self.coordinate_random_move_duration_checkbox.isChecked()
                ),
                "coordinate_move_duration_max": self._interval_value(
                    self.coordinate_move_duration_max_edit
                ),
                "coordinate_cycle_interval": self._interval_value(
                    self.coordinate_cycle_interval_edit
                ),
                "coordinate_cycle_interval_max": self._interval_value(
                    self.coordinate_cycle_interval_max_edit
                ),
                "coordinate_random_cycle_interval": (
                    self.random_interval.isChecked()
                    if self.current_mode == self.MODE_COORDINATES
                    else False
                ),
                "coordinate_random_click_interval": (
                    self.coordinate_random_click_interval_checkbox.isChecked()
                    if self.current_mode == self.MODE_COORDINATES
                    else False
                ),
                "random_i": (
                    (
                        self.coordinate_random_click_interval_checkbox.isChecked()
                        if self.current_mode == self.MODE_COORDINATES
                        else self.random_interval.isChecked()
                    )
                    and not interval_fields_match(
                        self.min_interval_edit,
                        self.max_interval_edit,
                    )
                ),
                "click_limit_enabled": (
                    self.click_limit_checkbox.isChecked()
                ),
                "click_limit": click_limit,
                "scenario_run_limit_enabled": (
                    self.scenario_run_limit_checkbox.isChecked()
                ),
                "scenario_run_limit": scenario_run_limit,
                "duration_limit_enabled": (
                    self.duration_limit_checkbox.isChecked()
                ),
                "duration_limit_minutes": duration_limit,
                "lang": self.language,
                "theme": self.theme,
                "start_hotkey": start_str,
                "stop_hotkey": stop_str,
                "emergency_stop_key": self.emergency_stop_key,
                "click_key": click_key_str,
                "click_key_type": self.click_key_type,
                "hotkeys_enabled": self.hotkeys_enabled,
            }
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
                f.flush()
                os.fsync(f.fileno())
            try:
                os.replace(temp_file, SETTINGS_FILE)
            except OSError:
                with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
                    f.flush()
                    os.fsync(f.fileno())
        except Exception:
            try:
                if temp_file.exists():
                    temp_file.unlink()
            except Exception:
                pass
            pass

    def _parse_hotkey_string(self, s):
        """Парсит строку вида 'CTRL+SHIFT+A' и возвращает множество строк."""
        if not s:
            return set()
        parts = s.split('+')
        result = set()
        for p in parts:
            p = p.upper()
            p = {"BUTTON.X1": "X1", "BUTTON.X2": "X2"}.get(p, p)
            if p in ("CTRL", "SHIFT", "ALT", "SPACE", "ENTER", "ESC", "TAB"):
                result.add(p)
            elif p.startswith("F") and p[1:].isdigit():
                num = int(p[1:])
                if 1 <= num <= 12:
                    result.add(p)
            elif len(p) == 1 and p.isalnum():
                result.add(p)
            elif p in ("LMB", "RMB", "MMB", "X1", "X2"):
                result.add(p)
            else:
                result.add(p)  # на случай неизвестных
        return result

    def load_settings(self):
        settings_file = SETTINGS_FILE
        if not settings_file.exists() and LEGACY_SETTINGS_FILE.exists():
            settings_file = LEGACY_SETTINGS_FILE
        if not settings_file.exists():
            return
        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            legacy_settings = data.get("settings_version", 1) < 3
            settings_upgrade = data.get("settings_version", 1) < 12
            tutorial_offer_version = data.get("tutorial_offer_version")
            self._tutorial_offer_version = (
                tutorial_offer_version
                if isinstance(tutorial_offer_version, str)
                else None
            )
            self._tutorial_offer_dismissed = (
                data.get("tutorial_offer_dismissed") is True
            )
            self._tutorial_prompt_pending = (
                not self._tutorial_offer_dismissed
                and self._tutorial_offer_version != APP_VERSION
            )
            if legacy_settings:
                data = {
                    "window": {"width": 1200, "height": 780},
                    "mode_idx": 0,
                    "min_int": 0.5,
                    "max_int": 1.0,
                    "hold_t": 1.0,
                    "btw_t": 0.2,
                    "seq_raw": "",
                    "coordinate_smooth": False,
                    "coordinate_move_duration": 0.3,
                    "coordinate_random_move_duration": False,
                    "coordinate_move_duration_max": 0.5,
                    "coordinate_cycle_interval": 0.5,
                    "coordinate_cycle_interval_max": 1.0,
                    "coordinate_random_cycle_interval": False,
                    "coordinate_random_click_interval": False,
                    "random_i": True,
                    "click_limit_enabled": False,
                    "click_limit": 100,
                    "lang": "ru",
                    "theme": "dark",
                    "start_hotkey": "F6",
                    "stop_hotkey": "F7",
                    "emergency_stop_key": "ESC",
                    "click_key": "SPACE",
                    "click_key_type": "keyboard",
                    "hotkeys_enabled": True,
                }
            click_limit_enabled = data.get(
                "click_limit_enabled",
                False,
            )
            if not isinstance(click_limit_enabled, bool):
                click_limit_enabled = False
            click_limit = data.get("click_limit", 100)
            if (
                isinstance(click_limit, bool)
                or not isinstance(click_limit, int)
                or not 1 <= click_limit <= 999999999
            ):
                click_limit = 100
            limit_signals_blocked = (
                self.click_limit_checkbox.blockSignals(True)
            )
            try:
                self.click_limit_checkbox.setChecked(
                    click_limit_enabled
                )
            finally:
                self.click_limit_checkbox.blockSignals(
                    limit_signals_blocked
                )
            self.click_limit_edit.setText(str(click_limit))
            self.click_limit_edit.setEnabled(click_limit_enabled)
            scenario_run_limit_enabled = data.get(
                "scenario_run_limit_enabled",
                False,
            )
            if not isinstance(scenario_run_limit_enabled, bool):
                scenario_run_limit_enabled = False
            scenario_run_limit = data.get("scenario_run_limit", 1)
            if (
                isinstance(scenario_run_limit, bool)
                or not isinstance(scenario_run_limit, int)
                or not 1 <= scenario_run_limit <= 999999999
            ):
                scenario_run_limit = 1
            duration_limit_enabled = data.get(
                "duration_limit_enabled",
                data.get("scenario_duration_limit_enabled", False),
            )
            if not isinstance(duration_limit_enabled, bool):
                duration_limit_enabled = False
            duration_limit = data.get(
                "duration_limit_minutes",
                data.get("scenario_duration_limit_minutes", 30),
            )
            if (
                isinstance(duration_limit, bool)
                or not isinstance(duration_limit, int)
                or not 1 <= duration_limit <= 999999999
            ):
                duration_limit = 30
            run_limit_signals_blocked = (
                self.scenario_run_limit_checkbox.blockSignals(True)
            )
            time_limit_signals_blocked = (
                self.duration_limit_checkbox.blockSignals(True)
            )
            try:
                self.scenario_run_limit_checkbox.setChecked(
                    scenario_run_limit_enabled
                )
                self.duration_limit_checkbox.setChecked(
                    duration_limit_enabled
                )
            finally:
                self.scenario_run_limit_checkbox.blockSignals(
                    run_limit_signals_blocked
                )
                self.duration_limit_checkbox.blockSignals(
                    time_limit_signals_blocked
                )
            self.scenario_run_limit_edit.setText(str(scenario_run_limit))
            self.scenario_run_limit_edit.setEnabled(
                scenario_run_limit_enabled
            )
            self.duration_limit_edit.setText(str(duration_limit))
            self.duration_limit_edit.setEnabled(
                duration_limit_enabled
            )
            if "window" in data:
                self.resize(data["window"]["width"], data["window"]["height"])
            self.mode.setCurrentIndex(data.get("mode_idx", 0))
            min_signals_blocked = self.min_interval_edit.blockSignals(True)
            max_signals_blocked = self.max_interval_edit.blockSignals(True)
            try:
                self.min_interval_edit.setText(
                    format_interval_value(
                        max(0.0, float(data.get("min_int", 0.5)))
                    )
                )
                self.max_interval_edit.setText(
                    format_interval_value(
                        max(0.0, float(data.get("max_int", 1.0)))
                    )
                )
            finally:
                self.min_interval_edit.blockSignals(min_signals_blocked)
                self.max_interval_edit.blockSignals(max_signals_blocked)
            self.hold_time_edit.setText(str(max(0.0, float(data.get("hold_t", 1.0)))))
            self.between_edit.setText(str(max(0.0, float(data.get("btw_t", 0.2)))))
            self.sequence_edit.setPlainText(data.get("seq_raw", ""))
            coordinate_smooth = data.get("coordinate_smooth", False)
            self.coordinate_smooth_checkbox.setChecked(
                coordinate_smooth
                if isinstance(coordinate_smooth, bool)
                else False
            )
            coordinate_move_duration = data.get(
                "coordinate_move_duration",
                0.3,
            )
            if (
                isinstance(coordinate_move_duration, bool)
                or not isinstance(coordinate_move_duration, (int, float))
                or not math.isfinite(coordinate_move_duration)
                or coordinate_move_duration < 0
                or coordinate_move_duration > 999999999
            ):
                coordinate_move_duration = 0.3
            self.coordinate_move_duration_edit.setText(
                format_interval_value(coordinate_move_duration)
            )
            coordinate_random_move_duration = data.get(
                "coordinate_random_move_duration",
                False,
            )
            self.coordinate_random_move_duration_checkbox.setChecked(
                coordinate_random_move_duration
                if isinstance(coordinate_random_move_duration, bool)
                else False
            )
            coordinate_move_duration_max = data.get(
                "coordinate_move_duration_max",
                max(0.5, coordinate_move_duration),
            )
            if (
                isinstance(coordinate_move_duration_max, bool)
                or not isinstance(
                    coordinate_move_duration_max,
                    (int, float),
                )
                or not math.isfinite(coordinate_move_duration_max)
                or coordinate_move_duration_max < 0
                or coordinate_move_duration_max > 999999999
            ):
                coordinate_move_duration_max = coordinate_move_duration
            self.coordinate_move_duration_min_edit.setText(
                format_interval_value(coordinate_move_duration)
            )
            self.coordinate_move_duration_max_edit.setText(
                format_interval_value(coordinate_move_duration_max)
            )
            coordinate_cycle_interval = data.get(
                "coordinate_cycle_interval",
                0.5,
            )
            if (
                isinstance(coordinate_cycle_interval, bool)
                or not isinstance(coordinate_cycle_interval, (int, float))
                or not math.isfinite(coordinate_cycle_interval)
                or coordinate_cycle_interval < 0
                or coordinate_cycle_interval > 999999999
            ):
                coordinate_cycle_interval = 0.5
            self.coordinate_cycle_interval_edit.setText(
                format_interval_value(coordinate_cycle_interval)
            )
            coordinate_cycle_interval_max = data.get(
                "coordinate_cycle_interval_max",
                max(1.0, coordinate_cycle_interval),
            )
            if (
                isinstance(coordinate_cycle_interval_max, bool)
                or not isinstance(
                    coordinate_cycle_interval_max,
                    (int, float),
                )
                or not math.isfinite(coordinate_cycle_interval_max)
                or coordinate_cycle_interval_max < 0
                or coordinate_cycle_interval_max > 999999999
            ):
                coordinate_cycle_interval_max = max(
                    1.0,
                    coordinate_cycle_interval,
                )
            self.coordinate_cycle_interval_max_edit.setText(
                format_interval_value(coordinate_cycle_interval_max)
            )
            coordinate_random_cycle_interval = data.get(
                "coordinate_random_cycle_interval",
                False,
            )
            self.random_interval.setChecked(
                coordinate_random_cycle_interval
                if isinstance(coordinate_random_cycle_interval, bool)
                else False
            )
            coordinate_random_click_interval = data.get(
                "coordinate_random_click_interval",
                data.get("random_i", True),
            )
            self.coordinate_random_click_interval_checkbox.setChecked(
                coordinate_random_click_interval
                if isinstance(coordinate_random_click_interval, bool)
                else False
            )
            self.update_coordinate_move_ui()
            same_bounds = interval_fields_match(
                self.min_interval_edit,
                self.max_interval_edit,
            )
            if self.current_mode != self.MODE_COORDINATES:
                self.random_interval.setChecked(
                    data.get("random_i", True) and not same_bounds
                )
            elif same_bounds:
                self.coordinate_random_click_interval_checkbox.setChecked(
                    False
                )
            self.update_random_interval_ui()
            self.language = data.get("lang", "ru")
            stored_theme = data.get("theme", "dark")
            self.theme = (
                stored_theme
                if isinstance(stored_theme, str)
                and stored_theme in THEME_COLOR_MAPS
                else "dark"
            )
            start_str = data.get("start_hotkey", "F6")
            stop_str = data.get("stop_hotkey", "F7")
            self.start_hotkey = self._parse_hotkey_string(start_str)
            self.stop_hotkey = self._parse_hotkey_string(stop_str)
            emergency_stop_key = data.get("emergency_stop_key", "ESC")
            if (
                not isinstance(emergency_stop_key, str)
                or not emergency_stop_key.strip()
                or "+" in emergency_stop_key
            ):
                emergency_stop_key = "ESC"
            self.emergency_stop_key = self._normalize_key_name(
                emergency_stop_key
            )
            self.hk_start_edit.setText(start_str)
            self.hk_stop_edit.setText(stop_str)
            click_key_str = data.get("click_key", "SPACE")
            click_key = self.parse_key_token(click_key_str)
            if click_key is not None:
                self.click_key = click_key
                self.click_key_type = (
                    "mouse" if isinstance(click_key, mouse.Button) else "keyboard"
                )
                self.hotkey_edit.setText(
                    self.get_binding_name(self.click_key, self.click_key_type)
                )
            self.hotkeys_enabled = data.get("hotkeys_enabled", True)
            self.update_hotkey_ui()
            self.update_language()
            self.apply_theme()
            if settings_file != SETTINGS_FILE or settings_upgrade:
                self.save_settings()
        except Exception:
            pass

    def closeEvent(self, event):
        self.hotkeys_enabled = False
        self._cancel_scenario_recording()
        QApplication.instance().removeEventFilter(self)
        self.stop_clicker()
        if self.keyboard_listener:
            self.keyboard_listener.stop()
        if self.mouse_listener:
            self.mouse_listener.stop()
        self.save_settings()
        self.save_profiles()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    icon_path = ICON_FILE if ICON_FILE.exists() else FALLBACK_ICON_FILE
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()