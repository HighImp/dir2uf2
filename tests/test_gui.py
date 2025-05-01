import os
import sys
import tempfile
import logging
from pathlib import Path
import pytest
from PyQt5.QtWidgets import QApplication
from PyQt5.QtTest import QTest
from PyQt5.QtCore import Qt

# Add the src directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dir2uf2.gui import Dir2UF2GUI, LogHandler, LogWidget

@pytest.fixture(scope="session")
def qapp():
    """Create a QApplication instance for the entire test session."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app
    app.quit()

@pytest.fixture
def gui(qapp):
    """Create a GUI instance for testing."""
    window = Dir2UF2GUI()
    yield window
    window.close()

@pytest.fixture
def log_widget(qapp):
    """Create a LogWidget instance for testing."""
    widget = LogWidget()
    yield widget
    widget.close()

def test_log_widget_append(log_widget, qapp):
    """Test that the log widget correctly appends messages."""
    test_message = "Test log message"
    log_widget.append(test_message)
    QTest.qWait(100)  # Give Qt time to process events
    assert test_message in log_widget.text_widget.toPlainText()

def test_log_widget_clear(log_widget, qapp):
    """Test that the log widget can be cleared."""
    log_widget.append("Test message")
    QTest.qWait(100)  # Give Qt time to process events
    log_widget.clear()
    QTest.qWait(100)  # Give Qt time to process events
    assert log_widget.text_widget.toPlainText() == ""

def test_log_handler_emit(log_widget, qapp):
    """Test that the log handler correctly emits messages."""
    handler = LogHandler(log_widget.text_widget)
    test_message = "Test handler message"
    handler.emit(logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg=test_message,
        args=(),
        exc_info=None
    ))
    QTest.qWait(100)  # Give Qt time to process events
    assert test_message in log_widget.text_widget.toPlainText()

def test_venv_detection(gui, qapp, monkeypatch):
    """Test virtual environment detection."""
    # Test with VIRTUAL_ENV set
    with tempfile.TemporaryDirectory() as temp_dir:
        monkeypatch.setenv('VIRTUAL_ENV', temp_dir)
        # Create a mock download_latest_uf2 method that returns the default directory
        def mock_download_latest_uf2(self, url):
            return self.download_latest_uf2.__get__(self)(url)
        monkeypatch.setattr(Dir2UF2GUI, 'download_latest_uf2', mock_download_latest_uf2)
        
        # Get the default directory
        default_dir = gui.download_latest_uf2("http://example.com")
        assert str(Path(temp_dir).parent) in default_dir

    # Test without VIRTUAL_ENV
    monkeypatch.delenv('VIRTUAL_ENV', raising=False)
    default_dir = gui.download_latest_uf2("http://example.com")
    assert str(Path.home()) in default_dir

def test_firmware_version_extraction(gui, qapp):
    """Test firmware version extraction from UF2 files."""
    # Create a test UF2 file with version string
    with tempfile.NamedTemporaryFile(suffix='.uf2', delete=False) as f:
        f.write(b"MicroPython v1.21.0")
        f.flush()
        
        version = gui.extract_version_from_uf2(f.name)
        assert version == "MicroPython v1.21.0"
        
        # Test with invalid file
        version = gui.extract_version_from_uf2("nonexistent.uf2")
        assert version == "unknown"

def test_gui_initialization(gui, qapp):
    """Test that the GUI initializes correctly."""
    assert gui.windowTitle() == "UF2 Filesystem Patcher"
    assert gui.minimumWidth() == 900
    assert gui.minimumHeight() == 600
    
    # Check that all main components exist
    assert hasattr(gui, 'uf2_input')
    assert hasattr(gui, 'src_input')
    assert hasattr(gui, 'out_input')
    assert hasattr(gui, 'log_widget')
    assert hasattr(gui, 'build_button')

def test_log_level_selection(gui, qapp):
    """Test that log level selection works correctly."""
    # Test each log level
    for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
        gui.log_level_combo.setCurrentText(level)
        QTest.qWait(100)  # Give Qt time to process events
        assert logging.getLogger().getEffectiveLevel() == getattr(logging, level) 