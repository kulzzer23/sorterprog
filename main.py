import sys
import os
import json
import re
import requests
import pytesseract
from PIL import Image, ImageEnhance, ImageOps
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QLineEdit, 
                             QFileDialog, QListWidget, QListWidgetItem, QMessageBox,
                             QProgressDialog, QComboBox, QInputDialog, QFrame, QDialog)
from PyQt6.QtGui import QPixmap, QIcon, QMovie
from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal

IMGBB_API_KEY = "ea9bc80bf3bddd99f0633e65deea3ac9"

# Укажи путь к установленному Tesseract (обычно он такой по умолчанию)
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

DARK_STYLESHEET = """
QWidget { background-color: #1e1e2e; color: #cdd6f4; font-family: 'Segoe UI', sans-serif; font-size: 14px; }
QPushButton { background-color: #313244; border: 1px solid #45475a; border-radius: 6px; padding: 8px 16px; font-weight: bold; }
QPushButton:hover { background-color: #45475a; }
QPushButton:pressed { background-color: #585b70; }
QLineEdit, QComboBox, QListWidget { background-color: #181825; border: 1px solid #313244; border-radius: 4px; padding: 6px; }
QListWidget::item:selected { background-color: #89b4fa; color: #11111b; }
QListWidget::item { padding: 4px; border-bottom: 1px solid #313244; }
QLabel { font-size: 14px; }
"""

