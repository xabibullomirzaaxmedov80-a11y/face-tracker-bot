# -*- coding: utf-8 -*-
"""
FaceGuard — OpenCV 5.0 YuNet (detection) + SFace (128D recognition)
Tashqi ML kutubxona kerak emas, hammasi opencv-python 5.0 ichida!
"""
import os, io, sys, cv2, numpy as np, requests, base64, time
from flask import Flask, request, jsonify, render_template, session, send_from_directory, send_file
from flask_cors import CORS
from dotenv import load_dotenv
from gtts import gTTS

# Windows UTF-8 konsolini majburlash
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "super_secret_admin_key_123")
CORS(app)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")
KNOWN_FACES_DIR    = "known_faces"
COSINE_THRESHOLD   = 0.363   # SFace uchun rasmiy chegara (>= = bir odam)

DET_MODEL  = "face_detection_yunet.onnx"
REC_MODEL  = "face_recognition_sface.onnx"

if not os.path.exists(KNOWN_FACES_DIR):
    os.makedirs(KNOWN_FACES_DIR)

# ── OpenCV YuNet + SFace modellari ────────────────────────────────────────────
print("[INIT] OpenCV YuNet va SFace modellari yuklanmoqda...")

detector   = cv2.FaceDetectorYN.create(
    DET_MODEL, "", (320, 240),   # Kichik input = tezroq CPU inference
    score_threshold=0.6,
    nms_threshold=0.3,
    top_k=50
)
recognizer = cv2.FaceRecognizerSF.create(REC_MODEL, "")
print(f"[OK] YuNet + SFace tayyor! (cosine threshold={COSINE_THRESHOLD})")

# ── Ma'lum yuzlar bazasi ───────────────────────────────────────────────────────
known_features   = []   # har bir rasm uchun 128-o'lchamli feature
known_names_list = []   # mos ism
is_loaded        = False

def detect_faces(img):
    """img: BGR numpy array. Qaytaradi: faces array yoki [] """
    h, w = img.shape[:2]
    detector.setInputSize((w, h))
    _, faces = detector.detect(img)
    if faces is None:
        return []
    return faces  # Nx15 array

def extract_feature(img, face_row):
    """Yuzni hizalab, 128D feature vektorini qaytaradi"""
    aligned = recognizer.alignCrop(img, face_row)
    return recognizer.feature(aligned)

def load_known_faces():
    global known_features, known_names_list, is_loaded
    known_features   = []
    known_names_list = []

    total = 0
    for filename in sorted(os.listdir(KNOWN_FACES_DIR)):
        if not filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            continue
        img_path = os.path.join(KNOWN_FACES_DIR, filename)
        img = cv2.imread(img_path)
        if img is None:
            print(f"  [SKIP] O'qib bo'lmadi: {filename}")
            continue

        name = os.path.splitext(filename)[0].split('_')[0]
        faces = detect_faces(img)

        if len(faces) == 0:
            print(f"  [SKIP] {filename} da yuz topilmadi")
            continue

        # Eng yuqori score li yuzni tanlaymiz
        best = max(faces, key=lambda f: f[14])
        feat = extract_feature(img, best)
        known_features.append(feat)
        known_names_list.append(name)
        total += 1
        print(f"  [OK] {filename} -> '{name}' (det_score={best[14]:.2f})")

    is_loaded = total > 0
    print(f"Jami {total} ta rasm, {len(set(known_names_list))} ta shaxs yuklandi.")

def recognize_feature(feat, threshold=COSINE_THRESHOLD):
    """Berilgan feature ni bazadagi barchasi bilan taqqoslab, ism va score qaytaradi"""
    if not known_features:
        return "Unknown", 0.0
    scores = []
    for kf in known_features:
        s = recognizer.match(feat, kf, cv2.FACE_RECOGNIZER_SF_FR_COSINE)
        scores.append(float(s))
    best_i = int(np.argmax(scores))
    best_s = scores[best_i]
    if best_s >= threshold:
        return known_names_list[best_i], round(best_s, 3)
    return "Unknown", round(best_s, 3)

load_known_faces()

# ── Telegram ───────────────────────────────────────────────────────────────────
last_notification_times = {}
NOTIFICATION_COOLDOWN   = 300

def send_telegram_photo(message, frame_bytes):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url   = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    data  = {"chat_id": TELEGRAM_CHAT_ID, "caption": message}
    files = {"photo": ("face.jpg", frame_bytes, "image/jpeg")}
    try:
        requests.post(url, data=data, files=files, timeout=10)
    except Exception as e:
        print("Telegram error:", e)


