import sys
import markdown
import json
import os
import time
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QTextEdit, QLineEdit, QPushButton, QSlider, QLabel,
                             QDialog, QColorDialog, QFrame, QButtonGroup, QComboBox,
                             QInputDialog, QMessageBox, QSpinBox)
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint, QRect, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QTextCursor
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from google import genai
from google.genai import types

# --- 1. Gelişmiş API / Uç Nokta Yöneticisi ---
class APIDialog(QDialog):
    def __init__(self, parent, api_profiles, active_profile_name, accent_hex):
        super().__init__(parent)
        self.setWindowTitle("API ve Uç Nokta Ayarları")
        self.setMinimumSize(420, 260)
        self.setStyleSheet(self.get_dialog_style(accent_hex))

        layout = QVBoxLayout()

        self.profile_label = QLabel("Aktif API Profili:")
        layout.addWidget(self.profile_label)

        profile_layout = QHBoxLayout()
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(api_profiles.keys())
        self.profile_combo.setCurrentText(active_profile_name)
        self.profile_combo.currentTextChanged.connect(self.load_profile_data)

        self.btn_add = QPushButton("+")
        self.btn_add.setFixedSize(30, 30)
        self.btn_add.clicked.connect(self.add_profile)

        self.btn_delete = QPushButton("-")
        self.btn_delete.setFixedSize(30, 30)
        self.btn_delete.clicked.connect(self.delete_profile)

        profile_layout.addWidget(self.profile_combo)
        profile_layout.addWidget(self.btn_add)
        profile_layout.addWidget(self.btn_delete)
        layout.addLayout(profile_layout)

        self.url_label = QLabel("Base URL (Google Gemini için boş bırakın):")
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Örn: http://localhost:4000/v1")
        layout.addWidget(self.url_label)
        layout.addWidget(self.url_input)

        self.api_label = QLabel("API Anahtarı:")
        self.api_input = QLineEdit()
        self.api_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.api_label)
        layout.addWidget(self.api_input)

        self.save_btn = QPushButton("Kaydet ve Uygula")
        self.save_btn.clicked.connect(self.save_api)
        layout.addWidget(self.save_btn)

        self.setLayout(layout)

        self.api_profiles = api_profiles
        self.load_profile_data(active_profile_name)

    def load_profile_data(self, profile_name):
        if profile_name in self.api_profiles:
            data = self.api_profiles[profile_name]
            self.api_input.setText(data["key"])
            self.url_input.setText(data["url"])

    def add_profile(self):
        text, ok = QInputDialog.getText(self, 'Yeni API Profili', 'Profil Adı (Örn: Gemini Yedek):')
        if ok and text:
            if text not in self.api_profiles:
                self.api_profiles[text] = {"key": "", "url": ""}
                self.profile_combo.addItem(text)
                self.profile_combo.setCurrentText(text)

    def delete_profile(self):
        current = self.profile_combo.currentText()
        if len(self.api_profiles) > 1:
            del self.api_profiles[current]
            self.profile_combo.removeItem(self.profile_combo.currentIndex())
        else:
            QMessageBox.warning(self, "Hata", "En az bir profil kalmak zorundadır!")

    def get_dialog_style(self, accent_hex):
        return f"""
            QDialog {{ background-color: #1a1a1a; }}
            QLabel {{ color: #eeeeee; font-weight: bold; margin-top: 5px; font-size: 13px; }}
            QPushButton {{ background-color: #2a2a2a; color: white; border: 1px solid #444; padding: 6px; font-size: 13px; }}
            QPushButton:hover {{ background-color: #3a3a3a; border: 1px solid {accent_hex}; }}
            QLineEdit, QComboBox {{ background-color: #0a0a0a; color: white; border: 1px solid #444; padding: 6px; font-size: 13px; min-height: 25px; }}
            QLineEdit:focus, QComboBox:focus {{ border: 1px solid {accent_hex}; }}
            QComboBox::drop-down {{ border: none; }}
        """

    def save_api(self):
        profile_name = self.profile_combo.currentText()
        self.api_profiles[profile_name] = {
            "key": self.api_input.text(),
            "url": self.url_input.text()
        }
        self.parent().api_profiles = self.api_profiles
        self.parent().active_api_profile = profile_name
        self.parent().save_config()
        self.accept()