# --- Диалоговое окно для выбора строки OCR ---
class OCRDialog(QDialog):
    def __init__(self, lines, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Распознанный чат (Выберите строку)")
        self.resize(700, 400)
        self.setStyleSheet(DARK_STYLESHEET)
        self.selected_text = ""

        layout = QVBoxLayout(self)
        
        self.list_widget = QListWidget()
        self.list_widget.addItems(lines)
        self.list_widget.setWordWrap(True)
        layout.addWidget(self.list_widget)

        btn_select = QPushButton("Выбрать как описание")
        btn_select.setStyleSheet("background-color: #a6e3a1; color: #11111b;")
        btn_select.clicked.connect(self.accept_selection)
        layout.addWidget(btn_select)

    def accept_selection(self):
        item = self.list_widget.currentItem()
        if item:
            self.selected_text = item.text()
            self.accept()

    def get_selected_text(self):
        return self.selected_text

# --- Виджет Drag & Drop ---
class AlbumDropList(QListWidget):
    images_dropped = pyqtSignal(str, list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        
    def dragEnterEvent(self, event):
        if event.source() and event.source() != self:
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.source() and event.source() != self:
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        target_item = self.itemAt(event.position().toPoint())
        if target_item:
            album_name = target_item.text()
            source_widget = event.source()
            
            if isinstance(source_widget, QListWidget):
                paths = [item.data(Qt.ItemDataRole.UserRole) for item in source_widget.selectedItems()]
                if paths:
                    self.images_dropped.emit(album_name, paths)
                    event.accept()
        else:
            event.ignore()

# --- Поток загрузки ---
class UploaderThread(QThread):
    progress = pyqtSignal(int)
    finished_upload = pyqtSignal(bool, str)
    
    def __init__(self, project_data, albums, export_path):
        super().__init__()
        self.project_data = project_data
        self.albums = albums
        self.export_path = export_path
        
    def run(self):
        items_to_upload = [(path, data) for path, data in self.project_data.items() if data['desc'].strip()]
        total = len(items_to_upload)
        
        if total == 0:
            self.finished_upload.emit(False, "Нет файлов с описанием для загрузки.")
            return

        grouped_data = {album: [] for album in self.albums}
        for path, data in items_to_upload:
            album = data['album'] if data['album'] in grouped_data else "Без альбома"
            grouped_data[album].append((path, data['desc']))

        try:
            with open(self.export_path, 'w', encoding='utf-8') as f:
                processed_count = 0
                for album in self.albums:
                    images_in_album = grouped_data.get(album, [])
                    if not images_in_album: continue
                        
                    f.write(f"\n{'='*10} Альбом: {album} {'='*10}\n")
                    for img_path, desc in images_in_album:
                        with open(img_path, 'rb') as img_file:
                            response = requests.post(
                                "https://api.imgbb.com/1/upload",
                                data={"key": IMGBB_API_KEY},
                                files={"image": img_file}
                            )
                            resp_data = response.json()
                            if response.status_code == 200 and resp_data.get("success"):
                                link = resp_data["data"]["url"]
                                f.write(f"{desc} - {link}\n")
                        processed_count += 1
                        self.progress.emit(int((processed_count / total) * 100))
                        
            self.finished_upload.emit(True, "Загрузка завершена. Файл сохранен!")
        except Exception as e:
            self.finished_upload.emit(False, f"Ошибка сети: {str(e)}")


# --- Основной класс ---
class ImageTagger(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pro Image Tagger & Uploader")
        self.resize(1200, 800)
        self.setStyleSheet(DARK_STYLESHEET)
        
        self.project_data = {}
        self.albums = ["Без альбома"]
        self.current_image_path = None
        self.current_movie = None
        self.carousel_items = {}
        
        self.init_ui()
        
    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        
        toolbar = QHBoxLayout()
        self.btn_load_folder = QPushButton("📁 Выбрать папку")
        self.btn_load_project = QPushButton("📂 Загрузить проект")
        self.btn_save_project = QPushButton("💾 Сохранить проект")
        self.btn_export_txt = QPushButton("📄 Экспорт .txt")
        self.btn_upload = QPushButton("☁ Загрузить на ImgBB")
        self.btn_upload.setStyleSheet("background-color: #89b4fa; color: #11111b;")
        
        toolbar.addWidget(self.btn_load_folder)
        toolbar.addWidget(self.btn_load_project)
        toolbar.addWidget(self.btn_save_project)
        toolbar.addWidget(self.btn_export_txt)
        toolbar.addStretch()
        toolbar.addWidget(self.btn_upload)
        main_layout.addLayout(toolbar)
        
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #45475a;")
        main_layout.addWidget(line)
        
        work_layout = QHBoxLayout()
        
        # ЛЕВАЯ ПАНЕЛЬ
        album_layout = QVBoxLayout()
        album_layout.addWidget(QLabel("Управление альбомами\n(перетащите фото сюда):"))
        self.album_list = AlbumDropList()
        self.album_list.addItems(self.albums)
        self.album_list.setFixedWidth(200)
        self.album_list.images_dropped.connect(self.assign_images_to_album)
        album_layout.addWidget(self.album_list)
        
        self.btn_add_album = QPushButton("+ Создать альбом")
        album_layout.addWidget(self.btn_add_album)
        work_layout.addLayout(album_layout)
        
        # ЦЕНТР
        center_layout = QVBoxLayout()
        self.image_label = QLabel("Выберите папку или загрузите проект")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(600, 500)
        self.image_label.setStyleSheet("border: 2px dashed #45475a; border-radius: 10px;")
        center_layout.addWidget(self.image_label, stretch=1)
        
        editor_layout = QHBoxLayout()
        self.desc_input = QLineEdit()
        self.desc_input.setPlaceholderText("Описание фото или гифки...")
        
        # Новая кнопка OCR
        self.btn_ocr = QPushButton("🔍 Скан чата")
        self.btn_ocr.setStyleSheet("background-color: #cba6f7; color: #11111b;")
        
        self.album_selector = QComboBox()
        self.album_selector.addItems(self.albums)
        
        editor_layout.addWidget(self.desc_input, stretch=4)
        editor_layout.addWidget(self.btn_ocr)
        editor_layout.addWidget(QLabel("Альбом:"))
        editor_layout.addWidget(self.album_selector, stretch=1)
        center_layout.addLayout(editor_layout)
        
        nav_layout = QHBoxLayout()
        self.btn_prev = QPushButton("◄ Назад")
        self.btn_next = QPushButton("Вперед ►")
        nav_layout.addWidget(self.btn_prev)
        nav_layout.addWidget(self.btn_next)
        center_layout.addLayout(nav_layout)
        
        work_layout.addLayout(center_layout, stretch=3)
        
        # ПРАВАЯ ПАНЕЛЬ
        right_layout = QVBoxLayout()
        right_layout.addWidget(QLabel("Медиафайлы:"))
        self.carousel = QListWidget()
        self.carousel.setViewMode(QListWidget.ViewMode.IconMode)
        self.carousel.setIconSize(QSize(100, 100))
        self.carousel.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.carousel.setFixedWidth(250)
        self.carousel.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.carousel.setDragEnabled(True)
        
        right_layout.addWidget(self.carousel)
        work_layout.addLayout(right_layout)
        
        main_layout.addLayout(work_layout, stretch=1)
        
        # Сигналы
        self.btn_load_folder.clicked.connect(self.load_folder)
        self.btn_load_project.clicked.connect(self.load_project)
        self.btn_save_project.clicked.connect(self.save_project)
        self.btn_export_txt.clicked.connect(self.export_local_txt)
        self.btn_upload.clicked.connect(self.start_upload)
        self.btn_add_album.clicked.connect(self.add_album)
        self.btn_ocr.clicked.connect(self.scan_chat)
        
        self.carousel.itemClicked.connect(self.on_thumbnail_clicked)
        self.btn_prev.clicked.connect(self.show_prev_image)
        self.btn_next.clicked.connect(self.show_next_image)
        
        self.desc_input.textChanged.connect(self.save_current_data)
        self.album_selector.currentTextChanged.connect(self.save_current_data)

    # --- Новая функция OCR ---
    def scan_chat(self):
        if not self.current_image_path:
            return
            
        if not os.path.exists(pytesseract.pytesseract.tesseract_cmd):
            QMessageBox.critical(self, "Ошибка", "Tesseract OCR не найден!\nУбедитесь, что он установлен в C:\\Program Files\\Tesseract-OCR\\tesseract.exe")
            return
            
        try:
            # --- 1. ПРЕПРОЦЕССИНГ КАРТИНКИ ---
            img = Image.open(self.current_image_path)
            
            # Переводим в ЧБ (убиваем цветные ники)
            img = img.convert('L')
            # Выкручиваем контраст
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(2.5)
            # Инвертируем цвета (светлый текст SAMP станет черным, а темный фон - белым)
            img = ImageOps.invert(img)
            
            # (Опционально) Можно сохранить промежуточный вариант для теста:
            # img.save("debug_ocr_image.png")

            # --- 2. СКАНИРОВАНИЕ ---
            raw_text = pytesseract.image_to_string(img, lang='rus+eng')
            raw_lines = raw_text.split('\n')
            
            valid_lines = []
            for line in raw_lines:
                line = line.strip()
                # Фильтр: длина больше 10 символов и содержит хоть какие-то буквы
                if len(line) > 10 and re.search('[a-zA-Zа-яА-Я]', line):
                    valid_lines.append(line)
                    
            # --- 3. ДЕБАГ (Если ничего не нашлось) ---
            if not valid_lines:
                debug_out = raw_text.strip()
                if not debug_out:
                    debug_out = "[ПУСТО - Tesseract не увидел ни одной буквы на картинке]"
                
                # Показываем всплывающее окно с сырым результатом
                QMessageBox.warning(
                    self, 
                    "Дебаг OCR (Текст отфильтрован)", 
                    f"Не удалось найти подходящие строки.\n\nВот что реально прочитал Tesseract:\n{debug_out[:1000]}"
                )
                return
                
            # --- 4. ВЫВОД РЕЗУЛЬТАТА ---
            dialog = OCRDialog(valid_lines, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                selected_text = dialog.get_selected_text()
                if selected_text:
                    # Очищаем от таймкодов типа [19:53:25] или [19:53:25] [V]
                    clean_text = re.sub(r'^\[\d{2}:\d{2}:\d{2}\]\s*(?:\[[A-Za-z]\])?\s*-\s*', '', selected_text)
                    clean_text = re.sub(r'^\[\d{2}:\d{2}:\d{2}\]\s*(?:\[[A-Za-z]\])?\s*', '', clean_text)
                    self.desc_input.setText(clean_text)
                    
        except Exception as e:
            QMessageBox.critical(self, "Ошибка сканирования", str(e))

    def add_album(self):
        name, ok = QInputDialog.getText(self, "Новый альбом", "Введите название альбома:")
        if ok and name and name not in self.albums:
            self.albums.append(name)
            self.album_list.addItem(name)
            self.album_selector.blockSignals(True)
            self.album_selector.addItem(name)
            self.album_selector.blockSignals(False)

    def assign_images_to_album(self, album_name, paths):
        for path in paths:
            if path in self.project_data:
                self.project_data[path]["album"] = album_name
                if path in self.carousel_items:
                    self.carousel_items[path].setToolTip(f"Альбом: {album_name}")
        if self.current_image_path in paths:
            self.album_selector.blockSignals(True)
            self.album_selector.setCurrentText(album_name)
            self.album_selector.blockSignals(False)
        self.carousel.clearSelection()

    def load_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку")
        if not folder: return
        self.carousel.clear()
        self.project_data.clear()
        self.carousel_items.clear()
        valid_exts = ('.png', '.jpg', '.jpeg', '.bmp', '.webp', '.gif')
        for file in os.listdir(folder):
            if file.lower().endswith(valid_exts):
                full_path = os.path.join(folder, file)
                self.project_data[full_path] = {"desc": "", "album": "Без альбома"}
                self.add_to_carousel(full_path, file)
        if self.carousel.count() > 0:
            self.carousel.setCurrentRow(0)
            self.display_image(self.carousel.item(0).data(Qt.ItemDataRole.UserRole))

    def add_to_carousel(self, path, filename):
        icon = QIcon(path)
        item = QListWidgetItem(icon, filename)
        item.setData(Qt.ItemDataRole.UserRole, path)
        album_name = self.project_data.get(path, {}).get("album", "Без альбома")
        item.setToolTip(f"Альбом: {album_name}")
        self.carousel.addItem(item)
        self.carousel_items[path] = item

    def load_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Загрузить проект", "", "JSON Files (*.json)")
        if not path: return
        with open(path, 'r', encoding='utf-8') as f:
            try: data = json.load(f)
            except Exception:
                QMessageBox.warning(self, "Ошибка", "Файл проекта поврежден.")
                return
        self.carousel.clear()
        self.project_data.clear()
        self.carousel_items.clear()
        if "images" not in data:
            self.albums = ["Без альбома"]
            for img_path, desc in data.items():
                if isinstance(desc, str): self.project_data[img_path] = {"desc": desc, "album": "Без альбома"}
        else:
            self.albums = data.get("albums", ["Без альбома"])
            self.project_data = data.get("images", {})
        self.album_list.clear()
        self.album_list.addItems(self.albums)
        self.album_selector.blockSignals(True)
        self.album_selector.clear()
        self.album_selector.addItems(self.albums)
        self.album_selector.blockSignals(False)
        for img_path in self.project_data.keys():
            if os.path.exists(img_path):
                self.add_to_carousel(img_path, os.path.basename(img_path))
        if self.carousel.count() > 0:
            self.carousel.setCurrentRow(0)
            self.display_image(self.carousel.item(0).data(Qt.ItemDataRole.UserRole))
            QMessageBox.information(self, "Успех", "Проект загружен!")

    def save_project(self):
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить проект", "my_project.json", "JSON Files (*.json)")
        if path:
            export_data = {"albums": self.albums, "images": self.project_data}
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=4)
            QMessageBox.information(self, "Успех", "Проект сохранен!")

    def display_image(self, path):
        self.current_image_path = path
        if self.current_movie:
            self.current_movie.stop()
            self.current_movie = None
            self.image_label.clear()
        if path.lower().endswith('.gif'):
            self.current_movie = QMovie(path)
            self.current_movie.jumpToFrame(0)
            orig_size = self.current_movie.frameRect().size()
            if orig_size.isValid() and not orig_size.isEmpty():
                scaled_size = orig_size.scaled(self.image_label.size(), Qt.AspectRatioMode.KeepAspectRatio)
                self.current_movie.setScaledSize(scaled_size)
            self.image_label.setMovie(self.current_movie)
            self.current_movie.start()
        else:
            pixmap = QPixmap(path)
            pixmap = pixmap.scaled(self.image_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.image_label.setPixmap(pixmap)
        
        img_data = self.project_data.get(path, {"desc": "", "album": "Без альбома"})
        self.desc_input.blockSignals(True)
        self.album_selector.blockSignals(True)
        self.desc_input.setText(img_data["desc"])
        self.album_selector.setCurrentText(img_data["album"])
        self.desc_input.blockSignals(False)
        self.album_selector.blockSignals(False)

    def save_current_data(self):
        if self.current_image_path:
            album_name = self.album_selector.currentText()
            self.project_data[self.current_image_path] = {
                "desc": self.desc_input.text(),
                "album": album_name
            }
            if self.current_image_path in self.carousel_items:
                self.carousel_items[self.current_image_path].setToolTip(f"Альбом: {album_name}")

    def on_thumbnail_clicked(self, item):
        self.display_image(item.data(Qt.ItemDataRole.UserRole))
        
    def show_prev_image(self):
        current_row = self.carousel.currentRow()
        if current_row > 0:
            self.carousel.setCurrentRow(current_row - 1)
            self.display_image(self.carousel.item(current_row - 1).data(Qt.ItemDataRole.UserRole))

    def show_next_image(self):
        current_row = self.carousel.currentRow()
        if current_row < self.carousel.count() - 1:
            self.carousel.setCurrentRow(current_row + 1)
            self.display_image(self.carousel.item(current_row + 1).data(Qt.ItemDataRole.UserRole))

    def export_local_txt(self):
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт", "local_export.txt", "Text Files (*.txt)")
        if not path: return
        grouped = {a: [] for a in self.albums}
        for img_path, data in self.project_data.items():
            if data['desc'].strip():
                grouped[data['album']].append((os.path.basename(img_path), data['desc']))
        with open(path, 'w', encoding='utf-8') as f:
            for album, items in grouped.items():
                if items:
                    f.write(f"\n=== Альбом: {album} ===\n")
                    for filename, desc in items: f.write(f"{desc} - {filename}\n")
        QMessageBox.information(self, "Успех", "Локальный TXT сгенерирован по альбомам!")

    def start_upload(self):
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт ImgBB", "imgbb_links.txt", "Text Files (*.txt)")
        if not path: return
        self.progress_dialog = QProgressDialog("Загрузка на ImgBB...", "Отмена", 0, 100, self)
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setValue(0)
        self.uploader = UploaderThread(self.project_data, self.albums, path)
        self.uploader.progress.connect(self.progress_dialog.setValue)
        self.uploader.finished_upload.connect(self.upload_finished)
        self.uploader.start()
        
    def upload_finished(self, success, message):
        self.progress_dialog.close()
        if success: QMessageBox.information(self, "Готово", message)
        else: QMessageBox.warning(self, "Внимание", message)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = ImageTagger()
    window.show()
    sys.exit(app.exec())