// ══════════════════════════════════════════════
//  FaceGuard — Scanner + Ovozli Tanish
// ══════════════════════════════════════════════

const video        = document.getElementById('videoElement');
const canvas       = document.getElementById('overlayCanvas');
const ctx          = canvas.getContext('2d');
const startBtn     = document.getElementById('startButton');
const stopBtn      = document.getElementById('stopButton');
const statusText   = document.getElementById('statusText');
const statusDot    = document.getElementById('statusDot');
const cameraResult = document.getElementById('cameraResult');
const cameraName   = document.getElementById('cameraPersonName');
const vectorNorm   = document.getElementById('vectorNormText');

let stream        = null;
let intervalId    = null;
let analyzing     = false;
let scanLineY     = 0;
let scanDir       = 1;
let animFrameId   = null;
let lastFaceBoxes = [];
let lastSpokenNames = {};  // Ovozni takrorlamaslik uchun

// ── Ovozli gapiruv (Google TTS — haqiqiy o'zbekcha) ────
const audioCache = {};   // Bir xil ismni qayta yuklamaslik uchun
let currentAudio = null;

async function speak(text) {
    try {
        // Avval cache tekshiramiz
        if (!audioCache[text]) {
            const res = await fetch('/speak', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text })
            });
            if (!res.ok) return;
            const blob = await res.blob();
            audioCache[text] = URL.createObjectURL(blob);
        }

        // Oldingi audio to'xtatiladi
        if (currentAudio) {
            currentAudio.pause();
            currentAudio.currentTime = 0;
        }

        currentAudio = new Audio(audioCache[text]);
        currentAudio.volume = 1.0;
        currentAudio.play();
    } catch (e) {
        console.warn('Ovoz xatosi:', e);
    }
}

function shouldSpeak(name) {
    const now = Date.now();
    const last = lastSpokenNames[name] || 0;
    if (now - last > 8000) {  // 8 soniya o'tsa qayta gapiradi
        lastSpokenNames[name] = now;
        return true;
    }
    return false;
}

// ── Kamera ─────────────────────────────────────
async function startCamera() {
    try {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            alert("Brauzeringiz kamerani qo'llab-quvvatlamaydi.");
            return;
        }
        stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } });
        video.srcObject = stream;
        video.addEventListener('loadedmetadata', () => {
            canvas.width  = video.videoWidth;
            canvas.height = video.videoHeight;
            scanLineY = 0;
            startScanAnimation();
        });

        startBtn.disabled = true;
        stopBtn.disabled  = false;
        statusText.textContent = 'Kamera faol — Tahlil qilinmoqda...';
        statusDot.classList.add('active');

        // Brauzer autoplay siyosatini chetlab o'tish (ovozni bloklamaslik uchun)
        const dummyAudio = new Audio();
        dummyAudio.play().catch(e => {});

        intervalId = setInterval(analyzeFrame, 1800);
    } catch (err) {
        statusText.textContent = "Kameraga ulanib bo'lmadi!";
        alert('Kamera xatosi: ' + err.name);
    }
}

function stopCamera() {
    if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
    if (intervalId) { clearInterval(intervalId); intervalId = null; }
    if (animFrameId) { cancelAnimationFrame(animFrameId); animFrameId = null; }
    video.srcObject = null;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    lastFaceBoxes = [];
    startBtn.disabled = false;
    stopBtn.disabled  = true;
    statusText.textContent = "Kamera to'xtatildi";
    statusDot.classList.remove('active');
    // Ovozni to'xtatish
    if (currentAudio) { currentAudio.pause(); currentAudio = null; }
}

// ── Skaner animatsiyasi ────────────────────────
function startScanAnimation() {
    function draw() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        // 1. Yuz atrofidagi ramkalar chizish
        drawFaceBoxes();

        // 2. Umumiy skaner chizig'i
        drawScanLine();

        scanLineY += 3 * scanDir;
        if (scanLineY >= canvas.height || scanLineY <= 0) scanDir *= -1;

        animFrameId = requestAnimationFrame(draw);
    }
    draw();
}

function drawScanLine() {
    // Gradient skaner chizig'i
    const grad = ctx.createLinearGradient(0, scanLineY - 10, 0, scanLineY + 10);
    grad.addColorStop(0, 'rgba(124, 58, 237, 0)');
    grad.addColorStop(0.5, 'rgba(124, 58, 237, 0.7)');
    grad.addColorStop(1, 'rgba(124, 58, 237, 0)');
    ctx.fillStyle = grad;
    ctx.fillRect(0, scanLineY - 10, canvas.width, 20);

    // Asosiy chiziq
    ctx.strokeStyle = 'rgba(124, 58, 237, 0.9)';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(0, scanLineY);
    ctx.lineTo(canvas.width, scanLineY);
    ctx.stroke();
}

