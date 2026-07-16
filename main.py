import sys
import os
import json
import requests
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QLineEdit, 
                             QFileDialog, QListWidget, QListWidgetItem, QMessageBox,
                             QProgressDialog, QComboBox, QInputDialog, QFrame)
from PyQt6.QtGui import QPixmap, QIcon, QMovie
from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal

IMGBB_API_KEY = "ea9bc80bf3bddd99f0633e65deea3ac9"

# --- Темная тема для красоты ---
DARK_STYLESHEET = """
QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: 'Segoe UI', sans-serif;
    font-size: 14px;
}
QPushButton {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: bold;
}
QPushButton:hover { background-color: #45475a; }
QPushButton:pressed { background-color: #585b70; }
QLineEdit, QComboBox, QListWidget {
    background-color: #181825;
    border: 1px solid #313244;
    border-radius: 4px;
    padding: 6px;
}
QListWidget::item:selected { background-color: #89b4fa; color: #11111b; }
QLabel { font-size: 14px; }
"""

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
            self.finished_upload.emit(False, "Нет фотографий или гифок с описанием для загрузки.")
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
                    if not images_in_album:
                        continue
                        
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
                            else:
                                print(f"Ошибка загрузки {img_path}: {resp_data}")
                                
                        processed_count += 1
                        self.progress.emit(int((processed_count / total) * 100))
                        
            self.finished_upload.emit(True, "Загрузка завершена. Файл со ссылками сохранен!")
        except Exception as e:
            self.finished_upload.emit(False, f"Ошибка сети: {str(e)}")

class ImageTagger(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pro Image Tagger & Uploader (С поддержкой GIF)")
        self.resize(1200, 800)
        self.setStyleSheet(DARK_STYLESHEET)
        
        self.project_data = {}
        self.albums = ["Без альбома"]
        self.current_image_path = None
        self.current_movie = None # Храним объект анимации гифки
        
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
        
        album_layout = QVBoxLayout()
        album_layout.addWidget(QLabel("Управление альбомами:"))
        self.album_list = QListWidget()
        self.album_list.addItems(self.albums)
        self.album_list.setFixedWidth(200)
        album_layout.addWidget(self.album_list)
        
        self.btn_add_album = QPushButton("+ Создать альбом")
        album_layout.addWidget(self.btn_add_album)
        work_layout.addLayout(album_layout)
        
        center_layout = QVBoxLayout()
        self.image_label = QLabel("Выберите папку или загрузите проект")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(600, 500)
        self.image_label.setStyleSheet("border: 2px dashed #45475a; border-radius: 10px;")
        center_layout.addWidget(self.image_label, stretch=1)
        
        editor_layout = QHBoxLayout()
        self.desc_input = QLineEdit()
        self.desc_input.setPlaceholderText("Описание фото или гифки...")
        self.album_selector = QComboBox()
        self.album_selector.addItems(self.albums)
        
        editor_layout.addWidget(self.desc_input, stretch=3)
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
        
        right_layout = QVBoxLayout()
        right_layout.addWidget(QLabel("Медиафайлы:"))
        self.carousel = QListWidget()
        self.carousel.setViewMode(QListWidget.ViewMode.IconMode)
        self.carousel.setIconSize(QSize(100, 100))
        self.carousel.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.carousel.setFixedWidth(250)
        right_layout.addWidget(self.carousel)
        work_layout.addLayout(right_layout)
        
        main_layout.addLayout(work_layout, stretch=1)
        
        self.btn_load_folder.clicked.connect(self.load_folder)
        self.btn_load_project.clicked.connect(self.load_project)
        self.btn_save_project.clicked.connect(self.save_project)
        self.btn_export_txt.clicked.connect(self.export_local_txt)
        self.btn_upload.clicked.connect(self.start_upload)
        self.btn_add_album.clicked.connect(self.add_album)
        
        self.carousel.itemClicked.connect(self.on_thumbnail_clicked)
        self.btn_prev.clicked.connect(self.show_prev_image)
        self.btn_next.clicked.connect(self.show_next_image)
        
        self.desc_input.textChanged.connect(self.save_current_data)
        self.album_selector.currentTextChanged.connect(self.save_current_data)

    def add_album(self):
        name, ok = QInputDialog.getText(self, "Новый альбом", "Введите название альбома:")
        if ok and name and name not in self.albums:
            self.albums.append(name)
            self.album_list.addItem(name)
            
            self.album_selector.blockSignals(True)
            self.album_selector.addItem(name)
            self.album_selector.blockSignals(False)

    def load_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку")
        if not folder: return
            
        self.carousel.clear()
        self.project_data.clear()
        
        # Добавили .gif в разрешенные форматы
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
        self.carousel.addItem(item)

    def load_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Загрузить проект", "", "JSON Files (*.json)")
        if not path: return
        
        with open(path, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except Exception:
                QMessageBox.warning(self, "Ошибка", "Файл проекта поврежден.")
                return

        self.carousel.clear()
        self.project_data.clear()
        
        if "images" not in data:
            self.albums = ["Без альбома"]
            for img_path, desc in data.items():
                if isinstance(desc, str):
                    self.project_data[img_path] = {"desc": desc, "album": "Без альбома"}
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
            else:
                print(f"Файл не найден: {img_path}")
                
        if self.carousel.count() > 0:
            self.carousel.setCurrentRow(0)
            self.display_image(self.carousel.item(0).data(Qt.ItemDataRole.UserRole))
            QMessageBox.information(self, "Успех", "Проект загружен!")

    def save_project(self):
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить проект", "my_project.json", "JSON Files (*.json)")
        if path:
            export_data = {
                "albums": self.albums,
                "images": self.project_data
            }
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=4)
            QMessageBox.information(self, "Успех", "Проект сохранен!")

    def display_image(self, path):
        self.current_image_path = path
        
        # Очищаем предыдущую гифку, если она проигрывалась
        if self.current_movie:
            self.current_movie.stop()
            self.current_movie = None
            self.image_label.clear()

        # Разделяем логику отрисовки для GIF и обычных картинок
        if path.lower().endswith('.gif'):
            self.current_movie = QMovie(path)
            
            # Прыгаем на первый кадр, чтобы узнать оригинальный размер гифки
            self.current_movie.jumpToFrame(0)
            orig_size = self.current_movie.frameRect().size()
            
            # Масштабируем гифку с сохранением пропорций
            if orig_size.isValid() and not orig_size.isEmpty():
                scaled_size = orig_size.scaled(self.image_label.size(), Qt.AspectRatioMode.KeepAspectRatio)
                self.current_movie.setScaledSize(scaled_size)
                
            self.image_label.setMovie(self.current_movie)
            self.current_movie.start() # Запускаем анимацию
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
            self.project_data[self.current_image_path] = {
                "desc": self.desc_input.text(),
                "album": self.album_selector.currentText()
            }

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
                    for filename, desc in items:
                        f.write(f"{desc} - {filename}\n")
                        
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
        if success:
            QMessageBox.information(self, "Готово", message)
        else:
            QMessageBox.warning(self, "Внимание", message)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = ImageTagger()
    window.show()
    sys.exit(app.exec())