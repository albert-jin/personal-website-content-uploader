# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime as dt
import json
import random
import re
import shutil
import subprocess
import time
import urllib.parse
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

APP_NAME = "Albert Evans 内容半自动发布器"
APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
STATE_PATH = APP_DIR / "app_state.json"
GIT_STATUS_PATH = APP_DIR / "git_push_status.json"

REMOTE_PUSH_URL = "https://albert-jin@github.com/albert-jin/albert-evans.github.io.git"
IMAGE_TARGET_SUBDIR = Path("assets") / "image-albert-evans" / "image-continue-added"
REQUIRED_REPO_DIRS = ("_publications", "_news", "_talks", "assets")
TZ_SUFFIX = "+0800"


def load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return dict(default)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return dict(default)


def save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def yaml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower())
    slug = slug.strip("-")
    return slug


def make_auto_slug_from_title(title: str) -> str:
    base = slugify(title)
    if not base:
        base = "item"
    base = base[:20]
    rand_suffix = str(random.randint(100000, 999999))
    return f"{base}-{rand_suffix}"


def ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def parse_datetime(date_text: str, time_text: str) -> dt.datetime:
    date_text = date_text.strip()
    time_text = time_text.strip() or "00:00:00"
    try:
        return dt.datetime.strptime(f"{date_text} {time_text}", "%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise ValueError("日期必须是 YYYY-MM-DD，时间必须是 HH:MM:SS。") from exc


def write_text_file(path: Path, content: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


class ContentUploaderApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1040x780")
        self.minsize(940, 680)

        self.config_data = load_json(CONFIG_PATH, {"repo_path": ""})
        self.state_data = load_json(STATE_PATH, {"pending_changes": 0})

        self.repo_path_var = tk.StringVar(value=str(self.config_data.get("repo_path", "")))
        self.pending_changes = int(self.state_data.get("pending_changes", 0))
        self.pending_var = tk.StringVar()
        self.path_var = tk.StringVar()
        self.status_var = tk.StringVar(value="请先完成“登录/项目路径”配置。")

        self.current_module = "publications"
        self.form_widgets: dict[str, object] = {}
        self.talk_image_sources: list[str] = []

        self.git_polling = False
        self.git_poll_started_at = 0.0

        self.module_buttons: dict[str, ttk.Button] = {}
        self.path_link_label: ttk.Label | None = None

        self._build_layout()
        self._refresh_topbar()
        self.switch_module("publications")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(50, self.ensure_repo_path_ready)

    def _build_layout(self) -> None:
        toolbar = ttk.Frame(self, padding=10)
        toolbar.pack(fill="x")

        ttk.Button(toolbar, text="登录/项目路径", command=self.open_login_dialog).pack(side="left", padx=(0, 8))

        for module_key, label in (
            ("publications", "_publications"),
            ("news", "_news"),
            ("talks", "_talks"),
        ):
            btn = ttk.Button(toolbar, text=label, command=lambda m=module_key: self.switch_module(m))
            btn.pack(side="left", padx=4)
            self.module_buttons[module_key] = btn

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Label(toolbar, textvariable=self.pending_var).pack(side="left")

        self.push_button = ttk.Button(toolbar, text="提交到远端", command=self.start_git_push)
        self.push_button.pack(side="left", padx=(10, 0))
        ttk.Button(toolbar, text="检测并拉取远端", command=self.start_git_sync).pack(side="left", padx=(8, 0))

        path_frame = ttk.Frame(self, padding=(10, 0, 10, 8))
        path_frame.pack(fill="x")
        ttk.Label(path_frame, text="当前项目路径:").pack(side="left")
        self.path_link_label = ttk.Label(path_frame, textvariable=self.path_var, foreground="#0b5a9d", cursor="hand2")
        self.path_link_label.pack(side="left", padx=(6, 0))
        self.path_link_label.bind("<Button-1>", self.on_path_label_click)

        sep = ttk.Separator(self, orient="horizontal")
        sep.pack(fill="x")

        self.form_container = ttk.Frame(self, padding=12)
        self.form_container.pack(fill="both", expand=True)

        status_bar = ttk.Frame(self, padding=(10, 0, 10, 10))
        status_bar.pack(fill="x")
        ttk.Label(status_bar, textvariable=self.status_var).pack(side="left")

    def _refresh_topbar(self) -> None:
        self.pending_var.set(f"待提交修改数: {self.pending_changes}")
        current_path = self.repo_path_var.get().strip()
        if current_path and self._validate_repo_path(Path(current_path)):
            self.path_var.set(current_path)
        else:
            self.path_var.set("未设置（点击这里重新选择项目文件夹）")
        self.push_button["state"] = "normal" if self.pending_changes > 0 else "disabled"
        for key, button in self.module_buttons.items():
            button["state"] = "disabled" if key == self.current_module else "normal"

    def on_path_label_click(self, _event: tk.Event) -> None:
        self.open_login_dialog(force=False)

    def ensure_repo_path_ready(self) -> None:
        current = self.repo_path_var.get().strip()
        if current and self._validate_repo_path(Path(current)):
            self.status_var.set("配置完成。请选择模块并填写表单。")
            return
        self.open_login_dialog(force=True)

    def open_login_dialog(self, force: bool = False) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("登录：绑定本地 albert-evans.github.io 绝对路径")
        dialog.resizable(False, False)
        dialog.transient(self)

        path_var = tk.StringVar(value=self.repo_path_var.get().strip())

        main = ttk.Frame(dialog, padding=14)
        main.grid(row=0, column=0, sticky="nsew")

        ttk.Label(
            main,
            text="请输入本地仓库绝对路径，或点击“浏览”通过文件管理器选择：",
        ).grid(row=0, column=0, columnspan=3, sticky="w")

        entry = ttk.Entry(main, textvariable=path_var, width=90)
        entry.grid(row=1, column=0, columnspan=2, sticky="we", pady=(8, 0))

        def browse() -> None:
            selected = filedialog.askdirectory(title="选择 albert-evans.github.io 根目录")
            if selected:
                path_var.set(selected)

        ttk.Button(main, text="浏览", command=browse).grid(row=1, column=2, padx=(8, 0), pady=(8, 0))

        tips = (
            "程序会在该路径下新增 md 文件，并在 talks 模块把图片复制到：\n"
            "assets/image-albert-evans/image-continue-added"
        )
        ttk.Label(main, text=tips).grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 0))

        def save_and_close() -> None:
            raw_path = path_var.get().strip()
            if not raw_path:
                messagebox.showerror("路径无效", "请填写项目绝对路径，或点击“浏览”选择目录。", parent=dialog)
                return

            candidate = Path(raw_path)
            is_valid, reason = self._validate_repo_path_with_reason(candidate)
            if not is_valid:
                messagebox.showerror(
                    "路径无效",
                    "该路径不是有效的 albert-evans.github.io 根目录。\n"
                    f"原因：{reason}",
                    parent=dialog,
                )
                return
            resolved = str(candidate.resolve())
            self.repo_path_var.set(resolved)
            self.config_data["repo_path"] = resolved
            save_json(CONFIG_PATH, self.config_data)
            self._refresh_topbar()
            self.status_var.set("登录配置已保存，可开始录入内容。")
            dialog.destroy()

        button_frame = ttk.Frame(main)
        button_frame.grid(row=3, column=0, columnspan=3, sticky="e", pady=(14, 0))
        ttk.Button(button_frame, text="保存", command=save_and_close).pack(side="left", padx=(0, 8))

        def on_cancel() -> None:
            if force:
                messagebox.showwarning("需要配置路径", "首次使用必须完成路径登录配置。", parent=dialog)
                return
            dialog.destroy()

        ttk.Button(button_frame, text="取消", command=on_cancel).pack(side="left")

        dialog.grab_set()
        entry.focus_set()
        self.wait_window(dialog)

    def _validate_repo_path(self, path: Path) -> bool:
        return self._validate_repo_path_with_reason(path)[0]

    def _validate_repo_path_with_reason(self, path: Path) -> tuple[bool, str]:
        try:
            path = path.resolve()
        except Exception:
            return False, "路径无法解析。"
        if not path.exists() or not path.is_dir():
            return False, "路径不存在或不是文件夹。"

        missing_dirs = [name for name in REQUIRED_REPO_DIRS if not (path / name).exists()]
        if missing_dirs:
            return False, f"缺少目录: {', '.join(missing_dirs)}"

        if not (path / ".git").is_dir():
            return False, "未检测到 .git 文件夹。请确认选择的是项目根目录。"

        return True, ""

    def get_repo_path_or_raise(self) -> Path:
        raw = self.repo_path_var.get().strip()
        if not raw:
            raise ValueError("请先点击“登录/项目路径”完成绝对路径配置。")
        path = Path(raw)
        is_valid, reason = self._validate_repo_path_with_reason(path)
        if not is_valid:
            raise ValueError(f"当前项目路径不可用，请重新登录配置。原因：{reason}")
        return path.resolve()

    def switch_module(self, module: str) -> None:
        self.current_module = module
        self.form_widgets = {}
        self.talk_image_sources = []
        for widget in self.form_container.winfo_children():
            widget.destroy()

        if module == "publications":
            self.build_publications_form()
        elif module == "news":
            self.build_news_form()
        else:
            self.build_talks_form()
        self._refresh_topbar()

    def build_publications_form(self) -> None:
        frame = self.form_container
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="_publications 新增", font=("", 13, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")

        self.form_widgets["title"] = self._add_entry(frame, 1, "标题*")
        self.form_widgets["date"] = self._add_entry(frame, 2, "日期* (YYYY-MM-DD)", dt.date.today().strftime("%Y-%m-%d"))
        self.form_widgets["time"] = self._add_entry(frame, 3, "时间 (HH:MM:SS)", "00:00:00")
        self.form_widgets["slug"] = self._add_entry(frame, 4, "文件标识 slug（可空，自动生成）")

        selected_var = tk.BooleanVar(value=False)
        self.form_widgets["selected"] = selected_var
        ttk.Checkbutton(frame, text="selected: true", variable=selected_var).grid(row=5, column=1, sticky="w", pady=(2, 6))

        self.form_widgets["pub"] = self._add_entry(frame, 6, "期刊/会议 (pub，可空)")
        self.form_widgets["pub_post"] = self._add_entry(frame, 7, "pub_post（可空）", " | Published: ")
        self.form_widgets["pub_date"] = self._add_entry(frame, 8, "pub_date（可空）")
        self.form_widgets["pub_last"] = self._add_entry(frame, 9, "pub_last（可空，可放 badge html）")
        self.form_widgets["semantic_scholar_id"] = self._add_entry(frame, 10, "semantic_scholar_id（可空）")
        self.form_widgets["authors"] = self._add_text(frame, 11, "作者（每行一个，可空）", 4)
        self.form_widgets["links"] = self._add_text(frame, 12, "链接（每行一个，格式：标签|URL，可空）", 4)
        self.form_widgets["body"] = self._add_text(frame, 13, "正文（可空）", 7)

        ttk.Button(frame, text="提交并新增 md（本地）", command=self.submit_publication).grid(row=14, column=1, sticky="e", pady=(12, 0))

    def build_news_form(self) -> None:
        frame = self.form_container
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="_news 新增", font=("", 13, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")

        self.form_widgets["title"] = self._add_entry(frame, 1, "标题*")
        self.form_widgets["date"] = self._add_entry(frame, 2, "日期* (YYYY-MM-DD)", dt.date.today().strftime("%Y-%m-%d"))
        self.form_widgets["time"] = self._add_entry(frame, 3, "时间 (HH:MM:SS)", "10:00:00")
        self.form_widgets["display_date"] = self._add_entry(frame, 4, "display_date（可空，默认自动生成）")
        self.form_widgets["slug"] = self._add_entry(frame, 5, "文件标识 slug（可空，自动生成）")
        self.form_widgets["body"] = self._add_text(frame, 6, "正文（可空）", 12)

        ttk.Button(frame, text="提交并新增 md（本地）", command=self.submit_news).grid(row=7, column=1, sticky="e", pady=(12, 0))

    def build_talks_form(self) -> None:
        frame = self.form_container
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="_talks 新增", font=("", 13, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")

        self.form_widgets["title"] = self._add_entry(frame, 1, "标题*")
        self.form_widgets["date"] = self._add_entry(frame, 2, "日期* (YYYY-MM-DD)", dt.date.today().strftime("%Y-%m-%d"))
        self.form_widgets["time"] = self._add_entry(frame, 3, "时间 (HH:MM:SS)", "00:00:00")
        self.form_widgets["slug"] = self._add_entry(frame, 4, "文件标识 slug（可空，自动生成）")
        self.form_widgets["type"] = self._add_entry(frame, 5, "type（可空）", "Conference proceedings talk")
        self.form_widgets["venue"] = self._add_entry(frame, 6, "venue（可空）")
        self.form_widgets["location"] = self._add_entry(frame, 7, "location（可空）")
        self.form_widgets["summary"] = self._add_entry(frame, 8, "summary（可空）")
        self.form_widgets["paper_url"] = self._add_entry(frame, 9, "paper_url（可空）")
        self.form_widgets["event_url"] = self._add_entry(frame, 10, "event_url（可空）")
        self.form_widgets["cover"] = self._add_entry(frame, 11, "cover（可空，不填则自动用第一张图片）")

        image_row = 12
        ttk.Label(frame, text="图片（可多选，自动复制到 assets/image-albert-evans/image-continue-added）").grid(
            row=image_row, column=0, columnspan=2, sticky="w", pady=(8, 2)
        )

        listbox = tk.Listbox(frame, height=5)
        listbox.grid(row=image_row + 1, column=0, columnspan=2, sticky="nsew")
        self.form_widgets["image_listbox"] = listbox

        image_btns = ttk.Frame(frame)
        image_btns.grid(row=image_row + 2, column=0, columnspan=2, sticky="w", pady=(5, 0))
        ttk.Button(image_btns, text="添加图片", command=self.add_talk_images).pack(side="left", padx=(0, 8))
        ttk.Button(image_btns, text="移除选中", command=self.remove_selected_talk_image).pack(side="left", padx=(0, 8))
        ttk.Button(image_btns, text="清空图片", command=self.clear_talk_images).pack(side="left")

        self.form_widgets["body"] = self._add_text(frame, 15, "正文（可空）", 7)

        ttk.Button(frame, text="提交并新增 md（本地）", command=self.submit_talk).grid(row=16, column=1, sticky="e", pady=(12, 0))

    def _add_entry(self, parent: ttk.Frame, row: int, label: str, default: str = "") -> ttk.Entry:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=(3, 3), padx=(0, 10))
        entry = ttk.Entry(parent)
        entry.grid(row=row, column=1, sticky="we", pady=(3, 3))
        if default:
            entry.insert(0, default)
        return entry

    def _add_text(self, parent: ttk.Frame, row: int, label: str, height: int) -> tk.Text:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="nw", pady=(3, 3), padx=(0, 10))
        text = tk.Text(parent, height=height, wrap="word")
        text.grid(row=row, column=1, sticky="we", pady=(3, 3))
        return text

    def add_talk_images(self) -> None:
        selected = filedialog.askopenfilenames(
            title="选择 talk 图片",
            filetypes=[("Image Files", "*.png;*.jpg;*.jpeg;*.webp;*.gif;*.bmp"), ("All Files", "*.*")],
        )
        if not selected:
            return
        for file_path in selected:
            if file_path not in self.talk_image_sources:
                self.talk_image_sources.append(file_path)
        self.refresh_image_listbox()

    def remove_selected_talk_image(self) -> None:
        listbox = self.form_widgets.get("image_listbox")
        if not isinstance(listbox, tk.Listbox):
            return
        indexes = listbox.curselection()
        if not indexes:
            return
        for idx in sorted(indexes, reverse=True):
            del self.talk_image_sources[idx]
        self.refresh_image_listbox()

    def clear_talk_images(self) -> None:
        self.talk_image_sources = []
        self.refresh_image_listbox()

    def refresh_image_listbox(self) -> None:
        listbox = self.form_widgets.get("image_listbox")
        if not isinstance(listbox, tk.Listbox):
            return
        listbox.delete(0, tk.END)
        for file_path in self.talk_image_sources:
            listbox.insert(tk.END, file_path)

    def _entry_value(self, key: str) -> str:
        widget = self.form_widgets.get(key)
        if isinstance(widget, ttk.Entry):
            return widget.get().strip()
        return ""

    def _text_value(self, key: str) -> str:
        widget = self.form_widgets.get(key)
        if isinstance(widget, tk.Text):
            return widget.get("1.0", "end").strip()
        return ""

    def _bump_pending_and_notify(self, created_file: Path) -> None:
        self.pending_changes += 1
        self.state_data["pending_changes"] = self.pending_changes
        save_json(STATE_PATH, self.state_data)
        self._refresh_topbar()
        self.status_var.set(f"已新增本地文件: {created_file}")
        messagebox.showinfo(
            "新增成功",
            f"已写入:\n{created_file}\n\n待提交修改数 +1。\n你可以继续新增，最后统一点“提交到远端”。",
        )

    def submit_publication(self) -> None:
        try:
            repo_path = self.get_repo_path_or_raise()
            title = self._entry_value("title")
            if not title:
                raise ValueError("publication 标题必填。")
            record_dt = parse_datetime(self._entry_value("date"), self._entry_value("time"))
            raw_slug = self._entry_value("slug")
            slug = slugify(raw_slug) if raw_slug else make_auto_slug_from_title(title)
            if not slug:
                slug = make_auto_slug_from_title(title)

            year_dir = repo_path / "_publications" / str(record_dt.year)
            year_dir.mkdir(parents=True, exist_ok=True)
            file_path = year_dir / f"{record_dt.year}-{slug}.md"
            if file_path.exists():
                raise ValueError(f"文件已存在：{file_path.name}，请修改 slug 后重试。")

            lines = [
                "---",
                f"title: {yaml_quote(title)}",
                f'date: "{record_dt.strftime("%Y-%m-%d %H:%M:%S")} {TZ_SUFFIX}"',
            ]

            selected_var = self.form_widgets.get("selected")
            if isinstance(selected_var, tk.BooleanVar) and selected_var.get():
                lines.append("selected: true")

            for key in ("pub", "pub_post", "pub_date", "pub_last", "semantic_scholar_id"):
                value = self._entry_value(key)
                if value:
                    lines.append(f"{key}: {yaml_quote(value)}")

            authors = [line.strip() for line in self._text_value("authors").splitlines() if line.strip()]
            if authors:
                lines.append("authors:")
                for author in authors:
                    lines.append(f"  - {yaml_quote(author)}")

            link_lines = [line.strip() for line in self._text_value("links").splitlines() if line.strip()]
            if link_lines:
                lines.append("links:")
                for line in link_lines:
                    if "|" not in line:
                        raise ValueError(f"链接格式错误：{line}\n请使用 标签|URL。")
                    key, url = line.split("|", 1)
                    key = key.strip()
                    url = url.strip()
                    if not key or not url:
                        raise ValueError(f"链接格式错误：{line}")
                    lines.append(f"  {yaml_quote(key)}: {yaml_quote(url)}")

            lines.append("---")

            body = self._text_value("body")
            content = "\n".join(lines) + "\n\n"
            if body:
                content += body + "\n"

            write_text_file(file_path, content)
            self._bump_pending_and_notify(file_path)
        except Exception as exc:
            messagebox.showerror("新增失败", str(exc))

    def submit_news(self) -> None:
        try:
            repo_path = self.get_repo_path_or_raise()
            title = self._entry_value("title")
            if not title:
                raise ValueError("news 标题必填。")
            record_dt = parse_datetime(self._entry_value("date"), self._entry_value("time"))
            raw_slug = self._entry_value("slug")
            slug = slugify(raw_slug) if raw_slug else make_auto_slug_from_title(title)
            if not slug:
                slug = make_auto_slug_from_title(title)
            display_date = self._entry_value("display_date") or record_dt.strftime("%b %d")

            file_name = f"{record_dt.strftime('%Y-%m-%d')}-{slug}.md"
            file_path = repo_path / "_news" / file_name
            if file_path.exists():
                raise ValueError(f"文件已存在：{file_path.name}，请修改 slug 后重试。")

            lines = [
                "---",
                f"title: {yaml_quote(title)}",
                f'date: "{record_dt.strftime("%Y-%m-%d %H:%M:%S")} {TZ_SUFFIX}"',
                f"display_date: {yaml_quote(display_date)}",
                "---",
            ]

            body = self._text_value("body")
            content = "\n".join(lines) + "\n\n"
            if body:
                content += body + "\n"

            write_text_file(file_path, content)
            self._bump_pending_and_notify(file_path)
        except Exception as exc:
            messagebox.showerror("新增失败", str(exc))

    def submit_talk(self) -> None:
        try:
            repo_path = self.get_repo_path_or_raise()
            title = self._entry_value("title")
            if not title:
                raise ValueError("talk 标题必填。")

            record_dt = parse_datetime(self._entry_value("date"), self._entry_value("time"))
            raw_slug = self._entry_value("slug")
            slug = slugify(raw_slug) if raw_slug else make_auto_slug_from_title(title)
            if not slug:
                slug = make_auto_slug_from_title(title)
            copied_images = self.copy_talk_images(repo_path, self.talk_image_sources)

            cover = self._entry_value("cover")
            if not cover and copied_images:
                cover = copied_images[0]["web"]

            file_name = f"{record_dt.strftime('%Y-%m-%d')}-{slug}.md"
            file_path = repo_path / "_talks" / file_name
            if file_path.exists():
                raise ValueError(f"文件已存在：{file_path.name}，请修改 slug 后重试。")

            lines = [
                "---",
                f"title: {yaml_quote(title)}",
                f'date: "{record_dt.strftime("%Y-%m-%d %H:%M:%S")} {TZ_SUFFIX}"',
            ]

            for key in ("type", "venue", "location", "summary", "paper_url", "event_url"):
                value = self._entry_value(key)
                if value:
                    lines.append(f"{key}: {yaml_quote(value)}")

            if cover:
                lines.append(f"cover: {yaml_quote(cover)}")

            lines.append("---")

            body = self._text_value("body")
            body_parts: list[str] = []
            if body:
                body_parts.append(body)

            if copied_images:
                if body_parts:
                    body_parts.append("")
                for index, image_item in enumerate(copied_images, start=1):
                    alt = f"{title} Photo {index}"
                    body_parts.append(
                        f"![{alt}]({{{{ '{image_item['web']}' | relative_url }}}})"
                    )

            content = "\n".join(lines) + "\n\n"
            if body_parts:
                content += "\n\n".join(body_parts) + "\n"

            write_text_file(file_path, content)
            self._bump_pending_and_notify(file_path)
            self.clear_talk_images()
        except Exception as exc:
            messagebox.showerror("新增失败", str(exc))

    def copy_talk_images(self, repo_path: Path, image_sources: list[str]) -> list[dict[str, str]]:
        copied: list[dict[str, str]] = []
        if not image_sources:
            return copied

        target_dir = repo_path / IMAGE_TARGET_SUBDIR
        target_dir.mkdir(parents=True, exist_ok=True)

        for source in image_sources:
            src = Path(source)
            if not src.exists() or not src.is_file():
                raise ValueError(f"图片不存在：{source}")

            target = target_dir / src.name
            stem = src.stem
            suffix = src.suffix
            counter = 1
            while target.exists():
                target = target_dir / f"{stem}-{counter}{suffix}"
                counter += 1

            shutil.copy2(src, target)
            encoded_name = urllib.parse.quote(target.name)
            web_path = f"/assets/image-albert-evans/image-continue-added/{encoded_name}"
            copied.append({"absolute": str(target), "web": web_path})
        return copied

    def start_git_push(self) -> None:
        if self.pending_changes <= 0:
            messagebox.showinfo("提示", "当前没有待提交修改。")
            return

        try:
            repo_path = self.get_repo_path_or_raise()
        except Exception as exc:
            messagebox.showerror("提交失败", str(exc))
            return

        default_msg = f"Update publications/news/talks via uploader ({dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})"
        commit_message = simpledialog.askstring("Commit Message", "请输入 git commit message：", initialvalue=default_msg)
        if commit_message is None:
            return
        commit_message = commit_message.strip()
        if not commit_message:
            messagebox.showerror("提交失败", "commit message 不能为空。")
            return

        try:
            if GIT_STATUS_PATH.exists():
                GIT_STATUS_PATH.unlink()
            self.launch_git_window(repo_path, commit_message)
            self.status_var.set("已打开 git 窗口，正在执行 add/commit/push。")
            messagebox.showinfo(
                "已启动推送",
                "已打开新的终端窗口并执行:\n"
                "git add .\n"
                "git commit -m ...\n"
                "git push https://albert-jin@github.com/albert-jin/albert-evans.github.io.git\n\n"
                "窗口会保留，你可以查看命令输出。",
            )
            # 用户确认已启动提交流程后，立即清零待提交计数。
            self.pending_changes = 0
            self.state_data["pending_changes"] = 0
            save_json(STATE_PATH, self.state_data)
            self._refresh_topbar()
            self.status_var.set("已启动远端提交流程，待提交修改数已清零。")
        except Exception as exc:
            messagebox.showerror("提交失败", str(exc))

    def start_git_sync(self) -> None:
        try:
            repo_path = self.get_repo_path_or_raise()
        except Exception as exc:
            messagebox.showerror("同步失败", str(exc))
            return

        try:
            self.launch_git_sync_window(repo_path)
            self.status_var.set("已打开 git 窗口，正在检测远端并按需拉取。")
            messagebox.showinfo(
                "已启动远端同步",
                "已打开新的终端窗口并执行:\n"
                "git fetch origin\n"
                "自动检测本地与远端差异\n"
                "如远端领先则执行 git pull --no-rebase origin <当前分支>\n\n"
                "窗口会保留，你可以查看命令输出。",
            )
        except Exception as exc:
            messagebox.showerror("同步失败", str(exc))

    def launch_git_sync_window(self, repo_path: Path) -> None:
        repo = str(repo_path.resolve())
        script = f"""
$ErrorActionPreference = 'Continue'
Set-Location -LiteralPath {ps_quote(repo)}
Write-Host "[Uploader] Repo:" (Get-Location).Path

$branch = (git rev-parse --abbrev-ref HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($branch)) {{
  Write-Host "[Uploader] Unable to detect current branch."
  exit 1
}}
Write-Host "[Uploader] Branch:" $branch

git fetch origin
if ($LASTEXITCODE -ne 0) {{
  Write-Host "[Uploader] git fetch origin failed."
  exit $LASTEXITCODE
}}

$upstream = (git rev-parse --abbrev-ref --symbolic-full-name "@{{u}}" 2>$null)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($upstream)) {{
  $upstream = "origin/$branch"
  Write-Host "[Uploader] No tracking branch configured; use" $upstream
}} else {{
  $upstream = $upstream.Trim()
}}

$counts = git rev-list --left-right --count ("HEAD..." + $upstream)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($counts)) {{
  Write-Host "[Uploader] Unable to compare with upstream, trying direct pull..."
  git pull --no-rebase origin $branch
  if ($LASTEXITCODE -ne 0) {{
    Write-Host "[Uploader] git pull failed."
    exit $LASTEXITCODE
  }}
  Write-Host "[Uploader] Pull completed."
  exit 0
}}

$parts = $counts.Trim().Split(' ', [System.StringSplitOptions]::RemoveEmptyEntries)
$ahead = 0
$behind = 0
if ($parts.Length -ge 2) {{
  [int]$ahead = $parts[0]
  [int]$behind = $parts[1]
}}
Write-Host "[Uploader] Ahead:" $ahead "Behind:" $behind

if ($behind -gt 0) {{
  Write-Host "[Uploader] Remote has new commits. Pulling and merging..."
  git pull --no-rebase origin $branch
  if ($LASTEXITCODE -ne 0) {{
    Write-Host "[Uploader] git pull failed."
    exit $LASTEXITCODE
  }}
  Write-Host "[Uploader] Pull+merge completed."
}} else {{
  Write-Host "[Uploader] Local is up to date. No pull needed."
}}
"""
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        subprocess.Popen(
            ["powershell", "-NoExit", "-Command", script],
            creationflags=flags,
        )

    def launch_git_window(self, repo_path: Path, commit_message: str) -> None:
        status_file = str(GIT_STATUS_PATH.resolve())
        repo = str(repo_path.resolve())

        script = f"""
$ErrorActionPreference = 'Continue'
$statusFile = {ps_quote(status_file)}
Set-Location -LiteralPath {ps_quote(repo)}
Write-Host "[Uploader] Repo:" (Get-Location).Path

git add .
if ($LASTEXITCODE -ne 0) {{
  Write-Host "[Uploader] git add failed."
  exit $LASTEXITCODE
}}

$changes = git status --porcelain
if (-not $changes) {{
  @{{ success = $true; no_changes = $true; at = (Get-Date).ToString("s") }} |
    ConvertTo-Json |
    Set-Content -LiteralPath $statusFile -Encoding UTF8
  Write-Host "[Uploader] No changes to commit."
  exit 0
}}

git commit -m {ps_quote(commit_message)}
if ($LASTEXITCODE -ne 0) {{
  Write-Host "[Uploader] git commit failed."
  exit $LASTEXITCODE
}}

git push {ps_quote(REMOTE_PUSH_URL)}
if ($LASTEXITCODE -ne 0) {{
  Write-Host "[Uploader] git push failed."
  exit $LASTEXITCODE
}}

@{{ success = $true; no_changes = $false; at = (Get-Date).ToString("s") }} |
  ConvertTo-Json |
  Set-Content -LiteralPath $statusFile -Encoding UTF8
Write-Host "[Uploader] Push finished."
"""
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        subprocess.Popen(
            ["powershell", "-NoExit", "-Command", script],
            creationflags=flags,
        )

    def poll_git_status(self) -> None:
        if not self.git_polling:
            return

        if GIT_STATUS_PATH.exists():
            try:
                payload = json.loads(GIT_STATUS_PATH.read_text(encoding="utf-8"))
            except Exception:
                payload = {}
            if payload.get("success"):
                self.git_polling = False
                self.pending_changes = 0
                self.state_data["pending_changes"] = 0
                save_json(STATE_PATH, self.state_data)
                self._refresh_topbar()
                self.status_var.set("远端提交流程已完成。")
                messagebox.showinfo("提交完成", "检测到 push 流程完成，待提交修改数已清零。")
                return

        if time.time() - self.git_poll_started_at > 1800:
            self.git_polling = False
            self.status_var.set("暂未检测到完成标记，请在 git 窗口确认是否执行成功。")
            return

        self.after(1500, self.poll_git_status)

    def on_close(self) -> None:
        if self.pending_changes > 0:
            confirm = messagebox.askyesno(
                "提交提醒",
                f"当前仍有 {self.pending_changes} 条未提交修改。\n是否仍然关闭程序？",
            )
            if not confirm:
                return
        self.destroy()


if __name__ == "__main__":
    app = ContentUploaderApp()
    app.mainloop()
