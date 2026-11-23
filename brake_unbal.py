"""
Brake Unbal Monitor
- ค้นหา window ชื่อ "Brakes" อัตโนมัติ (รองรับ DPI Scaling และหลายจอ)
- อ่านตัวเลข 7-Segment (Cyan/Green/White) ได้ในตัว ไม่ต้องพึ่ง Tesseract
- มีโหมด Preview ภาพที่แคปและ mask เพื่อตรวจสอบความถูกต้องบนเครื่องจริง
- แสดง Unbal% แบบ Always on Top + Save/Load config จาก config.json
"""

import ctypes
import json
import os
import re
import sys
import time
import tkinter as tk
from tkinter import messagebox

# ── DPI Awareness (ต้องเรียกก่อนสร้าง Tk window) ────────────────────────────
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-Monitor DPI Aware
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

try:
    from PIL import Image, ImageEnhance, ImageGrab, ImageTk
    import win32gui
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

try:
    import pytesseract
    HAS_PYTESSERACT = True
except ImportError:
    HAS_PYTESSERACT = False

# ── Config ───────────────────────────────────────────────────────────────────
TARGET_WINDOW_TITLE = "Brakes"
APP_TITLE = "Brake Unbal"
PASS_THRESHOLD = 25.00
SCAN_INTERVAL_MS = 350   # อ่านค่าเร็วขึ้น (~3 ครั้ง/วินาที) เพราะ 7-segment decoder ทำงานใน <5ms
CONFIG_FILE = os.path.join(
    os.path.dirname(sys.executable if getattr(sys, "frozen", False) else __file__),
    "config.json",
)

# Tesseract path (optional fallback สำหรับฟอนต์ทั่วไปที่ไม่ใช่ 7-segment)
TESS_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ── Colors ───────────────────────────────────────────────────────────────────
BG     = "#0d0d0d"
GREEN  = "#00ff41"
RED    = "#ff4444"
YELLOW = "#ffd700"
GRAY   = "#888888"
PANEL  = "#1a1a1a"

# ── 7-Segment Lookup Table: (a, b, c, d, e, f, g) ────────────────────────────
SEG_TABLE = {
    (1, 1, 1, 1, 1, 1, 0): "0",
    (0, 1, 1, 0, 0, 0, 0): "1",
    (0, 0, 0, 0, 1, 1, 0): "1",
    (1, 1, 0, 1, 1, 0, 1): "2",
    (1, 1, 1, 1, 0, 0, 1): "3",
    (0, 1, 1, 0, 0, 1, 1): "4",
    (1, 0, 1, 1, 0, 1, 1): "5",
    (1, 0, 1, 1, 1, 1, 1): "6",
    (0, 0, 1, 1, 1, 1, 1): "6",
    (1, 1, 1, 0, 0, 0, 0): "7",
    (1, 1, 1, 0, 0, 1, 0): "7",
    (1, 1, 1, 1, 1, 1, 1): "8",
    (1, 1, 1, 1, 0, 1, 1): "9",
    (1, 1, 1, 0, 0, 1, 1): "9",
}


# ── Helpers: Window & Screen ─────────────────────────────────────────────────
def get_virtual_screen_rect():
    """คืน (x, y, width, height) ของพื้นที่หน้าจอทั้งหมด (รองรับหลายจอ)"""
    u32 = ctypes.windll.user32
    vx = u32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
    vy = u32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
    vw = u32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
    vh = u32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
    return vx, vy, vw, vh


def find_window(title):
    """หา (hwnd, window_title) ของ window ที่ตรงกับ title (เน้นตรงชื่อก่อน)"""
    exact = []
    partial = []
    target_low = title.strip().lower()
    app_low = APP_TITLE.lower()

    def enum_cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        t = win32gui.GetWindowText(hwnd).strip()
        if not t:
            return
        t_low = t.lower()
        if t_low == app_low:
            return
        if t_low == target_low:
            exact.append((hwnd, t))
        elif target_low in t_low:
            partial.append((hwnd, t))

    win32gui.EnumWindows(enum_cb, None)
    if exact:
        return exact[0]
    if partial:
        partial.sort(key=lambda item: len(item[1]))
        return partial[0]
    return None, None


