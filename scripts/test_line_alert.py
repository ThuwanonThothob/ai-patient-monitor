#!/usr/bin/env python3
"""CLI utility to test mobile alert integration for Smart Ward (LINE Bot & Telegram).

Supports:
- Family Audience (Default): AI-curated, reassuring, structured Thai alerts with explicit Bed numbers.
- Staff Audience: Modified NEWS2, clinical parameters, and nursing action steps.
- Bed Isolation: Restricts alerts to designated beds so relatives never receive other patients' alarms.

Usage:
  python3 scripts/test_line_alert.py
  python3 scripts/test_line_alert.py --type vital --patient A001 --audience family
  python3 scripts/test_line_alert.py --type posture --patient A001 --audience family
  python3 scripts/test_line_alert.py --patient A001 --audience staff
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv
load_dotenv(BACKEND / ".env", override=False)

import line_notifier


def main():
    parser = argparse.ArgumentParser(description="Test Smart Ward Mobile Alerts (LINE Bot & Telegram).")
    parser.add_argument("--line-token", default=None, help="LINE Channel Access Token (overrides .env)")
    parser.add_argument("--telegram-token", default=None, help="Telegram Bot Token (overrides .env)")
    parser.add_argument("--telegram-chat", default=None, help="Telegram Chat ID (overrides .env)")
    parser.add_argument("--type", choices=["test", "vital", "posture"], default="test", help="Alert type to simulate")
    parser.add_argument("--patient", default="A001", help="Patient bed ID (default: A001)")
    parser.add_argument("--audience", choices=["family", "staff"], default="family", help="Target audience: 'family' (default) or 'staff'")
    args = parser.parse_args()

    if args.line_token:
        os.environ["LINE_CHANNEL_ACCESS_TOKEN"] = args.line_token
    if args.telegram_token:
        os.environ["TELEGRAM_BOT_TOKEN"] = args.telegram_token
    if args.telegram_chat:
        os.environ["TELEGRAM_CHAT_ID"] = args.telegram_chat

    if not line_notifier.is_configured():
        print("\n❌ ยังไม่ได้ระบุ Token การแจ้งเตือน!")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print("📌 ตัวเลือกที่ 1: ใช้ LINE Messaging API (LINE Official Account / Bot ทางการ)")
        print("   (แทนที่ LINE Notify เดิมที่ยุติการให้บริการ · ฟรี 100%)")
        print("   1. เข้าเว็บ: https://developers.line.biz/ แล้ว Login ด้วย LINE")
        print("   2. สร้าง Provider -> สร้าง Messaging API Channel (ได้ LINE Bot ทันที)")
        print("   3. ไปที่แท็บ 'Messaging API' เลื่อนล่างสุด -> กด Issue 'Channel access token (long-lived)'")
        print("   4. คัดลอก Token มาใส่ใน backend/.env:")
        print("      LINE_CHANNEL_ACCESS_TOKEN=ใส่รหัสโทเคนตรงนี้")
        print("   5. สแกน QR Code เพื่อเพิ่มเพื่อนกับบอทของคุณใน LINE")
        print("   *ระบบจะ Broadcast แจ้งเตือนเข้าโทรศัพท์ทุกคนที่เพิ่มเพื่อนบอททันที!*")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print("📌 ตัวเลือกที่ 2: ใช้ Telegram Bot (เร็วที่สุดใน 30 วินาที · ฟรี 100% ไม่มีลิมิต)")
        print("   1. เปิดแอป Telegram ค้นหาบอทชื่อ: @BotFather")
        print("   2. พิมพ์ /newbot -> ตั้งชื่อบอท -> จะได้รับ Bot Token ทันที")
        print("   3. ค้นหาบอทชื่อ: @userinfobot เพื่อดู Chat ID ของคุณ")
        print("   4. นำมาใส่ใน backend/.env:")
        print("      TELEGRAM_BOT_TOKEN=ใส่บอทโทเคน")
        print("      TELEGRAM_CHAT_ID=ใส่เลขChatID")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
        sys.exit(1)

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("🏥 SMART WARD · ระบบแจ้งเตือนฉุกเฉินผ่าน LINE บนมือถือ")
    print(f"🛏️ เตียงผู้ป่วยเป้าหมาย: เตียง {args.patient}")
    print(f"👥 กลุ่มผู้รับการแจ้งเตือน: {'ญาติผู้ป่วย (Family / Caregiver)' if args.audience == 'family' else 'เจ้าหน้าที่ทางการแพทย์ (Staff)'}")
    print(f"📋 ประเภทเหตุการณ์: {args.type}")
    print("🔒 การจัดระเบียบแยกเตียง (Bed Isolation): เปิดใช้งาน (แยกเตียงชัดเจน ไม่ปะปน)")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("กำลังส่งการแจ้งเตือนไปยังโทรศัพท์มือถือ...")

    success, message = line_notifier.send_test_message(
        patient_id=args.patient,
        audience=args.audience,
        alert_type=args.type,
    )

    if success:
        print(f"\n✅ ส่งการแจ้งเตือนสำเร็จเรียบร้อย! ({message})")
        print("👉 กรุณาตรวจดูข้อความแจ้งเตือนที่เด้งบนหน้าจอโทรศัพท์ของคุณใน LINE ได้เลยครับ")
    else:
        print(f"\n❌ ส่งไม่สำเร็จ: {message}")
        sys.exit(1)


if __name__ == "__main__":
    main()
