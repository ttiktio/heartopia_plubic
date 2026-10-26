"""
====================================================================
 Auto Clicker v3 (SendInput + ตรวจหาปุ่ม "ขายเลย" สีฟ้าอัตโนมัติ)
====================================================================
ขั้นตอนต่อรอบ
  1. เลื่อนเมาส์ไปกลางจอ
  2. คลิกจุดที่ 1 (721, 869)
  3. คลิกจุดที่ 2 (1397, 867)
  4. หาปุ่มสีฟ้า "ขายเลย" ในกรอบ X 1568-1909, Y 60-311 แล้วคลิก
     - ปุ่มเลื่อนขึ้นลงตามจำนวนชื่อปลาหายากในกล่องข้อความ สคริปต์จะหาตำแหน่งจริงทุกครั้ง
     - ถ้ารอแล้วกล่องไม่โผล่ (รอบนั้นไม่มีปลาหายาก) จะข้าม ไม่คลิกมั่ว
     - ถ้าคลิกแล้วปุ่มยังอยู่ จะคลิกซ้ำให้

วิธีหาปุ่มที่เบาเครื่องที่สุด
  - จับภาพเฉพาะกรอบเล็กๆ ที่กำหนด (ไม่จับทั้งจอ) ด้วย GDI ของ Windows
  - หน่วยความจำรับภาพสร้างครั้งเดียวแล้วใช้ซ้ำ
  - หาสีฟ้าด้วย regex ซึ่งทำงานในภาษา C จึงเร็วกว่าวนลูปทีละพิกเซลมาก (ราว 3 ms ต่อภาพ)
  - จับภาพเฉพาะตอนรอปุ่มเท่านั้น ช่วงอื่นไม่ใช้ CPU เลย
  - ไม่ต้องลง numpy / opencv / pyautogui ใช้แค่ Python ล้วน

วิธีใช้
  python auto_clicker.py           -> เริ่มทำงาน
  python auto_clicker.py --pos     -> ดูพิกัดเมาส์ (ไว้หาค่า X, Y)
  python auto_clicker.py --detect  -> ทดสอบว่าหาปุ่มเจอไหม (ไม่คลิก)
  กด [SPACEBAR] เพื่อหยุดฉุกเฉินได้ตลอดเวลา
====================================================================
"""

import ctypes
import os
import re
import struct
import subprocess
import sys
import time

if sys.platform != "win32":
    sys.exit("สคริปต์นี้ใช้ได้บน Windows เท่านั้น")

from ctypes import wintypes

# ============================ ตั้งค่าตรงนี้ ============================

# ขั้นตอนที่ทำในแต่ละรอบ (เรียงตามลำดับ)
#   คลิกพิกัดตายตัว:  {"name": "...", "x": 100, "y": 200}
#   หาปุ่มสีฟ้าแล้วคลิก: {"name": "...", "find_in": (x1, y1, x2, y2), "wait": 3.0}
#                      ใส่ "fallback": (x, y) ถ้าอยากให้คลิกจุดนี้แทนเมื่อหาไม่เจอ
#   กดคีย์บอร์ด:       {"name": "...", "key": "enter"}  หรือคีย์ผสม "ctrl+s"
STEPS = [
    {"name": "จุดที่ 1", "x": 721,  "y": 869},
    {"name": "จุดที่ 2", "x": 1397, "y": 867},
    {"name": "ปุ่มขายเลย", "find_in": (1568, 60, 1909, 311), "wait": 3.0},
]

# ---- การหาปุ่มสีฟ้า ----
# สีปุ่ม "ขายเลย" ในเกมคือ RGB(10, 132, 255) ช่วงด้านล่างเผื่อสีเปลี่ยนตอนเอาเมาส์ชี้
BLUE_R_MAX = 80
BLUE_G_MIN, BLUE_G_MAX = 90, 190
BLUE_B_MIN = 200
BUTTON_MIN_W = 40      # ปุ่มจริงกว้าง ~63 px
BUTTON_MIN_H = 15      # ปุ่มจริงสูง ~30 px (แถบเวลาสีฟ้าใต้ปุ่มสูงแค่ 3 px จึงถูกตัดทิ้ง)
SCAN_ROW_STEP = 2      # ตรวจทุกๆ 2 แถว (ประหยัดเครื่องลงครึ่งหนึ่ง ยังแม่นพอ)
FIND_POLL = 0.08       # จับภาพทุกๆ กี่วินาทีระหว่างรอปุ่ม
CLICK_RETRY = 2        # คลิกแล้วปุ่มยังอยู่ ให้คลิกซ้ำได้อีกกี่ครั้ง

