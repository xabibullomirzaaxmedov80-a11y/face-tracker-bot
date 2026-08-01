import cv2

print("Kamerani tekshirish boshlandi...")
cap = cv2.VideoCapture(0)
if not cap.isOpened():
    print("XATO: Kamera 0 ochilmadi.")
    cap = cv2.VideoCapture(1)
    if not cap.isOpened():
        print("XATO: Kamera 1 ochilmadi.")
    else:
        print("Muvaffaqiyat: Kamera 1 ochildi.")
        cap.release()
else:
    print("Muvaffaqiyat: Kamera 0 ochildi.")
    cap.release()
