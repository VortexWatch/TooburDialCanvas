from __future__ import annotations

import copy
import datetime
import io
import itertools
import json
import math
import os
import struct
import zipfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

APP_NAME = "TooburDialCanvas"
APP_VERSION = "0.2.0"
SCREEN_W, SCREEN_H = 320, 385
PREVIEW_W, PREVIEW_H = 272, 324
MAX_ENTRY_NAME = 31
WEEK_ORDER = ["sun", "mon", "tue", "wed", "thur", "fri", "sat"]          # glyph order used by stock faces
PY_WEEKDAY_KEYS = ["mon", "tue", "wed", "thur", "fri", "sat", "sun"]     # datetime.weekday() -> key
HAND_DEFS = (("hour", "hour"), ("minute", "min"), ("second", "sec"))     # (manifest key, key prefix)
TOP_KEY_ORDER = ["version", "clouddialversion", "preview", "name", "author", "description", "deviceId",
                 "bluetooth", "disturb", "battery", "compress", "environment"]


# =====================================================================================
#  RAW image codec
# =====================================================================================
_B8 = np.array([[0, 32, 8, 40, 2, 34, 10, 42], [48, 16, 56, 24, 50, 18, 58, 26], [12, 44, 4, 36, 14, 46, 6, 38],
                [60, 28, 52, 20, 62, 30, 54, 22], [3, 35, 11, 43, 1, 33, 9, 41], [51, 19, 59, 27, 49, 17, 57, 25],
                [15, 47, 7, 39, 13, 45, 5, 37], [63, 31, 55, 23, 61, 29, 53, 21]])
_B4 = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]])


