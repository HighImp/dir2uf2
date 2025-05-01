import sys
import os
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urlparse
import re
import logging
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog,
    QLabel, QCheckBox, QLineEdit, QMessageBox, QFrame, QMainWindow, QMenuBar, 
    QAction, QGroupBox, QStatusBar, QProgressBar, QToolTip, QTreeView, QFileSystemModel,
    QTextEdit, QComboBox
)
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QMetaObject, Q_ARG
from dir2uf2.dir2uf2 import main as dir2uf2_main

class LogHandler(logging.Handler):
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget
        self.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        
    def emit(self, record):
        msg = self.format(record)
        # Use Qt's invokeMethod for thread-safe logging
        QMetaObject.invokeMethod(self.text_widget, "append",
                               Qt.ConnectionType.QueuedConnection,
                               Q_ARG(str, msg))

class FileBrowserWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        
        # Add title label
        title_label = QLabel("Files to be included:")
        title_label.setStyleSheet("font-weight: bold; padding: 5px;")
        self.layout.addWidget(title_label)
        
        # Create file system model
        self.model = QFileSystemModel()
        self.model.setRootPath('')
        
        # Create tree view
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.index(''))
        
        # Hide unnecessary columns
        self.tree.setColumnHidden(1, True)  # Size
        self.tree.setColumnHidden(2, True)  # Type
        self.tree.setColumnHidden(3, True)  # Date Modified
        
        self.layout.addWidget(self.tree)
        
    def set_root_path(self, path):
        self.tree.setRootIndex(self.model.index(path))

class LogWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        
        # Create log text widget
        self.text_widget = QTextEdit()
        self.text_widget.setReadOnly(True)
        self.text_widget.setMaximumHeight(150)
        
        # Add clear button
        clear_button = QPushButton("Clear Log")
        clear_button.clicked.connect(self.clear)
        
        self.layout.addWidget(self.text_widget)
        self.layout.addWidget(clear_button)
        
    def append(self, text):
        self.text_widget.append(text)
        self.text_widget.verticalScrollBar().setValue(
            self.text_widget.verticalScrollBar().maximum()
        )
        
    def clear(self):
        self.text_widget.clear()

class WorkerThread(QThread):
    finished = pyqtSignal(bool, str)
    progress = pyqtSignal(int)
    
    def __init__(self, args):
        super().__init__()
        self.args = args
        
    def run(self):
        try:
            # Call dir2uf2 directly
            dir2uf2_main(self.args)
            self.finished.emit(True, "Operation completed successfully")
        except Exception as e:
            self.finished.emit(False, f"Error: {str(e)}")

