#!/usr/bin/env python3
"""Agnes AI 创作工具 - GUI 版"""

import json
import os
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from urllib import error, parse, request

API_BASE = "https://apihub.agnes-ai.com"
IMAGE_MODEL = "agnes-image-2.1-flash"
VIDEO_MODEL = "agnes-video-v2.0"

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

PLACEHOLDER_MAP = {
    "图片描述": "一只戴墨镜的猫坐在沙滩上",
    "参考图片URL": "https://example.com/ref.png",
    "尺寸": "1024x768",
    "视频描述": "夕阳下海浪拍打沙滩",
    "图片URL": "https://example.com/image.png",
    "宽度": "1152",
    "高度": "768",
    "帧率": "24",
}


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


def get_placeholder(label: str) -> str:
    for key, val in PLACEHOLDER_MAP.items():
        if key in label:
            return val
    return ""


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


class AgnesApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Agnes AI 创作工具")
        self.root.geometry("960x640")
        self.root.minsize(800, 500)
        self.root.configure(bg=BG)

        self.api_keys = load_api_keys()
        self.current_key = tk.StringVar(value=self.api_keys[0] if self.api_keys else "")
        self.current_page = "image"
        self._last_image_urls: list[str] = []
        self._last_video_url: str | None = None
        self._busy = False

        self._apply_style()
        self._build_layout()
        self._show_page("image")

        if not self.api_keys:
            self.root.after(300, lambda: messagebox.showwarning(
                "API Key", "未找到 API Key，请在设置中配置。\n\n获取地址: https://platform.agnes-ai.com/settings/apiKeys"
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

    def _build_layout(self):
        sidebar = tk.Frame(self.root, bg=MANTLE, width=200)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        tk.Label(sidebar, text="Agnes AI", bg=MANTLE, fg=ACCENT, font=("Segoe UI", 16, "bold")).pack(
            pady=(24, 20), padx=16, anchor="w"
        )

        self.nav_buttons = {}
        for key, label in [
            ("image", "🖼  图片生成"),
            ("video", "🎬  视频生成"),
            ("chat", "💬  AI 对话"),
            ("settings", "⚙  设置"),
        ]:
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
            "chat": self._build_chat_page,
            "settings": self._build_settings_page,
        }[name]()

    def _make_field(self, parent, label_text, default="", row=0, width=50):
        tk.Label(parent, text=label_text, bg=BG, fg=FG, font=("Segoe UI", 10)).grid(
            row=row, column=0, sticky="w", padx=(0, 12), pady=6
        )
        placeholder = get_placeholder(label_text)
        entry = PlaceholderEntry(
            parent, placeholder=placeholder, bg=SURFACE, fg=FG, insertbackground=FG,
            font=("Segoe UI", 10), relief="flat", width=width,
        )
        entry.grid(row=row, column=1, sticky="ew", pady=6, ipady=6)
        if default:
            entry.insert(0, default)
            entry._has_placeholder = False
            entry.configure(foreground=FG)
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

    def _make_action_btn(self, parent, text, command, style="primary"):
        bg, fg = (ACCENT, MANTLE) if style == "primary" else (SURFACE, FG)
        return tk.Button(
            parent, text=text, bg=bg, fg=fg, font=("Segoe UI", 11, "bold" if style == "primary" else "normal"),
            relief="flat", padx=24, pady=8, cursor="hand2",
            activebackground=ACCENT_HOVER if style == "primary" else SURFACE2,
            command=command,
        )

    def _run_in_thread(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    def _set_busy(self, btn, busy: bool, label: str, busy_label: str):
        self._busy = busy
        btn.configure(state="disabled" if busy else "normal", text=busy_label if busy else label)

    # ==================== 图片 ====================

    def _build_image_page(self):
        frame = tk.Frame(self.content, bg=BG, padx=32, pady=24)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text="图片生成", bg=BG, fg=ACCENT, font=("Segoe UI", 18, "bold")).pack(anchor="w")
        tk.Label(frame, text="输入描述，AI 生成图片", bg=BG, fg=SURFACE2, font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 16))

        form = tk.Frame(frame, bg=BG)
        form.pack(fill="x")
        self.img_prompt = self._make_field(form, "图片描述:", row=0)
        self.img_size = self._make_field(form, "尺寸:", "1024x768", row=1)
        self.img_ref = self._make_field(form, "参考图片URL:", row=2)

        btn_frame = tk.Frame(frame, bg=BG)
        btn_frame.pack(fill="x", pady=(16, 8))
        self.img_btn = self._make_action_btn(btn_frame, "生成图片", self._run_image_gen)
        self.img_btn.pack(side="left")
        self.img_download_btn = self._make_action_btn(btn_frame, "下载图片", self._download_images, "secondary")
        self.img_download_btn.pack(side="left", padx=(12, 0))
        self.img_download_btn.configure(state="disabled")
        self.img_status = tk.Label(btn_frame, text="", bg=BG, fg=GREEN, font=("Segoe UI", 10))
        self.img_status.pack(side="left", padx=(16, 0))
        self.img_log = self._create_log_widget(tk.Frame(frame, bg=BG).pack(fill="both", expand=True, pady=(8, 0)) or frame.winfo_children()[-1])

    def _run_image_gen(self):
        if not self.current_key.get():
            messagebox.showwarning("提示", "请先在设置中配置 API Key")
            return
        if not self.img_prompt.get_value():
            messagebox.showwarning("提示", "请输入图片描述")
            return
        self._set_busy(self.img_btn, True, "生成图片", "生成中...")
        self.img_status.configure(text="")
        self.img_download_btn.configure(state="disabled")
        self._last_image_urls.clear()
        self._log(self.img_log, f"正在生成: {self.img_prompt.get_value()}")
        self._run_in_thread(self._image_worker)

    def _image_worker(self):
        prompt = self.img_prompt.get_value()
        size = self.img_size.get_value() or "1024x768"
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
                self._auto_download_images()
            else:
                self.root.after(0, lambda: self._log(self.img_log, json.dumps(resp, ensure_ascii=False, indent=2)))
                self.root.after(0, lambda: self.img_status.configure(text="⚠ 未获取到URL", fg=YELLOW))
        except Exception as e:
            self.root.after(0, lambda: self._log(self.img_log, f"失败: {e}", "error"))
            self.root.after(0, lambda: self.img_status.configure(text="✗ 失败", fg=RED))
        finally:
            self.root.after(0, lambda: self._set_busy(self.img_btn, False, "生成图片", ""))

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
        tk.Label(frame, text="输入描述，AI 生成视频（耗时较长）", bg=BG, fg=SURFACE2, font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 16))

        form = tk.Frame(frame, bg=BG)
        form.pack(fill="x")
        self.vid_prompt = self._make_field(form, "视频描述:", row=0)
        self.vid_ref = self._make_field(form, "图片URL:", row=1)
        self.vid_w = self._make_field(form, "宽度:", "1152", row=2, width=10)
        self.vid_h = self._make_field(form, "高度:", "768", row=3, width=10)

        tk.Label(form, text="帧数:", bg=BG, fg=FG, font=("Segoe UI", 10)).grid(row=4, column=0, sticky="w", padx=(0, 12), pady=6)
        self.vid_frames = ttk.Combobox(form, values=["81", "121", "161", "241", "441"], state="readonly", width=8)
        self.vid_frames.set("121")
        self.vid_frames.grid(row=4, column=1, sticky="w", pady=6, ipady=4)

        self.vid_fps = self._make_field(form, "帧率:", "24", row=5, width=10)

        btn_frame = tk.Frame(frame, bg=BG)
        btn_frame.pack(fill="x", pady=(16, 8))
        self.vid_btn = self._make_action_btn(btn_frame, "生成视频", self._run_video_gen)
        self.vid_btn.pack(side="left")
        self.vid_download_btn = self._make_action_btn(btn_frame, "下载视频", self._download_video, "secondary")
        self.vid_download_btn.pack(side="left", padx=(12, 0))
        self.vid_download_btn.configure(state="disabled")
        self.vid_status = tk.Label(btn_frame, text="", bg=BG, fg=GREEN, font=("Segoe UI", 10))
        self.vid_status.pack(side="left", padx=(16, 0))

        self.vid_progress = ttk.Progressbar(frame, mode="indeterminate", length=300)
        self.vid_progress.pack(fill="x", pady=(0, 8))
        self.vid_progress.pack_forget()

        self.vid_log = self._create_log_widget(tk.Frame(frame, bg=BG).pack(fill="both", expand=True, pady=(8, 0)) or frame.winfo_children()[-1], height=8)

    def _run_video_gen(self):
        if not self.current_key.get():
            messagebox.showwarning("提示", "请先在设置中配置 API Key")
            return
        if not self.vid_prompt.get_value():
            messagebox.showwarning("提示", "请输入视频描述")
            return
        self._set_busy(self.vid_btn, True, "生成视频", "提交中...")
        self.vid_status.configure(text="")
        self.vid_download_btn.configure(state="disabled")
        self._last_video_url = None
        self.vid_progress.pack(fill="x", pady=(0, 8))
        self.vid_progress.start(10)
        self._log(self.vid_log, f"正在提交: {self.vid_prompt.get_value()}")
        self._run_in_thread(self._video_worker)

    def _video_worker(self):
        prompt = self.vid_prompt.get_value()
        ref = self.vid_ref.get_value()

        try:
            w = int(self.vid_w.get_value() or "1152")
            h = int(self.vid_h.get_value() or "768")
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

        while True:
            time.sleep(3)
            try:
                status_resp = api_request("GET", f"/v1/videos/{parse.quote(task_id)}", self.current_key.get())
            except Exception as e:
                self.root.after(0, lambda: self._log(self.vid_log, f"查询失败: {e}", "error"))
                self.root.after(0, self._video_reset)
                return

            status = (status_resp.get("status") or status_resp.get("data", {}).get("status", "")).lower()
            elapsed = time.time() - t0

            if status in ("completed", "succeeded", "success"):
                video_url = self._find_video_url(status_resp)
                self._last_video_url = video_url
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

            self.root.after(0, lambda e=elapsed: self.vid_status.configure(text=f"生成中... {e:.0f}s", fg=YELLOW))

    def _find_video_url(self, resp: dict) -> str | None:
        for key in ("video_url", "url"):
            val = resp.get(key) or resp.get("data", {}).get(key)
            if isinstance(val, str) and val.startswith("http"):
                return val
        return None

    def _video_reset(self):
        self._set_busy(self.vid_btn, False, "生成视频", "")
        self.vid_progress.stop()
        self.vid_progress.pack_forget()

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

    # ==================== 聊天 ====================

    def _build_chat_page(self):
        frame = tk.Frame(self.content, bg=BG, padx=32, pady=24)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text="AI 对话", bg=BG, fg=ACCENT, font=("Segoe UI", 18, "bold")).pack(anchor="w")
        tk.Label(frame, text="与 Agnes AI 实时对话", bg=BG, fg=SURFACE2, font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 12))

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
        self.chat_btn = self._make_action_btn(input_frame, "发送", self._send_chat)
        self.chat_btn.pack(side="right")

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
        self._run_in_thread(lambda: self._chat_worker())

    def _chat_worker(self):
        payload = {"model": "agnes-2.0-flash", "messages": self.chat_messages, "stream": True, "temperature": 0.7}
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
        frame = tk.Frame(self.content, bg=BG, padx=32, pady=24)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text="设置", bg=BG, fg=ACCENT, font=("Segoe UI", 18, "bold")).pack(anchor="w")
        tk.Label(frame, text="管理 API Key 和输出目录", bg=BG, fg=SURFACE2, font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 16))

        key_frame = tk.LabelFrame(frame, text=" API Key 管理 ", bg=BG, fg=FG, font=("Segoe UI", 11), padx=16, pady=12)
        key_frame.pack(fill="x", pady=(0, 16))

        add_frame = tk.Frame(key_frame, bg=BG)
        add_frame.pack(fill="x", pady=(0, 8))
        self.settings_key_entry = tk.Entry(add_frame, bg=SURFACE, fg=FG, insertbackground=FG,
                                            font=("Consolas", 10), relief="flat", show="*")
        self.settings_key_entry.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 8))
        tk.Button(add_frame, text="添加", bg=GREEN, fg=MANTLE, font=("Segoe UI", 10, "bold"),
                  relief="flat", padx=16, pady=4, cursor="hand2", command=self._add_key).pack(side="left")

        self.key_list_frame = tk.Frame(key_frame, bg=BG)
        self.key_list_frame.pack(fill="x")
        self._refresh_key_list()

        dir_frame = tk.LabelFrame(frame, text=" 输出目录 ", bg=BG, fg=FG, font=("Segoe UI", 11), padx=16, pady=12)
        dir_frame.pack(fill="x", pady=(0, 16))
        dir_inner = tk.Frame(dir_frame, bg=BG)
        dir_inner.pack(fill="x")
        self.settings_dir_var = tk.StringVar(value=str(OUTPUT_DIR))
        tk.Entry(dir_inner, textvariable=self.settings_dir_var, bg=SURFACE, fg=FG, insertbackground=FG,
                 font=("Consolas", 10), relief="flat").pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 8))
        tk.Button(dir_inner, text="浏览", bg=SURFACE, fg=FG, font=("Segoe UI", 10),
                  relief="flat", padx=12, pady=4, cursor="hand2", command=self._browse_output_dir).pack(side="left")

        info_frame = tk.LabelFrame(frame, text=" 关于 ", bg=BG, fg=FG, font=("Segoe UI", 11), padx=16, pady=12)
        info_frame.pack(fill="x")
        tk.Label(info_frame, text="Agnes AI 创作工具 v1.1", bg=BG, fg=FG, font=("Segoe UI", 10)).pack(anchor="w")
        tk.Label(info_frame, text="API: https://apihub.agnes-ai.com", bg=BG, fg=SURFACE2, font=("Segoe UI", 9)).pack(anchor="w")
        tk.Label(info_frame, text="获取 Key: https://platform.agnes-ai.com/settings/apiKeys", bg=BG, fg=ACCENT, font=("Segoe UI", 9)).pack(anchor="w")

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
