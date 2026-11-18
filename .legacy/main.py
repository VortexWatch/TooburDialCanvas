import sys
import os
import re
import json
import math
import zipfile
import shutil
from datetime import time as dtime

from PyQt6.QtCore import (
    Qt, QRectF, QPointF, QSizeF, pyqtSignal, QTime, QTimer, QSize
)
from PyQt6.QtGui import (
    QPixmap, QImage, QPainter, QPainterPath, QPen, QBrush, QColor,
    QAction, QIcon, QFont, QTransform, QPolygonF, QAction
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QGraphicsView, QGraphicsScene,
    QGraphicsPixmapItem, QGraphicsItem, QToolBar, QDockWidget, QTreeWidget,
    QTreeWidgetItem, QLineEdit, QSpinBox, QComboBox, QCheckBox, QLabel,
    QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog, QMessageBox,
    QPlainTextEdit, QListWidget, QListWidgetItem, QSplitter, QStatusBar,
    QTimeEdit, QGroupBox, QFormLayout, QStyle, QSizePolicy, QFrame,
    QToolButton, QMenu, QInputDialog, QAbstractItemView, QMenuBar, QDialog,
    QColorDialog
)

# ---------------------------------------------------------------------------
# Preview constants
# ---------------------------------------------------------------------------

CANVAS_W = 320
CANVAS_H = 385
PREVIEW_W = 272
PREVIEW_H = 324

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_ANCHOR_X = 160
DEFAULT_ANCHOR_Y = 193
# GRID_SIZE = 10 - Unused
WIDGET_ITEMS = None

DEFAULT_PROJECT = {
    "version": 1,
    "clouddialversion": 3,
    "preview": "preview.png",
    "name": "",
    "author": "",
    "description": "IDW20",
    "deviceId": "IDW20",
    "bluetooth": False,
    "disturb": False,
    "battery": False,
    "compress": "LZ4",
    "item": [],
    "bkground": ""
}

HAND_KEYS = {
    "hour": ("hour", "hourcenterx", "hourcentery", "houranchorx", "houranchory"),
    "minute": ("minute", "mincenterx", "mincentery", "minanchorx", "minanchory"),
    "second": ("second", "seccenterx", "seccentery", "secanchorx", "secanchory"),
}

