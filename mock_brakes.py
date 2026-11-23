import ctypes
import random
import tkinter as tk
from tkinter import ttk

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# 7-Segment map: (a, b, c, d, e, f, g)
DIGIT_SEGS = {
    "0": (1, 1, 1, 1, 1, 1, 0),
    "1": (0, 1, 1, 0, 0, 0, 0),
    "2": (1, 1, 0, 1, 1, 0, 1),
    "3": (1, 1, 1, 1, 0, 0, 1),
    "4": (0, 1, 1, 0, 0, 1, 1),
    "5": (1, 0, 1, 1, 0, 1, 1),
    "6": (1, 0, 1, 1, 1, 1, 1),
    "7": (1, 1, 1, 0, 0, 0, 0),
    "8": (1, 1, 1, 1, 1, 1, 1),
    "9": (1, 1, 1, 1, 0, 1, 1),
}


class SevenSegDisplay(tk.Canvas):
    """Canvas วาดตัวเลข 7-Segment สีฟ้า (Cyan) บนพื้นดำเหมือนโปรแกรม Brakes จริง"""

    def __init__(self, parent, digits=3, width=156, height=68, fg="#20d8c8", bg="#262c2e", **kwargs):
        super().__init__(
            parent,
            width=width,
            height=height,
            bg=bg,
            highlightthickness=2,
            highlightbackground="#455056",
            **kwargs,
        )
        self.num_digits = digits
        self.w = width
        self.h = height
        self.fg = fg
        self.off_color = "#2e3639"

    def _draw_hseg(self, x, y, length, thick, color):
        t = thick / 2
        pts = [
            x + t, y,
            x + length - t, y,
            x + length, y + t,
            x + length - t, y + thick,
            x + t, y + thick,
            x, y + t,
        ]
        self.create_polygon(pts, fill=color, outline="")

    def _draw_vseg(self, x, y, length, thick, color):
        t = thick / 2
        pts = [
            x + t, y,
            x + thick, y + t,
            x + thick, y + length - t,
            x + t, y + length,
            x, y + length - t,
            x, y + t,
        ]
        self.create_polygon(pts, fill=color, outline="")

    def set_value(self, value, pad_zero=False):
        self.delete("all")
        s = str(int(value))
        if pad_zero:
            s = s.zfill(self.num_digits)
        else:
            s = s.rjust(self.num_digits)

        pad_x = 12
        pad_y = 9
        gap = 10
        avail_w = self.w - 2 * pad_x - gap * (self.num_digits - 1)
        dw = avail_w / self.num_digits
        dh = self.h - 2 * pad_y
        thick = max(5, dh * 0.14)
        seg_gap = 2
        half_h = (dh - thick) / 2

        for idx, ch in enumerate(s[-self.num_digits:]):
            ox = pad_x + idx * (dw + gap)
            oy = pad_y
            segs = DIGIT_SEGS.get(ch, (0, 0, 0, 0, 0, 0, 0))
            a, b, c, d, e, f, g = segs

            # a (top)
            self._draw_hseg(ox + thick * 0.6, oy, dw - thick * 1.2, thick, self.fg if a else self.off_color)
            # g (middle)
            self._draw_hseg(ox + thick * 0.6, oy + half_h, dw - thick * 1.2, thick, self.fg if g else self.off_color)
            # d (bottom)
            self._draw_hseg(ox + thick * 0.6, oy + dh - thick, dw - thick * 1.2, thick, self.fg if d else self.off_color)
            # f (top-left)
            self._draw_vseg(ox, oy + thick * 0.5 + seg_gap, half_h - seg_gap, thick, self.fg if f else self.off_color)
            # b (top-right)
            self._draw_vseg(ox + dw - thick, oy + thick * 0.5 + seg_gap, half_h - seg_gap, thick, self.fg if b else self.off_color)
            # e (bot-left)
            self._draw_vseg(ox, oy + half_h + thick * 0.5 + seg_gap, half_h - seg_gap, thick, self.fg if e else self.off_color)
            # c (bot-right)
            self._draw_vseg(ox + dw - thick, oy + half_h + thick * 0.5 + seg_gap, half_h - seg_gap, thick, self.fg if c else self.off_color)