# --- 2. Tools / Persona Kütüphanesi Penceresi ---
class ToolsDialog(QDialog):
    def __init__(self, parent, current_persona, personas, accent_hex):
        super().__init__(parent)
        self.setWindowTitle("Araçlar ve Asistan Profilleri")
        self.setFixedSize(350, 150)
        self.setStyleSheet(parent.get_dialog_style(accent_hex))

        layout = QVBoxLayout()
        self.info_label = QLabel("Asistanın Uzmanlık Alanını (Persona) Seçin:")
        layout.addWidget(self.info_label)

        self.persona_combo = QComboBox()
        self.persona_combo.addItems(personas.keys())
        self.persona_combo.setCurrentText(current_persona)
        layout.addWidget(self.persona_combo)

        self.desc_label = QLabel(personas[current_persona])
        self.desc_label.setWordWrap(True)
        self.desc_label.setStyleSheet("color: gray; font-style: italic; margin-top: 5px; margin-bottom: 10px;")
        layout.addWidget(self.desc_label)

        self.persona_combo.currentTextChanged.connect(
            lambda text: self.desc_label.setText(personas[text])
        )

        self.save_btn = QPushButton("Personayı Aktifleştir")
        self.save_btn.clicked.connect(self.save_tools)
        layout.addWidget(self.save_btn)
        self.setLayout(layout)

    def save_tools(self):
        self.parent().current_persona = self.persona_combo.currentText()
        self.parent().chat_history.append(f"<i style='color:gray;'>Sistem: Persona değiştirildi -> {self.parent().current_persona}</i><br>")
        self.parent().save_config()
        self.accept()

# --- Görünüm Ayarları ---
class SettingsDialog(QDialog):
    def __init__(self, parent, current_alpha, current_bg_color, current_accent_color, current_width, current_height):
        super().__init__(parent)
        self.setWindowTitle("Görünüm ve Boyut Ayarları")
        self.setMinimumSize(320, 380)
        accent_hex = current_accent_color.name()
        self.setStyleSheet(parent.get_dialog_style(accent_hex))

        layout = QVBoxLayout()

        size_layout = QHBoxLayout()
        self.width_label = QLabel("Genişlik:")
        self.width_spin = QSpinBox()
        self.width_spin.setRange(300, 1000)
        self.width_spin.setValue(current_width)

        self.height_label = QLabel("Yükseklik:")
        self.height_spin = QSpinBox()
        self.height_spin.setRange(400, 2000)
        self.height_spin.setValue(current_height)

        size_layout.addWidget(self.width_label)
        size_layout.addWidget(self.width_spin)
        size_layout.addWidget(self.height_label)
        size_layout.addWidget(self.height_spin)
        layout.addLayout(size_layout)

        self.bg_color_label = QLabel("Arka Plan Rengi:")
        self.bg_color_btn = QPushButton("Arka Plan Rengi Seç")
        self.bg_color_btn.clicked.connect(self.choose_bg_color)
        self.selected_bg_color = current_bg_color
        layout.addWidget(self.bg_color_label)
        layout.addWidget(self.bg_color_btn)

        self.accent_color_label = QLabel("Vurgu Rengi (İkon ve İsimler):")
        self.accent_color_btn = QPushButton("Vurgu Rengi Seç")
        self.accent_color_btn.clicked.connect(self.choose_accent_color)
        self.selected_accent_color = current_accent_color
        layout.addWidget(self.accent_color_label)
        layout.addWidget(self.accent_color_btn)

        self.alpha_label = QLabel("Arka Plan Şeffaflığı:")
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(50)
        self.slider.setMaximum(255)
        self.slider.setValue(current_alpha)
        self.slider.setStyleSheet(f"""
            QSlider::handle:horizontal {{ background: {accent_hex}; width: 15px; margin: -5px 0; border-radius: 2px; }}
        """)
        layout.addWidget(self.alpha_label)
        layout.addWidget(self.slider)

        self.save_btn = QPushButton("Kaydet ve Kapat")
        self.save_btn.clicked.connect(self.save_settings)
        layout.addWidget(self.save_btn)
        self.setLayout(layout)

    def choose_bg_color(self):
        color = QColorDialog.getColor(self.selected_bg_color, self, "Arka Plan Rengi Seç")
        if color.isValid(): self.selected_bg_color = color

    def choose_accent_color(self):
        color = QColorDialog.getColor(self.selected_accent_color, self, "Vurgu Rengi Seç")
        if color.isValid(): self.selected_accent_color = color

    def save_settings(self):
        self.parent().update_settings(
            self.slider.value(),
            self.selected_bg_color,
            self.selected_accent_color,
            self.width_spin.value(),
            self.height_spin.value()
        )
        self.accept()

