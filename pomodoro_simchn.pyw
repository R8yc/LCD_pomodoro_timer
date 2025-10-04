# -*- coding: utf-8 -*-
"""
Pomodoro GUI (fixed window size after startup; user-resizable)
- 启动: 固定初始大小；此后程序不再自动改变窗口大小（用户可手动改）
- 三行显示在上；Settings 下分三段：工具栏（COLOR+SIZE+B/I/U）→ 参数网格 → 底栏（Start/Reset + Date/Floating）
- 单击第一行开合 Settings；双击第一行或 Esc 切换浮窗
- 浮窗: Windows 色键透明，可拖动；默认无描边（浮窗与常态字重一致）
- Pause 显示 'PAUSE'；Resume 恢复 STUDY/BREAK
- 新增：快捷键 S/s 切换 Settings
"""
import os, glob, threading, time
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter import font as tkfont

# ---------- 工具 ----------
def find_audio_file(folder: str):
    for pat in ("*.wav", "*.mp3", "*.WAV", "*.MP3"):
        fs = glob.glob(os.path.join(folder, pat))
        if fs: return fs[0]
    return None

def play_sound_async(path: str):
    if not path: return
    def worker():
        try:
            ext = os.path.splitext(path)[1].lower()
            if os.name == "nt" and ext == ".wav":
                import winsound
                winsound.PlaySound(path, winsound.SND_ASYNC)
            else:
                import playsound
                try: playsound.playsound(path, block=False)
                except TypeError: playsound.playsound(path)
        except: pass
    threading.Thread(target=worker, daemon=True).start()

def load_first_ttf_and_get_family(folder: str):
    ttf_files = sorted(glob.glob(os.path.join(folder, "*.ttf")))
    if not ttf_files: return False, None
    ttf = ttf_files[0]
    _ = tkfont.families()
    before = set(tkfont.families())
    if os.name == "nt":
        try:
            import ctypes
            FR_PRIVATE = 0x10
            ctypes.windll.gdi32.AddFontResourceExW(ttf, FR_PRIVATE, 0)
            tk._default_root.tk.call('tk', 'fontchooser', 'configure', '-font', 'TkDefaultFont')
            after = set(tkfont.families())
            newf = list(after - before)
            if newf: return True, sorted(newf)[0]
        except: pass
    return False, None

def fmt_clock(dt: datetime) -> str: return dt.strftime("%y/%m/%d %H:%M:%S")
def fmt_mm_ss(sec: int) -> str:
    if sec < 0: sec = 0
    m, s = divmod(sec, 60)
    return f"{m:02d}:{s:02d}"
def fmt_progress(n: int, d: int) -> str:
    n = max(0, n); d = max(0, d)
    return f"{n:02d}/{d:02d}"

