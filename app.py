#!/usr/bin/env python3
"""Agnes AI 创作工具 - GUI 版 v2.0"""

import io
import json
import os
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from urllib import error, parse, request

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

API_BASE = "https://apihub.agnes-ai.com"
IMAGE_MODEL = "agnes-image-2.1-flash"
VIDEO_MODEL = "agnes-video-v2.0"
CHAT_MODEL = "agnes-2.0-flash"


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


APP_DIR = _app_dir()
OUTPUT_DIR = APP_DIR / "output"

BG = "#1e1e2e"
FG = "#cdd6f4"
ACCENT = "#89b4fa"
ACCENT_HOVER = "#74c7ec"
SURFACE = "#313244"
SURFACE2 = "#45475a"
GREEN = "#a6e3a1"
RED = "#f38ba8"
YELLOW = "#f9e2af"
MANTLE = "#181825"
PLACEHOLDER_COLOR = "#585b70"
OVERLAY_BG = "#11111b"

SIZE_PRESETS = [
    "1024x1024", "1024x768", "768x1024", "1280x720", "720x1280",
    "1536x1024", "1024x1536", "1920x1080", "1080x1920",
]


def load_api_keys() -> list[str]:
    keys = []
    env_file = APP_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                _, v = line.split("=", 1)
                v = v.strip().strip("'\"")
                if v and v not in keys:
                    keys.append(v)
    for var in ("AGNES_API_KEY", "AGNES_TOKEN"):
        val = os.environ.get(var, "").strip()
        if val and val not in keys:
            keys.append(val)
    return keys


def api_request(method: str, path: str, api_key: str, payload: dict | None = None) -> dict:
    url = f"{API_BASE}{path}"
    headers = {"Authorization": f"Bearer {api_key}"}
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=data, headers=headers, method=method)
    with request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8"))