# ---- การเลื่อนเมาส์ / จังหวะ ----
# "absolute" = แอป/เกมทั่วไป (แนะนำ) | "relative" = เกมที่รับแค่การขยับแบบเมาส์จริง
MOVE_MODE = "absolute"
START_FROM_CENTER = True     # เลื่อนกลับกลางจอก่อนเริ่มทุกรอบ
MOVE_DURATION = 0.35         # เวลาที่ใช้เลื่อนเมาส์ไปแต่ละจุด (วินาที)
MOVE_STEPS = 30              # จำนวนสเต็ปย่อยตอนเลื่อน (มาก = สมูทขึ้น)
HOVER_BEFORE_CLICK = 0.10    # พักให้ปุ่มรับรู้ hover ก่อนคลิก
CLICK_HOLD = 0.06            # กดค้างเมาส์กี่วินาที
KEY_HOLD = 0.05              # กดค้างคีย์บอร์ดกี่วินาที
DELAY_BETWEEN_STEPS = 1.0    # ดีเลย์ระหว่างแต่ละขั้นตอน
DELAY_BETWEEN_LOOPS = 10 * 60  # ดีเลย์ก่อนเริ่มรอบใหม่ (10 นาที)
AUTO_RUN_AS_ADMIN = True     # ขอสิทธิ์ Admin อัตโนมัติถ้ายังไม่มี
STOP_KEY = 0x20              # ปุ่มหยุดฉุกเฉิน (0x20 = Spacebar, 0x77 = F8, 0x1B = Esc)
CLICK_SOUND = True

# =====================================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.argv[0] or __file__))

# DPI Awareness (ต้องตั้งก่อนอ่านขนาดจอ/พิกัด ไม่งั้นพิกัดเพี้ยนเมื่อจอ scale ไม่ใช่ 100%)
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
shell32 = ctypes.windll.shell32

# ---------- ค่าคงที่ของ Windows ----------
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_MOVE_NOCOALESCE = 0x2000   # ไม่ให้ Windows รวบ event การเลื่อน (สมูทจริง ไม่วาป)
MOUSEEVENTF_VIRTUALDESK = 0x4000       # ใช้พิกัดครอบคลุมทุกจอ
MOUSEEVENTF_ABSOLUTE = 0x8000

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

SM_CXSCREEN, SM_CYSCREEN = 0, 1
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79

SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
BI_RGB = 0

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


# ---------- โครงสร้าง INPUT (ต้องมีครบทั้ง 3 แบบ ขนาดจึงถูกต้อง) ----------
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


# ---------- โครงสร้างภาพสำหรับจับหน้าจอ ----------
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


# ---------- กำหนด signature ให้ฟังก์ชัน Win32 (กันค่า handle ถูกตัดบน 64-bit) ----------
user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT
user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
user32.GetCursorPos.restype = wintypes.BOOL
user32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
user32.GetSystemMetrics.argtypes = (ctypes.c_int,)
user32.GetSystemMetrics.restype = ctypes.c_int
user32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
user32.MapVirtualKeyW.restype = wintypes.UINT
user32.GetDC.argtypes = (wintypes.HWND,)
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
user32.ReleaseDC.restype = ctypes.c_int

gdi32.CreateCompatibleDC.argtypes = (wintypes.HDC,)
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateDIBSection.argtypes = (wintypes.HDC, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
                                   ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD)
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = (wintypes.HDC, wintypes.HGDIOBJ)
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.BitBlt.argtypes = (wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD)
gdi32.BitBlt.restype = wintypes.BOOL
gdi32.GdiFlush.argtypes = ()
gdi32.GdiFlush.restype = wintypes.BOOL
gdi32.DeleteObject.argtypes = (wintypes.HGDIOBJ,)
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.DeleteDC.argtypes = (wintypes.HDC,)
gdi32.DeleteDC.restype = wintypes.BOOL

shell32.ShellExecuteW.argtypes = (wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                  wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int)
shell32.ShellExecuteW.restype = ctypes.c_void_p


