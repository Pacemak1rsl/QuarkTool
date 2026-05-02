import sys

from PySide6.QtWidgets import QApplication, QStyleFactory

from .ui import MainWindow, app_icon


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Pan Tools")
    app.setWindowIcon(app_icon())
    app.setStyle(QStyleFactory.create("Fusion"))
    window = MainWindow()
    available = app.primaryScreen().availableGeometry()
    min_width = min(1220, available.width())
    min_height = min(700, available.height())
    window.setMinimumSize(min_width, min_height)
    width = min(1460, max(min_width, int(available.width() * 0.72)))
    height = min(820, max(min_height, int(available.height() * 0.88)))
    window.resize(width, height)
    window.move(available.center() - window.rect().center())
    window.show()
    sys.exit(app.exec())
