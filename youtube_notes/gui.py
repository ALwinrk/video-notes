"""tkinter GUI for youtube-notes — 全中文界面，无需命令行。"""

from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox

from config import (
    Config, Provider, ProviderInfo,
    PROVIDER_CONFIG, get_provider_info, PipelineCancelled,
)
from pipeline import run_pipeline


# ---------------------------------------------------------------------------
# 笔记语言选项
# ---------------------------------------------------------------------------

_NOTE_LANGUAGES = [
    ("中文", "zh"),
    ("English", "en"),
    ("日本語", "ja"),
    ("한국어", "ko"),
    ("Français", "fr"),
    ("Deutsch", "de"),
    ("Español", "es"),
]


# ---------------------------------------------------------------------------
# 字体检测（必须在 Tk() 创建后调用）
# ---------------------------------------------------------------------------

def _detect_fonts(root: tk.Tk) -> tuple[tuple, tuple]:
    """返回 (通用字体, 等宽字体)。"""
    available = tkfont.families(root)
    available_lower = [f.lower() for f in available]

    def _find(keys: tuple[str, ...]) -> str | None:
        """在可用字体中查找关键字匹配（大小写不敏感）。"""
        for key in keys:
            key_lower = key.lower()
            for i, name_lower in enumerate(available_lower):
                if key_lower in name_lower:
                    return available[i]
        return None

    # 优先中文字体
    normal_name = _find(("Microsoft YaHei", "SimHei", "SimSun", "Microsoft JhengHei", "Song", "Hei", "Kai"))
    normal = (normal_name, 9) if normal_name else ("TkDefaultFont", 9)

    # 优先等宽字体
    mono_name = _find(("Consolas", "Courier New", "Microsoft YaHei"))
    mono = (mono_name, 10) if mono_name else ("TkFixedFont", 10)

    return normal, mono


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------

