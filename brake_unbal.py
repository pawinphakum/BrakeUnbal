"""
Brake Unbal Monitor
- ค้นหา window ชื่อ "Brakes" อัตโนมัติ
- OCR อ่านค่า LF / RF จาก region ที่ setup ครั้งแรก
- แสดง Unbal% แบบ Always on Top
- Save/Load config จาก config.json
"""

import tkinter as tk
from tkinter import messagebox
import json
import os
import sys
import threading
import time
import re

try:
    from PIL import ImageGrab, Image, ImageEnhance, ImageFilter
    import pytesseract
    import win32gui
    import win32con
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

# ── Config ──────────────────────────────────────────────────────────────────
TARGET_WINDOW_TITLE = "Brakes"
PASS_THRESHOLD = 25.00
SCAN_INTERVAL_MS = 1500   # OCR ทุก 1.5 วินาที
CONFIG_FILE = os.path.join(os.path.dirname(sys.executable if getattr(sys, 'frozen', False) else __file__), "config.json")

# Tesseract path (Windows default)
TESS_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ── Colors ───────────────────────────────────────────────────────────────────
BG         = "#0d0d0d"
GREEN      = "#00ff41"
RED        = "#ff4444"
YELLOW     = "#ffd700"
GRAY       = "#888888"
PANEL      = "#1a1a1a"

# ── Helpers ───────────────────────────────────────────────────────────────────
def find_window(title):
    """หา hwnd ของ window ที่ชื่อตรงกับ title"""
    result = []
    def enum_cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            t = win32gui.GetWindowText(hwnd)
            if title.lower() in t.lower():
                result.append(hwnd)
    win32gui.EnumWindows(enum_cb, None)
    return result[0] if result else None

def get_window_rect(hwnd):
    """คืน (left, top, right, bottom) ของ window"""
    return win32gui.GetWindowRect(hwnd)

def capture_region(hwnd, rel_rect):
    """
    ถ่ายภาพ region สัมพัทธ์กับ window
    rel_rect = (x1, y1, x2, y2) relative to window top-left
    """
    wx, wy, _, _ = get_window_rect(hwnd)
    abs_rect = (wx + rel_rect[0], wy + rel_rect[1],
                wx + rel_rect[2], wy + rel_rect[3])
    return ImageGrab.grab(bbox=abs_rect)

