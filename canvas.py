from __future__ import annotations

import math
from typing import List, Optional, Tuple

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PyQt6.QtWidgets import QSizePolicy, QWidget

from iwf_compiler import HAND_DEFS, SCREEN_H, SCREEN_W, Project, SimState, Widget, hand_angle

CANVAS_THEMES = {
    "light": dict(bg="#d9dadd", dot="#b9bbc0", accent="#3d7eff", chip_fg="#ffffff", frame="#7d8089",
                  guide="#ff4d8d", bounds="#5b6068", handle="#ffffff", shadow=(0, 0, 0, 45)),
    "dark": dict(bg="#26282d", dot="#3b3e46", accent="#5b95ff", chip_fg="#ffffff", frame="#6f7380",
                 guide="#ff6aa2", bounds="#9aa0ad", handle="#ffffff", shadow=(0, 0, 0, 110)),
}


def pil_to_qimage(im) -> QImage:
    """PIL RGBA -> QImage (deep copy, safe after the PIL image is gone)."""
    im = im.convert("RGBA")
    w, h = im.size
    data = im.tobytes("raw", "RGBA")
    return QImage(data, w, h, 4 * w, QImage.Format.Format_RGBA8888).copy()


def hand_quad(project: Project, w: Widget, kind: str, pre: str, st: SimState) -> Optional[List[Tuple[float, float]]]:
    """Corners (design px) of a hand image after rotation, or None when the image is missing."""
    im = project.images.get(w.data.get(kind, ""))
    if im is None:
        return None
    px, py = w.geti(pre + "centerx"), w.geti(pre + "centery")
    ax, ay = w.geti(pre + "anchorx", SCREEN_W // 2), w.geti(pre + "anchory", SCREEN_H // 2)
    th = math.radians(hand_angle(kind, st))
    c, s = math.cos(th), math.sin(th)
    out = []
    for cx, cy in ((0, 0), (im.width, 0), (im.width, im.height), (0, im.height)):
        rx, ry = cx - px, cy - py
        out.append((ax + rx * c - ry * s, ay + rx * s + ry * c))      # clockwise on a y-down screen
    return out


def _point_in_poly(pt: Tuple[float, float], poly: List[Tuple[float, float]]) -> bool:
    x, y = pt
    inside = False
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1:
            inside = not inside
    return inside


HANDLE_CURSORS = {"tl": Qt.CursorShape.SizeFDiagCursor, "br": Qt.CursorShape.SizeFDiagCursor,
                  "tr": Qt.CursorShape.SizeBDiagCursor, "bl": Qt.CursorShape.SizeBDiagCursor,
                  "t": Qt.CursorShape.SizeVerCursor, "b": Qt.CursorShape.SizeVerCursor,
                  "l": Qt.CursorShape.SizeHorCursor, "r": Qt.CursorShape.SizeHorCursor,
                  "anchor": Qt.CursorShape.SizeAllCursor}


class FaceCanvas(QWidget):
    selectionChanged = pyqtSignal(int)              # widget uid, -1 for none
    liveChanged = pyqtSignal()                       # geometry changing while dragging
    edited = pyqtSignal(str, object)                 # (undo text, snapshot before) after a finished edit
    cursorMoved = pyqtSignal(int, int)               # design coordinates under the mouse
    zoomChanged = pyqtSignal(float)
    deleteRequested = pyqtSignal()

    MIN_ZOOM, MAX_ZOOM = 0.25, 8.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(360, 320)
        self.project: Optional[Project] = None
        self.state = SimState()
        self.face: Optional[QImage] = None
        self.selected_uid: int = -1
        self.zoom = 1.0
        self.origin = QPointF(40, 40)
        self._fit = True
        self._space = False
        self._int: Optional[dict] = None
        self._guides: List[Tuple[str, float]] = []
        self._hover = ""
        self.show_grid = False
        self.snap = True
        self.show_guides = True
        self.show_bounds = False
        self.show_frame = True
        self.grid_size = 10
        self.theme = dict(CANVAS_THEMES["light"])

    # ------------------------------------------------------------------ setup
    def set_theme(self, name: str):
        self.theme = dict(CANVAS_THEMES.get(name, CANVAS_THEMES["light"]))
        self.update()

    def set_project(self, project: Project):
        self.project = project
        self.selected_uid = -1
        self.update()

    def set_face(self, pil_img, state: SimState):
        self.face = pil_to_qimage(pil_img)
        self.state = state
        self.update()

    def set_selected(self, uid: int):
        if uid != self.selected_uid:
            self.selected_uid = uid
            self.update()

    def selected_widget(self) -> Optional[Widget]:
        return self.project.widget_by_uid(self.selected_uid) if self.project and self.selected_uid >= 0 else None

    # ------------------------------------------------------------------ view transform
    def to_widget(self, x: float, y: float) -> QPointF:
        return QPointF(self.origin.x() + x * self.zoom, self.origin.y() + y * self.zoom)

    def to_design(self, p: QPointF) -> Tuple[float, float]:
        return (p.x() - self.origin.x()) / self.zoom, (p.y() - self.origin.y()) / self.zoom

    def fit_view(self):
        self._fit = True
        z = min((self.width() - 90) / SCREEN_W, (self.height() - 90) / SCREEN_H)
        self.zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, z))
        self.origin = QPointF((self.width() - SCREEN_W * self.zoom) / 2, (self.height() - SCREEN_H * self.zoom) / 2)
        self.zoomChanged.emit(self.zoom)
        self.update()

    def set_zoom(self, z: float, around: Optional[QPointF] = None):
        z = max(self.MIN_ZOOM, min(self.MAX_ZOOM, z))
        around = around or QPointF(self.width() / 2, self.height() / 2)
        dx, dy = self.to_design(around)
        self.zoom = z
        self.origin = QPointF(around.x() - dx * z, around.y() - dy * z)
        self._fit = False
        self.zoomChanged.emit(self.zoom)
        self.update()

    def zoom_by(self, factor: float):
        self.set_zoom(self.zoom * factor)

    def resizeEvent(self, e):
        if self._fit:
            self.fit_view()
        super().resizeEvent(e)

    # ------------------------------------------------------------------ painting
    def paintEvent(self, e):
        t = self.theme
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(t["bg"]))
        p.setPen(QPen(QColor(t["dot"]), 1.6))
        step = 20
        for x in range(step // 2, self.width(), step):
            for y in range(step // 2, self.height(), step):
                p.drawPoint(QPointF(x, y))
        z = self.zoom
        r = QRectF(self.origin.x(), self.origin.y(), SCREEN_W * z, SCREEN_H * z)
        p.fillRect(r.translated(0, 3), QColor(*t["shadow"]))
        if self.face is not None:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, z < 1.5)
            p.drawImage(r, self.face)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        else:
            p.fillRect(r, QColor("#000000"))
        if self.show_frame:
            p.setPen(QPen(QColor(t["frame"]), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(r)
        if self.show_grid:
            self._paint_grid(p, r)
        if self.show_guides:
            pen = QPen(QColor(t["accent"]), 1, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            p.setPen(pen)
            cx, cy = self.to_widget(SCREEN_W / 2, SCREEN_H / 2).x(), self.to_widget(SCREEN_W / 2, SCREEN_H / 2).y()
            p.drawLine(QPointF(cx, r.top()), QPointF(cx, r.bottom()))
            p.drawLine(QPointF(r.left(), cy), QPointF(r.right(), cy))
        if self.project is not None:
            if self.show_bounds:
                p.setPen(QPen(QColor(t["bounds"]), 1, Qt.PenStyle.DotLine))
                for w in self.project.items:
                    if not w.is_analog and not w.hidden:
                        p.drawRect(self._wrect(w))
            sel = self.selected_widget()
            if sel is not None:
                self._paint_selection(p, sel)
        p.setPen(QPen(QColor(t["guide"]), 1))
        for kind, v in self._guides:
            if kind == "v":
                x = self.to_widget(v, 0).x()
                p.drawLine(QPointF(x, r.top() - 6), QPointF(x, r.bottom() + 6))
            else:
                y = self.to_widget(0, v).y()
                p.drawLine(QPointF(r.left() - 6, y), QPointF(r.right() + 6, y))
        p.end()

    def _paint_grid(self, p: QPainter, r: QRectF):
        g = self.grid_size
        for i, x in enumerate(range(0, SCREEN_W + 1, g)):
            major = (x // g) % 5 == 0
            p.setPen(QPen(QColor(255, 255, 255, 46 if major else 20), 1))
            xx = self.to_widget(x, 0).x()
            p.drawLine(QPointF(xx, r.top()), QPointF(xx, r.bottom()))
        for y in range(0, SCREEN_H + 1, g):
            major = (y // g) % 5 == 0
            p.setPen(QPen(QColor(255, 255, 255, 46 if major else 20), 1))
            yy = self.to_widget(0, y).y()
            p.drawLine(QPointF(r.left(), yy), QPointF(r.right(), yy))

    def _wrect(self, w: Widget) -> QRectF:
        a = self.to_widget(w.x, w.y)
        return QRectF(a.x(), a.y(), w.w * self.zoom, w.h * self.zoom)

    def _handle_points(self, w: Widget) -> dict:
        r = self._wrect(w)
        cx, cy = r.center().x(), r.center().y()
        return {"tl": QPointF(r.left(), r.top()), "t": QPointF(cx, r.top()), "tr": QPointF(r.right(), r.top()),
                "l": QPointF(r.left(), cy), "r": QPointF(r.right(), cy),
                "bl": QPointF(r.left(), r.bottom()), "b": QPointF(cx, r.bottom()), "br": QPointF(r.right(), r.bottom())}

    def _anchor_points(self, w: Widget) -> List[QPointF]:
        return [self.to_widget(w.geti(pre + "anchorx", SCREEN_W // 2), w.geti(pre + "anchory", SCREEN_H // 2))
                for _, pre in HAND_DEFS]

    def _chip(self, p: QPainter, text: str, x: float, y: float):
        f = QFont()
        f.setPointSizeF(8.5)
        f.setBold(True)
        p.setFont(f)
        fm = QFontMetricsF(f)
        w = fm.horizontalAdvance(text) + 12
        h = fm.height() + 4
        rect = QRectF(x, y - h - 4, w, h)
        path = QPainterPath()
        path.addRoundedRect(rect, 4, 4)
        p.fillPath(path, QColor(self.theme["accent"]))
        p.setPen(QColor(self.theme["chip_fg"]))
        p.drawText(QPointF(rect.left() + 6, rect.top() + 2 + fm.ascent()), text)

    def _paint_selection(self, p: QPainter, w: Widget):
        acc = QColor(self.theme["accent"])
        if w.is_analog:
            p.setPen(QPen(acc, 1.2, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            for kind, pre in HAND_DEFS:
                q = hand_quad(self.project, w, kind, pre, self.state)
                if q:
                    poly = QPolygonF([self.to_widget(x, y) for x, y in q])
                    p.drawPolygon(poly)
            for pt in self._anchor_points(w):
                p.setPen(QPen(acc, 1.6))
                p.setBrush(QColor(self.theme["handle"]))
                p.drawEllipse(pt, 5.5, 5.5)
                p.drawLine(QPointF(pt.x() - 9, pt.y()), QPointF(pt.x() + 9, pt.y()))
                p.drawLine(QPointF(pt.x(), pt.y() - 9), QPointF(pt.x(), pt.y() + 9))
            a = self._anchor_points(w)[0]
            self._chip(p, "%s  anchor %d,%d" % (w.title, w.geti("houranchorx"), w.geti("houranchory")),
                       a.x() + 12, a.y() - 8)
            return
        r = self._wrect(w)
        p.setPen(QPen(acc, 1.5, Qt.PenStyle.DashLine if w.locked else Qt.PenStyle.SolidLine))
        p.setBrush(QColor(acc.red(), acc.green(), acc.blue(), 26))
        p.drawRect(r)
        if not w.locked:
            p.setPen(QPen(acc, 1.4))
            p.setBrush(QColor(self.theme["handle"]))
            for pt in self._handle_points(w).values():
                p.drawRect(QRectF(pt.x() - 4, pt.y() - 4, 8, 8))
        self._chip(p, "%s  %d, %d  %d\u00d7%d%s" % (w.title, w.x, w.y, w.w, w.h, "  \U0001F512" if w.locked else ""),
                   r.left(), r.top())

    # ------------------------------------------------------------------ hit testing
    def _handle_at(self, w: Widget, pos: QPointF) -> str:
        if w.is_analog:
            return "anchor" if any(math.hypot(pos.x() - a.x(), pos.y() - a.y()) <= 10 for a in self._anchor_points(w)) else ""
        for name, pt in self._handle_points(w).items():
            if abs(pos.x() - pt.x()) <= 7 and abs(pos.y() - pt.y()) <= 7:
                return name
        return ""

    def _hit_widget(self, dp: Tuple[float, float]) -> Optional[Widget]:
        if self.project is None:
            return None
        pad = 3 / self.zoom
        for w in reversed(self.project.items):
            if w.hidden:
                continue
            if w.is_analog:
                for kind, pre in HAND_DEFS:
                    q = hand_quad(self.project, w, kind, pre, self.state)
                    if q and _point_in_poly(dp, q):
                        return w
            elif w.x - pad <= dp[0] <= w.x + w.w + pad and w.y - pad <= dp[1] <= w.y + w.h + pad:
                return w
        return None

    # ------------------------------------------------------------------ snapping
    def _targets(self, exclude: int) -> Tuple[List[float], List[float]]:
        xs = [0.0, SCREEN_W / 2, float(SCREEN_W)]
        ys = [0.0, SCREEN_H / 2, float(SCREEN_H)]
        for w in self.project.items:
            if w.uid != exclude and not w.is_analog and not w.hidden:
                xs += [w.x, w.x + w.w / 2, w.x + w.w]
                ys += [w.y, w.y + w.h / 2, w.y + w.h]
        return xs, ys

    def _snap_axis(self, edges: List[float], targets: List[float]) -> Tuple[float, Optional[float]]:
        thr = 6 / self.zoom
        best, guide = 0.0, None
        bd = thr + 1
        for e in edges:
            for t in targets:
                d = t - e
                if abs(d) < bd and abs(d) <= thr:
                    bd, best, guide = abs(d), d, t
        return best, guide

    # ------------------------------------------------------------------ mouse
    def mousePressEvent(self, e):
        self.setFocus()
        pos = e.position()
        if e.button() == Qt.MouseButton.MiddleButton or (e.button() == Qt.MouseButton.LeftButton and self._space):
            self._int = dict(mode="pan", start=pos, origin=QPointF(self.origin))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if e.button() != Qt.MouseButton.LeftButton or self.project is None:
            return
        dp = self.to_design(pos)
        sel = self.selected_widget()
        if sel is not None and not sel.locked:
            h = self._handle_at(sel, pos)
            if h:
                self._begin(sel, "anchor" if h == "anchor" else "resize", h, dp)
                return
        hit = self._hit_widget(dp)
        if hit is None:
            self.selected_uid = -1
            self.selectionChanged.emit(-1)
            self.update()
            return
        if hit.uid != self.selected_uid:
            self.selected_uid = hit.uid
            self.selectionChanged.emit(hit.uid)
        if not hit.locked and not hit.is_analog:
            self._begin(hit, "move", "", dp)
        elif not hit.locked and hit.is_analog:
            self._begin(hit, "anchor", "anchor", dp)
        self.update()

    def _begin(self, w: Widget, mode: str, handle: str, dp: Tuple[float, float]):
        self._int = dict(mode=mode, handle=handle, start=dp, uid=w.uid, before=self.project.snapshot(),
                         orig=dict(w.data), changed=False)

    def mouseMoveEvent(self, e):
        pos = e.position()
        dx, dy = self.to_design(pos)
        self.cursorMoved.emit(int(math.floor(dx)), int(math.floor(dy)))
        it = self._int
        if it is None:
            self._update_hover(pos)
            return
        if it["mode"] == "pan":
            self.origin = QPointF(it["origin"].x() + pos.x() - it["start"].x(), it["origin"].y() + pos.y() - it["start"].y())
            self._fit = False
            self.update()
            return
        w = self.project.widget_by_uid(it["uid"])
        if w is None:
            return
        ddx, ddy = dx - it["start"][0], dy - it["start"][1]
        o = it["orig"]
        self._guides = []
        if it["mode"] == "anchor":
            ix, iy = int(round(ddx)), int(round(ddy))
            for _, pre in HAND_DEFS:
                w.data[pre + "anchorx"] = int(o.get(pre + "anchorx", SCREEN_W // 2)) + ix
                w.data[pre + "anchory"] = int(o.get(pre + "anchory", SCREEN_H // 2)) + iy
        elif it["mode"] == "move":
            x0, y0, ww, hh = int(o["x"]), int(o["y"]), int(o["w"]), int(o["h"])
            nx, ny = x0 + ddx, y0 + ddy
            if self.snap:
                xs, ys = self._targets(w.uid)
                sx, gx = self._snap_axis([nx, nx + ww / 2, nx + ww], xs)
                sy, gy = self._snap_axis([ny, ny + hh / 2, ny + hh], ys)
                nx, ny = nx + sx, ny + sy
                if gx is not None:
                    self._guides.append(("v", gx))
                if gy is not None:
                    self._guides.append(("h", gy))
                if self.show_grid and gx is None:
                    nx = round(nx / self.grid_size) * self.grid_size
                if self.show_grid and gy is None:
                    ny = round(ny / self.grid_size) * self.grid_size
            w.x, w.y = int(round(nx)), int(round(ny))
        else:
            self._resize(w, it["handle"], o, ddx, ddy)
        it["changed"] = True
        self.liveChanged.emit()
        self.update()

    def _resize(self, w: Widget, h: str, o: dict, dx: float, dy: float):
        x0, y0, x1, y1 = float(o["x"]), float(o["y"]), float(o["x"]) + float(o["w"]), float(o["y"]) + float(o["h"])
        xs, ys = self._targets(w.uid) if self.snap else ([], [])
        if "l" in h:
            x0 += dx
            if self.snap:
                s, g = self._snap_axis([x0], xs)
                x0 += s
                if g is not None:
                    self._guides.append(("v", g))
        if "r" in h:
            x1 += dx
            if self.snap:
                s, g = self._snap_axis([x1], xs)
                x1 += s
                if g is not None:
                    self._guides.append(("v", g))
        if "t" in h:
            y0 += dy
            if self.snap:
                s, g = self._snap_axis([y0], ys)
                y0 += s
                if g is not None:
                    self._guides.append(("h", g))
        if "b" in h:
            y1 += dy
            if self.snap:
                s, g = self._snap_axis([y1], ys)
                y1 += s
                if g is not None:
                    self._guides.append(("h", g))
        x0, y0, x1, y1 = round(x0), round(y0), round(x1), round(y1)
        if x1 - x0 < 4:
            if "l" in h:
                x0 = x1 - 4
            else:
                x1 = x0 + 4
        if y1 - y0 < 4:
            if "t" in h:
                y0 = y1 - 4
            else:
                y1 = y0 + 4
        w.x, w.y, w.w, w.h = int(x0), int(y0), int(x1 - x0), int(y1 - y0)

    def mouseReleaseEvent(self, e):
        it, self._int = self._int, None
        self._guides = []
        self.unsetCursor()
        if it and it["mode"] != "pan" and it.get("changed"):
            label = {"move": "Move", "resize": "Resize", "anchor": "Move hands"}[it["mode"]]
            w = self.project.widget_by_uid(it["uid"])
            self.edited.emit("%s %s" % (label, w.title if w else "widget"), it["before"])
        self.update()

    def _update_hover(self, pos: QPointF):
        sel = self.selected_widget()
        cur = None
        if self._space:
            cur = Qt.CursorShape.OpenHandCursor
        elif sel is not None and not sel.locked:
            h = self._handle_at(sel, pos)
            cur = HANDLE_CURSORS.get(h)
        if cur is None and self.project is not None:
            hit = self._hit_widget(self.to_design(pos))
            if hit is not None and not hit.locked:
                cur = Qt.CursorShape.SizeAllCursor
        if cur is None:
            self.unsetCursor()
        else:
            self.setCursor(cur)

    def wheelEvent(self, e):
        dy = e.angleDelta().y()
        if dy:
            self.set_zoom(self.zoom * (1.12 if dy > 0 else 1 / 1.12), e.position())
        e.accept()

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key.Key_Space:
            self._space = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            return
        w = self.selected_widget()
        if k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and w is not None:
            self.deleteRequested.emit()
            return
        if k == Qt.Key.Key_Escape:
            self.selected_uid = -1
            self.selectionChanged.emit(-1)
            self.update()
            return
        arrows = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0), Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
        if k in arrows and w is not None and not w.locked:
            step = 10 if (e.modifiers() & Qt.KeyboardModifier.ShiftModifier) else 1
            before = self.project.snapshot()
            dx, dy = arrows[k][0] * step, arrows[k][1] * step
            if w.is_analog:
                for _, pre in HAND_DEFS:
                    w.data[pre + "anchorx"] = w.geti(pre + "anchorx") + dx
                    w.data[pre + "anchory"] = w.geti(pre + "anchory") + dy
            else:
                w.x, w.y = w.x + dx, w.y + dy
            self.edited.emit("Nudge %s" % w.title, before)
            self.update()
            return
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key.Key_Space:
            self._space = False
            self.unsetCursor()
        super().keyReleaseEvent(e)


class PreviewWidget(QWidget):
    """Live preview clipped to a device shape: 'rounded' (the IDW20), 'rect' or 'circle'."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(250)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.face: Optional[QImage] = None
        self.shape = "rounded"
        self.dark = False

    def set_face(self, pil_img):
        self.face = pil_to_qimage(pil_img)
        self.update()

    def set_shape(self, shape: str):
        self.shape = shape
        self.update()

    def set_dark(self, dark: bool):
        self.dark = dark
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        m = 14
        avail = QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m)
        aspect = SCREEN_W / SCREEN_H
        h = min(avail.height(), avail.width() / aspect)
        w = h * aspect
        r = QRectF(avail.center().x() - w / 2, avail.center().y() - h / 2, w, h)
        path = QPainterPath()
        if self.shape == "circle":
            path.addEllipse(QRectF(r.center().x() - w / 2, r.center().y() - w / 2, w, w))
        elif self.shape == "rect":
            path.addRect(r)
        else:
            path.addRoundedRect(r, w * 0.200, w * 0.200)
        shadow = QPainterPath(path)
        shadow.translate(0, 3)
        p.fillPath(shadow, QColor(0, 0, 0, 70 if self.dark else 40))
        if self.face is not None:
            p.save()
            p.setClipPath(path)
            p.fillRect(r, QColor("#000000"))
            p.drawImage(r, self.face)
            p.restore()
        else:
            p.fillPath(path, QColor("#000000"))
        #p.setPen(QPen(QColor("#8b8f98" if not self.dark else "#6a6e7a"), 2.4))
        #p.setBrush(Qt.BrushStyle.NoBrush)
        #p.drawPath(path)
        p.end()
