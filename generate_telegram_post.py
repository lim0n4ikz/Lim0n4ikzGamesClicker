import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path


APPLICATION_URL = "https://lim0n4ikz.github.io/Lim0n4ikzGamesClicker/"


def choose_version(manifest):
    latest_version = manifest.get("latest_version")
    releases = manifest.get("releases")
    if not isinstance(latest_version, str) or not isinstance(releases, list):
        raise ValueError("versions.json must contain latest_version and releases")

    versions = [
        release["version"]
        for release in releases
        if isinstance(release, dict) and isinstance(release.get("version"), str)
    ]
    if latest_version not in versions:
        raise ValueError(f"Latest release {latest_version} was not found")

    menu_versions = list(reversed(versions))
    sys.stdout.write("Available versions:\n")
    for index, version in enumerate(menu_versions, start=1):
        suffix = " (latest)" if version == latest_version else ""
        sys.stdout.write(f"{index}. {version}{suffix}\n")

    selection = input("Choose a number or enter a version (Enter = latest): ").strip()
    if not selection:
        return latest_version
    if selection in versions:
        return selection
    if selection.isdecimal():
        index = int(selection) - 1
        if 0 <= index < len(menu_versions):
            return menu_versions[index]
    raise ValueError(f"Unknown version selection: {selection}")


def build_post(manifest, requested_version=None):
    if not isinstance(manifest, dict):
        raise ValueError("versions.json must contain a JSON object")

    latest_version = manifest.get("latest_version")
    releases = manifest.get("releases")
    if not isinstance(latest_version, str) or not isinstance(releases, list):
        raise ValueError("versions.json must contain latest_version and releases")

    version = requested_version or latest_version
    release = next(
        (
            item
            for item in releases
            if isinstance(item, dict) and item.get("version") == version
        ),
        None,
    )
    if release is None:
        raise ValueError(f"Release {version} was not found")

    changes = release.get("changes")
    russian_changes = changes.get("ru") if isinstance(changes, dict) else None
    telegram_post = release.get("telegram_post")
    if (
        not isinstance(russian_changes, list)
        or not all(
            isinstance(item, str) and item.strip() for item in russian_changes
        )
        or not isinstance(telegram_post, dict)
    ):
        raise ValueError(
            f"Release {version} needs Russian changes and telegram_post categories"
        )

    features = telegram_post.get("features")
    fixes = telegram_post.get("fixes")
    if not all(
        isinstance(items, list)
        and all(isinstance(item, str) and item.strip() for item in items)
        for items in (features, fixes)
    ):
        raise ValueError(
            f"Release {version} has invalid telegram_post categories"
        )
    if Counter(features + fixes) != Counter(russian_changes):
        raise ValueError(
            f"telegram_post categories for {version} must include "
            "each Russian change exactly once"
        )

    sections = []
    seen_items = set()
    for heading, items in (
        ("✨ **Новые функции и улучшения:**", features),
        ("⚙️ **Исправления и доработки:**", fixes),
    ):
        unique_items = [item for item in items if item not in seen_items]
        seen_items.update(unique_items)
        if unique_items:
            sections.append((heading, unique_items))

    lines = [f"🍋 **Lim0n4ikzGames Clicker — версия {version}**"]
    for heading, items in sections:
        lines.extend(["", heading, ""])
        lines.extend(f"> - {item}" for item in items)
    lines.append("")
    lines.extend(
        [
            f"🔗 [Ссылка на приложение.]({APPLICATION_URL})",
            "",
            "#**Clicker**",
        ]
    )
    return "\n".join(lines)


