import numpy as np
from sklearn.linear_model import LinearRegression

print("📈 กำลังเตรียมระบบพยากรณ์ล่วงหน้า (Forecasting)...")

def predict_future_vitals(history_hr: list, history_spo2: list, future_steps: int = 3):
    """
    วิเคราะห์แนวโน้ม (Trend) จากประวัติเพื่อพยากรณ์ค่าในอนาคต
    """
    # ถ้าข้อมูลน้อยเกินไป ยังไม่ทำนาย
    if len(history_hr) < 5 or len(history_spo2) < 5:
        return {"predicted_hr": None, "predicted_spo2": None}

    try:
        # สร้างแกนเวลา (X) เช่น [0, 1, 2, 3, ...]
        X = np.array(range(len(history_hr))).reshape(-1, 1)
        
        # เทรนโมเดลหาระยะห่างของ Heart Rate
        model_hr = LinearRegression()
        model_hr.fit(X, np.array(history_hr))
        
        # เทรนโมเดลหาระยะห่างของ SpO2
        model_spo2 = LinearRegression()
        model_spo2.fit(X, np.array(history_spo2))
        
        # ทำนายอนาคตไปข้างหน้าตามจำนวน future_steps
        future_X = np.array([[len(history_hr) + future_steps - 1]])
        pred_hr = int(model_hr.predict(future_X)[0])
        pred_spo2 = int(model_spo2.predict(future_X)[0])
        
        # ป้องกันค่าพยากรณ์เวอร์เกินจริง (เช่น SpO2 ทะลุ 100)
        pred_spo2 = min(100, max(0, pred_spo2))
        pred_hr = min(250, max(0, pred_hr))
        
        return {
            "predicted_hr": pred_hr,
            "predicted_spo2": pred_spo2
        }
    except Exception as e:
        print(f"❌ Forecasting Error: {e}")
        return {"predicted_hr": None, "predicted_spo2": None}