class StopRequested(Exception):
    """ถูกสั่งหยุดฉุกเฉิน"""


# ============================ ฟังก์ชันพื้นฐาน ============================

def stop_pressed():
    return (user32.GetAsyncKeyState(STOP_KEY) & 0x8000) != 0


def check_stop():
    if stop_pressed():
        raise StopRequested()


def emergency_sleep(duration):
    """หน่วงเวลาแบบเช็กปุ่มหยุดตลอด"""
    end = time.perf_counter() + duration
    while time.perf_counter() < end:
        check_stop()
        time.sleep(min(0.02, max(0.0, end - time.perf_counter())))


def get_cursor_pos():
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def get_screen_center():
    return user32.GetSystemMetrics(SM_CXSCREEN) // 2, user32.GetSystemMetrics(SM_CYSCREEN) // 2


def virtual_screen():
    """ขอบเขตจอทั้งหมด (รวมหลายจอ) -> (left, top, width, height)"""
    return (
        user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
        max(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN), 1),
        max(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN), 1),
    )


_input_warned = False


def send_inputs(*inputs):
    """ส่ง input เข้า Windows ผ่าน SendInput"""
    global _input_warned
    arr = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    if sent != len(inputs) and not _input_warned:
        _input_warned = True
        print(f"  ⚠️ Windows ปฏิเสธ input (error {ctypes.get_last_error()}) "
              f"ลองรันสคริปต์แบบ Administrator")
    return sent


# ============================ เมาส์ ============================

def _mouse(dx, dy, flags):
    inp = INPUT(type=INPUT_MOUSE)
    inp.mi = MOUSEINPUT(dx, dy, 0, flags, 0, 0)
    return inp


def to_absolute(x, y):
    """แปลงพิกัดพิกเซลเป็นสเกล 0-65535 ที่ SendInput ใช้ (เล็งกลางพิกเซลให้ตรงเป๊ะ)"""
    vx, vy, vw, vh = virtual_screen()
    ax = int((x - vx + 0.5) * 65536 / vw)
    ay = int((y - vy + 0.5) * 65536 / vh)
    return min(max(ax, 0), 65535), min(max(ay, 0), 65535)


def move_absolute(x, y):
    ax, ay = to_absolute(x, y)
    send_inputs(_mouse(ax, ay, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
                       | MOUSEEVENTF_VIRTUALDESK | MOUSEEVENTF_MOVE_NOCOALESCE))


def move_relative(dx, dy):
    send_inputs(_mouse(dx, dy, MOUSEEVENTF_MOVE | MOUSEEVENTF_MOVE_NOCOALESCE))


def _move_one(x, y):
    if MOVE_MODE == "relative":
        # ส่งเป็น "ระยะขยับ" จากตำแหน่งจริงตอนนี้ ถ้า pointer acceleration ทำให้เกิน/ขาด
        # สเต็ปถัดไปจะชดเชยให้เอง
        px, py = get_cursor_pos()
        if x != px or y != py:
            move_relative(x - px, y - py)
    else:
        move_absolute(x, y)


def ease_in_out(t):
    """เร่งตอนออกตัว ผ่อนตอนใกล้ถึง เหมือนมือคนเลื่อนเมาส์"""
    return t * t * (3 - 2 * t)


def smooth_move_to(tx, ty, duration=MOVE_DURATION, steps=MOVE_STEPS):
    """เลื่อนเมาส์แบบสมูทด้วย SendInput (มี event การเลื่อนทุกสเต็ป ไม่วาป)"""
    sx, sy = get_cursor_pos()
    step_delay = duration / steps
    for s in range(1, steps + 1):
        check_stop()
        e = ease_in_out(s / steps)
        _move_one(round(sx + (tx - sx) * e), round(sy + (ty - sy) * e))
        time.sleep(step_delay)

    # แก้ตำแหน่งสุดท้ายให้ตรงเป๊ะ
    for _ in range(5):
        if get_cursor_pos() == (tx, ty):
            return
        _move_one(tx, ty)
        time.sleep(0.01)
    if get_cursor_pos() != (tx, ty):
        user32.SetCursorPos(tx, ty)  # ทางสุดท้าย ถ้ายังคลาดอยู่


