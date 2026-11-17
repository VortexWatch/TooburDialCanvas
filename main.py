import sys

from PyQt6.QtWidgets import QApplication

def main():
    import main_window
    app = QApplication(sys.argv)
    window = main_window.MainWindow()
    window.show()
    sys.exit(app.exec())
    
if __name__ == "__main__":
    main()
