import time
import threading
import pydirectinput
import keyboard

# ('ปุ่ม', ระยะเวลาที่กดค้าง)
ACTIONS = [
    ('w', 1.0), ('e', 3.0), ('s', 0.30),
    ('e', 3.0), ('s', 0.30), ('e', 3.0)
]

stop = threading.Event()

def on_stop(e):
    stop.set()

keyboard.on_press_key('space', on_stop)
keyboard.on_press_key('esc', on_stop)

def run():
    time.sleep(5)
    count = 1
    while not stop.is_set():
        for key, duration in ACTIONS:
            if stop.is_set():
                break
            pydirectinput.keyDown(key)
            time.sleep(duration)
            pydirectinput.keyUp(key)
            time.sleep(0.1)
        
        if not stop.is_set():
            print(f"\rRound: {count}", end="", flush=True)
            count += 1

if __name__ == "__main__":
    try:
        run()
    except:
        pass

#### 19,260 per hour