WATCH_ITEM_TEMPLATE = {
    "widget": "watch",
    "type": "time",
    "x": 0,
    "y": 0,
    "w": CANVAS_W,
    "h": CANVAS_H,
    "fgcolor": "0xFFFFFFFF",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def hand_angle_degrees(hand: str, h: int, m: int, s: int) -> float:
    """Clockwise rotation in degrees, 0 = pointing up (12 o'clock)."""
    if hand == "hour":
        return ((h % 12) + m / 60.0 + s / 3600.0) * 30.0
    if hand == "minute":
        return (m + s / 60.0) * 6.0
    if hand == "second":
        return s * 6.0
    return 0.0

def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


# ---------------------------------------------------------------------------
# Project model
# ---------------------------------------------------------------------------

class IWFProject:
    """Holds the iwf.json data dict plus the folder it lives in / will save to."""

    def __init__(self):
        self.data = json.loads(json.dumps(DEFAULT_PROJECT))
        self.folder = None  # str path once known
        self.dirty = False

    # -- watch item -----------------------------------------------------
    def get_watch_item(self, create=False):
        for it in self.data["item"]:
            if it.get("widget") == "watch" and it.get("type") == "time":
                return it
        if create:
            new_item = json.loads(json.dumps(WATCH_ITEM_TEMPLATE))
            self.data["item"].append(new_item)
            return new_item
        return None

    def has_hand(self, hand: str) -> bool:
        item = self.get_watch_item()
        if not item:
            return False
        key, *_ = HAND_KEYS[hand]
        return bool(item.get(key))

    def set_hand(self, hand: str, filename: str, centerx: float, centery: float,
                 anchorx: float = DEFAULT_ANCHOR_X, anchory: float = DEFAULT_ANCHOR_Y):
        item = self.get_watch_item(create=True)
        key, ckx, cky, akx, aky = HAND_KEYS[hand]
        item[key] = filename
        item[ckx] = round(centerx)
        item[cky] = round(centery)
        item[akx] = round(anchorx)
        item[aky] = round(anchory)
        self.dirty = True

    def remove_hand(self, hand: str):
        item = self.get_watch_item()
        if not item:
            return
        for k in HAND_KEYS[hand]:
            item.pop(k, None)
        self.dirty = True

    def hand_values(self, hand: str):
        item = self.get_watch_item()
        if not item:
            return None
        key, ckx, cky, akx, aky = HAND_KEYS[hand]
        if not item.get(key):
            return None
        return {
            "filename": item.get(key, ""),
            "centerx": item.get(ckx, 0),
            "centery": item.get(cky, 0),
            "anchorx": item.get(akx, DEFAULT_ANCHOR_X),
            "anchory": item.get(aky, DEFAULT_ANCHOR_Y),
        }

    # -- IO ---------------------------------------------------------------
    def load(self, folder: str):
        json_path = os.path.join(folder, "iwf.json")
        with open(json_path, "r", encoding="utf-8") as f:
            self.data = json.load(f)
        self.folder = folder
        self.dirty = False

    def save(self, folder: str = None):
        folder = folder or self.folder
        if not folder:
            raise ValueError("No project folder set.")
        os.makedirs(folder, exist_ok=True)
        json_path = os.path.join(folder, "iwf.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
        self.folder = folder
        self.dirty = False

    def to_json_str(self) -> str:
        return json.dumps(self.data, indent=2, ensure_ascii=False)

    def load_from_json_str(self, text: str):
        self.data = json.loads(text)
        self.dirty = True


# ---------------------------------------------------------------------------
# Canvas graphics items
# ---------------------------------------------------------------------------

class HandGraphicsItem(QGraphicsPixmapItem):
    """A rotatable clock-hand pixmap."""

    def __init__(self, hand_name: str, main_window):
        super().__init__()
        self.hand_name = hand_name
        self.main_window = main_window
        self.centerx = 0.0
        self.centery = 0.0
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False) # Disabled to prevent weird preview
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False) # Disabled to prevent weird preview
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue({"hour": 10, "minute": 11, "second": 12}.get(hand_name, 5))
        self._suppress_notify = False
        
        # Set the hands smooth
        self.setTransformationMode(Qt.TransformationMode.SmoothTransformation)

    def set_pivot(self, centerx, centery):
        self.centerx = centerx
        self.centery = centery
        self.setTransformOriginPoint(QPointF(centerx, centery))

    def place_at_anchor(self, anchorx, anchory):
        self._suppress_notify = True
        self.setPos(anchorx - self.centerx, anchory - self.centery)
        self._suppress_notify = False

    def current_anchor(self):
        return (self.pos().x() + self.centerx, self.pos().y() + self.centery)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.scene() is not None:
            new_pos = value
            anchor_x = new_pos.x() + self.centerx
            anchor_y = new_pos.y() + self.centery
            return new_pos
        return super().itemChange(change, value)


