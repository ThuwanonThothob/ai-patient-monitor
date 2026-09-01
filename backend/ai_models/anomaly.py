import numpy as np
from sklearn.ensemble import IsolationForest

print("🧠 กำลังเทรน AI: Anomaly Detection (Isolation Forest)...")

# 1. ตั้งค่าโมเดล (contamination = 0.05 หมายถึง ยอมให้มีข้อมูลผิดปกติได้ 5%)
model = IsolationForest(contamination=0.05, random_state=42)

# 2. สร้างข้อมูลจำลองของ "คนปกติ" เพื่อสอน AI เบื้องต้น 
# รูปแบบ: [Heart Rate, SpO2]
normal_data = [
    [70, 98], [75, 99], [80, 97], [85, 98], [65, 96],
    [72, 98], [78, 99], [82, 97], [68, 98], [74, 99]
]
# เพิ่มข้อมูลปกติเข้าไป 100 แถวเพื่อให้ AI เรียนรู้แพทเทิร์น
X_train = np.array(normal_data * 10) 
model.fit(X_train)

def detect_anomaly(hr: int, spo2: int) -> bool:
    """
    รับค่าปัจจุบันมาตรวจสอบว่า "แปลก" ไปจากปกติหรือไม่
    Return True ถ้าผิดปกติ, False ถ้าปกติ
    """
    try:
        # โมเดลจะคืนค่า: 1 = ปกติ, -1 = ผิดปกติ (Anomaly)
        prediction = model.predict([[hr, spo2]])
        return bool(prediction[0] == -1)
    except Exception as e:
        print(f"❌ Anomaly Detection Error: {e}")
        return False