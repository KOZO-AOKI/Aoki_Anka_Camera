from flask import Flask, Response, render_template
import cv2
import os
import threading
import time
from datetime import datetime

app = Flask(__name__)

WIDTH = 640
HEIGHT = 480
FPS = 20
RECORD_SECONDS = 60
MAX_CAMERAS = 6

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAVE_DIR = os.path.join(BASE_DIR, 'save')
os.makedirs(SAVE_DIR, exist_ok=True)

def cleanup_old_files(folder, max_age_hours=24):
    now = time.time()
    cutoff = now - (max_age_hours * 3600)
    for filename in os.listdir(folder):
        path = os.path.join(folder, filename)
        if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
            os.remove(path)

class CameraHandler:
    def __init__(self, physical_index, display_number):
        self.physical_index = physical_index
        self.display_number = display_number  # Camera1〜Camera6
        self.cap = cv2.VideoCapture(physical_index, cv2.CAP_DSHOW)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
        self.cap.set(cv2.CAP_PROP_FPS, FPS)
        self.frame = None
        self.lock = threading.Lock()
        self.running = True

        threading.Thread(target=self.update_frame, daemon=True).start()
        threading.Thread(target=self.record_loop, daemon=True).start()

    def update_frame(self):
        while self.running:
            ret, frame = self.cap.read()
            if ret:
                with self.lock:
                    self.frame = frame.copy()
            time.sleep(1.0 / FPS)

    def get_frame(self):
        with self.lock:
            return self.frame.copy() if self.frame is not None else None

    def record_loop(self):
        while self.running:
            cleanup_old_files(SAVE_DIR, max_age_hours=24)
            now = datetime.now()
            filename = os.path.join(SAVE_DIR, f"Camera{self.display_number}_{now.strftime('%Y%m%d_%H%M%S')}.mp4")
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(filename, fourcc, FPS, (WIDTH, HEIGHT))

            if not out.isOpened():
                print(f"⚠️ VideoWriter open failed: {filename}")
                time.sleep(RECORD_SECONDS)
                continue

            start_time = time.time()
            frame_count = 0

            while time.time() - start_time < RECORD_SECONDS:
                frame = self.get_frame()
                if frame is not None:
                    out.write(frame)
                    frame_count += 1
                time.sleep(1.0 / FPS)

            out.release()
            print(f"✅ Camera{self.display_number} 録画完了: {filename}（{frame_count} フレーム）")

    def release(self):
        self.running = False
        self.cap.release()

# カメラ検出（接続順に Camera1〜Camera6 を割り当て）
cameras = {}
display_num = 1

for i in range(10):  # 物理インデックス0〜9を試行（6台まで）
    if display_num > MAX_CAMERAS:
        break
    cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
    if cap.isOpened():
        cap.release()
        handler = CameraHandler(i, display_num)
        cameras[display_num] = handler
        print(f"✅ Camera{display_num} を物理インデックス {i} に割り当て")
        display_num += 1
    else:
        print(f"❌ Camera index {i} は未接続")

@app.route('/')
def index():
    return render_template('index.html', camera_indexes=sorted(cameras.keys()))

@app.route('/video_feed/<int:display_number>')
def video_feed(display_number):
    def gen():
        handler = cameras.get(display_number)
        if handler is None:
            return
        while True:
            frame = handler.get_frame()
            if frame is None:
                continue
            ret, buffer = cv2.imencode('.jpg', frame)
            if not ret:
                continue
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            time.sleep(1.0 / FPS)
    return Response(gen(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=False)
