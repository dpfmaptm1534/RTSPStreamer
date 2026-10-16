"""Run with .venv/Scripts/python.exe -m unittest discover -s tests -v.

No production DB is contacted. RTSP checks use their own loopback server/port.
"""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main


class Root:
    def after(self, _delay, callback):
        callback()


class Label:
    def config(self, **_kwargs):
        pass


def app_stub():
    app = object.__new__(main.RTSPStreamerGUI)
    app.root = Root()
    app.lbl_db_status = Label()
    app.is_streaming = True
    app.closing = False
    app.ffmpeg_process = None
    app.stream_progress = None
    app.stream_attempt = 0
    app.streaming_source_mode = "file"
    app.streaming_interval_seconds = 1
    app.streaming_frame_rate = 10
    app.video_duration = 2
    app.streaming_video_duration = 2
    app._mark_streaming = lambda: None
    return app


class SchedulerTests(unittest.TestCase):
    def test_db_waits_for_frames_and_uses_current_value_after_loop_and_restart(self):
        app = app_stub()
        app.schedule_rows = [
            {"offset": 0, "value": "1"},
            {"offset": 1, "value": "2"},
            {"offset": 2, "value": "3"},
        ]
        app.get_db_config = lambda: {}
        inserted = []
        app.insert_db_row = lambda _config, row: inserted.append(row["value"])
        sequence = iter([(1, 0), (1, 0.4), (1, 0.4), (1, 1.2), (1, 2.1), (2, 0), (2, 1.2)])

        def tick(_seconds):
            app.schedule_rows[1]["value"] = "2.502"
            try:
                app.stream_progress = next(sequence)
            except StopIteration:
                app.is_streaming = False

        with patch.object(main.time, "sleep", tick):
            app._run_db_scheduler()
        self.assertEqual(inserted, ["1", "2.502", "3", "1", "1", "2.502"])

    def test_highlight_does_not_advance_when_output_is_stalled(self):
        app = app_stub()
        app.schedule_rows = [{"offset": 0}, {"offset": 1}]
        highlighted = []
        app.set_elapsed_highlight = highlighted.append
        sequence = iter([(1, 0.2), (1, 0.2), (1, 1.2), (1, 2.2), None])

        def tick(_seconds):
            try:
                app.stream_progress = next(sequence)
            except StopIteration:
                app.is_streaming = False

        with patch.object(main.time, "sleep", tick):
            app._run_elapsed_highlight()
        self.assertEqual(highlighted, [None, 0, 0, 1, 0, None])

    def test_watchdog_terminates_live_process_with_no_frame_progress(self):
        app = app_stub()
        real_monotonic = time.monotonic
        code = "import time; print('frame=1\\nout_time_us=100000\\nprogress=continue', flush=True); time.sleep(60)"
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            with patch.object(main, "FFMPEG_LOG_PATH", str(Path(tmp) / "watchdog.log")):
                with patch.object(main.time, "monotonic", lambda: real_monotonic() * 50):
                    started = real_monotonic()
                    returncode, error = app._execute_ffmpeg([sys.executable, "-u", "-c", code])
        self.assertLess(real_monotonic() - started, 3)
        self.assertNotEqual(returncode, 0)
        self.assertIn("자동 재시작", error)
        self.assertIsNone(app.ffmpeg_process)
        self.assertIsNone(app.stream_progress)