def get_window_rect(hwnd):
    """คืน (left, top, right, bottom) ของ window"""
    return win32gui.GetWindowRect(hwnd)


def capture_region(hwnd, rel_rect):
    """
    ถ่ายภาพ region สัมพัทธ์กับ window (รองรับหลายจอ)
    rel_rect = (x1, y1, x2, y2) relative to window top-left
    """
    wx, wy, _, _ = get_window_rect(hwnd)
    abs_rect = (
        int(wx + rel_rect[0]),
        int(wy + rel_rect[1]),
        int(wx + rel_rect[2]),
        int(wy + rel_rect[3]),
    )
    if abs_rect[2] <= abs_rect[0] or abs_rect[3] <= abs_rect[1]:
        raise ValueError("Invalid capture region")
    return ImageGrab.grab(bbox=abs_rect, all_screens=True)


# ── 7-Segment Decoder (Pure Python + Pillow) ─────────────────────────────────
def _otsu_threshold(values):
    hist = [0] * 256
    for v in values:
        hist[v] += 1
    total = len(values)
    if total == 0:
        return 128
    sum_all = sum(i * hist[i] for i in range(256))
    sum_b = 0
    w_b = 0
    max_var = -1.0
    best_t = 128
    for t in range(256):
        w_b += hist[t]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += t * hist[t]
        m_b = sum_b / w_b
        m_f = (sum_all - sum_b) / w_f
        var_between = w_b * w_f * (m_b - m_f) ** 2
        if var_between > max_var:
            max_var = var_between
            best_t = t
    return best_t


def make_digit_mask(img):
    """
    สร้าง binary mask (list[list[int]]) และภาพ mask (PIL.Image 'L')
    รองรับทั้งตัวเลข 7-Segment สีฟ้า/เขียวบนพื้นเข้ม (โปรแกรม Brakes จริง)
    และตัวเลขขาว/เทาบนพื้นเข้มทั่วไป
    """
    rgb = img.convert("RGB")
    w, h = rgb.size
    raw = rgb.tobytes()
    n = w * h
    if n == 0:
        return None, None, "empty"

    rs = raw[0::3]
    gs = raw[1::3]
    bs = raw[2::3]

    # คะแนนสีเขียว/ฟ้า (G - R): แยกตัวเลข Cyan/Green ออกจากทั้งพื้นดำและขอบเทา/ฟ้าอ่อน
    gr_vals = [g - r if g > r else 0 for r, g in zip(rs, gs)]
    sorted_gr = sorted(gr_vals)
    p98_gr = sorted_gr[min(n - 1, int(n * 0.98))]

    if p98_gr >= 45:
        t = max(_otsu_threshold(gr_vals), 30)
        flat = [1 if (gr_vals[i] > t and gs[i] >= 80) else 0 for i in range(n)]
        mode = f"7seg-cyan (t={t})"
    else:
        # โหมดขาวดำ / สีอื่นบนพื้นเข้ม
        luma = [(77 * r + 150 * g + 29 * b) >> 8 for r, g, b in zip(rs, gs, bs)]
        sorted_luma = sorted(luma)
        p02 = sorted_luma[int(n * 0.02)]
        p98 = sorted_luma[min(n - 1, int(n * 0.98))]
        if p98 - p02 < 35:
            # พื้นเรียบไม่มีตัวเลข
            empty_mask = [[0] * w for _ in range(h)]
            empty_img = Image.new("L", (w, h), 0)
            return empty_mask, empty_img, "blank"
        t = _otsu_threshold(luma)
        bright_count = sum(1 for v in luma if v > t)
        invert = bright_count > n * 0.65
        if invert:
            flat = [1 if v < t else 0 for v in luma]
        else:
            flat = [1 if v > t else 0 for v in luma]
        mode = f"luma (t={t})"

    mask = [flat[y * w:(y + 1) * w] for y in range(h)]
    mask_bytes = bytes(255 if v else 0 for v in flat)
    mask_img = Image.frombytes("L", (w, h), mask_bytes)
    return mask, mask_img, mode