def ocr_number(img):
    """OCR ตัวเลขจากภาพ — คืน float หรือ None"""
    # ขยายภาพ + เพิ่ม contrast
    img = img.resize((img.width * 4, img.height * 4), Image.LANCZOS)
    img = img.convert("L")
    img = ImageEnhance.Contrast(img).enhance(3.0)
    img = img.point(lambda p: 255 if p > 100 else 0)

    cfg = "--psm 7 -c tessedit_char_whitelist=0123456789"
    text = pytesseract.image_to_string(img, config=cfg).strip()
    nums = re.findall(r'\d+', text)
    if nums:
        return float(nums[0])
    return None

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
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ── Region Selector ───────────────────────────────────────────────────────────
class RegionSelector:
    """overlay เต็มจอให้ลากกรอบเลือก region"""
    def __init__(self, root, title, callback):
        self.callback = callback
        self.start_x = self.start_y = 0
        self.rect_id = None

        self.win = tk.Toplevel(root)
        self.win.attributes("-fullscreen", True)
        self.win.attributes("-alpha", 0.3)
        self.win.attributes("-topmost", True)
        self.win.configure(bg="black")
        self.win.title(title)

        self.canvas = tk.Canvas(self.win, cursor="cross", bg="black",
                                highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        lbl = tk.Label(self.win,
                       text=f"ลากเลือกพื้นที่  {title}  แล้วปล่อย",
                       font=("Segoe UI", 18, "bold"),
                       bg="black", fg="white")
        lbl.place(relx=0.5, rely=0.05, anchor="center")

        self.canvas.bind("<ButtonPress-1>",   self.on_press)
        self.canvas.bind("<B1-Motion>",        self.on_drag)
        self.canvas.bind("<ButtonRelease-1>",  self.on_release)
        self.win.bind("<Escape>", lambda e: self.win.destroy())

    def on_press(self, e):
        self.start_x, self.start_y = e.x_root, e.y_root
        if self.rect_id:
            self.canvas.delete(self.rect_id)

    def on_drag(self, e):
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        cx = e.x_root - self.win.winfo_rootx()
        cy = e.y_root - self.win.winfo_rooty()
        sx = self.start_x - self.win.winfo_rootx()
        sy = self.start_y - self.win.winfo_rooty()
        self.rect_id = self.canvas.create_rectangle(
            sx, sy, cx, cy, outline="#00ff41", width=2)

    def on_release(self, e):
        x1, y1 = min(self.start_x, e.x_root), min(self.start_y, e.y_root)
        x2, y2 = max(self.start_x, e.x_root), max(self.start_y, e.y_root)
        self.win.destroy()
        self.callback((x1, y1, x2, y2))   # abs screen coords

# ── Main App ──────────────────────────────────────────────────────────────────
class BrakeUnbalApp:
    def __init__(self, root):
        self.root = root
        self.config = load_config()
        self.lf_region = self.config.get("lf_region")   # abs screen coords
        self.rf_region = self.config.get("rf_region")
        self.scanning = False
        self._setup_tesseract()
        self._build_ui()
        self._start_scan()

    def _setup_tesseract(self):
        if HAS_DEPS and os.path.exists(TESS_PATH):
            pytesseract.pytesseract.tesseract_cmd = TESS_PATH

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        r = self.root
        r.title("Brake Unbal")
        r.geometry("220x260")
        r.resizable(False, False)
        r.attributes("-topmost", True)
        r.configure(bg=BG)

        # Title bar แทนด้วยแถบเล็กๆ
        bar = tk.Frame(r, bg="#111111", height=28)
        bar.pack(fill="x")
        tk.Label(bar, text="🔧 Brake Unbal", font=("Segoe UI", 9, "bold"),
                 bg="#111111", fg=YELLOW).pack(side="left", padx=8, pady=4)

        # Status window
        self.status_var = tk.StringVar(value="กำลังหา Brakes window...")
        tk.Label(r, textvariable=self.status_var,
                 font=("Segoe UI", 8), bg=BG, fg=GRAY,
                 wraplength=200).pack(pady=(6, 0))

        # LF / RF row
        row = tk.Frame(r, bg=BG)
        row.pack(pady=6)
        self._lf_val = tk.StringVar(value="---")
        self._rf_val = tk.StringVar(value="---")
        for label, var in [("LF", self._lf_val), ("RF", self._rf_val)]:
            col = tk.Frame(row, bg=PANEL, bd=0,
                           highlightbackground="#333", highlightthickness=1)
            col.pack(side="left", padx=6)
            tk.Label(col, text=label, font=("Segoe UI", 8),
                     bg=PANEL, fg=GRAY).pack(pady=(4, 0))
            tk.Label(col, textvariable=var, font=("Consolas", 16, "bold"),
                     bg=PANEL, fg=GREEN, width=5).pack(padx=8, pady=(0, 4))

        # Unbal big display
        tk.Label(r, text="Unbal", font=("Segoe UI", 9),
                 bg=BG, fg=GRAY).pack()
        self._unbal_var = tk.StringVar(value="--.-- %")
        self._unbal_lbl = tk.Label(r, textvariable=self._unbal_var,
                                   font=("Consolas", 32, "bold"),
                                   bg=BG, fg=GRAY)
        self._unbal_lbl.pack(pady=2)

        # Pass/Fail
        self._result_var = tk.StringVar(value="")
        self._result_lbl = tk.Label(r, textvariable=self._result_var,
                                    font=("Segoe UI", 12, "bold"),
                                    bg=BG, fg=GRAY, pady=4)
        self._result_lbl.pack()

        # Setup button
        btn_frame = tk.Frame(r, bg=BG)
        btn_frame.pack(pady=(4, 8))
        tk.Button(btn_frame, text="⚙ Setup Region",
                  font=("Segoe UI", 8), bg="#333", fg="white",
                  relief="flat", padx=8, pady=3, cursor="hand2",
                  command=self._start_setup).pack()

        region_ok = self.lf_region and self.rf_region
        if not region_ok:
            self.status_var.set("⚠ กรุณากด Setup Region ก่อน")

    # ── Setup Flow ────────────────────────────────────────────────────────────
    def _start_setup(self):
        if not HAS_DEPS:
            messagebox.showerror("Error", "ไม่พบ dependencies\nกรุณาติดตั้ง: pip install pillow pytesseract pywin32")
            return
        hwnd = find_window(TARGET_WINDOW_TITLE)
        if not hwnd:
            messagebox.showwarning("ไม่พบ Window",
                                   f'ไม่พบ window ชื่อ "{TARGET_WINDOW_TITLE}"\nกรุณาเปิดโปรแกรมทดสอบเบรกก่อน')
            return
        # ซ่อนหน้าต่างตัวเองชั่วคราว
        self.root.withdraw()
        time.sleep(0.3)
        RegionSelector(self.root, "LF  (ซ้ายหน้า)", self._on_lf_selected)

    def _on_lf_selected(self, abs_rect):
        self._pending_lf = abs_rect
        time.sleep(0.2)
        RegionSelector(self.root, "RF  (ขวาหน้า)", self._on_rf_selected)

    def _on_rf_selected(self, abs_rect):
        self.root.deiconify()
        hwnd = find_window(TARGET_WINDOW_TITLE)
        if not hwnd:
            messagebox.showerror("Error", "ไม่พบ window ขณะ save config")
            return
        wx, wy, _, _ = get_window_rect(hwnd)

        def to_rel(a):
            return (a[0]-wx, a[1]-wy, a[2]-wx, a[3]-wy)

        self.lf_region = to_rel(self._pending_lf)
        self.rf_region = to_rel(abs_rect)
        save_config({"lf_region": self.lf_region, "rf_region": self.rf_region})
        self.status_var.set("✔ Setup เสร็จแล้ว — กำลัง OCR...")

    # ── Scan Loop ─────────────────────────────────────────────────────────────
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

        hwnd = find_window(TARGET_WINDOW_TITLE)
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

        lf = ocr_number(lf_img)
        rf = ocr_number(rf_img)
        self._set_values(lf, rf)

        if lf is not None and rf is not None:
            self.status_var.set("● กำลังอ่านค่า...")
        else:
            self.status_var.set("OCR อ่านไม่ได้ — ตรวจสอบ region")

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

# ── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    app = BrakeUnbalApp(root)
    root.mainloop()