import tkinter as tk
from tkinter import ttk, messagebox
from pynput import keyboard, mouse
import threading
import time
import random
import sys
import os

# Для корректного отображения в панели задач Windows
if sys.platform == "win32":
    import ctypes
    myappid = "mycompany.zloyclicker.version.1"
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    
def resource_path(relative_path):
    """Return a path to a bundled resource both in source and PyInstaller builds."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


def set_windows_icon(root, icon_path):
    """Set the icon for the Tk window and Windows taskbar when possible."""
    if sys.platform != "win32" or not os.path.isfile(icon_path):
        return

    # Tk's iconbitmap is the normal path and also works with a bundled .ico.
    try:
        root.iconbitmap(icon_path)
        root.iconbitmap(default=icon_path)
    except tk.TclError:
        pass

    # Also set the native Win32 small/large window icons. This helps Windows
    # keep the same icon in the title bar and taskbar for a windowed build.
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32

        hwnd = wintypes.HWND(root.winfo_id())
        LR_LOADFROMFILE = 0x00000010
        IMAGE_ICON = 1
        LR_DEFAULTSIZE = 0x00000040
        ICON_SMALL = 0
        ICON_BIG = 1
        WM_SETICON = 0x0080

        hicon_big = user32.LoadImageW(
            None, icon_path, IMAGE_ICON, 32, 32, LR_LOADFROMFILE
        )
        hicon_small = user32.LoadImageW(
            None, icon_path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE
        )

        if hicon_big:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_big)
        if hicon_small:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)

        # Keep the AppUserModelID consistent with the one set above.
        try:
            shell32.SetCurrentProcessExplicitAppUserModelID(
                "Lim0n4ikzGamesClicker"
            )
        except Exception:
            pass
    except Exception:
        pass

class Lim0n4ikzGamesClicker:
    MODE_HOLD = "Зажатие клавиши"
    MODE_SEQUENCE = "Последовательное нажатие"
    MODE_INSTANT = "Мгновенное нажатие"
    MODE_COMBO = "Мгновенная комбинация"

    def __init__(self, root):
        self.root = root
        self.root.title("Lim0n4ikzGames Clicker")
        self.root.geometry("700x900")
        self.root.minsize(700, 900)
        self.root.resizable(False, False)

        icon_path = resource_path("lim0n4ikzgames.ico")
        set_windows_icon(self.root, icon_path)

        self.clicking = False
        self.hotkeys_enabled = False
        self.closed = False
        self.click_lock = threading.Lock()
        self.listeners_started = False  # флаг, что слушатели уже запущены

        self.waiting_for_click_key = False
        self.waiting_for_start_key = False
        self.waiting_for_stop_key = False

        self.start_hotkey = {keyboard.Key.f6}
        self.stop_hotkey = {keyboard.Key.f7}
        self.pressed_keys = set()
        self.binding_capture_keys = set()

        self.start_key = keyboard.Key.f6
        self.start_key_type = "keyboard"
        self.stop_key = keyboard.Key.f7
        self.stop_key_type = "keyboard"
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

        # --- ЯЗЫК ---
        self.language = 'ru'
        self.init_translations()

        self.create_styles()
        self.create_ui()
        self.update_language()

        # Слушатели НЕ создаются и не запускаются здесь
        self.keyboard_listener = None
        self.mouse_listener = None

        self.root.protocol("WM_DELETE_WINDOW", self.close)

    # ---------- Метод для запуска слушателей (по требованию) ----------
    def _ensure_listeners_started(self):
        if self.listeners_started or self.closed:
            return
        self.keyboard_listener = keyboard.Listener(
            on_press=self.on_key_press,
            on_release=self.on_key_release
        )
        self.keyboard_listener.start()
        time.sleep(0.05)

        self.mouse_listener = mouse.Listener(on_click=self.on_mouse_click)
        self.mouse_listener.start()
        time.sleep(0.05)

        self.listeners_started = True

    # ==========================================================
    # ЛОКАЛИЗАЦИЯ
    # ==========================================================
    def init_translations(self):
        self.translations = {
            'ru': {
                'title': "Lim0n4ikzGames Clicker",
                'subtitle': "Автоматизация клавиш и комбинаций",
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
                'mode_instant': "Мгновенное нажатие",
                'mode_hold': "Зажатие клавиши",
                'mode_sequence': "Последовательное нажатие",
                'mode_combo': "Мгновенная комбинация",
                'label_mode': "Режим работы",
                'label_settings': "Параметры",
                'label_click_key': "Клавиша / кнопка",
                'label_assigned': "Назначенная:",
                'button_assign': "Назначить",
                'label_interval': "Интервал между циклами",
                'label_min': "Минимум:",
                'label_max': "Максимум:",
                'label_sec': "сек.",
                'label_sequence': "Последовательность / комбинация",
                'label_keys': "Клавиши:",
                'label_interval_seq': "Интервал:",
                'button_apply': "Применить",
                'button_clear': "Очистить",
                'label_hold': "Параметры зажатия",
                'label_hold_duration': "Держать:",
                'label_control': "Управление",
                'button_start': "▶  Начать",
                'button_stop': "■  Остановить",
                'button_emergency': "Аварийная остановка (Esc)",
                'button_hotkeys_enable': "Включить Горячие клавиши",
                'button_hotkeys_disable': "Выключить",
                'label_hotkey_bindings': "Бинды запуска и остановки",
                'label_start_binding': "Запуск:",
                'label_stop_binding': "Остановка:",
                'label_bindings_disabled': "Бинды выключены",
                'label_hotkey_info': "{} — запуск | {} — остановка",
                'memo_main_title': "Памятка для Majestic RP",
                'memo_main_text': (
                    "Копание червей\n"
                    "Рекомендуемый режим:\n"
                    "Мгновенное нажатие\n"
                    "Интервал: 8.6–9 сек\n"
                    "Клавиша нажатия: Быстрый слот, где лопата (1/2/3)\n\n"
                    "Казино (игровые автоматы)\n"
                    "Рекомендуемый режим:\n"
                    "Мгновенное нажатие\n"
                    "Интервал: 8–9 сек\n"
                    "Клавиша нажатия: F\n\n"
                    "Лесоруб, шахта, карьер\n"
                    "Рекомендуемый режим:\n"
                    "Мгновенное нажатие\n"
                    "Интервал: 0.01-0.01 сек\n"
                    "Клавиша нажатия: ЛКМ\n\n"
                    "ИРП каждые 2 часа\n"
                    "Рекомендуемый режим:\n"
                    "Мгновенное нажатие\n"
                    "Интервал: 7200-7200 сек\n"
                    "Клавиша нажатия: Быстрый слот, где ИРП (1/2/3)"
                ),
                'memo_mode_title': "Полезная информация",
                'memo_mode_default': "Выберите режим для получения подсказки.",
                'info_instant': (
                    "Мгновенное нажатие\n"
                    "• Одно нажатие за цикл.\n"
                    "• Используйте для повторяющихся действий (копка, казино).\n"
                    "• Рекомендуется для большинства задач.\n"
                    "• Настройте интервал под нужную задержку."
                ),
                'info_hold': (
                    "Зажатие клавиши\n"
                    "• Клавиша удерживается заданное время.\n"
                    "• Полезно для удержания кнопок (например, Shift для бега).\n"
                    "• Укажите длительность зажатия в поле «Держать».\n"
                    "• После отпускания цикл повторяется."
                ),
                'info_combo': (
                    "Мгновенная комбинация\n"
                    "• Одновременно зажимает несколько клавиш.\n"
                    "• Можно добавлять любое количество клавиш.\n"
                    "• Подходит для быстрых комбинаций (например, Ctrl+C)."
                ),
                'info_sequence': (
                    "Последовательное нажатие\n"
                    "• Нажимает несколько клавиш по очереди.\n"
                    "• Интервал между нажатиями регулируется отдельно в поле «Интервал».\n"
                    "• Отлично для макросов с несколькими действиями."
                ),
                'hint_instant': "(для мгновенного нажатия используется назначенная клавиша)",
                'hint_hold': "(для зажатия используется назначенная клавиша)",
                'hint_sequence': "Задайте список через последовательное\n нажатие клавиш на клавиатуре.",
                'hint_combo': "Задайте список через последовательное\n нажатие клавиш на клавиатуре.",
                'placeholder_sequence': "Например: SPACE, ENTER, ЛКМ, W",
                'placeholder_combo': "Например: CTRL+SHIFT+W",
                'error_sequence_parse': "Проверьте формат ввода.\nДля последовательности используйте запятые (SPACE, ENTER, ЛКМ, w).\nДля комбинации – плюсы (CTRL+SHIFT+w).",
                'footer': "Creator's Discord - lim0n4ikz",
                'lang_ru': "Русский",
                'lang_en': "English",
                'label_language': "Язык",
            },
            'en': {
                'title': "Lim0n4ikzGames Clicker",
                'subtitle': "Keyboard and combinations automation",
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
                'mode_instant': "Instant press",
                'mode_hold': "Hold key",
                'mode_sequence': "Sequence press",
                'mode_combo': "Instant combo",
                'label_mode': "Mode",
                'label_settings': "Settings",
                'label_click_key': "Key / Button",
                'label_assigned': "Assigned:",
                'button_assign': "Assign",
                'label_interval': "Cycle interval",
                'label_min': "Min:",
                'label_max': "Max:",
                'label_sec': "sec.",
                'label_sequence': "Sequence / Combo",
                'label_keys': "Keys:",
                'label_interval_seq': "Interval:",
                'button_apply': "Apply",
                'button_clear': "Clear",
                'label_hold': "Hold settings",
                'label_hold_duration': "Hold:",
                'label_control': "Control",
                'button_start': "▶  Start",
                'button_stop': "■  Stop",
                'button_emergency': "Emergency stop (Esc)",
                'button_hotkeys_enable': "Enable Hotkeys",
                'button_hotkeys_disable': "Disable",
                'label_hotkey_bindings': "Start/Stop bindings",
                'label_start_binding': "Start:",
                'label_stop_binding': "Stop:",
                'label_bindings_disabled': "Bindings disabled",
                'label_hotkey_info': "{} — start | {} — stop",
                'memo_main_title': "Tips for Majestic RP",
                'memo_main_text': (
                    "Digging worms\n"
                    "Recommended mode:\n"
                    "Instant press\n"
                    "Interval: 8.6–9 sec\n"
                    "Press key: Quick slot where shovel is (1/2/3)\n\n"
                    "Casino (slot machines)\n"
                    "Recommended mode:\n"
                    "Instant press\n"
                    "Interval: 8–9 sec\n"
                    "Press key: F\n\n"
                    "Lumberjack, mine, quarry\n"
                    "Recommended mode:\n"
                    "Instant press\n"
                    "Interval: 0.01-0.01 sec\n"
                    "Press key: LMB\n\n"
                    "IRP every 2 hours\n"
                    "Recommended mode:\n"
                    "Instant press\n"
                    "Interval: 7200-7200 sec\n"
                    "Press key: Quick slot where IRP is (1/2/3)"
                ),
                'memo_mode_title': "Useful info",
                'memo_mode_default': "Select a mode for hints.",
                'info_instant': (
                    "Instant press\n"
                    "• One press per cycle.\n"
                    "• Use for repetitive actions (digging, casino).\n"
                    "• Recommended for most tasks.\n"
                    "• Adjust the interval for the desired delay."
                ),
                'info_hold': (
                    "Hold key\n"
                    "• The key is held for a specified time.\n"
                    "• Useful for holding buttons (e.g., Shift for running).\n"
                    "• Set the hold duration in the 'Hold' field.\n"
                    "• After release, the cycle repeats."
                ),
                'info_combo': (
                    "Instant combo\n"
                    "• Presses several keys simultaneously.\n"
                    "• Any number of keys can be added.\n"
                    "• Suitable for quick combinations (e.g., Ctrl+C)."
                ),
                'info_sequence': (
                    "Sequence press\n"
                    "• Presses several keys one after another.\n"
                    "• The interval between presses is set separately in the 'Interval' field.\n"
                    "• Great for macros with multiple actions."
                ),
                'hint_instant': "(for instant press, the assigned key is used)",
                'hint_hold': "(for holding, the assigned key is used)",
                'hint_sequence': "Enter the list by sequentially\n pressing keys on the keyboard.",
                'hint_combo': "Enter the combo by sequentially\n pressing keys on the keyboard.",
                'placeholder_sequence': "E.g.: SPACE, ENTER, LMB, W",
                'placeholder_combo': "E.g.: CTRL+SHIFT+W",
                'error_sequence_parse': "Check the input format.\nFor sequence use commas (SPACE, ENTER, LMB, w).\nFor combo use plus signs (CTRL+SHIFT+w).",
                'footer': "Creator's Discord - lim0n4ikz",
                'lang_ru': "Russian",
                'lang_en': "English",
                'label_language': "Language",
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

    def update_language(self):
        # Заголовок и подзаголовок
        self.title_label.config(text=self.tr('title'))
        self.subtitle_label.config(text=self.tr('subtitle'))

        # Статус
        self.set_status(self.tr('status_stopped'), 'green')

        # Рамка языка
        self.lang_frame.config(text=self.tr('label_language'))

        for rb in self.lang_buttons:
            if rb['value'] == 'ru':
                rb.config(text=self.tr('lang_ru'))
            else:
                rb.config(text=self.tr('lang_en'))

        self.mode_frame.config(text=self.tr('label_mode'))
        self.settings_frame.config(text=self.tr('label_settings'))
        self.click_key_frame.config(text=self.tr('label_click_key'))
        self.interval_frame.config(text=self.tr('label_interval'))
        self.sequence_frame.config(text=self.tr('label_sequence'))
        self.hold_frame.config(text=self.tr('label_hold'))
        self.control_frame.config(text=self.tr('label_control'))
        self.hotkey_frame.config(text=self.tr('label_hotkey_bindings'))

        self.lbl_assigned.config(text=self.tr('label_assigned'))
        self.lbl_min.config(text=self.tr('label_min'))
        self.lbl_max.config(text=self.tr('label_max'))
        self.lbl_sec1.config(text=self.tr('label_sec'))
        self.lbl_sec2.config(text=self.tr('label_sec'))
        self.lbl_keys.config(text=self.tr('label_keys'))
        self.lbl_interval_seq.config(text=self.tr('label_interval_seq'))
        self.lbl_hold_duration.config(text=self.tr('label_hold_duration'))
        self.lbl_start_binding.config(text=self.tr('label_start_binding'))
        self.lbl_stop_binding.config(text=self.tr('label_stop_binding'))

        self.start_button.config(text=self.tr('button_start'))
        self.stop_button.config(text=self.tr('button_stop'))
        self.emergency_button.config(text=self.tr('button_emergency'))
        self.enable_hotkeys_button.config(text=self.tr('button_hotkeys_enable'))
        self.disable_hotkeys_button.config(text=self.tr('button_hotkeys_disable'))
        self.bind_click_button.config(text=self.tr('button_assign'))
        self.bind_start_button.config(text=self.tr('button_assign'))
        self.bind_stop_button.config(text=self.tr('button_assign'))
        self.apply_seq_button.config(text=self.tr('button_apply'))
        self.clear_seq_button.config(text=self.tr('button_clear'))

        mode_values = [
            self.tr('mode_instant'),
            self.tr('mode_hold'),
            self.tr('mode_combo'),
            self.tr('mode_sequence'),
        ]
        self.mode_combo['values'] = mode_values
        current_mode_translated = self.tr_mode(self.current_mode)
        self.mode_var.set(current_mode_translated)

        self.memo_main_widget.configure(state="normal")
        self.memo_main_widget.delete("1.0", tk.END)
        self.memo_main_widget.insert("1.0", self.tr('memo_main_text'))
        self._apply_bold_tags(self.memo_main_widget)
        self.memo_main_widget.configure(state="disabled")
        self.memo_main_frame.config(text=self.tr('memo_main_title'))

        self.memo_mode_frame.config(text=self.tr('memo_mode_title'))
        self.update_mode_info()
        self.update_info()

        mode = self.current_mode
        if mode == self.MODE_COMBO:
            placeholder = self.tr('placeholder_combo')
        else:
            placeholder = self.tr('placeholder_sequence')
        if self.sequence_placeholder_active:
            self.sequence_text.delete("1.0", tk.END)
            self.sequence_text.insert("1.0", placeholder)
            self.sequence_text.config(fg="#999999")

        self.footer_label.config(text=self.tr('footer'))
        self.update_mode_ui()

    # ==========================================================
    # СТИЛИ
    # ==========================================================
    def create_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Card.TLabelframe", padding=8)
        style.configure("Card.TLabelframe.Label", font=("Segoe UI", 10, "bold"))
        style.configure("TButton", font=("Segoe UI", 9))
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))
        style.configure("TCombobox", font=("Segoe UI", 9))

    # ==========================================================
    # GUI
    # ==========================================================
    def create_ui(self):
        self.root.configure(bg="#f4f4f4")

        top_frame = tk.Frame(self.root, bg="#f4f4f4")
        top_frame.pack(fill="x", padx=18, pady=(5, 0))

        left_top = tk.Frame(top_frame, bg="#f4f4f4")
        left_top.pack(side="left", fill="both", expand=True)

        self.title_label = tk.Label(
            left_top,
            text=self.tr('title'),
            font=("Segoe UI", 24, "bold"),
            bg="#f4f4f4",
        )
        self.title_label.pack(anchor="w")

        self.subtitle_label = tk.Label(
            left_top,
            text=self.tr('subtitle'),
            font=("Segoe UI", 10),
            fg="#666666",
            bg="#f4f4f4",
        )
        self.subtitle_label.pack(anchor="w")

        self.status_label = tk.Label(
            left_top,
            text=self.tr('status_stopped'),
            font=("Segoe UI", 10, "bold"),
            fg="green",
            bg="#f4f4f4",
        )
        self.status_label.pack(anchor="w", pady=(2, 0))

        right_top = tk.Frame(top_frame, bg="#f4f4f4")
        right_top.pack(side="right", fill="y", padx=(10, 0))

        self.lang_frame = ttk.LabelFrame(right_top, text=self.tr('label_language'), style="Card.TLabelframe")
        self.lang_frame.pack(fill="both", expand=True, padx=5, pady=5)

        lang_inner = tk.Frame(self.lang_frame, bg="#f4f4f4")
        lang_inner.pack(padx=5, pady=5)

        self.lang_var = tk.StringVar(value='ru')
        rb_ru = tk.Radiobutton(
            lang_inner, text=self.tr('lang_ru'), variable=self.lang_var,
            value='ru', bg="#f4f4f4", font=("Segoe UI", 9),
            command=self.on_language_changed
        )
        rb_ru.pack(side="left", padx=5)

        rb_en = tk.Radiobutton(
            lang_inner, text=self.tr('lang_en'), variable=self.lang_var,
            value='en', bg="#f4f4f4", font=("Segoe UI", 9),
            command=self.on_language_changed
        )
        rb_en.pack(side="left", padx=5)

        self.lang_buttons = (rb_ru, rb_en)

        main = tk.Frame(self.root, bg="#f4f4f4")
        main.pack(fill="both", expand=True, padx=18, pady=(8, 5))

        left = tk.Frame(main, bg="#f4f4f4", width=350)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)

        right = tk.Frame(main, bg="#f4f4f4", width=330)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)

        self.mode_frame = ttk.LabelFrame(left, text=self.tr('label_mode'), style="Card.TLabelframe")
        self.mode_frame.pack(fill="x", pady=(0, 7))

        self.mode_var = tk.StringVar(value=self.tr_mode(self.current_mode))
        self.mode_combo = ttk.Combobox(
            self.mode_frame,
            textvariable=self.mode_var,
            values=[
                self.tr('mode_instant'),
                self.tr('mode_hold'),
                self.tr('mode_combo'),
                self.tr('mode_sequence'),
            ],
            state="readonly",
            width=33,
        )
        self.mode_combo.pack(fill="x", padx=3, pady=3)
        self.mode_combo.bind("<<ComboboxSelected>>", self.on_mode_changed)

        self.settings_frame = ttk.LabelFrame(left, text=self.tr('label_settings'), style="Card.TLabelframe")
        self.settings_frame.pack(fill="x", pady=7)

        self.click_key_frame = ttk.LabelFrame(left, text=self.tr('label_click_key'), style="Card.TLabelframe")
        row = tk.Frame(self.click_key_frame)
        row.pack(fill="x", padx=8, pady=5)
        self.lbl_assigned = tk.Label(row, text=self.tr('label_assigned'), width=13, anchor="w")
        self.lbl_assigned.pack(side="left")
        self.click_key_label = tk.Label(
            row,
            text=self.get_binding_name(self.click_key, self.click_key_type),
            width=16,
            relief="sunken",
            bg="white",
        )
        self.click_key_label.pack(side="left", padx=5)
        self.bind_click_button = ttk.Button(row, text=self.tr('button_assign'), command=self.bind_click_key)
        self.bind_click_button.pack(side="right")

        self.interval_frame = ttk.LabelFrame(left, text=self.tr('label_interval'), style="Card.TLabelframe")
        self.interval_frame.pack(fill="x", pady=7)

        self.min_interval_var = tk.StringVar(value="0.5")
        self.max_interval_var = tk.StringVar(value="1.0")
        self.hold_duration_var = tk.StringVar(value="1.0")
        self.sequence_interval_var = tk.StringVar(value="0.2")

        r1 = tk.Frame(self.interval_frame)
        r1.pack(fill="x", padx=8, pady=(4, 2))
        self.lbl_min = tk.Label(r1, text=self.tr('label_min'), width=13, anchor="w")
        self.lbl_min.pack(side="left")
        ttk.Entry(r1, textvariable=self.min_interval_var, width=12).pack(side="left")
        self.lbl_sec1 = tk.Label(r1, text=self.tr('label_sec'))
        self.lbl_sec1.pack(side="left", padx=5)

        r2 = tk.Frame(self.interval_frame)
        r2.pack(fill="x", padx=8, pady=(2, 4))
        self.lbl_max = tk.Label(r2, text=self.tr('label_max'), width=13, anchor="w")
        self.lbl_max.pack(side="left")
        ttk.Entry(r2, textvariable=self.max_interval_var, width=12).pack(side="left")
        self.lbl_sec2 = tk.Label(r2, text=self.tr('label_sec'))
        self.lbl_sec2.pack(side="left", padx=5)

        self.sequence_frame = ttk.LabelFrame(left, text=self.tr('label_sequence'), style="Card.TLabelframe")
        sr = tk.Frame(self.sequence_frame)
        sr.pack(fill="x", padx=8, pady=4)
        self.lbl_keys = tk.Label(sr, text=self.tr('label_keys'), width=13, anchor="w")
        self.lbl_keys.pack(side="left")

        self.sequence_text = tk.Text(
            sr,
            font=("Segoe UI", 9),
            relief="sunken",
            bd=1,
            wrap="word",
            height=1,
            width=20,
            bg="white",
            fg="#999999"
        )
        self.sequence_text.pack(side="left", fill="x", expand=True)

        self.sequence_text.bind("<FocusIn>", self._sequence_focus_in)
        self.sequence_text.bind("<FocusOut>", self._sequence_focus_out)
        self.sequence_text.bind("<KeyPress>", self._capture_sequence_key)
        self.sequence_text.bind("<KeyRelease>", self._capture_sequence_key_release)
        self.sequence_text.bind("<<Modified>>", self._on_text_modified)

        self.sequence_placeholder_active = True
        self.sequence_capture_active = False
        self._captured_sequence_tokens = []

        self._set_sequence_placeholder()

        self.hint_label = tk.Label(
            self.sequence_frame,
            text="",
            font=("Segoe UI", 8),
            fg="#555555",
            bg="#f4f4f4",
        )
        self.hint_label.pack(fill="x", padx=8, pady=(0, 2))

        self.interval_row = tk.Frame(self.sequence_frame)
        self.interval_row.pack(fill="x", padx=8, pady=(0, 2))
        self.lbl_interval_seq = tk.Label(self.interval_row, text=self.tr('label_interval_seq'), width=13, anchor="w")
        self.lbl_interval_seq.pack(side="left")
        self.interval_entry = ttk.Entry(self.interval_row, textvariable=self.sequence_interval_var, width=12)
        self.interval_entry.pack(side="left")
        self.lbl_sec3 = tk.Label(self.interval_row, text=self.tr('label_sec'))
        self.lbl_sec3.pack(side="left", padx=5)

        button_row = tk.Frame(self.sequence_frame)
        button_row.pack(fill="x", padx=8, pady=(0, 4))
        self.apply_seq_button = ttk.Button(button_row, text=self.tr('button_apply'), command=self.apply_sequence)
        self.apply_seq_button.pack(side="right", padx=(0, 5))
        self.clear_seq_button = ttk.Button(button_row, text=self.tr('button_clear'), command=self.clear_sequence)
        self.clear_seq_button.pack(side="right")

        self.hold_frame = ttk.LabelFrame(left, text=self.tr('label_hold'), style="Card.TLabelframe")
        hr = tk.Frame(self.hold_frame)
        hr.pack(fill="x", padx=8, pady=4)
        self.lbl_hold_duration = tk.Label(hr, text=self.tr('label_hold_duration'), width=13, anchor="w")
        self.lbl_hold_duration.pack(side="left")
        ttk.Entry(hr, textvariable=self.hold_duration_var, width=12).pack(side="left")
        self.lbl_sec4 = tk.Label(hr, text=self.tr('label_sec'))
        self.lbl_sec4.pack(side="left", padx=5)

        self.control_frame = ttk.LabelFrame(left, text=self.tr('label_control'), style="Card.TLabelframe")
        self.control_frame.pack(fill="x", pady=(7, 0))

        self.start_button = ttk.Button(self.control_frame, text=self.tr('button_start'), command=self.start_clicker, style="Accent.TButton")
        self.start_button.pack(fill="x", padx=10, pady=(5, 3))
        self.stop_button = ttk.Button(self.control_frame, text=self.tr('button_stop'), command=self.stop_clicker)
        self.stop_button.pack(fill="x", padx=10, pady=3)

        self.emergency_button = tk.Button(
            self.control_frame,
            text=self.tr('button_emergency'),
            command=self.stop_clicker,
            bg="#cc0000",
            fg="white",
            font=("Segoe UI", 10, "bold"),
            relief="raised",
            bd=3
        )
        self.emergency_button.pack(fill="x", padx=10, pady=5)

        buttons = tk.Frame(self.control_frame)
        buttons.pack(fill="x", padx=10, pady=(3, 5))
        self.enable_hotkeys_button = ttk.Button(buttons, text=self.tr('button_hotkeys_enable'), command=self.enable_hotkeys)
        self.enable_hotkeys_button.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.disable_hotkeys_button = ttk.Button(buttons, text=self.tr('button_hotkeys_disable'), command=self.disable_hotkeys)
        self.disable_hotkeys_button.pack(side="right", fill="x", expand=True, padx=(4, 0))

        self.hotkey_frame = ttk.LabelFrame(left, text=self.tr('label_hotkey_bindings'), style="Card.TLabelframe")
        self.hotkey_frame.pack(fill="x", pady=7)
        self.start_key_label, self.lbl_start_binding, self.bind_start_button = self._make_bind_row(
            self.hotkey_frame, self.tr('label_start_binding'), self.bind_start_key,
            self.start_hotkey, "hotkey"
        )
        self.stop_key_label, self.lbl_stop_binding, self.bind_stop_button = self._make_bind_row(
            self.hotkey_frame, self.tr('label_stop_binding'), self.bind_stop_key,
            self.stop_hotkey, "hotkey"
        )

        self.info_label = tk.Label(left, text=self.tr('label_bindings_disabled'), font=("Segoe UI", 9), fg="#666666", bg="#f4f4f4")
        self.info_label.pack(pady=(0, 1))

        self.memo_main_frame = ttk.LabelFrame(right, text=self.tr('memo_main_title'), style="Card.TLabelframe")
        self.memo_main_frame.pack(fill="x", pady=(0, 5))
        memo_main_frame_inner = tk.Frame(self.memo_main_frame, height=450)
        memo_main_frame_inner.pack(fill="both", expand=True, padx=5, pady=5)
        memo_main_frame_inner.pack_propagate(False)

        self.memo_main_widget = tk.Text(
            memo_main_frame_inner,
            wrap="word",
            font=("Segoe UI", 10),
            relief="flat",
            bg="#e2f5e1",
            padx=10,
            pady=10,
        )
        self.memo_main_widget.insert("1.0", self.tr('memo_main_text'))
        self.memo_main_widget.configure(state="disabled")

        scroll_main = ttk.Scrollbar(memo_main_frame_inner, orient="vertical", command=self.memo_main_widget.yview)
        self.memo_main_widget.configure(yscrollcommand=scroll_main.set)
        self.memo_main_widget.pack(side="left", fill="both", expand=True)
        scroll_main.pack(side="right", fill="y")

        self._apply_bold_tags(self.memo_main_widget)

        self.memo_mode_frame = ttk.LabelFrame(right, text=self.tr('memo_mode_title'), style="Card.TLabelframe")
        self.memo_mode_frame.pack(fill="x", pady=(5, 0))
        memo_mode_frame_inner = tk.Frame(self.memo_mode_frame, height=200)
        memo_mode_frame_inner.pack(fill="both", expand=True, padx=5, pady=5)
        memo_mode_frame_inner.pack_propagate(False)

        self.memo_mode_widget = tk.Text(
            memo_mode_frame_inner,
            wrap="word",
            font=("Segoe UI", 10),
            relief="flat",
            bg="#f0f8ff",
            padx=10,
            pady=10,
        )
        self.memo_mode_widget.tag_configure("bold", font=("Segoe UI", 10, "bold"))
        self.memo_mode_widget.insert("1.0", self.tr('memo_mode_default'))
        self.memo_mode_widget.configure(state="disabled")

        scroll_mode = ttk.Scrollbar(memo_mode_frame_inner, orient="vertical", command=self.memo_mode_widget.yview)
        self.memo_mode_widget.configure(yscrollcommand=scroll_mode.set)
        self.memo_mode_widget.pack(side="left", fill="both", expand=True)
        scroll_mode.pack(side="right", fill="y")

        self.footer_label = tk.Label(
            self.root,
            text=self.tr('footer'),
            font=("Segoe UI", 9, "bold"),
            fg="#5865F2",
            bg="#f4f4f4",
        )
        self.footer_label.pack(pady=(3, 8))

    def _make_bind_row(self, parent, label, command, binding, binding_type):
        row = tk.Frame(parent)
        row.pack(fill="x", padx=8, pady=3)
        lbl = tk.Label(row, text=label, width=13, anchor="w")
        lbl.pack(side="left")
        if binding_type == "hotkey":
            binding_text = self._hotkey_name(binding)
        else:
            binding_text = self.get_binding_name(binding, binding_type)
        value_lbl = tk.Label(row, text=binding_text, width=16, relief="sunken", bg="white")
        value_lbl.pack(side="left", padx=5)
        btn = ttk.Button(row, text=self.tr('button_assign'), command=command)
        btn.pack(side="right")
        return value_lbl, lbl, btn

    def _apply_bold_tags(self, widget):
        widget.configure(state="normal")
        widget.tag_configure("bold", font=("Segoe UI", 10, "bold"))
        keywords = [
            "Копание червей", "Digging worms",
            "Казино (игровые автоматы)", "Casino (slot machines)",
            "Лесоруб, шахта, карьер", "Lumberjack, mine, quarry",
            "ИРП каждые 2 часа", "IRP every 2 hours",
            "Интервал:", "Interval:",
            "Мгновенное нажатие", "Instant press"
        ]
        for keyword in keywords:
            start = "1.0"
            while True:
                pos = widget.search(keyword, start, stopindex="end")
                if not pos:
                    break
                end = f"{pos}+{len(keyword)}c"
                widget.tag_add("bold", pos, end)
                start = end
        widget.configure(state="disabled")

    def update_mode_info(self):
        mode = self.current_mode
        if mode == self.MODE_INSTANT:
            text = self.tr('info_instant')
        elif mode == self.MODE_HOLD:
            text = self.tr('info_hold')
        elif mode == self.MODE_COMBO:
            text = self.tr('info_combo')
        elif mode == self.MODE_SEQUENCE:
            text = self.tr('info_sequence')
        else:
            text = self.tr('memo_mode_default')
        self.memo_mode_widget.configure(state="normal")
        self.memo_mode_widget.delete("1.0", tk.END)
        self.memo_mode_widget.insert("1.0", text)
        first_line_end = self.memo_mode_widget.search("\n", "1.0", stopindex="end")
        if first_line_end:
            self.memo_mode_widget.tag_add("bold", "1.0", first_line_end)
        else:
            self.memo_mode_widget.tag_add("bold", "1.0", "end-1c")
        self.memo_mode_widget.configure(state="disabled")

    # ==========================================================
    # РАБОТА С ПОЛЕМ ВВОДА ПОСЛЕДОВАТЕЛЬНОСТИ/КОМБИНАЦИИ (Text)
    # ==========================================================
    def _set_sequence_placeholder(self):
        if not hasattr(self, "sequence_text"):
            return
        content = self.sequence_text.get("1.0", "end-1c").strip()
        if content:
            return
        mode = self.current_mode
        if mode == self.MODE_COMBO:
            placeholder = self.tr('placeholder_combo')
        else:
            placeholder = self.tr('placeholder_sequence')
        self.sequence_placeholder_active = True
        self.sequence_capture_active = False
        self._captured_sequence_tokens = []
        self.sequence_text.config(fg="#999999")
        self.sequence_text.delete("1.0", tk.END)
        self.sequence_text.insert("1.0", placeholder)
        self.sequence_text.config(height=1)

    def _sequence_focus_in(self, _event=None):
        if self.sequence_placeholder_active:
            self.sequence_text.delete("1.0", tk.END)
            self.sequence_placeholder_active = False
            self.sequence_text.config(fg="#222222")
        self.sequence_capture_active = True
        self._captured_sequence_tokens = []

    def _sequence_focus_out(self, _event=None):
        self.sequence_capture_active = False
        self._captured_sequence_tokens = []
        content = self.sequence_text.get("1.0", "end-1c").strip()
        if not content:
            self._set_sequence_placeholder()

    def _on_text_modified(self, event=None):
        self.sequence_text.edit_modified(False)
        lines = int(self.sequence_text.index("end-1c").split(".")[0])
        new_height = min(max(lines, 1), 6)
        self.sequence_text.config(height=new_height)

    def _event_key_name(self, event):
        keysym = str(event.keysym)
        special = {
            "space": "SPACE",
            "Return": "ENTER",
            "Escape": "ESC",
            "Tab": "TAB",
            "BackSpace": "BACKSPACE",
            "Delete": "DELETE",
            "Shift_L": "SHIFT",
            "Shift_R": "SHIFT",
            "Control_L": "CTRL",
            "Control_R": "CTRL",
            "Alt_L": "ALT",
            "Alt_R": "ALT",
            "Left": "LEFT_ARROW",
            "Right": "RIGHT_ARROW",
            "Up": "UP",
            "Down": "DOWN",
            "F1": "F1", "F2": "F2", "F3": "F3", "F4": "F4",
            "F5": "F5", "F6": "F6", "F7": "F7", "F8": "F8",
            "F9": "F9", "F10": "F10", "F11": "F11", "F12": "F12",
        }
        if keysym in special:
            return special[keysym]
        char = event.char
        if char and char.isalnum() and len(char) == 1:
            return char.upper()
        return keysym.upper()

    def _capture_sequence_key(self, event):
        if not self.sequence_capture_active:
            return
        key_name = self._event_key_name(event)
        mode = self.current_mode
        if key_name == "BACKSPACE":
            if self._captured_sequence_tokens:
                self._captured_sequence_tokens.pop()
                self._update_sequence_display()
            return "break"
        if mode == self.MODE_COMBO:
            if key_name not in self._captured_sequence_tokens:
                self._captured_sequence_tokens.append(key_name)
                self._update_sequence_display()
            return "break"
        else:  # MODE_SEQUENCE
            if key_name in ("CTRL", "SHIFT", "ALT"):
                if not self._captured_sequence_tokens or self._captured_sequence_tokens[-1] != key_name:
                    self._captured_sequence_tokens.append(key_name)
                    self._update_sequence_display()
                return "break"
            if not self._captured_sequence_tokens or self._captured_sequence_tokens[-1] != key_name:
                self._captured_sequence_tokens.append(key_name)
                self._update_sequence_display()
            return "break"

    def _capture_sequence_key_release(self, event):
        return

    def _update_sequence_display(self):
        mode = self.current_mode
        if mode == self.MODE_COMBO:
            text = "+".join(self._captured_sequence_tokens)
        else:
            text = ", ".join(self._captured_sequence_tokens)
        self.sequence_text.delete("1.0", tk.END)
        self.sequence_text.insert("1.0", text)
        self.sequence_text.config(fg="#222222")
        self._on_text_modified()

    def clear_sequence(self):
        self.sequence_capture_active = False
        self.sequence_placeholder_active = False
        self._captured_sequence_tokens = []
        self.sequence_text.delete("1.0", tk.END)
        self.sequence_text.config(fg="#222222", height=1)
        self.sequence_text.focus_set()
        self.sequence_capture_active = True

    # ==========================================================
    # ОБРАБОТКА МЫШИ ДЛЯ ЗАХВАТА В ПОЛЕ ВВОДА И ГОРЯЧИХ КЛАВИШ
    # ==========================================================
    def on_mouse_click(self, x, y, button, pressed):
        if self.closed:
            return

        if self.waiting_for_click_key and pressed:
            self.click_key = button
            self.click_key_type = "mouse"
            self.waiting_for_click_key = False
            self._update_label(self.click_key_label, self.get_binding_name(button, "mouse"))
            return

        if self.waiting_for_start_key or self.waiting_for_stop_key:
            if pressed:
                self.binding_capture_keys.add(button)
            else:
                if button in self.binding_capture_keys:
                    self._finish_hotkey_capture(
                        "start" if self.waiting_for_start_key else "stop"
                    )
                self.binding_capture_keys.clear()
            return

        if pressed:
            self.pressed_keys.add(button)
            if self.hotkeys_enabled:
                if self._hotkey_match(self.pressed_keys, self.start_hotkey):
                    self.safe_after(self.start_clicker)
                elif self._hotkey_match(self.pressed_keys, self.stop_hotkey):
                    self.safe_after(self.stop_clicker)
        else:
            self.pressed_keys.discard(button)

        if not pressed:
            return

        try:
            widget_under = self.root.winfo_containing(x, y)
        except Exception:
            return

        if widget_under != self.sequence_text and not self._is_child_of(widget_under, self.sequence_text):
            return

        if not self.sequence_capture_active:
            return

        btn_name = self.mouse_to_string(button)
        mode = self.current_mode
        if mode == self.MODE_COMBO:
            if btn_name not in self._captured_sequence_tokens:
                self._captured_sequence_tokens.append(btn_name)
                self._update_sequence_display()
        else:
            if not self._captured_sequence_tokens or self._captured_sequence_tokens[-1] != btn_name:
                self._captured_sequence_tokens.append(btn_name)
                self._update_sequence_display()

    def _is_child_of(self, child, parent):
        while child:
            if child == parent:
                return True
            try:
                child = child.master
            except AttributeError:
                break
        return False

    # ==========================================================
    # ПРИМЕНЕНИЕ ПОСЛЕДОВАТЕЛЬНОСТИ / КОМБИНАЦИИ
    # ==========================================================
    def apply_sequence(self, show_error=False):
        try:
            if self.sequence_placeholder_active:
                raw = ""
            else:
                raw = self.sequence_text.get("1.0", "end-1c").strip()
            if not raw:
                raise ValueError
            items = self.parse_sequence(raw)
            if items is None or not items:
                raise ValueError
            mode = self.current_mode
            if mode == self.MODE_COMBO:
                if len(items) < 2:
                    raise ValueError
                self.sequence_keys = items
                return True
            else:  # MODE_SEQUENCE
                interval = self._positive_float(self.sequence_interval_var.get())
                self.sequence_keys = items
                self.sequence_interval = interval
                return True
        except ValueError:
            if show_error:
                messagebox.showerror(
                    "Ошибка",
                    self.tr('error_sequence_parse')
                )
            return False

    # ==========================================================
    # ОСТАЛЬНЫЕ МЕТОДЫ
    # ==========================================================
    def update_mode_ui(self):
        mode = self.current_mode
        self.sequence_frame.pack_forget()
        self.hold_frame.pack_forget()
        self.click_key_frame.pack_forget()
        if mode == self.MODE_HOLD:
            self.click_key_frame.pack(fill="x", pady=7)
            self.hold_frame.pack(fill="x", pady=7)
            self.hint_label.config(text=self.tr('hint_hold'))
        elif mode == self.MODE_SEQUENCE:
            self.sequence_frame.pack(fill="x", pady=7)
            self.interval_row.pack(fill="x", padx=8, pady=(0, 2))
            self.hint_label.config(text=self.tr('hint_sequence'))
            if self.sequence_placeholder_active or not self.sequence_text.get("1.0", "end-1c").strip():
                self.sequence_text.delete("1.0", tk.END)
                self._set_sequence_placeholder()
        elif mode == self.MODE_COMBO:
            self.sequence_frame.pack(fill="x", pady=7)
            self.interval_row.pack_forget()
            self.hint_label.config(text=self.tr('hint_combo'))
            if self.sequence_placeholder_active or not self.sequence_text.get("1.0", "end-1c").strip():
                self.sequence_text.delete("1.0", tk.END)
                self._set_sequence_placeholder()
        else:  # INSTANT
            self.click_key_frame.pack(fill="x", pady=7)
            self.hint_label.config(text=self.tr('hint_instant'))
        self.update_mode_info()

    def on_mode_changed(self, _event=None):
        selected = self.mode_var.get()
        mapping = {
            self.tr('mode_instant'): self.MODE_INSTANT,
            self.tr('mode_hold'): self.MODE_HOLD,
            self.tr('mode_sequence'): self.MODE_SEQUENCE,
            self.tr('mode_combo'): self.MODE_COMBO,
        }
        new_mode = mapping.get(selected, self.MODE_INSTANT)
        if new_mode != self.current_mode:
            self.current_mode = new_mode
            self.sequence_capture_active = False
            self._captured_sequence_tokens = []
            self.update_mode_ui()
            self.set_status(self.tr('status_mode', self.tr_mode(self.current_mode)), "green")

    def on_language_changed(self):
        new_lang = self.lang_var.get()
        if new_lang != self.language:
            self.language = new_lang
            self.update_language()
            self.set_status(self.tr('status_mode', self.tr_mode(self.current_mode)), "green")

    # ---------- Кликер ----------
    def start_clicker(self):
        if self.closed:
            return
        with self.click_lock:
            if self.clicking:
                return
            self.current_mode = self.mode_var.get()
            mapping = {
                self.tr('mode_instant'): self.MODE_INSTANT,
                self.tr('mode_hold'): self.MODE_HOLD,
                self.tr('mode_sequence'): self.MODE_SEQUENCE,
                self.tr('mode_combo'): self.MODE_COMBO,
            }
            self.current_mode = mapping.get(self.current_mode, self.MODE_INSTANT)

            try:
                minimum = self._positive_float(self.min_interval_var.get())
                maximum = self._positive_float(self.max_interval_var.get())
                if minimum > maximum:
                    raise ValueError
                self.min_interval = minimum
                self.max_interval = maximum
                if self.current_mode == self.MODE_HOLD:
                    self.hold_duration = self._positive_float(self.hold_duration_var.get())
                elif self.current_mode in (self.MODE_SEQUENCE, self.MODE_COMBO):
                    if not self.apply_sequence(show_error=True):
                        return
            except ValueError:
                self.set_status(self.tr('status_error'), "red")
                return
            self.clicking = True
        self.set_status(self.tr('status_running'), "red")
        self.start_button.config(state="disabled")
        self.stop_button.config(state="normal")
        threading.Thread(target=self.click_loop, daemon=True).start()

    def stop_clicker(self):
        with self.click_lock:
            self.clicking = False
        self.pressed_keys.clear()
        if self.closed:
            return
        self.set_status(self.tr('status_stopped'), "green")
        self.start_button.config(state="normal")
        self.stop_button.config(state="normal")

    def click_loop(self):
        held = False
        try:
            while True:
                with self.click_lock:
                    active = self.clicking
                if not active or self.closed:
                    break
                mode = self.current_mode
                if mode == self.MODE_HOLD:
                    self.press_only(self.click_key, self.click_key_type)
                    held = True
                    self.set_status(self.tr('status_held', self.get_binding_name(self.click_key, self.click_key_type)), "red")
                    if not self.interruptible_sleep(self.hold_duration):
                        break
                    self.release_only(self.click_key, self.click_key_type)
                    held = False
                    self.set_status(self.tr('status_hold_released'), "red")
                elif mode == self.MODE_SEQUENCE:
                    for item in list(self.sequence_keys):
                        with self.click_lock:
                            if not self.clicking:
                                return
                        self._press_and_release_item(item)
                        self.set_status(self.tr('status_pressed', self._item_to_string(item)), "red")
                        if not self.interruptible_sleep(self.sequence_interval):
                            return
                elif mode == self.MODE_COMBO:
                    combo = list(self.sequence_keys)
                    if combo:
                        self._press_combo(combo)
                        self.set_status(
                            self.tr('status_combo', '+'.join(self._item_to_string(x) for x in combo)),
                            "red"
                        )
                else:  # Мгновенное нажатие
                    self.press_and_release(self.click_key, self.click_key_type)
                    self.set_status(self.tr('status_pressed', self.get_binding_name(self.click_key, self.click_key_type)), "red")
                interval = random.uniform(self.min_interval, self.max_interval)
                if not self.interruptible_sleep(interval):
                    break
                time.sleep(0.001)
        finally:
            if held:
                self.release_only(self.click_key, self.click_key_type)
            self.release_all()

    def _press_and_release_item(self, item):
        if isinstance(item, str):
            self.keyboard_controller.press(item)
            self.keyboard_controller.release(item)
        elif isinstance(item, keyboard.Key) or isinstance(item, keyboard.KeyCode):
            self.keyboard_controller.press(item)
            self.keyboard_controller.release(item)
        elif isinstance(item, mouse.Button):
            self.mouse_controller.click(item)

    def _press_combo(self, items):
        pressed_keys = []
        pressed_mouse = []
        try:
            for item in items:
                if isinstance(item, str):
                    self.keyboard_controller.press(item)
                    pressed_keys.append(item)
                elif isinstance(item, keyboard.Key) or isinstance(item, keyboard.KeyCode):
                    self.keyboard_controller.press(item)
                    pressed_keys.append(item)
                elif isinstance(item, mouse.Button):
                    self.mouse_controller.press(item)
                    pressed_mouse.append(item)
        except Exception:
            pass
        finally:
            for item in reversed(pressed_keys):
                try:
                    self.keyboard_controller.release(item)
                except Exception:
                    pass
            for item in reversed(pressed_mouse):
                try:
                    self.mouse_controller.release(item)
                except Exception:
                    pass

    def _item_to_string(self, item):
        if isinstance(item, str):
            return item.upper()
        elif isinstance(item, keyboard.Key) or isinstance(item, keyboard.KeyCode):
            return self.key_to_string(item)
        elif isinstance(item, mouse.Button):
            return self.mouse_to_string(item)
        return str(item)

    def interruptible_sleep(self, duration):
        end = time.monotonic() + max(0, duration)
        while time.monotonic() < end:
            with self.click_lock:
                active = self.clicking
            if not active or self.closed:
                return False
            time.sleep(min(0.01, max(0.001, end - time.monotonic())))
        return True

    # ---------- Ввод ----------
    def press_only(self, binding, binding_type):
        try:
            if binding_type == "mouse":
                self.mouse_controller.press(binding)
            else:
                self.keyboard_controller.press(binding)
        except Exception:
            pass

    def release_only(self, binding, binding_type):
        try:
            if binding_type == "mouse":
                self.mouse_controller.release(binding)
            else:
                self.keyboard_controller.release(binding)
        except Exception:
            pass

    def press_and_release(self, binding, binding_type):
        try:
            if binding_type == "mouse":
                self.mouse_controller.click(binding)
            else:
                self.keyboard_controller.press(binding)
                self.keyboard_controller.release(binding)
        except Exception:
            pass

    def parse_key_token(self, token):
        mouse_map = {
            "ЛКМ": mouse.Button.left,
            "ПКМ": mouse.Button.right,
            "СКМ": mouse.Button.middle,
            "X1": mouse.Button.x1,
            "X2": mouse.Button.x2,
            "LEFT": mouse.Button.left,
            "RIGHT": mouse.Button.right,
            "MIDDLE": mouse.Button.middle,
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
            "SHIFT_L": keyboard.Key.shift_l,
            "SHIFT_R": keyboard.Key.shift_r,
            "CTRL": keyboard.Key.ctrl,
            "CONTROL": keyboard.Key.ctrl,
            "CTRL_L": keyboard.Key.ctrl_l,
            "CTRL_R": keyboard.Key.ctrl_r,
            "ALT": keyboard.Key.alt,
            "ALT_L": keyboard.Key.alt_l,
            "ALT_R": keyboard.Key.alt_r,
            "F1": keyboard.Key.f1, "F2": keyboard.Key.f2,
            "F3": keyboard.Key.f3, "F4": keyboard.Key.f4,
            "F5": keyboard.Key.f5, "F6": keyboard.Key.f6,
            "F7": keyboard.Key.f7, "F8": keyboard.Key.f8,
            "F9": keyboard.Key.f9, "F10": keyboard.Key.f10,
            "F11": keyboard.Key.f11, "F12": keyboard.Key.f12,
            "UP": keyboard.Key.up, "DOWN": keyboard.Key.down,
            "LEFT_ARROW": keyboard.Key.left, "RIGHT_ARROW": keyboard.Key.right,
            "BACKSPACE": keyboard.Key.backspace,
            "DELETE": keyboard.Key.delete,
        }
        if token in special:
            return special[token]
        if len(token) == 1 and token.isalnum():
            return token.lower()
        if token.startswith("KEY."):
            return self.parse_key_token(token[4:])
        return None

    def parse_sequence(self, raw):
        raw = raw.strip()
        if not raw:
            return []
        if self.current_mode == self.MODE_COMBO:
            parts = [p.strip() for p in raw.split("+") if p.strip()]
        else:
            parts = [p.strip() for p in raw.split(",") if p.strip()]
        result = []
        for token in parts:
            token = token.upper()
            parsed = self.parse_key_token(token)
            if parsed is None:
                return None
            result.append(parsed)
        return result

    # ---------- Горячие клавиши ----------
    def enable_hotkeys(self):
        if self.closed:
            return
        self._ensure_listeners_started()
        self.hotkeys_enabled = True
        self.set_status(self.tr('status_hotkeys_enabled'), "green")
        self.update_info()

    def disable_hotkeys(self):
        if self.closed:
            return
        self.hotkeys_enabled = False
        self.pressed_keys.clear()
        self.set_status(self.tr('status_hotkeys_disabled'), "green")
        self.update_info()

    def _normalize_hotkey_key(self, key):
        try:
            if key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
                return keyboard.Key.ctrl
            if key in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r):
                return keyboard.Key.shift
            if key in (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r):
                return keyboard.Key.alt
        except AttributeError:
            pass
        return key

    def _hotkey_key_name(self, key):
        if isinstance(key, mouse.Button):
            return self.mouse_to_string(key)
        key = self._normalize_hotkey_key(key)
        if key == keyboard.Key.ctrl:
            return "CTRL"
        if key == keyboard.Key.shift:
            return "SHIFT"
        if key == keyboard.Key.alt:
            return "ALT"
        return self.key_to_string(key)

    def _hotkey_name(self, hotkey):
        order = {"CTRL": 0, "SHIFT": 1, "ALT": 2}
        mouse_order = {"ЛКМ": 10, "ПКМ": 11, "СКМ": 12, "X1": 13, "X2": 14}
        names = [self._hotkey_key_name(k) for k in hotkey]
        names.sort(key=lambda n: (order.get(n, mouse_order.get(n, 20)), n))
        return "+".join(names)

    def _hotkey_match(self, pressed, target):
        return pressed == target

    def _finish_hotkey_capture(self, target):
        captured = set(self.binding_capture_keys)
        self.binding_capture_keys.clear()
        if not captured:
            return
        if target == "start":
            self.start_hotkey = captured
            self._update_label(self.start_key_label, self._hotkey_name(captured))
        else:
            self.stop_hotkey = captured
            self._update_label(self.stop_key_label, self._hotkey_name(captured))
        self.waiting_for_start_key = False
        self.waiting_for_stop_key = False
        self.update_info()

    def _hotkey_capture_press(self, key):
        normalized = self._normalize_hotkey_key(key)
        self.binding_capture_keys.add(normalized)

    def _hotkey_capture_release(self, key):
        normalized = self._normalize_hotkey_key(key)
        if normalized in self.binding_capture_keys:
            self._finish_hotkey_capture(
                "start" if self.waiting_for_start_key else "stop"
            )
        self.binding_capture_keys.clear()

    def on_key_press(self, key):
        if self.closed:
            return
        normalized = self._normalize_hotkey_key(key)
        if self.waiting_for_click_key:
            self.click_key = key
            self.click_key_type = "keyboard"
            self.waiting_for_click_key = False
            self._update_label(self.click_key_label, self.get_binding_name(key, "keyboard"))
            return
        if self.waiting_for_start_key or self.waiting_for_stop_key:
            self._hotkey_capture_press(key)
            return
        self.pressed_keys.add(normalized)
        if self.keys_equal(key, keyboard.Key.esc):
            self.safe_after(self.stop_clicker)
            return
        if not self.hotkeys_enabled:
            return
        if self._hotkey_match(self.pressed_keys, self.start_hotkey):
            self.safe_after(self.start_clicker)
        elif self._hotkey_match(self.pressed_keys, self.stop_hotkey):
            self.safe_after(self.stop_clicker)

    def on_key_release(self, key):
        if self.closed:
            return
        normalized = self._normalize_hotkey_key(key)
        if self.waiting_for_start_key or self.waiting_for_stop_key:
            self._hotkey_capture_release(key)
            return
        self.pressed_keys.discard(normalized)

    def bind_click_key(self):
        self._ensure_listeners_started()
        self.waiting_for_click_key = True
        self.waiting_for_start_key = False
        self.waiting_for_stop_key = False
        self.click_key_label.config(text="Нажмите...")
        self.root.focus_set()

    def bind_start_key(self):
        self._ensure_listeners_started()
        self.waiting_for_start_key = True
        self.waiting_for_click_key = False
        self.waiting_for_stop_key = False
        self.binding_capture_keys.clear()
        self.start_key_label.config(text="Нажмите комбинацию...")
        self.root.focus_set()

    def bind_stop_key(self):
        self._ensure_listeners_started()
        self.waiting_for_stop_key = True
        self.waiting_for_click_key = False
        self.waiting_for_start_key = False
        self.binding_capture_keys.clear()
        self.stop_key_label.config(text="Нажмите комбинацию...")
        self.root.focus_set()

    # ---------- Служебные ----------
    def set_status(self, text, color):
        self.safe_after(lambda: self.status_label.config(text=text, fg=color))

    def safe_after(self, function):
        if self.closed:
            return
        try:
            self.root.after(0, function)
        except tk.TclError:
            pass

    def _update_label(self, label, text):
        self.safe_after(lambda: label.config(text=text))

    def _positive_float(self, value):
        number = float(value.replace(",", "."))
        if number <= 0:
            raise ValueError
        return number

    def release_all(self):
        for key in [
            keyboard.Key.space,
            keyboard.Key.shift,
            keyboard.Key.shift_l,
            keyboard.Key.shift_r,
            keyboard.Key.ctrl,
            keyboard.Key.ctrl_l,
            keyboard.Key.ctrl_r,
            keyboard.Key.alt,
            keyboard.Key.alt_l,
            keyboard.Key.alt_r,
            keyboard.Key.enter,
        ]:
            try:
                self.keyboard_controller.release(key)
            except Exception:
                pass
        for btn in [
            mouse.Button.left,
            mouse.Button.right,
            mouse.Button.middle,
            mouse.Button.x1,
            mouse.Button.x2,
        ]:
            try:
                self.mouse_controller.release(btn)
            except Exception:
                pass

    def key_to_string(self, key):
        if key == keyboard.Key.space:
            return "ПРОБЕЛ"
        try:
            if key.char:
                return key.char.upper()
        except AttributeError:
            pass
        return str(key).replace("Key.", "").upper()

    def mouse_to_string(self, button):
        names = {
            mouse.Button.left: "ЛКМ",
            mouse.Button.right: "ПКМ",
            mouse.Button.middle: "СКМ",
            mouse.Button.x1: "X1",
            mouse.Button.x2: "X2",
        }
        return names.get(button, str(button))

    def get_binding_name(self, binding, binding_type):
        if binding_type == "keyboard":
            return self.key_to_string(binding)
        else:
            return self.mouse_to_string(binding)

    def keys_equal(self, key1, key2):
        return str(key1) == str(key2)

    def get_hotkey_info(self):
        start_name = self._hotkey_name(self.start_hotkey)
        stop_name = self._hotkey_name(self.stop_hotkey)
        return self.tr('label_hotkey_info', start_name, stop_name)

    def update_info(self):
        if self.closed:
            return
        if self.hotkeys_enabled:
            self.info_label.config(text=self.get_hotkey_info())
        else:
            self.info_label.config(text=self.tr('label_bindings_disabled'))

    def close(self):
        if self.closed:
            return
        self.closed = True
        with self.click_lock:
            self.clicking = False
        self.hotkeys_enabled = False
        self.pressed_keys.clear()
        self.binding_capture_keys.clear()
        if self.keyboard_listener is not None:
            try:
                self.keyboard_listener.stop()
            except Exception:
                pass
        if self.mouse_listener is not None:
            try:
                self.mouse_listener.stop()
            except Exception:
                pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass

if __name__ == "__main__":
    root = tk.Tk()
    app = Lim0n4ikzGamesClicker(root)
    root.mainloop()