def decode_7seg(img):
    """
    อ่านตัวเลข 7-segment จากภาพ
    คืน (float หรือ None, mask_img, debug_text)
    """
    mask, mask_img, mode = make_digit_mask(img)
    if mask is None:
        return None, mask_img, mode

    h = len(mask)
    w = len(mask[0]) if h else 0
    if w < 5 or h < 8:
        return None, mask_img, f"{mode}: too small"

    # 1. หาแถบแนวตั้งหลักของตัวเลข (เชื่อมช่องว่างกลางของเลข 1 ด้วย)
    row_counts = [sum(mask[y]) for y in range(h)]
    max_rc = max(row_counts) if row_counts else 0
    if max_rc == 0:
        return None, mask_img, f"{mode}: empty"

    r_thresh = max(1, int(max_rc * 0.08))
    max_vgap = max(3, int(h * 0.14))
    vbands = []
    in_band = False
    b_start = 0
    vgap = 0
    for y in range(h):
        if row_counts[y] >= r_thresh:
            if not in_band:
                b_start = y
                in_band = True
            vgap = 0
        else:
            if in_band:
                vgap += 1
                if vgap > max_vgap:
                    vbands.append((b_start, y - vgap))
                    in_band = False
    if in_band:
        vbands.append((b_start, h - 1 - vgap))

    if not vbands:
        return None, mask_img, f"{mode}: no vband"

    # เลือกแถบแนวตั้งที่มีจำนวนพิกเซลรวมมากที่สุด
    y1, y2 = max(vbands, key=lambda b: sum(row_counts[b[0]:b[1] + 1]))
    dh = y2 - y1 + 1
    if dh < 8:
        return None, mask_img, f"{mode}: dh={dh}"

    # 2. แยกหลักตัวเลขตามแนวนอน (column projection)
    col_counts = [sum(mask[y][x] for y in range(y1, y2 + 1)) for x in range(w)]
    c_thresh = max(1, int(dh * 0.04))
    max_hgap = max(1, int(dh * 0.03))

    runs = []
    in_run = False
    start = 0
    gap = 0
    for x in range(w):
        if col_counts[x] >= c_thresh:
            if not in_run:
                start = x
                in_run = True
            gap = 0
        else:
            if in_run:
                gap += 1
                if gap > max_hgap:
                    runs.append((start, x - gap))
                    in_run = False
    if in_run:
        runs.append((start, w - 1 - gap))

    # กรอง noise และแยกหลักที่ติดกัน (ถ้ากว้างเกิน 0.95 * dh)
    clean_runs = []
    for rx1, rx2 in runs:
        rw = rx2 - rx1 + 1
        if rw < max(2, int(dh * 0.08)):
            continue
        run_ys = [y for y in range(y1, y2 + 1) if any(mask[y][rx1:rx2 + 1])]
        if not run_ys:
            continue
        run_h = run_ys[-1] - run_ys[0] + 1
        if run_h < dh * 0.55:
            continue
        if rw > dh * 1.05:
            mid_lo = rx1 + int(rw * 0.30)
            mid_hi = rx1 + int(rw * 0.70)
            split_x = min(range(mid_lo, mid_hi + 1), key=lambda x: col_counts[x])
            if col_counts[split_x] <= max(2, int(dh * 0.12)):
                if split_x - 1 > rx1:
                    clean_runs.append((rx1, split_x - 1))
                if rx2 > split_x + 1:
                    clean_runs.append((split_x + 1, rx2))
                continue
        clean_runs.append((rx1, rx2))

    if not clean_runs:
        return None, mask_img, f"{mode}: no digits"

    # 3. ตรวจ 7 segments ของแต่ละหลัก
    def zone_fill(bx1, by1, bx2, by2, fx1, fy1, fx2, fy2):
        bw = bx2 - bx1 + 1
        bh = by2 - by1 + 1
        zx1 = max(bx1, min(bx2, bx1 + int(bw * fx1)))
        zx2 = max(bx1, min(bx2, bx1 + max(int(bw * fx2), int(bw * fx1) + 1)))
        zy1 = max(by1, min(by2, by1 + int(bh * fy1)))
        zy2 = max(by1, min(by2, by1 + max(int(bh * fy2), int(bh * fy1) + 1)))
        total = (zy2 - zy1 + 1) * (zx2 - zx1 + 1)
        if total <= 0:
            return 0.0
        lit = 0
        for yy in range(zy1, zy2 + 1):
            row = mask[yy]
            for xx in range(zx1, zx2 + 1):
                lit += row[xx]
        return lit / total

    digits = []
    for rx1, rx2 in clean_runs:
        rw = rx2 - rx1 + 1
        ratio = rw / dh
        if ratio < 0.36:
            top_f = zone_fill(rx1, y1, rx2, y2, 0.0, 0.15, 1.0, 0.45)
            bot_f = zone_fill(rx1, y1, rx2, y2, 0.0, 0.55, 1.0, 0.85)
            if top_f > 0.25 and bot_f > 0.25:
                digits.append("1")
                continue

        scores = (
            zone_fill(rx1, y1, rx2, y2, 0.28, 0.00, 0.72, 0.22),  # a (top)
            zone_fill(rx1, y1, rx2, y2, 0.68, 0.18, 1.00, 0.45),  # b (top-right)
            zone_fill(rx1, y1, rx2, y2, 0.68, 0.55, 1.00, 0.82),  # c (bot-right)
            zone_fill(rx1, y1, rx2, y2, 0.28, 0.78, 0.72, 1.00),  # d (bottom)
            zone_fill(rx1, y1, rx2, y2, 0.00, 0.55, 0.32, 0.82),  # e (bot-left)
            zone_fill(rx1, y1, rx2, y2, 0.00, 0.18, 0.32, 0.45),  # f (top-left)
            zone_fill(rx1, y1, rx2, y2, 0.28, 0.40, 0.72, 0.60),  # g (middle)
        )
        bits = tuple(1 if s >= 0.28 else 0 for s in scores)
        ch = SEG_TABLE.get(bits)
        if ch is None:
            return None, mask_img, f"{mode}: unknown seg"
        digits.append(ch)

    text = "".join(digits)
    return float(text), mask_img, f"7seg: {text}"


