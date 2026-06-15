import tkinter as tk
from tkinter import ttk
import random

class BrakesSimulator:
    def __init__(self, root):
        self.root = root
        self.root.title("Brakes")
        self.root.geometry("450x420")
        self.root.configure(bg="#1e1e24")
        self.root.resizable(False, False)

        # State variables
        self.lf_val = tk.IntVar(value=180)
        self.rf_val = tk.IntVar(value=195)
        self.auto_fluctuate = tk.BooleanVar(value=False)

        self._build_ui()
        self._tick()

    def _build_ui(self):
        # 1. Header
        header = tk.Frame(self.root, bg="#2b2d42", height=50)
        header.pack(fill="x")
        tk.Label(header, text="📟 Machine Simulator (Brakes)", font=("Segoe UI", 12, "bold"),
                 bg="#2b2d42", fg="#edf2f4").pack(pady=10)

        # 2. Display Area (This is what the OCR will capture)
        display_frame = tk.LabelFrame(self.root, text=" OCR DISPLAY REGION (ลากครอบส่วนนี้) ", 
                                      font=("Segoe UI", 9, "bold"), bg="#1e1e24", fg="#a0a0b0",
                                      bd=1, relief="solid", padx=10, pady=10)
        display_frame.pack(fill="x", padx=20, pady=15)

        # We will make the actual number display areas pure black with high-contrast text
        num_frame = tk.Frame(display_frame, bg="#000000", bd=2, relief="solid")
        num_frame.pack(fill="x", ipady=10)

        # LF Box
        lf_box = tk.Frame(num_frame, bg="#000000")
        lf_box.pack(side="left", expand=True, fill="both")
        tk.Label(lf_box, text="LF", font=("Segoe UI", 10, "bold"), bg="#000000", fg="#888").pack(pady=(5,0))
        self.lf_lbl = tk.Label(lf_box, textvariable=self.lf_val, font=("Consolas", 42, "bold"), 
                               bg="#000000", fg="#ffffff")
        self.lf_lbl.pack()

        # Divider line
        div = tk.Frame(num_frame, bg="#333", width=2)
        div.pack(side="left", fill="y", padx=5)

        # RF Box
        rf_box = tk.Frame(num_frame, bg="#000000")
        rf_box.pack(side="left", expand=True, fill="both")
        tk.Label(rf_box, text="RF", font=("Segoe UI", 10, "bold"), bg="#000000", fg="#888").pack(pady=(5,0))
        self.rf_lbl = tk.Label(rf_box, textvariable=self.rf_val, font=("Consolas", 42, "bold"), 
                               bg="#000000", fg="#ffffff")
        self.rf_lbl.pack()

        # 3. Control Panel
        control_frame = tk.LabelFrame(self.root, text=" Controls / Adjustments ", 
                                      font=("Segoe UI", 9, "bold"), bg="#1e1e24", fg="#a0a0b0",
                                      bd=1, relief="solid", padx=15, pady=10)
        control_frame.pack(fill="both", expand=True, padx=20, pady=(0, 15))

        # Slider for LF
        lf_ctrl = tk.Frame(control_frame, bg="#1e1e24")
        lf_ctrl.pack(fill="x", pady=2)
        tk.Label(lf_ctrl, text="LF Force:", width=8, anchor="w", bg="#1e1e24", fg="#edf2f4", font=("Segoe UI", 9)).pack(side="left")
        self.lf_scale = ttk.Scale(lf_ctrl, from_=0, to=450, variable=self.lf_val, orient="horizontal", command=self._on_lf_scroll)
        self.lf_scale.pack(side="left", fill="x", expand=True, padx=10)
        tk.Label(lf_ctrl, textvariable=self.lf_val, width=4, bg="#1e1e24", fg="#edf2f4", font=("Consolas", 10, "bold")).pack(side="right")

        # Slider for RF
        rf_ctrl = tk.Frame(control_frame, bg="#1e1e24")
        rf_ctrl.pack(fill="x", pady=2)
        tk.Label(rf_ctrl, text="RF Force:", width=8, anchor="w", bg="#1e1e24", fg="#edf2f4", font=("Segoe UI", 9)).pack(side="left")
        self.rf_scale = ttk.Scale(rf_ctrl, from_=0, to=450, variable=self.rf_val, orient="horizontal", command=self._on_rf_scroll)
        self.rf_scale.pack(side="left", fill="x", expand=True, padx=10)
        tk.Label(rf_ctrl, textvariable=self.rf_val, width=4, bg="#1e1e24", fg="#edf2f4", font=("Consolas", 10, "bold")).pack(side="right")

        # Preset & Auto Fluctuate Row
        row3 = tk.Frame(control_frame, bg="#1e1e24")
        row3.pack(fill="x", pady=(10, 0))

        # Preset Buttons
        tk.Button(row3, text="Preset: Pass (180/195)", font=("Segoe UI", 8), bg="#2b2d42", fg="white", 
                  relief="flat", cursor="hand2", command=lambda: self.set_preset(180, 195)).pack(side="left", padx=2)
        tk.Button(row3, text="Preset: Fail (180/260)", font=("Segoe UI", 8), bg="#ef233c", fg="white", 
                  relief="flat", cursor="hand2", command=lambda: self.set_preset(180, 260)).pack(side="left", padx=2)

        # Checkbox for Auto Fluctuate
        chk = tk.Checkbutton(row3, text="Auto Fluctuate", variable=self.auto_fluctuate, 
                             font=("Segoe UI", 9), bg="#1e1e24", fg="#edf2f4", selectcolor="#2b2d42",
                             activebackground="#1e1e24", activeforeground="#edf2f4")
        chk.pack(side="right")

    def _on_lf_scroll(self, val):
        self.lf_val.set(int(float(val)))

    def _on_rf_scroll(self, val):
        self.rf_val.set(int(float(val)))

    def set_preset(self, lf, rf):
        self.lf_val.set(lf)
        self.rf_val.set(rf)

    def _tick(self):
        if self.auto_fluctuate.get():
            # Add or subtract a small amount
            dlf = random.choice([-3, -2, -1, 0, 1, 2, 3])
            drf = random.choice([-3, -2, -1, 0, 1, 2, 3])
            
            new_lf = max(0, min(450, self.lf_val.get() + dlf))
            new_rf = max(0, min(450, self.rf_val.get() + drf))
            
            self.lf_val.set(new_lf)
            self.rf_val.set(new_rf)
            
        self.root.after(1000, self._tick)

if __name__ == "__main__":
    root = tk.Tk()
    # Apply ttk style for nicer sliders
    style = ttk.Style()
    style.theme_use("clam")
    style.configure("Horizontal.TScale", background="#1e1e24", troughcolor="#333", bordercolor="#444")
    
    app = BrakesSimulator(root)
    root.mainloop()
