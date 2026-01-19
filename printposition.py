from pynput.mouse import Listener
import pyautogui

def on_click(x, y, button, pressed):
    """
    Callback function when mouse is clicked
    """
    if pressed:
        current_x, current_y = pyautogui.position()
        print(f"Mouse Clicked at: X={current_x}, Y={current_y}")

def print_position():
    """
    Print mouse position every time user clicks
    """
    print("Listening for mouse clicks. Press Ctrl+C to stop.")
    with Listener(on_click=on_click) as listener:
        listener.join()

if __name__ == "__main__":
    try:
        print_position()
    except KeyboardInterrupt:
        print("\nStopped listening for mouse clicks.")
