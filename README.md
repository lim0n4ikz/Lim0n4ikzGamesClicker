# 🍋 Lim0n4ikzGames Clicker

**Lim0n4ikzGames Clicker** is an automatic clicker for Windows with support for keyboard keys, mouse buttons, sequences, and key combinations.

The application allows you to automate repetitive actions using customizable intervals, hotkeys, and profiles.

---

## ✨ Features

* 🖱️ Automatic mouse button clicking
* ⌨️ Automatic keyboard key pressing
* 🔗 Support for key combinations
* 🔄 Support for action sequences
* ⏱️ Customizable intervals between actions
* 🎲 Randomized intervals between actions
* 🔒 Key hold mode
* ⚡ Instant press mode
* 🎮 Start and stop hotkeys
* 💾 Automatic settings saving
* 📋 Custom user profiles
* 🌐 Russian and English language support
* 🌙 Dark interface
* 🖥️ Runs in the background after launch

---

## 🖥️ Screenshot

<p align="center">
  <img src="screenshots/main.png" alt="Lim0n4ikzGames Clicker" width="700">
</p>

---

## 🎮 Operation Modes

The application supports four operation modes.

### 1. 🔒 Hold Key

The selected key is held down for a specified amount of time.

You can configure:

* the key;
* hold duration;
* interval between actions;
* randomized interval.

---

### 2. 🔄 Sequential Press

Allows you to record a sequence of keyboard keys or mouse buttons.

For example:

```text
1 → 2 → 3 → LMB → SPACE
```

After recording, the application will repeat the specified sequence.

Actions are separated using:

```text
,
```

---

### 3. ⚡ Instant Press

Presses a keyboard key or mouse button once without holding it.

For example:

```text
SPACE
```

or:

```text
LMB
```

You can configure the minimum and maximum interval between presses.

---

### 4. 🔗 Instant Combination

Allows multiple keys to be pressed simultaneously.

For example:

```text
CTRL + C
```

or:

```text
SHIFT + SPACE
```

Keys in a combination are separated using:

```text
+
```

---

## ⌨️ Hotkeys

The default hotkeys are:

| Action   | Key  |
| -------- | ---- |
| ▶️ Start | `F6` |
| ⏹️ Stop  | `F7` |

Hotkeys can be changed in the application settings.

Global hotkeys can also be disabled if needed.

---

## 🖱️ Supported Mouse Buttons

The application supports:

* `LMB` — Left Mouse Button
* `RMB` — Right Mouse Button
* `MMB` — Middle Mouse Button
* `X1`
* `X2`

Keyboard keys can also be used.

---

## ⏱️ Intervals

For automatic actions, you can configure:

* minimum interval;
* maximum interval;
* hold duration;
* delay between actions.

### 🎲 Randomized Interval

When randomized intervals are enabled, the application chooses a delay between the specified minimum and maximum values.

For example:

```text
Minimum: 0.5 sec
Maximum: 1.0 sec
```

Each subsequent action may be performed after a different delay within the specified range.

---

## 📋 Profiles

The application includes a profile system.

A profile allows you to save a separate clicker configuration and quickly switch between different sets of settings.

The project includes the following default profiles:

| Profile                | Mode          |    Interval | Key   |
| ---------------------- | ------------- | ----------: | ----- |
| 🪱 Worm Digging        | Instant Press |   `8.6–9.0` | `1`   |
| 🎰 Casino              | Instant Press |   `8.0–9.0` | `F`   |
| ⛏️ Lumberjack / Mining | Instant Press | `0.01–0.01` | `LMB` |
| 🧰 IRP                 | Instant Press | `7200–7200` | `2`   |

Users can create and modify their own profiles.

---

## 💾 Settings Persistence

Application settings and profiles are saved automatically.

In the installed Windows version, they are stored in:

```text
%LOCALAPPDATA%\Lim0n4ikzGamesClicker\
```

Main files:

```text
settings.json
profiles.json
```

`settings.json` contains application settings.

`profiles.json` contains saved profiles.

Settings and profiles are automatically saved when the application is closed.

---

## 🌐 Interface Language

The application supports:

* 🇷🇺 Russian
* 🇬🇧 English

