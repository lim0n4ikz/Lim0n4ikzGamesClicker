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

from PySide6.QtCore import Qt, QEvent, QTimer, QThread, Signal, Slot, QLocale, QUrl, QObject
from PySide6.QtGui import (
    QFont, QAction, QCursor, QIcon, QDoubleValidator, QDesktopServices, QColor,
    QPainter, QPen,
)
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QLineEdit, QComboBox,
    QTextEdit, QFrame, QCheckBox, QMessageBox, QRadioButton,
    QMenu, QDialog, QDialogButtonBox, QFormLayout, QSizePolicy, QScrollArea,
    QTextBrowser, QFileDialog, QStyle, QStyleOptionButton,
)

from pynput import keyboard, mouse


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

# Для корректного отображения в панели задач Windows
if sys.platform == "win32":
    import ctypes
    myappid = "mycompany.zloyclicker.version.2.0"
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
# ============================================================
# APP SETTINGS
# ============================================================

APP_NAME = "Lim0n4ikzGames Clicker"
APP_VERSION = "2.1"
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
        modes = [parent.tr('mode_instant'), parent.tr('mode_hold'), parent.tr('mode_combo'), parent.tr('mode_sequence')]
        self.mode_combo.addItems(modes)
        mode_names = {
            parent.MODE_INSTANT: parent.tr('mode_instant'),
            parent.MODE_HOLD: parent.tr('mode_hold'),
            parent.MODE_COMBO: parent.tr('mode_combo'),
            parent.MODE_SEQUENCE: parent.tr('mode_sequence'),
            "Instant press": parent.tr('mode_instant'),
            "Hold key": parent.tr('mode_hold'),
            "Instant combo": parent.tr('mode_combo'),
            "Sequence press": parent.tr('mode_sequence'),
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
        self.random_interval.setChecked(self.profile.get("random", True))
        self.random_interval.stateChanged.connect(self.update_interval_ui)
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

        layout.addRow(self.name_label, self.name_edit)
        layout.addRow(self.icon_label, self.icon_edit)
        self.key_edit.installEventFilter(self)
        self.key_label = QLabel(parent.tr('label_click_key') + ":")
        layout.addRow(self.key_label, key_box)
        self.mode_label = QLabel()
        layout.addRow(self.mode_label, self.mode_combo)
        self.sequence_label = QLabel(parent.tr('label_sequence') + ":")
        layout.addRow(self.sequence_label, sequence_widget)
        layout.addRow(self.random_interval)
        self.min_label = QLabel()
        self.max_label = QLabel()
        self.hold_label = QLabel()
        self.between_label = QLabel()
        layout.addRow(self.min_label, self.min_edit)
        layout.addRow(self.max_label, self.max_edit)
        layout.addRow(self.hold_label, self.hold_edit)
        layout.addRow(self.between_label, self.between_edit)
        self.update_interval_ui()
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
        self.hold_label.setText(self.parent.tr('label_hold') + ":")
        self.between_label.setText(self.parent.tr('label_interval_seq') + ":")
        self.random_interval.setText(self.parent.tr('label_random_interval'))
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
        edit = QLineEdit(str(max(0.0, float(value))))
        edit.setValidator(IntervalValidator(edit))
        return edit

    @staticmethod
    def _interval_value(edit):
        try:
            return max(0.0, float(edit.text().replace(",", ".")))
        except ValueError:
            return 0.0

    def get_profile(self):
        mode_names = [
            self.parent.tr('mode_instant'),
            self.parent.tr('mode_hold'),
            self.parent.tr('mode_combo'),
            self.parent.tr('mode_sequence'),
        ]
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
            "random": self.random_interval.isChecked(),
        }

    def update_interval_ui(self):
        enabled = self.random_interval.isChecked()
        self.min_label.setText(
            self.parent.tr('label_min' if enabled else 'label_single_interval') + ":"
        )
        self.max_label.setText(self.parent.tr('label_max') + ":")
        self.max_label.setVisible(enabled)
        self.max_edit.setVisible(enabled)

    def update_mode_ui(self, index):
        is_sequence_mode = index in (2, 3)
        self.key_edit.setVisible(not is_sequence_mode)
        self.key_assign_btn.setVisible(not is_sequence_mode)
        self.key_label.setVisible(not is_sequence_mode)
        self.sequence_label.setVisible(is_sequence_mode)
        self.sequence_widget.setVisible(is_sequence_mode)
        self.sequence_edit.setVisible(is_sequence_mode)
        self.record_btn.setVisible(is_sequence_mode)
        self.clear_btn.setVisible(is_sequence_mode)
        is_hold_mode = index == 1
        self.hold_label.setVisible(is_hold_mode)
        self.hold_edit.setVisible(is_hold_mode)
        is_sequence_mode = index == 3
        self.between_label.setVisible(is_sequence_mode)
        self.between_edit.setVisible(is_sequence_mode)

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

    def __init__(self, parent_clicker):
        super().__init__()
        self.c = parent_clicker
        self.stop_event = threading.Event()
        self.last_status_time = 0.0

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

                mode = self.c.current_mode

                if mode == self.c.MODE_HOLD:
                    self.c.press_only(self.c.click_key, self.c.click_key_type)
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
                        with self.c.click_lock:
                            if not self.c.clicking:
                                return
                        self.c._press_and_release_item(item)
                        self.report_status(self.c.tr('status_pressed', self.c._item_to_string(item)), "red")
                        if not self.interruptible_sleep(self.c.sequence_interval):
                            return

                elif mode == self.c.MODE_COMBO:
                    combo = list(self.c.sequence_keys)
                    if combo:
                        self.c._press_combo(combo)
                        self.report_status(
                            self.c.tr('status_combo', '+'.join(self.c._item_to_string(x) for x in combo)),
                            "red"
                        )
                else:  # Мгновенное нажатие
                    self.c.press_and_release(self.c.click_key, self.c.click_key_type)
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
            if held:
                self.c.release_only(self.c.click_key, self.c.click_key_type)
            self.c.release_all()

    def interruptible_sleep(self, duration):
        with self.c.click_lock:
            if not self.c.clicking or self.stop_event.is_set():
                return False
        duration = max(0.0, duration)
        if duration < 0.01:
            deadline = time.perf_counter() + duration
            while time.perf_counter() < deadline:
                if self.stop_event.is_set():
                    return False
                time.sleep(0)
            return not self.stop_event.is_set()
        return not self.stop_event.wait(duration)

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
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#060d16"), 2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(
            indicator.left() + indicator.width() * 0.24,
            indicator.top() + indicator.height() * 0.52,
            indicator.left() + indicator.width() * 0.43,
            indicator.top() + indicator.height() * 0.7,
        )
        painter.drawLine(
            indicator.left() + indicator.width() * 0.43,
            indicator.top() + indicator.height() * 0.7,
            indicator.left() + indicator.width() * 0.77,
            indicator.top() + indicator.height() * 0.32,
        )


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
                f'{self.parent.tr("interval")}: {minimum_interval} sec.'
            )
        else:
            interval_text = (
                f'{self.parent.tr("interval")}: {minimum_interval} — '
                f'{maximum_interval} sec.'
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

        key = QLabel(self.parent.display_key_token(profile["key"]))
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
        self.settings_save_signal.connect(self.save_settings)

        # Запускаем слушатели сразу
        self._ensure_listeners_started()

        # Обновляем состояние кнопок управления горячими клавишами
        self.update_hotkey_ui()
        QTimer.singleShot(1000, self.check_for_updates)

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
            on_click=self.on_mouse_click
        )
        self.mouse_listener.start()
        self.listeners_started = True

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
                    "Эта клавиша всегда активна, даже если обычные бинды выключены "
                    "или окно свёрнуто. Рекомендуется назначить отдельную клавишу, "
                    "например Pause/Break или F12. Не используйте клавишу запуска "
                    "или часто используемую в игре клавишу."
                ),
                'emergency_stop_assign': "Назначить клавишу",
                'emergency_stop_capture': "Нажмите клавишу...",
                'settings_updates_section': "Обновления",
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
                'update_check_error': "Не удалось проверить обновления. Проверьте подключение к интернету и попробуйте ещё раз.",
                'profiles_transfer_title': "Профили",
                'profiles_export': "Экспортировать профили",
                'profiles_import': "Импортировать профили",
                'profiles_export_success': "Профили экспортированы.",
                'profiles_import_success': "Импортировано профилей: {}. Пропущено дубликатов: {}.",
                'profiles_import_empty': "В файле нет новых профилей. Пропущено дубликатов: {}.",
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
                'profile_file_too_large': "Размер файла профилей превышает 5 МБ",
                'profile_file_format_invalid': "Неподдерживаемый формат файла профилей",
                'profile_file_schema_invalid': "Неподдерживаемая версия файла профилей",
                'profile_file_list_invalid': "Файл должен содержать список профилей",
                'update_error_title': "Ошибка",
                'update_open_error': "Не удалось открыть страницу загрузки обновления.",
                'status_stopped': "● Остановлен",
                'status_running': "● Кликер работает",
                'status_error': "● Ошибка параметров",
                'status_hotkeys_enabled': "● Горячие клавиши включены",
                'status_hotkeys_disabled': "● Горячие клавиши отключены",
                'status_mode': "● Режим: {}",
                'status_held': "● Зажата {}",
                'status_pressed': "● Нажата {}",
                'status_combo': "● Выполнена комбинация: {}",
                'status_hold_released': "● Кликер работает (зажатие отпущено)",
                'profiles_save_error': "● Не удалось сохранить профили",
                'mode_instant': "Мгновенное нажатие",
                'mode_hold': "Зажатие клавиши",
                'mode_sequence': "Последовательное нажатие",
                'mode_combo': "Мгновенная комбинация",
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
                'label_random_interval': "Включить случайный интервал",
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
                    "disabled or the window is minimized. Use a dedicated key "
                    "such as Pause/Break or F12. Avoid the start key and keys "
                    "you frequently use in your game."
                ),
                'emergency_stop_assign': "Assign key",
                'emergency_stop_capture': "Press a key...",
                'settings_updates_section': "Updates",
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
                'update_check_error': "Could not check for updates. Check your internet connection and try again.",
                'profiles_transfer_title': "Profiles",
                'profiles_export': "Export profiles",
                'profiles_import': "Import profiles",
                'profiles_export_success': "Profiles exported.",
                'profiles_import_success': "Imported profiles: {}. Skipped duplicates: {}.",
                'profiles_import_empty': "No new profiles in the file. Skipped duplicates: {}.",
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
                'profile_file_too_large': "Profile file exceeds 5 MB",
                'profile_file_format_invalid': "Unsupported profile file format",
                'profile_file_schema_invalid': "Unsupported profile file version",
                'profile_file_list_invalid': "The file must contain a profile list",
                'update_error_title': "Error",
                'update_open_error': "Could not open the update download page.",
                'status_stopped': "● Stopped",
                'status_running': "● Clicker running",
                'status_error': "● Parameter error",
                'status_hotkeys_enabled': "● Hotkeys enabled",
                'status_hotkeys_disabled': "● Hotkeys disabled",
                'status_mode': "● Mode: {}",
                'status_held': "● Held {}",
                'status_pressed': "● Pressed {}",
                'status_combo': "● Executed combination: {}",
                'status_hold_released': "● Clicker running (hold released)",
                'profiles_save_error': "● Failed to save profiles",
                'mode_instant': "Instant press",
                'mode_hold': "Hold key",
                'mode_sequence': "Sequence press",
                'mode_combo': "Instant combo",
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
                'label_random_interval': "Enable random interval",
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
        }
        return self.tr(mapping.get(mode_key, mode_key))

    @Slot()
    def update_language(self):
        # Заголовки и основные надписи
        self.title.setText(self.tr('title'))
        self.subtitle.setText(self.tr('subtitle'))
        self.settings_dialog.setWindowTitle(self.tr('settings_title'))
        self.settings_version_label.setText(
            self.tr('settings_version').format(APP_VERSION)
        )
        self.settings_developer_label.setText(self.tr('settings_developer'))
        self.settings_developer_discord_label.setText(
            self.tr('settings_developer_discord')
        )
        self.settings_theme_label.setText(self.tr('settings_theme'))
        self.settings_updates_title_label.setText(
            self.tr('settings_updates_section')
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
        self.profiles_transfer_title_label.setText(
            self.tr('profiles_transfer_title')
        )
        self.profiles_export_button.setText(self.tr('profiles_export'))
        self.profiles_import_button.setText(self.tr('profiles_import'))
        self.settings_close_button.setText(self.tr('dialog_close'))
        self.settings_button.setToolTip(self.tr('settings_button_tooltip'))
        self.settings_button.setAccessibleName(self.tr('settings_title'))
        self.section_mode.setText(self.tr('label_mode'))
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
        self.update_random_interval_ui()
        self.profiles_title_label.setText(self.tr('profiles_title'))
        self.add_profile_btn.setText(self.tr('add_profile'))
        self.lang_label.setText(self.tr('language'))
        # Обновление выпадающего списка режимов
        self.mode.blockSignals(True)
        self.mode.clear()
        self.mode.addItems([
            self.tr('mode_instant'),
            self.tr('mode_hold'),
            self.tr('mode_combo'),
            self.tr('mode_sequence')
        ])
        mode_map = {
            self.MODE_INSTANT: 0,
            self.MODE_HOLD: 1,
            self.MODE_COMBO: 2,
            self.MODE_SEQUENCE: 3
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
        self.lbl_min_interval.setText(
            self.tr('label_min') if random_enabled
            else self.tr('label_single_interval')
        )
        self.lbl_max_interval.setVisible(random_enabled)
        self.max_interval_edit.setVisible(random_enabled)

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

        self.status_label = QLabel(self.tr('status_stopped'))
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

    def export_profiles(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr('profiles_export'),
            "clicker-profiles.json",
            self.tr('profiles_file_filter'),
        )
        if not file_path:
            return

        payload = {
            "format": PROFILE_FILE_FORMAT,
            "schema_version": 1,
            "profiles": self.profiles,
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
        }
        for language in ("ru", "en"):
            supported_modes.update(
                self.translations[language][translation_key]
                for translation_key in (
                    "mode_instant",
                    "mode_hold",
                    "mode_sequence",
                    "mode_combo",
                )
            )
        if not isinstance(mode, str) or mode not in supported_modes:
            raise ValueError(self.tr('profile_mode_unknown', name))

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
        if not isinstance(random_interval, bool):
            raise ValueError(self.tr('profile_random_invalid', name))
        if not isinstance(sequence, str):
            raise ValueError(self.tr('profile_sequence_invalid', name))

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
            "random": random_interval,
        }

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

        existing_names = {
            profile.get("name", "").strip().casefold()
            for profile in self.profiles
            if isinstance(profile.get("name"), str)
        }
        updated_profiles = list(self.profiles)
        skipped = 0
        for profile in profiles_to_import:
            normalized_name = profile["name"].casefold()
            if normalized_name in existing_names:
                skipped += 1
                continue
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
            message = self.tr('profiles_import_success').format(added, skipped)
        else:
            message = self.tr('profiles_import_empty').format(skipped)
        QMessageBox.information(
            self,
            self.tr('profiles_transfer_title'),
            message,
        )

    def build_settings_dialog(self):
        self.settings_dialog = QDialog(self)
        self.settings_dialog.setWindowTitle(self.tr('settings_title'))
        self.settings_dialog.setMinimumWidth(360)

        layout = QVBoxLayout(self.settings_dialog)

        def add_separator():
            separator = QFrame()
            separator.setFixedHeight(1)
            separator.setStyleSheet(
                "background-color: #eef5ff; border: none;"
            )
            layout.addWidget(separator)

        language_layout = QHBoxLayout()
        self.lang_label = QLabel(self.tr('language'))
        self.lang_label.setObjectName("section")
        self.lang_combo = QComboBox()
        self.lang_combo.addItems([self.tr('lang_ru'), self.tr('lang_en')])
        self.lang_combo.currentIndexChanged.connect(self.on_language_changed)
        language_layout.addWidget(self.lang_label)
        language_layout.addWidget(self.lang_combo, 1)
        layout.addLayout(language_layout)

        theme_layout = QHBoxLayout()
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
        theme_layout.addWidget(self.settings_theme_label)
        theme_layout.addWidget(self.theme_combo, 1)
        layout.addLayout(theme_layout)

        add_separator()
        self.settings_updates_title_label = QLabel(
            self.tr('settings_updates_section')
        )
        self.settings_updates_title_label.setObjectName("section")
        layout.addWidget(self.settings_updates_title_label)
        self.update_check_button = QPushButton(self.tr('update_check_button'))
        self.update_check_button.clicked.connect(
            lambda: self.check_for_updates(manual=True)
        )
        layout.addWidget(self.update_check_button)

        add_separator()

        self.profiles_transfer_title_label = QLabel(
            self.tr('profiles_transfer_title')
        )
        self.profiles_transfer_title_label.setObjectName("section")
        layout.addWidget(self.profiles_transfer_title_label)

        self.profiles_export_button = QPushButton(self.tr('profiles_export'))
        self.profiles_export_button.clicked.connect(self.export_profiles)
        layout.addWidget(self.profiles_export_button)

        self.profiles_import_button = QPushButton(self.tr('profiles_import'))
        self.profiles_import_button.clicked.connect(self.import_profiles)
        layout.addWidget(self.profiles_import_button)

        add_separator()
        self.emergency_stop_title_label = QLabel(
            self.tr('emergency_stop_title')
        )
        self.emergency_stop_title_label.setObjectName("section")
        layout.addWidget(self.emergency_stop_title_label)
        self.emergency_stop_warning_label = QLabel(
            self.tr('emergency_stop_warning')
        )
        self.emergency_stop_warning_label.setWordWrap(True)
        self.emergency_stop_warning_label.setStyleSheet(
            "color: #ffd35c; font-size: 12px;"
        )
        layout.addWidget(self.emergency_stop_warning_label)
        emergency_stop_layout = QHBoxLayout()
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
        layout.addLayout(emergency_stop_layout)

        layout.addStretch()
        add_separator()

        self.settings_developer_label = QLabel(self.tr('settings_developer'))
        layout.addWidget(self.settings_developer_label)
        self.settings_developer_discord_label = QLabel(
            self.tr('settings_developer_discord')
        )
        self.settings_developer_discord_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse
        )
        layout.addWidget(self.settings_developer_discord_label)
        self.settings_version_label = QLabel(
            self.tr('settings_version').format(APP_VERSION)
        )
        self.settings_version_label.setStyleSheet("color: #91a4ba;")
        layout.addWidget(self.settings_version_label)

        buttons = QDialogButtonBox()
        self.settings_close_button = buttons.addButton(
            self.tr('dialog_close'),
            QDialogButtonBox.RejectRole,
        )
        self.settings_close_button.clicked.connect(self.settings_dialog.reject)
        layout.addWidget(buttons)
        self.settings_dialog.setMinimumHeight(520)
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
        layout.addLayout(grid)

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

        self.random_interval = CheckmarkCheckBox(
            self.tr('label_random_interval')
        )
        self.random_interval.setChecked(True)
        self.random_interval.stateChanged.connect(self.update_random_interval_ui)
        layout.addWidget(self.random_interval)

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
        self.add_profile_btn = QPushButton(self.tr('add_profile'))
        self.add_profile_btn.setObjectName("blue")
        self.add_profile_btn.clicked.connect(self.add_profile)
        header.addWidget(self.profiles_title_label)
        header.addStretch()
        header.addWidget(self.add_profile_btn)
        layout.addLayout(header)

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
                    self.stop_clicker_safe()
            elif not simulating and self._hotkey_matches(self.start_hotkey):
                if "start" not in self.hotkey_fired:
                    self.hotkey_fired.add("start")
                    self.start_clicker_safe()

    def on_key_release(self, key):
        with self.hotkey_lock:
            if self.waiting_for_sequence_input:
                self.sequence_recording_down.discard(
                    self._normalize_key_to_str(key)
                )
                return

            if self.waiting_for_start_key or self.waiting_for_stop_key:
                target = "start" if self.waiting_for_start_key else "stop"
                self._finish_hotkey_capture(target)
                return

            self.pressed_keys.discard(self._normalize_key_to_str(key))

            # Сброс флага hotkey_fired, чтобы можно было заново нажать
            if not self.pressed_keys or self.pressed_keys.isdisjoint(
                self.start_hotkey.union(self.stop_hotkey)
            ):
                self.hotkey_fired.clear()

    def on_mouse_click(self, x, y, button, pressed):
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
                            self.stop_clicker_safe()
                else:
                    self.pressed_keys.discard(token)
                    if not self.pressed_keys or self.pressed_keys.isdisjoint(
                        self.start_hotkey.union(self.stop_hotkey)
                    ):
                        self.hotkey_fired.clear()
            return

        with self.hotkey_lock:
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
            try:
                self.min_interval = self._interval_value(self.min_interval_edit)
                if self.random_interval.isChecked():
                    self.max_interval = self._interval_value(self.max_interval_edit)
                else:
                    self.max_interval = self.min_interval
                if self.min_interval > self.max_interval:
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
            except ValueError:
                self.status_signal.emit(self.tr('status_error'), "red")
                return
            self.clicking = True
            self.status_signal.emit(self.tr('status_running'), "#35d07f")
            self.worker = ClickerWorker(self)
            self.worker.status_signal.connect(self.status_signal.emit)
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
        modes = [self.MODE_INSTANT, self.MODE_HOLD, self.MODE_COMBO, self.MODE_SEQUENCE]
        if self.waiting_for_sequence_input:
            self._stop_sequence_recording()
        self.current_mode = modes[index]
        self.update_mode_ui()

    def update_mode_ui(self):
        is_seq_or_combo = self.current_mode in (self.MODE_SEQUENCE, self.MODE_COMBO)
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
        self.status_label.setText(text)
        self._status_base_color = color
        status_color = THEME_COLOR_MAPS[self.theme].get(
            color.lower(),
            color,
        )
        self.status_label.setStyleSheet(
            f"color: {status_color}; font-weight: 700;"
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
        for p in self.profiles:
            widget = ProfileWidget(p, self.apply_profile, self.edit_profile, self.delete_profile, parent=self)
            self.profile_container.addWidget(widget)
        self.profile_container.addStretch()
        self.apply_theme()

    def add_profile(self):
        new_p = {
            "icon": "✨",
            "name": f"Новый профиль {len(self.profiles)+1}",
            "mode": self.tr('mode_instant'),
            "min": 1.0,
            "max": 1.0,
            "hold": 1.0,
            "between": 0.2,
            "key": "SPACE"
        }
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
        self.min_interval_edit.setText(str(max(0.0, float(profile["min"]))))
        self.max_interval_edit.setText(str(max(0.0, float(profile["max"]))))
        self.hold_time_edit.setText(
            str(max(0.0, float(profile.get("hold", 1.0))))
        )
        self.between_edit.setText(
            str(max(0.0, float(profile.get("between", 0.2))))
        )
        self.random_interval.setChecked(profile.get("random", True))
        m_str = profile["mode"]
        mode_aliases = {
            self.MODE_INSTANT: self.MODE_INSTANT,
            self.MODE_HOLD: self.MODE_HOLD,
            self.MODE_SEQUENCE: self.MODE_SEQUENCE,
            self.MODE_COMBO: self.MODE_COMBO,
            self.tr('mode_instant'): self.MODE_INSTANT,
            self.tr('mode_hold'): self.MODE_HOLD,
            self.tr('mode_sequence'): self.MODE_SEQUENCE,
            self.tr('mode_combo'): self.MODE_COMBO,
            "Обычный клик": self.MODE_INSTANT,
        }
        mode_key = mode_aliases.get(m_str, m_str)
        for i in range(self.mode.count()):
            item_mode = mode_aliases.get(self.mode.itemText(i), self.mode.itemText(i))
            if mode_key == item_mode:
                self.mode.setCurrentIndex(i)
                break

        if "sequence" in profile:
            self.sequence_edit.setPlainText(profile["sequence"])

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

    def default_profiles(self):
        return [
            {"icon": "🪱", "name": "Копка червей", "mode": self.tr('mode_instant'), "min": 8.6, "max": 9.0, "key": "1"},
            {"icon": "🎰", "name": "Казино", "mode": self.tr('mode_instant'), "min": 8.0, "max": 9.0, "key": "F"},
            {"icon": "⛏️", "name": "Лесоруб / шахта", "mode": self.tr('mode_instant'), "min": 0.01, "max": 0.01, "key": "ЛКМ"},
            {"icon": "🧰", "name": "ИРП", "mode": self.tr('mode_instant'), "min": 7200, "max": 7200, "key": "2"}
        ]

    def load_profiles(self):
        profile_file = PROFILES_FILE
        if not profile_file.exists() and LEGACY_PROFILES_FILE.exists():
            profile_file = LEGACY_PROFILES_FILE

        if not profile_file.exists():
            profiles = self.default_profiles()
            self._write_profiles(profiles)
            return profiles

        try:
            with profile_file.open("r", encoding="utf-8") as f:
                profiles = json.load(f)
            if not isinstance(profiles, list) or not all(
                isinstance(profile, dict) for profile in profiles
            ):
                raise ValueError("profiles.json должен содержать список профилей")
            return profiles
        except (OSError, json.JSONDecodeError, ValueError):
            profiles = self.default_profiles()
            self._write_profiles(profiles)
            return profiles

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
            data = {
                "settings_version": 5,
                "window": {"width": self.width(), "height": self.height()},
                "mode_idx": self.mode.currentIndex(),
                "min_int": self._interval_value(self.min_interval_edit),
                "max_int": self._interval_value(self.max_interval_edit),
                "hold_t": self._interval_value(self.hold_time_edit),
                "btw_t": self._interval_value(self.between_edit),
                "seq_raw": self.sequence_edit.toPlainText(),
                "random_i": self.random_interval.isChecked(),
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
            settings_upgrade = data.get("settings_version", 1) < 5
            if legacy_settings:
                data = {
                    "window": {"width": 1200, "height": 780},
                    "mode_idx": 0,
                    "min_int": 0.5,
                    "max_int": 1.0,
                    "hold_t": 1.0,
                    "btw_t": 0.2,
                    "seq_raw": "",
                    "random_i": True,
                    "lang": "ru",
                    "theme": "dark",
                    "start_hotkey": "F6",
                    "stop_hotkey": "F7",
                    "emergency_stop_key": "ESC",
                    "click_key": "SPACE",
                    "click_key_type": "keyboard",
                    "hotkeys_enabled": True,
                }
            if "window" in data:
                self.resize(data["window"]["width"], data["window"]["height"])
            self.mode.setCurrentIndex(data.get("mode_idx", 0))
            self.min_interval_edit.setText(str(max(0.0, float(data.get("min_int", 0.5)))))
            self.max_interval_edit.setText(str(max(0.0, float(data.get("max_int", 1.0)))))
            self.hold_time_edit.setText(str(max(0.0, float(data.get("hold_t", 1.0)))))
            self.between_edit.setText(str(max(0.0, float(data.get("btw_t", 0.2)))))
            self.sequence_edit.setPlainText(data.get("seq_raw", ""))
            self.random_interval.setChecked(data.get("random_i", True))
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