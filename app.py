# -*- coding: utf-8 -*-
import os, io, sys, cv2, numpy as np, base64, time
from flask import Flask, request, jsonify, render_template, session, redirect, url_for, send_file
from flask_cors import CORS
from dotenv import load_dotenv
from gtts import gTTS
from werkzeug.security import generate_password_hash, check_password_hash

import git_db

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "super_secret_admin_key_123")
CORS(app)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")
COSINE_THRESHOLD   = 0.363

DET_MODEL  = "face_detection_yunet.onnx"
REC_MODEL  = "face_recognition_sface.onnx"

print("[INIT] YuNet va SFace yuklanmoqda...")
detector = cv2.FaceDetectorYN.create(
    DET_MODEL, "", (320, 240),
    score_threshold=0.6, nms_threshold=0.3, top_k=50
)
recognizer = cv2.FaceRecognizerSF.create(REC_MODEL, "")

# ── Caches ──
user_features_cache = {}
user_names_cache = {}

def detect_faces(img):
    h, w = img.shape[:2]
    detector.setInputSize((w, h))
    _, faces = detector.detect(img)
    return faces if faces is not None else []

def extract_feature(img, face_row):
    aligned = recognizer.alignCrop(img, face_row)
    return recognizer.feature(aligned)

def load_user_faces(username):
    faces_data = git_db.get_faces(username)
    features = []
    names = []
    for f in faces_data:
        try:
            feat_arr = np.array(f["embedding"], dtype=np.float32)
            features.append(feat_arr)
            names.append(f["name"])
        except Exception as e:
            print("Error loading face for", username, e)
    
    user_features_cache[username] = features
    user_names_cache[username] = names
    print(f"Loaded {len(names)} faces for {username}")

def recognize_feature(feat, username, threshold=COSINE_THRESHOLD):
    features = user_features_cache.get(username, [])
    names = user_names_cache.get(username, [])
    if not features:
        return "Unknown", 0.0
    
    scores = []
    for kf in features:
        s = recognizer.match(feat, kf, cv2.FACE_RECOGNIZER_SF_FR_COSINE)
        scores.append(float(s))
    
    best_i = int(np.argmax(scores))
    best_s = scores[best_i]
    if best_s >= threshold:
        return names[best_i], round(best_s, 3)
    return "Unknown", round(best_s, 3)

# ── Telegram ──
last_notification_times = {}
def send_telegram_photo(message, frame_bytes):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID: return
    import requests
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    data = {"chat_id": TELEGRAM_CHAT_ID, "caption": message}
    files = {"photo": ("face.jpg", frame_bytes, "image/jpeg")}
    try: requests.post(url, data=data, files=files, timeout=10)
    except: pass


# ── AUTH ROUTES ──
@app.route("/login", methods=["GET"])
def login_page():
    return render_template("login.html")

@app.route("/api/auth/register", methods=["POST"])
def api_register():
    data = request.json
    username = data.get("username", "").strip()
    password = data.get("password", "")
    
    if len(username) < 3 or len(password) < 4:
        return jsonify({"success": False, "error": "Login va parol qisqa!"}), 400
        
    users = git_db.get_users()
    if username in users:
        return jsonify({"success": False, "error": "Bu login band!"}), 400
        
    users[username] = {
        "password_hash": generate_password_hash(password)
    }
    git_db.save_users(users)
    
    session["username"] = username
    load_user_faces(username)
    return jsonify({"success": True})

@app.route("/api/auth/login", methods=["POST"])
def api_login():
    data = request.json
    username = data.get("username", "").strip()
    password = data.get("password", "")
    
    users = git_db.get_users()
    user = users.get(username)
    if user and check_password_hash(user["password_hash"], password):
        session["username"] = username
        load_user_faces(username)
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Login yoki parol xato"}), 401

@app.route("/api/auth/logout", methods=["POST"])
def api_logout():
    session.pop("username", None)
    return jsonify({"success": True})


# ── CAMERA ROUTES ──
@app.route("/")
def index():
    if "username" not in session:
        return redirect(url_for("login_page"))
    return render_template("index.html")

