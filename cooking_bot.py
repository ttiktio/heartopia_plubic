"""
🍳 Cooking Bot - Heartopia
Loop: เลือกเมนู → Quicktime Event (กดรัวๆ) → อาหารเสร็จ → วนลูป

Templates:
- select_menu.png   = หน้าจอเลือกเมนู (รอผู้ใช้กดเอง)
- spatula_template.png = ไอคอนตะหลิว (กดรัวๆ)
- cookingdone.png   = อาหารเสร็จ (คลิก 1 ครั้ง)

กด ESC หรือ SPACE เพื่อหยุด
"""

import time
import sys
import json
from pathlib import Path
from enum import Enum

import pyautogui
from pynput import keyboard
import cv2
import numpy as np

# =========================
# SETTINGS
# =========================
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.01

BASE_DIR = Path(__file__).parent

# Template paths
TEMPLATE_SPATULA = BASE_DIR / "spatula_template.png"
TEMPLATE_MENU = BASE_DIR / "select_menu.png"
TEMPLATE_DONE = BASE_DIR / "cookingdone.png"
TEMPLATE_CANCOOK = BASE_DIR / "cancook.png"
TEMPLATE_CANNOTCOOK = BASE_DIR / "cannotcook.png"
REGION_FILE = BASE_DIR / "spatula_region.json"

# --- Matching thresholds ---
MATCH_CONFIDENCE = 0.70        # raw grayscale threshold
EDGE_CONFIDENCE  = 0.35        # edge threshold

# --- Timing ---
SPATULA_CLICK_DELAY = 0.04     # delay ระหว่างการคลิกตะหลิว
SEARCH_DELAY = 0.08            # delay ระหว่างการค้นหา
DONE_CLICK_WAIT = 2.5          # รอหลังคลิก cookingdone

# --- Click behavior ---
DOUBLE_CLICK_SPATULA = True    # double click สำหรับตะหลิว
MAX_CLICKS_PER_FOUND = 8       # คลิกสูงสุดต่อการเจอ

# --- Special Regions ---
# พื้นที่สำหรับปุ่ม "เริ่มทำอาหาร" โดยเฉพาะ (x, y, w, h)
BTN_START_X1, BTN_START_Y1 = 1236, 919
BTN_START_X2, BTN_START_Y2 = 1573, 1041
REGION_START_BTN = (BTN_START_X1, BTN_START_Y1, BTN_START_X2 - BTN_START_X1, BTN_START_Y2 - BTN_START_Y1)

# ตำแหน่งกลางปุ่ม (สำหรับเช็คสี)
BTN_CENTER_X = (BTN_START_X1 + BTN_START_X2) // 2  # 1404
BTN_CENTER_Y = (BTN_START_Y1 + BTN_START_Y2) // 2  # 980

# --- สีของปุ่ม ---
BTN_COLOR_CANCOOK = "#3ECDC3"     # สีฟ้า (ทำอาหารได้)
BTN_COLOR_CANNOTCOOK = "#BDC3C0" # สีเทา (ทำอาหารไม่ได้)
BTN_COLOR_TOLERANCE = 30          # ความคลาดเคลื่อนของสี

# =========================
# GAME STATE
# =========================
class GameState(Enum):
    WAITING_MENU = "waiting_menu"       # รอเลือกเมนู (select_menu.png)
    CAN_COOK = "can_cook"               # ทำอาหารได้ (cancook.png)
    CANNOT_COOK = "cannot_cook"         # ทำอาหารไม่ได้ (cannotcook.png)
    QUICKTIME_EVENT = "quicktime"       # กดรัวๆ (spatula_template.png)
    COOKING_DONE = "cooking_done"       # อาหารเสร็จ (cookingdone.png)

# =========================
# EMERGENCY STOP
# =========================
STOP_FLAG = False

def on_key_press(key):
    global STOP_FLAG
    try:
        if key == keyboard.Key.esc or key == keyboard.Key.space:
            STOP_FLAG = True
            print("\n🛑 หยุดฉุกเฉิน! (กด ESC หรือ SPACE)")
            return False
    except:
        pass

def start_keyboard_listener():
    listener = keyboard.Listener(on_press=on_key_press)
    listener.start()
    return listener

def check_stop():
    return STOP_FLAG

