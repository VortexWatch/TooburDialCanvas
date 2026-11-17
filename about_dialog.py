# -*- coding: utf-8 -*-
"""about_dialog.py -- the About box of IDW20 Face Studio."""
from __future__ import annotations

import platform
import sys

from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR, QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QTabWidget,
                             QVBoxLayout, QWidget)

from iwf_compiler import APP_NAME, APP_VERSION

APP_AUTHOR = "VortexWatch Studio"

FORMAT_NOTES = """\
.iwf container
  "iwf\\0", u16 version (1), u16 entry count, then 40-byte records
  (32-byte NUL padded name, u32 offset, u32 size), then the data. Little-endian.

RAW image
  "RAW\\0", u16 width, u16 height, 0x85, flag (0x66 = alpha plane), 2 padding bytes,
  u32 size of the colour plane, RGB565 BIG-endian pixels, optional 4-bit alpha plane
  (first pixel of each pair in the high nibble).
"""


class _Logo(QWidget):
    def __init__(self, size: int = 76, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self.width()
        grad = QLinearGradient(0, 0, s, s)
        grad.setColorAt(0, QColor("#4d8dff"))
        grad.setColorAt(1, QColor("#7c5cff"))
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, s, s), s * 0.24, s * 0.24)
        p.fillPath(path, grad)
        p.setPen(QPen(QColor("#ffffff"), s * 0.055, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        face = QPainterPath()
        face.addRoundedRect(QRectF(s * 0.27, s * 0.18, s * 0.46, s * 0.58), s * 0.12, s * 0.12)
        p.drawPath(face)
        c = QPointF(s * 0.5, s * 0.47)
        p.drawLine(c, QPointF(c.x(), s * 0.31))
        p.drawLine(c, QPointF(s * 0.62, s * 0.55))
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(c, s * 0.025, s * 0.025)
        p.end()


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About %s" % APP_NAME)
        self.setMinimumSize(520, 470)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 16)
        root.setSpacing(14)

        head = QHBoxLayout()
        head.setSpacing(16)
        head.addWidget(_Logo())
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(APP_NAME)
        t.setObjectName("Title")
        f = QFont(t.font())
        f.setPointSizeF(f.pointSizeF() + 6)
        f.setBold(True)
        t.setFont(f)
        v = QLabel("Version %s  \u00b7  for the TOOBUR IDW20 smartwatch (320\u00d7385)" % APP_VERSION)
        v.setObjectName("Muted")
        d = QLabel("A visual editor for IDO / VeryFit watch faces: arrange widgets on a canvas, preview the "
                   "result live and compile a binary .iwf.")
        d.setWordWrap(True)
        col.addWidget(t)
        col.addWidget(v)
        col.addSpacing(6)
        col.addWidget(d)
        head.addLayout(col, 1)
        root.addLayout(head)

        tabs = QTabWidget()
        info = QWidget()
        il = QVBoxLayout(info)
        il.setContentsMargins(4, 12, 4, 4)
        il.setSpacing(6)
        rows = [("Author", APP_AUTHOR), ("Qt", "%s (PyQt %s)" % (QT_VERSION_STR, PYQT_VERSION_STR)),
                ("Python", "%s on %s" % (platform.python_version(), platform.system())), ("Pillow", _ver("PIL")),
                ("NumPy", _ver("numpy")), ("License", "GPL-3.0")]
        for k, val in rows:
            r = QHBoxLayout()
            a = QLabel(k)
            a.setObjectName("Muted")
            a.setFixedWidth(80)
            b = QLabel(val)
            b.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            r.addWidget(a)
            r.addWidget(b, 1)
            il.addLayout(r)
        il.addSpacing(8)
        note = QLabel("Not affiliated with Shenzhen DO Intelligent Technology Co., Ltd.")
        note.setWordWrap(True)
        note.setObjectName("Muted")
        il.addWidget(note)
        il.addStretch(1)
        tabs.addTab(info, "About")

        fmt = QPlainTextEdit(FORMAT_NOTES)
        fmt.setReadOnly(True)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSizeF(9)
        fmt.setFont(mono)
        fmt.setFrameShape(QFrame.Shape.NoFrame)
        tabs.addTab(fmt, "Format notes")
        root.addWidget(tabs, 1)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        root.addWidget(bb)


def _ver(mod: str) -> str:
    try:
        m = __import__(mod)
        return str(getattr(m, "__version__", getattr(m, "VERSION", "?")))
    except Exception:
        return "not installed"
