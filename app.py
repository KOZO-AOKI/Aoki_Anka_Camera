from flask import Flask, Response, render_template
import cv2
import os
import threading
import time
from datetime import datetime

app = Flask(__name__)

# 録画設定
WIDTH = 640
HEIGHT = 480
FPS = 20
RECORD_SECONDS = 60
MAX_CAMERAS = 4  # 最大4台チェック

# 保存フォルダを app.py と同階層に作成
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAVE_DIR = os.path.join(BASE_DIR, 'save')
os.makedirs(SAVE_DIR, exist_ok=True)

# 24時間以上前の録画ファイルを削除する
def cleanup_old_files(folder, max_age_hours=24):
    now = time.time()
    cutoff = now - (max_age_hours * 3600)
    for filename in os.listdir(folder):
        path = os.path.join(folder, filename)
        if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
            os.remove(path)

# カメラ1台の映像取得・録画処理
class CameraHandler:
    def __init__(self, index):
        self.index = index
        self.cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
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
            filename = os.path.join(SAVE_DIR, f"camera{self.index}_{now.strftime('%Y%m%d_%H%M%S')}.mp4")
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
            print(f"✅ Camera {self.index} 録画完了: {filename}（{frame_count} フレーム）")

    def release(self):
        self.running = False
        self.cap.release()

# 利用可能なカメラだけ検出して起動
cameras = {}
for i in range(MAX_CAMERAS):
    cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
    if cap.isOpened():
        cap.release()
        cameras[i] = CameraHandler(i)
        print(f"✅ Camera {i} を初期化しました")
    else:
        print(f"❌ Camera {i} は利用できません")

# ルート：配信ページ
@app.route('/')
def index():
    return render_template('index.html', camera_indexes=cameras.keys())

# 映像配信ルート（個別カメラ）
@app.route('/video_feed/<int:camera_index>')
def video_feed(camera_index):
    def gen():
        while True:
            frame = cameras[camera_index].get_frame()
            if frame is None:
                continue
            ret, buffer = cv2.imencode('.jpg', frame)
            if not ret:
                continue
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            time.sleep(1.0 / FPS)
    return Response(gen(), mimetype='multipart/x-mixed-replace; boundary=frame')

# 実行開始
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=False)
