import sys
import time
import pyautogui

def launch(account, character=None):
    # Disable failsafe
    pyautogui.FAILSAFE = False
    
    # Temporarily disable pause for the duration of the typing and entering process
    original_pause = pyautogui.PAUSE
    pyautogui.PAUSE = 0
    
    try:
        # Focus on the EVE Online Launcher window
        eve_launcher_windows = pyautogui.getWindowsWithTitle("EVE Online Launcher")
        if not eve_launcher_windows:
            print("EVE Online Launcher window not found!")
            return

        eve_launcher_windows[0].activate()
        time.sleep(0.2)  # Small delay to ensure the window is focused
        pyautogui.hotkey('ctrl', 'f')
        time.sleep(0.1)  # Small delay for the find command
        if character:
            pyautogui.write(f'play: {character}')
        else:
            pyautogui.write(f'play: {account}')
        pyautogui.press('enter')
    finally:
        # Re-enable failsafe and pause
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = original_pause

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python launch.py <character_name>")
        sys.exit(1)
    
    character_name = sys.argv[1]
    launch(character_name)