# =========================
# REGION LOAD
# =========================
def load_region():
    """โหลด region จากไฟล์ JSON และแปลงเป็น (x, y, w, h)"""
    if REGION_FILE.exists():
        try:
            data = json.loads(REGION_FILE.read_text(encoding="utf-8"))
            r = data.get("region")
            if isinstance(r, list) and len(r) == 4:
                # region format: [x1, y1, x2, y2] -> (x, y, w, h)
                x1, y1, x2, y2 = [int(v) for v in r]
                return (x1, y1, x2 - x1, y2 - y1)
        except Exception as e:
            print(f"⚠️ ไม่สามารถโหลด region: {e}")
    return None

# =========================
# IMAGE PROCESSING
# =========================
def to_gray(pil_img):
    arr = np.array(pil_img)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

def edges(gray):
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    return cv2.Canny(blur, 50, 150)

def load_template(path):
    """โหลด template และคืนค่า (gray, edge) หรือ None"""
    if not path.exists():
        return None
    gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return None
    edge = edges(gray)
    return (gray, edge)

def screenshot_gray(region=None):
    img = pyautogui.screenshot(region=region) if region else pyautogui.screenshot()
    return to_gray(img)

def match_template(screen_gray, template_gray, template_edge, raw_thr=MATCH_CONFIDENCE, edge_thr=EDGE_CONFIDENCE):
    """
    คืนค่า: (cx, cy, score, mode) หรือ None
    mode = 'raw' หรือ 'edge'
    """
    h, w = template_gray.shape[:2]
    best = None

    # --- RAW matching ---
    res = cv2.matchTemplate(screen_gray, template_gray, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    if max_val >= raw_thr:
        best = ("raw", max_val, max_loc)

    # --- EDGE matching ---
    scr_edge = edges(screen_gray)
    res2 = cv2.matchTemplate(scr_edge, template_edge, cv2.TM_CCOEFF_NORMED)
    _, max_val2, _, max_loc2 = cv2.minMaxLoc(res2)
    if max_val2 >= edge_thr:
        if best is None or max_val2 > best[1]:
            best = ("edge", max_val2, max_loc2)

    if best is None:
        return None

    mode, score, loc = best
    cx = int(loc[0] + w // 2)
    cy = int(loc[1] + h // 2)
    return (cx, cy, float(score), mode)

# =========================
# REGION PREVIEW
# =========================
def draw_region_preview(region, loops=2, speed=0.15):
    """
    วาดสี่เหลี่ยมด้วยเมาส์เพื่อแสดงพื้นที่ตรวจจับ
    region: (x, y, width, height)
    loops: จำนวนรอบที่จะวาด
    speed: ความเร็วในการเลื่อนเมาส์ (วินาที)
    """
    if not region:
        print("⚠️ ไม่มี region ให้แสดง")
        return
    
    x, y, w, h = region
    # คำนวณ 4 มุม
    top_left = (x, y)
    top_right = (x + w, y)
    bottom_right = (x + w, y + h)
    bottom_left = (x, y + h)
    
    print(f"\n📐 กำลังวาดพื้นที่ตรวจจับ...")
    print(f"   มุมซ้ายบน: {top_left}")
    print(f"   มุมขวาล่าง: {bottom_right}")
    
    for i in range(loops):
        # วาดสี่เหลี่ยม: ซ้ายบน -> ขวาบน -> ขวาล่าง -> ซ้ายล่าง -> กลับซ้ายบน
        pyautogui.moveTo(top_left[0], top_left[1], duration=speed)
        pyautogui.moveTo(top_right[0], top_right[1], duration=speed)
        pyautogui.moveTo(bottom_right[0], bottom_right[1], duration=speed)
        pyautogui.moveTo(bottom_left[0], bottom_left[1], duration=speed)
        pyautogui.moveTo(top_left[0], top_left[1], duration=speed)
    
    # จบที่กลางพื้นที่
    center_x = x + w // 2
    center_y = y + h // 2
    pyautogui.moveTo(center_x, center_y, duration=speed)
    print(f"   ✅ วาดเสร็จแล้ว! (กลาง: {center_x}, {center_y})")

# =========================
# CLICK FUNCTIONS
# =========================
def click_at(x, y, double=False):
    """คลิกที่ตำแหน่ง x, y"""
    pyautogui.moveTo(x, y)
    if double:
        pyautogui.mouseDown(); time.sleep(0.01); pyautogui.mouseUp()
        time.sleep(0.01)
        pyautogui.mouseDown(); time.sleep(0.01); pyautogui.mouseUp()
    else:
        pyautogui.click()

def simple_click(x, y):
    """คลิกธรรมดา"""
    pyautogui.moveTo(x, y)
    pyautogui.click()

# =========================
# DETECTION FUNCTIONS
# =========================
def detect_state(screen_gray, templates, offset=(0, 0)):
    """
    ตรวจจับ state ปัจจุบัน
    Returns: (state, x, y, score) หรือ (None, 0, 0, 0)
    """
    menu_tpl, spatula_tpl, done_tpl, cancook_tpl, cannotcook_tpl = templates
    ox, oy = offset
    
    # ลำดับความสำคัญ: spatula > done > cannotcook > cancook > menu
    
    # 1. ตรวจ spatula (quicktime event - ต้องกดรัวๆ)
    if spatula_tpl:
        result = match_template(screen_gray, spatula_tpl[0], spatula_tpl[1])
        if result:
            cx, cy, score, mode = result
            return (GameState.QUICKTIME_EVENT, cx + ox, cy + oy, score)
    
    # 2. ตรวจ cooking done
    if done_tpl:
        result = match_template(screen_gray, done_tpl[0], done_tpl[1])
        if result:
            cx, cy, score, mode = result
            return (GameState.COOKING_DONE, cx + ox, cy + oy, score)
    
    # 3. ตรวจ cannotcook (หมดวัตถุดิบ - หยุดบอท)
    if cannotcook_tpl:
        result = match_template(screen_gray, cannotcook_tpl[0], cannotcook_tpl[1])
        if result:
            cx, cy, score, mode = result
            return (GameState.CANNOT_COOK, cx + ox, cy + oy, score)
    
    # 4. ตรวจ cancook (ทำอาหารได้ - double click)
    if cancook_tpl:
        result = match_template(screen_gray, cancook_tpl[0], cancook_tpl[1])
        if result:
            cx, cy, score, mode = result
            return (GameState.CAN_COOK, cx + ox, cy + oy, score)
    
    # 5. ตรวจ select menu
    if menu_tpl:
        result = match_template(screen_gray, menu_tpl[0], menu_tpl[1])
        if result:
            cx, cy, score, mode = result
            return (GameState.WAITING_MENU, cx + ox, cy + oy, score)
    
    return (None, 0, 0, 0)

# =========================
# MAIN BOT LOOP
# =========================
def run_bot():
    global STOP_FLAG
    STOP_FLAG = False

    print("\n" + "="*60)
    print("🍳 Cooking Bot - Heartopia")
    print("="*60)

    # Load templates
    print("\n📦 กำลังโหลด templates...")
    
    spatula_tpl = load_template(TEMPLATE_SPATULA)
    menu_tpl = load_template(TEMPLATE_MENU)
    done_tpl = load_template(TEMPLATE_DONE)
    cancook_tpl = load_template(TEMPLATE_CANCOOK)
    cannotcook_tpl = load_template(TEMPLATE_CANNOTCOOK)
    
    if not spatula_tpl:
        print(f"❌ ไม่พบ template ตะหลิว: {TEMPLATE_SPATULA}")
        return
    print(f"   ✅ spatula_template.png")
    
    if not menu_tpl:
        print(f"⚠️ ไม่พบ template เลือกเมนู: {TEMPLATE_MENU}")
    else:
        print(f"   ✅ select_menu.png")
    
    if not done_tpl:
        print(f"⚠️ ไม่พบ template อาหารเสร็จ: {TEMPLATE_DONE}")
    else:
        print(f"   ✅ cookingdone.png")
    
    if not cancook_tpl:
        print(f"⚠️ ไม่พบ template ทำอาหารได้: {TEMPLATE_CANCOOK}")
    else:
        print(f"   ✅ cancook.png")
    
    if not cannotcook_tpl:
        print(f"⚠️ ไม่พบ template ทำอาหารไม่ได้: {TEMPLATE_CANNOTCOOK}")
    else:
        print(f"   ✅ cannotcook.png")

    # Load region
    region = load_region()
    if region:
        print(f"\n✅ REGION: ({region[0]}, {region[1]}) - ({region[0]+region[2]}, {region[1]+region[3]})")
        print(f"   ขนาด: {region[2]}x{region[3]} พิกเซล")
    else:
        print("\n⚠️ ไม่พบ region - จะค้นหาทั้งหน้าจอ")

    print("\n" + "------------------------------------------------------------")
    print("🎮 Game Flow:")
    print("   1. รอหน้าเลือกเมนู (select_menu) -> คลิกเมนู + คลิกพิกัด (220, 260)")
    print("   2. เจอ cancook → double click เริ่มทำอาหาร")
    print("   3. เจอ cannotcook → หยุดบอท (หมดวัตถุดิบ)")
    print("   4. เห็น spatula → กดรัวๆ จนหายไป")
    print("   5. เห็น cookingdone → คลิก, รอ 1 วิ")
    print("   6. วนลูปกลับไปข้อ 1")
    print("------------------------------------------------------------")
    print("\n🛑 กด ESC หรือ SPACE เพื่อหยุด")
    input("\n👉 กด Enter เพื่อดูพื้นที่ตรวจจับ...")

    # วาดสี่เหลี่ยมแสดงพื้นที่ตรวจจับ
    if region:
        print("\n⏳ สลับไปหน้าเกมใน 2 วินาที...")
        time.sleep(2)
        draw_region_preview(region, loops=2, speed=0.12)
        time.sleep(0.5)
    
    input("\n👉 กด Enter เพื่อเริ่มบอท...")
    print("\n⏳ เริ่มใน 2 วินาที...")
    time.sleep(2)
    print("   GO!\n")

    listener = start_keyboard_listener()
    
    templates = (menu_tpl, spatula_tpl, done_tpl, cancook_tpl, cannotcook_tpl)
    offset = (region[0], region[1]) if region else (0, 0)
    
    # Stats
    click_count = 0
    done_count = 0
    current_state = None
    should_check_btn_color = False  # Flag: ตรวจสอบสีปุ่มหลังกด select_menu เท่านั้น
    
    try:
        while not check_stop():
            # 1. สแกนพื้นที่หลัก (Main Region)
            scr = screenshot_gray(region=region)
            state, x, y, score = detect_state(scr, templates, offset)
            
            # 2. ตรวจสอบปุ่มเริ่มทำอาหารด้วยการเช็คสี (Color Check)
            # ** จะตรวจเฉพาะหลังกด select_menu แล้วเท่านั้น **
            btn_state = None
            btn_color = None
            
            if should_check_btn_color:
                try:
                    # HYBRID: Template Matching + Color Check
                    btn_scr = screenshot_gray(region=REGION_START_BTN)
                    btn_found = False
                    btn_x, btn_y = 0, 0
                    
                    # หาปุ่ม
                    if templates[3]:
                        res = match_template(btn_scr, templates[3][0], templates[3][1])
                        if res:
                            btn_found = True
                            btn_x, btn_y = res[0] + BTN_START_X1, res[1] + BTN_START_Y1
                    
                    if not btn_found and templates[4]:
                        res = match_template(btn_scr, templates[4][0], templates[4][1])
                        if res:
                            btn_found = True
                            btn_x, btn_y = res[0] + BTN_START_X1, res[1] + BTN_START_Y1
                    
                    # เช็คสีถ้าเจอปุ่ม
                    if btn_found:
                        current_rgb = pyautogui.pixel(btn_x, btn_y)
                        
                        def hex_to_rgb(h):
                            h = h.lstrip('#')
                            return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
                        
                        def color_dist(c1, c2):
                            return max(abs(c1[i] - c2[i]) for i in range(3))
                        
                        dist_can = color_dist(current_rgb, hex_to_rgb(BTN_COLOR_CANCOOK))
                        dist_cannot = color_dist(current_rgb, hex_to_rgb(BTN_COLOR_CANNOTCOOK))
                        
                        # เปรียบเทียบสี
                        if dist_can < dist_cannot:
                            btn_state = GameState.CAN_COOK
                            print(f"   ✅ ปุ่มสีฟ้า -> ทำอาหารได้!")
                        else:
                            btn_state = GameState.CANNOT_COOK
                            print(f"   🛑 ปุ่มสีเทา -> หยุดบอท")
                            
                except Exception as e:
                    pass
            
            # ถ้าเจอสถานะจากปุ่ม ให้ใช้สถานะนั้นแทน (ยกเว้นกำลังผัดตะหลิวอยู่)
            if btn_state and state != GameState.QUICKTIME_EVENT:
                state = btn_state
                x, y, score = BTN_CENTER_X, BTN_CENTER_Y, 1.0
                should_check_btn_color = False

            # === STATE HANDLERS ===
            if state == GameState.QUICKTIME_EVENT:
                # ผัดอาหาร
                if current_state != GameState.QUICKTIME_EVENT:
                    print(f"🎯 เจอตะหลิว! กำลังคลิก...")
                    current_state = GameState.QUICKTIME_EVENT
                
                click_at(x, y, double=DOUBLE_CLICK_SPATULA)
                click_count += 1
                time.sleep(SPATULA_CLICK_DELAY)
                
            elif state == GameState.COOKING_DONE:
                # เก็บอาหาร
                if current_state != GameState.COOKING_DONE:
                    click_at(x, y, double=True)
                    click_count += 1
                    done_count += 1
                    print(f"✅ อาหารเสร็จ! (จาน #{done_count}) รอ {DONE_CLICK_WAIT} วิ...")
                    current_state = GameState.COOKING_DONE
                    time.sleep(DONE_CLICK_WAIT)
                    current_state = None
            
            elif state == GameState.CAN_COOK:
                # กดปุ่มเริ่มทำอาหาร
                if current_state != GameState.CAN_COOK:
                    click_at(x, y, double=True)
                    click_count += 1
                    print(f"🍳 เริ่มทำอาหาร! รอ 0.8 วิ...")
                    current_state = GameState.CAN_COOK
                    time.sleep(0.8) 
                    current_state = None
                
            elif state == GameState.CANNOT_COOK:
                # หยุดบอท
                print(f"\n🛑 วัตถุดิบหมด! หยุดการทำงาน")
                break
                    
            elif state == GameState.WAITING_MENU:
                # กดเลือกเมนูอาหาร
                if current_state != GameState.WAITING_MENU:
                    # คลิกเลือกเมนู
                    click_at(x, y, double=True)
                    click_count += 1
                    
                    # คลิกพิกัดพิเศษตามที่ผู้ใช้ระบุ
                    click_at(220, 260, double=True)
                    click_count += 1
                    
                    print(f"📋 เลือกเมนู! (และคลิกพิกัดพิเศษ) รอ 1 วิ...")
                    current_state = GameState.WAITING_MENU
                    time.sleep(1)
                    should_check_btn_color = True
                    current_state = None
                
            else:
                # ไม่เจออะไรเลย
                if current_state is not None:
                    current_state = None
                time.sleep(SEARCH_DELAY)

    except pyautogui.FailSafeException:
        print("\n🛑 FailSafe: เมาส์ไปมุมจอแล้วหยุดอัตโนมัติ")
    except KeyboardInterrupt:
        pass
    finally:
        try:
            listener.stop()
        except:
            pass
        print(f"\n🏁 สรุป:")
        print(f"   คลิกทั้งหมด: {click_count} ครั้ง")
        print(f"   ทำอาหารเสร็จ: {done_count} จาน")

# =========================
# MAIN
# =========================
def main():
    if len(sys.argv) > 1:
        cmd = sys.argv[1].strip().lower()
        if cmd == "--help":
            print("Usage:")
            print("  python cooking_bot.py           # รันบอท")
            print("  python cooking_bot.py --help    # แสดงวิธีใช้")
            print("\nต้องมีไฟล์:")
            print("  - spatula_template.png = ไอคอนตะหลิว (quicktime)")
            print("  - select_menu.png      = หน้าเลือกเมนู")
            print("  - cookingdone.png      = อาหารเสร็จ")
            print("  - spatula_region.json  = พื้นที่ค้นหา [x1, y1, x2, y2]")
        else:
            print(f"Unknown option: {sys.argv[1]}")
    else:
        run_bot()

if __name__ == "__main__":
    main()