def ocr_fallback(img):
    """Fallback ด้วย Tesseract (เฉพาะกรณีฟอนต์ธรรมดาและเครื่องมี Tesseract)"""
    if not HAS_PYTESSERACT or not os.path.exists(TESS_PATH):
        return None
    try:
        pytesseract.pytesseract.tesseract_cmd = TESS_PATH
        g = img.resize((img.width * 3, img.height * 3), Image.LANCZOS).convert("L")
        g = ImageEnhance.Contrast(g).enhance(3.0)
        # แปลงเป็นตัวอักษรดำบนพื้นขาว + ขอบขาว เพื่อให้ Tesseract อ่านแม่นขึ้น
        bin_img = g.point(lambda p: 0 if p > 110 else 255)
        padded = Image.new("L", (bin_img.width + 20, bin_img.height + 20), 255)
        padded.paste(bin_img, (10, 10))
        cfg = "--psm 7 -c tessedit_char_whitelist=0123456789"
        text = pytesseract.image_to_string(padded, config=cfg).strip()
        nums = re.findall(r"\d+", text)
        if nums:
            return float(nums[0])
    except Exception:
        pass
    return None


def read_number(img):
    """อ่านตัวเลขจากภาพ: ใช้ 7-segment decoder ก่อน แล้วค่อย fallback Tesseract"""
    val, mask_img, info = decode_7seg(img)
    if val is not None:
        return val, mask_img, info
    fb = ocr_fallback(img)
    if fb is not None:
        return fb, mask_img, f"ocr: {int(fb)}"
    return None, mask_img, info