# ── ROUTES ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze_frame():
    data = request.json
    if not data or 'image' not in data:
        return jsonify({"error": "No image provided"}), 400

    try:
        img_b64 = data['image'].split(',')[1]
        nparr   = np.frombuffer(base64.b64decode(img_b64), np.uint8)
        frame   = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    # Tezlashtirish: agar rasm katta bo'lsa, 480px ga kichraytir
    h_orig, w_orig = frame.shape[:2]
    if w_orig > 480:
        scale  = 480 / w_orig
        frame  = cv2.resize(frame, (480, int(h_orig * scale)))

    recognized_names = []
    norms            = []
    face_boxes       = []

    faces = detect_faces(frame)

    for face in faces:
        x, y, w, h = int(face[0]), int(face[1]), int(face[2]), int(face[3])

        name = "Unknown"
        sim  = 0.0

        if is_loaded:
            try:
                feat        = extract_feature(frame, face)
                name, sim   = recognize_feature(feat)
                print(f"[FACE] name={name}, cosine_sim={sim:.3f}, det={face[14]:.2f}")
            except Exception as e:
                print(f"[ERR] Feature extraction: {e}")

        recognized_names.append(name)
        norms.append(sim)
        face_boxes.append({"x": x, "y": y, "w": int(w), "h": int(h), "name": name})

        if name != "Unknown":
            cur = time.time()
            if cur - last_notification_times.get(name, 0) > NOTIFICATION_COOLDOWN:
                pad  = 20
                crop = frame[max(0,y-pad):y+h+pad, max(0,x-pad):x+w+pad].copy()
                _, buf = cv2.imencode('.jpg', crop)
                send_telegram_photo(
                    f"Tanildi: {name} (o'xshashlik: {sim:.0%})",
                    buf.tobytes()
                )
                last_notification_times[name] = cur

    return jsonify({
        "recognized_faces": recognized_names,
        "norms":            norms,
        "face_boxes":       face_boxes,
        "img_w":            int(frame.shape[1]),
        "img_h":            int(frame.shape[0])
    })


# ── ADMIN PANEL ────────────────────────────────────────────────────────────────

@app.route("/admin")
def admin_panel():
    return render_template("admin.html")

@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    pw = request.json.get("password")
    if pw == "admin123":
        session["admin_logged_in"] = True
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Noto'g'ri parol"}), 401

@app.route("/api/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("admin_logged_in", None)
    return jsonify({"success": True})

@app.route("/api/admin/faces", methods=["GET"])
def admin_get_faces():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    faces = []
    for fn in os.listdir(KNOWN_FACES_DIR):
        if fn.lower().endswith(('.png', '.jpg', '.jpeg')):
            name = os.path.splitext(fn)[0].split('_')[0]
            faces.append({"filename": fn, "name": name, "url": f"/known_faces/{fn}"})
    return jsonify({"faces": faces})

@app.route("/api/admin/faces", methods=["POST"])
def admin_upload_face():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    if 'file' not in request.files:
        return jsonify({"error": "Fayl yuborilmadi"}), 400
    file = request.files['file']
    name = request.form.get('name', '').strip()
    if not name:
        return jsonify({"error": "Ism kiritilmadi"}), 400
    safe_name = "".join(c for c in name if c.isalpha() or c.isdigit()).lower()
    ext       = os.path.splitext(file.filename)[1]
    filename  = f"{safe_name}_{int(time.time())}{ext}"
    file.save(os.path.join(KNOWN_FACES_DIR, filename))
    load_known_faces()
    return jsonify({"success": True, "message": "Rasm saqlandi va baza yangilandi!"})

@app.route("/api/admin/faces/<filename>", methods=["DELETE"])
def admin_delete_face(filename):
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    fp = os.path.join(KNOWN_FACES_DIR, filename)
    if os.path.exists(fp):
        os.remove(fp)
        load_known_faces()
        return jsonify({"success": True})
    return jsonify({"error": "Topilmadi"}), 404

@app.route("/api/admin/train", methods=["POST"])
def admin_train():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    load_known_faces()
    return jsonify({"success": True,
                    "message": f"Baza yangilandi: {len(known_features)} ta yuz."})

@app.route("/known_faces/<path:filename>")
def serve_known_faces(filename):
    return send_from_directory(KNOWN_FACES_DIR, filename)

# ── TTS ────────────────────────────────────────────────────────────────────────

@app.route("/speak", methods=["POST"])
def speak_text():
    text = request.json.get("text", "").strip()
    if not text:
        return jsonify({"error": "Matn yo'q"}), 400
    try:
        tts = gTTS(text=text, lang="ru", slow=False)
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        buf.seek(0)
        return send_file(buf, mimetype="audio/mpeg",
                         as_attachment=False, download_name="speech.mp3")
    except Exception as e:
        print(f"gTTS error: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000, host='0.0.0.0')