# ---------- 文本行（Canvas；默认无描边，浮窗与常态字重一致） ----------
class TextLine(tk.Canvas):
    def __init__(self, master, text="", font=None, fg="#000", bg=None, **kw):
        super().__init__(master, bd=0, highlightthickness=0, **kw)
        self._text = text
        self._font = font or ("Segoe UI", 36, "bold")
        self._fg = fg
        self._bg = bg or master.cget("bg")
        self._outline_thick = 0
        self._outline_color = self._fg
        super().configure(bg=self._bg)
        self.bind("<Configure>", lambda e: self._redraw())
        self._redraw()

    def configure(self, **kw):
        if "text" in kw: self._text = kw.pop("text")
        if "font" in kw: self._font = kw.pop("font")
        if "fg"   in kw: self._fg   = kw.pop("fg")
        if "bg"   in kw:
            self._bg = kw.pop("bg"); super().configure(bg=self._bg)
        if kw: super().configure(**kw)
        self._redraw()
    config = configure

    def cget(self, key):
        return {"text":self._text, "font":self._font, "fg":self._fg, "bg":self._bg}.get(
            key, super().cget(key))

    def set_outline(self, thickness: int, color: str = None):
        self._outline_thick = max(0, int(thickness))
        if color is not None: self._outline_color = color
        self._redraw()

    def _redraw(self):
        self.delete("all")
        fnt = tkfont.Font(font=self._font)
        h = fnt.metrics("linespace")
        super().configure(height=h + 6)
        x, y = 0, (h // 2) + 3
        if self._outline_thick > 0 and self._text:
            t = self._outline_thick
            for dx, dy in [(-t,-t), (t,-t), (-t,t), (t,t)]:
                self.create_text(x+dx, y+dy, text=self._text, font=self._font,
                                 fill=self._outline_color, anchor="w")
        if self._text:
            self.create_text(x, y, text=self._text, font=self._font,
                             fill=self._fg, anchor="w")

# ---------- 主程序 ----------
class PomodoroApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Pomodoro Timer")
        # 你当前版本的初始尺寸（保持不变）
        self.geometry("600x450")
        self.minsize(400, 240)

        self.folder = os.path.abspath(os.path.dirname(__file__))
        self.audio_path = find_audio_file(self.folder)

        _ = tkfont.families()
        _, fam = load_first_ttf_and_get_family(self.folder)
        self.base_family = fam or "Segoe UI"

        # 尺寸/样式
        self.size_presets = {
            "Large": {"large":57, "mid":36, "pad":{"status":(6,2), "bottom":(0,6), "time":(0,6)}},
            "Mid":   {"large":38, "mid":24, "pad":{"status":(4,2), "bottom":(0,4), "time":(0,4)}},
            "Small": {"large":28, "mid":18, "pad":{"status":(3,1), "bottom":(0,3), "time":(0,3)}},
        }
        self.current_size = "Large"
        self.bold_on = tk.BooleanVar(value=True)
        self.italic_on = tk.BooleanVar(value=False)
        self.underline_on = tk.BooleanVar(value=False)
        self.font_small = (self.base_family, 12)
        self.content_padx = 32

        # 浮窗
        self._root_bg0 = self.cget("bg")
        self.chroma = "#FF00FF"
        self.float_on  = tk.BooleanVar(value=False)
        self.show_time = tk.BooleanVar(value=True)  # Date
        self.float_outline_px = 0                  # 默认无描边

        # ===== 三行显示区 =====
        self.wrap = tk.Frame(self, bd=0, highlightthickness=0)
        self.wrap.pack(side=tk.TOP, fill="x")
        self.display = tk.Frame(self.wrap, bd=0, highlightthickness=0)
        self.display.pack(side=tk.TOP, fill="x")
        self.wrap_default_bg = self.wrap.cget("bg")
        self.display_default_bg = self.display.cget("bg")

        self.lbl_status = TextLine(self.display, text="READY", font=self._font_big())
        self.lbl_status.pack(side=tk.TOP, fill="x", padx=self.content_padx,
                             pady=self.size_presets[self.current_size]["pad"]["status"])
        # 单击：开合 Settings（保留在浮窗/常态两种模式）
        self.lbl_status.bind("<Button-1>", self._on_status_click)
        # 双击：进/出浮窗
        self.lbl_status.bind("<Double-Button-1>", self._toggle_floating_evt)

        self.lbl_bottom = TextLine(self.display,
                                   text=f"{fmt_progress(0,0)}    00:00", font=self._font_big())
        self.lbl_bottom.pack(side=tk.TOP, fill="x", padx=self.content_padx,
                             pady=self.size_presets[self.current_size]["pad"]["bottom"])

        self.lbl_now = TextLine(self.display, text=fmt_clock(datetime.now()), font=self._font_mid())
        self.lbl_now.pack(side=tk.TOP, fill="x", padx=self.content_padx,
                          pady=self.size_presets[self.current_size]["pad"]["time"])

        self._status_bg0 = self.lbl_status.cget("bg")
        self._bottom_bg0 = self.lbl_bottom.cget("bg")
        self._now_bg0    = self.lbl_now.cget("bg")

        # ===== Settings（整体）=====
        self.setting_open = tk.BooleanVar(value=True)
        self.settings = ttk.Frame(self, padding=(8,0,8,6))
        self.settings.pack(side=tk.TOP, fill=tk.X, after=self.wrap)

        # —— 工具栏：COLOR + SIZE + B/I/U —— 
        self.toolbar = ttk.Frame(self.settings)
        self.toolbar.pack(side=tk.TOP, fill=tk.X, pady=(0,6))

        ttk.Label(self.toolbar, text="COLOR:", font=self.font_small)\
            .pack(side=tk.LEFT, padx=(0,6))
        self.color_var = tk.StringVar(value="Black")
        self.color_box = ttk.Combobox(self.toolbar, textvariable=self.color_var, state="readonly",
                                      values=["Black","Red","Yellow","Blue","Green"], width=8)
        self.color_box.pack(side=tk.LEFT)
        self.color_box.bind("<<ComboboxSelected>>", self.on_color_change)

        ttk.Label(self.toolbar, text="SIZE:", font=self.font_small)\
            .pack(side=tk.LEFT, padx=(12,6))
        self.size_var = tk.StringVar(value="Large")
        self.size_box = ttk.Combobox(self.toolbar, textvariable=self.size_var, state="readonly",
                                     values=["Large","Mid","Small"], width=7)
        self.size_box.pack(side=tk.LEFT)
        self.size_box.bind("<<ComboboxSelected>>", self.on_size_change)

        # B I U 切换（按钮式）
        btn_font_B = (self.base_family, 11, "bold")
        btn_font_I = (self.base_family, 11, "italic")
        btn_font_U = (self.base_family, 11, "underline")
        tk.Checkbutton(self.toolbar, text="B", width=2, indicatoron=False,
                       font=btn_font_B, variable=self.bold_on,
                       command=self.apply_text_style).pack(side=tk.LEFT, padx=(12,2))
        tk.Checkbutton(self.toolbar, text="I", width=2, indicatoron=False,
                       font=btn_font_I, variable=self.italic_on,
                       command=self.apply_text_style).pack(side=tk.LEFT, padx=2)
        tk.Checkbutton(self.toolbar, text="U", width=2, indicatoron=False,
                       font=btn_font_U, variable=self.underline_on,
                       command=self.apply_text_style).pack(side=tk.LEFT, padx=2)

        # —— 参数网格 —— 
        self.gridp = ttk.Frame(self.settings)
        self.gridp.pack(side=tk.TOP, fill=tk.X, pady=(4,6))

        self.var_sessions  = tk.StringVar(value="12")
        self.var_pomo_min  = tk.StringVar(value="25")
        self.var_short_min = tk.StringVar(value="5")
        self.var_long_min  = tk.StringVar(value="15")

        ttk.Label(self.gridp, text="SESSIONS (≤20):", font=self.font_small)\
            .grid(row=0, column=0, sticky="e", padx=(0,6), pady=2)
        ttk.Entry(self.gridp, width=6, textvariable=self.var_sessions, font=self.font_small)\
            .grid(row=0, column=1, sticky="w", padx=(0,16), pady=2)

        ttk.Label(self.gridp, text="POMODORO (min):", font=self.font_small)\
            .grid(row=0, column=2, sticky="e", padx=(0,6), pady=2)
        ttk.Entry(self.gridp, width=6, textvariable=self.var_pomo_min, font=self.font_small)\
            .grid(row=0, column=3, sticky="w")

        ttk.Label(self.gridp, text="SHORT BREAK (min):", font=self.font_small)\
            .grid(row=1, column=0, sticky="e", padx=(0,6), pady=2)
        ttk.Entry(self.gridp, width=6, textvariable=self.var_short_min, font=self.font_small)\
            .grid(row=1, column=1, sticky="w", padx=(0,16), pady=2)

        ttk.Label(self.gridp, text="LONG BREAK (min):", font=self.font_small)\
            .grid(row=1, column=2, sticky="e", padx=(0,6), pady=2)
        ttk.Entry(self.gridp, width=6, textvariable=self.var_long_min, font=self.font_small)\
            .grid(row=1, column=3, sticky="w")

        # —— 底栏 —— 
        self.bottombar = ttk.Frame(self.settings)
        self.bottombar.pack(side=tk.TOP, fill=tk.X, pady=(2,0))
        self.btn_start = ttk.Button(self.bottombar, text="Start", command=self.on_start_pause_resume)
        self.btn_start.pack(side=tk.LEFT, padx=(0,6))
        self.btn_reset = ttk.Button(self.bottombar, text="Reset", command=self.on_reset)
        self.btn_reset.pack(side=tk.LEFT, padx=(0,12))
        ttk.Checkbutton(self.bottombar, text="Date", variable=self.show_time,
                        command=self.apply_show_time).pack(side=tk.LEFT, padx=(12,0))
        ttk.Checkbutton(self.bottombar, text="Floating", variable=self.float_on,
                        command=self.apply_floating).pack(side=tk.LEFT, padx=(12,0))

        # 颜色
        self.current_fg = "#000000"
        self.apply_color("Black")

        # 运行状态
        self.total_sessions = 0
        self.done_pomodoros = 0
        self.mode = "idle"
        self.paused = False
        self.paused_left = 0
        self._status_before_pause = "READY"
        self.pomo_min = 25; self.short_min = 5; self.long_min = 15
        self.phase_end_monot = 0.0
        self.heartbeat_ms = 200
        self._hb_id = None

        # Esc：切换浮窗；S/s：切换 Settings
        self.bind("<KeyPress-f>", self._toggle_floating_evt)
        self.bind("<KeyPress-F>", self._toggle_floating_evt)
        self.bind("<KeyPress-s>", self._toggle_settings_key)
        self.bind("<KeyPress-S>", self._toggle_settings_key)

        self._update_clock(); self._heartbeat()

    # ---------- 样式/字号 ----------
    def _styles(self):
        s = []
        if self.bold_on.get(): s.append("bold")
        if self.italic_on.get(): s.append("italic")
        if self.underline_on.get(): s.append("underline")
        return tuple(s)
    def _font_big(self):
        L = self.size_presets[self.current_size]["large"]
        return (self.base_family, L) + self._styles()
    def _font_mid(self):
        M = self.size_presets[self.current_size]["mid"]
        return (self.base_family, M) + self._styles()
    def apply_text_style(self, *_):
        self.lbl_status.config(font=self._font_big())
        self.lbl_bottom.config(font=self._font_big())
        self.lbl_now.config(font=self._font_mid())

    # ---------- 快捷键：S/s 切换 Settings ----------
    def _toggle_settings_key(self, _evt=None):
        self.toggle_settings()
        return "break"

    # ---------- 状态行交互 ----------
    def _on_status_click(self, _):
        # 浮窗/常态都允许用第一行开合 Settings
        self.toggle_settings()

    def _toggle_floating_evt(self, *_):
        self.float_on.set(not self.float_on.get())
        self.apply_floating()

    # ---------- 折叠/展开 Settings ----------
    def toggle_settings(self):
        if self.setting_open.get():
            if self.settings.winfo_manager()=="pack": self.settings.pack_forget()
            self.setting_open.set(False)
        else:
            self.settings.pack(side=tk.TOP, fill=tk.X, after=self.wrap)
            self.setting_open.set(True)

    # ---------- 颜色 ----------
    def on_color_change(self, _evt=None): self.apply_color(self.color_var.get())
    def apply_color(self, name: str):
        mapping = {"Black":"#000000","Red":"#FF0000","Yellow":"#FFD400","Blue":"#2060FF","Green":"#19A95A"}
        self.current_fg = mapping.get(name, "#000000")
        for w in (self.lbl_status, self.lbl_now, self.lbl_bottom):
            w.config(fg=self.current_fg)
        if self.float_on.get():  # 同步描边（当前默认 0）
            for w in (self.lbl_status, self.lbl_now, self.lbl_bottom):
                w.set_outline(self.float_outline_px, self.current_fg)

    # ---------- 字号 ----------
    def on_size_change(self, _evt=None):
        self.current_size = self.size_var.get()
        pad = self.size_presets[self.current_size]["pad"]
        self.apply_text_style()
        self.lbl_status.pack_configure(pady=pad["status"])
        self.lbl_bottom.pack_configure(pady=pad["bottom"])
        if self.lbl_now.winfo_manager():
            self.lbl_now.pack_configure(pady=pad["time"])

    # ---------- 悬浮透明（不改变窗口大小） ----------
    def apply_floating(self):
        if self.float_on.get():
            if self.settings.winfo_manager()=="pack": self.settings.pack_forget()
            self.setting_open.set(False)

            self.attributes("-topmost", True)
            self.overrideredirect(True)
            if os.name == "nt":
                self.configure(bg=self.chroma)
                self.wrap.configure(bg=self.chroma)
                self.display.configure(bg=self.chroma)
                for w in (self.lbl_status, self.lbl_bottom, self.lbl_now):
                    w.config(bg=self.chroma)
                try: self.wm_attributes("-transparentcolor", self.chroma)
                except Exception: pass
                self.wrap.pack_configure(fill="both", expand=True)
                self.display.pack_configure(fill="both", expand=True)
            else:
                self.attributes("-alpha", 0.85)

            for w in (self.lbl_status, self.lbl_bottom, self.lbl_now):
                w.set_outline(self.float_outline_px, self.current_fg)

            # 拖动：仅在 display / 第二行 / 第三行上绑定，避免覆盖状态行单击
            for w in (self.display, self.lbl_bottom, self.lbl_now):
                w.bind("<Button-1>", self._drag_start)
                w.bind("<B1-Motion>", self._drag_move)

            # 确保状态行单击始终可用
            self.lbl_status.bind("<Button-1>", self._on_status_click)

        else:
            self.overrideredirect(False)
            self.attributes("-topmost", False)
            if os.name == "nt":
                try: self.wm_attributes("-transparentcolor", "")
                except Exception: pass
                self.configure(bg=self._root_bg0)
                self.wrap.configure(bg=self.wrap_default_bg)
                self.display.configure(bg=self.display_default_bg)
                self.lbl_status.config(bg=self._status_bg0)
                self.lbl_bottom.config(bg=self._bottom_bg0)
                self.lbl_now.config(bg=self._now_bg0)
                self.wrap.pack_configure(fill="x")
                self.display.pack_configure(fill="x")
            else:
                self.attributes("-alpha", 1.0)

            for w in (self.lbl_status, self.lbl_bottom, self.lbl_now):
                w.set_outline(0)
            # 只解除拖动绑定（不解除状态行单击）
            for w in (self.display, self.lbl_bottom, self.lbl_now):
                w.unbind("<Button-1>"); w.unbind("<B1-Motion>")
            # 退出浮窗后，明确恢复状态行单击
            self.lbl_status.bind("<Button-1>", self._on_status_click)

    def _drag_start(self, e):
        self._drag_origin = (e.x_root, e.y_root, self.winfo_x(), self.winfo_y())
    def _drag_move(self, e):
        x0, y0, gx, gy = self._drag_origin
        self.geometry(f"+{gx + (e.x_root-x0)}+{gy + (e.y_root-y0)}")  # 仅改位置

    # ---------- 日期行显示 ----------
    def apply_show_time(self):
        if self.show_time.get():
            if self.lbl_now.winfo_manager() != "pack":
                self.lbl_now.pack(side=tk.TOP, fill="x", padx=self.content_padx,
                                  pady=self.size_presets[self.current_size]["pad"]["time"])
            if self.float_on.get() and os.name == "nt":
                self.lbl_now.config(bg=self.chroma)
                self.lbl_now.set_outline(self.float_outline_px, self.current_fg)
        else:
            if self.lbl_now.winfo_manager() == "pack":
                self.lbl_now.pack_forget()

    # ---------- 心跳 ----------
    def _heartbeat(self):
        self._update_clock()
        if self.mode in ("study", "break"):
            if self.paused:
                self._update_bottom_with_left(self.paused_left)
            else:
                left = int(round(self.phase_end_monot - time.monotonic()))
                if left <= 0:
                    play_sound_async(self.audio_path)
                    self._advance_phase()
                else:
                    self._update_bottom_with_left(left)
        self._hb_id = self.after(self.heartbeat_ms, self._heartbeat)

    def _update_clock(self):
        if self.show_time.get():
            self.lbl_now.config(text=fmt_clock(datetime.now()))

    # ---------- Start / Pause / Resume ----------
    def on_start_pause_resume(self):
        if self.mode == "idle":
            vals = self._read_settings()
            if not vals: return
            self.total_sessions, self.pomo_min, self.short_min, self.long_min = vals
            self.done_pomodoros = 0
            self.paused = False
            self._enter_study()
            self.btn_start.config(text="Pause")
            return
        if not self.paused:
            if self.mode in ("study","break"):
                self.paused_left = max(0, int(round(self.phase_end_monot - time.monotonic())))
                self.paused = True
                self._status_before_pause = "STUDY" if self.mode=="study" else "BREAK"
                self.lbl_status.config(text="PAUSE")
                self.btn_start.config(text="Resume")
        else:
            if self.mode in ("study","break"):
                self.phase_end_monot = time.monotonic() + self.paused_left
                self.paused = False
                self.lbl_status.config(text=self._status_before_pause)
                self.btn_start.config(text="Pause")

    # ---------- Reset ----------
    def on_reset(self):
        if self.total_sessions <= 0:
            vals = self._read_settings()
            if vals:
                self.total_sessions, self.pomo_min, self.short_min, self.long_min = vals
        self.mode = "idle"; self.paused = False; self.done_pomodoros = 0
        self.lbl_status.config(text="READY")
        self._status_before_pause = "READY"
        self._render_bottom_static("00:00")
        self.btn_start.config(text="Start")

    # ---------- 读取设置 ----------
    def _read_settings(self):
        try:
            s  = int(self.var_sessions.get().strip())
            p  = int(self.var_pomo_min.get().strip())
            sb = int(self.var_short_min.get().strip())
            lb = int(self.var_long_min.get().strip())
        except Exception:
            messagebox.showerror("Invalid input", "请输入整数。"); return None
        if not (1 <= s <= 20):
            messagebox.showerror("Invalid Sessions", "Sessions 需为 1~20。"); return None
        if p<=0 or sb<=0 or lb<=0:
            messagebox.showerror("Invalid minutes", "各时长需为正整数（分钟）。"); return None
        return s,p,sb,lb

    # ---------- 阶段切换 ----------
    def _enter_study(self):
        self.mode="study"; self.lbl_status.config(text="STUDY")
        self._status_before_pause = "STUDY"
        dur = self.pomo_min*60
        self.phase_end_monot = time.monotonic() + dur; self.paused=False
        self._render_bottom_dynamic(self.done_pomodoros+1, dur)

    def _enter_break(self):
        self.mode="break"; self.lbl_status.config(text="BREAK")
        self._status_before_pause = "BREAK"
        dur = (self.long_min if self.done_pomodoros % 5 == 0 else self.short_min)*60
        self.phase_end_monot = time.monotonic() + dur; self.paused=False
        self._render_bottom_dynamic(self.done_pomodoros, dur)

    def _advance_phase(self):
        if self.mode=="study":
            self.done_pomodoros += 1
            if self.done_pomodoros >= self.total_sessions:
                self.mode="idle"; self.lbl_status.config(text="READY")
                self._status_before_pause = "READY"
                self._render_bottom_static("00:00"); self.btn_start.config(text="Start")
                return
            self._enter_break()
        elif self.mode=="break":
            self._enter_study()

    # ---------- 行2渲染 ----------
    def _render_bottom_dynamic(self, numerator: int, total_seconds: int):
        self.lbl_bottom.config(
            text=f"{fmt_progress(numerator, self.total_sessions)}    {fmt_mm_ss(total_seconds)}"
        )
    def _update_bottom_with_left(self, left_seconds: int):
        numerator = self.done_pomodoros + (1 if self.mode=="study" else 0)
        self.lbl_bottom.config(
            text=f"{fmt_progress(numerator, self.total_sessions)}    {fmt_mm_ss(left_seconds)}"
        )
    def _render_bottom_static(self, mmss: str):
        self.lbl_bottom.config(
            text=f"{fmt_progress(self.done_pomodoros, self.total_sessions)}    {mmss}"
        )

    def destroy(self):
        try:
            if self._hb_id: self.after_cancel(self._hb_id)
        except Exception: pass
        super().destroy()

if __name__ == "__main__":
    app = PomodoroApp()
    app.mainloop()