function drawFaceBoxes() {
    if (!lastFaceBoxes || lastFaceBoxes.length === 0) return;

    const scaleX = canvas.width  / (lastFaceBoxes._imgW || canvas.width);
    const scaleY = canvas.height / (lastFaceBoxes._imgH || canvas.height);

    lastFaceBoxes.forEach(face => {
        const wScaled = face.w * scaleX;
        const hScaled = face.h * scaleY;
        const xScaled = face.x * scaleX;
        const yScaled = face.y * scaleY;
        // Mirror X coordinate
        const x = canvas.width - (xScaled + wScaled);
        const y = yScaled;
        const w = wScaled;
        const h = hScaled;
        const isKnown = face.name !== 'Unknown';

        const color  = isKnown ? '#10b981' : '#ef4444';
        const color2 = isKnown ? 'rgba(16,185,129,0.15)' : 'rgba(239,68,68,0.12)';

        // Yuz ichini to'ldirish (shaffof)
        ctx.fillStyle = color2;
        ctx.fillRect(x, y, w, h);

        // Burchak chiziqlari (scanner uslubida)
        const cLen = Math.min(w, h) * 0.22; // Burchak uzunligi
        ctx.strokeStyle = color;
        ctx.lineWidth = 3;
        ctx.lineCap = 'round';

        // Yuqori-chap
        ctx.beginPath(); ctx.moveTo(x, y + cLen); ctx.lineTo(x, y); ctx.lineTo(x + cLen, y); ctx.stroke();
        // Yuqori-o'ng
        ctx.beginPath(); ctx.moveTo(x + w - cLen, y); ctx.lineTo(x + w, y); ctx.lineTo(x + w, y + cLen); ctx.stroke();
        // Quyi-chap
        ctx.beginPath(); ctx.moveTo(x, y + h - cLen); ctx.lineTo(x, y + h); ctx.lineTo(x + cLen, y + h); ctx.stroke();
        // Quyi-o'ng
        ctx.beginPath(); ctx.moveTo(x + w - cLen, y + h); ctx.lineTo(x + w, y + h); ctx.lineTo(x + w, y + h - cLen); ctx.stroke();

        // Ism yozuvi
        const label = isKnown ? 'SPASIBA' : 'NEZNAKOMETS';
        const boxH  = 28;
        const boxW  = ctx.measureText(label).width + 24;

        // Label background
        ctx.fillStyle = isKnown ? 'rgba(16,185,129,0.85)' : 'rgba(239,68,68,0.85)';
        roundRect(ctx, x, y - boxH - 4, boxW, boxH, 6);
        ctx.fill();

        // Label text
        ctx.fillStyle = 'white';
        ctx.font = 'bold 13px Outfit, sans-serif';
        ctx.fillText(label, x + 10, y - 12);

        // Pulsatsiya effekti — burchaqlarda yashil/qizil nuqta
        const pulse = 0.5 + 0.5 * Math.sin(Date.now() / 250);
        ctx.fillStyle = isKnown
            ? `rgba(16,185,129,${pulse})`
            : `rgba(239,68,68,${pulse})`;
        ctx.beginPath();
        ctx.arc(x + w - 8, y + 8, 5, 0, Math.PI * 2);
        ctx.fill();
    });
}

// Yumaloq to'rtburchak
function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
}

// ── Tahlil ─────────────────────────────────────
async function analyzeFrame() {
    if (analyzing || !video.videoWidth) return;
    analyzing = true;

    const tmpCanvas = document.createElement('canvas');
    // Tezlashtirish: maksimum 480px kenglikda yuboramiz
    const MAX_W = 480;
    const scale = Math.min(1, MAX_W / video.videoWidth);
    tmpCanvas.width  = Math.round(video.videoWidth  * scale);
    tmpCanvas.height = Math.round(video.videoHeight * scale);
    tmpCanvas.getContext('2d').drawImage(video, 0, 0, tmpCanvas.width, tmpCanvas.height);
    const dataUrl = tmpCanvas.toDataURL('image/jpeg', 0.65);

    try {
        const res  = await fetch('/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image: dataUrl })
        });
        if (!res.ok) return;
        const data = await res.json();

        // Yuz koordinatalarini saqlash
        const boxes = data.face_boxes || [];
        boxes._imgW = data.img_w || video.videoWidth;
        boxes._imgH = data.img_h || video.videoHeight;
        lastFaceBoxes = boxes;

        // UI yangilash
        const knownNames = (data.recognized_faces || []).filter(n => n !== 'Unknown');
        const hasUnknown = (data.recognized_faces || []).includes('Unknown');

        if (knownNames.length > 0) {
            cameraName.textContent = knownNames.join('  |  ');
            cameraName.style.color = '#10b981';
            const norms = data.norms || [];
            vectorNorm.textContent = `Masofa: ${norms[0] || '--'}`;
            cameraResult.classList.remove('hidden');

            // ── OVOZLI GAPIRUV ──
            knownNames.forEach(name => {
                if (shouldSpeak(name)) {
                    speak('Spasiba');
                }
            });

        } else if (hasUnknown) {
            cameraName.textContent = '⚠ Begona shaxs';
            cameraName.style.color = '#ef4444';
            const norms = data.norms || [];
            vectorNorm.textContent = `Masofa: ${norms[0] || '--'}`;
            cameraResult.classList.remove('hidden');

            if (shouldSpeak('unknown')) {
                speak('Neznakomets');
            }

        } else if (boxes.length === 0) {
            cameraName.textContent = 'Yuz qidirilmoqda...';
            cameraName.style.color = '#94a3b8';
            vectorNorm.textContent = '';
        }

    } catch (e) {
        console.error('Analyze xatosi:', e);
    } finally {
        analyzing = false;
    }
}
