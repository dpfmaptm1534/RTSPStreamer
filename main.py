import os
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox
from urllib.parse import urlparse


if getattr(sys, "frozen", False):
    CURRENT_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
FFMPEG_PATH = os.path.join(CURRENT_DIR, "ffmpeg.exe")
MEDIAMTX_PATH = os.path.join(CURRENT_DIR, "mediamtx.exe")
MEDIAMTX_CONFIG_PATH = os.path.join(CURRENT_DIR, "mediamtx.yml")
MEDIAMTX_LOG_PATH = os.path.join(CURRENT_DIR, "mediamtx.log")
DEFAULT_RTSP_URL = "rtsp://127.0.0.1:8554/live/stream"
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class RTSPStreamerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("영상 파일 RTSP 송출기")
        self.root.geometry("650x330")
        self.root.resizable(False, False)

        self.video_path = ""
        self.ffmpeg_process = None
        self.server_process = None
        self.server_log_file = None
        self.is_streaming = False
        self.closing = False

        self.create_widgets()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.start_internal_server()

    def create_widgets(self):
        file_frame = tk.LabelFrame(
            self.root, text=" 1. 송출할 영상 파일 ", padx=10, pady=10
        )
        file_frame.pack(fill="x", padx=15, pady=(15, 8))

        self.lbl_file = tk.Label(
            file_frame, text="선택된 파일이 없습니다.", fg="gray", anchor="w"
        )
        self.lbl_file.pack(side="left", fill="x", expand=True, padx=5)

        self.btn_browse = tk.Button(
            file_frame, text="파일 선택", width=11, command=self.browse_file
        )
        self.btn_browse.pack(side="right", padx=5)

        url_frame = tk.LabelFrame(
            self.root, text=" 2. RTSP 송출 주소 ", padx=10, pady=10
        )
        url_frame.pack(fill="x", padx=15, pady=8)

        self.entry_url = tk.Entry(url_frame)
        self.entry_url.insert(0, DEFAULT_RTSP_URL)
        self.entry_url.pack(fill="x", padx=5)

        help_label = tk.Label(
            self.root,
            text="재생 주소도 위 주소와 같습니다. VLC에서 '네트워크 스트림 열기'로 확인할 수 있습니다.",
            fg="#555555",
            anchor="w",
        )
        help_label.pack(fill="x", padx=22, pady=(2, 6))

        status_frame = tk.Frame(self.root, pady=10)
        status_frame.pack(fill="x", padx=15)

        self.lbl_server = tk.Label(
            status_frame, text="RTSP 서버: 시작 중...", fg="#d97706", anchor="w"
        )
        self.lbl_server.pack(fill="x", padx=5)

        action_frame = tk.Frame(self.root)
        action_frame.pack(fill="x", padx=15, pady=(2, 10))

        self.lbl_status = tk.Label(
            action_frame,
            text="상태: 대기 중",
            fg="#2563eb",
            font=("맑은 고딕", 10, "bold"),
        )
        self.lbl_status.pack(side="left", padx=5)

        self.btn_action = tk.Button(
            action_frame,
            text="송출 시작",
            bg="#16a34a",
            fg="white",
            font=("맑은 고딕", 10, "bold"),
            width=13,
            command=self.toggle_streaming,
            state="disabled",
        )
        self.btn_action.pack(side="right", padx=5)

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
                    "RTSP 서버: 기존 서버 사용 중 (127.0.0.1:8554)",
                    "#16a34a",
                    True,
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
                            "RTSP 서버: 정상 실행 중 (127.0.0.1:8554)",
                            "#16a34a",
                            True,
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
        if selected_file:
            self.video_path = selected_file
            self.lbl_file.config(text=os.path.basename(selected_file), fg="black")

    def toggle_streaming(self):
        if self.is_streaming:
            self.stop_streaming()
        else:
            self.start_streaming()

    def start_streaming(self):
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

        self.is_streaming = True
        self.btn_action.config(text="연결 중...", bg="#d97706", state="disabled")
        self.btn_browse.config(state="disabled")
        self.entry_url.config(state="disabled")
        self.lbl_status.config(text="상태: RTSP 서버 연결 중...", fg="#d97706")

        threading.Thread(
            target=self._run_ffmpeg, args=(rtsp_url,), daemon=True
        ).start()

    def _run_ffmpeg(self, rtsp_url):
        command = [
            FFMPEG_PATH,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-re",
            "-stream_loop",
            "-1",
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

        try:
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
            if return_code != 0 and self.is_streaming and not self.closing:
                detail = stderr.decode("utf-8", errors="replace").strip()
                if not detail:
                    detail = f"FFmpeg 종료 코드: {return_code}"
                self.root.after(0, lambda: self._show_stream_error(detail[-4000:]))
        except Exception as exc:
            if not self.closing:
                self.root.after(0, lambda: self._show_stream_error(str(exc)))
        finally:
            self.ffmpeg_process = None
            if not self.closing:
                self.root.after(0, self._reset_stream_ui)

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