def click():
    """คลิกซ้ายด้วย SendInput (กดค้างแป๊บหนึ่งเหมือนนิ้วจริง)"""
    send_inputs(_mouse(0, 0, MOUSEEVENTF_LEFTDOWN))
    time.sleep(CLICK_HOLD)
    send_inputs(_mouse(0, 0, MOUSEEVENTF_LEFTUP))
    if CLICK_SOUND:
        try:
            import winsound
            winsound.Beep(1300, 40)
        except Exception:
            pass


def move_and_click(name, x, y):
    print(f"  [~] เลื่อนไป {name} -> ({x}, {y})...")
    smooth_move_to(x, y)
    time.sleep(HOVER_BEFORE_CLICK)
    check_stop()
    click()
    px, py = get_cursor_pos()
    note = "" if (px, py) == (x, y) else f"  (แต่เมาส์อยู่ที่ {px}, {py})"
    print(f"  [✓] คลิก {name} เรียบร้อย!{note}")


# ============================ คีย์บอร์ด ============================

KEY_NAMES = {
    "enter": 0x0D, "esc": 0x1B, "space": 0x20, "tab": 0x09, "backspace": 0x08,
    "shift": 0x10, "ctrl": 0x11, "alt": 0x12,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22,
}
KEY_NAMES.update({f"f{i}": 0x6F + i for i in range(1, 13)})  # F1 = 0x70

# ปุ่มที่ต้องติดธง "extended" ตอนส่งเป็น scan code
EXTENDED_VK = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E}


def vk_from_name(name):
    key = str(name).strip().lower()
    if key in KEY_NAMES:
        return KEY_NAMES[key]
    if len(key) == 1 and key.isascii() and key.isalnum():
        return ord(key.upper())
    raise ValueError(f"ไม่รู้จักชื่อปุ่ม '{name}' (ใช้ได้: a-z, 0-9, {', '.join(KEY_NAMES)})")


def _key_input(vk, release):
    """สร้าง event คีย์บอร์ด ส่งเป็น Scan Code (เกมที่ใช้ DirectInput อ่านค่านี้)"""
    scan = user32.MapVirtualKeyW(vk, 0)  # MAPVK_VK_TO_VSC
    inp = INPUT(type=INPUT_KEYBOARD)
    if scan:
        flags = KEYEVENTF_SCANCODE | (KEYEVENTF_EXTENDEDKEY if vk in EXTENDED_VK else 0)
        inp.ki = KEYBDINPUT(0, scan, flags | (KEYEVENTF_KEYUP if release else 0), 0, 0)
    else:
        inp.ki = KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP if release else 0, 0, 0)
    return inp


def press_key(combo, hold=KEY_HOLD):
    """กดปุ่มหรือคีย์ผสม เช่น "enter", "e", "ctrl+s" """
    vks = [vk_from_name(part) for part in str(combo).split("+") if part.strip()]
    try:
        for vk in vks:
            send_inputs(_key_input(vk, release=False))
            time.sleep(0.01)
        time.sleep(hold)
    finally:
        for vk in reversed(vks):  # ปล่อยปุ่มเสมอ กันปุ่มค้าง
            send_inputs(_key_input(vk, release=True))


# ============================ หาปุ่มสีฟ้าบนจอ ============================

# รูปแบบ 1 พิกเซลสีฟ้า (ข้อมูลภาพเรียงเป็น B, G, R, A ช่องละ 1 ไบต์)
_BLUE_PIXEL = b"[\\x%02x-\\xff][\\x%02x-\\x%02x][\\x00-\\x%02x]." % (
    BLUE_B_MIN, BLUE_G_MIN, BLUE_G_MAX, BLUE_R_MAX)
# สีฟ้าติดกันอย่างน้อย 4 พิกเซลในแถวเดียวกัน
_BLUE_RUN = re.compile(b"(?:" + _BLUE_PIXEL + b"){4,}", re.DOTALL)