@app.route("/analyze", methods=["POST"])
def analyze_frame():
    username = session.get("username")
    if not username:
        return jsonify({"error": "Unauthorized"}), 401
        
    data = request.json
    if not data or 'image' not in data:
        return jsonify({"error": "No image"}), 400

    try:
        img_b64 = data['image'].split(',')[1]
        nparr = np.frombuffer(base64.b64decode(img_b64), np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    h_orig, w_orig = frame.shape[:2]
    if w_orig > 480:
        scale = 480 / w_orig
        frame = cv2.resize(frame, (480, int(h_orig * scale)))

    recognized_names = []
    norms = []
    face_boxes = []

    faces = detect_faces(frame)
    if username not in user_features_cache:
        load_user_faces(username)

    for face in faces:
        x, y, w, h = int(face[0]), int(face[1]), int(face[2]), int(face[3])
        name = "Unknown"
        sim = 0.0

        try:
            feat = extract_feature(frame, face)
            name, sim = recognize_feature(feat, username)
        except Exception as e:
            print("Feature extraction error:", e)

        recognized_names.append(name)
        norms.append(sim)
        face_boxes.append({"x": x, "y": y, "w": w, "h": h, "name": name})

        # Telegramga xabar yuborish (Tanish va Noma'lum yuzlar uchun)
        display_name = name if name != "Unknown" else "Begona shaxs!"
        cur = time.time()
        
        # Har 30 soniyada bir marta rasm yuborish (bir xil odam uchun)
        if cur - last_notification_times.get(display_name, 0) > 30:
            pad = 20
            crop = frame[max(0,y-pad):y+h+pad, max(0,x-pad):x+w+pad].copy()
            if crop.size > 0:
                _, buf = cv2.imencode('.jpg', crop)
                caption = f"Tanildi: {name} (o'xshashlik: {sim:.0%})" if name != "Unknown" else "⚠️ DIQQAT! BEGONA SHAXS ANIQLANDI!"
                send_telegram_photo(caption, buf.tobytes())
                last_notification_times[display_name] = cur

    return jsonify({
        "recognized_faces": recognized_names,
        "norms": norms,
        "face_boxes": face_boxes,
        "img_w": int(frame.shape[1]),
        "img_h": int(frame.shape[0])
    })


# ── ADMIN PANEL ──
@app.route("/admin")
def admin_panel():
    if "username" not in session:
        return redirect(url_for("login_page"))
    return render_template("admin.html")

@app.route("/api/admin/faces", methods=["GET"])
def admin_get_faces():
    username = session.get("username")
    if not username: return jsonify({"error": "Unauthorized"}), 401
    
    faces = git_db.get_faces(username)
    # Rasm payloadini kichraytirish uchun faqat metadata qaytaramiz (yoki base64 bilan ham mumkin)
    # HTMLda img src = b64 qilib ko'rsatamiz
    return jsonify({"faces": faces})

@app.route("/api/admin/faces", methods=["POST"])
def admin_upload_face():
    username = session.get("username")
    if not username: return jsonify({"error": "Unauthorized"}), 401
    
    file = request.files.get('file')
    name = request.form.get('name', '').strip()
    if not name or not file:
        return jsonify({"error": "Ma'lumotlar to'liq emas"}), 400
        
    nparr = np.frombuffer(file.read(), np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    faces = detect_faces(img)
    if len(faces) == 0:
        return jsonify({"error": "Rasmda yuz topilmadi!"}), 400
        
    best = max(faces, key=lambda f: f[14])
    feat = extract_feature(img, best)
    
    # Rasmni kichraytirib base64 qilish (UI uchun)
    h, w = img.shape[:2]
    scale = min(1.0, 150 / max(w, h))
    thumb = cv2.resize(img, (int(w*scale), int(h*scale)))
    _, buf = cv2.imencode('.jpg', thumb, [cv2.IMWRITE_JPEG_QUALITY, 80])
    b64_img = "data:image/jpeg;base64," + base64.b64encode(buf).decode('utf-8')
    
    face_id = str(int(time.time()))
    new_face = {
        "id": face_id,
        "name": name,
        "image_b64": b64_img,
        "embedding": feat.tolist()
    }
    
    faces_list = git_db.get_faces(username)
    faces_list.append(new_face)
    if not git_db.save_faces(username, faces_list):
        return jsonify({"error": "GitHub tarmog'iga ulanishda xatolik! Qayta urinib ko'ring."}), 500
    
    load_user_faces(username)
    return jsonify({"success": True, "message": "Yuz muvaffaqiyatli saqlandi!"})

@app.route("/api/admin/faces/<face_id>", methods=["DELETE"])
def admin_delete_face(face_id):
    username = session.get("username")
    if not username: return jsonify({"error": "Unauthorized"}), 401
    
    faces_list = git_db.get_faces(username)
    faces_list = [f for f in faces_list if f["id"] != face_id]
    if not git_db.save_faces(username, faces_list):
        return jsonify({"error": "O'chirishda tarmoq xatosi."}), 500
    
    load_user_faces(username)
    return jsonify({"success": True})


# ── TTS ──
@app.route("/speak", methods=["POST"])
def speak_text():
    text = request.json.get("text", "").strip()
    if not text: return jsonify({"error": "Matn yo'q"}), 400
    try:
        tts = gTTS(text=text, lang="ru", slow=False)
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        buf.seek(0)
        return send_file(buf, mimetype="audio/mpeg")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000, host='0.0.0.0')
