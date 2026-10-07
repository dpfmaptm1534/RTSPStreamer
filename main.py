import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urlparse

import psycopg2
from psycopg2 import sql


if getattr(sys, "frozen", False):
    CURRENT_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

FFMPEG_PATH = os.path.join(CURRENT_DIR, "ffmpeg.exe")
MEDIAMTX_PATH = os.path.join(CURRENT_DIR, "mediamtx.exe")
MEDIAMTX_CONFIG_PATH = os.path.join(CURRENT_DIR, "mediamtx.yml")
MEDIAMTX_LOG_PATH = os.path.join(CURRENT_DIR, "mediamtx.log")
FFMPEG_LOG_PATH = os.path.join(CURRENT_DIR, "ffmpeg.log")
DEFAULT_RTSP_URL = "rtsp://127.0.0.1:8554/live/stream"
RECENT_SETTINGS_PATH = os.path.join(CURRENT_DIR, "recent_settings.json")
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class RTSPStreamerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("영상 파일 RTSP 송출기 + DB 입력")
        self.root.geometry("1050x760")
        self.root.minsize(980, 690)

        self.video_path = ""
        self.video_duration = 0.0
        self.schedule_rows = []
        self.ffmpeg_process = None
        self.server_process = None
        self.server_log_file = None
        self.db_thread = None
        self.recent_settings = []
        self.is_streaming = False
        self.closing = False
        self.edit_entry = None

        self.create_widgets()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.start_internal_server()

    def create_widgets(self):
        top_frame = tk.Frame(self.root)
        top_frame.pack(fill="x", padx=14, pady=(12, 6))

        settings_frame = tk.Frame(top_frame)
        settings_frame.pack(fill="x", pady=(0, 8))

        tk.Button(settings_frame, text="설정 저장", width=10, command=self.save_settings_as).pack(
            side="left"
        )
        tk.Button(settings_frame, text="설정 불러오기", width=12, command=self.load_settings_from_file).pack(
            side="left", padx=(6, 0)
        )

        tk.Label(settings_frame, text="최근 설정").pack(side="right", padx=(8, 0))
        self.recent_settings_var = tk.StringVar(value="")
        self.combo_recent_settings = ttk.Combobox(
            settings_frame,
            width=42,
            textvariable=self.recent_settings_var,
            state="readonly",
            values=[],
        )
        self.combo_recent_settings.pack(side="right")
        self.combo_recent_settings.bind("<<ComboboxSelected>>", self.load_recent_setting)
        self.load_recent_settings()

        file_frame = tk.LabelFrame(top_frame, text=" 1. 송출할 영상 파일 ", padx=10, pady=10)
        file_frame.pack(fill="x")

        self.lbl_file = tk.Label(file_frame, text="선택된 파일이 없습니다.", fg="gray", anchor="w")
        self.lbl_file.pack(side="left", fill="x", expand=True, padx=5)

        self.lbl_duration = tk.Label(file_frame, text="", fg="#555555")
        self.lbl_duration.pack(side="left", padx=8)

        self.btn_browse = tk.Button(file_frame, text="파일 선택", width=11, command=self.browse_file)
        self.btn_browse.pack(side="right", padx=5)

        url_frame = tk.LabelFrame(top_frame, text=" 2. RTSP 송출 주소 ", padx=10, pady=10)
        url_frame.pack(fill="x", pady=(8, 0))

        self.entry_url = tk.Entry(url_frame)
        self.entry_url.insert(0, DEFAULT_RTSP_URL)
        self.entry_url.pack(fill="x", padx=5)

        self.lbl_server = tk.Label(
            top_frame, text="RTSP 서버: 시작 중...", fg="#d97706", anchor="w"
        )
        self.lbl_server.pack(fill="x", padx=8, pady=(8, 0))

        action_frame = tk.Frame(self.root, bd=1, relief="raised", bg="#f3f4f6")
        action_frame.pack(side="bottom", fill="x", padx=0, pady=0)

        self.lbl_status = tk.Label(
            action_frame,
            text="상태: 대기 중",
            fg="#2563eb",
            bg="#f3f4f6",
            font=("맑은 고딕", 10, "bold"),
        )
        self.lbl_status.pack(side="left", padx=18, pady=10)

        self.btn_action = tk.Button(
            action_frame,
            text="송출 시작",
            bg="#16a34a",
            fg="white",
            font=("맑은 고딕", 11, "bold"),
            width=16,
            height=2,
            command=self.toggle_streaming,
            state="disabled",
        )
        self.btn_action.pack(side="right", padx=18, pady=8)

        mid_frame = tk.Frame(self.root)
        mid_frame.pack(fill="both", expand=True, padx=14, pady=6)

        db_frame = tk.LabelFrame(mid_frame, text=" 3. DB INSERT 설정 ", padx=10, pady=8)
        db_frame.pack(fill="x")

        self.db_enabled_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            db_frame,
            text="송출 중 시간표에 맞춰 DB INSERT 사용",
            variable=self.db_enabled_var,
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 6))

        tk.Label(db_frame, text="DB 명 (필수)").grid(row=1, column=0, sticky="w")
        self.entry_db_name = tk.Entry(db_frame)
        self.entry_db_name.insert(0, "MFLOW")
        self.entry_db_name.grid(row=1, column=1, sticky="ew", padx=5)

        tk.Label(db_frame, text="DB 사용자 명 (필수)").grid(row=1, column=2, sticky="e")
        self.entry_db_user = tk.Entry(db_frame)
        self.entry_db_user.insert(0, "postgres")
        self.entry_db_user.grid(row=1, column=3, sticky="ew", padx=(5, 0))

        tk.Label(db_frame, text="패스워드(암호) (필수)").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.entry_db_password = tk.Entry(db_frame, show="*")
        self.entry_db_password.grid(row=2, column=1, sticky="ew", padx=5, pady=(6, 0))

        tk.Label(db_frame, text="접속주소(host) (필수)").grid(row=2, column=2, sticky="e", pady=(6, 0))
        self.entry_db_host = tk.Entry(db_frame)
        self.entry_db_host.insert(0, "localhost")
        self.entry_db_host.grid(row=2, column=3, sticky="ew", padx=(5, 0), pady=(6, 0))

        tk.Label(db_frame, text="접속포트(port) (필수)").grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.entry_db_port = tk.Entry(db_frame)
        self.entry_db_port.insert(0, "5432")
        self.entry_db_port.grid(row=3, column=1, sticky="ew", padx=5, pady=(6, 0))

        tk.Button(db_frame, text="DB 연결 테스트", command=self.test_db_connection).grid(
            row=3, column=3, sticky="e", pady=(6, 0)
        )

        tk.Label(db_frame, text="스키마").grid(row=4, column=0, sticky="w", pady=(6, 0))
        self.entry_schema = tk.Entry(db_frame)
        self.entry_schema.insert(0, "MEASURE")
        self.entry_schema.grid(row=4, column=1, sticky="ew", padx=5, pady=(6, 0))

        tk.Label(db_frame, text="테이블").grid(row=4, column=2, sticky="e", pady=(6, 0))
        self.entry_table = tk.Entry(db_frame)
        self.entry_table.insert(0, "water_level_log")
        self.entry_table.grid(row=4, column=3, sticky="ew", padx=(5, 0), pady=(6, 0))

        tk.Label(db_frame, text="현재시간 컬럼").grid(row=5, column=0, sticky="w", pady=(6, 0))
        self.entry_time_col = tk.Entry(db_frame, width=18)
        self.entry_time_col.insert(0, "created_at")
        self.entry_time_col.grid(row=5, column=1, sticky="ew", padx=5, pady=(6, 0))

        tk.Label(db_frame, text="수위값 컬럼").grid(row=5, column=2, sticky="e", pady=(6, 0))
        self.entry_value_col = tk.Entry(db_frame, width=18)
        self.entry_value_col.insert(0, "level_value")
        self.entry_value_col.grid(row=5, column=3, sticky="ew", padx=(5, 0), pady=(6, 0))

        db_frame.columnconfigure(1, weight=1)
        db_frame.columnconfigure(3, weight=1)

        table_frame = tk.LabelFrame(mid_frame, text=" 4. 영상 시간별 수위값 표 ", padx=10, pady=8)
        table_frame.pack(fill="both", expand=True, pady=(8, 0))

        toolbar = tk.Frame(table_frame)
        toolbar.pack(fill="x", pady=(0, 6))

        tk.Label(toolbar, text="간격").pack(side="left")
        self.interval_value_var = tk.StringVar(value="5")
        self.spin_interval = tk.Spinbox(
            toolbar, from_=1, to=3600, width=6, textvariable=self.interval_value_var
        )
        self.spin_interval.pack(side="left", padx=(5, 4))

        self.interval_unit_var = tk.StringVar(value="초")
        ttk.Combobox(
            toolbar,
            width=6,
            textvariable=self.interval_unit_var,
            values=["초", "분"],
            state="readonly",
        ).pack(side="left")

        tk.Button(toolbar, text="표 다시 만들기", command=self.rebuild_schedule_from_ui).pack(
            side="left", padx=8
        )
        tk.Button(toolbar, text="수위값 비우기", command=self.clear_values).pack(side="left")

        self.lbl_paste_help = tk.Label(
            toolbar,
            text="엑셀에서 수위값을 여러 행 복사한 뒤 표에서 Ctrl+V로 붙여넣기",
            fg="#555555",
        )
        self.lbl_paste_help.pack(side="left", padx=12)

        self.lbl_db_status = tk.Label(toolbar, text="DB INSERT: 대기", fg="#555555")
        self.lbl_db_status.pack(side="right")

        tree_box = tk.Frame(table_frame)
        tree_box.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(
            tree_box,
            columns=("time", "value"),
            show="headings",
            selectmode="extended",
            height=14,
        )
        self.tree.heading("time", text="영상 시간")
        self.tree.heading("value", text="수위값")
        self.tree.column("time", width=140, anchor="center", stretch=False)
        self.tree.column("value", width=780, anchor="w", stretch=True)

        y_scroll = ttk.Scrollbar(tree_box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=y_scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        y_scroll.pack(side="right", fill="y")

        self.tree.bind("<Double-1>", self.start_cell_edit)
        self.tree.bind("<ButtonRelease-1>", self.select_clicked_row)
        self.tree.bind("<Control-v>", self.paste_from_clipboard)
        self.tree.bind("<Control-V>", self.paste_from_clipboard)
        self.tree.bind("<Delete>", self.clear_selected_values)
        self.tree.bind("<BackSpace>", self.clear_selected_values)
        self.tree.bind("<Key>", self.start_typing_in_selected_cell)

    def set_server_status(self, text, color, ready=False):
        if self.closing:
            return
        self.lbl_server.config(text=text, fg=color)
        if not self.is_streaming:
            self.btn_action.config(state="normal" if ready else "disabled")

    def start_internal_server(self):
        if not os.path.isfile(MEDIAMTX_PATH):
            messagebox.showerror("실행 오류", "mediamtx.exe를 찾을 수 없습니다.")
            self.set_server_status("RTSP 서버: 실행 파일 없음", "#dc2626")
            return
        if not os.path.isfile(MEDIAMTX_CONFIG_PATH):
            messagebox.showerror("실행 오류", "mediamtx.yml 설정 파일을 찾을 수 없습니다.")
            self.set_server_status("RTSP 서버: 설정 파일 없음", "#dc2626")
            return
        threading.Thread(target=self._start_server_worker, daemon=True).start()

    def _start_server_worker(self):
        if self._port_is_open("127.0.0.1", 8554):
            self.root.after(
                0,
                lambda: self.set_server_status(
                    "RTSP 서버: 기존 서버 사용 중 (127.0.0.1:8554)", "#16a34a", True
                ),
            )
            return

        try:
            self.server_log_file = open(
                MEDIAMTX_LOG_PATH, "w", encoding="utf-8", errors="replace"
            )
            self.server_process = subprocess.Popen(
                [MEDIAMTX_PATH, MEDIAMTX_CONFIG_PATH],
                cwd=CURRENT_DIR,
                stdout=self.server_log_file,
                stderr=subprocess.STDOUT,
                creationflags=CREATE_NO_WINDOW,
            )

            deadline = time.time() + 5
            while time.time() < deadline:
                if self.server_process.poll() is not None:
                    raise RuntimeError(self._read_server_log())
                if self._port_is_open("127.0.0.1", 8554):
                    self.root.after(
                        0,
                        lambda: self.set_server_status(
                            "RTSP 서버: 정상 실행 중 (127.0.0.1:8554)", "#16a34a", True
                        ),
                    )
                    return
                time.sleep(0.1)
            raise RuntimeError("5초 안에 8554 포트가 열리지 않았습니다.")
        except Exception as exc:
            detail = str(exc).strip() or "알 수 없는 서버 실행 오류"
            self.root.after(0, lambda: self._show_server_error(detail))

    def _show_server_error(self, detail):
        self.set_server_status("RTSP 서버: 실행 실패", "#dc2626")
        messagebox.showerror(
            "RTSP 서버 실행 실패",
            f"내장 RTSP 서버를 시작하지 못했습니다.\n\n{detail}",
        )

    @staticmethod
    def _port_is_open(host, port):
        try:
            with socket.create_connection((host, port), timeout=0.25):
                return True
        except OSError:
            return False

    def _read_server_log(self):
        if self.server_log_file:
            self.server_log_file.flush()
        try:
            with open(MEDIAMTX_LOG_PATH, "r", encoding="utf-8", errors="replace") as log:
                return log.read()[-3000:]
        except OSError:
            return "MediaMTX가 시작 직후 종료되었습니다."

    def browse_file(self):
        selected_file = filedialog.askopenfilename(
            title="송출할 영상 선택",
            filetypes=[
                ("동영상 파일", "*.mp4 *.avi *.mkv *.mov *.wmv *.webm *.ts"),
                ("모든 파일", "*.*"),
            ],
        )
        if not selected_file:
            return

        self.video_path = selected_file
        self.lbl_file.config(text=os.path.basename(selected_file), fg="black")
        self.video_duration = self.get_video_duration(selected_file)
        if self.video_duration <= 0:
            self.lbl_duration.config(text="길이 확인 실패", fg="#dc2626")
            self.schedule_rows = []
            self.refresh_tree()
            return

        self.lbl_duration.config(
            text=f"영상 길이: {self.format_time(self.video_duration)}", fg="#555555"
        )
        self.rebuild_schedule_from_ui()

    def load_recent_settings(self):
        try:
            with open(RECENT_SETTINGS_PATH, "r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError):
            data = []

        self.recent_settings = [
            path for path in data if isinstance(path, str) and os.path.isfile(path)
        ][:10]
        self.refresh_recent_settings_combo()

    def save_recent_settings(self):
        try:
            with open(RECENT_SETTINGS_PATH, "w", encoding="utf-8") as file:
                json.dump(self.recent_settings[:10], file, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def refresh_recent_settings_combo(self):
        if not hasattr(self, "combo_recent_settings"):
            return
        labels = [self.make_recent_label(path) for path in self.recent_settings]
        self.combo_recent_settings["values"] = labels
        if labels and self.recent_settings_var.get() not in labels:
            self.recent_settings_var.set(labels[0])
        elif not labels:
            self.recent_settings_var.set("")

    @staticmethod
    def make_recent_label(path):
        return os.path.basename(path) or path

    def remember_setting_path(self, path):
        path = os.path.abspath(path)
        self.recent_settings = [item for item in self.recent_settings if os.path.abspath(item) != path]
        self.recent_settings.insert(0, path)
        self.recent_settings = self.recent_settings[:10]
        self.save_recent_settings()
        self.refresh_recent_settings_combo()
        self.recent_settings_var.set(self.make_recent_label(path))

    def save_settings_as(self):
        self.finish_cell_edit(save=True)
        selected_file = filedialog.asksaveasfilename(
            title="설정 저장",
            defaultextension=".json",
            filetypes=[("RTSPStreamer 설정", "*.json"), ("모든 파일", "*.*")],
            initialfile="rtspstreamer_settings.json",
        )
        if not selected_file:
            return

        data = self.collect_settings()
        try:
            with open(selected_file, "w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)
        except OSError as exc:
            messagebox.showerror("설정 저장 실패", str(exc))
            return

        self.remember_setting_path(selected_file)
        messagebox.showinfo("설정 저장", "설정을 저장했습니다.")

    def load_settings_from_file(self):
        selected_file = filedialog.askopenfilename(
            title="설정 불러오기",
            filetypes=[("RTSPStreamer 설정", "*.json"), ("모든 파일", "*.*")],
        )
        if selected_file:
            self.apply_settings_file(selected_file)

    def load_recent_setting(self, _event=None):
        selected_index = self.combo_recent_settings.current()
        if selected_index < 0 or selected_index >= len(self.recent_settings):
            return
        self.apply_settings_file(self.recent_settings[selected_index])

    def collect_settings(self):
        return {
            "version": 1,
            "video_path": self.video_path,
            "rtsp_url": self.entry_url.get().strip(),
            "db_enabled": self.db_enabled_var.get(),
            "db_name": self.entry_db_name.get().strip(),
            "db_user": self.entry_db_user.get().strip(),
            "db_password": self.entry_db_password.get(),
            "db_host": self.entry_db_host.get().strip(),
            "db_port": self.entry_db_port.get().strip(),
            "schema": self.entry_schema.get().strip(),
            "table": self.entry_table.get().strip(),
            "time_column": self.entry_time_col.get().strip(),
            "value_column": self.entry_value_col.get().strip(),
            "interval_value": self.interval_value_var.get(),
            "interval_unit": self.interval_unit_var.get(),
            "video_duration": self.video_duration,
            "schedule_rows": self.schedule_rows,
        }

    def apply_settings_file(self, path):
        try:
            with open(path, "r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError) as exc:
            messagebox.showerror("설정 불러오기 실패", str(exc))
            return

        try:
            self.apply_settings(data)
        except Exception as exc:
            messagebox.showerror("설정 적용 실패", str(exc))
            return

        self.remember_setting_path(path)

    def apply_settings(self, data):
        self.finish_cell_edit(save=False)
        self.video_path = str(data.get("video_path", "") or "")
        if self.video_path:
            self.lbl_file.config(text=os.path.basename(self.video_path), fg="black")
        else:
            self.lbl_file.config(text="선택된 파일이 없습니다.", fg="gray")

        if self.video_path and os.path.isfile(self.video_path):
            self.video_duration = self.get_video_duration(self.video_path)
        else:
            self.video_duration = float(data.get("video_duration", 0) or 0)

        if self.video_duration > 0:
            self.lbl_duration.config(
                text=f"영상 길이: {self.format_time(self.video_duration)}", fg="#555555"
            )
        elif self.video_path:
            self.lbl_duration.config(text="영상 파일 없음/길이 확인 실패", fg="#dc2626")
        else:
            self.lbl_duration.config(text="", fg="#555555")

        self.set_entry_value(self.entry_url, data.get("rtsp_url", DEFAULT_RTSP_URL))
        self.db_enabled_var.set(bool(data.get("db_enabled", True)))
        self.set_entry_value(self.entry_db_name, data.get("db_name", data.get("database", "MFLOW")))
        self.set_entry_value(self.entry_db_user, data.get("db_user", data.get("user", "postgres")))
        self.set_entry_value(self.entry_db_password, data.get("db_password", data.get("password", "")))
        self.set_entry_value(self.entry_db_host, data.get("db_host", data.get("host", "localhost")))
        self.set_entry_value(self.entry_db_port, data.get("db_port", data.get("port", "5432")))
        self.set_entry_value(self.entry_schema, data.get("schema", "MEASURE"))
        self.set_entry_value(self.entry_table, data.get("table", "water_level_log"))
        self.set_entry_value(self.entry_time_col, data.get("time_column", "created_at"))
        self.set_entry_value(self.entry_value_col, data.get("value_column", "level_value"))

        self.interval_value_var.set(str(data.get("interval_value", "5") or "5"))
        interval_unit = data.get("interval_unit", "초")
        self.interval_unit_var.set(interval_unit if interval_unit in ("초", "분") else "초")

        loaded_rows = data.get("schedule_rows", [])
        if isinstance(loaded_rows, list) and loaded_rows:
            self.schedule_rows = []
            for row in loaded_rows:
                if not isinstance(row, dict):
                    continue
                offset = float(row.get("offset", 0) or 0)
                time_text = str(row.get("time") or self.format_time(offset))
                value = str(row.get("value", "") or "")
                self.schedule_rows.append({"offset": offset, "time": time_text, "value": value})
            self.refresh_tree()
        elif self.video_duration > 0:
            self.rebuild_schedule_from_ui()
        else:
            self.schedule_rows = []
            self.refresh_tree()

    @staticmethod
    def set_entry_value(entry, value):
        entry.delete(0, tk.END)
        entry.insert(0, str(value or ""))

    def get_video_duration(self, path):
        try:
            result = subprocess.run(
                [FFMPEG_PATH, "-hide_banner", "-i", path],
                cwd=CURRENT_DIR,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
                timeout=15,
            )
        except Exception:
            return 0.0

        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
        if not match:
            return 0.0
        hours, minutes, seconds = match.groups()
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    def rebuild_schedule_from_ui(self):
        if self.video_duration <= 0:
            messagebox.showwarning("영상 확인", "먼저 영상 파일을 선택해 주세요.")
            return

        try:
            interval_value = int(self.interval_value_var.get())
            if interval_value <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("간격 확인", "간격은 1 이상의 숫자로 입력해 주세요.")
            return

        interval_seconds = interval_value * 60 if self.interval_unit_var.get() == "분" else interval_value
        old_values = {row["time"]: row.get("value", "") for row in self.schedule_rows}

        rows = []
        offset = 0
        while offset < self.video_duration:
            time_text = self.format_time(offset)
            rows.append({"offset": float(offset), "time": time_text, "value": old_values.get(time_text, "")})
            offset += interval_seconds

        last_text = self.format_time(self.video_duration)
        if not rows or rows[-1]["time"] != last_text:
            rows.append(
                {
                    "offset": float(self.video_duration),
                    "time": last_text,
                    "value": old_values.get(last_text, ""),
                }
            )

        self.schedule_rows = rows
        self.refresh_tree()

    def refresh_tree(self):
        self.finish_cell_edit(save=True)
        for item in self.tree.get_children():
            self.tree.delete(item)
        for index, row in enumerate(self.schedule_rows):
            self.tree.insert("", "end", iid=str(index), values=(row["time"], row.get("value", "")))

    def clear_values(self):
        selected = self.tree.selection()
        if selected:
            self.clear_selected_values()
            return
        for row in self.schedule_rows:
            row["value"] = ""
        self.refresh_tree()

    @staticmethod
    def format_time(seconds):
        total = max(0, int(round(seconds)))
        hours = total // 3600
        minutes = (total % 3600) // 60
        secs = total % 60
        if hours:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"

    def start_cell_edit(self, event):
        region = self.tree.identify("region", event.x, event.y)
        column = self.tree.identify_column(event.x)
        item = self.tree.identify_row(event.y)
        if region != "cell" or column != "#2" or not item:
            return

        self.open_value_editor(item)

    def open_value_editor(self, item, initial_text=None, append=False):
        self.finish_cell_edit(save=True)
        bbox = self.tree.bbox(item, "#2")
        if not bbox:
            self.tree.see(item)
            self.root.update_idletasks()
            bbox = self.tree.bbox(item, "#2")
        if not bbox:
            return

        x, y, width, height = bbox
        value = self.tree.set(item, "value")
        self.edit_entry = tk.Entry(self.tree)
        if initial_text is None:
            self.edit_entry.insert(0, value)
        elif append:
            self.edit_entry.insert(0, value + initial_text)
        else:
            self.edit_entry.insert(0, initial_text)
        self.edit_entry.select_range(0, tk.END)
        if initial_text is not None:
            self.edit_entry.icursor(tk.END)
        self.edit_entry.focus_set()
        self.edit_entry.place(x=x, y=y, width=width, height=height)
        self.edit_entry.item_id = item
        self.edit_entry.bind("<Return>", lambda _event: self.move_from_editor(1))
        self.edit_entry.bind("<Down>", lambda _event: self.move_from_editor(1))
        self.edit_entry.bind("<Up>", lambda _event: self.move_from_editor(-1))
        self.edit_entry.bind("<Tab>", lambda _event: self.move_from_editor(1))
        self.edit_entry.bind("<Shift-Tab>", lambda _event: self.move_from_editor(-1))
        self.edit_entry.bind("<Escape>", lambda _event: self.finish_cell_edit(save=False))
        self.edit_entry.bind("<FocusOut>", lambda _event: self.finish_cell_edit(save=True))

    def select_clicked_row(self, event):
        item = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if item and column == "#2":
            self.tree.focus(item)
            if not (event.state & 0x0004) and not (event.state & 0x0001):
                self.tree.selection_set(item)
            self.tree.focus_set()

    def start_typing_in_selected_cell(self, event):
        if event.keysym in {
            "Up",
            "Down",
            "Left",
            "Right",
            "Home",
            "End",
            "Prior",
            "Next",
            "Tab",
            "Return",
            "Escape",
        }:
            return
        if event.state & 0x0004:
            return
        if event.keysym in {"Delete", "BackSpace"}:
            return
        if not event.char or ord(event.char) < 32:
            return

        item = self.tree.focus()
        if not item:
            selected = self.tree.selection()
            item = selected[0] if selected else ""
        if not item:
            return "break"

        self.open_value_editor(item, initial_text=event.char)
        return "break"

    def finish_cell_edit(self, save):
        if not self.edit_entry:
            return
        entry = self.edit_entry
        self.edit_entry = None
        if save and hasattr(entry, "item_id"):
            item = entry.item_id
            value = entry.get().strip()
            if item in self.tree.get_children():
                self.tree.set(item, "value", value)
            index = int(item)
            if 0 <= index < len(self.schedule_rows):
                self.schedule_rows[index]["value"] = value
        entry.destroy()

    def move_from_editor(self, delta):
        item = self.edit_entry.item_id if self.edit_entry and hasattr(self.edit_entry, "item_id") else self.tree.focus()
        self.finish_cell_edit(save=True)
        self.move_selection(delta)
        return "break"

    def move_selection(self, delta):
        children = self.tree.get_children()
        if not children:
            return

        current = self.tree.focus() or (self.tree.selection()[0] if self.tree.selection() else children[0])
        try:
            current_index = children.index(current)
        except ValueError:
            current_index = 0

        next_index = min(max(current_index + delta, 0), len(children) - 1)
        next_item = children[next_index]
        self.tree.selection_set(next_item)
        self.tree.focus(next_item)
        self.tree.see(next_item)
        self.tree.focus_set()

    def paste_from_clipboard(self, _event=None):
        self.finish_cell_edit(save=True)
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            return "break"

        lines = [line for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if line != ""]
        if not lines:
            return "break"

        selected = self.tree.selection()
        start_index = int(selected[0]) if selected else 0

        for row_offset, line in enumerate(lines):
            index = start_index + row_offset
            if index >= len(self.schedule_rows):
                break
            cells = line.split("\t")
            value = cells[-1].strip() if len(cells) >= 2 else cells[0].strip()
            self.schedule_rows[index]["value"] = value
            self.tree.set(str(index), "value", value)

        return "break"

    def clear_selected_values(self, _event=None):
        self.finish_cell_edit(save=False)
        selected = self.tree.selection()
        if not selected:
            focused = self.tree.focus()
            selected = (focused,) if focused else ()

        for item in selected:
            try:
                index = int(item)
            except ValueError:
                continue
            if 0 <= index < len(self.schedule_rows):
                self.schedule_rows[index]["value"] = ""
                self.tree.set(item, "value", "")

        return "break"

    def toggle_streaming(self):
        if self.is_streaming:
            self.stop_streaming()
        else:
            self.start_streaming()

    def start_streaming(self):
        self.finish_cell_edit(save=True)
        if not os.path.isfile(self.video_path):
            messagebox.showwarning("파일 확인", "먼저 송출할 영상 파일을 선택해 주세요.")
            return
        if not os.path.isfile(FFMPEG_PATH):
            messagebox.showerror("실행 오류", "ffmpeg.exe를 찾을 수 없습니다.")
            return

        rtsp_url = self.entry_url.get().strip()
        parsed = urlparse(rtsp_url)
        if parsed.scheme.lower() not in ("rtsp", "rtsps") or not parsed.hostname:
            messagebox.showwarning(
                "주소 확인", "올바른 RTSP 주소를 입력해 주세요.\n예: rtsp://127.0.0.1:8554/live/stream"
            )
            return

        if self.db_enabled_var.get():
            try:
                self.prepare_database()
            except Exception as exc:
                messagebox.showerror("DB 설정 오류", str(exc))
                return

        self.is_streaming = True
        self.btn_action.config(text="연결 중...", bg="#d97706", state="disabled")
        self.btn_browse.config(state="disabled")
        self.entry_url.config(state="disabled")
        self.lbl_status.config(text="상태: RTSP 서버 연결 중...", fg="#d97706")

        if self.db_enabled_var.get():
            self.db_thread = threading.Thread(target=self._run_db_scheduler, daemon=True)
            self.db_thread.start()

        threading.Thread(target=self._run_ffmpeg, args=(rtsp_url,), daemon=True).start()

    def validate_identifier(self, label, value, allow_empty=False):
        value = value.strip()
        if allow_empty and not value:
            return ""
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError(f"{label}은 영문/숫자/밑줄만 사용할 수 있고 숫자로 시작할 수 없습니다: {value}")
        return value

    @staticmethod
    def quote_identifier(value):
        return '"' + value.replace('"', '""') + '"'

    def get_db_config(self):
        db_name = self.entry_db_name.get().strip()
        db_user = self.entry_db_user.get().strip()
        db_password = self.entry_db_password.get()
        db_host = self.entry_db_host.get().strip()
        db_port = self.entry_db_port.get().strip()

        missing = []
        if not db_name:
            missing.append("DB 명")
        if not db_user:
            missing.append("DB 사용자 명")
        if not db_password:
            missing.append("패스워드")
        if not db_host:
            missing.append("접속주소(host)")
        if not db_port:
            missing.append("접속포트(port)")
        if missing:
            raise ValueError("필수 DB 정보를 입력해 주세요: " + ", ".join(missing))

        try:
            port_number = int(db_port)
        except ValueError as exc:
            raise ValueError("접속포트(port)는 숫자로 입력해 주세요.") from exc

        return {
            "db_name": db_name,
            "db_user": db_user,
            "db_password": db_password,
            "db_host": db_host,
            "db_port": port_number,
            "schema": self.validate_identifier("스키마명", self.entry_schema.get(), allow_empty=True),
            "table": self.validate_identifier("테이블명", self.entry_table.get()),
            "time_col": self.validate_identifier("현재시간 컬럼명", self.entry_time_col.get()),
            "value_col": self.validate_identifier("수위값 컬럼명", self.entry_value_col.get()),
        }

    def open_db_connection(self, config):
        return psycopg2.connect(
            dbname=config["db_name"],
            user=config["db_user"],
            password=config["db_password"],
            host=config["db_host"],
            port=config["db_port"],
            connect_timeout=5,
        )

    @staticmethod
    def table_identifier(config):
        if config.get("schema"):
            return sql.Identifier(config["schema"], config["table"])
        return sql.Identifier(config["table"])

    def test_db_connection(self):
        try:
            config = self.get_db_config()
            with self.open_db_connection(config) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
                    if config.get("schema"):
                        cursor.execute(
                            """
                            SELECT 1
                            FROM information_schema.tables
                            WHERE table_schema = %s AND table_name = %s
                            """,
                            (config["schema"], config["table"]),
                        )
                    else:
                        cursor.execute(
                            """
                            SELECT 1
                            FROM information_schema.tables
                            WHERE table_name = %s
                            """,
                            (config["table"],),
                        )
                    table_exists = cursor.fetchone() is not None
        except Exception as exc:
            messagebox.showerror("DB 연결 실패", str(exc))
            return
        table_name = f"{config['schema']}.{config['table']}" if config.get("schema") else config["table"]
        suffix = f"\n대상 테이블 확인: {table_name}" if table_exists else f"\n대상 테이블 없음: {table_name}\n송출 시작 시 자동 생성합니다."
        messagebox.showinfo("DB 연결 성공", "PostgreSQL DB 연결에 성공했습니다." + suffix)

    def prepare_database(self):
        config = self.get_db_config()

        columns = [
            sql.SQL("{} TIMESTAMP NOT NULL").format(sql.Identifier(config["time_col"]))
        ]
        columns.append(sql.SQL("{} DOUBLE PRECISION").format(sql.Identifier(config["value_col"])))

        query = sql.SQL("CREATE TABLE IF NOT EXISTS {} ({})").format(
            self.table_identifier(config),
            sql.SQL(", ").join(columns),
        )

        with self.open_db_connection(config) as conn:
            with conn.cursor() as cursor:
                cursor.execute(query)
            conn.commit()

    def _run_db_scheduler(self):
        rows = [
            dict(row)
            for row in self.schedule_rows
            if str(row.get("value", "")).strip() != ""
        ]
        if not rows:
            self.root.after(
                0,
                lambda: self.lbl_db_status.config(
                    text="DB INSERT: 입력할 수위값 없음", fg="#d97706"
                ),
            )
            return

        config = self.get_db_config()
        start_mono = time.monotonic()
        cycle_index = 0
        inserted = set()
        insert_count = 0
        duration = max(self.video_duration, 1.0)

        self.root.after(0, lambda: self.lbl_db_status.config(text="DB INSERT: 실행 중", fg="#16a34a"))

        while self.is_streaming and not self.closing:
            elapsed = time.monotonic() - start_mono
            cycle_start = cycle_index * duration

            for row_index, row in enumerate(rows):
                key = (cycle_index, row_index)
                target = cycle_start + float(row["offset"])
                if key not in inserted and elapsed >= target:
                    try:
                        self.insert_db_row(config, row)
                        insert_count += 1
                        inserted.add(key)
                        self.root.after(
                            0,
                            lambda count=insert_count: self.lbl_db_status.config(
                                text=f"DB INSERT: {count}건 입력", fg="#16a34a"
                            ),
                        )
                    except Exception as exc:
                        self.root.after(
                            0,
                            lambda err=str(exc): self.lbl_db_status.config(
                                text=f"DB INSERT 오류: {err[:80]}", fg="#dc2626"
                            ),
                        )

            if elapsed >= (cycle_index + 1) * duration + 0.2:
                cycle_index += 1
                inserted.clear()

            time.sleep(0.1)

    def insert_db_row(self, config, row):
        columns = [sql.Identifier(config["time_col"])]
        values = [datetime.now()]

        columns.append(sql.Identifier(config["value_col"]))
        raw_value = str(row.get("value", "")).strip()
        try:
            value = float(raw_value)
        except ValueError:
            raise ValueError(f"수위값은 숫자여야 합니다: {raw_value}")
        values.append(value)

        query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            self.table_identifier(config),
            sql.SQL(", ").join(columns),
            sql.SQL(", ").join(sql.Placeholder() * len(values)),
        )

        with self.open_db_connection(config) as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, values)
            conn.commit()

    def _run_ffmpeg(self, rtsp_url):
        attempts = [
            self._build_ffmpeg_command(rtsp_url, repair_timestamps=False),
            self._build_ffmpeg_command(rtsp_url, repair_timestamps=True),
        ]
        last_error = ""

        try:
            for attempt_number, command in enumerate(attempts):
                if not self.is_streaming or self.closing:
                    return
                if attempt_number == 1:
                    self.root.after(0, self._mark_repairing)

                return_code, error_text = self._execute_ffmpeg(command)
                last_error = error_text

                if return_code == 0 or not self.is_streaming or self.closing:
                    return
                if attempt_number == 0 and self._is_timestamp_error(error_text):
                    continue
                break

            if self.is_streaming and not self.closing:
                detail = last_error.strip() or "FFmpeg가 오류 코드와 함께 종료되었습니다."
                self.root.after(0, lambda: self._show_stream_error(detail[-4000:]))
        except Exception as exc:
            if not self.closing:
                self.root.after(0, lambda: self._show_stream_error(str(exc)))
        finally:
            self.ffmpeg_process = None
            if not self.closing:
                self.root.after(0, self._reset_stream_ui)

    def _build_ffmpeg_command(self, rtsp_url, repair_timestamps):
        command = [
            FFMPEG_PATH,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-re",
            "-stream_loop",
            "-1",
        ]

        if repair_timestamps:
            command.extend(
                [
                    "-ignore_editlist",
                    "1",
                    "-fflags",
                    "+genpts+discardcorrupt",
                    "-err_detect",
                    "ignore_err",
                ]
            )

        command.extend(
            [
                "-i",
                self.video_path,
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-tune",
                "zerolatency",
                "-pix_fmt",
                "yuv420p",
                "-g",
                "60",
                "-keyint_min",
                "60",
                "-sc_threshold",
                "0",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-f",
                "rtsp",
                "-rtsp_transport",
                "tcp",
                rtsp_url,
            ]
        )
        return command

    def _execute_ffmpeg(self, command):
        self.ffmpeg_process = subprocess.Popen(
            command,
            cwd=CURRENT_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW,
        )

        time.sleep(1)
        if self.ffmpeg_process.poll() is None and self.is_streaming:
            self.root.after(0, self._mark_streaming)

        _, stderr = self.ffmpeg_process.communicate()
        return_code = self.ffmpeg_process.returncode
        error_text = stderr.decode("utf-8", errors="replace").strip()

        try:
            with open(FFMPEG_LOG_PATH, "w", encoding="utf-8", errors="replace") as log:
                log.write(error_text)
        except OSError:
            pass

        self.ffmpeg_process = None
        return return_code, error_text

    @staticmethod
    def _is_timestamp_error(error_text):
        lowered = error_text.lower()
        indicators = (
            "missing key frame",
            "cannot find an index entry",
            "edit list",
            "non-monotonous dts",
            "invalid, non monotonically increasing dts",
            "operation not permitted",
        )
        return any(indicator in lowered for indicator in indicators)

    def _mark_repairing(self):
        if not self.is_streaming or self.closing:
            return
        self.btn_action.config(text="복구 재시도 중...", bg="#d97706", state="disabled")
        self.lbl_status.config(
            text="상태: 영상 타임스탬프를 복구하여 다시 연결 중...", fg="#d97706"
        )

    def _mark_streaming(self):
        if not self.is_streaming or self.closing:
            return
        self.btn_action.config(text="송출 중지", bg="#dc2626", state="normal")
        self.lbl_status.config(text="상태: 송출 중 (영상 반복 재생)", fg="#16a34a")

    def _show_stream_error(self, detail):
        messagebox.showerror(
            "RTSP 송출 실패",
            f"송출을 시작하지 못했거나 송출이 중단되었습니다.\n\n{detail}",
        )

    def stop_streaming(self):
        self.is_streaming = False
        process = self.ffmpeg_process
        if process and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=2)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    process.kill()
                except OSError:
                    pass
        self._reset_stream_ui()

    def _reset_stream_ui(self):
        if self.closing:
            return
        self.is_streaming = False
        self.btn_action.config(text="송출 시작", bg="#16a34a", state="normal")
        self.btn_browse.config(state="normal")
        self.entry_url.config(state="normal")
        self.lbl_status.config(text="상태: 대기 중", fg="#2563eb")
        if self.db_enabled_var.get():
            self.lbl_db_status.config(text="DB INSERT: 대기", fg="#555555")

    def close(self):
        self.closing = True
        self.is_streaming = False

        if self.ffmpeg_process and self.ffmpeg_process.poll() is None:
            try:
                self.ffmpeg_process.kill()
            except OSError:
                pass

        if self.server_process and self.server_process.poll() is None:
            try:
                self.server_process.terminate()
                self.server_process.wait(timeout=2)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    self.server_process.kill()
                except OSError:
                    pass

        if self.server_log_file:
            self.server_log_file.close()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    RTSPStreamerGUI(root)
    root.mainloop()
