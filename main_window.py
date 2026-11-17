from __future__ import annotations

import datetime
import copy
import os
import zlib
from typing import Callable, Dict, List, Optional, Tuple

from PIL import Image
from PyQt6.QtCore import QPointF, QRectF, QRegularExpression, QSettings, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QAction, QActionGroup, QColor, QFont, QIcon, QKeySequence, QPainter, QPalette, QPen,
                         QPixmap, QPolygonF, QRegularExpressionValidator, QUndoCommand, QUndoStack)
from PyQt6.QtWidgets import (QAbstractSpinBox, QApplication, QButtonGroup, QCheckBox, QColorDialog, QComboBox,
                             QDialog, QDialogButtonBox, QDockWidget, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                             QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu,
                             QMessageBox, QPushButton, QRadioButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter,
                             QTabWidget, QToolBar, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from about_dialog import AboutDialog
from canvas import FaceCanvas, PreviewWidget, pil_to_qimage
from iwf_compiler import (APP_NAME, CHARSETS, HAND_DEFS, SCREEN_H, SCREEN_W, WIDGET_SPECS, GlyphStyle, Project,
                          SimState, Widget, color_from_str, color_to_str, default_font_path, generate_glyph_set,
                          make_default_hand, make_widget_data, max_text_width, render_face, render_preview_png,
                          sample_stems)

# =====================================================================================
#  Theme
# =====================================================================================
THEMES = {
    "light": dict(bg="#e9eaed", panel="#ffffff", card="#ffffff", section="#f5f6f8", border="#d5d8de",
                  text="#1f2430", muted="#7b8190", accent="#3d7eff", accent_hover="#5a92ff", accent_soft="#e4edff",
                  input="#ffffff", hover="#eef0f4", hover2="#e2e5eb", scroll="#c3c7d0", icon="#5b6272",
                  canvas="light", dark=False),
    "dark": dict(bg="#16171b", panel="#1e2025", card="#24272d", section="#1a1c21", border="#33363f",
                 text="#e7e9ee", muted="#8a90a0", accent="#4d8dff", accent_hover="#6a9fff", accent_soft="#263a63",
                 input="#181a1f", hover="#2b2e36", hover2="#343842", scroll="#454a57", icon="#aab0bf",
                 canvas="dark", dark=True),
}

QSS = """
* { font-size: 12px; }
QMainWindow, QDialog { background: @bg; }
QWidget { color: @text; }
QToolTip { background: @card; color: @text; border: 1px solid @border; padding: 4px 6px; }
QMenuBar { background: @panel; border-bottom: 1px solid @border; padding: 2px 6px; }
QMenuBar::item { padding: 5px 10px; background: transparent; border-radius: 4px; }
QMenuBar::item:selected { background: @hover2; }
QMenu { background: @card; border: 1px solid @border; padding: 5px; }
QMenu::item { padding: 6px 30px 6px 26px; border-radius: 4px; }
QMenu::item:selected { background: @accent_soft; color: @text; }
QMenu::item:disabled { color: @muted; }
QMenu::separator { height: 1px; background: @border; margin: 5px 8px; }
QToolBar { background: @panel; border: none; border-bottom: 1px solid @border; spacing: 3px; padding: 5px 10px; }
QToolBar::separator { background: @border; width: 1px; margin: 5px 7px; }
QToolButton { background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 5px; }
QToolButton:hover { background: @hover; }
QToolButton:pressed { background: @hover2; }
QToolButton:checked { background: @accent_soft; border-color: @accent; }
QToolButton:disabled { color: @muted; }
QToolButton#Primary { background: @accent; border-color: @accent; color: white; padding: 5px 14px; font-weight: 600; }
QToolButton#Primary:hover { background: @accent_hover; }
QToolButton::menu-indicator { image: none; }
QDockWidget { border: none; }
QFrame#Panel { background: @panel; }
QFrame#PropHeader { background: @panel; border: none; border-bottom: 1px solid @border; }
QFrame#RunHeader { background: @panel; border: none; border-bottom: 1px solid @border; }
QFrame#Section { background: @panel; border: none; }
QTabWidget::pane { border: none; border-top: 1px solid @border; background: @panel; }
QTabBar { background: @panel; }
QTabBar::tab { background: transparent; color: @muted; padding: 9px 16px; border: none;
               border-bottom: 2px solid transparent; font-weight: 600; }
QTabBar::tab:selected { color: @text; border-bottom: 2px solid @accent; }
QTabBar::tab:hover:!selected { color: @text; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 11px; margin: 2px; }
QScrollBar::handle:vertical { background: @scroll; border-radius: 3px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: @muted; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 11px; margin: 2px; }
QScrollBar::handle:horizontal { background: @scroll; border-radius: 3px; min-width: 30px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QLineEdit, QSpinBox { background: @input; border: 1px solid @border; border-radius: 6px; padding: 4px 8px;
                      min-height: 20px; selection-background-color: @accent; selection-color: white; }
QLineEdit:focus, QSpinBox:focus { border: 1px solid @accent; }
QLineEdit:disabled, QSpinBox:disabled { color: @muted; background: @section; }
QLineEdit[readOnly="true"] { color: @muted; background: @section; }
QComboBox { padding: 4px 8px; min-height: 22px; }
QPushButton { background: @card; border: 1px solid @border; border-radius: 6px; padding: 5px 12px; min-height: 20px; }
QPushButton:hover { background: @hover; }
QPushButton:pressed { background: @hover2; }
QPushButton:disabled { color: @muted; background: @section; }
QPushButton[kind="primary"] { background: @accent; border-color: @accent; color: white; font-weight: 600; }
QPushButton[kind="primary"]:hover { background: @accent_hover; }
QPushButton[kind="primary"]:disabled { background: @scroll; border-color: @scroll; }
QPushButton#Seg { border-radius: 0; margin-left: -1px; padding: 4px 12px; }
QPushButton#Seg[pos="first"] { border-top-left-radius: 6px; border-bottom-left-radius: 6px; margin-left: 0; }
QPushButton#Seg[pos="last"] { border-top-right-radius: 6px; border-bottom-right-radius: 6px; }
QPushButton#Seg:checked { background: @accent; border-color: @accent; color: white; }
QPushButton#SectionHead { text-align: left; border: none; border-top: 1px solid @border; border-radius: 0;
                          background: @section; padding: 9px 12px; font-weight: 700; font-size: 11px; color: @muted; }
QPushButton#SectionHead:hover { color: @text; }
QPushButton#Swatch { border: 1px solid @border; border-radius: 5px; padding: 0; min-height: 22px; }
QPushButton#IconBtn { padding: 5px; min-height: 18px; }
QLabel#Title { font-size: 14px; font-weight: 700; }
QLabel#Chip { background: @accent_soft; color: @accent; border-radius: 9px; padding: 2px 9px;
              font-size: 11px; font-weight: 600; }
QLabel#Muted { color: @muted; }
QLabel#RunLabel { font-weight: 700; color: @muted; font-size: 11px; }
QLabel#Thumb { background: @section; border: 1px solid @border; border-radius: 6px; }
QLabel#Strip { background: @section; border: 1px solid @border; border-radius: 6px; padding: 4px; }
QTreeWidget, QListWidget { background: @panel; border: none; outline: 0; }
QTreeWidget::item, QListWidget::item { padding: 5px 4px; border-radius: 5px; }
QTreeWidget::item:selected, QListWidget::item:selected { background: @accent_soft; color: @text; }
QTreeWidget::item:hover:!selected, QListWidget::item:hover:!selected { background: @hover; }
QHeaderView::section { background: @section; border: none; border-bottom: 1px solid @border; padding: 5px 8px; }
QStatusBar { background: @panel; border-top: 1px solid @border; }
QStatusBar::item { border: none; }
QStatusBar QLabel { color: @muted; padding: 0 6px; }
QSplitter::handle { background: @border; }
QCheckBox, QRadioButton { spacing: 8px; }
QDialogButtonBox QPushButton { min-width: 78px; }
QPlainTextEdit { background: @section; border: 1px solid @border; border-radius: 6px; }
QDockWidget::title { background: @panel; border: none; padding: 4px 8px; }
QDockWidget::close-button { subcontrol-origin: title; subcontrol-position: top right; }
QDockWidget::float-button { subcontrol-origin: title; subcontrol-position: top right; }
QDockWidget::close-button:hover, QDockWidget::float-button:hover { background: @hover; }
QDockWidget::close-button:pressed, QDockWidget::float-button:pressed { background: @hover2; }
QComboBox QAbstractItemView { background: @card; border: 1px solid @border; border-radius: 6px; selection-background-color: @accent; selection-color: white; }
QComboBox QAbstractItemView::item { padding: 4px 8px; }
QComboBox QAbstractItemView::item:selected { background: @accent_soft; color: @text; }
QComboBox QAbstractItemView::item:hover:!selected { background: @hover; }
QComboBox QAbstractItemView::item:disabled { color: @muted; }
QComboBox QAbstractItemView::item:!enabled { color: @muted; }
QComboBox QAbstractItemView::item:!enabled:selected { background: @section; color: @muted; }
QComboBox QAbstractItemView::item:!enabled:hover:!selected { background: @section; color: @muted; }
"""


def build_qss(t: dict) -> str:
    out = QSS
    for k in sorted(t, key=len, reverse=True):
        if isinstance(t[k], str):
            out = out.replace("@" + k, t[k])
    return out


def build_palette(t: dict) -> QPalette:
    p = QPalette()
    roles = {QPalette.ColorRole.Window: t["bg"], QPalette.ColorRole.WindowText: t["text"],
             QPalette.ColorRole.Base: t["input"], QPalette.ColorRole.AlternateBase: t["section"],
             QPalette.ColorRole.Text: t["text"], QPalette.ColorRole.Button: t["card"],
             QPalette.ColorRole.ButtonText: t["text"], QPalette.ColorRole.ToolTipBase: t["card"],
             QPalette.ColorRole.ToolTipText: t["text"], QPalette.ColorRole.Highlight: t["accent"],
             QPalette.ColorRole.HighlightedText: "#ffffff", QPalette.ColorRole.PlaceholderText: t["muted"]}
    for role, col in roles.items():
        p.setColor(role, QColor(col))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(t["muted"]))
    return p