def calc_unbal(lf, rf):
    if lf is None or rf is None:
        return None
    mx = max(lf, rf)
    mn = min(lf, rf)
    if mx == 0:
        return None
    return (mx - mn) / mx * 100


def load_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(data):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ── Region Selector ──────────────────────────────────────────────────────────
class RegionSelector:
    """overlay เต็มพื้นที่ทุกหน้าจอให้ลากกรอบเลือก region"""

    def __init__(self, root, title, callback, on_cancel=None):
        self.callback = callback
        self.on_cancel = on_cancel
        self.start_x = self.start_y = 0
        self.rect_id = None

        vx, vy, vw, vh = get_virtual_screen_rect()
        self.vx = vx
        self.vy = vy

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.geometry(f"{vw}x{vh}+{vx}+{vy}")
        self.win.attributes("-alpha", 0.3)
        self.win.attributes("-topmost", True)
        self.win.configure(bg="black")
        self.win.title(title)

        self.canvas = tk.Canvas(
            self.win, cursor="cross", bg="black", highlightthickness=0
        )
        self.canvas.pack(fill="both", expand=True)

        lbl = tk.Label(
            self.win,
            text=f"ลากกรอบครอบตัวเลข  {title}  แล้วปล่อย  (กด Esc เพื่อยกเลิก)",
            font=("Tahoma", 16, "bold"),
            bg="black",
            fg="#00ff41",
        )
        lbl.place(relx=0.5, rely=0.05, anchor="center")

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.win.bind("<Escape>", self._cancel)
        self.win.focus_force()

    def _cancel(self, _e=None):
        self.win.destroy()
        if self.on_cancel:
            self.on_cancel()

    def on_press(self, e):
        self.start_x, self.start_y = e.x_root, e.y_root
        if self.rect_id:
            self.canvas.delete(self.rect_id)

    def on_drag(self, e):
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        cx = e.x_root - self.vx
        cy = e.y_root - self.vy
        sx = self.start_x - self.vx
        sy = self.start_y - self.vy
        self.rect_id = self.canvas.create_rectangle(
            sx, sy, cx, cy, outline="#00ff41", width=2
        )

    def on_release(self, e):
        x1, y1 = min(self.start_x, e.x_root), min(self.start_y, e.y_root)
        x2, y2 = max(self.start_x, e.x_root), max(self.start_y, e.y_root)
        self.win.destroy()
        if x2 - x1 < 8 or y2 - y1 < 8:
            if self.on_cancel:
                self.on_cancel()
            return
        self.callback((x1, y1, x2, y2))