def launch_gui(manifest, initial_version=None):
    from PySide6.QtGui import QKeySequence, QShortcut
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QFrame,
        QHBoxLayout,
        QLabel,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )

    if not isinstance(manifest, dict):
        raise ValueError("versions.json must contain a JSON object")
    latest_version = manifest.get("latest_version")
    releases = manifest.get("releases")
    if not isinstance(latest_version, str) or not isinstance(releases, list):
        raise ValueError("versions.json must contain latest_version and releases")

    versions = [
        release["version"]
        for release in reversed(releases)
        if isinstance(release, dict) and isinstance(release.get("version"), str)
    ]
    if latest_version not in versions:
        raise ValueError(f"Latest release {latest_version} was not found")
    if initial_version is not None and initial_version not in versions:
        raise ValueError(f"Release {initial_version} was not found")

    application = QApplication.instance() or QApplication(sys.argv)
    window = QMainWindow()
    window.setWindowTitle("Telegram — текст обновления")
    window.setMinimumSize(680, 560)
    window.resize(820, 700)
    window.setStyleSheet(
        """
        QMainWindow, QWidget#container {
            background: #10161f;
            color: #e8edf5;
            font-size: 10pt;
        }
        QLabel#title {
            color: #f5f8fc;
            font-size: 23pt;
            font-weight: 700;
        }
        QLabel#subtitle, QLabel#hint, QLabel#counter {
            color: #9eacbd;
        }
        QLabel#eyebrow {
            color: #72dfa0;
            font-size: 9pt;
            font-weight: 700;
        }
        QFrame#card {
            background: #18212d;
            border: 1px solid #293647;
            border-radius: 12px;
        }
        QComboBox, QTextEdit {
            background: #0e141d;
            color: #e8edf5;
            border: 1px solid #344255;
            border-radius: 8px;
            padding: 9px;
            selection-background-color: #267c52;
        }
        QComboBox:focus, QTextEdit:focus {
            border: 1px solid #55d68a;
        }
        QComboBox QAbstractItemView {
            background: #18212d;
            color: #e8edf5;
            selection-background-color: #267c52;
            border: 1px solid #344255;
        }
        QPushButton#copyButton {
            background: #45d483;
            color: #07140c;
            border: none;
            border-radius: 9px;
            padding: 12px 18px;
            font-size: 11pt;
            font-weight: 700;
        }
        QPushButton#copyButton:hover {
            background: #63e499;
        }
        QPushButton#copyButton:pressed {
            background: #34b96c;
        }
        QPushButton#copyButton:disabled {
            background: #35433d;
            color: #87948b;
        }
        QLabel#status {
            color: #72dfa0;
            font-weight: 600;
        }
        """
    )

    container = QWidget()
    container.setObjectName("container")
    layout = QVBoxLayout(container)
    layout.setContentsMargins(26, 24, 26, 24)
    layout.setSpacing(16)

    heading = QVBoxLayout()
    heading.setSpacing(5)
    eyebrow = QLabel("LIM0N4IKZ GAMES CLICKER  ·  TELEGRAM")
    eyebrow.setObjectName("eyebrow")
    title = QLabel("Пост об обновлении")
    title.setObjectName("title")
    subtitle = QLabel(
        "Выберите версию, проверьте готовый текст и скопируйте его в канал."
    )
    subtitle.setObjectName("subtitle")
    heading.addWidget(eyebrow)
    heading.addWidget(title)
    heading.addWidget(subtitle)
    layout.addLayout(heading)

    version_card = QFrame()
    version_card.setObjectName("card")
    version_layout = QVBoxLayout(version_card)
    version_layout.setContentsMargins(18, 14, 18, 14)
    version_layout.setSpacing(8)
    version_row = QHBoxLayout()
    version_label = QLabel("ВЕРСИЯ РЕЛИЗА")
    version_label.setObjectName("eyebrow")
    version_row.addWidget(version_label)
    version_row.addStretch()
    latest_badge = QLabel("ПОСЛЕДНЯЯ")
    latest_badge.setObjectName("eyebrow")
    version_row.addWidget(latest_badge)
    version_layout.addLayout(version_row)

    version_picker = QComboBox()
    version_picker.addItems(versions)
    selected_version = initial_version if initial_version in versions else latest_version
    version_picker.setCurrentText(selected_version)
    version_picker.setMinimumHeight(42)
    version_layout.addWidget(version_picker)
    layout.addWidget(version_card)

    preview_card = QFrame()
    preview_card.setObjectName("card")
    preview_layout = QVBoxLayout(preview_card)
    preview_layout.setContentsMargins(18, 16, 18, 16)
    preview_layout.setSpacing(10)
    preview_header = QHBoxLayout()
    preview_label = QLabel("ГОТОВЫЙ ТЕКСТ")
    preview_label.setObjectName("eyebrow")
    counter_label = QLabel()
    counter_label.setObjectName("counter")
    preview_header.addWidget(preview_label)
    preview_header.addStretch()
    preview_header.addWidget(counter_label)
    preview_layout.addLayout(preview_header)

    post_preview = QTextEdit()
    post_preview.setPlaceholderText("Текст поста появится здесь")
    preview_layout.addWidget(post_preview, 1)
    layout.addWidget(preview_card, 1)

    footer = QHBoxLayout()
    status_label = QLabel()
    status_label.setObjectName("status")
    footer.addWidget(status_label, 1)
    copy_button = QPushButton("📋  Копировать готовый пост")
    copy_button.setObjectName("copyButton")
    footer.addWidget(copy_button)
    layout.addLayout(footer)

    def update_preview(version):
        try:
            post_preview.setPlainText(build_post(manifest, version))
            copy_button.setEnabled(True)
            counter_label.setText(
                f"{len(post_preview.toPlainText())} символов"
            )
            latest_badge.setVisible(version == latest_version)
            status_label.setText("Можно скопировать или отредактировать текст.")
        except ValueError as error:
            post_preview.clear()
            counter_label.clear()
            copy_button.setEnabled(False)
            status_label.clear()
            QMessageBox.critical(window, "Не удалось создать пост", str(error))

    def copy_post():
        try:
            application.clipboard().setText(post_preview.toPlainText())
            status_label.setText("✓  Готовый пост скопирован в буфер обмена.")
        except RuntimeError as error:
            QMessageBox.critical(window, "Не удалось скопировать текст", str(error))

    version_picker.currentTextChanged.connect(update_preview)
    copy_button.clicked.connect(copy_post)
    copy_shortcut = QShortcut(QKeySequence("Ctrl+Shift+C"), window)
    copy_shortcut.activated.connect(copy_post)
    update_preview(selected_version)
    window.setCentralWidget(container)
    window.show()
    return application.exec()