class CanvasScene(QGraphicsScene):
    """Scene with a rounded-corner clip mask and checkerboard"""

    def __init__(self, w, h):
        super().__init__(0, 0, w, h)
        self.w = w
        self.h = h
        self.setBackgroundBrush(QBrush(QColor("#1b1d23")))

    def drawBackground(self, painter: QPainter, rect: QRectF):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # checkerboard behind the rounded canvas (transparency indicator)
        painter.fillRect(rect, QColor("#1b1d23"))
        tile = 12
        light = QColor("#2a2d36")
        dark = QColor("#24262e")
        x0 = int(rect.left()) - (int(rect.left()) % tile)
        y0 = int(rect.top()) - (int(rect.top()) % tile)
        y = y0
        row = 0
        while y < rect.bottom():
            x = x0
            col = row
            while x < rect.right():
                painter.fillRect(QRectF(x, y, tile, tile),
                                  light if col % 2 == 0 else dark)
                x += tile
                col += 1
            y += tile
            row += 1
        painter.setClipping(False)

        # canvas border + rounded-corner frame
        painter.setPen(QPen(QColor("#000000"), 1.4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.restore()

    def render_clean(self) -> QImage:
        """Render the scene content at native canvas dimensions."""
        img = QImage(
            self.w,
            self.h,
            QImage.Format.Format_ARGB32_Premultiplied
        )
        img.fill(Qt.GlobalColor.transparent)

        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        self.render(
            painter,
            QRectF(0, 0, self.w, self.h),
            QRectF(0, 0, self.w, self.h)
        )

        painter.end()
        return img


class CanvasView(QGraphicsView):
    """Zoomable / pannable view hosting the CanvasScene."""

    zoomChanged = pyqtSignal(float)

    def __init__(self, scene):
        super().__init__(scene)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setBackgroundBrush(QBrush(QColor("#15161b")))
        self._zoom = 1.0
        
        # Set the view smooth
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)

    def set_zoom(self, factor: float):
        factor = max(0.25, min(6.0, factor))
        self._zoom = factor
        t = QTransform()
        t.scale(factor, factor)
        self.setTransform(t)
        self.zoomChanged.emit(self._zoom)

    def zoom_in(self):
        self.set_zoom(self._zoom * 1.2)

    def zoom_out(self):
        self.set_zoom(self._zoom / 1.2)

    def reset_zoom(self):
        self.set_zoom(1.0)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            self.zoom_in() if delta > 0 else self.zoom_out()
        else:
            super().wheelEvent(event)

# ---------------------------------------------------------------------------
# Properties panel (Qt-Designer style property tree)
# ---------------------------------------------------------------------------

class PropertiesPanel(QWidget):
    """Live-editable property tree for project + watch item + hands."""

    valueChanged = pyqtSignal()

    def __init__(self, main_window):
        super().__init__()
        self.mw = main_window
        self._building = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Property", "Value"])
        self.tree.setColumnWidth(0, 150)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        layout.addWidget(self.tree)

        self.build_tree()

    # -- construction -----------------------------------------------------
    def _row(self, parent, label, widget):
        item = QTreeWidgetItem(parent, [label, ""])
        self.tree.setItemWidget(item, 1, widget)
        return item

    def build_tree(self):
        self._building = True
        self.tree.clear()
        p = self.mw.project.data

        # --- Project group ---
        proj_root = QTreeWidgetItem(self.tree, ["Project"])
        proj_root.setFirstColumnSpanned(True)
        
        self.preview_edit = QLineEdit(p.get("preview", "preview.png"))
        self.preview_edit.editingFinished.connect(
            lambda: self._set_field("preview", (self.preview_edit.text() or "preview.png")))
        self._row(proj_root, "preview", self.preview_edit)

        self.name_edit = QLineEdit(p.get("name", ""))
        self.name_edit.textEdited.connect(lambda v: self._set_field("name", v))
        self._row(proj_root, "name", self.name_edit)

        self.author_edit = QLineEdit(p.get("author", ""))
        self.author_edit.textEdited.connect(lambda v: self._set_field("author", v))
        self._row(proj_root, "author", self.author_edit)

        self.desc_edit = QLineEdit(p.get("description", "KS2"))
        self.desc_edit.textEdited.connect(lambda v: self._set_field("description", v))
        self._row(proj_root, "description", self.desc_edit)
        self.desc_edit.setReadOnly(True)

        self.device_edit = QLineEdit(p.get("deviceId", "KS2"))
        self.device_edit.textEdited.connect(lambda v: self._set_field("deviceId", v))
        self._row(proj_root, "deviceId", self.device_edit)
        self.device_edit.setReadOnly(True)

        self.compress_combo = QComboBox()
        self.compress_combo.addItems(["LZ4", "FASTLZ"])
        self.compress_combo.setCurrentText(p.get("compress", "LZ4"))
        self.compress_combo.currentTextChanged.connect(lambda v: self._set_field("compress", v))
        self._row(proj_root, "compress", self.compress_combo)

        for flag in ("bluetooth", "disturb", "battery"):
            cb = QCheckBox()
            cb.setChecked(bool(p.get(flag, False)))
            cb.toggled.connect(lambda v, f=flag: self._set_field(f, bool(v)))
            self._row(proj_root, flag, cb)

        self.bkground_edit = QLineEdit(p.get("bkground", ""))
        self.bkground_edit.setReadOnly(True)
        self._row(proj_root, "bkground", self.bkground_edit)

        # --- Watch item group ---
        watch_root = QTreeWidgetItem(self.tree, ["Watch Widget"])
        watch_root.setFirstColumnSpanned(True)
        item = self.mw.project.get_watch_item()
        if item is None:
            note = QTreeWidgetItem(watch_root, ["(no hands added yet)", ""])
            note.setDisabled(True)
        else:
            for fld in ("x", "y", "w", "h"):
                sb = QSpinBox()
                sb.setRange(0, 4000)
                sb.setValue(int(item.get(fld, 0)))
                sb.valueChanged.connect(lambda v, f=fld: self._set_item_field(f, v))
                self._row(watch_root, fld, sb)
            fg = QLineEdit(item.get("fgcolor", "0xFFFFFFFF"))
            fg.editingFinished.connect(lambda: self._set_item_field("fgcolor", fg.text()))
            fg.setReadOnly(True) # Added to prevent editing, since fgcolor is not meant to be changed directly in this context
            self._row(watch_root, "fgcolor", fg)

            # --- per-hand subtrees ---
            for hand in ("hour", "minute", "second"):
                vals = self.mw.project.hand_values(hand)
                if not vals:
                    continue
                hand_root = QTreeWidgetItem(watch_root, [hand.capitalize() + " Hand"])
                hand_root.setFirstColumnSpanned(True)

                fname = QLineEdit(vals["filename"])
                fname.setReadOnly(True)
                self._row(hand_root, "image", fname)

                for coord, key in (("centerx", "centerx"), ("centery", "centery"),
                                    ("anchorx", "anchorx"), ("anchory", "anchory")):
                    sb = QSpinBox()
                    sb.setRange(-2000, 4000)
                    sb.setValue(int(vals[key]))
                    sb.valueChanged.connect(
                        lambda v, h=hand, k=key: self.mw.on_property_hand_edit(h, k, v))
                    self._row(hand_root, coord, sb)

        self.tree.expandAll()
        self._building = False

    # -- edits --------------------------------------------------------------
    def _set_field(self, field, value):
        if self._building:
            return
        self.mw.project.data[field] = value
        self.mw.project.dirty = True
        self.mw.refresh_raw_json()
        self.mw.set_status(f"Updated '{field}'")

    def _set_item_field(self, field, value):
        if self._building:
            return
        item = self.mw.project.get_watch_item(create=True)
        item[field] = value
        self.mw.project.dirty = True
        self.mw.refresh_raw_json()

    def refresh(self):
        self.build_tree()


# ---------------------------------------------------------------------------
# Assets panel
# ---------------------------------------------------------------------------

class AssetsPanel(QListWidget):
    """Thumbnail listing of PNG assets in the current project folder."""

    def __init__(self, main_window):
        super().__init__()
        self.mw = main_window
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setIconSize(self.iconSize())
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setSpacing(8)
        self.setMovement(QListWidget.Movement.Static)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

    def refresh(self):
        self.clear()
        from PyQt6.QtCore import QSize
        self.setIconSize(QSize(64, 64))
        folder = self.mw.project.folder
        if not folder or not os.path.isdir(folder):
            return
        for fname in sorted(os.listdir(folder)):
            if fname.lower().endswith(".png"):
                path = os.path.join(folder, fname)
                pix = QPixmap(path)
                icon = QIcon(pix) if not pix.isNull() else QIcon()
                item = QListWidgetItem(icon, fname)
                item.setToolTip(fname)
                self.addItem(item)


# ---------------------------------------------------------------------------
# Raw JSON panel
# ---------------------------------------------------------------------------

class RawJsonPanel(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.mw = main_window
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        self.editor = QPlainTextEdit()
        self.editor.setFont(QFont("Consolas", 10))
        layout.addWidget(self.editor)

        btn_row = QHBoxLayout()
        self.apply_btn = QPushButton("Apply JSON \u2192 Project")
        self.apply_btn.clicked.connect(self.apply_json)
        self.revert_btn = QPushButton("Revert to Project")
        self.revert_btn.clicked.connect(self.refresh)
        btn_row.addWidget(self.apply_btn)
        btn_row.addWidget(self.revert_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

    def refresh(self):
        self.editor.setPlainText(self.mw.project.to_json_str())

    def apply_json(self):
        text = self.editor.toPlainText()
        try:
            self.mw.project.load_from_json_str(text)
        except json.JSONDecodeError as e:
            QMessageBox.critical(self, "Invalid JSON", f"Could not parse iwf.json:\n{e}")
            return
        self.mw.rebuild_canvas_from_project()
        self.mw.properties_panel.refresh()
        self.mw.set_status("Applied raw iwf.json to project")

# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TooburDialCanvas")
        self.resize(1440, 940)

        self.project = IWFProject()
        self.preview_h, self.preview_m, self.preview_s = 10, 10, 30

        self.hand_items = {}
        self.ring_items = []
        self.progressbar_items = []
        self.histogram_items = []
        self.bkground_item = None

        self.scene = CanvasScene(CANVAS_W, CANVAS_H)
        self.view = CanvasView(self.scene)

        self._build_toolbar()
        self._build_docks()
        self._build_statusbar()

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.addWidget(self.view)
        self.setCentralWidget(central)

        self.rebuild_canvas_from_project()
        self.set_status("Ready.")

    # ---------------------------------------------------------------- UI --
    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setIconSize(self.style().pixelMetric(QStyle.PixelMetric.PM_ToolBarIconSize) * QSizeF(1, 1).toSize())
        self.addToolBar(tb)

        def act(text, slot, tip=None, checkable=False):
            a = QAction(text, self)
            a.triggered.connect(slot)
            if tip:
                a.setToolTip(tip)
            a.setCheckable(checkable)
            tb.addAction(a)
            return a

        act("Open Folder", self.open_folder, "Open a folder containing iwf.json")
        act("Save", self.save_project, "Save iwf.json to the project folder")
        act("Save As", self.save_project_as, "Choose a folder and save")
        tb.addSeparator()
        act("Upload Background", self.upload_background, "Upload background image")
        act("Add Hour", lambda: self.add_hand("hour"), "Add hour hand image")
        act("Add Minute", lambda: self.add_hand("minute"), "Add minute hand image")
        act("Add Second", lambda: self.add_hand("second"), "Add second hand image")
        act("Auto-Center Hands", self.auto_center_all_hands, "Recenter all hand pivots to canvas center")
        tb.addSeparator()
        act("Package .zip", self.package_zip, "Package the project folder into a .zip for upload")
        tb.addSeparator()
        act("Save Preview", self.save_preview_image, "Render + save preview.png")
        act("Save App Image", self.save_app_image, "Render + save app.png")
        tb.addSeparator()

        act("-", self.view.zoom_out, "Zoom out")
        act("\u2295 Reset", self.view.reset_zoom, "Reset zoom")
        act("+", self.view.zoom_in, "Zoom in")
        tb.addSeparator()

        tb.addWidget(QLabel("  Preview time: "))
        self.time_edit = QTimeEdit(QTime(self.preview_h, self.preview_m, self.preview_s))
        self.time_edit.setDisplayFormat("HH:mm:ss")
        self.time_edit.timeChanged.connect(self.on_preview_time_changed)
        tb.addWidget(self.time_edit)

        self.view.zoomChanged.connect(lambda z: self.set_status(f"Zoom: {z*100:.0f}%", transient=True))

    def _build_docks(self):
        # Properties dock
        self.properties_panel = PropertiesPanel(self)
        prop_dock = QDockWidget("Properties", self)
        prop_dock.setWidget(self.properties_panel)
        prop_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable |
                               QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, prop_dock)

        # Assets dock
        self.assets_panel = AssetsPanel(self)
        assets_dock = QDockWidget("Assets", self)
        assets_dock.setWidget(self.assets_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, assets_dock)
        self.tabifyDockWidget(prop_dock, assets_dock)
        prop_dock.raise_()

        # Raw JSON dock
        self.raw_json_panel = RawJsonPanel(self)
        raw_dock = QDockWidget("Raw iwf.json", self)
        raw_dock.setWidget(self.raw_json_panel)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, raw_dock)
        raw_dock.resize(raw_dock.width(), 220)

    def _build_statusbar(self):
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self._status_label = QLabel("")
        self.status.addWidget(self._status_label, 1)

    def set_status(self, text, transient=False):
        self._status_label.setText(text)
        if transient:
            QTimer.singleShot(2000, lambda: self._status_label.setText(""))
            
    def package_zip(self):
        # Package the project folder into a .zip without the parent folder itself
        if not self.ensure_project_folder():
            return
        # Create .zip package in the same folder as the project folder via project name in iwf.json
        if not self.project.data.get("name"):
            QMessageBox.warning(self, "No Name", "Please set a project name before creating the .zip package.")
            return
        else:
            zip_name = f"{self.project.data['name']}.zip"
            # Create the zip file in the same directory as the project folder
            zip_path = os.path.join(os.path.dirname(self.project.folder), zip_name)
            # Create the zip file
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(self.project.folder):
                    for file in files:
                        file_path = os.path.join(root, file)
                        # Add file to zip with relative path to the project folder
                        arcname = os.path.relpath(file_path, self.project.folder)
                        zipf.write(file_path, arcname)
            # Notify the user that the zip package was created successfully
            self.set_status(f"Packaged watch face into .zip: {zip_path}", transient=True)
            
            
    def save_app_image(self):
        if not self.ensure_project_folder():
            return
    
        img = self.scene.render_clean()
        corner_radius = 77
    
        # 1. Create a blank transparent destination image for the rounded version
        rounded_img = QImage(img.size(), QImage.Format.Format_ARGB32_Premultiplied)
        rounded_img.fill(Qt.GlobalColor.transparent)
    
        # 2. Set up the painter to draw onto the rounded image
        painter = QPainter(rounded_img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    
        # 3. Create the clipping path for the rounded corners
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, img.width(), img.height()), corner_radius, corner_radius)
        painter.setClipPath(path)
    
        # 4. Draw the original clean image into the clipped area
        painter.drawImage(0, 0, img)
        painter.end()  # Fixed the missing ()
    
        # 5. Check for valid name first, then define the actual file path string
        project_name = self.properties_panel.name_edit.text().strip()
        
        if not project_name:
            QMessageBox.warning(self, "No Name", "Please set a project name before saving app.png.")
            return

        import os
        # Pass the values positionally, and add the extension
        file_name = f"{project_name}.png" 
        file_path = os.path.join(self.project.folder, file_name)
        
        if not rounded_img.save(file_path, "PNG"):
            QMessageBox.critical(self, "Save failed", f"Could not save to {file_path}")
            return
    
        self.set_status(f"Saved {file_name} to {self.project.folder}", transient=True)
 
    # -------------------------------------------------------- canvas sync --
    def rebuild_canvas_from_project(self):
        self.scene.clear()
        self.hand_items = {}
        self.ring_items = []
        self.bkground_item = None

        item = self.project.get_watch_item()
        if item:
            self.scene.data_w = item.get("w", CANVAS_W)
            self.scene.data_h = item.get("h", CANVAS_H)

        # background
        bkg_name = self.project.data.get("bkground", "")
        if bkg_name and self.project.folder:
            path = os.path.join(self.project.folder, bkg_name)
            if os.path.isfile(path):
                pix = QPixmap(path)
                if not pix.isNull():
                    bkg_item = QGraphicsPixmapItem(pix)
                    bkg_item.setZValue(0)
                    self.scene.addItem(bkg_item)
                    self.bkground_item = bkg_item
                    # Set the background item to be smooth
                    bkg_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)

        # hands
        for hand in ("hour", "minute", "second"):
            vals = self.project.hand_values(hand)
            if not vals:
                continue
            path = os.path.join(self.project.folder, vals["filename"]) if self.project.folder else None
            pix = QPixmap(path) if path and os.path.isfile(path) else QPixmap()
            hi = HandGraphicsItem(hand, self)
            if not pix.isNull():
                hi.setPixmap(pix)
            hi.set_pivot(vals["centerx"], vals["centery"])
            hi.place_at_anchor(vals["anchorx"], vals["anchory"])
            self.scene.addItem(hi)
            self.hand_items[hand] = hi

        self.apply_preview_rotation()
        self.assets_panel.refresh()
        self.refresh_raw_json()

    def refresh_raw_json(self):
        self.raw_json_panel.refresh()

    def apply_preview_rotation(self):
        for hand, hi in self.hand_items.items():
            angle = hand_angle_degrees(hand, self.preview_h, self.preview_m, self.preview_s)
            hi.setRotation(angle)

    # ------------------------------------------------------------- events --
    def on_preview_time_changed(self, qtime: QTime):
        self.preview_h = qtime.hour()
        self.preview_m = qtime.minute()
        self.preview_s = qtime.second()
        self.apply_preview_rotation()

    def on_property_hand_edit(self, hand, key, value):
        item = self.project.get_watch_item(create=True)
        _, ckx, cky, akx, aky = HAND_KEYS[hand]
        mapping = {"centerx": ckx, "centery": cky, "anchorx": akx, "anchory": aky}
        item[mapping[key]] = value
        self.project.dirty = True
        hi = self.hand_items.get(hand)
        if hi:
            vals = self.project.hand_values(hand)
            hi.set_pivot(vals["centerx"], vals["centery"])
            hi.place_at_anchor(vals["anchorx"], vals["anchory"])
            self.apply_preview_rotation()
        self.refresh_raw_json()

    # ------------------------------------------------------------- folder --
    def ensure_project_folder(self) -> bool:
        if self.project.folder:
            return True
        folder = QFileDialog.getExistingDirectory(self, "Choose / create a project folder")
        if not folder:
            return False
        os.makedirs(folder, exist_ok=True)
        self.project.folder = folder
        return True

    def open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Open project folder (must contain iwf.json)")
        if not folder:
            return
        json_path = os.path.join(folder, "iwf.json")
        if not os.path.isfile(json_path):
            QMessageBox.warning(self, "No iwf.json found",
                                 "The selected folder does not contain an iwf.json file.")
            return
        try:
            self.project.load(folder)
        except Exception as e:
            QMessageBox.critical(self, "Failed to load", str(e))
            return
        self.rebuild_canvas_from_project()
        self.properties_panel.refresh()
        self.set_status(f"Loaded project from {folder}")

    def save_project(self):
        if not self.ensure_project_folder():
            return
        try:
            self.project.save()
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))
            return
        self.refresh_raw_json()
        self.set_status(f"Saved iwf.json to {self.project.folder}", transient=True)

    def save_project_as(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose / create a project folder")
        if not folder:
            return
        os.makedirs(folder, exist_ok=True)
        # migrate any already-referenced assets from the old folder if needed
        old_folder = self.project.folder
        self.project.folder = folder
        if old_folder and old_folder != folder and os.path.isdir(old_folder):
            for fname in self._referenced_filenames():
                src = os.path.join(old_folder, fname)
                dst = os.path.join(folder, fname)
                if os.path.isfile(src) and not os.path.isfile(dst):
                    shutil.copy2(src, dst)
        self.project.save(folder)
        self.rebuild_canvas_from_project()
        self.set_status(f"Saved project to {folder}")

    def _referenced_filenames(self):
        names = []
        if self.project.data.get("bkground"):
            names.append(self.project.data["bkground"])
        item = self.project.get_watch_item()
        if item:
            for hand in ("hour", "minute", "second"):
                key = HAND_KEYS[hand][0]
                if item.get(key):
                    names.append(item[key])
        return names

    # -------------------------------------------------------------- assets --
    def _import_png(self, title) -> str:
        """Prompts for a PNG, copies it into the project folder,
        returns the new filename or '' if cancelled."""
        path, _ = QFileDialog.getOpenFileName(self, title, "", "PNG Images (*.png)")
        if not path:
            return ""
        if not path.lower().endswith(".png"):
            QMessageBox.warning(self, "Unsupported file", "Only PNG images are supported.")
            return ""
        if not self.ensure_project_folder():
            return ""
        base = os.path.basename(path)
        new_name = (base)
        dst = os.path.join(self.project.folder, new_name)
        if os.path.abspath(path) != os.path.abspath(dst):
            shutil.copy2(path, dst)
        return new_name

    def upload_background(self):
        new_name = self._import_png("Choose background image")
        if not new_name:
            return
        self.project.data["bkground"] = new_name
        self.project.dirty = True
        self.rebuild_canvas_from_project()
        self.properties_panel.refresh()
        self.set_status(f"Background set to {new_name}")

    def add_hand(self, hand: str):
        if self.project.has_hand(hand):
            resp = QMessageBox.question(
                self, "Replace hand?",
                f"A {hand} hand image is already set. Replace it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if resp != QMessageBox.StandardButton.Yes:
                return
        new_name = self._import_png(f"Choose {hand} hand image")
        if not new_name:
            return
        img_path = os.path.join(self.project.folder, new_name)
        img = QImage(img_path)
        w = img.width() or 1
        h = img.height() or 1
        centerx, centery = w / 2.0, h / 2.0
        self.project.set_hand(hand, new_name, centerx, centery,
                               DEFAULT_ANCHOR_X, DEFAULT_ANCHOR_Y)
        self.rebuild_canvas_from_project()
        self.properties_panel.refresh()
        self.set_status(f"Added {hand} hand: {new_name} (auto-centered)")

    def auto_center_all_hands(self):
        if not self.project.folder:
            self.set_status("No project folder yet.", transient=True)
            return
        changed = 0
        for hand in ("hour", "minute", "second"):
            vals = self.project.hand_values(hand)
            if not vals:
                continue
            img_path = os.path.join(self.project.folder, vals["filename"])
            if not os.path.isfile(img_path):
                continue
            img = QImage(img_path)
            w = img.width() or 1
            h = img.height() or 1
            self.project.set_hand(hand, vals["filename"], w / 2.0, h / 2.0,
                                   DEFAULT_ANCHOR_X, DEFAULT_ANCHOR_Y)
            changed += 1
        self.rebuild_canvas_from_project()
        self.properties_panel.refresh()
        self.set_status(f"Auto-centered {changed} hand(s) to canvas center "
                         f"({DEFAULT_ANCHOR_X}, {DEFAULT_ANCHOR_Y})", transient=True)

    # ------------------------------------------------------------- preview --
    def save_preview_image(self):
        if not self.ensure_project_folder():
            return
    
        # 1. Get raw watch face rendering (320x385)
        raw_canvas = self.scene.render_clean()
    
        # Step 1: Render the scene at original size
        original_image = QImage(320, 385, QImage.Format.Format_ARGB32)
        original_image.fill(Qt.GlobalColor.transparent)

        painter = QPainter(original_image)
        painter.drawImage(0, 0, raw_canvas)
        painter.end()

        # Step 2: Compute scaling using floating-point math
        width_ratio = PREVIEW_W / CANVAS_W    # 272.0 / 320.0 = 0.85
        height_ratio = PREVIEW_H / CANVAS_H  # 324.0 / 385.0 = 0.8415
        max_scale = min(width_ratio, height_ratio)

        # Set width to 256 and height 308
        width_scale = 256
        height_scale = 308
        
        # Set positions and define them
        final_width = width_scale
        final_height = height_scale
        
        # Calculate offsets to center the scaled image on the final canvas
        x_offset = (PREVIEW_W - final_width) // 2
        y_offset = (PREVIEW_H - final_height) // 2

        # Scale canvas smoothly
        scaled_image = original_image.scaled(
            final_width, 
            final_height,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

        # Step 3: Create final 272x324 canvas with black background
        final_image = QImage(PREVIEW_W, PREVIEW_H, QImage.Format.Format_ARGB32)
        final_image.fill(Qt.GlobalColor.black)

        # Place the scaled image at 160, 193 - The center of the scaled image should align with the center of the final image
        x_offset = (PREVIEW_W - final_width) // 2
        y_offset = (PREVIEW_H - final_height) // 2
            
        painter = QPainter(final_image)
        painter.drawImage(x_offset, y_offset, scaled_image)

        # Step 4: Overlay frame/border
        border_image_path = os.path.join(os.path.dirname(__file__), "840.png")
        if os.path.isfile(border_image_path):
            border_image = QImage(border_image_path)
            if not border_image.isNull():
                # Draw as is
                painter.drawImage(0, 0, border_image)
        painter.end()
            
        out_img = final_image
    
        # Step 5: Save preview image
        rgb_img = out_img.convertToFormat(QImage.Format.Format_RGB888)
        preview_name = (self.project.data.get("preview") or "preview.png")
        self.project.data["preview"] = preview_name
        dst = os.path.join(self.project.folder, preview_name)
        rgb_img.save(dst, "PNG")
    
        self.properties_panel.refresh()
        self.refresh_raw_json()
        self.set_status(f"Saved preview image: {preview_name} ({PREVIEW_W}x{PREVIEW_H})")


# ---------------------------------------------------------------------------
# Stylesheet (professional dark ODM-tool theme)
# ---------------------------------------------------------------------------

STYLESHEET = """
QMainWindow, QWidget {
    background-color: #202228;
    color: #d7d9e0;
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 12.5px;
}
QToolBar {
    background-color: #26282f;
    border-bottom: 1px solid #34363f;
    padding: 4px;
    spacing: 4px;
}
QToolBar QToolButton {
    background: transparent;
    border-radius: 4px;
    padding: 5px 8px;
    color: #d7d9e0;
}
QToolBar QToolButton:hover {
    background-color: #34363f;
}
QToolBar QToolButton:checked {
    background-color: #3a5fc4;
    color: white;
}
QStatusBar {
    background-color: #26282f;
    border-top: 1px solid #34363f;
    color: #9aa0ad;
}
QDockWidget {
    color: #d7d9e0;
    titlebar-close-icon: none;
}
QDockWidget::title {
    background-color: #26282f;
    padding: 6px 8px;
    border-bottom: 1px solid #34363f;
    font-weight: 600;
}
QTreeWidget, QListWidget, QPlainTextEdit {
    background-color: #1c1e24;
    alternate-background-color: #212329;
    border: 1px solid #34363f;
    border-radius: 4px;
    selection-background-color: #3a5fc4;
    selection-color: white;
    outline: none;
}
QTreeWidget::item {
    height: 24px;
}
QHeaderView::section {
    background-color: #26282f;
    color: #9aa0ad;
    padding: 4px;
    border: none;
    border-bottom: 1px solid #34363f;
}
QLineEdit, QSpinBox, QComboBox, QTimeEdit {
    background-color: #26282f;
    border: 1px solid #3a3d47;
    border-radius: 3px;
    padding: 2px 6px;
    color: #e6e8ee;
    min-height: 20px;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QTimeEdit:focus {
    border: 1px solid #4c8bf5;
}
QLineEdit:read-only {
    color: #8b90a0;
    background-color: #232530;
}
QComboBox::drop-down { border: none; width: 18px; }
QCheckBox { spacing: 6px; }
QCheckBox::indicator {
    width: 15px; height: 15px;
    border: 1px solid #4a4d59;
    border-radius: 3px;
    background: #26282f;
}
QCheckBox::indicator:checked {
    background: #4c8bf5;
    border-color: #4c8bf5;
}
QPushButton {
    background-color: #34363f;
    border: 1px solid #40424c;
    border-radius: 4px;
    padding: 5px 12px;
}
QPushButton:hover { background-color: #3d3f4a; }
QPushButton:pressed { background-color: #2c2e36; }
QScrollBar:vertical {
    background: #1c1e24; width: 12px; margin: 0;
}
QScrollBar::handle:vertical {
    background: #3a3d47; border-radius: 5px; min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: #4a4d59; }
QScrollBar:horizontal {
    background: #1c1e24; height: 12px; margin: 0;
}
QScrollBar::handle:horizontal {
    background: #3a3d47; border-radius: 5px; min-width: 24px;
}
QSplitter::handle { background-color: #34363f; }
QMenu {
    background-color: #26282f;
    border: 1px solid #34363f;
}
QMenu::item:selected { background-color: #3a5fc4; }
QToolTip {
    background-color: #2c2e36;
    color: #e6e8ee;
    border: 1px solid #40424c;
    padding: 4px;
}
"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