class _ProjectSnapshotCommand(QUndoCommand):
    def __init__(self, window, text: str, before: dict, after: dict):
        super().__init__(text)
        self.window = window
        self.before = before
        self.after = after

    def undo(self):
        self.window._restore_snapshot(self.before)

    def redo(self):
        self.window._restore_snapshot(self.after)


class MainWindow(QMainWindow):
    """Main window of the app, with menu, toolbar, canvas and panels."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icon_for("glyph"))
        self.resize(1440, 900)
        self.setMinimumSize(900, 600)
        self._settings = QSettings("IDW20", "IDODialProgram")
        self._theme = self._settings.value("theme", "dark")
        if self._theme not in THEMES:
            self._theme = "dark"
        self._undo_stack = QUndoStack(self)
        self._project = Project.blank()
        self._sim_state = SimState()
        self._canvas = FaceCanvas(self)
        self._preview = PreviewWidget(self)
        self._layers_panel = None
        self._assets_panel = None
        self._sim_panel = None
        self._properties_body = None
        self._properties_layout = None
        self._properties_hint = None
        self._property_fields = {}
        self._run_btn: Optional[QToolButton] = None
        self._run_menu: Optional[QMenu] = None
        self._run_live_action: Optional[QAction] = None
        self._run_shape_action: Optional[QAction] = None
        self._run_shape_btns: Optional[List[QToolButton]] = None
        self._run_shape_group: Optional[QButtonGroup] = None
        self._build_properties()
        self._build_central_canvas()
        self._build_docks()
        self._build_actions()
        self._wire_canvas()
        self._apply_theme()
        self.refresh_view()
        self._undo_stack.setClean()
        self._undo_stack.cleanChanged.connect(self._update_title)
        self._update_title()

    @property
    def project(self) -> Project:
        return self._project

    @property
    def state(self) -> SimState:
        return self._sim_state

    @property
    def canvas(self) -> FaceCanvas:
        return self._canvas

    def _build_central_canvas(self):
        self.setCentralWidget(self._canvas)

    def _build_docks(self):
        left_tabs = QTabWidget()
        self._layers_panel = LayersPanel(self)
        self._assets_panel = AssetsPanel(self)
        left_tabs.addTab(self._layers_panel, "Layers")
        left_tabs.addTab(self._assets_panel, "Assets")
        left = QDockWidget("Project", self)
        left.setObjectName("ProjectDock")
        left.setWidget(left_tabs)
        left.setMinimumWidth(210)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, left)

        right_content = QWidget()
        right_layout = QVBoxLayout(right_content)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        run_header = QFrame()
        run_header.setObjectName("RunHeader")
        run_layout = QHBoxLayout(run_header)
        run_layout.setContentsMargins(8, 6, 8, 6)
        run_layout.setSpacing(5)
        self._run_btn = QToolButton()
        self._run_btn.setObjectName("Primary")
        self._run_btn.setText("RUN")
        self._run_btn.setIcon(icon_for("build"))
        self._run_btn.setToolTip("Compile this face to an .iwf file")
        self._run_btn.clicked.connect(self.compile_project)
        run_layout.addWidget(self._run_btn)
        run_layout.addWidget(muted("PREVIEW", False))
        run_layout.addStretch(1)
        self._run_shape_group = QButtonGroup(self)
        self._run_shape_group.setExclusive(True)
        self._run_shape_btns = []
        for shape, label in (("rounded", "Rounded"), ("rect", "Rect")):
            button = QToolButton()
            button.setText(label)
            button.setCheckable(True)
            button.setToolTip("Preview shape: " + shape)
            button.setChecked(shape == "rounded")
            button.clicked.connect(lambda _checked=False, value=shape: self._preview.set_shape(value))
            self._run_shape_group.addButton(button)
            run_layout.addWidget(button)
            self._run_shape_btns.append(button)
        right_layout.addWidget(run_header)
        right_layout.addWidget(self._preview, 1)

        tabs = QTabWidget()
        self._properties_scroll = QScrollArea()
        self._properties_scroll.setWidgetResizable(True)
        self._properties_scroll.setWidget(self._properties_body)
        tabs.addTab(self._properties_scroll, "Properties")
        self._sim_panel = SimulationPanel(self)
        tabs.addTab(self._sim_panel, "Simulation")
        right_layout.addWidget(tabs, 2)

        right = QDockWidget("Preview & Properties", self)
        right.setObjectName("PreviewDock")
        right.setWidget(right_content)
        right.setMinimumWidth(300)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, right)
        self.resizeDocks([left, right], [250, 350], Qt.Orientation.Horizontal)

    def _build_properties(self):
        self._properties_body = QWidget()
        self._properties_layout = QVBoxLayout(self._properties_body)
        self._properties_layout.setContentsMargins(0, 0, 0, 0)
        self._properties_hint = muted("Select a layer or a widget on the canvas to edit its properties.")
        self._properties_hint.setContentsMargins(14, 14, 14, 14)
        self._properties_layout.addWidget(self._properties_hint)
        self._properties_layout.addStretch(1)

    def _build_actions(self):
        bar = self.menuBar()
        file_menu = bar.addMenu("&File")
        self._action(file_menu, "&New", "Ctrl+N", self.new_project, "new")
        self._action(file_menu, "&Open…", "Ctrl+O", self.open_project, "open")
        self._action(file_menu, "&Save", "Ctrl+S", self.save_project, "save")
        self._action(file_menu, "Save &As…", "Ctrl+Shift+S", self.save_project_as)
        file_menu.addSeparator()
        self._action(file_menu, "Export .iwf…", "", self.compile_project, "build")
        file_menu.addSeparator()
        self._action(file_menu, "E&xit", "Ctrl+Q", self.close)

        edit_menu = bar.addMenu("&Edit")
        edit_menu.addAction(self._undo_stack.createUndoAction(self, "&Undo"))
        edit_menu.addAction(self._undo_stack.createRedoAction(self, "&Redo"))
        edit_menu.addSeparator()
        self._action(edit_menu, "Add widget…", "Insert", self.add_widget_dialog, "add")
        self._action(edit_menu, "Duplicate", "Ctrl+D", self.duplicate_selected, "copy")
        self._action(edit_menu, "Delete", "Delete", self.delete_selected, "trash")

        view_menu = bar.addMenu("&View")
        self._theme_action = QAction("Dark theme", self, checkable=True)
        self._theme_action.setChecked(self._theme == "dark")
        self._theme_action.toggled.connect(self._set_theme)
        view_menu.addAction(self._theme_action)
        view_menu.addSeparator()
        for label, attr, checked in (("Grid", "show_grid", False), ("Snap", "snap", True),
                                     ("Guides", "show_guides", True), ("Widget bounds", "show_bounds", False)):
            action = QAction(label, self, checkable=True)
            action.setChecked(checked)
            action.toggled.connect(lambda on, name=attr: self._set_canvas_option(name, on))
            view_menu.addAction(action)
        view_menu.addSeparator()
        self._action(view_menu, "Zoom in", "Ctrl++", lambda: self._canvas.zoom_by(1.2), "zoom_in")
        self._action(view_menu, "Zoom out", "Ctrl+-", lambda: self._canvas.zoom_by(1 / 1.2), "zoom_out")
        self._action(view_menu, "Fit canvas", "Ctrl+0", self._canvas.fit_view, "fit")

        tools_menu = bar.addMenu("&Tools")
        self._action(tools_menu, "Check project…", "", self.check_project, "warn")
        self._action(tools_menu, "Generate preview.png", "", self.generate_preview, "image")

        help_menu = bar.addMenu("&Help")
        self._action(help_menu, "&About", "", lambda: AboutDialog(self).exec(), "info")

        toolbar = QToolBar("Main")
        toolbar.setObjectName("MainToolBar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        for name, text, slot, icon in (
            ("New", "New", self.new_project, "new"),
            ("Open", "Open", self.open_project, "open"),
            ("Save", "Save", self.save_project, "save"),
        ):
            action = QAction(icon_for(icon), text, self)
            action.triggered.connect(slot)
            toolbar.addAction(action)
        toolbar.addSeparator()
        undo_action = self._undo_stack.createUndoAction(self, "Undo")
        undo_action.setIcon(icon_for("undo"))
        toolbar.addAction(undo_action)
        redo_action = self._undo_stack.createRedoAction(self, "Redo")
        redo_action.setIcon(icon_for("redo"))
        toolbar.addAction(redo_action)
        toolbar.addSeparator()
        self._action(toolbar, "Add widget", "Insert", self.add_widget_dialog, "add")
        self._action(toolbar, "Duplicate", "Ctrl+D", self.duplicate_selected, "copy")
        self._action(toolbar, "Delete", "Delete", self.delete_selected, "trash")
        toolbar.addSeparator()
        self._action(toolbar, "Zoom out", "", lambda: self._canvas.zoom_by(1 / 1.2), "zoom_out")
        self._action(toolbar, "Fit canvas", "Ctrl+0", self._canvas.fit_view, "fit")
        self._action(toolbar, "Zoom in", "", lambda: self._canvas.zoom_by(1.2), "zoom_in")

    def _action(self, parent, text: str, shortcut: str, slot, icon: Optional[str] = None):
        action = QAction(icon_for(icon), text, self) if icon else QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        parent.addAction(action)
        return action

    def _wire_canvas(self):
        self._canvas.selectionChanged.connect(self.select)
        self._canvas.liveChanged.connect(lambda: self.refresh_view(rebuild_panels=False))
        self._canvas.edited.connect(self._push_edit)
        self._canvas.cursorMoved.connect(
            lambda x, y: self.statusBar().showMessage("X: %d    Y: %d    Zoom: %d%%" %
                                                       (x, y, round(self._canvas.zoom * 100))))
        self._canvas.zoomChanged.connect(
            lambda z: self.statusBar().showMessage("Zoom: %d%%" % round(z * 100)))
        self._canvas.deleteRequested.connect(self.delete_selected)

    def _apply_theme(self):
        theme = THEMES[self._theme]
        self.setPalette(build_palette(theme))
        self.setStyleSheet(build_qss(theme))
        ICON_COLOR[0] = theme["icon"]
        self._canvas.set_theme(self._theme)
        self._preview.set_dark(theme["dark"])
        if self._layers_panel is not None:
            self._layers_panel.refresh_icons()

    def _set_theme(self, dark: bool):
        self._theme = "dark" if dark else "light"
        self._settings.setValue("theme", self._theme)
        self._apply_theme()
        self.refresh_view()

    def _set_canvas_option(self, name: str, value: bool):
        setattr(self._canvas, name, value)
        self._canvas.update()

    def _update_title(self, *_):
        path = self._project.path
        name = os.path.basename(path) if path else self._project.name
        marker = "" if self._undo_stack.isClean() else " *"
        self.setWindowTitle("%s — %s%s" % (APP_NAME, name or "Untitled", marker))

    def refresh_view(self, rebuild_panels: bool = True):
        face = render_face(self._project, self._sim_state)
        self._canvas.set_face(face, self._sim_state)
        self._preview.set_face(face)
        if rebuild_panels:
            if self._layers_panel is not None:
                self._layers_panel.rebuild()
            if self._assets_panel is not None:
                self._assets_panel.rebuild()
            if self._sim_panel is not None:
                self._sim_panel.sync()
            self._refresh_properties()
        self._update_title()

    def _restore_snapshot(self, snapshot: dict):
        self._project.restore(snapshot)
        selected = self._canvas.selected_uid
        if self._project.widget_by_uid(selected) is None:
            selected = -1
        self._canvas.set_project(self._project)
        self._canvas.set_selected(selected)
        self.refresh_view()

    def _push_edit(self, text: str, before: dict):
        self._commit_snapshot(text, before)

    def _commit_snapshot(self, text: str, before: dict):
        after = self._project.snapshot()
        self._undo_stack.push(_ProjectSnapshotCommand(self, text, before, after))

    def select(self, uid: int, from_layers: bool = False):
        self._canvas.set_selected(uid)
        if self._layers_panel is not None and not from_layers:
            self._layers_panel.select(uid)
        self._refresh_properties()

    def _refresh_properties(self):
        layout = self._properties_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._property_fields = {}
        widget = self._project.widget_by_uid(self._canvas.selected_uid)
        if widget is None:
            hint = muted("Select a layer or a widget on the canvas to edit its properties.")
            hint.setContentsMargins(14, 14, 14, 14)
            layout.addWidget(hint)
            layout.addStretch(1)
            return

        title = QLabel(widget.title)
        title.setObjectName("Title")
        title.setContentsMargins(14, 12, 14, 4)
        layout.addWidget(title)
        geometry = Section("Position and size")
        for key, label, lo, hi in (("x", "X", -1000, 1000), ("y", "Y", -1000, 1000),
                                   ("w", "Width", 1, 9999), ("h", "Height", 1, 9999)):
            field = NumField(lo, hi, " px")
            field.set_quiet(widget.geti(key))
            field.editingFinished.connect(
                lambda k=key, f=field, uid=widget.uid: self._set_widget_property(uid, k, f.value()))
            self._property_fields[key] = field
            geometry.add_pair(label, field, "", QLabel())
        layout.addWidget(geometry)

        if not widget.is_analog:
            appearance = Section("Appearance")
            color = ColorField(widget.data.get("fgcolor", "0xFFFFFFFF"))
            color.changed.connect(
                lambda value, uid=widget.uid: self._set_widget_property(uid, "fgcolor", value))
            appearance.add_row("Color", color)
            align = QComboBox()
            for value, label in (("left", "Left"), ("center", "Center"), ("right", "Right")):
                align.addItem(label, value)
            align.setCurrentIndex(max(0, align.findData(widget.data.get("align", "left"))))
            align.currentIndexChanged.connect(
                lambda _index, box=align, uid=widget.uid: self._set_widget_property(uid, "align", box.currentData()))
            appearance.add_row("Alignment", align)
            layout.addWidget(appearance)
        else:
            for kind, prefix in HAND_DEFS:
                section = Section("%s hand" % kind.title(), kind != "second")
                for suffix, label, limit in (("anchorx", "Anchor X", SCREEN_W), ("anchory", "Anchor Y", SCREEN_H),
                                             ("centerx", "Pivot X", 1000), ("centery", "Pivot Y", 1000)):
                    key = prefix + suffix
                    field = NumField(-limit, limit, " px")
                    field.set_quiet(widget.geti(key))
                    field.editingFinished.connect(
                        lambda k=key, f=field, uid=widget.uid: self._set_widget_property(uid, k, f.value()))
                    section.add_pair(label, field, "", QLabel())
                layout.addWidget(section)
        layout.addStretch(1)

    def _set_widget_property(self, uid: int, key: str, value):
        widget = self._project.widget_by_uid(uid)
        if widget is None or widget.data.get(key) == value:
            return
        before = self._project.snapshot()
        widget.data[key] = value
        self._commit_snapshot("Change %s" % key, before)
        self.refresh_view()
        self.select(uid)

    def add_widget_dialog(self):
        dialog = AddWidgetDialog(self._project, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._add_widget(dialog.config())

    def _add_widget(self, config: dict):
        key = config.get("key")
        if key not in WIDGET_SPECS:
            return
        before = self._project.snapshot()
        if key == ("watch", "time"):
            data = make_widget_data(key, 0, 0, SCREEN_W, SCREEN_H)
            for kind, prefix in HAND_DEFS:
                image, pivot = make_default_hand(kind, config.get("hand_color", (255, 255, 255)))
                name = self._project.unique_image_name({"hour": "h.png", "minute": "m.png",
                                                        "second": "s.png"}[kind])
                self._project.images[name] = image
                data[kind] = name
                data[prefix + "centerx"], data[prefix + "centery"] = pivot
                data[prefix + "anchorx"], data[prefix + "anchory"] = SCREEN_W // 2, SCREEN_H // 2
        else:
            if config.get("mode") == "reuse":
                set_name = config.get("set_name")
                glyphs = self._project.glyphs.get(set_name, {})
                if not glyphs:
                    QMessageBox.warning(self, "Add widget", "The selected glyph set is empty.")
                    return
            else:
                set_name = self._project.unique_fontset_name(key[1])
                glyphs = generate_glyph_set(sample_stems(key), config["style"])
                self._project.ensure_fontset(set_name)
                self._project.glyphs[set_name] = glyphs
            spec = WIDGET_SPECS[key]
            width = max_text_width(glyphs, spec["layout"])
            height = max((image.height for image in glyphs.values()), default=24)
            data = make_widget_data(key, (SCREEN_W - width) // 2, (SCREEN_H - height) // 2,
                                    max(1, width), max(1, height), font=set_name)
        self._project.items.append(Widget(data))
        added = self._project.items[-1]
        self._canvas.set_project(self._project)
        self._canvas.set_selected(added.uid)
        self._commit_snapshot("Add %s" % added.title, before)
        self.refresh_view()
        self.select(added.uid)

    def duplicate_selected(self):
        source = self._project.widget_by_uid(self._canvas.selected_uid)
        if source is None:
            return
        before = self._project.snapshot()
        data = copy.deepcopy(source.data)
        if not source.is_analog:
            data["x"] = source.x + 10
            data["y"] = source.y + 10
        else:
            for _, prefix in HAND_DEFS:
                data[prefix + "anchorx"] = source.geti(prefix + "anchorx") + 10
                data[prefix + "anchory"] = source.geti(prefix + "anchory") + 10
        duplicate = Widget(data)
        self._project.items.insert(self._project.items.index(source) + 1, duplicate)
        self._canvas.set_selected(duplicate.uid)
        self._commit_snapshot("Duplicate %s" % source.title, before)
        self.refresh_view()
        self.select(duplicate.uid)

    def delete_selected(self):
        uid = self._canvas.selected_uid
        widget = self._project.widget_by_uid(uid)
        if widget is None:
            return
        before = self._project.snapshot()
        self._project.items.remove(widget)
        self._canvas.set_selected(-1)
        self._commit_snapshot("Delete %s" % widget.title, before)
        self.refresh_view()

    def move_selected(self, direction: int):
        widget = self._project.widget_by_uid(self._canvas.selected_uid)
        if widget is None:
            return
        index = self._project.items.index(widget)
        target = index + direction
        if not 0 <= target < len(self._project.items):
            return
        before = self._project.snapshot()
        self._project.items[index], self._project.items[target] = self._project.items[target], self._project.items[index]
        self._commit_snapshot("Reorder %s" % widget.title, before)
        self.refresh_view()

    def new_project(self):
        if not self._confirm_discard():
            return
        self._project = Project.blank()
        self._sim_state = SimState()
        self._project.path = None
        self._undo_stack.clear()
        self._canvas.set_project(self._project)
        self._canvas.set_selected(-1)
        self.refresh_view()
        self._undo_stack.setClean()

    def open_project(self):
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open face project", "", "Face projects (*.iwf *.zip);;All files (*)")
        if not path:
            return
        try:
            project = Project.load(path)
        except (OSError, ValueError, KeyError, TypeError) as error:
            QMessageBox.critical(self, "Open project", str(error))
            return
        self._project = project
        self._sim_state = SimState()
        self._undo_stack.clear()
        self._canvas.set_project(self._project)
        self._canvas.set_selected(-1)
        self.refresh_view()
        self._undo_stack.setClean()
        if project.load_warnings:
            QMessageBox.warning(self, "Project loaded with warnings", "\n".join(project.load_warnings))

    def save_project(self):
        path = self._project.path
        if not path:
            self.save_project_as()
            return
        self._save_to(path)

    def save_project_as(self):
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "Save face project", self._project.name + ".zip",
            "Face project archive (*.zip);;Project folder (*)")
        if not path:
            return
        if selected_filter.startswith("Face project archive") and not path.lower().endswith(".zip"):
            path += ".zip"
        self._save_to(path)

    def _save_to(self, path: str):
        try:
            if path.lower().endswith(".zip"):
                self._project.save_zip(path)
            else:
                self._project.save_dir(path)
        except (OSError, ValueError, TypeError) as error:
            QMessageBox.critical(self, "Save project", str(error))
            return
        self._project.path = path
        self._undo_stack.setClean()
        self._update_title()
        self.statusBar().showMessage("Saved %s" % path, 5000)

    def compile_project(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export compiled watch face", self._project.name + ".iwf",
                                              "IWF Files (*.iwf)")
        if not path:
            return
        if not path.lower().endswith(".iwf"):
            path += ".iwf"
        problems = self._project.validate()
        errors = [problem for problem in problems if problem[0] == "error"]
        if errors:
            self._show_problems(problems)
            return
        try:
            self._project.images[self._project.preview_name] = render_preview_png(self._project, self._sim_state)
            notes = self._project.compile(path)
        except (OSError, ValueError, KeyError, TypeError) as error:
            QMessageBox.critical(self, "Export watch face", str(error))
            return
        self.refresh_view()
        message = "Exported %s" % path
        if notes:
            message += "\n\n" + "\n".join(notes)
        QMessageBox.information(self, "Export complete", message)

    def generate_preview(self):
        before = self._project.snapshot()
        self._project.images[self._project.preview_name] = render_preview_png(self._project, self._sim_state)
        self._commit_snapshot("Generate preview.png", before)
        self.refresh_view()

    def check_project(self):
        self._show_problems(self._project.validate())

    def _show_problems(self, problems):
        dialog = ProblemsDialog(problems, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_uid >= 0:
            self.select(dialog.selected_uid)

    def _confirm_discard(self) -> bool:
        if self._undo_stack.isClean():
            return True
        answer = QMessageBox.question(self, "Unsaved changes", "Discard unsaved project changes?",
                                      QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Cancel)
        return answer == QMessageBox.StandardButton.Discard

    def _set_dirty(self, text: str):
        self.statusBar().showMessage(text, 4000)

    def _refresh_assets(self):
        if self._assets_panel is not None:
            self._assets_panel.rebuild()

    def _replace_asset(self, kind: str, name: str):
        path, _ = QFileDialog.getOpenFileName(self, "Replace image", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        try:
            with Image.open(path) as source:
                image = source.convert("RGBA")
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "Replace image", str(error))
            return
        before = self._project.snapshot()
        if kind == "bg":
            self._project.images[self._project.bkground] = image
        elif kind == "preview":
            self._project.images[self._project.preview_name] = image
        elif kind == "hand":
            self._project.images[name] = image
        self._commit_snapshot("Replace %s image" % kind, before)
        self.refresh_view()

    def _regenerate_glyphs(self, name: str):
        dialog = GlyphDialog(name, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        before = self._project.snapshot()
        try:
            self._project.glyphs[name] = generate_glyph_set(
                self._charset_for_set(name), dialog.editor.style())
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "Regenerate glyphs", str(error))
            return
        if dialog.fit.isChecked():
            for widget in self._project.items:
                if widget.font == name and not widget.is_analog:
                    widget.w = max_text_width(self._project.glyphs[name], widget.spec["layout"])
                    widget.h = max((im.height for im in self._project.glyphs[name].values()), default=widget.h)
        self._commit_snapshot("Regenerate glyph set %s" % name, before)
        self.refresh_view()

    def _charset_for_set(self, name: str):
        for widget in self._project.items:
            if widget.font == name and widget.spec and widget.spec.get("charset"):
                return CHARSETS[widget.spec["charset"]]
        return CHARSETS["digits"]

    def closeEvent(self, event):
        if self._confirm_discard():
            self._settings.setValue("theme", self._theme)
            event.accept()
        else:
            event.ignore()

# =====================================================================================
#  Icons (drawn in code, so there are no resource files)
# =====================================================================================
ICON_COLOR = ["#5b6272"]
ICONS: Dict[str, Callable] = {}
_ICON_CACHE: Dict[tuple, QIcon] = {}


def _icon(*names):
    def deco(f):
        for n in names:
            ICONS[n] = f
        return f
    return deco


def _pts(*xy):
    return QPolygonF([QPointF(x, y) for x, y in xy])


def _ln(p, x1, y1, x2, y2):
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))


def make_icon(name: str, color: Optional[str] = None, size: int = 18) -> QIcon:
    color = color or ICON_COLOR[0]
    key = (name, color, size)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.GlobalColor.transparent)
    pm.setDevicePixelRatio(2.0)
    fn = ICONS.get(name)
    if fn is not None:
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(size / 24.0, size / 24.0)
        pen = QPen(QColor(color), 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        fn(p, QColor(color))
        p.end()
    _ICON_CACHE[key] = QIcon(pm)
    return _ICON_CACHE[key]


@_icon("new")
def _i_new(p, c):
    p.drawPolyline(_pts((6, 3), (14, 3), (19, 8), (19, 21), (6, 21), (6, 3)))
    p.drawPolyline(_pts((14, 3), (14, 8), (19, 8)))
    _ln(p, 12.5, 12, 12.5, 18)
    _ln(p, 9.7, 15, 15.3, 15)


@_icon("open")
def _i_open(p, c):
    p.drawPolyline(_pts((3, 19), (3, 6), (9, 6), (11, 9), (19, 9), (19, 12)))
    p.drawPolyline(_pts((3, 19), (6, 12), (22, 12), (19, 19), (3, 19)))


@_icon("save")
def _i_save(p, c):
    p.drawPolyline(_pts((4, 4), (17, 4), (20, 7), (20, 20), (4, 20), (4, 4)))
    p.drawRect(QRectF(8, 4, 7, 5))
    p.drawRect(QRectF(7, 13, 10, 7))


@_icon("build")
def _i_build(p, c):
    p.drawRect(QRectF(7, 7, 10, 10))
    for i in (10, 14):
        _ln(p, i, 3, i, 7)
        _ln(p, i, 17, i, 21)
        _ln(p, 3, i, 7, i)
        _ln(p, 17, i, 21, i)


@_icon("undo")
def _i_undo(p, c):
    p.drawPolyline(_pts((9, 6), (4, 11), (9, 16)))
    p.drawPolyline(_pts((4, 11), (14, 11), (19, 13), (19, 17), (14, 19), (8, 19)))


@_icon("redo")
def _i_redo(p, c):
    p.translate(24, 0)
    p.scale(-1, 1)
    _i_undo(p, c)


@_icon("add")
def _i_add(p, c):
    _ln(p, 12, 5, 12, 19)
    _ln(p, 5, 12, 19, 12)


@_icon("trash")
def _i_trash(p, c):
    _ln(p, 4, 7, 20, 7)
    p.drawPolyline(_pts((9, 7), (9, 4), (15, 4), (15, 7)))
    p.drawPolyline(_pts((6, 7), (7, 21), (17, 21), (18, 7)))
    _ln(p, 10, 11, 10, 17)
    _ln(p, 14, 11, 14, 17)


@_icon("copy")
def _i_copy(p, c):
    p.drawRect(QRectF(8, 8, 12, 12))
    p.drawPolyline(_pts((16, 8), (16, 4), (4, 4), (4, 16), (8, 16)))


@_icon("up")
def _i_up(p, c):
    p.drawPolyline(_pts((6, 14), (12, 8), (18, 14)))


@_icon("down")
def _i_down(p, c):
    p.drawPolyline(_pts((6, 10), (12, 16), (18, 10)))


@_icon("eye")
def _i_eye(p, c):
    p.drawPolyline(_pts((2, 12), (7, 6.5), (12, 5), (17, 6.5), (22, 12), (17, 17.5), (12, 19), (7, 17.5), (2, 12)))
    p.drawEllipse(QPointF(12, 12), 3.2, 3.2)


@_icon("eye_off")
def _i_eye_off(p, c):
    _i_eye(p, c)
    _ln(p, 4, 20, 20, 4)


@_icon("lock")
def _i_lock(p, c):
    p.drawRect(QRectF(5, 11, 14, 10))
    p.drawPolyline(_pts((8, 11), (8, 7), (10, 4.5), (14, 4.5), (16, 7), (16, 11)))


@_icon("unlock")
def _i_unlock(p, c):
    p.drawRect(QRectF(5, 11, 14, 10))
    p.drawPolyline(_pts((8, 11), (8, 7), (10, 4.5), (14, 4.5), (16, 7)))


@_icon("grid")
def _i_grid(p, c):
    for v in (4, 9.3, 14.7, 20):
        _ln(p, v, 4, v, 20)
        _ln(p, 4, v, 20, v)


@_icon("snap")
def _i_snap(p, c):
    p.drawPolyline(_pts((6, 4), (6, 13), (8, 18), (12, 20), (16, 18), (18, 13), (18, 4)))
    _ln(p, 6, 8, 10, 8)
    _ln(p, 14, 8, 18, 8)


@_icon("fit")
def _i_fit(p, c):
    for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
        x0, y0 = (4 if sx > 0 else 20), (4 if sy > 0 else 20)
        p.drawPolyline(_pts((x0 + sx * 5, y0), (x0, y0), (x0, y0 + sy * 5)))


@_icon("zoom_in", "zoom_out")
def _i_zoom(p, c):
    p.drawEllipse(QPointF(10.5, 10.5), 6.5, 6.5)
    _ln(p, 15.5, 15.5, 20.5, 20.5)
    _ln(p, 7.5, 10.5, 13.5, 10.5)


@_icon("zoom_in")
def _i_zoom_in(p, c):
    _i_zoom(p, c)
    _ln(p, 10.5, 7.5, 10.5, 13.5)


@_icon("clock")
def _i_clock(p, c):
    p.drawEllipse(QPointF(12, 12), 8.5, 8.5)
    p.drawPolyline(_pts((12, 7), (12, 12), (15.5, 14)))


@_icon("calendar")
def _i_calendar(p, c):
    p.drawRect(QRectF(4, 6, 16, 14))
    _ln(p, 4, 10.5, 20, 10.5)
    _ln(p, 8.5, 3.5, 8.5, 8)
    _ln(p, 15.5, 3.5, 15.5, 8)
    _ln(p, 8, 14.5, 10, 14.5)
    _ln(p, 14, 14.5, 16, 14.5)


@_icon("weekday")
def _i_weekday(p, c):
    _i_calendar(p, c)
    _ln(p, 8, 17.5, 16, 17.5)


@_icon("cloud")
def _i_cloud(p, c):
    p.drawPolyline(_pts((7, 18), (5, 18), (3.5, 16), (3.8, 13.5), (6, 12), (7, 9), (10, 7), (13.5, 8), (15, 10),
                        (18, 10.5), (20, 13), (19, 16.5), (17, 18), (7, 18)))


@_icon("battery")
def _i_battery(p, c):
    p.drawRect(QRectF(3, 7.5, 16, 9))
    _ln(p, 21, 10.5, 21, 13.5)
    p.drawRect(QRectF(5.5, 10, 8, 4))


@_icon("steps")
def _i_steps(p, c):
    p.drawEllipse(QPointF(8.5, 8), 2.6, 4)
    p.drawEllipse(QPointF(15.5, 16), 2.6, 4)
    _ln(p, 8.5, 13.5, 8.5, 14.2)


@_icon("flame")
def _i_flame(p, c):
    p.drawPolyline(_pts((12, 3), (15.5, 8), (18, 12), (17.5, 16.5), (14.5, 20), (12, 21), (9.5, 20), (6.5, 16.5),
                        (6, 12.5), (8.5, 10), (9.5, 12), (10.5, 8), (12, 3)))


@_icon("hands")
def _i_hands(p, c):
    p.drawEllipse(QPointF(12, 12), 8.5, 8.5)
    _ln(p, 12, 12, 12, 6.5)
    _ln(p, 12, 12, 16.5, 14.5)
    _ln(p, 12, 3.5, 12, 4.8)
    _ln(p, 12, 19.2, 12, 20.5)
    _ln(p, 3.5, 12, 4.8, 12)
    _ln(p, 19.2, 12, 20.5, 12)


@_icon("image")
def _i_image(p, c):
    p.drawRect(QRectF(3.5, 5, 17, 14))
    p.drawPolyline(_pts((3.5, 16), (9, 11), (13, 15), (16, 12.5), (20.5, 17)))
    p.drawEllipse(QPointF(8, 9), 1.6, 1.6)


@_icon("glyph")
def _i_glyph(p, c):
    p.drawPolyline(_pts((5, 19), (12, 4.5), (19, 19)))
    _ln(p, 8, 14, 16, 14)


@_icon("bolt")
def _i_bolt(p, c):
    p.drawPolyline(_pts((13, 3), (6, 13), (11, 13), (10, 21), (18, 10), (13, 10), (13, 3)))


@_icon("info")
def _i_info(p, c):
    p.drawEllipse(QPointF(12, 12), 8.5, 8.5)
    _ln(p, 12, 11, 12, 16.5)
    _ln(p, 12, 7.6, 12, 7.8)


@_icon("warn")
def _i_warn(p, c):
    p.drawPolyline(_pts((12, 4), (21, 19.5), (3, 19.5), (12, 4)))
    _ln(p, 12, 10, 12, 14.5)
    _ln(p, 12, 17, 12, 17.2)


@_icon("error")
def _i_error(p, c):
    p.drawEllipse(QPointF(12, 12), 8.5, 8.5)
    _ln(p, 8.5, 8.5, 15.5, 15.5)
    _ln(p, 15.5, 8.5, 8.5, 15.5)


@_icon("al_left")
def _i_al_left(p, c):
    _ln(p, 4, 3.5, 4, 20.5)
    p.drawRect(QRectF(7, 6, 12, 4.5))
    p.drawRect(QRectF(7, 13.5, 8, 4.5))


@_icon("al_hcenter")
def _i_al_hc(p, c):
    _ln(p, 12, 3.5, 12, 20.5)
    p.drawRect(QRectF(5, 6, 14, 4.5))
    p.drawRect(QRectF(7.5, 13.5, 9, 4.5))


@_icon("al_right")
def _i_al_right(p, c):
    _ln(p, 20, 3.5, 20, 20.5)
    p.drawRect(QRectF(5, 6, 12, 4.5))
    p.drawRect(QRectF(9, 13.5, 8, 4.5))


@_icon("al_top")
def _i_al_top(p, c):
    _ln(p, 3.5, 4, 20.5, 4)
    p.drawRect(QRectF(6, 7, 4.5, 12))
    p.drawRect(QRectF(13.5, 7, 4.5, 8))


@_icon("al_vcenter")
def _i_al_vc(p, c):
    _ln(p, 3.5, 12, 20.5, 12)
    p.drawRect(QRectF(6, 5, 4.5, 14))
    p.drawRect(QRectF(13.5, 7.5, 4.5, 9))


@_icon("al_bottom")
def _i_al_bottom(p, c):
    _ln(p, 3.5, 20, 20.5, 20)
    p.drawRect(QRectF(6, 5, 4.5, 12))
    p.drawRect(QRectF(13.5, 9, 4.5, 8))


@_icon("popout")
def _i_popout(p, c):
    p.drawPolyline(_pts((10, 5), (5, 5), (5, 19), (19, 19), (19, 14)))
    p.drawPolyline(_pts((13, 4.5), (19.5, 4.5), (19.5, 11)))
    _ln(p, 19.5, 4.5, 11, 13)


TYPE_ICONS = {("custom", "time"): "clock", ("custom", "date"): "calendar", ("custom", "week"): "weekday",
              ("custom", "day"): "calendar", ("custom", "hour"): "clock", ("custom", "min"): "clock",
              ("custom", "weather"): "cloud", ("custom", "battery"): "battery", ("custom", "step"): "steps",
              ("custom", "calorie"): "flame", ("watch", "time"): "hands"}


def icon_for(name: str, size: int = 18) -> QIcon:
    return make_icon(name, ICON_COLOR[0], size)


def widget_icon(w: Widget, size: int = 18) -> QIcon:
    return icon_for(TYPE_ICONS.get(w.key, "glyph"), size)


def pix_from_pil(im, box: Tuple[int, int] = (44, 44), bg=(48, 51, 59, 255)) -> QPixmap:
    im = im.convert("RGBA")
    sc = min(box[0] / im.width, box[1] / im.height, 4.0)
    tw, th = max(1, int(im.width * sc)), max(1, int(im.height * sc))
    small = im.resize((tw, th), Image.LANCZOS)
    base = Image.new("RGBA", (tw, th), bg)
    base.alpha_composite(small)
    return QPixmap.fromImage(pil_to_qimage(base))


# =====================================================================================
#  Reusable controls
# =====================================================================================
class NumField(QSpinBox):
    """Compact number field: no spin arrows, wheel only works while focused, commits on Enter / focus-out."""

    def __init__(self, lo: int, hi: int, suffix: str = " px", parent=None):
        super().__init__(parent)
        self.setRange(lo, hi)
        self.setSuffix(suffix)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setKeyboardTracking(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccelerated(True)

    def wheelEvent(self, e):
        if self.hasFocus():
            super().wheelEvent(e)
        else:
            e.ignore()

    def set_quiet(self, v: int):
        self.blockSignals(True)
        self.setValue(int(v))
        self.blockSignals(False)


class Segmented(QWidget):
    """Joined toggle buttons, one active at a time."""
    changed = pyqtSignal(object)

    def __init__(self, items: List[Tuple[object, str, str]], parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: Dict[object, QPushButton] = {}
        for i, (val, text, tip) in enumerate(items):
            b = QPushButton(text)
            b.setObjectName("Seg")
            b.setCheckable(True)
            b.setToolTip(tip)
            b.setProperty("pos", "first" if i == 0 else "last" if i == len(items) - 1 else "mid")
            b.clicked.connect(lambda _=False, v=val: self.changed.emit(v))
            self.group.addButton(b)
            h.addWidget(b)
            self.buttons[val] = b

    def set_value(self, v):
        for k, b in self.buttons.items():
            b.blockSignals(True)
            b.setChecked(k == v)
            b.blockSignals(False)


class ColorField(QWidget):
    """Swatch + AARRGGBB hex box; emits '0xAARRGGBB'."""
    changed = pyqtSignal(str)

    def __init__(self, value: str = "0xFFFFFFFF", parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self.sw = QPushButton()
        self.sw.setObjectName("Swatch")
        self.sw.setFixedSize(30, 26)
        self.sw.setToolTip("Pick a colour")
        self.edit = QLineEdit()
        self.edit.setMaxLength(8)
        self.edit.setPlaceholderText("AARRGGBB")
        self.edit.setValidator(QRegularExpressionValidator(QRegularExpression("[0-9A-Fa-f]{0,8}")))
        h.addWidget(self.sw)
        h.addWidget(self.edit, 1)
        self._value = value
        self.sw.clicked.connect(self._pick)
        self.edit.editingFinished.connect(self._typed)
        self.set_value(value)

    def value(self) -> str:
        return self._value

    def rgb(self) -> Tuple[int, int, int]:
        r, g, b, _ = color_from_str(self._value)
        return r, g, b

    def set_value(self, s: str):
        self._value = s
        r, g, b, a = color_from_str(s)
        self.edit.blockSignals(True)
        self.edit.setText("%02X%02X%02X%02X" % (a, r, g, b))
        self.edit.blockSignals(False)
        self.sw.setStyleSheet("QPushButton#Swatch { background-color: rgba(%d,%d,%d,%d); }" % (r, g, b, a))

    def _pick(self):
        r, g, b, a = color_from_str(self._value)
        c = QColorDialog.getColor(QColor(r, g, b, a), self, "Choose colour",
                                  QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if c.isValid():
            self._emit(color_to_str(c.red(), c.green(), c.blue(), c.alpha()))

    def _typed(self):
        t = self.edit.text().strip()
        if len(t) == 6:
            t = "FF" + t
        if len(t) == 8:
            self._emit("0x" + t.upper())
        else:
            self.set_value(self._value)

    def _emit(self, s: str):
        if s != self._value:
            self.set_value(s)
            self.changed.emit(s)


class Section(QFrame):
    """Collapsible property group with a 4-column grid: [label][field][label][field]."""

    def __init__(self, title: str, expanded: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("Section")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.title = title.upper()
        self.head = QPushButton()
        self.head.setObjectName("SectionHead")
        self.head.setCheckable(True)
        self.head.setChecked(expanded)
        self.head.setCursor(Qt.CursorShape.PointingHandCursor)
        self.body = QWidget()
        self.grid = QGridLayout(self.body)
        self.grid.setContentsMargins(14, 10, 14, 14)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(8)
        self.grid.setColumnStretch(1, 1)
        self.grid.setColumnStretch(3, 1)
        self._row = 0
        v.addWidget(self.head)
        v.addWidget(self.body)
        self.head.toggled.connect(self._toggle)
        self._toggle(expanded)

    def _toggle(self, on: bool):
        self.head.setText(("\u25BE  " if on else "\u25B8  ") + self.title)
        self.body.setVisible(on)

    def _label(self, text: str, tip: str = "") -> QLabel:
        l = QLabel(text)
        l.setObjectName("Muted")
        if tip:
            l.setToolTip(tip)
        return l

    def add_row(self, label: str, widget: QWidget, tip: str = ""):
        self.grid.addWidget(self._label(label, tip), self._row, 0)
        self.grid.addWidget(widget, self._row, 1, 1, 3)
        if tip:
            widget.setToolTip(tip)
        self._row += 1

    def add_pair(self, l1: str, w1: QWidget, l2: str, w2: QWidget, tip1: str = "", tip2: str = ""):
        self.grid.addWidget(self._label(l1, tip1), self._row, 0)
        self.grid.addWidget(w1, self._row, 1)
        self.grid.addWidget(self._label(l2, tip2), self._row, 2)
        self.grid.addWidget(w2, self._row, 3)
        self._row += 1

    def add_wide(self, widget: QWidget):
        self.grid.addWidget(widget, self._row, 0, 1, 4)
        self._row += 1


def hbox(*widgets, spacing: int = 6, stretch_last: bool = False) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(spacing)
    for x in widgets:
        h.addWidget(x)
    if stretch_last:
        h.addStretch(1)
    return w


def muted(text: str, wrap: bool = True) -> QLabel:
    l = QLabel(text)
    l.setObjectName("Muted")
    l.setWordWrap(wrap)
    return l


# =====================================================================================
#  Dialogs
# =====================================================================================
class GlyphStyleEditor(QWidget):
    """Font / size / colours of generated glyph images, with a live sample strip."""
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        s = Section("Glyph style", True)
        s.head.setEnabled(False)
        self.font_edit = QLineEdit(default_font_path() or "")
        self.font_edit.setPlaceholderText("Pillow's built-in font")
        browse = QPushButton("Browse\u2026")
        browse.clicked.connect(self._browse)
        s.add_row("Font file", hbox(self.font_edit, browse, spacing=6))
        self.ink = NumField(8, 140)
        self.ink.setValue(28)
        s.add_row("Digit height", self.ink, "Height of the digits in pixels; the cell height follows.")
        self.top = ColorField("0xFFFFFFFF")
        self.bottom = ColorField("0xFFFFFFFF")
        s.add_row("Fill (top)", self.top)
        s.add_row("Fill (bottom)", self.bottom, "Vertical gradient from the top colour to this one.")
        self.outline_on = QCheckBox("Outline")
        self.outline_c = ColorField("0xFF000000")
        self.outline_px = NumField(1, 6)
        self.outline_px.setValue(1)
        s.add_row("", self.outline_on)
        s.add_row("Outline", hbox(self.outline_c, self.outline_px, spacing=6))
        self.glow_on = QCheckBox("Glow")
        self.glow_c = ColorField("0xFF00E5FF")
        self.glow_px = NumField(1, 12)
        self.glow_px.setValue(3)
        s.add_row("", self.glow_on)
        s.add_row("Glow", hbox(self.glow_c, self.glow_px, spacing=6))
        self.sample = QLabel()
        self.sample.setObjectName("Strip")
        self.sample.setMinimumHeight(60)
        s.add_wide(self.sample)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(s)
        for w in (self.top, self.bottom, self.outline_c, self.glow_c):
            w.changed.connect(self._changed)
        for w in (self.ink, self.outline_px, self.glow_px):
            w.valueChanged.connect(self._changed)
        for w in (self.outline_on, self.glow_on):
            w.toggled.connect(self._changed)
        self.font_edit.editingFinished.connect(self._changed)
        self._update_sample()

    def _browse(self):
        p, _ = QFileDialog.getOpenFileName(self, "Choose a font", self.font_edit.text(),
                                           "Fonts (*.ttf *.otf *.ttc);;All files (*)")
        if p:
            self.font_edit.setText(p)
            self._changed()

    def _changed(self, *_):
        self._update_sample()
        self.changed.emit()

    def style(self) -> GlyphStyle:
        return GlyphStyle(font_path=self.font_edit.text().strip() or None, ink=self.ink.value(),
                          top=self.top.rgb(), bottom=self.bottom.rgb(),
                          outline=self.outline_c.rgb() if self.outline_on.isChecked() else None,
                          outline_px=self.outline_px.value() if self.outline_on.isChecked() else 0,
                          glow=self.glow_c.rgb() if self.glow_on.isChecked() else None,
                          glow_px=self.glow_px.value() if self.glow_on.isChecked() else 0)

    def _update_sample(self):
        try:
            gl = generate_glyph_set(CHARSETS["digits"], self.style())
        except Exception as e:                                           # bad font path etc.
            self.sample.setText("Cannot render: %s" % e)
            return
        imgs = [gl[str(i)] for i in range(10)]
        W, H = sum(i.width for i in imgs), max(i.height for i in imgs)
        strip = Image.new("RGBA", (W, H), (28, 30, 36, 255))
        x = 0
        for i in imgs:
            strip.alpha_composite(i, (x, 0))
            x += i.width
        pm = QPixmap.fromImage(pil_to_qimage(strip))
        if pm.width() > 330:
            pm = pm.scaledToWidth(330, Qt.TransformationMode.SmoothTransformation)
        self.sample.setPixmap(pm)


class AddWidgetDialog(QDialog):
    """Pick a widget type and where its glyph images come from."""

    def __init__(self, project: Project, preselect: Optional[Tuple[str, str]] = None, parent=None):
        super().__init__(parent)
        self.project = project
        self.setWindowTitle("Add widget")
        self.resize(780, 640)
        root = QHBoxLayout(self)
        root.setSpacing(14)
        self.list = QListWidget()
        self.list.setFixedWidth(210)
        self.list.setIconSize(QSize(18, 18))
        root.addWidget(self.list)
        right = QVBoxLayout()
        right.setSpacing(10)
        self.title = QLabel()
        self.title.setObjectName("Title")
        self.desc = muted("")
        right.addWidget(self.title)
        right.addWidget(self.desc)

        self.src_box = QWidget()
        sv = QVBoxLayout(self.src_box)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(8)
        self.rb_gen = QRadioButton("Generate glyph images from a font")
        self.rb_reuse = QRadioButton("Reuse an existing glyph set")
        self.rb_gen.setChecked(True)
        self.reuse = QComboBox()
        for f in project.fontsets:
            self.reuse.addItem("%s  (%d images)" % (f["name"], len(project.glyphs.get(f["name"], {}))), f["name"])
        self.rb_reuse.setEnabled(bool(project.fontsets))
        self.reuse.setEnabled(False)
        self.style_editor = GlyphStyleEditor()
        sv.addWidget(self.rb_gen)
        sv.addWidget(self.style_editor)
        sv.addWidget(self.rb_reuse)
        sv.addWidget(self.reuse)
        right.addWidget(self.src_box)

        self.hand_box = QWidget()
        hv = QVBoxLayout(self.hand_box)
        hv.setContentsMargins(0, 0, 0, 0)
        hv.addWidget(muted("Three plain hands are generated (hour, minute, second). Replace them with your own "
                           "artwork later from the Properties panel; the pivot is the hub of each hand."))
        self.hand_color = ColorField("0xFFFFFFFF")
        hs = Section("Hands", True)
        hs.head.setEnabled(False)
        hs.add_row("Colour", self.hand_color)
        hv.addWidget(hs)
        right.addWidget(self.hand_box)
        self.warn = QLabel()
        self.warn.setObjectName("Muted")
        right.addWidget(self.warn)
        right.addStretch(1)
        self.bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_btn = self.bb.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_btn.setText("Add widget")
        self.ok_btn.setProperty("kind", "primary")
        self.bb.accepted.connect(self.accept)
        self.bb.rejected.connect(self.reject)
        right.addWidget(self.bb)
        root.addLayout(right, 1)

        self._populate(preselect)
        self.list.currentItemChanged.connect(lambda *_: self._on_select())
        self.rb_gen.toggled.connect(self._on_mode)
        self._on_select()

    def _populate(self, preselect):
        first = None
        for group in ("Time & Date", "Data", "Analog"):
            h = QListWidgetItem(group.upper())
            h.setFlags(Qt.ItemFlag.NoItemFlags)
            f = h.font()
            f.setBold(True)
            f.setPointSizeF(max(7.0, f.pointSizeF() - 1))
            h.setFont(f)
            self.list.addItem(h)
            for key, spec in sorted(WIDGET_SPECS.items(), key=lambda kv: kv[1]["label"]):
                if spec["group"] != group:
                    continue
                it = QListWidgetItem(icon_for(TYPE_ICONS.get(key, "glyph")), spec["label"])
                it.setData(Qt.ItemDataRole.UserRole, key)
                self.list.addItem(it)
                if first is None or key == preselect:
                    if first is None or preselect is not None:
                        first = it
        if first is not None:
            self.list.setCurrentItem(first)

    def key(self) -> Optional[Tuple[str, str]]:
        it = self.list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it is not None else None

    def _on_mode(self, *_):
        gen = self.rb_gen.isChecked()
        self.style_editor.setEnabled(gen)
        self.reuse.setEnabled(not gen and self.rb_reuse.isEnabled())

    def _on_select(self):
        key = self.key()
        if key is None:
            return
        spec = WIDGET_SPECS[key]
        self.title.setText(spec["label"])
        self.desc.setText(spec["desc"] + "   [%s/%s]" % key)
        analog = key == ("watch", "time")
        self.src_box.setVisible(not analog)
        self.hand_box.setVisible(analog)
        exists = analog and any(w.is_analog for w in self.project.items)
        self.warn.setText("This face already has an analog widget; stock faces use only one." if exists else "")
        self.ok_btn.setEnabled(not exists)
        self.rb_reuse.setChecked(False) if self.rb_gen.isChecked() else None
        self._on_mode()

    def config(self) -> dict:
        key = self.key()
        reuse = self.rb_reuse.isChecked() and self.rb_reuse.isEnabled()
        return dict(key=key, mode="reuse" if reuse else "generate", set_name=self.reuse.currentData() if reuse else None,
                    style=self.style_editor.style(), hand_color=self.hand_color.rgb())


class GlyphDialog(QDialog):
    """Regenerate the images of an existing glyph set."""

    def __init__(self, set_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Regenerate glyphs \u2013 %s" % set_name)
        self.resize(460, 520)
        v = QVBoxLayout(self)
        v.addWidget(muted("Replaces every image in the set '%s' with newly rendered ones." % set_name))
        self.editor = GlyphStyleEditor()
        v.addWidget(self.editor)
        self.fit = QCheckBox("Resize the widget box to fit the new glyphs")
        self.fit.setChecked(True)
        v.addWidget(self.fit)
        v.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        ok = bb.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("Regenerate")
        ok.setProperty("kind", "primary")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)


class ProblemsDialog(QDialog):
    """Validation results. Double-click a row to select the widget it is about."""

    def __init__(self, problems, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Project check")
        self.resize(640, 380)
        self.selected_uid = -1
        v = QVBoxLayout(self)
        n_err = sum(1 for p in problems if p[0] == "error")
        n_warn = sum(1 for p in problems if p[0] == "warning")
        v.addWidget(QLabel("<b>%d error(s), %d warning(s)</b>" % (n_err, n_warn) if problems
                           else "<b>No problems found.</b>"))
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setIconSize(QSize(16, 16))
        icons = {"error": "error", "warning": "warn", "info": "info"}
        colors = {"error": "#e5484d", "warning": "#e5a000", "info": "#3d7eff"}
        for level, text, uid in problems:
            it = QTreeWidgetItem([text])
            it.setIcon(0, make_icon(icons[level], colors[level]))
            it.setData(0, Qt.ItemDataRole.UserRole, -1 if uid is None else uid)
            self.tree.addTopLevelItem(it)
        self.tree.itemDoubleClicked.connect(self._pick)
        v.addWidget(self.tree, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        v.addWidget(bb)

    def _pick(self, item, _col=0):
        self.selected_uid = item.data(0, Qt.ItemDataRole.UserRole)
        self.accept()


# =====================================================================================
#  Panels
# =====================================================================================
class LayersPanel(QWidget):
    """Widget stack, front-most first. Eye / lock columns are editor-only flags."""

    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setIconSize(QSize(16, 16))
        self.tree.setIndentation(0)
        hd = self.tree.header()
        hd.setStretchLastSection(False)
        hd.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hd.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hd.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.tree.setColumnWidth(1, 30)
        self.tree.setColumnWidth(2, 30)
        self.tree.itemSelectionChanged.connect(self._sel_changed)
        self.tree.itemClicked.connect(self._clicked)
        v.addWidget(self.tree, 1)
        bar = QFrame()
        bar.setObjectName("RunHeader")
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 6, 8, 6)
        h.setSpacing(2)
        self._btns = []
        for name, tip, fn in (("add", "Add widget\u2026", lambda: mw.add_widget_dialog()),
                              ("copy", "Duplicate (Ctrl+D)", lambda: mw.duplicate_selected()),
                              ("trash", "Delete (Del)", lambda: mw.delete_selected()),
                              ("up", "Bring forward", lambda: mw.move_selected(+1)),
                              ("down", "Send backward", lambda: mw.move_selected(-1))):
            b = QToolButton()
            b.setToolTip(tip)
            b.setIcon(icon_for(name))
            b.clicked.connect(lambda _=False, f=fn: f())
            h.addWidget(b)
            self._btns.append((b, name))
        h.addStretch(1)
        v.addWidget(bar)
        self._busy = False

    def refresh_icons(self):
        for b, name in self._btns:
            b.setIcon(icon_for(name))
        self.rebuild()

    def rebuild(self):
        self._busy = True
        self.tree.clear()
        sel = self.mw.canvas.selected_uid
        for w in reversed(self.mw.project.items):
            it = QTreeWidgetItem([w.title, "", ""])
            it.setIcon(0, widget_icon(w))
            it.setData(0, Qt.ItemDataRole.UserRole, w.uid)
            it.setToolTip(0, "%s/%s" % w.key)
            it.setIcon(1, icon_for("eye_off" if w.hidden else "eye"))
            it.setIcon(2, icon_for("lock" if w.locked else "unlock"))
            it.setToolTip(1, "Show / hide in the editor (not saved)")
            it.setToolTip(2, "Lock against dragging (not saved)")
            self.tree.addTopLevelItem(it)
            if w.uid == sel:
                self.tree.setCurrentItem(it)
        self._busy = False

    def select(self, uid: int):
        self._busy = True
        self.tree.clearSelection()
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.data(0, Qt.ItemDataRole.UserRole) == uid:
                self.tree.setCurrentItem(it)
        self._busy = False

    def _sel_changed(self):
        if self._busy:
            return
        items = self.tree.selectedItems()
        self.mw.select(items[0].data(0, Qt.ItemDataRole.UserRole) if items else -1, from_layers=True)

    def _clicked(self, item, col):
        w = self.mw.project.widget_by_uid(item.data(0, Qt.ItemDataRole.UserRole))
        if w is None or col == 0:
            return
        if col == 1:
            w.hidden = not w.hidden
            item.setIcon(1, icon_for("eye_off" if w.hidden else "eye"))
            self.mw.refresh_view()
        else:
            w.locked = not w.locked
            item.setIcon(2, icon_for("lock" if w.locked else "unlock"))
            self.mw.canvas.update()


class AssetsPanel(QWidget):
    """Background, preview, hand images and glyph sets of the project. Double-click to replace / regenerate."""

    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIconSize(QSize(30, 30))
        self.tree.setIndentation(14)
        self.tree.itemDoubleClicked.connect(self._dbl)
        v.addWidget(self.tree, 1)
        v.addWidget(muted("Double-click an item to replace its image or regenerate its glyphs."))
        v.itemAt(1).widget().setContentsMargins(12, 6, 12, 8)

    def rebuild(self):
        self.tree.clear()
        p = self.mw.project

        def group(title):
            g = QTreeWidgetItem([title.upper()])
            f = g.font(0)
            f.setBold(True)
            f.setPointSizeF(max(7.0, f.pointSizeF() - 1))
            g.setFont(0, f)
            g.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.tree.addTopLevelItem(g)
            g.setExpanded(True)
            return g

        def leaf(parent, text, im, kind, name):
            it = QTreeWidgetItem(parent, [text])
            if im is not None:
                it.setIcon(0, QIcon(pix_from_pil(im, (30, 30))))
            it.setData(0, Qt.ItemDataRole.UserRole, (kind, name))
            return it

        g = group("Background")
        bg = p.images.get(p.bkground)
        leaf(g, "%s  \u00b7  %s" % (p.bkground, "%d\u00d7%d" % bg.size if bg else "missing"), bg, "bg", p.bkground)
        g = group("Preview")
        pv = p.images.get(p.preview_name)
        leaf(g, "%s  \u00b7  %s" % (p.preview_name, "%d\u00d7%d" % pv.size if pv else "missing"), pv, "preview", p.preview_name)
        hands = p.used_hand_images()
        if hands:
            g = group("Hand images")
            for n in hands:
                im = p.images.get(n)
                leaf(g, "%s  \u00b7  %s" % (n, "%d\u00d7%d" % im.size if im else "missing"), im, "hand", n)
        g = group("Glyph sets")
        for f in p.fontsets:
            gl = p.glyphs.get(f["name"], {})
            users = ", ".join(w.title for w in p.items if w.font == f["name"] and not w.is_analog)
            first = next(iter(gl.values()), None)
            leaf(g, "%s  \u00b7  %d images%s" % (f["name"], len(gl), "  \u00b7  " + users if users else "  \u00b7  unused"),
                 first, "set", f["name"])

    def _dbl(self, item, _column=0):
        asset = item.data(0, Qt.ItemDataRole.UserRole)
        if not asset:
            return
        kind, name = asset
        if kind == "set":
            self.mw._regenerate_glyphs(name)
        else:
            self.mw._replace_asset(kind, name)


class SimulationPanel(QWidget):
    """What the preview pretends the watch knows: date, time, weather, activity."""

    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        st = mw.state

        t = Section("Time")
        self.fmt = Segmented([(False, "12H", "12-hour clock"), (True, "24H", "24-hour clock")])
        self.fmt.changed.connect(lambda val: self._set("use24h", val))
        t.add_row("Format", self.fmt)
        self.f = {}
        for key, label, lo, hi in (("year", "Year", 2000, 2099), ("month", "Month", 1, 12), ("day", "Day", 1, 31),
                                   ("hour", "Hour", 0, 23), ("minute", "Minute", 0, 59), ("second", "Second", 0, 59)):
            self.f[key] = NumField(lo, hi, "")
            self.f[key].valueChanged.connect(lambda val, k=key: self._set(k, val))
        t.add_pair("Year", self.f["year"], "Month", self.f["month"])
        t.add_pair("Day", self.f["day"], "Weekday", QLabel())
        self.weekday = QLabel("")
        t.grid.addWidget(self.weekday, t._row - 1, 3)
        t.add_pair("Hour", self.f["hour"], "Minute", self.f["minute"])
        t.add_pair("Second", self.f["second"], "", QLabel())
        self.live = QCheckBox("Follow the system clock")
        self.live.toggled.connect(self._live_toggled)
        t.add_wide(self.live)
        v.addWidget(t)

        w = Section("Weather")
        self.temp = NumField(-60, 99, "\u00b0")
        self.temp.valueChanged.connect(lambda val: self._set("temp", val))
        self.unit = Segmented([("C", "\u00b0C", "Celsius glyph (11)"), ("F", "\u00b0F", "Fahrenheit glyph (12)")])
        self.unit.changed.connect(lambda val: self._set("temp_unit", val))
        w.add_row("Temperature", self.temp)
        w.add_row("Unit", self.unit)
        v.addWidget(w)

        a = Section("Activity")
        self.steps = NumField(0, 99999, "")
        self.cal = NumField(0, 99999, "")
        self.bat = NumField(0, 100, " %")
        self.steps.valueChanged.connect(lambda val: self._set("steps", val))
        self.cal.valueChanged.connect(lambda val: self._set("calories", val))
        self.bat.valueChanged.connect(lambda val: self._set("battery", val))
        a.add_row("Steps", self.steps)
        a.add_row("Calories", self.cal)
        a.add_row("Battery", self.bat)
        v.addWidget(a)
        v.addWidget(muted("The preview is a simulation: the watch firmware decides number formats and "
                          "leading zeros.", True))
        v.itemAt(v.count() - 1).widget().setContentsMargins(14, 12, 14, 12)
        v.addStretch(1)
        sc.setWidget(body)
        outer.addWidget(sc)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.sync()

    def sync(self):
        s = self.mw.state
        s.clamp()
        self.fmt.set_value(s.use24h)
        for k, f in self.f.items():
            f.set_quiet(getattr(s, k))
        self.weekday.setText(s.weekday_key.upper())
        self.temp.set_quiet(s.temp)
        self.unit.set_value(s.temp_unit)
        self.steps.set_quiet(s.steps)
        self.cal.set_quiet(s.calories)
        self.bat.set_quiet(s.battery)

    def _set(self, key, val):
        setattr(self.mw.state, key, val)
        self.mw.state.clamp()
        self.sync()
        self.mw.refresh_view()

    def _live_toggled(self, on: bool):
        for f in self.f.values():
            f.setEnabled(not on)
        if on:
            self._tick()
            self.timer.start(1000)
        else:
            self.timer.stop()

    def _tick(self):
        n = datetime.datetime.now()
        s = self.mw.state
        s.year, s.month, s.day, s.hour, s.minute, s.second = n.year, n.month, n.day, n.hour, n.minute, n.second
        self.sync()
        self.mw.refresh_view()
