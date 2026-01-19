"""
🍳 Cooking Bot - Heartopia (FULL VERBOSE LOG VERSION)
Loop: เลือกเมนู → Quicktime Event (กดรัวๆ) → อาหารเสร็จ → วนลูป

Templates:
- select_menu.png      = หน้าจอเลือกเมนู (รอผู้ใช้กดเอง)
- spatula_template.png = ไอคอนตะหลิว (กดรัวๆ)
- cookingdone.png      = อาหารเสร็จ (คลิก 1 ครั้ง)
- cancook.png          = ทำอาหารได้
- cannotcook.png       = ทำอาหารไม่ได้ (หมดวัตถุดิบ)

Stop: กด ESC หรือ SPACE เพื่อหยุด

LOG:
- Console + File (cooking_bot.log)
"""

import time
import sys
import json
import logging
from logging.handlers import RotatingFileHandler
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
MAX_CLICKS_PER_FOUND = 8       # (ยังคงค่าไว้) คลิกสูงสุดต่อการเจอ (ในเวอร์ชันนี้ยังคลิกแบบเดิม = 1 click/loop)

# --- Special Regions ---
# พื้นที่สำหรับปุ่ม "เริ่มทำอาหาร" โดยเฉพาะ (x, y, w, h)
BTN_START_X1, BTN_START_Y1 = 1236, 919
BTN_START_X2, BTN_START_Y2 = 1573, 1041
REGION_START_BTN = (BTN_START_X1, BTN_START_Y1, BTN_START_X2 - BTN_START_X1, BTN_START_Y2 - BTN_START_Y1)

# ตำแหน่งกลางปุ่ม (สำหรับใช้แทนตำแหน่งคลิก)
BTN_CENTER_X = (BTN_START_X1 + BTN_START_X2) // 2  # 1404
BTN_CENTER_Y = (BTN_START_Y1 + BTN_START_Y2) // 2  # 980

# --- สีของปุ่ม ---
BTN_COLOR_CANCOOK = "#3ECDC3"     # สีฟ้า (ทำอาหารได้)
BTN_COLOR_CANNOTCOOK = "#BDC3C0" # สีเทา (ทำอาหารไม่ได้)
BTN_COLOR_TOLERANCE = 30          # ความคลาดเคลื่อนของสี (เก็บไว้เผื่อใช้)

# --- LOGGING ---
LOG_FILE = BASE_DIR / "cooking_bot.log"
LOG_LEVEL = "DEBUG"  # DEBUG / INFO
LOG_TO_FILE = True
LOG_TO_CONSOLE = True

# log รายละเอียด match ทุกกี่เฟรม (1 = ทุกลูป)
LOG_EVERY_N_FRAMES = 1

# ถ้า True จะ log คะแนน raw/edge ของ template ทุกตัว (ละเอียดมาก)
LOG_MATCH_DETAILS = True

# log การ “ไม่พบอะไร” ทุกลูปด้วย (ถ้า False จะ log เฉพาะเมื่อเจอ state สำคัญ)
LOG_NO_STATE_EACH_LOOP = True