# --- Streaming Worker ---
class ChatWorker(QThread):
    chunk_received = pyqtSignal(str)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, client, model_name, contents, config):
        super().__init__()
        self.client = client
        self.model_name = model_name
        self.contents = contents
        self.config = config

    def run(self):
        try:
            full_response = ""
            for chunk in self.client.models.generate_content_stream(
                model=self.model_name,
                contents=self.contents,
                config=self.config
            ):
                if chunk.text:
                    # Daha akıcı bir "yazma" efekti için küçük bir gecikme (0.01sn)
                    for char in chunk.text:
                        self.chunk_received.emit(char)
                        time.sleep(0.01)
                    full_response += chunk.text
            self.finished.emit(full_response)
        except Exception as e:
            self.error.emit(str(e))

# --- ANA PENCERE SINIFI ---
class GeminiSidebar(QWidget):
    def __init__(self):
        super().__init__()
        self._is_init = True # Açılışta konumun ezilmesini önlemek için
        self._is_dragging = False # Dragging sırasında konum kaydı için
        self.bg_alpha = 230
        self.bg_color = QColor(20, 20, 20)
        self.accent_color = QColor("#ff80ab")
        self.current_mode = "Balanced"
        self.app_width = 450
        self.app_height = 900
        self.active_api_profile = "Ana Gemini Hesabı"
        self.api_profiles = {
            "Ana Gemini Hesabı": {"key": "", "url": ""},
            "Yedek Gemini Hesabı": {"key": "", "url": ""}
        }
        self.current_persona = "Genel Asistan"
        self.personas = {
            "Genel Asistan": "Sen yardımcı, kibar ve çözüm odaklı bir yapay zeka asistanısın.",
            "Arch Linux & KDE Uzmanı": "Sen Arch Linux ve KDE Plasma sistemleri üzerinde uzman bir mühendissin. Yanıtlarında pacman komutlarını kullan.",
            "Yerel AI & Homelab Mimarı": "Sen Docker, LiteLLM uzmanısın...",
            "Sürdürülebilir Tarım Danışmanı": "Sen tarım uzmanısın...",
            "Oyun & Modlama Rehberi": "Sen modlama uzmanısın..."
        }

        self.load_config()

        # Socket Sunucusu
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self.handle_connection)

        self.initUI()

        # Thinking Animation Timer
        self.thinking_dots = 0
        self.thinking_icons = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.thinking_timer = QTimer()
        self.thinking_timer.timeout.connect(self.update_thinking_animation)

        # Save Position Timer (Debounce)
        self.save_timer = QTimer()
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self.save_config)

    def mousePressEvent(self, event):
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            self._is_dragging = True
            # Wayland'de startSystemMove en sağlıklı yöntemdir
            if self.windowHandle():
                self.windowHandle().startSystemMove()
            else:
                self._drag_pos = event.globalPosition().toPoint() - self.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if not self.windowHandle() and event.buttons() & (Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton):
            if hasattr(self, '_drag_pos'):
                new_pos = event.globalPosition().toPoint() - self._drag_pos
                self.move(new_pos)
            event.accept()

    def moveEvent(self, event):
        super().moveEvent(event)
        # Sadece kullanıcı sürüklerken konumu güncelle
        if self._is_dragging and not self._is_init:
            self.last_x = self.x()
            self.last_y = self.y()
            self.save_timer.start(500)

    def mouseReleaseEvent(self, event):
        self._is_dragging = False
        self.save_config()
        event.accept()

    def showEvent(self, event):
        super().showEvent(event)
        # Animasyon kullanıldığı için buradaki snap timer'ı kaldırıldı

    def handle_connection(self):
        socket = self.server.nextPendingConnection()
        if socket.waitForReadyRead(500):
            data = socket.readAll().data()
            if data == b"TOGGLE":
                if self.isVisible():
                    self.hide()
                else:
                    self.animate_show()
        socket.disconnectFromServer()

    def load_config(self):
        self.config_file = os.path.join(os.path.expanduser("~"), ".gemini_sidebar_config.json")
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                    self.bg_alpha = data.get("bg_alpha", self.bg_alpha)
                    self.bg_color = QColor(data.get("bg_color", self.bg_color.name()))
                    self.accent_color = QColor(data.get("accent_color", self.accent_color.name()))
                    self.app_width = data.get("app_width", self.app_width)
                    self.app_height = data.get("app_height", self.app_height)
                    self.active_api_profile = data.get("active_api_profile", self.active_api_profile)
                    self.api_profiles = data.get("api_profiles", self.api_profiles)
                    self.current_persona = data.get("current_persona", self.current_persona)
                    self.last_x = data.get("last_x", 0)
                    self.last_y = data.get("last_y", 100)
            except Exception as e:
                print("Ayar dosyası okunamadı:", e)
        else:
            screen = QApplication.primaryScreen().availableGeometry()
            self.last_x = 0
            self.last_y = (screen.height() - self.app_height) // 2

    def save_config(self):
        data = {
            "bg_alpha": self.bg_alpha,
            "bg_color": self.bg_color.name(),
            "accent_color": self.accent_color.name(),
            "active_api_profile": self.active_api_profile,
            "api_profiles": self.api_profiles,
            "current_persona": self.current_persona,
            "last_x": self.last_x,
            "last_y": self.last_y,
            "app_width": self.width(),
            "app_height": self.height(),
        }
        with open(self.config_file, 'w') as f:
            json.dump(data, f, indent=4)

    def position_on_left(self):
        self.setFixedSize(self.app_width, self.app_height)
        self.setGeometry(self.last_x, self.last_y, self.app_width, self.app_height)

    def update_settings(self, alpha, bg_color, accent_color, width, height):
        self.bg_alpha = alpha
        self.bg_color = bg_color
        self.accent_color = accent_color
        self.app_width = width
        self.app_height = height
        self.position_on_left()
        self.apply_styles()
        self.save_config()

    def animate_show(self):
        self._is_init = True
        self.setWindowOpacity(0.0)
        # Wayland'de stabilize olması için kısa bir bekleme sonrası animasyonu başlat
        QTimer.singleShot(100, self._start_show_animation)

    def _start_show_animation(self):
        # Genişliği 0 yapıp konumlandır
        self.setGeometry(self.last_x, self.last_y, 0, self.app_height)
        self.show()
        self.showNormal()
        self.activateWindow()

        # Animasyon 1: Boyut (Soldan sağa genişleme)
        self.width_anim = QPropertyAnimation(self, b"geometry")
        self.width_anim.setDuration(500)
        self.width_anim.setStartValue(QRect(self.last_x, self.last_y, 0, self.app_height))
        self.width_anim.setEndValue(QRect(self.last_x, self.last_y, self.app_width, self.app_height))
        self.width_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Animasyon 2: Şeffaflık (Belirme)
        self.opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        self.opacity_anim.setDuration(500)
        self.opacity_anim.setStartValue(0.0)
        self.opacity_anim.setEndValue(1.0)

        self.width_anim.finished.connect(self._on_animated_show_finished)

        self.width_anim.start()
        self.opacity_anim.start()

    def _on_animated_show_finished(self):
        self._is_init = False
        # Konumu son kez sabitle (Wayland için zorla)
        self.setGeometry(self.last_x, self.last_y, self.app_width, self.app_height)
        QTimer.singleShot(100, lambda: self.move(self.last_x, self.last_y))

    def open_settings(self):
        self.settings_dialog = SettingsDialog(self, self.bg_alpha, self.bg_color, self.accent_color, self.app_width, self.app_height)
        self.settings_dialog.show()

    def open_api_settings(self):
        accent_hex = self.accent_color.name()
        self.api_dialog = APIDialog(self, self.api_profiles, self.active_api_profile, accent_hex)
        self.api_dialog.show()

    def open_tools_settings(self):
        accent_hex = self.accent_color.name()
        self.tools_dialog = ToolsDialog(self, self.current_persona, self.personas, accent_hex)
        self.tools_dialog.show()

    def get_dialog_style(self, accent_hex):
        return f"""
            QDialog {{ background-color: #1a1a1a; }}
            QLabel {{ color: #eeeeee; font-weight: bold; margin-top: 5px; }}
            QPushButton {{ background-color: #2a2a2a; color: white; border: 1px solid #444; padding: 8px; }}
            QPushButton:hover {{ background-color: #3a3a3a; border: 1px solid {accent_hex}; }}
            QComboBox {{ background-color: #0a0a0a; color: white; border: 1px solid #444; padding: 6px; }}
            QComboBox:focus {{ border: 1px solid {accent_hex}; }}
        """

    def initUI(self):
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(self.app_width, self.app_height)

        master_layout = QVBoxLayout(self)
        master_layout.setContentsMargins(0, 0, 0, 0)

        self.bg_frame = QFrame()
        self.bg_frame.setObjectName("MainFrame")
        master_layout.addWidget(self.bg_frame)

        main_layout = QVBoxLayout(self.bg_frame)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # Üst Bar
        top_bar_layout = QHBoxLayout()
        self.btn_apis = QPushButton("❖ APIs")
        self.btn_tools = QPushButton("💼 Tools")
        self.settings_btn = QPushButton("⚙️ Settings")

        tab_style = "QPushButton { background-color: transparent; border: none; color: gray; font-weight: bold; padding: 5px; } QPushButton:hover { color: white; }"
        self.btn_apis.setStyleSheet(tab_style)
        self.btn_tools.setStyleSheet(tab_style)
        self.settings_btn.setStyleSheet(tab_style)

        self.btn_apis.clicked.connect(self.open_api_settings)
        self.btn_tools.clicked.connect(self.open_tools_settings)
        self.settings_btn.clicked.connect(self.open_settings)

        top_bar_layout.addWidget(self.btn_apis)
        top_bar_layout.addWidget(self.btn_tools)
        top_bar_layout.addStretch()
        top_bar_layout.addWidget(self.settings_btn)

        # Başlık Alanı
        header_layout = QVBoxLayout()
        self.icon_label = QLabel("✦")
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label = QLabel("Assistant (Gemini)")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: white;")
        self.subtitle_label = QLabel("Powered by Google")
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle_label.setStyleSheet("font-size: 11px; color: gray; margin-bottom: 5px;")

        header_layout.addWidget(self.icon_label)
        header_layout.addWidget(self.title_label)
        header_layout.addWidget(self.subtitle_label)

        # Model Seçim Butonları
        mode_layout = QHBoxLayout()
        self.btn_precise = QPushButton("Precise")
        self.btn_balanced = QPushButton("Balanced")
        self.btn_creative = QPushButton("Creative")

        self.btn_precise.setCheckable(True)
        self.btn_balanced.setCheckable(True)
        self.btn_creative.setCheckable(True)

        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.btn_precise)
        self.mode_group.addButton(self.btn_balanced)
        self.mode_group.addButton(self.btn_creative)
        self.btn_balanced.setChecked(True)

        self.btn_precise.clicked.connect(lambda: self.change_mode("Precise"))
        self.btn_balanced.clicked.connect(lambda: self.change_mode("Balanced"))
        self.btn_creative.clicked.connect(lambda: self.change_mode("Creative"))

        mode_layout.addWidget(self.btn_precise)
        mode_layout.addWidget(self.btn_balanced)
        mode_layout.addWidget(self.btn_creative)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: rgba(255,255,255,30); margin: 10px 0px;")

        # Sohbet ve Girdi
        self.chat_history = QTextEdit()
        self.chat_history.setReadOnly(True)

        # Thinking Label
        self.thinking_label = QLabel("⠋ Gemini çalışıyor...")
        self.thinking_label.setStyleSheet(f"color: {self.accent_color.name()}; font-style: italic; margin-left: 5px;")
        self.thinking_label.hide()

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Message Gemini...")
        self.input_field.returnPressed.connect(self.send_message)

        main_layout.addLayout(top_bar_layout)
        main_layout.addLayout(header_layout)
        main_layout.addLayout(mode_layout)
        main_layout.addWidget(line)
        main_layout.addWidget(self.chat_history)
        main_layout.addWidget(self.thinking_label)
        main_layout.addWidget(self.input_field)

        self.apply_styles()

    def change_mode(self, mode):
        self.current_mode = mode
        self.apply_styles()

    def apply_styles(self):
        r, g, b = self.bg_color.red(), self.bg_color.green(), self.bg_color.blue()
        accent_hex = self.accent_color.name()
        self.bg_frame.setStyleSheet(f"QFrame#MainFrame {{ background-color: rgba({r}, {g}, {b}, {self.bg_alpha}); border: 1px solid rgba(255, 255, 255, 50); }}")
        self.icon_label.setStyleSheet(f"font-size: 36px; color: {accent_hex}; margin-top: 5px;")
        mode_btn_style = f"QPushButton {{ background-color: rgba(255,255,255,10); border: 1px solid rgba(255,255,255,30); color: gray; padding: 6px; }} QPushButton:checked {{ background-color: {accent_hex}; color: black; font-weight: bold; border: none; }} QPushButton:hover:!checked {{ background-color: rgba(255,255,255,20); }}"
        self.btn_precise.setStyleSheet(mode_btn_style)
        self.btn_balanced.setStyleSheet(mode_btn_style)
        self.btn_creative.setStyleSheet(mode_btn_style)
        input_chat_style = "background-color: rgba(0, 0, 0, 100); padding: 10px; font-size: 14px; border: 1px solid rgba(255, 255, 255, 30); color: white;"
        self.chat_history.setStyleSheet(input_chat_style)
        self.input_field.setStyleSheet(input_chat_style)

    def send_message(self):
        user_text = self.input_field.text()
        if not user_text: return
        active_api_data = self.api_profiles[self.active_api_profile]
        if not active_api_data["key"]:
            self.chat_history.append("<b>Sistem:</b> Lütfen API anahtarı girin.<br>")
            return

        accent_hex = self.accent_color.name()
        self.chat_history.append(f"<b style='color:{accent_hex};'>Sen:</b> {user_text}<br>")
        self.input_field.clear()

        # Thinking Animation başlat
        self.thinking_label.show()
        self.thinking_dots = 0
        self.thinking_timer.start(100)
        self.chat_history.verticalScrollBar().setValue(self.chat_history.verticalScrollBar().maximum())

        self.current_ai_response = ""
        temp = 0.2 if self.current_mode == "Precise" else 1.5 if self.current_mode == "Creative" else 0.7

        try:
            client = genai.Client(api_key=active_api_data["key"])
            config = types.GenerateContentConfig(temperature=temp, system_instruction=self.personas[self.current_persona])

            self.worker = ChatWorker(client, 'gemini-2.5-flash', user_text, config)
            self.worker.chunk_received.connect(self.on_chunk_received)
            self.worker.finished.connect(self.on_response_finished)
            self.worker.error.connect(self.on_worker_error)
            self.worker.start()
        except Exception as e:
            self.chat_history.append(f"<b>Hata:</b> {str(e)}<br><br>")

    def on_chunk_received(self, char):
        if not self.current_ai_response:
            # Thinking animasyonunu durdur
            if self.thinking_timer.isActive():
                self.thinking_timer.stop()
            self.thinking_label.hide()

            # Gemini header'ını şimdi ekle (streaming başlangıcında)
            self.chat_history.append(f"<b style='color:{self.accent_color.name()};'>Gemini:</b>")
            self.chat_history.append("") # Mesaj için boş satır
            self.response_start_pos = self.chat_history.textCursor().position()

        self.current_ai_response += char
        # Markdown render et ve göster
        html_response = markdown.markdown(self.current_ai_response)

        # Sadece son bloğu güncellemek yerine, streaming sırasında düz metin ekleyip
        # bittiğinde markdown yapmak daha güvenli olabilir ama kullanıcı anlık istiyor.
        # Basitçe imleci sona alıp metni ekliyoruz.
        cursor = self.chat_history.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        # QTextEdit'e parça parça markdown eklemek zordur, o yüzden düz metin ekliyoruz
        # on_response_finished'da markdown'a çevireceğiz.
        cursor.insertText(char)
        self.chat_history.verticalScrollBar().setValue(self.chat_history.verticalScrollBar().maximum())

    def on_response_finished(self, full_text):
        html_response = markdown.markdown(full_text)

        # Streaming sırasında eklenen metni tam olarak seçip sil
        cursor = self.chat_history.textCursor()
        cursor.setPosition(self.response_start_pos)
        cursor.movePosition(cursor.MoveOperation.End, cursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()

        # Markdown halini ekle
        cursor.insertHtml(html_response)
        self.chat_history.append("<br>")
        self.chat_history.verticalScrollBar().setValue(self.chat_history.verticalScrollBar().maximum())

    def on_worker_error(self, error_msg):
        if self.thinking_timer.isActive():
            self.thinking_timer.stop()
        self.chat_history.append(f"<b>Hata:</b> {error_msg}<br><br>")

    def update_thinking_animation(self):
        self.thinking_dots = (self.thinking_dots + 1) % len(self.thinking_icons)
        icon = self.thinking_icons[self.thinking_dots]
        self.thinking_label.setText(f"{icon} Gemini çalışıyor...")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    socket_name = "GeminiSidebar_Unique_Socket"
    socket = QLocalSocket()
    socket.connectToServer(socket_name)

    if socket.waitForConnected(500):
        socket.write(b"TOGGLE")
        socket.waitForBytesWritten(500)
        socket.disconnectFromServer()
        sys.exit(0)
    else:
        ex = GeminiSidebar()
        ex.server.removeServer(socket_name)
        ex.server.listen(socket_name)
        # ex.animate_show() # Başlangıçta gizli kalsın
        sys.exit(app.exec())