def find_blue_button(pixels, w, h, row_step=SCAN_ROW_STEP):
    """
    หาก้อนสีฟ้าที่ใหญ่พอจะเป็นปุ่มในภาพ (ข้อมูล BGRA เรียงแถวจากบนลงล่าง)
    คืนค่า (กลาง x, กลาง y, กว้าง, สูง) เทียบมุมซ้ายบนของภาพ หรือ None ถ้าไม่เจอ
    """
    stride = w * 4
    blobs = []  # แต่ละก้อน: [แถวบน, แถวล่าง, ซ้าย, ขวา, จำนวนพิกเซล]
    for y in range(0, h, row_step):
        row = y * stride
        end = row + stride
        pos = row
        while True:
            m = _BLUE_RUN.search(pixels, pos, end)
            if m is None:
                break
            off = m.start() - row
            if off % 4:  # เจอแบบเหลื่อมขอบพิกเซล ไม่ใช่ของจริง เลื่อนไปพิกเซลถัดไป
                pos = row + (off // 4 + 1) * 4
                continue
            x0 = off // 4
            x1 = (m.end() - row) // 4 - 1
            for b in blobs:  # ต่อกับก้อนเดิมที่อยู่ติดกันด้านบน
                if y - b[1] <= row_step * 2 and x0 <= b[3] + 2 and x1 >= b[2] - 2:
                    b[1] = y
                    b[2] = min(b[2], x0)
                    b[3] = max(b[3], x1)
                    b[4] += x1 - x0 + 1
                    break
            else:
                blobs.append([y, y, x0, x1, x1 - x0 + 1])
            pos = m.end()

    best = None
    for top, bottom, left, right, count in blobs:
        bw, bh = right - left + 1, bottom - top + 1
        fill = count * row_step / (bw * bh)  # ต้องทึบพอ (ปุ่มเป็นสี่เหลี่ยมเต็มๆ)
        if bw >= BUTTON_MIN_W and bh >= BUTTON_MIN_H and fill >= 0.5:
            if best is None or count > best[0]:
                best = (count, (left + right) // 2, (top + bottom) // 2, bw, bh)
    return None if best is None else best[1:]


class ScreenRegion:
    """
    จับภาพหน้าจอเฉพาะกรอบที่กำหนด
    สร้างหน่วยความจำรับภาพครั้งเดียวแล้วใช้ซ้ำ แต่ละครั้งแค่ก๊อปพิกเซลในกรอบมา
    """

    def __init__(self, x1, y1, x2, y2):
        self.left, self.top = min(x1, x2), min(y1, y2)
        self.w = abs(x2 - x1) + 1
        self.h = abs(y2 - y1) + 1
        self.size = self.w * self.h * 4

        bmi = BITMAPINFO()
        hdr = bmi.bmiHeader
        hdr.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        hdr.biWidth = self.w
        hdr.biHeight = -self.h  # ติดลบ = แถวบนสุดมาก่อน
        hdr.biPlanes = 1
        hdr.biBitCount = 32
        hdr.biCompression = BI_RGB

        self.bits = ctypes.c_void_p()
        screen = user32.GetDC(None)
        try:
            self.mem_dc = gdi32.CreateCompatibleDC(screen)
            self.bmp = gdi32.CreateDIBSection(screen, ctypes.byref(bmi), DIB_RGB_COLORS,
                                              ctypes.byref(self.bits), None, 0)
        finally:
            user32.ReleaseDC(None, screen)
        if not self.mem_dc or not self.bmp or not self.bits.value:
            raise OSError("สร้างหน่วยความจำจับภาพหน้าจอไม่สำเร็จ")
        self.old = gdi32.SelectObject(self.mem_dc, self.bmp)

    def grab(self):
        """คืนพิกเซลในกรอบ (BGRA) หรือ None ถ้าจับภาพไม่ได้ (เช่น ตอนหน้าจอ UAC ขึ้น)"""
        screen = user32.GetDC(None)
        try:
            ok = gdi32.BitBlt(self.mem_dc, 0, 0, self.w, self.h,
                              screen, self.left, self.top, SRCCOPY)
        finally:
            user32.ReleaseDC(None, screen)
        if not ok:
            return None
        gdi32.GdiFlush()
        return ctypes.string_at(self.bits.value, self.size)

    def find(self):
        """จับภาพแล้วหาปุ่ม คืน (x, y) บนจอ หรือ None"""
        pixels = self.grab()
        if pixels is None:
            return None
        found = find_blue_button(pixels, self.w, self.h)
        if found is None:
            return None
        return self.left + found[0], self.top + found[1]

    def close(self):
        if self.mem_dc:
            gdi32.SelectObject(self.mem_dc, self.old)
            gdi32.DeleteObject(self.bmp)
            gdi32.DeleteDC(self.mem_dc)
            self.mem_dc = None


_regions = {}


def get_region(rect):
    """ใช้กรอบจับภาพเดิมซ้ำ ไม่สร้างใหม่ทุกครั้ง"""
    key = tuple(rect)
    if key not in _regions:
        _regions[key] = ScreenRegion(*key)
    return _regions[key]


def close_regions():
    for region in _regions.values():
        region.close()
    _regions.clear()


def _near(a, b, tol=3):
    return a is not None and b is not None and abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def wait_for_button(region, timeout):
    """
    รอจนเจอปุ่มที่ "นิ่งแล้ว" (เจอที่เดิม 2 ครั้งติด กันคลิกตอนกล่องกำลังเลื่อนเข้ามา)
    คืนพิกัด (x, y) บนจอ หรือ None ถ้าหมดเวลา
    """
    end = time.perf_counter() + timeout
    last = None
    while True:
        check_stop()
        pos = region.find()
        if pos is not None and _near(pos, last):
            return pos
        last = pos
        if time.perf_counter() >= end:
            return last
        time.sleep(FIND_POLL)


def save_bmp(path, pixels, w, h):
    """บันทึกภาพ BGRA เป็นไฟล์ .bmp 24-bit (ไว้เช็กว่าสคริปต์มองเห็นอะไร)"""
    row_bytes = w * 3
    pad = (4 - row_bytes % 4) % 4
    data = bytearray()
    for y in range(h - 1, -1, -1):  # BMP เก็บแถวล่างขึ้นบน
        src = pixels[y * w * 4:(y + 1) * w * 4]
        line = bytearray(row_bytes)
        line[0::3] = src[0::4]
        line[1::3] = src[1::4]
        line[2::3] = src[2::4]
        data += line + b"\x00" * pad
    header = struct.pack("<2sIHHI", b"BM", 54 + len(data), 0, 0, 54)
    info = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, len(data), 2835, 2835, 0, 0)
    with open(path, "wb") as f:
        f.write(header + info + data)


# ============================ สิทธิ์ Admin ============================

def is_admin():
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin():
    """เปิดสคริปต์นี้ใหม่แบบ Administrator (จะมีหน้าต่าง UAC ถามยืนยัน)"""
    if getattr(sys, "frozen", False):
        args = sys.argv[1:]
    else:
        args = [os.path.abspath(sys.argv[0])] + sys.argv[1:]
    params = subprocess.list2cmdline(args + ["--elevated"])
    ret = shell32.ShellExecuteW(None, "runas", sys.executable, params, SCRIPT_DIR, 1)
    return (ret or 0) > 32


# ============================ โหมดทดสอบ ============================

def show_position_mode():
    print("โหมดดูพิกัด: เลื่อนเมาส์ไปที่ปุ่มที่ต้องการ แล้วจดค่า X, Y ไปใส่ใน STEPS")
    print("(พิกัดนี้ตรงกับที่สคริปต์ใช้คลิกแน่นอน แม้จอจะตั้ง scale 125%/150%)")
    print("กด SPACEBAR หรือ Ctrl+C เพื่อออก\n")
    last = None
    try:
        while not stop_pressed():
            pos = get_cursor_pos()
            if pos != last:
                print(f"\r  X = {pos[0]:5d}, Y = {pos[1]:5d}    ", end="", flush=True)
                last = pos
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    print()


def detect_mode():
    """ทดสอบการหาปุ่มสีฟ้าแบบไม่คลิก"""
    find_steps = [s for s in STEPS if "find_in" in s]
    if not find_steps:
        print("ไม่มีขั้นตอนแบบ find_in ใน STEPS")
        return
    step = find_steps[0]
    region = get_region(step["find_in"])
    bmp_path = os.path.join(SCRIPT_DIR, "detect_region.bmp")
    print(f"โหมดทดสอบ: หา {step['name']} ในกรอบ ({region.left}, {region.top}) "
          f"ขนาด {region.w}x{region.h} (ไม่คลิก)")
    print("เปิดเกมให้กล่องยืนยันขึ้นมา แล้วดูผลด้านล่าง")
    print(f"ภาพที่สคริปต์มองเห็นจะถูกบันทึกที่ {bmp_path} ทุกครั้งที่ผลเปลี่ยน")
    print("กด SPACEBAR หรือ Ctrl+C เพื่อออก\n")
    last_state = object()
    try:
        while not stop_pressed():
            t0 = time.perf_counter()
            pixels = region.grab()
            found = find_blue_button(pixels, region.w, region.h) if pixels else None
            ms = (time.perf_counter() - t0) * 1000
            if found:
                x, y = region.left + found[0], region.top + found[1]
                state = f"เจอปุ่มที่ X = {x}, Y = {y} (ขนาด {found[2]}x{found[3]})"
            elif pixels is None:
                state = "จับภาพไม่ได้"
            else:
                state = "ไม่เจอปุ่ม"
            print(f"\r  {state}  [{ms:.1f} ms]          ", end="", flush=True)
            if state != last_state and pixels:
                save_bmp(bmp_path, pixels, region.w, region.h)
                last_state = state
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    print()


# ============================ การทำงานหลัก ============================

def run_find_step(step):
    region = get_region(step["find_in"])
    wait = step.get("wait", 3.0)
    name = step["name"]
    print(f"  [🔍] กำลังหา {name} (รอสูงสุด {wait} วินาที)...")
    pos = wait_for_button(region, wait)

    if pos is None:
        fallback = step.get("fallback")
        if fallback is None:
            print(f"  [-] ไม่เจอ {name} ข้ามขั้นตอนนี้")
            return
        print(f"  [!] ไม่เจอ {name} ใช้พิกัดสำรอง {tuple(fallback)}")
        move_and_click(name, *fallback)
        return

    print(f"  [✓] เจอ {name} ที่ ({pos[0]}, {pos[1]})")
    move_and_click(name, *pos)

    # เช็กว่ากดติดไหม ถ้าปุ่มยังอยู่ที่เดิมให้กดซ้ำ
    for attempt in range(1, CLICK_RETRY + 1):
        emergency_sleep(0.5)
        again = wait_for_button(region, 0.2)
        if not _near(again, pos, tol=6):
            return
        print(f"  [↻] ปุ่มยังอยู่ กดซ้ำครั้งที่ {attempt}")
        pos = again
        move_and_click(name, *pos)


def run_step(step):
    if "key" in step:
        print(f"  [⌨] กด {step['key']} ({step['name']})")
        press_key(step["key"])
    elif "find_in" in step:
        run_find_step(step)
    else:
        move_and_click(step["name"], step["x"], step["y"])


def validate_steps():
    vx, vy, vw, vh = virtual_screen()

    def on_screen(x, y):
        return vx <= x < vx + vw and vy <= y < vy + vh

    for step in STEPS:
        if "key" in step:
            for part in str(step["key"]).split("+"):
                if part.strip() and vk_from_name(part) == STOP_KEY:
                    print(f"⚠️ {step['name']}: ปุ่มนี้ซ้ำกับปุ่มหยุดฉุกเฉิน สคริปต์จะหยุดตัวเอง")
        elif "find_in" in step:
            x1, y1, x2, y2 = step["find_in"]
            if not (on_screen(x1, y1) and on_screen(x2, y2)):
                print(f"⚠️ {step['name']}: กรอบค้นหาเลยขอบจอ")
            if abs(x2 - x1) + 1 < BUTTON_MIN_W or abs(y2 - y1) + 1 < BUTTON_MIN_H:
                print(f"⚠️ {step['name']}: กรอบค้นหาเล็กกว่าขนาดปุ่ม จะหาไม่เจอ")
        elif not on_screen(step["x"], step["y"]):
            print(f"⚠️ {step['name']} ({step['x']}, {step['y']}) อยู่นอกจอ")


def describe_step(step):
    if "key" in step:
        return f"กดปุ่ม {step['key']}"
    if "find_in" in step:
        x1, y1, x2, y2 = step["find_in"]
        return (f"หาปุ่มสีฟ้าในกรอบ X {min(x1, x2)}-{max(x1, x2)}, "
                f"Y {min(y1, y2)}-{max(y1, y2)} แล้วคลิก")
    return f"คลิก X = {step['x']}, Y = {step['y']}"


def main():
    if "--pos" in sys.argv:
        show_position_mode()
        return
    if "--detect" in sys.argv:
        detect_mode()
        return

    if not is_admin():
        if AUTO_RUN_AS_ADMIN and "--elevated" not in sys.argv:
            print("กำลังขอสิทธิ์ Administrator (กด Yes ในหน้าต่าง UAC)...")
            if relaunch_as_admin():
                return  # หน้าต่างใหม่แบบ Admin จะทำงานต่อเอง
        print("⚠️ ไม่ได้รันแบบ Administrator: ถ้าโปรแกรม/เกมเป้าหมายรันแบบ Admin "
              "Windows จะบล็อกการคลิกทั้งหมด\n")

    validate_steps()
    center_x, center_y = get_screen_center()

    print("=" * 65)
    print("    โปรแกรมคลิกอัตโนมัติ v3 (SendInput + หาปุ่มสีฟ้าอัตโนมัติ)")
    print("=" * 65)
    print(f"โหมดเลื่อนเมาส์   : {MOVE_MODE}")
    print(f"สิทธิ์ Admin       : {'มี' if is_admin() else 'ไม่มี'}")
    if START_FROM_CENTER:
        print(f"จุดเริ่มต้น (กลางจอ): ({center_x}, {center_y})")
    print("ลำดับขั้นตอน:")
    for step in STEPS:
        print(f"  • {step['name']}: {describe_step(step)}")
    print(f"ดีเลย์ระหว่างขั้นตอน : {DELAY_BETWEEN_STEPS} วินาที")
    print(f"วนลูปทุกๆ          : {DELAY_BETWEEN_LOOPS / 60:g} นาที")
    print("-" * 65)
    print(">>> กดปุ่ม [ SPACEBAR ] ได้ทุกเมื่อเพื่อ 'หยุดฉุกเฉินทันที' <<<")
    print("=" * 65)

    # ทำให้ time.sleep ละเอียดขึ้น (การเลื่อนเมาส์สมูทขึ้นบน Python รุ่นเก่า)
    winmm = None
    try:
        winmm = ctypes.WinDLL("winmm")
        winmm.timeBeginPeriod(1)
    except Exception:
        winmm = None

    user32.GetAsyncKeyState(STOP_KEY)  # เคลียร์สถานะปุ่มค้าง
    loop_count = 1
    try:
        print("\nเตรียมพร้อม... สลับไปหน้าต่างเป้าหมายได้เลย")
        for i in range(3, 0, -1):
            print(f"เริ่มใน {i}...")
            emergency_sleep(1.0)

        print("\n>>> เริ่มต้นวนลูป (กด SPACEBAR เพื่อหยุด) <<<\n")
        while True:
            print(f"--- [รอบที่ {loop_count}] ---")
            if START_FROM_CENTER:
                print(f"  [>] เลื่อนไปกลางจอ ({center_x}, {center_y})...")
                smooth_move_to(center_x, center_y, duration=0.3)
                time.sleep(0.1)

            for i, step in enumerate(STEPS):
                check_stop()
                run_step(step)
                if i < len(STEPS) - 1:
                    emergency_sleep(DELAY_BETWEEN_STEPS)

            next_at = time.strftime("%H:%M:%S", time.localtime(time.time() + DELAY_BETWEEN_LOOPS))
            print(f"\nจบรอบที่ {loop_count} -> รอ {DELAY_BETWEEN_LOOPS / 60:g} นาที "
                  f"(รอบใหม่เริ่มเวลา {next_at})...\n")
            emergency_sleep(DELAY_BETWEEN_LOOPS)
            loop_count += 1

    except StopRequested:
        print("\n⚠️ ตรวจพบการกด SPACEBAR! หยุดฉุกเฉินทันที")
    except KeyboardInterrupt:
        print("\nหยุดการทำงานโดยผู้ใช้ (Ctrl+C)")
    finally:
        if winmm is not None:
            try:
                winmm.timeEndPeriod(1)
            except Exception:
                pass


if __name__ == "__main__":
    try:
        main()
    finally:
        close_regions()
        # ถ้าเป็นหน้าต่าง Admin ที่เปิดใหม่ ให้ค้างไว้ก่อน จะได้อ่านผลทัน
        if "--elevated" in sys.argv:
            try:
                input("\nกด Enter เพื่อปิดหน้าต่าง...")
            except (EOFError, KeyboardInterrupt):
                pass