def _thr(h: int, w: int, m: np.ndarray) -> np.ndarray:
    n = m.shape[0]
    return np.tile((m + .5) / (n * n), (h // n + 1, w // n + 1))[:h, :w]


def _rgb565(rgb: np.ndarray, dither: bool) -> np.ndarray:
    r, g, b = (rgb[..., i].astype(np.int32) for i in range(3))
    exact = ((((r >> 3) * 255 // 31) == r).all() and (((g >> 2) * 255 // 63) == g).all()
             and (((b >> 3) * 255 // 31) == b).all())
    if exact or not dither:                                  # stock behaviour: plain truncation
        return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
    t = _thr(r.shape[0], r.shape[1], _B8)
    r5 = np.clip(np.floor(r / 255 * 31 + t), 0, 31).astype(np.int32)
    g6 = np.clip(np.floor(g / 255 * 63 + t), 0, 63).astype(np.int32)
    b5 = np.clip(np.floor(b / 255 * 31 + t), 0, 31).astype(np.int32)
    return (r5 << 11) | (g6 << 5) | b5


def encode_raw(img: Image.Image, alpha: bool, dither: bool = False) -> bytes:
    """PIL image -> RAW blob.  Opaque images are flattened onto black (an LCD shows black as 'off')."""
    im = img.convert("RGBA")
    w, h = im.size
    if not alpha:
        base = Image.new("RGBA", (w, h), (0, 0, 0, 255))
        base.alpha_composite(im)
        im = base
    a = np.asarray(im, dtype=np.uint8)
    body = _rgb565(a[..., :3], dither).astype(">u2").tobytes()
    if not alpha:
        return struct.pack("<4sHHBBBBI", b"RAW\0", w, h, 0x85, 0, 0, 0, 0) + body
    al = a[..., 3].astype(np.int32)
    if dither and not (al % 17 == 0).all():
        a4 = np.clip(np.floor(al / 17.0 + _thr(h, w, _B4)), 0, 15)
    else:
        a4 = al >> 4
    flat = a4.astype(np.uint8).flatten()
    if flat.size % 2:
        flat = np.append(flat, np.uint8(0))
    packed = ((flat[0::2] << 4) | flat[1::2]).astype(np.uint8).tobytes()      # first pixel = HIGH nibble
    return struct.pack("<4sHHBBBBI", b"RAW\0", w, h, 0x85, 0x66, 0, 0, len(body)) + body + packed


def decode_raw(b: bytes) -> Image.Image:
    if b[:4] != b"RAW\0":
        raise ValueError("not a RAW image")
    w, h = struct.unpack_from("<HH", b, 4)
    n = w * h
    px = np.frombuffer(b[16:16 + n * 2], dtype=">u2").reshape(h, w).astype(np.int32)
    rgb = np.dstack([(px >> 11) * 255 // 31, ((px >> 5) & 63) * 255 // 63, (px & 31) * 255 // 31])
    rest = np.frombuffer(b[16 + n * 2:], dtype=np.uint8)
    if rest.size:
        nib = np.empty(rest.size * 2, np.uint8)
        nib[0::2] = rest >> 4
        nib[1::2] = rest & 15
        a = (nib[:n].astype(np.int32) * 17).reshape(h, w)
    else:
        a = np.full((h, w), 255, np.int32)
    return Image.fromarray(np.dstack([rgb, a]).astype(np.uint8), "RGBA")


# =====================================================================================
#  Container
# =====================================================================================
def pack_iwf(entries: List[Tuple[str, bytes]]) -> bytes:
    off = 8 + 40 * len(entries)
    table, data = bytearray(), bytearray()
    for name, blob in entries:
        nb = name.encode("utf-8")
        if len(nb) > MAX_ENTRY_NAME:
            raise ValueError("entry name too long (max %d bytes): %s" % (MAX_ENTRY_NAME, name))
        table += nb.ljust(32, b"\0") + struct.pack("<II", off + len(data), len(blob))
        data += blob
    return b"iwf\0" + struct.pack("<HH", 1, len(entries)) + bytes(table) + bytes(data)


def unpack_iwf(d: bytes) -> List[Tuple[str, bytes]]:
    if d[:4] != b"iwf\0":
        raise ValueError("not an .iwf file (bad magic)")
    ver, cnt = struct.unpack_from("<HH", d, 4)
    out = []
    for i in range(cnt):
        o = 8 + 40 * i
        name = d[o:o + 32].split(b"\0", 1)[0].decode("utf-8", "replace")
        off, size = struct.unpack_from("<II", d, o + 32)
        if off + size > len(d):
            raise ValueError("entry %r runs past end of file" % name)
        out.append((name, d[off:off + size]))
    return out


def dumps_json(obj) -> bytes:
    """Same text format as the stock faces: compact, non-ASCII kept as UTF-8."""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


# =====================================================================================
#  Simulation state (what the preview pretends the watch knows)
# =====================================================================================
@dataclass
class SimState:
    year: int = 2026
    month: int = 11
    day: int = 28
    hour: int = 10
    minute: int = 8
    second: int = 24
    use24h: bool = False
    temp: int = 23
    temp_unit: str = "C"
    steps: int = 8426
    calories: int = 312
    battery: int = 87

    def clamp(self):
        self.month = min(12, max(1, self.month))
        last = (datetime.date(self.year + (self.month == 12), self.month % 12 + 1, 1) - datetime.timedelta(days=1)).day
        self.day = min(last, max(1, self.day))
        self.hour %= 24
        self.minute = min(59, max(0, self.minute))
        self.second = min(59, max(0, self.second))

    @property
    def weekday_key(self) -> str:
        self.clamp()
        return PY_WEEKDAY_KEYS[datetime.date(self.year, self.month, self.day).weekday()]

    @property
    def display_hour(self) -> int:
        return self.hour if self.use24h else (self.hour % 12 or 12)

    def copy(self) -> "SimState":
        return copy.copy(self)


# =====================================================================================
#  Widget types
# =====================================================================================
def _digits():
    return [(str(i), str(i)) for i in range(10)]


CHARSETS = {
    "digits": _digits(),
    "time": _digits() + [("10", ":")],
    "date": _digits() + [("10", "/")],
    "weather": _digits() + [("10", "-"), ("11", "\u00b0C"), ("12", "\u00b0F")],
    "battery": _digits() + [("10", "%")],
    "week": [("en_" + d, "THU" if d == "thur" else d.upper()) for d in WEEK_ORDER],
}

# group: how the Add-widget dialog sorts them.  layout: representative glyphs for the widest value.
WIDGET_SPECS: Dict[Tuple[str, str], dict] = {
    ("custom", "time"): dict(label="Digital Time", group="Time & Date", charset="time", fontnum=11, addwh=True,
                             align="left", layout=["8", "8", "10", "8", "8"],
                             desc="Current time as HH:MM. Glyph 10 is the colon."),
    ("custom", "date"): dict(label="Date", group="Time & Date", charset="date", fontnum=11, addwh=False,
                             align="left", style=1, layout=["8", "8", "10", "8", "8"],
                             desc="Date as MM/DD (style 1). Glyph 10 is the slash."),
    ("custom", "week"): dict(label="Weekday", group="Time & Date", charset="week", fontnum=7, addwh=False,
                             align="left", style=0, layout=["en_wed"],
                             desc="Weekday label, one image per day (en_sun ... en_sat)."),
    ("custom", "day"): dict(label="Day of Month", group="Time & Date", charset="digits", fontnum=10, addwh=False,
                            align="left", layout=["8", "8"], desc="Day of the month, digits only."),
    ("custom", "hour"): dict(label="Hour", group="Time & Date", charset="digits", fontnum=10, addwh=True,
                             align="left", layout=["8", "8"], desc="Hours only, for stacked or split clocks."),
    ("custom", "min"): dict(label="Minute", group="Time & Date", charset="digits", fontnum=10, addwh=True,
                            align="left", layout=["8", "8"], desc="Minutes only, for stacked or split clocks."),
    ("custom", "weather"): dict(label="Weather", group="Data", charset="weather", fontnum=13, addwh=True,
                                align="center", style=2, layout=["10", "8", "8", "11"],
                                desc="Temperature. Glyphs: 10 = minus, 11 = \u00b0C, 12 = \u00b0F."),
    ("custom", "battery"): dict(label="Battery", group="Data", charset="battery", fontnum=11, addwh=True,
                                align="left", layout=["8", "8", "8", "10"], desc="Battery level. Glyph 10 is %."),
    ("custom", "step"): dict(label="Steps", group="Data", charset="digits", fontnum=10, addwh=True,
                             align="center", layout=["8"] * 5, desc="Step count."),
    ("custom", "calorie"): dict(label="Calories", group="Data", charset="digits", fontnum=10, addwh=True,
                                align="center", layout=["8"] * 4, desc="Calories burned."),
    ("watch", "time"): dict(label="Analog Hands", group="Analog", charset=None, fontnum=0, addwh=False,
                            align="left", layout=[], desc="Hour, minute and second hands rotated around a pivot."),
}


def sample_stems(spec_key: Tuple[str, str]) -> List[Tuple[str, str]]:
    cs = WIDGET_SPECS.get(spec_key, {}).get("charset")
    return list(CHARSETS[cs]) if cs else []


# =====================================================================================
#  Widget
# =====================================================================================
class Widget:
    """One manifest ``item``.  ``data`` is the raw dict, so unknown keys survive a round trip."""
    _uid = itertools.count(1)

    def __init__(self, data: dict, uid: Optional[int] = None, hidden: bool = False, locked: bool = False):
        self.data = data
        self.uid = uid if uid is not None else next(Widget._uid)
        self.hidden = hidden          # editor-only flags, never written to the file
        self.locked = locked

    def clone(self) -> "Widget":
        return Widget(copy.deepcopy(self.data), self.uid, self.hidden, self.locked)

    key = property(lambda s: (s.data.get("widget", "custom"), s.data.get("type", "")))
    wtype = property(lambda s: s.data.get("type", ""))
    spec = property(lambda s: WIDGET_SPECS.get(s.key))
    is_analog = property(lambda s: s.key == ("watch", "time"))
    title = property(lambda s: (s.spec or {}).get("label") or "%s/%s" % s.key)
    font = property(lambda s: s.data.get("font", ""))

    def geti(self, k: str, default: int = 0) -> int:
        try:
            return int(self.data.get(k, default))
        except (TypeError, ValueError):
            return default

    x = property(lambda s: s.geti("x"), lambda s, v: s.data.__setitem__("x", int(v)))
    y = property(lambda s: s.geti("y"), lambda s, v: s.data.__setitem__("y", int(v)))
    w = property(lambda s: s.geti("w"), lambda s, v: s.data.__setitem__("w", int(v)))
    h = property(lambda s: s.geti("h"), lambda s, v: s.data.__setitem__("h", int(v)))

    def rect(self) -> Tuple[int, int, int, int]:
        return self.x, self.y, self.w, self.h


def color_from_str(s: str) -> Tuple[int, int, int, int]:
    """'0xAARRGGBB' -> (r, g, b, a). Falls back to opaque white."""
    try:
        v = int(str(s), 16)
        return (v >> 16) & 255, (v >> 8) & 255, v & 255, (v >> 24) & 255
    except (TypeError, ValueError):
        return 255, 255, 255, 255


def color_to_str(r: int, g: int, b: int, a: int = 255) -> str:
    return "0x%02X%02X%02X%02X" % (a, r, g, b)


def make_widget_data(key: Tuple[str, str], x: int, y: int, w: int, h: int, font: str = "") -> dict:
    spec = WIDGET_SPECS[key]
    d = {"widget": key[0], "type": key[1]}
    if key == ("watch", "time"):
        cx, cy = SCREEN_W // 2, SCREEN_H // 2
        d.update(x=0, y=0, w=SCREEN_W, h=SCREEN_H, stepless_rotation=0)
        names = {"hour": "h.png", "minute": "m.png", "second": "s.png"}
        for k, pre in (("second", "sec"), ("minute", "min"), ("hour", "hour")):      # stock key order
            d[k] = names[k]
            if k == "second":
                d["fgcolor"] = "0xFFFFFFFF"
            d.update({pre + "centerx": 0, pre + "centery": 0, pre + "anchorx": cx, pre + "anchory": cy})
        return d
    if spec.get("addwh"):
        d["isShowAddwh"] = True
    d.update(x=x, y=y, w=w, h=h, fgcolor="0xFFFFFFFF", fgrender="0xFFFFFFFF", align=spec.get("align", "left"))
    if "style" in spec:
        d["style"] = spec["style"]
    d.update(font=font or key[1], fontnum=spec["fontnum"])
    return d


# =====================================================================================
#  Project
# =====================================================================================
class Project:
    def __init__(self):
        self.meta: dict = {"version": 1, "clouddialversion": 3, "preview": "preview.png", "name": "Untitled",
                           "author": "user", "description": "IDW20", "deviceId": "IDW20", "bluetooth": False,
                           "disturb": False, "battery": False, "compress": "LZ4", "environment": "Production"}
        self.items: List[Widget] = []
        self.bkground: str = "background.png"
        self.fontsets: List[dict] = []                                   # font.json "item" records
        self.images: Dict[str, Image.Image] = {}                         # background, preview, hand images
        self.glyphs: Dict[str, Dict[str, Image.Image]] = {}              # set -> stem -> image
        self.path: Optional[str] = None
        self.load_warnings: List[str] = []

    # -------- construction -------------------------------------------------------
    @staticmethod
    def blank(name: str = "Untitled", author: str = "") -> "Project":
        p = Project()
        p.meta["name"], p.meta["author"] = name, author
        black = Image.new("RGBA", (SCREEN_W, SCREEN_H), (0, 0, 0, 255))
        p.images[p.bkground] = black
        p.images["preview.png"] = Image.new("RGBA", (PREVIEW_W, PREVIEW_H), (0, 0, 0, 255))
        return p

    # -------- convenience --------------------------------------------------------
    name = property(lambda s: s.meta.get("name", ""))
    preview_name = property(lambda s: s.meta.get("preview", "preview.png"))

    @property
    def background(self) -> Optional[Image.Image]:
        return self.images.get(self.bkground)

    def widget_by_uid(self, uid: int) -> Optional[Widget]:
        return next((w for w in self.items if w.uid == uid), None)

    def fontset_names(self) -> List[str]:
        return [f["name"] for f in self.fontsets]

    def ensure_fontset(self, name: str):
        if name not in self.fontset_names():
            self.fontsets.append({"name": name, "bpp": 16, "format": "png"})
        self.glyphs.setdefault(name, {})

    def unique_fontset_name(self, base: str) -> str:
        names, n, cand = set(self.fontset_names()) | set(self.glyphs), 1, base
        while cand in names:
            n += 1
            cand = "%s_%d" % (base, n)
        return cand

    def unique_image_name(self, base: str) -> str:
        stem, ext = os.path.splitext(base)
        n, cand = 1, base
        while cand in self.images:
            n += 1
            cand = "%s_%d%s" % (stem, n, ext)
        return cand

    def used_hand_images(self) -> List[str]:
        out = []
        for w in self.items:
            if w.is_analog:
                for k, _ in HAND_DEFS:
                    v = w.data.get(k)
                    if v and v not in out:
                        out.append(v)
        return out

    def prune_unused(self):
        """Drop hand images and glyph sets nothing refers to any more."""
        keep = {self.bkground, self.preview_name} | set(self.used_hand_images())
        for n in [n for n in self.images if n not in keep]:
            del self.images[n]
        used = {w.font for w in self.items if not w.is_analog}
        for n in [n for n in self.fontset_names() if n not in used]:
            self.fontsets = [f for f in self.fontsets if f["name"] != n]
            self.glyphs.pop(n, None)

    # -------- undo support -------------------------------------------------------
    def snapshot(self) -> dict:
        return dict(meta=copy.deepcopy(self.meta), items=[w.clone() for w in self.items], bkground=self.bkground,
                    fontsets=copy.deepcopy(self.fontsets), images=dict(self.images),
                    glyphs={k: dict(v) for k, v in self.glyphs.items()})

    def restore(self, s: dict):
        self.meta = copy.deepcopy(s["meta"])
        self.items = [w.clone() for w in s["items"]]
        self.bkground = s["bkground"]
        self.fontsets = copy.deepcopy(s["fontsets"])
        self.images = dict(s["images"])
        self.glyphs = {k: dict(v) for k, v in s["glyphs"].items()}

    # -------- manifest -----------------------------------------------------------
    def manifest(self) -> dict:
        d = {k: self.meta[k] for k in TOP_KEY_ORDER if k in self.meta}
        for k, v in self.meta.items():
            if k not in d and k not in ("item", "bkground"):
                d[k] = v
        d["item"] = [w.data for w in self.items]
        d["bkground"] = self.bkground
        return d

    def fonts_json(self) -> dict:
        return {"item": self.fontsets}

    # -------- loading ------------------------------------------------------------
    @staticmethod
    def load(path: str) -> "Project":
        if os.path.isdir(path):
            p = Project._load_tree(lambda n: open(os.path.join(path, n), "rb").read(),
                                   lambda n: os.path.exists(os.path.join(path, n)),
                                   lambda d: sorted(f for f in os.listdir(os.path.join(path, d)) if f.lower().endswith(".png"))
                                   if os.path.isdir(os.path.join(path, d)) else [])
        elif path.lower().endswith(".zip"):
            z = zipfile.ZipFile(path)
            names = {n.replace("\\", "/") for n in z.namelist()}
            prefix = ""
            if "iwf.json" not in names:                                  # tolerate a single top-level folder
                cands = [n for n in names if n.endswith("/iwf.json") and n.count("/") == 1]
                if cands:
                    prefix = cands[0][:-len("iwf.json")]
            p = Project._load_tree(lambda n: z.read(prefix + n), lambda n: (prefix + n) in names,
                                   lambda d: sorted(os.path.basename(f) for f in names
                                                    if f.startswith(prefix + d + "/") and f.lower().endswith(".png")))
        else:
            p = Project._load_iwf(open(path, "rb").read())
        p.path = path
        return p

    @staticmethod
    def _stem_key(stem: str):
        if stem.isdigit():
            return (0, int(stem))
        base = stem.split("_", 1)[-1]
        return (1, WEEK_ORDER.index(base) if base in WEEK_ORDER else 99, stem)

    @staticmethod
    def _load_tree(read, exists, listpng) -> "Project":
        p = Project()
        man = json.loads(read("iwf.json").decode("utf-8"))
        p._adopt_manifest(man)
        fonts = json.loads(read("font.json").decode("utf-8")) if exists("font.json") else {"item": []}
        p.fontsets = fonts.get("item", [])

        def img(name):
            try:
                return Image.open(io.BytesIO(read(name))).convert("RGBA")
            except Exception as e:                                       # missing / corrupt
                p.load_warnings.append("could not read %s (%s)" % (name, e))
                return None
        for nm in dict.fromkeys([p.bkground, p.preview_name, *p.used_hand_images()]):
            im = img(nm) if exists(nm) else None
            if im is None and not exists(nm):
                p.load_warnings.append("missing image: %s" % nm)
            if im is not None:
                p.images[nm] = im
        for f in p.fontsets:
            gl = {}
            for fn in sorted(listpng(f["name"]), key=lambda n: Project._stem_key(os.path.splitext(n)[0])):
                im = img("%s/%s" % (f["name"], fn))
                if im is not None:
                    gl[os.path.splitext(fn)[0]] = im
            p.glyphs[f["name"]] = gl
        return p

    @staticmethod
    def _load_iwf(data: bytes) -> "Project":
        p = Project()
        ents = dict(unpack_iwf(data))
        order = [n for n, _ in unpack_iwf(data)]
        p._adopt_manifest(json.loads(ents["iwf.json"].decode("utf-8")))
        p.fontsets = json.loads(ents["font.json"].decode("utf-8")).get("item", []) if "font.json" in ents else []
        want = {p.bkground, p.preview_name, *p.used_hand_images()}
        for nm in want:
            if nm in ents:
                try:
                    p.images[nm] = decode_raw(ents[nm])
                except Exception as e:
                    p.load_warnings.append("could not decode %s (%s)" % (nm, e))
            else:
                p.load_warnings.append("missing image entry: %s" % nm)
        names = sorted(p.fontset_names(), key=len, reverse=True)           # longest prefix wins
        for f in p.fontsets:
            p.glyphs[f["name"]] = {}
        for n in order:
            if n in want or n in ("iwf.json", "font.json"):
                continue
            for fn in names:
                if n.startswith(fn + "_"):
                    try:
                        p.glyphs[fn][n[len(fn) + 1:]] = decode_raw(ents[n])
                    except Exception as e:
                        p.load_warnings.append("could not decode %s (%s)" % (n, e))
                    break
            else:
                p.load_warnings.append("unrecognised entry ignored: %s" % n)
        for fn, gl in p.glyphs.items():
            p.glyphs[fn] = {k: gl[k] for k in sorted(gl, key=Project._stem_key)}
        return p

    def _adopt_manifest(self, man: dict):
        man = dict(man)
        self.items = [Widget(dict(i)) for i in man.pop("item", [])]
        self.bkground = man.pop("bkground", "background.png")
        self.meta = man

    # -------- saving -------------------------------------------------------------
    def _files(self) -> List[Tuple[str, bytes]]:
        def png(im):
            b = io.BytesIO()
            im.save(b, "PNG")
            return b.getvalue()
        out = [("iwf.json", dumps_json(self.manifest())), ("font.json", dumps_json(self.fonts_json()))]
        for nm in [self.preview_name, self.bkground, *self.used_hand_images()]:
            if nm in self.images and nm not in (n for n, _ in out):
                out.append((nm, png(self.images[nm])))
        for f in self.fontsets:
            for stem, im in self.glyphs.get(f["name"], {}).items():
                out.append(("%s/%s.png" % (f["name"], stem), png(im)))
        return out

    def save_dir(self, folder: str):
        for rel, blob in self._files():
            full = os.path.join(folder, rel)
            os.makedirs(os.path.dirname(full) or folder, exist_ok=True)
            with open(full, "wb") as f:
                f.write(blob)

    def save_zip(self, path: str):
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for rel, blob in self._files():
                z.writestr(rel, blob)

    # -------- compiling ----------------------------------------------------------
    def compile_entries(self, dither: bool = True) -> Tuple[List[Tuple[str, bytes]], List[str]]:
        notes: List[str] = []
        ents = [("iwf.json", dumps_json(self.manifest())), ("font.json", dumps_json(self.fonts_json()))]
        pv = self.images.get(self.preview_name)
        bg = self.images.get(self.bkground)
        if pv is None:
            raise ValueError("preview image '%s' is missing" % self.preview_name)
        if bg is None:
            raise ValueError("background image '%s' is missing" % self.bkground)
        ents.append((self.preview_name, encode_raw(pv, False, dither)))
        ents.append((self.bkground, encode_raw(bg, False, dither)))
        hands = self.used_hand_images()
        for nm in hands:
            if nm not in self.images:
                raise ValueError("hand image '%s' is missing" % nm)
            ents.append((nm, encode_raw(self.images[nm], True, dither)))
        if hands:
            notes.append("Analog hand images were written as RAW + alpha entries named after their file names. "
                         "That encoding is inferred, not verified on a watch.")
        for f in self.fontsets:
            gl = self.glyphs.get(f["name"], {})
            for stem in sorted(gl, key=Project._stem_key):
                ents.append(("%s_%s" % (f["name"], stem), encode_raw(gl[stem], True, dither)))
        return ents, notes

    def compile(self, path: str, dither: bool = True) -> List[str]:
        ents, notes = self.compile_entries(dither)
        blob = pack_iwf(ents)
        with open(path, "wb") as f:
            f.write(blob)
        return notes

    # -------- validation ---------------------------------------------------------
    def validate(self) -> List[Tuple[str, str, Optional[int]]]:
        """[(level, message, widget uid or None)], level in {'error','warning','info'}."""
        out: List[Tuple[str, str, Optional[int]]] = []
        bg = self.background
        if bg is None:
            out.append(("error", "Background image '%s' is missing." % self.bkground, None))
        elif bg.size != (SCREEN_W, SCREEN_H):
            out.append(("warning", "Background is %dx%d, the IDW20 screen is %dx%d." % (*bg.size, SCREEN_W, SCREEN_H), None))
        if self.preview_name not in self.images:
            out.append(("warning", "preview.png is missing (Tools > Generate preview.png).", None))
        names = self.fontset_names()
        if len(names) != len(set(names)):
            out.append(("error", "Duplicate glyph set names in font.json.", None))
        for n in names:
            if len(("%s_en_thur" % n).encode()) > MAX_ENTRY_NAME:
                out.append(("error", "Glyph set name '%s' is too long for an .iwf entry name." % n, None))
        for w in self.items:
            if w.is_analog:
                self._validate_hands(w, out)
                continue
            u = w.uid
            spec = w.spec
            if w.font not in self.glyphs:
                out.append(("error", "%s: glyph set '%s' does not exist." % (w.title, w.font), u))
                continue
            gl = self.glyphs[w.font]
            want = [s for s, _ in sample_stems(w.key)] if spec else []
            missing = [s for s in want if s not in gl]
            if missing:
                out.append(("error", "%s: glyph images missing in '%s': %s" % (w.title, w.font, ", ".join(missing)), u))
            if spec and w.geti("fontnum") != spec["fontnum"]:
                out.append(("warning", "%s: fontnum is %d, stock faces use %d." % (w.title, w.geti("fontnum"), spec["fontnum"]), u))
            if gl and spec:
                widest = _max_text_width(gl, spec["layout"])
                gh = max(im.height for im in gl.values())
                if widest and w.w < widest:
                    out.append(("warning", "%s: box is %d px wide but its widest value needs %d px." % (w.title, w.w, widest), u))
                if w.h != gh:
                    out.append(("info", "%s: box height %d differs from glyph height %d (stock faces match them)." % (w.title, w.h, gh), u))
            if w.x < 0 or w.y < 0 or w.x + w.w > SCREEN_W or w.y + w.h > SCREEN_H:
                out.append(("warning", "%s: box extends past the %dx%d screen." % (w.title, SCREEN_W, SCREEN_H), u))
        return out

    def _validate_hands(self, w: Widget, out):
        for k, pre in HAND_DEFS:
            nm = w.data.get(k)
            im = self.images.get(nm) if nm else None
            if im is None:
                out.append(("error", "Analog hands: %s hand image '%s' is missing." % (k, nm), w.uid))
                continue
            cx, cy = w.geti(pre + "centerx"), w.geti(pre + "centery")
            if not (0 <= cx < im.width and 0 <= cy < im.height):
                out.append(("warning", "Analog hands: %s pivot (%d,%d) lies outside its %dx%d image." % (k, cx, cy, *im.size), w.uid))


def _max_text_width(gl: Dict[str, Image.Image], layout: List[str]) -> int:
    digit_w = max([im.width for s, im in gl.items() if s.isdigit() and int(s) < 10] or [0])
    total = 0
    for tok in layout:
        if tok == "8":
            total += digit_w
        elif tok in gl:
            total += gl[tok].width
        elif tok.startswith("en_"):
            total += max([im.width for im in gl.values()] or [0])
    return total


max_text_width = _max_text_width


# =====================================================================================
#  Renderer
# =====================================================================================
def glyph_keys(w: Widget, st: SimState) -> List[str]:
    t = w.wtype
    if t == "time":
        return list("%02d" % st.display_hour) + ["10"] + list("%02d" % st.minute)
    if t == "hour":
        return list("%02d" % st.display_hour)
    if t == "min":
        return list("%02d" % st.minute)
    if t == "date":
        return list("%02d" % st.month) + ["10"] + list("%02d" % st.day)
    if t == "day":
        return list(str(st.day))
    if t == "week":
        return ["en_" + st.weekday_key]
    if t == "weather":
        return (["10"] if st.temp < 0 else []) + list(str(abs(st.temp))) + ["12" if st.temp_unit == "F" else "11"]
    if t == "battery":
        return list(str(st.battery)) + ["10"]
    if t == "step":
        return list(str(st.steps))
    if t == "calorie":
        return list(str(st.calories))
    return []


def layout_widget(project: Project, w: Widget, st: SimState) -> List[Tuple[Image.Image, int, int]]:
    gl = project.glyphs.get(w.font, {})
    seq = [gl[k] for k in glyph_keys(w, st) if k in gl]
    tw = sum(i.width for i in seq)
    ox = {"left": 0, "center": (w.w - tw) // 2, "right": w.w - tw}.get(w.data.get("align", "left"), 0)
    out, x = [], w.x + ox
    for im in seq:
        out.append((im, x, w.y))
        x += im.width
    return out


def hand_angle(kind: str, st: SimState) -> float:
    if kind == "hour":
        return ((st.hour % 12) + st.minute / 60.0 + st.second / 3600.0) * 30.0
    if kind == "minute":
        return (st.minute + st.second / 60.0) * 6.0
    return st.second * 6.0


def render_hand(canvas: Image.Image, img: Image.Image, pivot: Tuple[int, int], anchor: Tuple[int, int], deg: float):
    """Rotate ``img`` clockwise by ``deg`` around ``pivot`` (pixel in img) and place the pivot on ``anchor``."""
    w, h = img.size
    px, py = pivot
    r = int(math.ceil(max(math.hypot(px - cx, py - cy) for cx in (0, w) for cy in (0, h)))) + 2
    big = Image.new("RGBA", (2 * r, 2 * r), (0, 0, 0, 0))
    big.paste(img, (r - px, r - py))
    big = big.rotate(-deg, resample=Image.BICUBIC)                     # PIL rotates counter-clockwise
    _paste_clipped(canvas, big, anchor[0] - r, anchor[1] - r)


def _paste_clipped(dst: Image.Image, src: Image.Image, x: int, y: int):
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(dst.width, x + src.width), min(dst.height, y + src.height)
    if x1 <= x0 or y1 <= y0:
        return
    dst.alpha_composite(src.crop((x0 - x, y0 - y, x1 - x, y1 - y)), (x0, y0))


def render_face(project: Project, st: SimState, include_hidden: bool = False) -> Image.Image:
    """The full 320x385 face as the watch would draw it (an approximation: firmware decides formatting)."""
    face = Image.new("RGBA", (SCREEN_W, SCREEN_H), (0, 0, 0, 255))
    bg = project.background
    if bg is not None:
        _paste_clipped(face, bg, 0, 0)
    for w in project.items:
        if w.hidden and not include_hidden:
            continue
        if w.is_analog:
            for kind, pre in HAND_DEFS:                          # hour, minute, second: second on top
                im = project.images.get(w.data.get(kind, ""))
                if im is None:
                    continue
                render_hand(face, im, (w.geti(pre + "centerx"), w.geti(pre + "centery")),
                            (w.geti(pre + "anchorx", SCREEN_W // 2), w.geti(pre + "anchory", SCREEN_H // 2)),
                            hand_angle(kind, st))
        else:
            for im, x, y in layout_widget(project, w, st):
                _paste_clipped(face, im, x, y)
    return face


def bezel_image(size: Tuple[int, int] = (PREVIEW_W, PREVIEW_H)) -> Tuple[Image.Image, Image.Image]:
    """(ring RGB, interior mask L) of a synthetic rounded device outline."""
    s = 4
    w, h = size
    r = int(min(w, h) * 0.17)
    outer = Image.new("L", (w * s, h * s), 0)
    ImageDraw.Draw(outer).rounded_rectangle([0, 0, w * s - 1, h * s - 1], r * s, fill=255)
    inner = Image.new("L", (w * s, h * s), 0)
    ImageDraw.Draw(inner).rounded_rectangle([2 * s, 2 * s, w * s - 1 - 2 * s, h * s - 1 - 2 * s], (r - 2) * s, fill=255)
    outer, inner = outer.resize(size, Image.LANCZOS), inner.resize(size, Image.LANCZOS)
    ring = np.clip(np.asarray(outer, np.int32) - np.asarray(inner, np.int32), 0, 255) * 127 // 255
    return Image.fromarray(np.dstack([ring] * 3).astype(np.uint8), "RGB"), inner


def load_bezel(path: str) -> Tuple[Image.Image, Image.Image]:
    """(ring RGB, interior mask L) from a bezel picture such as 840.png (gray ring on black)."""
    border = Image.open(path).convert("RGB")
    if border.size != (PREVIEW_W, PREVIEW_H):
        raise ValueError("bezel image must be %dx%d" % (PREVIEW_W, PREVIEW_H))
    gray = np.asarray(border.convert("L"))
    allowed = (gray < 40).astype(np.uint8) * 255
    cur = Image.new("L", border.size, 0)
    cur.putpixel((PREVIEW_W // 2, PREVIEW_H // 2), 255)
    for _ in range(PREVIEW_W + PREVIEW_H):
        nxt = Image.fromarray(np.minimum(np.asarray(cur.filter(ImageFilter.MaxFilter(3))), allowed))
        if np.array_equal(np.asarray(nxt), np.asarray(cur)):
            break
        cur = nxt
    return border, cur.filter(ImageFilter.MaxFilter(5))


def render_preview_png(project: Project, st: SimState, bezel_path: Optional[str] = None) -> Image.Image:
    """272x324 preview.png: the face scaled to cover the bezel and clipped to its inside."""
    face = render_face(project, st).convert("RGB")
    k = max(PREVIEW_W / SCREEN_W, PREVIEW_H / SCREEN_H)
    sw, sh = round(SCREEN_W * k), round(SCREEN_H * k)
    face = face.resize((sw, sh), Image.LANCZOS)
    ox, oy = (sw - PREVIEW_W) // 2, (sh - PREVIEW_H) // 2
    face = face.crop((ox, oy, ox + PREVIEW_W, oy + PREVIEW_H))
    ring, inside = load_bezel(bezel_path) if bezel_path else bezel_image()
    f = np.asarray(face, np.float32) * (np.asarray(inside, np.float32) / 255)[..., None]
    out = np.maximum(f, np.asarray(ring, np.float32)).astype(np.uint8)
    return Image.fromarray(np.dstack([out, np.full(out.shape[:2], 255, np.uint8)]), "RGBA")


# =====================================================================================
#  Asset generators
# =====================================================================================
_FONT_CANDIDATES = [
    "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
]


def default_font_path() -> Optional[str]:
    return next((p for p in _FONT_CANDIDATES if os.path.exists(p)), None)


def _load_font(path: Optional[str], size: int):
    if path:
        return ImageFont.truetype(path, size)
    try:
        return ImageFont.load_default(size)                    # Pillow >= 10.1
    except TypeError:
        return ImageFont.load_default()


@dataclass
class GlyphStyle:
    font_path: Optional[str] = None
    ink: int = 24                                  # height of a digit in pixels
    top: Tuple[int, int, int] = (255, 255, 255)    # vertical gradient of the fill
    bottom: Tuple[int, int, int] = (255, 255, 255)
    outline: Optional[Tuple[int, int, int]] = None
    outline_px: int = 0
    glow: Optional[Tuple[int, int, int]] = None
    glow_px: int = 0


def generate_glyph_set(charset: List[Tuple[str, str]], style: GlyphStyle) -> Dict[str, Image.Image]:
    """Render ``[(stem, text)]`` with a TTF into RGBA glyph images that share one cell height."""
    SS = 3
    big = _load_font(style.font_path, 1000)
    l, t, r, b = big.getbbox("0", anchor="ls")
    size = max(6, round(1000 * style.ink * SS / max(1, (b - t))))
    font = _load_font(style.font_path, size)
    _, t0, _, b0 = font.getbbox("0", anchor="ls")
    pad = max(2, style.glow_px * 2 + style.outline_px + 2)
    H = style.ink + 2 * pad
    boxes = {s: font.getbbox(txt, anchor="ls") for s, txt in charset}
    is_week = all(s.startswith("en_") for s, _ in charset)
    digit_w = max([(bx[2] - bx[0]) for s, bx in boxes.items() if s.isdigit() and int(s) < 10] or [0])
    week_w = max([(bx[2] - bx[0]) for bx in boxes.values()] or [0])
    out = {}
    for stem, text in charset:
        bx = boxes[stem]
        ink_w = (week_w if is_week else digit_w if (stem.isdigit() and int(stem) < 10) else bx[2] - bx[0])
        cw = int(math.ceil(ink_w / SS)) + 2 * pad
        W, Hh = cw * SS, H * SS
        base = Hh / 2 - (t0 + b0) / 2
        x = (pad * SS - bx[0]) if is_week else (W / 2 - (bx[0] + bx[2]) / 2)
        m = Image.new("L", (W, Hh), 0)
        ImageDraw.Draw(m).text((x, base), text, font=font, fill=255, anchor="ls")
        layers = Image.new("RGBA", (W, Hh), (0, 0, 0, 0))
        if style.glow and style.glow_px:
            ga = m.filter(ImageFilter.GaussianBlur(style.glow_px * SS))
            ga = ga.point(lambda v: min(255, int(v * 2.2)))
            layers.alpha_composite(Image.merge("RGBA", [Image.new("L", (W, Hh), c) for c in style.glow] + [ga]))
        if style.outline and style.outline_px:
            om = m.filter(ImageFilter.MaxFilter(2 * style.outline_px * SS + 1))
            layers.alpha_composite(Image.merge("RGBA", [Image.new("L", (W, Hh), c) for c in style.outline] + [om]))
        ys = np.clip((np.arange(Hh) - (base + t0)) / max(1, (b0 - t0)), 0, 1)[:, None, None]
        fill = (np.array(style.top, np.float32) * (1 - ys) + np.array(style.bottom, np.float32) * ys)
        fill = np.broadcast_to(fill, (Hh, W, 3)).astype(np.uint8)
        layers.alpha_composite(Image.merge("RGBA", [Image.fromarray(fill[..., i]) for i in range(3)] + [m]))
        out[stem] = layers.resize((cw, H), Image.LANCZOS)
    return out


def make_default_hand(kind: str, color: Tuple[int, int, int] = (255, 255, 255)) -> Tuple[Image.Image, Tuple[int, int]]:
    """A plain rounded hand (tip up).  Returns (image, pivot)."""
    length, tail, width = {"hour": (92, 18, 12), "minute": (132, 22, 9), "second": (150, 34, 3)}[kind]
    pad = 4
    W, H = width + 2 * pad + 8, length + tail + 2 * pad
    s = 4
    im = Image.new("RGBA", (W * s, H * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx = W * s // 2
    top, bot = pad * s, (pad + length + tail) * s
    d.rounded_rectangle([cx - width * s // 2, top, cx + width * s // 2, bot], radius=width * s // 2, fill=color + (255,))
    hub = (width + 4) * s // 2 if kind != "second" else 5 * s
    py = (pad + length) * s
    d.ellipse([cx - hub, py - hub, cx + hub, py + hub], fill=color + (255,))
    d.ellipse([cx - hub // 2, py - hub // 2, cx + hub // 2, py + hub // 2], fill=(20, 20, 20, 255))
    return im.resize((W, H), Image.LANCZOS), (W // 2, pad + length)