class YouTubeNotesGUI:
    """YouTube 视频笔记生成器 — 主窗口。"""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root

        # 检测可用字体（必须在 root 之后）
        self._font_normal, self._font_mono = _detect_fonts(root)

        self.root.title("视频笔记生成器")
        self.root.geometry("980x750")
        self.root.minsize(720, 520)

        # 取消支持
        self._cancel_event = threading.Event()
        self._progress_queue: queue.Queue = queue.Queue()
        self._running = False

        # 构建界面
        self._build_menu()
        self._build_widgets()
        self._bind_events()

        # 启动进度轮询
        self._poll_queue()

        # 初始化模型下拉框
        self._on_provider_changed()

    # ------------------------------------------------------------------
    # 菜单栏
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root, font=self._font_normal)
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0, font=self._font_normal)
        file_menu.add_command(label="退出", command=self.root.quit, accelerator="Ctrl+Q")
        menubar.add_cascade(label="文件", menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0, font=self._font_normal)
        help_menu.add_command(label="关于", command=self._show_about)
        menubar.add_cascade(label="帮助", menu=help_menu)

        self.root.bind_all("<Control-q>", lambda e: self.root.quit())

    # ------------------------------------------------------------------
    # 界面组件
    # ------------------------------------------------------------------

    def _build_widgets(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        # 全局默认字体
        style.configure(".", font=self._font_normal)
        style.configure("TLabelframe.Label", font=(self._font_normal[0], self._font_normal[1], "bold"))

        main_frame = ttk.Frame(self.root, padding="12 12 12 12")
        main_frame.pack(fill="both", expand=True)
        main_frame.columnconfigure(0, weight=1)

        row = 0

        # ---- 视频链接 / 本地文件 ----
        ttk.Label(main_frame, text="视频链接（或选择本地文件）：").grid(
            row=row, column=0, sticky="w", pady=(0, 2)
        )
        row += 1

        url_file_frame = ttk.Frame(main_frame)
        url_file_frame.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        url_file_frame.columnconfigure(0, weight=1)

        self.url_var = tk.StringVar()
        url_entry = ttk.Entry(url_file_frame, textvariable=self.url_var, font=self._font_mono)
        url_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.local_file_var = tk.StringVar()
        # 用户在 URL 框输入时，自动清除本地文件选择
        self.url_var.trace_add("write", lambda *_: self._on_url_changed())

        ttk.Button(
            url_file_frame, text="选择本地视频...",
            command=self._browse_local_file,
        ).grid(row=0, column=1, sticky="e")

        # Show selected local file name
        self.local_file_label = ttk.Label(
            url_file_frame, text="", foreground="gray",
        )
        self.local_file_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))

        row += 1

        # ---- 模型设置 ----
        llm_frame = ttk.LabelFrame(main_frame, text="模型设置", padding="8 4 8 8")
        llm_frame.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        llm_frame.columnconfigure(1, weight=1)
        llm_frame.columnconfigure(3, weight=2)

        ttk.Label(llm_frame, text="AI 平台：").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.provider_var = tk.StringVar(value="openai")
        # 使用 .value (字符串) 而非枚举对象，确保 tkinter 正确传递
        provider_keys = [p.value for p in PROVIDER_CONFIG]
        provider_cb = ttk.Combobox(
            llm_frame, textvariable=self.provider_var, state="readonly",
            values=provider_keys,
        )
        provider_cb.grid(row=0, column=1, sticky="w", padx=(0, 12))

        ttk.Label(llm_frame, text="模型：").grid(row=0, column=2, sticky="w", padx=(0, 4))
        self.model_var = tk.StringVar()
        self.model_cb = ttk.Combobox(llm_frame, textvariable=self.model_var, state="readonly")
        self.model_cb.grid(row=0, column=3, sticky="ew", padx=(0, 12))

        # API 密钥
        ttk.Label(llm_frame, text="API 密钥：").grid(row=1, column=0, sticky="w", padx=(0, 4), pady=(8, 0))
        self.api_key_var = tk.StringVar()
        self.api_key_entry = ttk.Entry(
            llm_frame, textvariable=self.api_key_var, show="*", font=self._font_mono,
        )
        self.api_key_entry.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(0, 12), pady=(8, 0))

        self.show_key_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            llm_frame, text="显示密钥", variable=self.show_key_var,
            command=self._toggle_key_visibility,
        ).grid(row=1, column=3, sticky="w", pady=(8, 0))

        ttk.Label(
            llm_frame, text="（Ollama 本地运行无需密钥）",
            foreground="gray",
        ).grid(row=2, column=1, columnspan=3, sticky="w", pady=(4, 0))

        row += 1

        # ---- 输出设置 ----
        settings_frame = ttk.LabelFrame(main_frame, text="输出设置", padding="8 4 8 8")
        settings_frame.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        settings_frame.columnconfigure(3, weight=1)

        ttk.Label(settings_frame, text="笔记语言：").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.lang_var = tk.StringVar(value="zh")
        lang_names = [name for name, _code in _NOTE_LANGUAGES]
        lang_cb = ttk.Combobox(
            settings_frame, textvariable=self.lang_var, state="readonly",
            values=lang_names,
        )
        lang_cb.grid(row=0, column=1, sticky="w", padx=(0, 16))
        for name, code in _NOTE_LANGUAGES:
            if code == self.lang_var.get():
                lang_cb.set(name)
                break

        ttk.Label(settings_frame, text="截图间隔（秒）：").grid(row=0, column=2, sticky="w", padx=(0, 4))
        self.interval_var = tk.IntVar(value=30)
        ttk.Spinbox(
            settings_frame, from_=5, to=300, textvariable=self.interval_var, width=6,
        ).grid(row=0, column=3, sticky="w", padx=(0, 16))

        ttk.Label(settings_frame, text="最大截图数：").grid(row=0, column=4, sticky="w", padx=(0, 4))
        self.max_frames_var = tk.IntVar(value=20)
        ttk.Spinbox(
            settings_frame, from_=1, to=100, textvariable=self.max_frames_var, width=6,
        ).grid(row=0, column=5, sticky="w")

        # 输出目录
        ttk.Label(settings_frame, text="输出目录：").grid(row=1, column=0, sticky="w", padx=(0, 4), pady=(8, 0))
        self.output_var = tk.StringVar(value="./notes")
        ttk.Entry(settings_frame, textvariable=self.output_var).grid(
            row=1, column=1, columnspan=3, sticky="ew", padx=(0, 8), pady=(8, 0)
        )
        ttk.Button(settings_frame, text="浏览...", command=self._browse_output).grid(
            row=1, column=4, columnspan=2, sticky="w", pady=(8, 0)
        )

        # 保留文件选项
        self.keep_video_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            settings_frame, text="保留视频文件", variable=self.keep_video_var,
        ).grid(row=2, column=1, sticky="w", pady=(8, 0))
        self.keep_frames_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            settings_frame, text="保留截图文件", variable=self.keep_frames_var,
        ).grid(row=2, column=3, sticky="w", pady=(8, 0))

        row += 1

        # ---- 进度条 + 状态 ----
        progress_frame = ttk.Frame(main_frame)
        progress_frame.grid(row=row, column=0, sticky="ew", pady=(4, 6))
        progress_frame.columnconfigure(0, weight=1)

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(
            progress_frame, variable=self.progress_var, maximum=100, mode="determinate",
        )
        self.progress_bar.grid(row=0, column=0, sticky="ew", padx=(0, 10))

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(progress_frame, textvariable=self.status_var, width=32).grid(row=0, column=1, sticky="e")

        row += 1

        # ---- 输出文本区域 ----
        output_frame = ttk.LabelFrame(main_frame, text="输出结果", padding="4 4 4 4")
        output_frame.grid(row=row, column=0, sticky="nsew", pady=(4, 10))
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(0, weight=1)
        main_frame.rowconfigure(row, weight=1)

        self.output_text = tk.Text(
            output_frame, wrap="word", state="disabled",
            font=self._font_mono, relief="flat", borderwidth=4,
        )
        self.output_text.grid(row=0, column=0, sticky="nsew")

        text_scrollbar = ttk.Scrollbar(
            output_frame, orient="vertical", command=self.output_text.yview,
        )
        text_scrollbar.grid(row=0, column=1, sticky="ns")
        self.output_text.configure(yscrollcommand=text_scrollbar.set)

        row += 1

        # ---- 操作按钮 ----
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=row, column=0, sticky="ew")
        btn_frame.columnconfigure(2, weight=1)

        self.generate_btn = ttk.Button(
            btn_frame, text="生成笔记", command=self._start_generation,
        )
        self.generate_btn.grid(row=0, column=0, padx=(0, 10))

        self.cancel_btn = ttk.Button(
            btn_frame, text="取消", command=self._cancel, state="disabled",
        )
        self.cancel_btn.grid(row=0, column=1, padx=(0, 10))

        # 右侧按钮
        ttk.Button(btn_frame, text="复制", command=self._copy_output).grid(
            row=0, column=3, padx=(6, 6), sticky="e",
        )
        ttk.Button(btn_frame, text="另存为...", command=self._save_as).grid(
            row=0, column=4, padx=(6, 6), sticky="e",
        )
        ttk.Button(btn_frame, text="清空", command=self._clear_output).grid(
            row=0, column=5, padx=(6, 0), sticky="e",
        )

    # ------------------------------------------------------------------
    # 事件绑定
    # ------------------------------------------------------------------

    def _bind_events(self) -> None:
        self.provider_var.trace_add("write", lambda *_: self._on_provider_changed())

    # ------------------------------------------------------------------
    # 平台切换联动
    # ------------------------------------------------------------------

    def _on_provider_changed(self) -> None:
        """切换 AI 平台时更新模型列表和密钥字段。"""
        provider_key = self.provider_var.get()
        try:
            provider = Provider(provider_key)
        except ValueError:
            return

        info = get_provider_info(provider)

        # 更新模型下拉框
        if info.models:
            self.model_cb.config(values=info.models, state="readonly")
            current = self.model_var.get()
            if current in info.models:
                self.model_var.set(current)
            else:
                self.model_var.set(info.default_model)
        else:
            # Ollama — 可手动输入模型名
            self.model_cb.config(values=[], state="normal")
            self.model_var.set(self.model_var.get() or info.default_model)

        # 更新 API 密钥字段
        if info.key_env:
            self.api_key_entry.config(state="normal")
            if not self.api_key_var.get():
                env_val = os.environ.get(info.key_env, "")
                if env_val:
                    self.api_key_var.set(env_val)
        else:
            # Ollama — 无需密钥
            self.api_key_var.set("")
            self.api_key_entry.config(state="disabled")

    def _toggle_key_visibility(self) -> None:
        """切换 API 密钥显示/隐藏。"""
        show = self.show_key_var.get()
        self.api_key_entry.config(show="" if show else "*")

    # ------------------------------------------------------------------
    # 生成流程
    # ------------------------------------------------------------------

    def _start_generation(self) -> None:
        """验证输入并在后台线程启动管道。"""
        url = self.url_var.get().strip()
        local_file = self.local_file_var.get().strip()

        if not url and not local_file:
            messagebox.showerror("错误", "请输入视频链接或选择本地视频文件。")
            return

        # 如果同时填了 URL 和本地文件，URL 优先（本地文件可能是上次残留的）
        if local_file and not url.startswith("http"):
            from pathlib import Path
            if not Path(local_file).exists():
                messagebox.showerror("错误", f"本地文件不存在：\n{local_file}")
                return
            # 用文件名作为标题占位
            url = f"file://{local_file}"  # 占位 URL

        # 获取平台
        provider_key = self.provider_var.get()
        try:
            provider = Provider(provider_key)
        except ValueError:
            messagebox.showerror("错误", f"未知的 AI 平台：{provider_key}")
            return

        provider_info = get_provider_info(provider)
        api_key = self.api_key_var.get().strip()

        if provider_info.key_env and not api_key:
            env_val = os.environ.get(provider_info.key_env, "")
            if not env_val:
                if not messagebox.askyesno(
                    "提示",
                    f"未设置 {provider_info.display_name} 的 API 密钥。\n\n"
                    f"你可以设置环境变量 {provider_info.key_env}\n"
                    "或在 API 密钥输入框中粘贴密钥。\n\n"
                    "没有密钥继续？（很可能会失败）",
                ):
                    return

        # 解析语言
        lang_code = "zh"
        for name, code in _NOTE_LANGUAGES:
            if name == self.lang_var.get():
                lang_code = code
                break

        # 构建配置
        try:
            cfg = Config(
                url=url,
                local_file=local_file or None,
                output_dir=self.output_var.get().strip() or "./notes",
                provider=provider,
                model=self.model_var.get().strip() or provider_info.default_model,
                api_key=api_key or None,
                api_base=None if provider != Provider.OLLAMA else provider_info.default_api_base,
                frame_interval=self.interval_var.get(),
                max_frames=self.max_frames_var.get(),
                note_language=lang_code,
                keep_video=self.keep_video_var.get(),
                keep_frames=self.keep_frames_var.get(),
            )
        except ValueError as exc:
            messagebox.showerror("配置错误", str(exc))
            return

        # 禁用界面，启动后台线程
        self._running = True
        self._cancel_event.clear()
        self._set_ui_state("running")

        thread = threading.Thread(target=self._run_pipeline_thread, args=(cfg,), daemon=True)
        thread.start()

    def _run_pipeline_thread(self, cfg: Config) -> None:
        """在后台线程运行管道，进度通过队列发送到主线程。"""
        try:
            notes, output_path, _meta = run_pipeline(
                cfg,
                progress=self._post_progress,
                cancel_event=self._cancel_event,
            )
            self._progress_queue.put(("done", notes, output_path))
        except PipelineCancelled:
            self._progress_queue.put(("cancelled",))
        except Exception as exc:
            self._progress_queue.put(("error", str(exc)))

    def _post_progress(self, status: str, percent: int) -> None:
        """管道进度回调——将更新加入队列。"""
        self._progress_queue.put(("progress", status, percent))

    def _poll_queue(self) -> None:
        """每 100ms 在主线程轮询进度队列。"""
        try:
            while True:
                msg = self._progress_queue.get_nowait()
                kind = msg[0]

                if kind == "progress":
                    _kind, status, percent = msg
                    self.progress_var.set(percent)
                    self.status_var.set(status)
                elif kind == "done":
                    _kind, notes, output_path = msg
                    self.progress_var.set(100)
                    self.status_var.set(f"完成 — 已保存到 {output_path}")
                    self._set_output_text(notes)
                    self._set_ui_state("idle")
                elif kind == "cancelled":
                    self.status_var.set("已取消")
                    self._set_ui_state("idle")
                elif kind == "error":
                    _kind, error_msg = msg
                    self.status_var.set("出错")
                    self._set_ui_state("idle")
                    self.root.after(50, lambda m=error_msg: messagebox.showerror("错误", m))
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _cancel(self) -> None:
        """用户点击取消。"""
        self._cancel_event.set()
        self.status_var.set("正在取消...")
        self.cancel_btn.config(state="disabled")

    # ------------------------------------------------------------------
    # UI 状态辅助方法
    # ------------------------------------------------------------------

    def _set_ui_state(self, state: str) -> None:
        if state == "running":
            self._running = True
            self.generate_btn.config(state="disabled")
            self.cancel_btn.config(state="normal")
            self.progress_var.set(0)
        else:
            self._running = False
            self.generate_btn.config(state="normal")
            self.cancel_btn.config(state="disabled")

    def _set_output_text(self, text: str) -> None:
        self.output_text.config(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", text)
        self.output_text.config(state="disabled")

    def _clear_output(self) -> None:
        self.output_text.config(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.config(state="disabled")
        self.progress_var.set(0)
        self.status_var.set("就绪")

    def _copy_output(self) -> None:
        text = self.output_text.get("1.0", "end-1c")
        if text.strip():
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.status_var.set("已复制到剪贴板")

    def _save_as(self) -> None:
        text = self.output_text.get("1.0", "end-1c")
        if not text.strip():
            messagebox.showinfo("提示", "没有可保存的内容。")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
        )
        if path:
            from pathlib import Path
            Path(path).write_text(text, encoding="utf-8")
            self.status_var.set(f"已保存到 {path}")

    def _on_url_changed(self) -> None:
        """When user types a URL, clear stale local file selection."""
        if self.url_var.get().strip():
            self.local_file_var.set("")
            self.local_file_label.config(text="")

    def _browse_local_file(self) -> None:
        path = filedialog.askopenfilename(
            title="选择视频文件",
            filetypes=[
                ("视频文件", "*.mp4 *.mkv *.webm *.avi *.mov *.flv *.wmv"),
                ("所有文件", "*.*"),
            ],
        )
        if path:
            self.local_file_var.set(path)
            self.local_file_label.config(text=f"📁 {Path(path).name}")
            # Clear URL when local file is selected
            self.url_var.set("")
        else:
            self.local_file_var.set("")
            self.local_file_label.config(text="")

    def _browse_output(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.output_var.set(path)

    def _show_about(self) -> None:
        messagebox.showinfo(
            "关于 — 视频笔记生成器",
            "视频笔记生成器 v1.2\n\n"
            "下载视频，提取关键帧，\n"
            "使用 AI 视觉分析生成结构化笔记。\n\n"
            "支持平台：YouTube、Bilibili、Twitter/X、\n"
            "TikTok、Vimeo 等数千个视频网站。\n\n"
            "支持的 AI 平台：\n"
            "  • OpenAI（GPT-4o / GPT-4-turbo）\n"
            "  • Anthropic（Claude Sonnet 4 / Opus 4）\n"
            "  • DeepSeek（deepseek-chat / deepseek-reasoner）\n"
            "  • Ollama（本地模型）\n\n"
            "运行要求：ffmpeg、Python 3.12+",
        )


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main() -> None:
    root = tk.Tk()
    _app = YouTubeNotesGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