class BrakesSimulator:
    def __init__(self, root):
        self.root = root
        self.root.title("Brakes")
        self.root.geometry("480x430")
        self.root.configure(bg="#1e1e24")
        self.root.resizable(False, False)

        self.lf_val = tk.IntVar(value=143)
        self.rf_val = tk.IntVar(value=156)
        self.auto_fluctuate = tk.BooleanVar(value=False)
        self.leading_zeros = tk.BooleanVar(value=False)

        self._build_ui()
        self._redraw_displays()
        self._tick()

    def _build_ui(self):
        # 1. Header
        header = tk.Frame(self.root, bg="#2b2d42", height=46)
        header.pack(fill="x")
        tk.Label(
            header,
            text="📟 Machine Simulator (Brakes - 7-Segment)",
            font=("Segoe UI", 11, "bold"),
            bg="#2b2d42",
            fg="#edf2f4",
        ).pack(pady=10)

        # 2. Display Area (เหมือนแผงสีฟ้าเทา + กล่อง 7-segment ของเครื่องจริง)
        panel = tk.Frame(self.root, bg="#88b0c8", bd=2, relief="ridge", padx=16, pady=12)
        panel.pack(fill="x", padx=20, pady=14)

        row = tk.Frame(panel, bg="#88b0c8")
        row.pack(fill="x")

        # LF
        lf_col = tk.Frame(row, bg="#88b0c8")
        lf_col.pack(side="left", expand=True)
        tk.Label(lf_col, text="LF", font=("Segoe UI", 13, "bold"), bg="#88b0c8", fg="#f0f6fa").pack(anchor="w")
        self.lf_disp = SevenSegDisplay(lf_col, digits=3, width=156, height=68)
        self.lf_disp.pack(pady=(2, 0))

        # Middle unit label
        mid_col = tk.Frame(row, bg="#88b0c8")
        mid_col.pack(side="left", padx=8)
        tk.Label(mid_col, text="daN", font=("Segoe UI", 12, "bold"), bg="#88b0c8", fg="#f0f6fa").pack(pady=(24, 0))

        # RF
        rf_col = tk.Frame(row, bg="#88b0c8")
        rf_col.pack(side="left", expand=True)
        tk.Label(rf_col, text="RF", font=("Segoe UI", 13, "bold"), bg="#88b0c8", fg="#f0f6fa").pack(anchor="w")
        self.rf_disp = SevenSegDisplay(rf_col, digits=3, width=156, height=68)
        self.rf_disp.pack(pady=(2, 0))

        # 3. Control Panel
        control_frame = tk.LabelFrame(
            self.root,
            text=" Controls / Adjustments ",
            font=("Segoe UI", 9, "bold"),
            bg="#1e1e24",
            fg="#a0a0b0",
            bd=1,
            relief="solid",
            padx=15,
            pady=10,
        )
        control_frame.pack(fill="both", expand=True, padx=20, pady=(0, 15))

        # Slider for LF
        lf_ctrl = tk.Frame(control_frame, bg="#1e1e24")
        lf_ctrl.pack(fill="x", pady=3)
        tk.Label(lf_ctrl, text="LF Force:", width=8, anchor="w", bg="#1e1e24", fg="#edf2f4", font=("Segoe UI", 9)).pack(side="left")
        ttk.Scale(lf_ctrl, from_=0, to=450, variable=self.lf_val, orient="horizontal", command=self._on_lf_scroll).pack(side="left", fill="x", expand=True, padx=10)
        tk.Label(lf_ctrl, textvariable=self.lf_val, width=4, bg="#1e1e24", fg="#edf2f4", font=("Consolas", 10, "bold")).pack(side="right")

        # Slider for RF
        rf_ctrl = tk.Frame(control_frame, bg="#1e1e24")
        rf_ctrl.pack(fill="x", pady=3)
        tk.Label(rf_ctrl, text="RF Force:", width=8, anchor="w", bg="#1e1e24", fg="#edf2f4", font=("Segoe UI", 9)).pack(side="left")
        ttk.Scale(rf_ctrl, from_=0, to=450, variable=self.rf_val, orient="horizontal", command=self._on_rf_scroll).pack(side="left", fill="x", expand=True, padx=10)
        tk.Label(rf_ctrl, textvariable=self.rf_val, width=4, bg="#1e1e24", fg="#edf2f4", font=("Consolas", 10, "bold")).pack(side="right")

        # Preset Buttons Row
        row3 = tk.Frame(control_frame, bg="#1e1e24")
        row3.pack(fill="x", pady=(10, 4))
        tk.Button(row3, text="Real: 143 / 156", font=("Segoe UI", 8), bg="#2b2d42", fg="white", relief="flat", cursor="hand2", command=lambda: self.set_preset(143, 156)).pack(side="left", padx=2)
        tk.Button(row3, text="Real: 009 / 009", font=("Segoe UI", 8), bg="#2b2d42", fg="white", relief="flat", cursor="hand2", command=lambda: self.set_preset(9, 9, pad=True)).pack(side="left", padx=2)
        tk.Button(row3, text="Fail: 180 / 260", font=("Segoe UI", 8), bg="#ef233c", fg="white", relief="flat", cursor="hand2", command=lambda: self.set_preset(180, 260)).pack(side="left", padx=2)

        # Options Row
        row4 = tk.Frame(control_frame, bg="#1e1e24")
        row4.pack(fill="x", pady=(4, 0))
        tk.Checkbutton(
            row4,
            text="Leading Zeros (009)",
            variable=self.leading_zeros,
            command=self._redraw_displays,
            font=("Segoe UI", 9),
            bg="#1e1e24",
            fg="#edf2f4",
            selectcolor="#2b2d42",
            activebackground="#1e1e24",
            activeforeground="#edf2f4",
        ).pack(side="left")
        tk.Checkbutton(
            row4,
            text="Auto Fluctuate",
            variable=self.auto_fluctuate,
            font=("Segoe UI", 9),
            bg="#1e1e24",
            fg="#edf2f4",
            selectcolor="#2b2d42",
            activebackground="#1e1e24",
            activeforeground="#edf2f4",
        ).pack(side="right")

    def _redraw_displays(self):
        pad = self.leading_zeros.get()
        self.lf_disp.set_value(self.lf_val.get(), pad_zero=pad)
        self.rf_disp.set_value(self.rf_val.get(), pad_zero=pad)

    def _on_lf_scroll(self, val):
        self.lf_val.set(int(float(val)))
        self._redraw_displays()

    def _on_rf_scroll(self, val):
        self.rf_val.set(int(float(val)))
        self._redraw_displays()

    def set_preset(self, lf, rf, pad=None):
        if pad is not None:
            self.leading_zeros.set(pad)
        self.lf_val.set(lf)
        self.rf_val.set(rf)
        self._redraw_displays()

    def _tick(self):
        if self.auto_fluctuate.get():
            dlf = random.choice([-3, -2, -1, 0, 1, 2, 3])
            drf = random.choice([-3, -2, -1, 0, 1, 2, 3])
            self.lf_val.set(max(0, min(450, self.lf_val.get() + dlf)))
            self.rf_val.set(max(0, min(450, self.rf_val.get() + drf)))
            self._redraw_displays()
        self.root.after(1000, self._tick)


if __name__ == "__main__":
    root = tk.Tk()
    style = ttk.Style()
    style.theme_use("clam")
    style.configure("Horizontal.TScale", background="#1e1e24", troughcolor="#333", bordercolor="#444")
    app = BrakesSimulator(root)
    root.mainloop()
