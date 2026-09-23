STYLE = """
QWidget {
    background: #151719;
    color: #f2f4f7;
    font-family: "Segoe UI", "Inter", Arial;
    font-size: 14px;
    letter-spacing: 0px;
}
QWidget#ViewContent, QScrollArea, QScrollArea > QWidget > QWidget {
    background: #151719;
}
QFrame#Sidebar {
    background: #101214;
    border: none;
}
QLabel {
    background: transparent;
}
QLabel#AppTitle {
    color: #ffffff;
    font-size: 18px;
    font-weight: 800;
}
QLabel#SidebarSubtle {
    color: #a8adb4;
    font-size: 11px;
}
QPushButton#NavButton {
    background: transparent;
    color: #c8cdd3;
    border: none;
    border-radius: 8px;
    padding: 12px 14px;
    text-align: left;
    font-weight: 650;
}
QPushButton#NavButton:hover {
    background: #24282d;
    color: #ffffff;
}
QPushButton#NavButton[active="true"] {
    background: #2f6fed;
    color: #ffffff;
}
QFrame#Header, QFrame#Card, QFrame#Toast {
    background: #202326;
    border: 1px solid #343941;
    border-radius: 8px;
}
QLabel#PageTitle {
    color: #ffffff;
    font-size: 26px;
    font-weight: 850;
}
QLabel#SectionTitle {
    color: #ffffff;
    font-size: 17px;
    font-weight: 800;
}
QLabel#Muted, QLabel#HelpText {
    color: #b2b8c2;
}
QLabel#FieldLabel {
    color: #d9dde3;
    font-size: 12px;
    font-weight: 800;
}
QLabel#RequiredMark {
    color: #f6c343;
    font-size: 12px;
    font-weight: 900;
}
QLabel#Metric {
    color: #ffffff;
    font-size: 30px;
    font-weight: 900;
}
QLineEdit, QComboBox, QTextEdit {
    background: #111315;
    color: #f2f4f7;
    border: 1px solid #4a5059;
    border-radius: 8px;
    padding: 10px 11px;
    selection-background-color: #2f6fed;
}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus {
    border: 2px solid #6ea8ff;
    padding: 9px 10px;
}
QLineEdit[invalid="true"], QComboBox[invalid="true"] {
    border: 2px solid #ef6b6b;
    padding: 9px 10px;
}
QLineEdit:disabled {
    color: #a8adb4;
    background: #191c1f;
}
QComboBox QAbstractItemView {
    background: #202326;
    color: #f2f4f7;
    border: 1px solid #4a5059;
    selection-background-color: #2f6fed;
}
QPushButton {
    background: #2f6fed;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 11px 16px;
    font-weight: 800;
}
QPushButton:hover { background: #255fce; }
QPushButton:pressed { background: #1f50ad; }
QPushButton:disabled {
    background: #25292e;
    color: #7f8791;
    border: 1px solid #3b4149;
}
QPushButton:focus {
    border: 2px solid #9ec5ff;
    padding: 9px 14px;
}
QPushButton#SuccessButton { background: #178553; }
QPushButton#SuccessButton:hover { background: #137044; }
QPushButton#DangerButton { background: #d14343; }
QPushButton#DangerButton:hover { background: #b93636; }
QPushButton#SecondaryButton {
    background: #2a2e33;
    color: #f2f4f7;
    border: 1px solid #5a626d;
}
QPushButton#SecondaryButton:hover { background: #343941; }
QPushButton#SecondaryButton:disabled,
QPushButton#SuccessButton:disabled,
QPushButton#DangerButton:disabled {
    background: #25292e;
    color: #7f8791;
    border: 1px solid #3b4149;
}
QPushButton#ToastCloseButton {
    background: transparent;
    color: #d9dde3;
    border: none;
    padding: 0;
    font-size: 20px;
}
QPushButton#ToastCloseButton:hover { background: #343941; }
QLabel#FeedbackLabel {
    padding: 10px 12px;
    border-radius: 6px;
    background: #24282d;
    color: #dce3ec;
}
QLabel#FeedbackLabel[level="success"] {
    background: #143d2d;
    color: #b8f3d7;
    border: 1px solid #2b8b61;
}
QLabel#FeedbackLabel[level="error"] {
    background: #482124;
    color: #ffd7d7;
    border: 1px solid #b94a50;
}
QLabel#FeedbackLabel[level="warning"] {
    background: #473918;
    color: #ffe8a3;
    border: 1px solid #a98122;
}
QCheckBox {
    background: transparent;
    color: #d9dde3;
    spacing: 8px;
    padding: 4px 0;
}
QScrollBar:vertical {
    background: #151719;
    width: 12px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #4a5059;
    border-radius: 5px;
    min-height: 32px;
}
QScrollBar::handle:vertical:hover { background: #606975; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QListWidget, QTableWidget {
    background: #17191c;
    color: #f2f4f7;
    border: 1px solid #343941;
    border-radius: 8px;
    gridline-color: #2c3036;
}
QHeaderView::section {
    background: #24282d;
    color: #ffffff;
    border: none;
    border-bottom: 1px solid #3a4048;
    padding: 9px;
    font-weight: 800;
}
QTableWidget::item { padding: 8px; }
QTableWidget::item:selected, QListWidget::item:selected {
    background: #2f6fed;
    color: #ffffff;
}
"""