class Dir2UF2GUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("UF2 Filesystem Patcher")
        self.setMinimumWidth(900)
        self.setMinimumHeight(600)
        self.setWindowIcon(QIcon("uf2_logo.png"))
        
        # Add status bar
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        
        # Add progress bar
        self.progressBar = QProgressBar()
        self.progressBar.setVisible(False)
        self.statusBar.addPermanentWidget(self.progressBar)
        
        # Central widget with horizontal layout
        self.central = QWidget()
        self.main_layout = QVBoxLayout(self.central)
        self.setCentralWidget(self.central)
        
        # Top section: Form and file browser
        top_section = QWidget()
        top_layout = QHBoxLayout(top_section)
        
        # Left side: Form layout
        self.form_widget = QWidget()
        self.layout = QVBoxLayout(self.form_widget)
        top_layout.addWidget(self.form_widget)
        
        # Right side: File browser
        self.file_browser = FileBrowserWidget()
        top_layout.addWidget(self.file_browser)
        
        self.main_layout.addWidget(top_section)
        
        # Create menu bar
        self.create_menu_bar()
        
        # Create main UI components
        self.create_firmware_section()
        self.create_source_section()
        self.create_output_section()
        self.create_options_section()
        self.create_build_button()
        
        # Bottom section: Log window
        self.log_widget = LogWidget()
        self.main_layout.addWidget(self.log_widget)
        
        # Setup logging
        log_handler = LogHandler(self.log_widget.text_widget)
        logging.getLogger().addHandler(log_handler)
        logging.getLogger().setLevel("INFO")
        
        # Initialize worker thread
        self.worker_thread = None
        
    def create_menu_bar(self):
        menu_bar = QMenuBar(self)
        
        # File menu
        file_menu = menu_bar.addMenu("File")
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Download menu
        download_menu = menu_bar.addMenu("Download Firmware")
        pico1_action = QAction("Pico 1", self)
        pico1_action.triggered.connect(lambda: self.download_latest_uf2(
            "https://micropython.org/download/rp2-pico/rp2-pico-latest.uf2"))
        pico1_action.setToolTip("Download latest MicroPython for Pico 1")
        download_menu.addAction(pico1_action)
        
        pico2_action = QAction("Pico 2", self)
        pico2_action.triggered.connect(lambda: self.download_latest_uf2(
            "https://micropython.org/download/RPI_PICO2/RPI_PICO2-latest.uf2"))
        pico2_action.setToolTip("Download latest MicroPython for Pico 2")
        download_menu.addAction(pico2_action)
        
        # Help menu
        help_menu = menu_bar.addMenu("Help")
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
        
        self.setMenuBar(menu_bar)
        
    def create_firmware_section(self):
        frame = QFrame()
        frame.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        frame.setLineWidth(2)
        layout = QVBoxLayout(frame)
        
        title = QLabel("Firmware")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)
        
        self.uf2_label = QLabel("Firmware UF2:")
        self.uf2_input = QLineEdit()
        self.uf2_input.setToolTip("Select the base MicroPython UF2 file")
        self.uf2_browse = QPushButton("Browse")
        self.uf2_browse.clicked.connect(self.select_uf2)
        self.version_label = QLabel("Version: unknown")
        
        firmware_layout = QHBoxLayout()
        firmware_layout.addWidget(self.uf2_label)
        firmware_layout.addWidget(self.uf2_input)
        firmware_layout.addWidget(self.uf2_browse)
        layout.addLayout(firmware_layout)
        layout.addWidget(self.version_label)
        
        self.layout.addWidget(frame)
        
    def create_source_section(self):
        frame = QFrame()
        frame.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        frame.setLineWidth(2)
        layout = QVBoxLayout(frame)
        
        title = QLabel("Source")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)
        
        self.src_label = QLabel("Source Directory:")
        self.src_input = QLineEdit()
        self.src_input.setToolTip("Select the directory containing files to add to the filesystem")
        self.src_browse = QPushButton("Browse")
        self.src_browse.clicked.connect(self.select_directory)
        
        src_layout = QHBoxLayout()
        src_layout.addWidget(self.src_label)
        src_layout.addWidget(self.src_input)
        src_layout.addWidget(self.src_browse)
        layout.addLayout(src_layout)
        
        self.layout.addWidget(frame)
        
    def create_output_section(self):
        frame = QFrame()
        frame.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        frame.setLineWidth(2)
        layout = QVBoxLayout(frame)
        
        title = QLabel("Output")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)
        
        self.out_label = QLabel("Output UF2 File:")
        self.out_input = QLineEdit()
        self.out_input.setToolTip("Select where to save the output UF2 file")
        self.out_browse = QPushButton("Browse")
        self.out_browse.clicked.connect(self.select_output)
        
        out_layout = QHBoxLayout()
        out_layout.addWidget(self.out_label)
        out_layout.addWidget(self.out_input)
        out_layout.addWidget(self.out_browse)
        layout.addLayout(out_layout)
        
        self.layout.addWidget(frame)
        
    def create_options_section(self):
        frame = QFrame()
        frame.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        frame.setLineWidth(2)
        layout = QVBoxLayout(frame)
        
        title = QLabel("Options")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)
        
        options_layout = QVBoxLayout()
        
        # Compact and Overwrite checkboxes
        checkbox_layout = QHBoxLayout()
        self.compact_checkbox = QCheckBox("CompactFS")
        self.compact_checkbox.setChecked(True)
        self.compact_checkbox.setToolTip("Compact the filesystem to save space")
        
        self.overwrite_checkbox = QCheckBox("OverwriteExistingFS")
        self.overwrite_checkbox.setToolTip("Overwrite existing filesystem if present")
        
        checkbox_layout.addWidget(self.compact_checkbox)
        checkbox_layout.addWidget(self.overwrite_checkbox)
        options_layout.addLayout(checkbox_layout)
        
        # Logging level selection
        log_layout = QHBoxLayout()
        log_label = QLabel("Log Level:")
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        self.log_level_combo.setCurrentText("INFO")
        self.log_level_combo.currentTextChanged.connect(self.update_log_level)
        log_layout.addWidget(log_label)
        log_layout.addWidget(self.log_level_combo)
        options_layout.addLayout(log_layout)
        
        layout.addLayout(options_layout)
        self.layout.addWidget(frame)
        
    def create_build_button(self):
        self.build_button = QPushButton("Create UF2")
        self.build_button.setStyleSheet("font-weight: bold; padding: 8px")
        self.build_button.clicked.connect(self.run_dir2uf2)
        self.layout.addWidget(self.build_button)
        
    def show_about(self):
        QMessageBox.about(self, "About UF2 Filesystem Patcher",
            "UF2 Filesystem Patcher v1.0\n\n"
            "A tool for creating and modifying UF2 filesystem images for Raspberry Pi Pico.\n\n"
            "Created by Phil Howard (github@gadgetoid.com)")
            
    def update_status(self, message, timeout=0):
        self.statusBar.showMessage(message, timeout)
        
    def show_progress(self, show=True):
        self.progressBar.setVisible(show)
        if not show:
            self.progressBar.setValue(0)
            
    def run_dir2uf2(self):
        if self.worker_thread and self.worker_thread.isRunning():
            QMessageBox.warning(self, "Operation in Progress", 
                              "Please wait for the current operation to complete.")
            return
            
        uf2 = self.uf2_input.text().strip()
        src = self.src_input.text().strip()
        out = self.out_input.text().strip()
        
        if not all([uf2, src, out]):
            QMessageBox.warning(self, "Missing Input", "Please fill in all fields.")
            return
            
        if not Path(uf2).is_file():
            QMessageBox.critical(self, "Error", f"Firmware UF2 file not found:\n{uf2}")
            return
            
        if not Path(src).is_dir():
            QMessageBox.critical(self, "Error", f"Source directory not found:\n{src}")
            return
            
        # Prepare arguments for dir2uf2
        args = type('Args', (), {
            'append_to': Path(uf2),
            'filename': Path(out),
            'fs_compact': self.compact_checkbox.isChecked(),
            'fs_overwrite': self.overwrite_checkbox.isChecked(),
            'source_dir': Path(src),
            'verbose_level': 'INFO',
            'fs_start': None,
            'fs_size': None,
            'sparse': False,
            'block_size': 4096,
            'read_size': 256,
            'prog_size': 32,
            'manifest': None,
            'write_bin': False
        })
        
        self.show_progress(True)
        self.update_status("Creating UF2 file...")
        self.build_button.setEnabled(False)
        
        self.worker_thread = WorkerThread(args)
        self.worker_thread.progress.connect(self.progressBar.setValue)
        self.worker_thread.finished.connect(self.handle_operation_finished)
        self.worker_thread.start()
        
    def handle_operation_finished(self, success, message):
        self.show_progress(False)
        self.build_button.setEnabled(True)
        self.update_status(message)
        
        if success:
            QMessageBox.information(self, "Success", "UF2 file created successfully.")
        else:
            QMessageBox.critical(self, "Error", message)
            
    def select_uf2(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Firmware UF2", filter="UF2 Files (*.uf2)")
        if path:
            self.uf2_input.setText(path.strip())
            self.version_label.setText("Version: parsing...")
            try:
                version = self.extract_version_from_uf2(path)
                self.version_label.setText(f"Version: {version}")
            except Exception:
                self.version_label.setText("Version: unknown")

    def extract_version_from_uf2(self, filepath):
        try:
            with open(filepath, 'rb') as f:
                data = f.read()
            # MicroPython Version pattern (e.g., "MicroPython v1.21.0" or similar)
            match = re.search(rb'MicroPython v[\d.]+(-\w+)?', data)
            if match:
                return match.group(0).decode('utf-8')
        except (FileNotFoundError, IOError) as e:
            logging.debug(f"Could not read UF2 file: {e}")
        return "unknown"

    def select_directory(self):
        path = QFileDialog.getExistingDirectory(self, "Select Source Directory")
        if path:
            self.src_input.setText(path.strip())
            self.file_browser.set_root_path(path)  # Update file browser
            # Autofill output path if empty
            if not self.out_input.text().strip():
                parent_dir = Path(path).resolve().parent
                folder_name = Path(path).name
                suggested_path = parent_dir / f"FS_{folder_name}.uf2"
                self.out_input.setText(str(suggested_path))

    def select_output(self):
        path, _ = QFileDialog.getSaveFileName(self, "Select Output UF2", filter="UF2 Files (*.uf2)")
        if path:
            self.out_input.setText(path.strip())

    def handle_file_save(self, temp_path, save_dir, version):
        """Handle saving a file with version information and conflict resolution."""
        # Generate base filename
        base_name = version if version else "micropython"
        base_filename = f"{base_name}.uf2"
        save_path = os.path.join(save_dir, base_filename)
        logging.debug(f"Target save path: {save_path}")
        
        # Handle filename conflicts
        counter = 1
        while os.path.exists(save_path):
            base_filename = f"{base_name} ({counter}).uf2"
            save_path = os.path.join(save_dir, base_filename)
            counter += 1
            logging.debug(f"File exists, trying new path: {save_path}")
        
        logging.debug(f"Renaming {temp_path} to {save_path}")
        try:
            os.rename(temp_path, save_path)
            logging.debug(f"Successfully renamed file to {save_path}")
        except Exception as e:
            logging.error(f"Failed to rename file: {e}")
            # Try to copy instead
            with open(temp_path, 'rb') as f_src:
                with open(save_path, 'wb') as f_dst:
                    f_dst.write(f_src.read())
            logging.debug(f"Successfully copied file to {save_path}")
            try:
                os.remove(temp_path)
            except Exception as e:
                logging.warning(f"Failed to remove temporary file: {e}")
        
        return save_path

    def download_latest_uf2(self, url):
        """Download the latest UF2 file from the given URL."""
        save_dir = QFileDialog.getExistingDirectory(self, "Select Save Directory")
        logging.debug(f"Selected save directory: {save_dir}")
        
        if save_dir:
            # Download the file
            logging.debug(f"Downloading from URL: {url}")
            with urlopen(url) as response:
                # Download to temporary file
                temp_path = os.path.join(save_dir, "temp.uf2")
                logging.debug(f"Writing to temporary file: {temp_path}")
                with open(temp_path, 'wb') as f:
                    data = response.read()
                    logging.debug(f"Downloaded {len(data)} bytes")
                    f.write(data)
                
                # Extract version
                version = self.extract_version_from_uf2(temp_path)
                logging.debug(f"Extracted version: {version}")
                
                # Handle file saving
                save_path = self.handle_file_save(temp_path, save_dir, version)
                
                self.uf2_input.setText(save_path)
                self.version_label.setText(f"Version: {version if version else 'unknown'}")
                QMessageBox.information(self, "Download Complete", f"Downloaded {os.path.basename(save_path)}")

    def update_log_level(self, level):
        logging.getLogger().setLevel(level)

def main():
    app = QApplication(sys.argv)
    window = Dir2UF2GUI()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