def main():
    parser = argparse.ArgumentParser(
        description="Choose a release and copy its Telegram post."
    )
    parser.add_argument(
        "--no-clipboard",
        action="store_true",
        help="Print the post without copying it to the clipboard.",
    )
    parser.add_argument(
        "--version",
        help="Generate this release's post in command-line mode.",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Open the post generator window.",
    )
    args = parser.parse_args()

    manifest_path = Path(__file__).with_name("versions.json")
    try:
        with manifest_path.open(encoding="utf-8") as manifest_file:
            manifest = json.load(manifest_file)
        if args.gui or (args.version is None and not args.no_clipboard):
            return launch_gui(manifest, args.version)

        version = args.version
        if version is None:
            version = choose_version(manifest)
        post = build_post(manifest, version)
        if not args.no_clipboard:
            if sys.platform != "win32":
                raise OSError("Clipboard copying is supported only on Windows")
            subprocess.run(
                ["clip"],
                input=post,
                text=True,
                encoding="utf-8",
                check=True,
            )
    except (
        OSError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
        ImportError,
        ValueError,
    ) as error:
        sys.stderr.buffer.write(
            f"Не удалось подготовить пост: {error}\n".encode("utf-8")
        )
        return 1

    sys.stdout.buffer.write((post + "\n").encode("utf-8"))
    if not args.no_clipboard:
        sys.stderr.write("Copied post to clipboard.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
