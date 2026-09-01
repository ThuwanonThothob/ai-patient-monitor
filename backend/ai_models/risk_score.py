import numpy as np
from sklearn.ensemble import RandomForestClassifier

print("🧠 กำลังเทรน AI: Risk Scoring (Random Forest)...")

# 1. ข้อมูลจำลองสำหรับสอน AI: [Heart Rate, SpO2, Age]
X_train = np.array([
    [70, 98, 30], [75, 99, 45], [80, 97, 50], [60, 99, 25],  # กลุ่มปกติ
    [120, 92, 60], [130, 88, 70], [45, 90, 65],              # กลุ่มความเสี่ยงสูง
    [100, 95, 80], [110, 94, 75], [50, 94, 85]               # กลุ่มเฝ้าระวัง
])

# 2. ป้ายกำกับ (Labels): 0 = ปกติ, 1 = เสี่ยง
y_train = np.array([0, 0, 0, 0, 1, 1, 1, 1, 1, 1])

# 3. สร้างและเทรนโมเดล
model = RandomForestClassifier(random_state=42)
model.fit(X_train, y_train)

def calculate_risk_score(hr: int, spo2: int, age: int = 50) -> int:
    """
    รับค่าปัจจุบันมาคำนวณโอกาสที่จะเกิดภาวะวิกฤต (Risk Score 0-100%)
    """
    try:
        # predict_proba คืนค่าเป็นความน่าจะเป็นของ [class 0, class 1]
        probability = model.predict_proba([[hr, spo2, age]])
        risk_percent = int(probability[0][1] * 100)
        return risk_percent
    except Exception as e:
        print(f"❌ Risk Score Error: {e}")
        return 0