# =========================
# LOGGER SETUP
# =========================
def setup_logger():
    logger = logging.getLogger("cooking_bot")
    # ป้องกันเพิ่ม handler ซ้ำ (ตอนรันซ้ำในบาง env)
    if logger.handlers:
        return logger

    level = getattr(logging, LOG_LEVEL.upper(), logging.DEBUG)
    logger.setLevel(level)

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-5s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    if LOG_TO_CONSOLE:
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(level)
        ch.setFormatter(fmt)
        logger.addHandler(ch)

    if LOG_TO_FILE:
        fh = RotatingFileHandler(str(LOG_FILE), maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        fh.setLevel(level)
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    logger.debug("Logger initialized.")
    return logger


logger = setup_logger()


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
            logger.warning("🛑 หยุดฉุกเฉิน! (กด ESC หรือ SPACE)")
            return False
    except Exception as e:
        logger.debug(f"on_key_press exception: {e}")
    return None

def start_keyboard_listener():
    listener = keyboard.Listener(on_press=on_key_press)
    listener.start()
    logger.debug("Keyboard listener started.")
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
                x1, y1, x2, y2 = [int(v) for v in r]
                region = (x1, y1, x2 - x1, y2 - y1)
                logger.info(f"✅ Loaded region from JSON: {r} -> (x={region[0]}, y={region[1]}, w={region[2]}, h={region[3]})")
                return region
            logger.warning(f"⚠️ REGION_FILE format invalid: {data}")
        except Exception as e:
            logger.exception(f"⚠️ ไม่สามารถโหลด region: {e}")
    else:
        logger.info("⚠️ REGION_FILE not found. Will scan full screen.")
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

def load_template(path: Path):
    """โหลด template และคืนค่า (gray, edge) หรือ None"""
    if not path.exists():
        logger.warning(f"Template missing: {path.name} ({path})")
        return None
    gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        logger.warning(f"Template read failed: {path.name} ({path})")
        return None
    edge = edges(gray)
    logger.debug(f"Template loaded: {path.name} shape={gray.shape}")
    return (gray, edge)

def screenshot_gray(region=None):
    t0 = time.perf_counter()
    img = pyautogui.screenshot(region=region) if region else pyautogui.screenshot()
    g = to_gray(img)
    dt = (time.perf_counter() - t0) * 1000
    logger.debug(f"Screenshot captured region={region} gray_shape={g.shape} time={dt:.1f}ms")
    return g


def match_template(screen_gray, template_gray, template_edge,
                   raw_thr=MATCH_CONFIDENCE, edge_thr=EDGE_CONFIDENCE,
                   return_debug=False):
    """
    คืนค่า:
      - ถ้า return_debug=False: (cx, cy, best_score, mode) หรือ None
      - ถ้า return_debug=True: ((cx, cy, best_score, mode) หรือ None, debug_dict)
    """
    h, w = template_gray.shape[:2]

    debug = {
        "raw_thr": float(raw_thr),
        "edge_thr": float(edge_thr),
        "raw_max": None, "raw_loc": None,
        "edge_max": None, "edge_loc": None,
        "best_mode": None, "best_score": None, "best_loc": None,
        "template_wh": (int(w), int(h)),
    }

    best = None

    # --- RAW matching ---
    res = cv2.matchTemplate(screen_gray, template_gray, cv2.TM_CCOEFF_NORMED)
    _, raw_max, _, raw_loc = cv2.minMaxLoc(res)
    debug["raw_max"] = float(raw_max)
    debug["raw_loc"] = (int(raw_loc[0]), int(raw_loc[1]))

    if raw_max >= raw_thr:
        best = ("raw", float(raw_max), raw_loc)

    # --- EDGE matching ---
    scr_edge = edges(screen_gray)
    res2 = cv2.matchTemplate(scr_edge, template_edge, cv2.TM_CCOEFF_NORMED)
    _, edge_max, _, edge_loc = cv2.minMaxLoc(res2)
    debug["edge_max"] = float(edge_max)
    debug["edge_loc"] = (int(edge_loc[0]), int(edge_loc[1]))

    if edge_max >= edge_thr:
        if best is None or edge_max > best[1]:
            best = ("edge", float(edge_max), edge_loc)

    if best is None:
        if return_debug:
            return None, debug
        return None

    mode, score, loc = best
    debug["best_mode"] = mode
    debug["best_score"] = float(score)
    debug["best_loc"] = (int(loc[0]), int(loc[1]))

    cx = int(loc[0] + w // 2)
    cy = int(loc[1] + h // 2)
    result = (cx, cy, float(score), mode)

    if return_debug:
        return result, debug
    return result


# =========================
# REGION PREVIEW
# =========================
def draw_region_preview(region, loops=2, speed=0.15):
    """
    วาดสี่เหลี่ยมด้วยเมาส์เพื่อแสดงพื้นที่ตรวจจับ
    region: (x, y, width, height)
    """
    if not region:
        logger.warning("⚠️ ไม่มี region ให้แสดง")
        return

    x, y, w, h = region
    top_left = (x, y)
    top_right = (x + w, y)
    bottom_right = (x + w, y + h)
    bottom_left = (x, y + h)

    logger.info("📐 กำลังวาดพื้นที่ตรวจจับ...")
    logger.info(f"   มุมซ้ายบน: {top_left}")
    logger.info(f"   มุมขวาล่าง: {bottom_right}")

    for i in range(loops):
        logger.debug(f"Draw loop {i+1}/{loops}")
        pyautogui.moveTo(top_left[0], top_left[1], duration=speed)
        pyautogui.moveTo(top_right[0], top_right[1], duration=speed)
        pyautogui.moveTo(bottom_right[0], bottom_right[1], duration=speed)
        pyautogui.moveTo(bottom_left[0], bottom_left[1], duration=speed)
        pyautogui.moveTo(top_left[0], top_left[1], duration=speed)

    center_x = x + w // 2
    center_y = y + h // 2
    pyautogui.moveTo(center_x, center_y, duration=speed)
    logger.info(f"   ✅ วาดเสร็จแล้ว! (กลาง: {center_x}, {center_y})")


# =========================
# CLICK FUNCTIONS
# =========================
def click_at(x, y, double=False, reason=""):
    """คลิกที่ตำแหน่ง x, y"""
    logger.debug(f"CLICK: moveTo({x},{y}) double={double} reason={reason}")
    pyautogui.moveTo(x, y)
    if double:
        pyautogui.mouseDown(); time.sleep(0.01); pyautogui.mouseUp()
        time.sleep(0.01)
        pyautogui.mouseDown(); time.sleep(0.01); pyautogui.mouseUp()
    else:
        pyautogui.click()

def simple_click(x, y, reason=""):
    logger.debug(f"CLICK(simple): moveTo({x},{y}) reason={reason}")
    pyautogui.moveTo(x, y)
    pyautogui.click()


# =========================
# DETECTION FUNCTIONS
# =========================
def _log_match(name, debug, found):
    if not debug:
        return
    logger.debug(
        f"MATCH[{name}] found={found} "
        f"raw={debug['raw_max']:.3f} (thr={debug['raw_thr']:.2f}, loc={debug['raw_loc']}) "
        f"edge={debug['edge_max']:.3f} (thr={debug['edge_thr']:.2f}, loc={debug['edge_loc']}) "
        f"best={debug['best_mode']}:{debug['best_score'] if debug['best_score'] is not None else None} "
        f"tpl_wh={debug['template_wh']}"
    )

def detect_state(screen_gray, templates, offset=(0, 0), frame_id=0):
    """
    ตรวจจับ state ปัจจุบัน
    Returns: (state, x, y, score) หรือ (None, 0, 0, 0)
    """
    menu_tpl, spatula_tpl, done_tpl, cancook_tpl, cannotcook_tpl = templates
    ox, oy = offset

    # ลำดับความสำคัญ: spatula > done > cannotcook > cancook > menu
    # หมายเหตุ: เพื่อให้ log ครบทุกขั้น เราจะ “คำนวณ + log” ตามลำดับนี้
    # และ return ทันทีเมื่อเจออันแรกที่ผ่าน threshold

    # 1) spatula
    if spatula_tpl:
        res, dbg = match_template(screen_gray, spatula_tpl[0], spatula_tpl[1], return_debug=True)
        if LOG_MATCH_DETAILS and (frame_id % LOG_EVERY_N_FRAMES == 0):
            _log_match("spatula", dbg, found=bool(res))
        if res:
            cx, cy, score, mode = res
            return (GameState.QUICKTIME_EVENT, cx + ox, cy + oy, score)

    # 2) done
    if done_tpl:
        res, dbg = match_template(screen_gray, done_tpl[0], done_tpl[1], return_debug=True)
        if LOG_MATCH_DETAILS and (frame_id % LOG_EVERY_N_FRAMES == 0):
            _log_match("done", dbg, found=bool(res))
        if res:
            cx, cy, score, mode = res
            return (GameState.COOKING_DONE, cx + ox, cy + oy, score)

    # 3) cannotcook
    if cannotcook_tpl:
        res, dbg = match_template(screen_gray, cannotcook_tpl[0], cannotcook_tpl[1], return_debug=True)
        if LOG_MATCH_DETAILS and (frame_id % LOG_EVERY_N_FRAMES == 0):
            _log_match("cannotcook", dbg, found=bool(res))
        if res:
            cx, cy, score, mode = res
            return (GameState.CANNOT_COOK, cx + ox, cy + oy, score)

    # 4) cancook
    if cancook_tpl:
        res, dbg = match_template(screen_gray, cancook_tpl[0], cancook_tpl[1], return_debug=True)
        if LOG_MATCH_DETAILS and (frame_id % LOG_EVERY_N_FRAMES == 0):
            _log_match("cancook", dbg, found=bool(res))
        if res:
            cx, cy, score, mode = res
            return (GameState.CAN_COOK, cx + ox, cy + oy, score)

    # 5) menu
    if menu_tpl:
        res, dbg = match_template(screen_gray, menu_tpl[0], menu_tpl[1], return_debug=True)
        if LOG_MATCH_DETAILS and (frame_id % LOG_EVERY_N_FRAMES == 0):
            _log_match("menu", dbg, found=bool(res))
        if res:
            cx, cy, score, mode = res
            return (GameState.WAITING_MENU, cx + ox, cy + oy, score)

    return (None, 0, 0, 0)


# =========================
# COLOR CHECK HELPERS
# =========================
def hex_to_rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def color_dist(c1, c2):
    return max(abs(c1[i] - c2[i]) for i in range(3))


# =========================
# MAIN BOT LOOP
# =========================
def run_bot():
    global STOP_FLAG
    STOP_FLAG = False

    logger.info("=" * 60)
    logger.info("🍳 Cooking Bot - Heartopia (VERBOSE LOG)")
    logger.info("=" * 60)

    logger.info("📦 กำลังโหลด templates...")

    spatula_tpl = load_template(TEMPLATE_SPATULA)
    menu_tpl = load_template(TEMPLATE_MENU)
    done_tpl = load_template(TEMPLATE_DONE)
    cancook_tpl = load_template(TEMPLATE_CANCOOK)
    cannotcook_tpl = load_template(TEMPLATE_CANNOTCOOK)

    if not spatula_tpl:
        logger.error(f"❌ ไม่พบ template ตะหลิว: {TEMPLATE_SPATULA}")
        return
    logger.info("   ✅ spatula_template.png")

    if not menu_tpl:
        logger.warning(f"⚠️ ไม่พบ template เลือกเมนู: {TEMPLATE_MENU}")
    else:
        logger.info("   ✅ select_menu.png")

    if not done_tpl:
        logger.warning(f"⚠️ ไม่พบ template อาหารเสร็จ: {TEMPLATE_DONE}")
    else:
        logger.info("   ✅ cookingdone.png")

    if not cancook_tpl:
        logger.warning(f"⚠️ ไม่พบ template ทำอาหารได้: {TEMPLATE_CANCOOK}")
    else:
        logger.info("   ✅ cancook.png")

    if not cannotcook_tpl:
        logger.warning(f"⚠️ ไม่พบ template ทำอาหารไม่ได้: {TEMPLATE_CANNOTCOOK}")
    else:
        logger.info("   ✅ cannotcook.png")

    region = load_region()
    if region:
        logger.info(f"✅ REGION: ({region[0]}, {region[1]}) - ({region[0] + region[2]}, {region[1] + region[3]}) | size={region[2]}x{region[3]}")
    else:
        logger.info("⚠️ ไม่พบ region - จะค้นหาทั้งหน้าจอ")

    logger.info("-" * 60)
    logger.info("🎮 Game Flow:")
    logger.info("   1) รอหน้าเลือกเมนู (select_menu) -> คลิกเมนู + คลิกพิกัด (220, 260)")
    logger.info("   2) เจอ cancook → double click เริ่มทำอาหาร")
    logger.info("   3) เจอ cannotcook → หยุดบอท (หมดวัตถุดิบ)")
    logger.info("   4) เห็น spatula → กดรัวๆ จนหายไป")
    logger.info(f"   5) เห็น cookingdone → คลิก, รอ {DONE_CLICK_WAIT} วิ")
    logger.info("   6) วนลูปกลับไปข้อ 1")
    logger.info("-" * 60)

    logger.info("🛑 กด ESC หรือ SPACE เพื่อหยุด")
    input("\n👉 กด Enter เพื่อดูพื้นที่ตรวจจับ...")

    if region:
        logger.info("⏳ สลับไปหน้าเกมใน 2 วินาที...")
        time.sleep(2)
        draw_region_preview(region, loops=2, speed=0.12)
        time.sleep(0.5)

    input("\n👉 กด Enter เพื่อเริ่มบอท...")
    logger.info("⏳ เริ่มใน 2 วินาที...")
    time.sleep(2)
    logger.info("GO!")

    listener = start_keyboard_listener()

    templates = (menu_tpl, spatula_tpl, done_tpl, cancook_tpl, cannotcook_tpl)
    offset = (region[0], region[1]) if region else (0, 0)

    click_count = 0
    done_count = 0
    current_state = None
    should_check_btn_color = False

    frame_id = 0

    try:
        while not check_stop():
            frame_id += 1
            loop_t0 = time.perf_counter()

            logger.debug(f"--- LOOP frame={frame_id} ---")

            # 1) Scan main region
            scr = screenshot_gray(region=region)
            state, x, y, score = detect_state(scr, templates, offset, frame_id=frame_id)

            if state:
                logger.info(f"[frame={frame_id}] DETECT state={state.value} pos=({x},{y}) score={score:.3f}")
            else:
                if LOG_NO_STATE_EACH_LOOP:
                    logger.info(f"[frame={frame_id}] DETECT state=None (no match above thresholds)")

            # 2) Button color check (only after selecting menu)
            btn_state = None

            if should_check_btn_color:
                logger.debug(f"[frame={frame_id}] BTN_COLOR_CHECK enabled. region={REGION_START_BTN}")

                try:
                    btn_scr = screenshot_gray(region=REGION_START_BTN)
                    btn_found = False
                    btn_x, btn_y = 0, 0
                    found_from = None

                    # Try find cancook icon inside button region
                    if templates[3]:
                        res, dbg = match_template(btn_scr, templates[3][0], templates[3][1], return_debug=True)
                        if LOG_MATCH_DETAILS and (frame_id % LOG_EVERY_N_FRAMES == 0):
                            _log_match("btn_cancook", dbg, found=bool(res))
                        if res:
                            btn_found = True
                            btn_x, btn_y = res[0] + BTN_START_X1, res[1] + BTN_START_Y1
                            found_from = "cancook"

                    # Try find cannotcook icon inside button region
                    if (not btn_found) and templates[4]:
                        res, dbg = match_template(btn_scr, templates[4][0], templates[4][1], return_debug=True)
                        if LOG_MATCH_DETAILS and (frame_id % LOG_EVERY_N_FRAMES == 0):
                            _log_match("btn_cannotcook", dbg, found=bool(res))
                        if res:
                            btn_found = True
                            btn_x, btn_y = res[0] + BTN_START_X1, res[1] + BTN_START_Y1
                            found_from = "cannotcook"

                    if btn_found:
                        current_rgb = pyautogui.pixel(btn_x, btn_y)
                        can_rgb = hex_to_rgb(BTN_COLOR_CANCOOK)
                        cannot_rgb = hex_to_rgb(BTN_COLOR_CANNOTCOOK)

                        dist_can = color_dist(current_rgb, can_rgb)
                        dist_cannot = color_dist(current_rgb, cannot_rgb)

                        logger.info(
                            f"[frame={frame_id}] BTN_FOUND via={found_from} sample=({btn_x},{btn_y}) "
                            f"rgb={current_rgb} dist_can={dist_can} dist_cannot={dist_cannot}"
                        )

                        if dist_can < dist_cannot:
                            btn_state = GameState.CAN_COOK
                            logger.info(f"[frame={frame_id}] ✅ ปุ่มสีฟ้า -> ทำอาหารได้!")
                        else:
                            btn_state = GameState.CANNOT_COOK
                            logger.warning(f"[frame={frame_id}] 🛑 ปุ่มสีเทา -> หยุดบอท")
                    else:
                        logger.warning(f"[frame={frame_id}] BTN_COLOR_CHECK: ไม่พบไอคอนปุ่มใน REGION_START_BTN")

                except Exception as e:
                    logger.exception(f"[frame={frame_id}] BTN_COLOR_CHECK exception: {e}")

            # ถ้าเจอสถานะจากปุ่ม ให้ใช้สถานะนั้นแทน (ยกเว้นกำลังผัดตะหลิวอยู่)
            if btn_state and state != GameState.QUICKTIME_EVENT:
                logger.debug(f"[frame={frame_id}] Override state by button color: {btn_state.value}")
                state = btn_state
                x, y, score = BTN_CENTER_X, BTN_CENTER_Y, 1.0
                should_check_btn_color = False

            # ===== STATE HANDLERS =====
            if state == GameState.QUICKTIME_EVENT:
                if current_state != GameState.QUICKTIME_EVENT:
                    logger.info(f"[frame={frame_id}] 🎯 เจอตะหลิว! เริ่มคลิก (double={DOUBLE_CLICK_SPATULA})")
                    current_state = GameState.QUICKTIME_EVENT

                click_at(x, y, double=DOUBLE_CLICK_SPATULA, reason="spatula")
                click_count += 1
                logger.debug(f"[frame={frame_id}] spatula click_count={click_count} delay={SPATULA_CLICK_DELAY}s")
                time.sleep(SPATULA_CLICK_DELAY)

            elif state == GameState.COOKING_DONE:
                if current_state != GameState.COOKING_DONE:
                    logger.info(f"[frame={frame_id}] ✅ อาหารเสร็จ! จะคลิกเก็บ + รอ {DONE_CLICK_WAIT}s")
                    click_at(x, y, double=True, reason="cooking_done")
                    click_count += 1
                    done_count += 1
                    logger.info(f"[frame={frame_id}] ✅ จาน #{done_count} | click_count={click_count}")
                    current_state = GameState.COOKING_DONE
                    time.sleep(DONE_CLICK_WAIT)
                    current_state = None
                    logger.debug(f"[frame={frame_id}] done wait finished -> state reset")

            elif state == GameState.CAN_COOK:
                if current_state != GameState.CAN_COOK:
                    logger.info(f"[frame={frame_id}] 🍳 เริ่มทำอาหาร! double click ที่ ({x},{y}) แล้วรอ 0.8s")
                    click_at(x, y, double=True, reason="can_cook")
                    click_count += 1
                    current_state = GameState.CAN_COOK
                    time.sleep(0.8)
                    current_state = None
                    logger.debug(f"[frame={frame_id}] can_cook wait finished -> state reset")

            elif state == GameState.CANNOT_COOK:
                logger.warning(f"[frame={frame_id}] 🛑 วัตถุดิบหมด! หยุดการทำงาน")
                break

            elif state == GameState.WAITING_MENU:
                if current_state != GameState.WAITING_MENU:
                    logger.info(f"[frame={frame_id}] 📋 เลือกเมนู: double click ที่ ({x},{y}) + double click (220,260)")
                    click_at(x, y, double=True, reason="select_menu")
                    click_count += 1

                    click_at(220, 260, double=True, reason="special_click_220_260")
                    click_count += 1

                    logger.info(f"[frame={frame_id}] 📋 เลือกเมนูแล้ว รอ 1s และเปิดโหมดเช็คสีปุ่มเริ่มทำอาหาร")
                    current_state = GameState.WAITING_MENU
                    time.sleep(1.0)
                    should_check_btn_color = True
                    current_state = None

            else:
                if current_state is not None:
                    logger.debug(f"[frame={frame_id}] No state -> reset current_state from {current_state.value}")
                    current_state = None
                logger.debug(f"[frame={frame_id}] sleep SEARCH_DELAY={SEARCH_DELAY}s")
                time.sleep(SEARCH_DELAY)

            loop_dt = (time.perf_counter() - loop_t0) * 1000
            logger.debug(f"[frame={frame_id}] loop time={loop_dt:.1f}ms | clicks={click_count} done={done_count}")

    except pyautogui.FailSafeException:
        logger.warning("🛑 FailSafe: เมาส์ไปมุมจอแล้วหยุดอัตโนมัติ")
    except KeyboardInterrupt:
        logger.warning("KeyboardInterrupt -> stop")
    finally:
        try:
            listener.stop()
            logger.debug("Keyboard listener stopped.")
        except Exception as e:
            logger.debug(f"listener.stop exception: {e}")

        logger.info("🏁 สรุป:")
        logger.info(f"   คลิกทั้งหมด: {click_count} ครั้ง")
        logger.info(f"   ทำอาหารเสร็จ: {done_count} จาน")
        logger.info(f"   LOG FILE: {LOG_FILE}")


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
            print("  - cancook.png          = ทำอาหารได้")
            print("  - cannotcook.png       = ทำอาหารไม่ได้")
            print("  - spatula_region.json  = พื้นที่ค้นหา [x1, y1, x2, y2] (optional)")
            print("\nLogs:")
            print(f"  - {LOG_FILE}")
        else:
            print(f"Unknown option: {sys.argv[1]}")
    else:
        run_bot()

if __name__ == "__main__":
    main()