The language can be changed directly in the application settings.

---

# 📦 Installation

For normal installation, **you do not need Python or any manual dependency installation**.

Use the provided installer:

```text
Lim0n4ikzGamesClickerSetup.exe
```

### Installation

1. Run:

```text
Lim0n4ikzGamesClickerSetup.exe
```

2. Follow the installer instructions.
3. Wait for the installation to complete.
4. Launch **Lim0n4ikzGames Clicker** using the created shortcut.

After installation, the application is ready to use.

---

# 🛠️ Building from Source

If you want to build the application yourself, you can use PyInstaller.

## Requirements

The following are required:

* Windows
* Python
* PySide6
* pynput
* PyInstaller

Install the dependencies using:

```cmd
pip install PySide6 pynput pyinstaller
```

---

## 🔨 Build Methods

### Method 1 — Using the BAT File

The easiest way to build the application is to run:

```cmd
build_Lim0n4ikzGamesClicker.bat
```

The BAT file automatically executes the required build commands.

---

### Method 2 — Manually Using PyInstaller

For a manual build, use:

```text
Lim0n4ikzGamesClicker.spec
```

Run:

```cmd
pyinstaller Lim0n4ikzGamesClicker.spec
```

After a successful build, the generated files will appear in:

```text
dist\
```

---

## 🎨 Application Icon

The application uses the following icon:

```text
lim0n4ikzgames.ico
```

When building the application manually, make sure the icon file is present in the project and included in the build configuration.

---

# 📁 Project Structure

Example project structure:

```text
Lim0n4ikzGamesClicker/
│
├── lim0n4ikzgames.ico
├── Lim0n4ikzGamesClicker.spec
├── build_Lim0n4ikzGamesClicker.bat
├── Lim0n4ikzGamesClickerSetup.exe
│
├── settings.json
├── profiles.json
│
└── source files
```

---

# ⚙️ Default Settings

| Setting                | Value     |
| ---------------------- | --------- |
| ▶️ Start Hotkey        | `F6`      |
| ⏹️ Stop Hotkey         | `F7`      |
| ⌨️ Click Key           | `SPACE`   |
| Minimum Interval       | `0.5 sec` |
| Maximum Interval       | `1.0 sec` |
| Hold Duration          | `1.0 sec` |
| Delay Between Actions  | `0.2 sec` |
| 🎲 Randomized Interval | Enabled   |
| 🌐 Language            | Russian   |
| ⌨️ Hotkeys             | Enabled   |

---

# ⛔ Stopping the Clicker

Automatic actions can be stopped using the following hotkey:

```text
F7
```

If different hotkeys are configured, they can be changed in the application settings.

`Esc` can also be used to cancel certain input operations, such as sequence recording or key capture.

---

# 🔐 Disclaimer

The application is intended for automating repetitive actions.

The use of automation in games and other applications may be restricted by their rules or terms of service. The user is responsible for how the software is used.

---

# 🧰 Technologies

The project uses:

* **Python**
* **PySide6** — graphical user interface
* **pynput** — keyboard and mouse control
* **PyInstaller** — executable application building

---

# 🐛 Bugs & Suggestions

If you find a bug or have a suggestion for an improvement, please create an **Issue** in the project repository.

When reporting a bug, please include:

* application version;
* Windows version;
* selected operation mode;
* keys or mouse buttons being used;
* steps required to reproduce the issue;
* error message, if one appears.

---

# ⭐ Support the Project

If you find the project useful, consider giving the repository a ⭐ **Star**.

It helps the project grow and shows that the application is useful to the community.

---

## 📄 License

**Lim0n4ikzGames Clicker** is distributed under the **Lim0n4ikzGames Clicker Non-Commercial License**.

You are free to:

* use the software for personal purposes;
* fork the repository;
* publish the source code on GitHub;
* modify the software for non-commercial purposes;
* publish non-commercial forks and modifications.

**Commercial use, selling, reselling, paid distribution, and inclusion in commercial projects are prohibited without prior written permission from the copyright holder.**

See the [`LICENSE`](LICENSE.md) file for the complete terms.

---

### 🍋 Lim0n4ikzGames Clicker

**Automation. Simplicity. Convenience.**