def download_file(url: str, output_dir: Path, default_name: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    name = Path(parse.urlparse(url).path).name
    if not name or "." not in name:
        name = default_name
    path = output_dir / name
    with request.urlopen(url, timeout=600) as resp:
        path.write_bytes(resp.read())
    return path


def download_bytes(url: str) -> bytes:
    with request.urlopen(url, timeout=60) as resp:
        return resp.read()


def extract_urls(data) -> list[str]:
    if isinstance(data, dict):
        for k, v in data.items():
            if k == "url" and isinstance(v, str) and v.startswith("http"):
                return [v]
            if k == "data" and isinstance(v, list):
                for item in v:
                    if isinstance(item, dict) and "url" in item:
                        u = item["url"]
                        if isinstance(u, str) and u.startswith("http"):
                            return [u]
            result = extract_urls(v)
            if result:
                return result
    elif isinstance(data, list):
        for item in data:
            result = extract_urls(item)
            if result:
                return result
    return []


def open_folder(path: Path):
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        os.system(f'open "{path}"')
    else:
        os.system(f'xdg-open "{path}"')


class PlaceholderEntry(tk.Entry):
    def __init__(self, master, placeholder="", **kw):
        super().__init__(master, **kw)
        self.placeholder = placeholder
        self._has_placeholder = False
        self._real_fg = kw.get("foreground", FG)
        if placeholder:
            self._show_placeholder()
            self.bind("<FocusIn>", self._on_focus_in)
            self.bind("<FocusOut>", self._on_focus_out)

    def _show_placeholder(self):
        if not self.get():
            self._has_placeholder = True
            self.insert(0, self.placeholder)
            self.configure(foreground=PLACEHOLDER_COLOR)

    def _on_focus_in(self, _):
        if self._has_placeholder:
            self.delete(0, "end")
            self.configure(foreground=self._real_fg)
            self._has_placeholder = False

    def _on_focus_out(self, _):
        if not self.get():
            self._show_placeholder()

    def get_value(self) -> str:
        if self._has_placeholder:
            return ""
        return self.get().strip()


class ScrollableFrame(tk.Frame):
    def __init__(self, parent, bg=BG, **kw):
        super().__init__(parent, bg=bg, **kw)
        canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.inner = tk.Frame(canvas, bg=bg)

        self.inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))
        canvas.bind_all("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
        canvas.bind_all("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))


class AgnesApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Agnes AI 创作工具")
        self.root.geometry("1080x720")
        self.root.minsize(860, 560)
        self.root.configure(bg=BG)

        self.api_keys = load_api_keys()
        self.current_key = tk.StringVar(value=self.api_keys[0] if self.api_keys else "")
        self.current_page = "image"
        self._last_image_urls: list[str] = []
        self._last_video_url: str | None = None
        self._preview_photo = None

        self._apply_style()
        self._build_layout()
        self._show_page("image")
        self._bind_shortcuts()

        if not self.api_keys:
            self.root.after(300, lambda: messagebox.showwarning(
                "API Key", "未找到 API Key，请在设置中配置。\n\n"
                "获取地址: https://platform.agnes-ai.com/settings/apiKeys"
            ))

    def _apply_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=FG, fieldbackground=SURFACE, borderwidth=0)
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG, font=("Segoe UI", 10))
        style.configure("TButton", background=SURFACE, foreground=FG, font=("Segoe UI", 10), padding=(12, 6))
        style.map("TButton", background=[("active", SURFACE2)])
        style.configure("TCombobox", fieldbackground=SURFACE, foreground=FG, padding=6)
        style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=SURFACE)
        style.configure("TScrollbar", background=SURFACE, troughcolor=MANTLE)

    def _build_layout(self):
        sidebar = tk.Frame(self.root, bg=MANTLE, width=200)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        tk.Label(sidebar, text="Agnes AI", bg=MANTLE, fg=ACCENT, font=("Segoe UI", 16, "bold")).pack(
            pady=(24, 20), padx=16, anchor="w"
        )

        self.nav_buttons = {}
        nav_items = [
            ("image", "🖼  图片生成"),
            ("video", "🎬  视频生成"),
            ("gallery", "🎨  画廊"),
            ("chat", "💬  AI 对话"),
            ("settings", "⚙  设置"),
        ]
        for key, label in nav_items:
            btn = tk.Button(
                sidebar, text=label, bg=MANTLE, fg=FG, font=("Segoe UI", 11),
                relief="flat", anchor="w", padx=20, pady=10, cursor="hand2",
                activebackground=SURFACE, activeforeground=FG,
                command=lambda k=key: self._show_page(k),
            )
            btn.pack(fill="x", padx=8, pady=2)
            btn.bind("<Enter>", lambda e, b=btn: b.configure(bg=SURFACE))
            btn.bind("<Leave>", lambda e, b=btn, k=key: b.configure(
                bg=ACCENT if k == self.current_page else MANTLE
            ))
            self.nav_buttons[key] = btn

        key_frame = tk.Frame(sidebar, bg=MANTLE)
        key_frame.pack(side="bottom", fill="x", padx=16, pady=16)
        tk.Label(key_frame, text="当前 Key:", bg=MANTLE, fg=SURFACE2, font=("Segoe UI", 8)).pack(anchor="w")
        self.key_label = tk.Label(key_frame, text="", bg=MANTLE, fg=GREEN, font=("Segoe UI", 9))
        self.key_label.pack(anchor="w")
        self._update_key_label()

        self.content = tk.Frame(self.root, bg=BG)
        self.content.pack(side="right", fill="both", expand=True)

    def _update_key_label(self):
        key = self.current_key.get()
        self.key_label.configure(text=f"{key[:8]}...{key[-4:]}" if key else "未配置")

    def _bind_shortcuts(self):
        self.root.bind("<Control-Return>", lambda e: self._on_ctrl_enter())
        self.root.bind("<Control-s>", lambda e: self._show_page("settings"))

    def _on_ctrl_enter(self):
        if self.current_page == "image":
            self._run_image_gen()
        elif self.current_page == "video":
            self._run_video_gen()
        elif self.current_page == "chat":
            self._send_chat()

    def _show_page(self, name: str):
        self.current_page = name
        for key, btn in self.nav_buttons.items():
            if key == name:
                btn.configure(bg=ACCENT, fg=MANTLE, font=("Segoe UI", 11, "bold"))
            else:
                btn.configure(bg=MANTLE, fg=FG, font=("Segoe UI", 11))

        for w in self.content.winfo_children():
            w.destroy()

        {
            "image": self._build_image_page,
            "video": self._build_video_page,
            "gallery": self._build_gallery_page,
            "chat": self._build_chat_page,
            "settings": self._build_settings_page,
        }[name]()

    def _make_field(self, parent, label_text, default="", row=0, width=50):
        tk.Label(parent, text=label_text, bg=BG, fg=FG, font=("Segoe UI", 10)).grid(
            row=row, column=0, sticky="w", padx=(0, 12), pady=6
        )
        entry = PlaceholderEntry(
            parent, placeholder="", bg=SURFACE, fg=FG, insertbackground=FG,
            font=("Segoe UI", 10), relief="flat", width=width,
        )
        entry.grid(row=row, column=1, sticky="ew", pady=6, ipady=6)
        if default:
            entry.insert(0, default)
        parent.columnconfigure(1, weight=1)
        return entry

    def _log(self, widget: scrolledtext.ScrolledText, msg: str, tag: str = "normal"):
        widget.configure(state="normal")
        widget.insert("end", msg + "\n", tag)
        widget.see("end")
        widget.configure(state="disabled")

    def _create_log_widget(self, parent, height=10):
        log = scrolledtext.ScrolledText(
            parent, bg=MANTLE, fg=FG, font=("Consolas", 10),
            relief="flat", state="disabled", wrap="word", height=height,
        )
        log.pack(fill="both", expand=True)
        for tag, color in [("normal", FG), ("success", GREEN), ("error", RED), ("url", ACCENT)]:
            log.tag_configure(tag, foreground=color)
        return log

    def _make_btn(self, parent, text, command, style="primary"):
        bg, fg, bold = SURFACE, FG, False
        if style == "primary":
            bg, fg, bold = ACCENT, MANTLE, True
        elif style == "danger":
            bg, fg = RED, MANTLE
        elif style == "success":
            bg, fg = GREEN, MANTLE
        return tk.Button(
            parent, text=text, bg=bg, fg=fg,
            font=("Segoe UI", 11, "bold" if bold else "normal"),
            relief="flat", padx=24, pady=8, cursor="hand2",
            activebackground=ACCENT_HOVER if style == "primary" else SURFACE2,
            command=command,
        )

    def _run_in_thread(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    def _set_busy(self, btn, busy: bool, label: str, busy_label: str):
        btn.configure(state="disabled" if busy else "normal", text=busy_label if busy else label)

    # ==================== 图片 ====================

    def _build_image_page(self):
        frame = tk.Frame(self.content, bg=BG, padx=32, pady=24)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text="图片生成", bg=BG, fg=ACCENT, font=("Segoe UI", 18, "bold")).pack(anchor="w")

        paned = tk.PanedWindow(frame, bg=BG, sashwidth=4, sashrelief="flat")
        paned.pack(fill="both", expand=True, pady=(12, 0))

        left = tk.Frame(paned, bg=BG)
        paned.add(left, minsize=380)

        form = tk.Frame(left, bg=BG)
        form.pack(fill="x")
        self.img_prompt = self._make_field(form, "图片描述:", row=0)

        size_frame = tk.Frame(form, bg=BG)
        size_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=6)
        tk.Label(size_frame, text="尺寸:", bg=BG, fg=FG, font=("Segoe UI", 10)).pack(side="left", padx=(0, 12))
        self.img_size_var = tk.StringVar(value="1024x768")
        size_combo = ttk.Combobox(size_frame, textvariable=self.img_size_var, values=SIZE_PRESETS, width=12)
        size_combo.pack(side="left", ipady=4)
        self.img_size_entry = PlaceholderEntry(
            size_frame, placeholder="自定义 如 800x600", bg=SURFACE, fg=FG, insertbackground=FG,
            font=("Segoe UI", 10), relief="flat", width=18,
        )
        self.img_size_entry.pack(side="left", padx=(12, 0), ipady=4)

        self.img_ref = self._make_field(form, "参考图片URL:", row=2)

        btn_frame = tk.Frame(left, bg=BG)
        btn_frame.pack(fill="x", pady=(12, 6))
        self.img_btn = self._make_btn(btn_frame, "生成图片  Ctrl+Enter", self._run_image_gen)
        self.img_btn.pack(side="left")
        self.img_download_btn = self._make_btn(btn_frame, "另存为...", self._download_images, "secondary")
        self.img_download_btn.pack(side="left", padx=(8, 0))
        self.img_download_btn.configure(state="disabled")
        self.img_open_btn = self._make_btn(btn_frame, "打开目录", lambda: open_folder(OUTPUT_DIR / "images"), "secondary")
        self.img_open_btn.pack(side="left", padx=(8, 0))

        self.img_status = tk.Label(btn_frame, text="", bg=BG, fg=GREEN, font=("Segoe UI", 10))
        self.img_status.pack(side="right")

        self.img_log = self._create_log_widget(left, height=6)

        right = tk.Frame(paned, bg=SURFACE, relief="flat")
        paned.add(right, minsize=280)

        self.img_preview_label = tk.Label(right, text="预览区", bg=SURFACE, fg=SURFACE2, font=("Segoe UI", 12))
        self.img_preview_label.pack(expand=True)
        self.img_preview_canvas = tk.Label(right, bg=SURFACE)
        self.img_preview_canvas.pack(fill="both", expand=True, padx=8, pady=8)

    def _get_image_size(self) -> str:
        custom = self.img_size_entry.get_value()
        return custom if custom else self.img_size_var.get()

    def _run_image_gen(self):
        if not self.current_key.get():
            messagebox.showwarning("提示", "请先在设置中配置 API Key")
            return
        prompt = self.img_prompt.get_value()
        if not prompt:
            messagebox.showwarning("提示", "请输入图片描述")
            self.img_prompt.focus_set()
            return
        self._set_busy(self.img_btn, True, "生成图片  Ctrl+Enter", "生成中...")
        self.img_status.configure(text="")
        self.img_download_btn.configure(state="disabled")
        self._last_image_urls.clear()
        self._log(self.img_log, f"正在生成: {prompt}")
        self._run_in_thread(self._image_worker)

    def _image_worker(self):
        prompt = self.img_prompt.get_value()
        size = self._get_image_size() or "1024x768"
        ref = self.img_ref.get_value()

        payload: dict = {"model": IMAGE_MODEL, "prompt": prompt, "size": size}
        if ref:
            payload["extra_body"] = {"image": [ref], "response_format": "url"}
        else:
            payload["extra_body"] = {"response_format": "url"}

        t0 = time.time()
        try:
            resp = api_request("POST", "/v1/images/generations", self.current_key.get(), payload)
            elapsed = time.time() - t0
            urls = extract_urls(resp)
            self._last_image_urls = urls
            self.root.after(0, lambda: self._log(self.img_log, f"完成 ({elapsed:.1f}s)", "success"))
            for i, url in enumerate(urls, 1):
                self.root.after(0, lambda u=url, n=i: self._log(self.img_log, f"  图片{n}: {u}", "url"))
            if urls:
                self.root.after(0, lambda: self.img_download_btn.configure(state="normal"))
                self.root.after(0, lambda: self.img_status.configure(text="✓ 生成完成", fg=GREEN))
                self._load_preview(urls[0])
                self._auto_download_images()
            else:
                self.root.after(0, lambda: self._log(self.img_log, json.dumps(resp, ensure_ascii=False, indent=2)))
                self.root.after(0, lambda: self.img_status.configure(text="⚠ 未获取到URL", fg=YELLOW))
        except Exception as e:
            self.root.after(0, lambda: self._log(self.img_log, f"失败: {e}", "error"))
            self.root.after(0, lambda: self.img_status.configure(text="✗ 失败", fg=RED))
        finally:
            self.root.after(0, lambda: self._set_busy(self.img_btn, False, "生成图片  Ctrl+Enter", ""))

    def _load_preview(self, url: str):
        def worker():
            try:
                data = download_bytes(url)
                self.root.after(0, lambda: self._render_preview(data))
            except Exception:
                pass
        self._run_in_thread(worker)

    def _render_preview(self, data: bytes):
        if HAS_PIL:
            img = Image.open(io.BytesIO(data))
            canvas_w = self.img_preview_canvas.winfo_width() or 260
            canvas_h = self.img_preview_canvas.winfo_height() or 260
            img.thumbnail((canvas_w - 16, canvas_h - 16), Image.LANCZOS)
            self._preview_photo = ImageTk.PhotoImage(img)
        else:
            try:
                self._preview_photo = tk.PhotoImage(data=data)
            except tk.TclError:
                self.img_preview_label.configure(text="预览需要安装 Pillow\npip install Pillow")
                return
        self.img_preview_label.pack_forget()
        self.img_preview_canvas.configure(image=self._preview_photo, text="")

    def _auto_download_images(self):
        if not self._last_image_urls:
            return
        save_dir = OUTPUT_DIR / "images"
        save_dir.mkdir(parents=True, exist_ok=True)
        for i, url in enumerate(self._last_image_urls, 1):
            try:
                path = download_file(url, save_dir, f"image_{i}.png")
                self.root.after(0, lambda p=path: self._log(self.img_log, f"  已保存: {p}", "success"))
            except Exception as e:
                self.root.after(0, lambda err=e: self._log(self.img_log, f"  自动下载失败: {err}", "error"))

    def _download_images(self):
        if not self._last_image_urls:
            return
        save_dir = filedialog.askdirectory(title="选择保存目录", initialdir=str(OUTPUT_DIR / "images"))
        if not save_dir:
            return
        self._log(self.img_log, f"下载到: {save_dir}")
        for i, url in enumerate(self._last_image_urls, 1):
            try:
                path = download_file(url, Path(save_dir), f"image_{i}.png")
                self._log(self.img_log, f"  已保存: {path}", "success")
            except Exception as e:
                self._log(self.img_log, f"  下载失败: {e}", "error")

    # ==================== 视频 ====================

    def _build_video_page(self):
        frame = tk.Frame(self.content, bg=BG, padx=32, pady=24)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text="视频生成", bg=BG, fg=ACCENT, font=("Segoe UI", 18, "bold")).pack(anchor="w")

        form = tk.Frame(frame, bg=BG)
        form.pack(fill="x", pady=(12, 0))
        self.vid_prompt = self._make_field(form, "视频描述:", row=0)
        self.vid_ref = self._make_field(form, "图片URL:", row=1)

        res_frame = tk.Frame(form, bg=BG)
        res_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=6)
        tk.Label(res_frame, text="分辨率:", bg=BG, fg=FG, font=("Segoe UI", 10)).pack(side="left", padx=(0, 12))
        self.vid_res_var = tk.StringVar(value="1152x768")
        ttk.Combobox(res_frame, textvariable=self.vid_res_var, values=[
            "1152x768", "1280x720", "1920x1080", "768x1152", "720x1280", "1024x1024",
        ], width=12).pack(side="left", ipady=4)

        tk.Label(form, text="帧数:", bg=BG, fg=FG, font=("Segoe UI", 10)).grid(row=3, column=0, sticky="w", padx=(0, 12), pady=6)
        self.vid_frames = ttk.Combobox(form, values=["81", "121", "161", "241", "441"], state="readonly", width=8)
        self.vid_frames.set("121")
        self.vid_frames.grid(row=3, column=1, sticky="w", pady=6, ipady=4)

        self.vid_fps = self._make_field(form, "帧率:", "24", row=4, width=10)

        btn_frame = tk.Frame(frame, bg=BG)
        btn_frame.pack(fill="x", pady=(16, 8))
        self.vid_btn = self._make_btn(btn_frame, "生成视频  Ctrl+Enter", self._run_video_gen)
        self.vid_btn.pack(side="left")
        self.vid_download_btn = self._make_btn(btn_frame, "另存为...", self._download_video, "secondary")
        self.vid_download_btn.pack(side="left", padx=(8, 0))
        self.vid_download_btn.configure(state="disabled")
        self.vid_status = tk.Label(btn_frame, text="", bg=BG, fg=GREEN, font=("Segoe UI", 10))
        self.vid_status.pack(side="right")

        self.vid_progress = ttk.Progressbar(frame, mode="determinate", length=300, maximum=100)
        self.vid_progress.pack(fill="x", pady=(0, 8))
        self.vid_progress.pack_forget()

        self.vid_log = self._create_log_widget(frame, height=10)

    def _run_video_gen(self):
        if not self.current_key.get():
            messagebox.showwarning("提示", "请先在设置中配置 API Key")
            return
        if not self.vid_prompt.get_value():
            messagebox.showwarning("提示", "请输入视频描述")
            self.vid_prompt.focus_set()
            return
        self._set_busy(self.vid_btn, True, "生成视频  Ctrl+Enter", "提交中...")
        self.vid_status.configure(text="")
        self.vid_download_btn.configure(state="disabled")
        self._last_video_url = None
        self.vid_progress["value"] = 0
        self.vid_progress.pack(fill="x", pady=(0, 8))
        self._log(self.vid_log, f"正在提交: {self.vid_prompt.get_value()}")
        self._run_in_thread(self._video_worker)

    def _video_worker(self):
        prompt = self.vid_prompt.get_value()
        ref = self.vid_ref.get_value()

        res = self.vid_res_var.get()
        try:
            w, h = int(res.split("x")[0]), int(res.split("x")[1])
            frames = int(self.vid_frames.get() or "121")
            fps = float(self.vid_fps.get_value() or "24")
        except ValueError:
            self.root.after(0, lambda: self._log(self.vid_log, "参数格式错误", "error"))
            self.root.after(0, self._video_reset)
            return

        payload: dict = {
            "model": VIDEO_MODEL, "prompt": prompt,
            "width": w, "height": h, "num_frames": frames, "frame_rate": fps,
        }
        if ref:
            payload["image"] = ref

        t0 = time.time()
        try:
            resp = api_request("POST", "/v1/videos", self.current_key.get(), payload)
        except Exception as e:
            self.root.after(0, lambda: self._log(self.vid_log, f"提交失败: {e}", "error"))
            self.root.after(0, self._video_reset)
            return

        task_id = resp.get("id") or resp.get("task_id") or resp.get("data", {}).get("id")
        if not task_id:
            self.root.after(0, lambda: self._log(self.vid_log, f"无法获取任务ID: {json.dumps(resp, ensure_ascii=False)}", "error"))
            self.root.after(0, self._video_reset)
            return

        self.root.after(0, lambda: self._log(self.vid_log, f"任务ID: {task_id}"))
        self.root.after(0, lambda: self.vid_btn.configure(text="等待生成..."))

        poll_interval = 3
        max_wait = 600
        while True:
            time.sleep(poll_interval)
            elapsed = time.time() - t0

            if elapsed > max_wait:
                self.root.after(0, lambda: self._log(self.vid_log, f"超时 ({max_wait}s)，请稍后在画廊中查看", "error"))
                self.root.after(0, self._video_reset)
                return

            try:
                status_resp = api_request("GET", f"/v1/videos/{parse.quote(task_id)}", self.current_key.get())
            except Exception as e:
                self.root.after(0, lambda: self._log(self.vid_log, f"查询失败: {e}", "error"))
                self.root.after(0, self._video_reset)
                return

            status = (status_resp.get("status") or status_resp.get("data", {}).get("status", "")).lower()
            progress = status_resp.get("progress") or status_resp.get("data", {}).get("progress")

            if progress is not None:
                try:
                    pct = int(float(progress))
                    self.root.after(0, lambda p=pct: self.vid_progress.configure(value=p))
                except (ValueError, TypeError):
                    pass

            if status in ("completed", "succeeded", "success"):
                video_url = self._find_video_url(status_resp)
                self._last_video_url = video_url
                self.root.after(0, lambda: self.vid_progress.configure(value=100))
                self.root.after(0, lambda: self._log(self.vid_log, f"完成 ({elapsed:.1f}s)", "success"))
                if video_url:
                    self.root.after(0, lambda u=video_url: self._log(self.vid_log, f"  视频: {u}", "url"))
                    self.root.after(0, lambda: self.vid_download_btn.configure(state="normal"))
                    self.root.after(0, lambda: self.vid_status.configure(text="✓ 生成完成", fg=GREEN))
                    self._auto_download_video()
                self.root.after(0, self._video_reset)
                return

            if status in ("failed", "cancelled", "error"):
                err = status_resp.get("error", {})
                msg = err.get("message", "未知错误") if isinstance(err, dict) else str(err)
                self.root.after(0, lambda: self._log(self.vid_log, f"失败 ({elapsed:.1f}s): {msg}", "error"))
                self.root.after(0, lambda: self.vid_status.configure(text="✗ 失败", fg=RED))
                self.root.after(0, self._video_reset)
                return

            mins, secs = divmod(int(elapsed), 60)
            self.root.after(0, lambda m=mins, s=secs: self.vid_status.configure(
                text=f"生成中... {m:02d}:{s:02d}", fg=YELLOW
            ))

    def _find_video_url(self, resp: dict) -> str | None:
        for key in ("video_url", "url"):
            val = resp.get(key) or resp.get("data", {}).get(key)
            if isinstance(val, str) and val.startswith("http"):
                return val
        return None

    def _video_reset(self):
        self._set_busy(self.vid_btn, False, "生成视频  Ctrl+Enter", "")
        self.root.after(3000, lambda: self.vid_progress.pack_forget())

    def _auto_download_video(self):
        if not self._last_video_url:
            return
        save_dir = OUTPUT_DIR / "videos"
        save_dir.mkdir(parents=True, exist_ok=True)
        try:
            path = download_file(self._last_video_url, save_dir, "video.mp4")
            self.root.after(0, lambda: self._log(self.vid_log, f"  已保存: {path}", "success"))
        except Exception as e:
            self.root.after(0, lambda: self._log(self.vid_log, f"  自动下载失败: {e}", "error"))

    def _download_video(self):
        if not self._last_video_url:
            return
        save_dir = filedialog.askdirectory(title="选择保存目录", initialdir=str(OUTPUT_DIR / "videos"))
        if not save_dir:
            return
        self._log(self.vid_log, f"下载到: {save_dir}")
        try:
            path = download_file(self._last_video_url, Path(save_dir), "video.mp4")
            self._log(self.vid_log, f"  已保存: {path}", "success")
        except Exception as e:
            self._log(self.vid_log, f"  下载失败: {e}", "error")

    # ==================== 画廊 ====================

    def _build_gallery_page(self):
        frame = tk.Frame(self.content, bg=BG, padx=32, pady=24)
        frame.pack(fill="both", expand=True)

        header = tk.Frame(frame, bg=BG)
        header.pack(fill="x", pady=(0, 12))
        tk.Label(header, text="画廊", bg=BG, fg=ACCENT, font=("Segoe UI", 18, "bold")).pack(side="left")
        self._make_btn(header, "刷新", self._refresh_gallery, "secondary").pack(side="right")
        self._make_btn(header, "打开目录", lambda: open_folder(OUTPUT_DIR), "secondary").pack(side="right", padx=(0, 8))

        self.gallery_canvas = tk.Canvas(frame, bg=BG, highlightthickness=0)
        gallery_scroll = ttk.Scrollbar(frame, orient="vertical", command=self.gallery_canvas.yview)
        self.gallery_inner = tk.Frame(self.gallery_canvas, bg=BG)

        self.gallery_inner.bind("<Configure>", lambda e: self.gallery_canvas.configure(
            scrollregion=self.gallery_canvas.bbox("all")
        ))
        self.gallery_canvas.create_window((0, 0), window=self.gallery_inner, anchor="nw")
        self.gallery_canvas.configure(yscrollcommand=gallery_scroll.set)

        self.gallery_canvas.pack(side="left", fill="both", expand=True)
        gallery_scroll.pack(side="right", fill="y")

        self.gallery_canvas.bind_all("<MouseWheel>",
            lambda e: self.gallery_canvas.yview_scroll(-1 * (e.delta // 120), "units"))
        self.gallery_canvas.bind_all("<Button-4>",
            lambda e: self.gallery_canvas.yview_scroll(-1, "units"))
        self.gallery_canvas.bind_all("<Button-5>",
            lambda e: self.gallery_canvas.yview_scroll(1, "units"))

        self._gallery_photos = []
        self._refresh_gallery()

    def _refresh_gallery(self):
        for w in self.gallery_inner.winfo_children():
            w.destroy()
        self._gallery_photos.clear()

        files = []
        for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.gif", "*.mp4"):
            files.extend((OUTPUT_DIR / "images").glob(ext))
            files.extend((OUTPUT_DIR / "videos").glob(ext))
        files.sort(key=lambda f: f.stat().st_mtime, reverse=True)

        if not files:
            tk.Label(self.gallery_inner, text="暂无生成记录\n\n图片和视频会自动保存到 output/ 目录",
                     bg=BG, fg=SURFACE2, font=("Segoe UI", 12), justify="center").pack(expand=True, pady=60)
            return

        cols = 4
        for i, fpath in enumerate(files):
            row, col = divmod(i, cols)
            card = tk.Frame(self.gallery_inner, bg=SURFACE, relief="flat", padx=6, pady=6)
            card.grid(row=row, column=col, padx=6, pady=6, sticky="nsew")

            if fpath.suffix.lower() == ".mp4":
                tk.Label(card, text="🎬 视频", bg=SURFACE, fg=FG, font=("Segoe UI", 14)).pack(pady=20)
            else:
                self._load_thumb(card, fpath)

            name_label = tk.Label(card, text=fpath.name, bg=SURFACE, fg=FG, font=("Segoe UI", 8),
                                   wraplength=160, justify="center")
            name_label.pack(pady=(4, 2))

            btn_row = tk.Frame(card, bg=SURFACE)
            btn_row.pack()
            tk.Button(btn_row, text="打开", bg=ACCENT, fg=MANTLE, font=("Segoe UI", 8), relief="flat",
                      padx=8, pady=2, cursor="hand2",
                      command=lambda p=fpath: open_folder(p) if p.is_dir() else os.startfile(str(p)) if sys.platform == "win32" else os.system(f'open "{p}"' if sys.platform == "darwin" else f'xdg-open "{p}"')
                      ).pack(side="left", padx=2)

        for c in range(cols):
            self.gallery_inner.columnconfigure(c, weight=1)

    def _load_thumb(self, parent, path: Path):
        def worker():
            try:
                if HAS_PIL:
                    img = Image.open(path)
                    img.thumbnail((160, 120), Image.LANCZOS)
                    photo = ImageTk.PhotoImage(img)
                else:
                    photo = tk.PhotoImage(file=str(path))
                self.root.after(0, lambda: self._set_thumb(parent, photo))
            except Exception:
                self.root.after(0, lambda: tk.Label(
                    parent, text="预览不可用", bg=SURFACE, fg=SURFACE2, font=("Segoe UI", 9)
                ).pack(pady=20))
        self._run_in_thread(worker)

    def _set_thumb(self, parent, photo):
        self._gallery_photos.append(photo)
        lbl = tk.Label(parent, image=photo, bg=SURFACE)
        lbl.pack()

    # ==================== 聊天 ====================

    def _build_chat_page(self):
        frame = tk.Frame(self.content, bg=BG, padx=32, pady=24)
        frame.pack(fill="both", expand=True)

        header = tk.Frame(frame, bg=BG)
        header.pack(fill="x", pady=(0, 12))
        tk.Label(header, text="AI 对话", bg=BG, fg=ACCENT, font=("Segoe UI", 18, "bold")).pack(side="left")
        self._make_btn(header, "清空对话", self._clear_chat, "secondary").pack(side="right")

        self.chat_messages: list[dict] = [{"role": "system", "content": "你是一个友好的AI助手，用简洁清晰的中文回答。"}]

        self.chat_display = scrolledtext.ScrolledText(
            frame, bg=MANTLE, fg=FG, font=("Consolas", 11), relief="flat", state="disabled", wrap="word",
        )
        self.chat_display.pack(fill="both", expand=True, pady=(0, 12))
        self.chat_display.tag_configure("user", foreground=ACCENT, font=("Consolas", 11, "bold"))
        self.chat_display.tag_configure("ai", foreground=GREEN)
        self.chat_display.tag_configure("sys", foreground=SURFACE2, font=("Consolas", 9))

        input_frame = tk.Frame(frame, bg=BG)
        input_frame.pack(fill="x")
        self.chat_input = tk.Entry(input_frame, bg=SURFACE, fg=FG, insertbackground=FG, font=("Segoe UI", 11), relief="flat")
        self.chat_input.pack(side="left", fill="x", expand=True, ipady=8, padx=(0, 8))
        self.chat_input.bind("<Return>", self._send_chat)
        self.chat_btn = self._make_btn(input_frame, "发送", self._send_chat)
        self.chat_btn.pack(side="right")

        self._chat_append("欢迎使用 Agnes AI 对话！输入消息开始聊天。\n\n", "sys")

    def _clear_chat(self):
        self.chat_messages.clear()
        self.chat_messages.append({"role": "system", "content": "你是一个友好的AI助手，用简洁清晰的中文回答。"})
        self.chat_display.configure(state="normal")
        self.chat_display.delete("1.0", "end")
        self.chat_display.configure(state="disabled")
        self._chat_append("对话已清空。\n\n", "sys")

    def _send_chat(self, _=None):
        if not self.current_key.get():
            messagebox.showwarning("提示", "请先在设置中配置 API Key")
            return
        user_text = self.chat_input.get().strip()
        if not user_text:
            return
        self.chat_input.delete(0, "end")
        self._chat_append(f"你: {user_text}\n", "user")
        self.chat_messages.append({"role": "user", "content": user_text})
        self._set_busy(self.chat_btn, True, "发送", "回复中...")
        self._run_in_thread(self._chat_worker)

    def _chat_worker(self):
        payload = {"model": CHAT_MODEL, "messages": self.chat_messages, "stream": True, "temperature": 0.7}
        req = request.Request(
            f"{API_BASE}/v1/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.current_key.get()}", "Content-Type": "application/json"},
            method="POST",
        )

        self.root.after(0, lambda: self._chat_append("AI: ", "ai"))
        full: list[str] = []
        try:
            with request.urlopen(req, timeout=120) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data: "):
                        continue
                    ds = line[6:]
                    if ds == "[DONE]":
                        break
                    try:
                        c = json.loads(ds).get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if c:
                            full.append(c)
                            self.root.after(0, lambda t=c: self._chat_append(t, "ai"))
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            self.root.after(0, lambda: self._chat_append(f"\n请求失败: {e}\n", "sys"))

        self.root.after(0, lambda: self._chat_append("\n", "ai"))
        self.chat_messages.append({"role": "assistant", "content": "".join(full)})
        self.root.after(0, lambda: self._set_busy(self.chat_btn, False, "发送", ""))

    def _chat_append(self, text: str, tag: str):
        self.chat_display.configure(state="normal")
        self.chat_display.insert("end", text, tag)
        self.chat_display.see("end")
        self.chat_display.configure(state="disabled")

    # ==================== 设置 ====================

    def _build_settings_page(self):
        scroll = ScrollableFrame(self.content, bg=BG)
        scroll.pack(fill="both", expand=True)
        frame = scroll.inner
        frame.configure(padx=32, pady=24)

        tk.Label(frame, text="设置", bg=BG, fg=ACCENT, font=("Segoe UI", 18, "bold")).pack(anchor="w")
        tk.Label(frame, text="管理 API Key 和输出目录", bg=BG, fg=SURFACE2, font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 16))

        key_frame = tk.LabelFrame(frame, text=" API Key 管理 ", bg=BG, fg=FG, font=("Segoe UI", 11), padx=16, pady=12)
        key_frame.pack(fill="x", pady=(0, 16))

        add_frame = tk.Frame(key_frame, bg=BG)
        add_frame.pack(fill="x", pady=(0, 8))
        self.settings_key_entry = tk.Entry(add_frame, bg=SURFACE, fg=FG, insertbackground=FG,
                                            font=("Consolas", 10), relief="flat", show="*")
        self.settings_key_entry.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 8))
        self.settings_key_entry.bind("<Return>", lambda e: self._add_key())
        tk.Button(add_frame, text="添加", bg=GREEN, fg=MANTLE, font=("Segoe UI", 10, "bold"),
                  relief="flat", padx=16, pady=4, cursor="hand2", command=self._add_key).pack(side="left")

        self.key_list_frame = tk.Frame(key_frame, bg=BG)
        self.key_list_frame.pack(fill="x")
        self._refresh_key_list()

        test_frame = tk.Frame(key_frame, bg=BG)
        test_frame.pack(fill="x", pady=(8, 0))
        self._make_btn(test_frame, "测试当前 Key", self._test_api_key, "secondary").pack(side="left")
        self.test_status = tk.Label(test_frame, text="", bg=BG, fg=FG, font=("Segoe UI", 10))
        self.test_status.pack(side="left", padx=(12, 0))

        dir_frame = tk.LabelFrame(frame, text=" 输出目录 ", bg=BG, fg=FG, font=("Segoe UI", 11), padx=16, pady=12)
        dir_frame.pack(fill="x", pady=(0, 16))
        dir_inner = tk.Frame(dir_frame, bg=BG)
        dir_inner.pack(fill="x")
        self.settings_dir_var = tk.StringVar(value=str(OUTPUT_DIR))
        tk.Entry(dir_inner, textvariable=self.settings_dir_var, bg=SURFACE, fg=FG, insertbackground=FG,
                 font=("Consolas", 10), relief="flat").pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 8))
        self._make_btn(dir_inner, "浏览", self._browse_output_dir, "secondary").pack(side="left")

        info_frame = tk.LabelFrame(frame, text=" 关于 ", bg=BG, fg=FG, font=("Segoe UI", 11), padx=16, pady=12)
        info_frame.pack(fill="x", pady=(0, 16))
        tk.Label(info_frame, text="Agnes AI 创作工具 v2.0", bg=BG, fg=FG, font=("Segoe UI", 10, "bold")).pack(anchor="w")
        tk.Label(info_frame, text="快捷键: Ctrl+Enter 生成 | Ctrl+S 设置", bg=BG, fg=SURFACE2, font=("Segoe UI", 9)).pack(anchor="w", pady=(4, 0))
        tk.Label(info_frame, text="API: https://apihub.agnes-ai.com", bg=BG, fg=SURFACE2, font=("Segoe UI", 9)).pack(anchor="w")
        tk.Label(info_frame, text="获取 Key: https://platform.agnes-ai.com/settings/apiKeys", bg=BG, fg=ACCENT, font=("Segoe UI", 9), cursor="hand2").pack(anchor="w")

        dep_frame = tk.LabelFrame(frame, text=" 依赖 ", bg=BG, fg=FG, font=("Segoe UI", 11), padx=16, pady=12)
        dep_frame.pack(fill="x")
        pil_status = "✓ 已安装 (支持所有格式预览)" if HAS_PIL else "✗ 未安装 (仅支持 PNG/GIF 预览)"
        pil_color = GREEN if HAS_PIL else YELLOW
        tk.Label(dep_frame, text=f"Pillow: {pil_status}", bg=BG, fg=pil_color, font=("Segoe UI", 9)).pack(anchor="w")
        if not HAS_PIL:
            tk.Label(dep_frame, text="安装命令: pip install Pillow", bg=BG, fg=SURFACE2, font=("Consolas", 9)).pack(anchor="w", pady=(2, 0))

    def _add_key(self):
        key = self.settings_key_entry.get().strip()
        if not key:
            return
        if key in self.api_keys:
            messagebox.showinfo("提示", "该 Key 已存在")
            return
        self.api_keys.append(key)
        env_file = APP_DIR / ".env"
        with open(env_file, "a") as f:
            f.write(f"\nAGNES_API_KEY={key}\n")
        self.settings_key_entry.delete(0, "end")
        self._refresh_key_list()
        if not self.current_key.get():
            self.current_key.set(key)
            self._update_key_label()

    def _refresh_key_list(self):
        for w in self.key_list_frame.winfo_children():
            w.destroy()
        if not self.api_keys:
            tk.Label(self.key_list_frame, text="暂无 API Key，请添加", bg=BG, fg=SURFACE2, font=("Segoe UI", 9)).pack(anchor="w")
            return
        for key in self.api_keys:
            row = tk.Frame(self.key_list_frame, bg=BG)
            row.pack(fill="x", pady=2)
            masked = f"{key[:8]}...{key[-4:]}"
            is_current = key == self.current_key.get()
            fg = GREEN if is_current else FG
            prefix = "● " if is_current else "  "
            tk.Label(row, text=f"{prefix}{masked}", bg=BG, fg=fg, font=("Consolas", 10)).pack(side="left")
            if not is_current:
                tk.Button(row, text="使用", bg=SURFACE, fg=FG, font=("Segoe UI", 9), relief="flat",
                          padx=8, pady=2, cursor="hand2", command=lambda k=key: self._select_key(k)).pack(side="right", padx=(4, 0))
            tk.Button(row, text="删除", bg=SURFACE, fg=RED, font=("Segoe UI", 9), relief="flat",
                      padx=8, pady=2, cursor="hand2", command=lambda k=key: self._remove_key(k)).pack(side="right")

    def _select_key(self, key: str):
        self.current_key.set(key)
        self._update_key_label()
        self._refresh_key_list()

    def _remove_key(self, key: str):
        self.api_keys.remove(key)
        if self.current_key.get() == key:
            self.current_key.set(self.api_keys[0] if self.api_keys else "")
            self._update_key_label()
        env_file = APP_DIR / ".env"
        if env_file.exists():
            lines = env_file.read_text().splitlines()
            env_file.write_text("\n".join(l for l in lines if key not in l) + "\n")
        self._refresh_key_list()

    def _test_api_key(self):
        key = self.current_key.get()
        if not key:
            self.test_status.configure(text="✗ 未配置 Key", fg=RED)
            return
        self.test_status.configure(text="测试中...", fg=YELLOW)
        self.root.update()

        def worker():
            try:
                api_request("POST", "/v1/chat/completions", key, {
                    "model": CHAT_MODEL, "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 5,
                })
                self.root.after(0, lambda: self.test_status.configure(text="✓ Key 有效", fg=GREEN))
            except Exception as e:
                self.root.after(0, lambda: self.test_status.configure(text=f"✗ {e}", fg=RED))
        self._run_in_thread(worker)

    def _browse_output_dir(self):
        d = filedialog.askdirectory(initialdir=self.settings_dir_var.get())
        if d:
            self.settings_dir_var.set(d)
            global OUTPUT_DIR
            OUTPUT_DIR = Path(d)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    AgnesApp().run()