@unittest.skipUnless(Path(main.FFMPEG_PATH).is_file() and Path(main.MEDIAMTX_PATH).is_file(), "bundled binaries required")
class RTSPRepeatTests(unittest.TestCase):
    def test_received_frames_repeat_across_three_cycles_even_with_bad_timestamps(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            tmp = Path(tmp)
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            env = dict(os.environ, MTX_RTSPADDRESS=f"127.0.0.1:{port}")
            server = subprocess.Popen([main.MEDIAMTX_PATH, main.MEDIAMTX_CONFIG_PATH], env=env,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      creationflags=main.CREATE_NO_WINDOW)
            try:
                deadline = time.monotonic() + 10
                while True:
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                            break
                    except OSError:
                        if time.monotonic() > deadline:
                            self.fail("test MediaMTX did not start")
                        time.sleep(0.1)
                for with_gap in (False, True):
                    with self.subTest(timestamp_gap=with_gap):
                        source = tmp / f"source-{with_gap}.mp4"
                        filters = "[0:v][1:v]concat=n=2:v=1:a=0"
                        if with_gap:
                            filters += ",setpts=PTS+if(gte(N\\,10)\\,5/TB\\,0)"
                        subprocess.run([
                            main.FFMPEG_PATH, "-hide_banner", "-loglevel", "error", "-y",
                            "-f", "lavfi", "-i", "color=red:size=160x90:rate=10:duration=1",
                            "-f", "lavfi", "-i", "color=blue:size=160x90:rate=10:duration=1",
                            "-filter_complex", filters, "-c:v", "libx264", "-preset", "ultrafast",
                            "-fps_mode", "passthrough", str(source),
                        ], check=True, timeout=15, creationflags=main.CREATE_NO_WINDOW)
                        if with_gap:
                            baseline = subprocess.run([
                                main.FFMPEG_PATH, "-hide_banner", "-loglevel", "error",
                                "-stream_loop", "-1", "-i", str(source), "-frames:v", "65",
                                "-r", "10", "-fps_mode", "cfr", "-vf", "scale=1:1",
                                "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1",
                            ], check=True, capture_output=True, timeout=10, creationflags=main.CREATE_NO_WINDOW)
                            baseline_colors = [baseline.stdout[i] > baseline.stdout[i + 2]
                                               for i in range(0, len(baseline.stdout), 3)]
                            self.assertLessEqual(sum(a != b for a, b in zip(baseline_colors, baseline_colors[1:])), 1)
                        app = app_stub()
                        duration = app.get_video_duration(str(source))
                        self.assertAlmostEqual(duration, 2.0, places=2)
                        app.video_duration = duration
                        app.streaming_frame_rate = app.video_frame_rate
                        app.streaming_video_path = str(source)
                        ready = threading.Event()
                        app._mark_streaming = ready.set
                        url = f"rtsp://127.0.0.1:{port}/loop-test"
                        command = app._build_ffmpeg_command(url, repair_timestamps=False)
                        command[command.index("-g") + 1] = "10"
                        results = []
                        with patch.object(main, "FFMPEG_LOG_PATH", str(tmp / "publisher.log")):
                            publisher = threading.Thread(target=lambda: results.append(app._execute_ffmpeg(command)))
                            publisher.start()
                            try:
                                self.assertTrue(ready.wait(10), "publisher did not produce a frame")
                                capture = subprocess.run([
                                    main.FFMPEG_PATH, "-hide_banner", "-loglevel", "error",
                                    "-rtsp_transport", "tcp", "-i", url, "-frames:v", "65",
                                    "-fps_mode", "passthrough",
                                    "-vf", "scale=1:1", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1",
                                ], capture_output=True, timeout=18, creationflags=main.CREATE_NO_WINDOW)
                                self.assertEqual(capture.returncode, 0, capture.stderr.decode(errors="replace"))
                                pixels = [capture.stdout[i:i + 3] for i in range(0, len(capture.stdout), 3)]
                                colors = ["R" if p[0] > p[2] else "B" for p in pixels]
                                changes = sum(a != b for a, b in zip(colors, colors[1:]))
                                self.assertEqual(len(colors), 65)
                                self.assertGreaterEqual(changes, 5, f"last frame froze instead of repeating: {''.join(colors)}")
                                self.assertGreater(app.stream_progress[1], duration * 3)
                            finally:
                                app.is_streaming = False
                                publisher.join(timeout=5)
                                self.assertFalse(publisher.is_alive())
                                if app.ffmpeg_process and app.ffmpeg_process.poll() is None:
                                    app.ffmpeg_process.kill()
            finally:
                server.terminate()
                server.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
