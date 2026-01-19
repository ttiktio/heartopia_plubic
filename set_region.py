"""
📐 Set Region Tool
คลิก 2 จุดเพื่อกำหนดพื้นที่ตรวจจับ (spatula_region.json)
  - คลิกแรก: มุมซ้ายบน
  - คลิกสอง: มุมขวาล่าง
"""

import json
import time
from pathlib import Path
from pynput import mouse

BASE_DIR = Path(__file__).parent
REGION_FILE = BASE_DIR / "spatula_region.json"

def set_region():
    print("\n" + "="*50)
    print("📐 Set Region Tool")
    print("="*50)
    print("\nวิธีใช้:")
    print("  1) สลับไปหน้าเกม")
    print("  2) คลิกจุดแรก = มุมซ้ายบน")
    print("  3) คลิกจุดที่สอง = มุมขวาล่าง")
    print("\n⚠️ กด Ctrl+C เพื่อยกเลิก")
    
    input("\n👉 กด Enter เมื่อพร้อม...")
    
    print("\n⏳ สลับไปหน้าเกมใน 3 วินาที...")
    for i in range(3, 0, -1):
        print(f"   {i}...")
        time.sleep(1)
    
    clicks = []
    
    def on_click(x, y, button, pressed):
        if pressed and button == mouse.Button.left:
            clicks.append((x, y))
            if len(clicks) == 1:
                print(f"\n✅ มุมซ้ายบน: ({x}, {y})")
                print("👉 คลิกมุมขวาล่าง...")
            elif len(clicks) == 2:
                print(f"✅ มุมขวาล่าง: ({x}, {y})")
                return False  # หยุด listener
    
    print("\n👆 คลิกมุมซ้ายบนของพื้นที่...")
    
    with mouse.Listener(on_click=on_click) as listener:
        listener.join()
    
    if len(clicks) != 2:
        print("\n❌ ไม่ได้รับพิกัดครบ")
        return False
    
    x1, y1 = clicks[0]
    x2, y2 = clicks[1]
    
    # ตรวจสอบว่าจุดที่ 2 ต้องอยู่ขวาล่างของจุดที่ 1
    if x2 <= x1 or y2 <= y1:
        print("\n❌ พิกัดไม่ถูกต้อง!")
        print("   มุมขวาล่างต้องอยู่ทางขวาและต่ำกว่ามุมซ้ายบน")
        return False
    
    # สร้าง region [x1, y1, x2, y2]
    region = [int(x1), int(y1), int(x2), int(y2)]
    
    # บันทึกลงไฟล์
    data = {"region": region}
    REGION_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    
    # แสดงผลลัพธ์
    width = x2 - x1
    height = y2 - y1
    
    print("\n" + "="*50)
    print("✅ บันทึกสำเร็จ!")
    print("="*50)
    print(f"📁 ไฟล์: {REGION_FILE.name}")
    print(f"📐 Region: [{x1}, {y1}, {x2}, {y2}]")
    print(f"   มุมซ้ายบน: ({x1}, {y1})")
    print(f"   มุมขวาล่าง: ({x2}, {y2})")
    print(f"   ขนาด: {width} x {height} พิกเซล")
    print("="*50)
    
    return True

if __name__ == "__main__":
    try:
        set_region()
    except KeyboardInterrupt:
        print("\n\n🛑 ยกเลิกโดยผู้ใช้")