# ── Main App ─────────────────────────────────────────────────────────────────
class BrakeUnbalApp:
    THUMB_W = 116
    THUMB_H = 54
    UI_FONT = "Tahoma"

    def __init__(self, root):
        self.root = root
        self.config = load_config()
        self.lf_region = self.config.get("lf_region")
        self.rf_region = self.config.get("rf_region")
        self.show_preview = False
        self._preview_refs = []
        self._blank_thumb = tk.PhotoImage(width=self.THUMB_W, height=self.THUMB_H)
        self._build_ui()
        self._start_scan()

    def _fit_window(self):
        self.root.update_idletasks()
        req_w = max(270, self.root.winfo_reqwidth())
        req_h = self.root.winfo_reqheight()
        self.root.geometry(f"{req_w}x{req_h}")

    # ── UI ───────────────────────────────────────────────────────────────────
    def _build_ui(self):
        r = self.root
        r.title(APP_TITLE)
        r.resizable(False, False)
        r.attributes("-topmost", True)
        r.configure(bg=BG)

        # Header bar
        bar = tk.Frame(r, bg="#111111", height=30)
        bar.pack(fill="x")
        tk.Label(
            bar,
            text="🔧 Brake Unbal",
            font=(self.UI_FONT, 9, "bold"),
            bg="#111111",
            fg=YELLOW,
        ).pack(side="left", padx=10, pady=5)

        # Status
        self.status_var = tk.StringVar(value="กำลังหา Brakes window...")
        tk.Label(
            r,
            textvariable=self.status_var,
            font=(self.UI_FONT, 9),
            bg=BG,
            fg=GRAY,
            wraplength=245,
        ).pack(pady=(8, 0), padx=8)

        # LF / RF row
        row = tk.Frame(r, bg=BG)
        row.pack(pady=8, padx=10)
        self._lf_val = tk.StringVar(value="---")
        self._rf_val = tk.StringVar(value="---")
        for label, var in [("LF", self._lf_val), ("RF", self._rf_val)]:
            col = tk.Frame(
                row,
                bg=PANEL,
                bd=0,
                highlightbackground="#333",
                highlightthickness=1,
            )
            col.pack(side="left", padx=6)
            tk.Label(
                col, text=label, font=(self.UI_FONT, 8, "bold"), bg=PANEL, fg=GRAY
            ).pack(pady=(4, 0))
            tk.Label(
                col,
                textvariable=var,
                font=("Consolas", 16, "bold"),
                bg=PANEL,
                fg=GREEN,
                width=5,
            ).pack(padx=10, pady=(0, 5))

        # Unbal big display
        tk.Label(r, text="Unbal", font=(self.UI_FONT, 9), bg=BG, fg=GRAY).pack()
        self._unbal_var = tk.StringVar(value="--.-- %")
        self._unbal_lbl = tk.Label(
            r,
            textvariable=self._unbal_var,
            font=("Consolas", 32, "bold"),
            bg=BG,
            fg=GRAY,
        )
        self._unbal_lbl.pack(pady=2, padx=12)

        # Pass/Fail
        self._result_var = tk.StringVar(value="")
        self._result_lbl = tk.Label(
            r,
            textvariable=self._result_var,
            font=(self.UI_FONT, 11, "bold"),
            bg=BG,
            fg=GRAY,
            padx=14,
            pady=4,
        )
        self._result_lbl.pack(pady=(2, 4))

        # Buttons
        btn_frame = tk.Frame(r, bg=BG)
        btn_frame.pack(pady=(4, 10), padx=10)
        tk.Button(
            btn_frame,
            text="⚙ Setup Region",
            font=(self.UI_FONT, 8, "bold"),
            bg="#333",
            fg="white",
            relief="flat",
            padx=10,
            pady=4,
            cursor="hand2",
            command=self._start_setup,
        ).pack(side="left", padx=4)

        self._preview_btn = tk.Button(
            btn_frame,
            text="👁 Preview",
            font=(self.UI_FONT, 8, "bold"),
            bg="#252525",
            fg="#cccccc",
            relief="flat",
            padx=10,
            pady=4,
            cursor="hand2",
            command=self._toggle_preview,
        )
        self._preview_btn.pack(side="left", padx=4)

        # Preview Panel (hidden by default)
        self._preview_frame = tk.Frame(
            r, bg="#141414", highlightbackground="#333", highlightthickness=1
        )
        self._prev_info_var = tk.StringVar(value="")
        tk.Label(
            self._preview_frame,
            textvariable=self._prev_info_var,
            font=("Consolas", 8),
            bg="#141414",
            fg="#aaaaaa",
        ).pack(pady=(6, 4), padx=6)

        grid = tk.Frame(self._preview_frame, bg="#141414")
        grid.pack(padx=8, pady=(0, 10))

        tk.Label(grid, text="LF Crop", font=(self.UI_FONT, 8), bg="#141414", fg=GRAY).grid(row=0, column=0, padx=5, pady=(0, 2))
        tk.Label(grid, text="RF Crop", font=(self.UI_FONT, 8), bg="#141414", fg=GRAY).grid(row=0, column=1, padx=5, pady=(0, 2))
        self._lf_crop_lbl = tk.Label(grid, bg="#000", image=self._blank_thumb, width=self.THUMB_W, height=self.THUMB_H)
        self._lf_crop_lbl.grid(row=1, column=0, padx=5, pady=(0, 6))
        self._rf_crop_lbl = tk.Label(grid, bg="#000", image=self._blank_thumb, width=self.THUMB_W, height=self.THUMB_H)
        self._rf_crop_lbl.grid(row=1, column=1, padx=5, pady=(0, 6))

        tk.Label(grid, text="LF Mask", font=(self.UI_FONT, 8), bg="#141414", fg=GRAY).grid(row=2, column=0, padx=5, pady=(0, 2))
        tk.Label(grid, text="RF Mask", font=(self.UI_FONT, 8), bg="#141414", fg=GRAY).grid(row=2, column=1, padx=5, pady=(0, 2))
        self._lf_mask_lbl = tk.Label(grid, bg="#000", image=self._blank_thumb, width=self.THUMB_W, height=self.THUMB_H)
        self._lf_mask_lbl.grid(row=3, column=0, padx=5, pady=(0, 2))
        self._rf_mask_lbl = tk.Label(grid, bg="#000", image=self._blank_thumb, width=self.THUMB_W, height=self.THUMB_H)
        self._rf_mask_lbl.grid(row=3, column=1, padx=5, pady=(0, 2))

        if not (self.lf_region and self.rf_region):
            self.status_var.set("⚠ กรุณากด Setup Region ก่อน")

        self._fit_window()

    def _toggle_preview(self):
        self.show_preview = not self.show_preview
        if self.show_preview:
            self._preview_frame.pack(fill="x", padx=10, pady=(0, 10))
            self._preview_btn.config(bg="#1f4d2e", fg=GREEN)
        else:
            self._preview_frame.pack_forget()
            self._preview_btn.config(bg="#252525", fg="#cccccc")
        self._fit_window()

    def _update_preview(self, lf_img, lf_mask, rf_img, rf_mask, info_text):
        if not self.show_preview:
            return
        self._prev_info_var.set(info_text)
        refs = []
        for img, lbl in [
            (lf_img, self._lf_crop_lbl),
            (rf_img, self._rf_crop_lbl),
            (lf_mask, self._lf_mask_lbl),
            (rf_mask, self._rf_mask_lbl),
        ]:
            if img is not None:
                thumb = img.copy()
                thumb.thumbnail((self.THUMB_W, self.THUMB_H), Image.NEAREST)
                tk_img = ImageTk.PhotoImage(thumb)
                lbl.config(image=tk_img, width=self.THUMB_W, height=self.THUMB_H)
                refs.append(tk_img)
        self._preview_refs = refs

    # ── Setup Flow ───────────────────────────────────────────────────────────
    def _start_setup(self):
        if not HAS_DEPS:
            messagebox.showerror(
                "Error",
                "ไม่พบ dependencies\nกรุณาติดตั้ง: pip install pillow pywin32",
            )
            return
        hwnd, _ = find_window(TARGET_WINDOW_TITLE)
        if not hwnd:
            messagebox.showwarning(
                "ไม่พบ Window",
                f'ไม่พบ window ชื่อ "{TARGET_WINDOW_TITLE}"\nกรุณาเปิดโปรแกรมทดสอบเบรกก่อน',
            )
            return
        self.root.withdraw()
        time.sleep(0.25)
        RegionSelector(
            self.root,
            "LF  (ซ้ายหน้า)",
            self._on_lf_selected,
            on_cancel=self._on_setup_cancel,
        )

    def _on_setup_cancel(self):
        self.root.deiconify()

    def _on_lf_selected(self, abs_rect):
        self._pending_lf = abs_rect
        time.sleep(0.2)
        RegionSelector(
            self.root,
            "RF  (ขวาหน้า)",
            self._on_rf_selected,
            on_cancel=self._on_setup_cancel,
        )

    def _on_rf_selected(self, abs_rect):
        self.root.deiconify()
        hwnd, _ = find_window(TARGET_WINDOW_TITLE)
        if not hwnd:
            messagebox.showerror("Error", "ไม่พบ window ขณะ save config")
            return
        wx, wy, _, _ = get_window_rect(hwnd)

        def to_rel(a):
            return [a[0] - wx, a[1] - wy, a[2] - wx, a[3] - wy]

        self.lf_region = to_rel(self._pending_lf)
        self.rf_region = to_rel(abs_rect)
        save_config({"lf_region": self.lf_region, "rf_region": self.rf_region})
        self.status_var.set("✔ Setup เสร็จแล้ว — กำลังอ่านค่า...")

    # ── Scan Loop ────────────────────────────────────────────────────────────
    def _start_scan(self):
        if not HAS_DEPS:
            self.status_var.set("⚠ ไม่พบ dependencies")
            return
        self._scan_loop()

    def _scan_loop(self):
        try:
            self._do_scan()
        except Exception as e:
            self.status_var.set(f"Error: {e}")
        self.root.after(SCAN_INTERVAL_MS, self._scan_loop)

    def _do_scan(self):
        if not self.lf_region or not self.rf_region:
            self.status_var.set("⚠ กรุณากด Setup Region ก่อน")
            return

        hwnd, win_title = find_window(TARGET_WINDOW_TITLE)
        if not hwnd:
            self.status_var.set(f'รอ "{TARGET_WINDOW_TITLE}" window...')
            self._set_values(None, None)
            return

        try:
            lf_img = capture_region(hwnd, self.lf_region)
            rf_img = capture_region(hwnd, self.rf_region)
        except Exception:
            self.status_var.set("capture ไม่ได้ — window อาจถูก minimize")
            return

        lf, lf_mask, lf_info = read_number(lf_img)
        rf, rf_mask, rf_info = read_number(rf_img)
        self._set_values(lf, rf)
        self._update_preview(
            lf_img, lf_mask, rf_img, rf_mask, f"{win_title} | {lf_info} / {rf_info}"
        )

        if lf is not None and rf is not None:
            self.status_var.set("● กำลังอ่านค่า...")
        else:
            self.status_var.set("อ่านค่าไม่ได้ — กด Preview เพื่อตรวจกรอบ")

    def _set_values(self, lf, rf):
        self._lf_val.set(str(int(lf)) if lf is not None else "---")
        self._rf_val.set(str(int(rf)) if rf is not None else "---")
        unbal = calc_unbal(lf, rf)
        if unbal is None:
            self._unbal_var.set("--.-- %")
            self._unbal_lbl.config(fg=GRAY)
            self._result_var.set("")
            self._result_lbl.config(bg=BG)
        else:
            self._unbal_var.set(f"{unbal:.2f} %")
            if unbal <= PASS_THRESHOLD:
                self._unbal_lbl.config(fg=GREEN)
                self._result_var.set("✔  ผ่าน")
                self._result_lbl.config(fg=GREEN, bg="#0a2e0a")
            else:
                self._unbal_lbl.config(fg=RED)
                self._result_var.set("✘  ไม่ผ่าน")
                self._result_lbl.config(fg=RED, bg="#2e0a0a")


# ── Entry Point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    app = BrakeUnbalApp(root)
    root.mainloop()
