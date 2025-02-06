from pyautogui import screenshot as pyautogui_screenshot
from pyautogui import press as pyautogui_press
from pyautogui import locateOnScreen as pyautogui_locateOnScreen
from pyautogui import pixel as pyautogui_pixel
from ultralytics import YOLO
from mss import mss

import threading
import cv2
import numpy as np
import time
import win32gui
import win32api
import datetime
import configparser
import win32con
import os
import requests
from dotenv import load_dotenv
import pyautogui

"""
mode 說明：
0 : keep（保留魚）
1 : sell（賣出魚）
"""

mode = 0  # 預設為 0（keep）

# 載入 .env 檔，主要用於取得 LINE Notify 的 Token
load_dotenv()
NOTIFY_TOKEN = os.getenv('NOTIFY_TOKEN')

activate = False   # 釣魚檢測是否啟動的旗標
counter = 0        # 計數器，記錄捕捉次數
last_catch_time = None  # 上一次捕捉到魚的時間戳

lock = threading.Lock()  # 執行緒鎖，用於保護共享資源（last_catch_time 等）

# 以下設定用於截圖範圍（BlueStacks App Player 2 視窗大小）
right = 960
bot = 540

# 檢查 BlueStacks 是否開啟，並回傳其視窗 HWND
def checkBlueStack():
    try:
        return win32gui.FindWindow(None, 'BlueStacks App Player 2')
    except:
        return False

# 取得 BlueStacks 視窗的 HWND
hwnd = checkBlueStack()

# 若找到 BlueStacks 視窗，調整其位置與大小
if hwnd: 
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOP, 0, 0, right, bot, True)

# 滑鼠座標（每次移動或點擊都會更新）
mouse_x = 0
mouse_y = 0

screen = None
fishing_state = 0 # 釣魚狀態
large_fish = 0

# 選定「釣魚觸發區域」的中心點（透過滑鼠左鍵點擊來設定）
active_mouse_x = 0
active_mouse_y = 0 

# x、y 偏移量，決定會從中心點往上下左右擷取多少區域當作「偵測釣魚」範圍
active_x_offset = 30
active_y_offset = 60

# 配合 cv2.matchTemplate 使用的相似度（敏感度）閾值
sensitive = 0.6

#-------------------------------------------------
# 讀取與寫入組態檔 config.ini，用於紀錄或載入參數
#-------------------------------------------------
configSection= 'config'
config = configparser.ConfigParser()
config.read('config.ini')

# 顯示視窗的名稱
windowName = "Enjoy Fish Bot"

# 釣魚品級顏色（若有需要可透過 pixel 做比對） 待處理
trash = (228, 224, 197)
green = (163, 228, 103)
blue  = (89, 168, 217)
purple = (231, 147, 232)

# 嘗試新增 configSection，若已存在則略過
try:
    config.add_section(configSection)
except configparser.DuplicateSectionError: 
    pass

# 依序載入各項參數（若 config.ini 有紀錄的話）
if config.has_option(configSection, 'active_mouse_x'):
    active_mouse_x = int(config.get(configSection, 'active_mouse_x'))
if config.has_option(configSection, 'active_mouse_y'):
    active_mouse_y = int(config.get(configSection, 'active_mouse_y'))

if config.has_option(configSection, 'mode'):
    mode = int(config.get(configSection, 'mode'))

if config.has_option(configSection, 'x_offset'):
    active_x_offset = int(config.get(configSection, 'x_offset'))

if config.has_option(configSection, 'y_offset'):
    active_y_offset = int(config.get(configSection, 'y_offset'))  

if config.has_option(configSection, 'sensitive'):
    sensitive = float(config.get(configSection, 'sensitive'))


#------------------------------------------------------------------------
model = YOLO('fish_shadow_yolo.pt').to('cuda')  # 將模型移動到 GPU
model.verbose = False  # 關閉模型的冗長輸出
#------------------------------------------------------------------------

#------------------------------------------------------------------------
# 函式：detectClick()
# 用途：偵測滑鼠左鍵點擊位置，並回傳該座標
#------------------------------------------------------------------------
def detectClick():
    """偵測滑鼠左鍵按下時，回傳其螢幕座標。"""
    state_left = win32api.GetKeyState(0x01)
    print("Select position")
    while True:
        a = win32api.GetKeyState(0x01)
        # 當偵測到左鍵狀態改變，表示有點擊
        if a != state_left:
            state_left = a
            if a < 0:
                print('Complete')
                return win32gui.GetCursorPos()
        time.sleep(0.1)

#------------------------------------------------------------------------
# 函式：detectClick_RGB_value()
# 用途：偵測滑鼠左鍵按下時，回傳其螢幕座標的 RGB 值。
#------------------------------------------------------------------------
def detectClick_RGB_value():
    """偵測滑鼠左鍵按下時，回傳其螢幕座標的 RGB 值。"""
    state_left = win32api.GetKeyState(0x01)  # 紀錄滑鼠左鍵初始狀態
    print("請點擊螢幕上想要獲取顏色的像素位置")
    while True:
        a = win32api.GetKeyState(0x01)
        # 當偵測到左鍵狀態改變，表示有點擊
        if a != state_left:
            state_left = a
            if a < 0:  # 當左鍵按下
                # 獲取滑鼠座標
                mouse_pos = win32gui.GetCursorPos()

                # 獲取該座標的像素 RGB 值
                screenshot = pyautogui.screenshot()
                rgb_value = screenshot.getpixel(mouse_pos)

                print(f"滑鼠座標: {mouse_pos}, RGB 值: {rgb_value}")
                print("完成！")
                return mouse_pos, rgb_value
        time.sleep(0.1)

#------------------------------新增: 抓取浮標位置------------------------------------------
# 函式：Getinput()
# 用途：程式開始時，取得使用者輸入：
#       1. 設定浮標座標
#       2. 設定驚嘆號座標
#------------------------------------------------------------------------
def Getinput():
    print('One time click:')
    detectClick()  # 先偵測一次點擊(若需要)

    print('Select fishing buoy location:')
    pt = detectClick()

    print('select shadow of fish to get the RGB value:')
    _, shadow_rgb = detectClick_RGB_value()

    # print('Select exclamation mark location:')
    # pt1 = detectClick()
    return pt, shadow_rgb #, pt1

# ------------------------ 新增：魚影量測功能 -------------------------
def measure_fish_shadow(image, fish_color_rgb):
    """
    從第一個腳本移植過來的魚影量測核心邏輯。
    進行灰階化、二值化、輪廓偵測，並依照面積大小分級。
    回傳： (cnt, area, size)
       cnt  -> 該輪廓 (或 None)
       area -> 面積大小
       size -> 大小分級 (0 = 未偵測到 / 小於門檻)
               1, 2, 3, 4 表示魚的大小分級，可自行調整
    """

    tolerance_hue = 10  # 色相範圍
    tolerance_sat = 50  # 飽和度範圍
    tolerance_val = 50  # 亮度範圍


    image_copy = image.copy()
    # 將影像從 BGR 轉換到 HSV 空間
    hsv_image = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    # 將魚影顏色從 RGB 轉換到 HSV
    fish_color_bgr = fish_color_rgb[::-1]
    fish_color_hsv = cv2.cvtColor(np.uint8([[fish_color_bgr]]), cv2.COLOR_BGR2HSV)[0][0]

    
    # 設定 HSV 範圍
    lower_bound = np.array([
        max(0, fish_color_hsv[0] - tolerance_hue),
        max(0, fish_color_hsv[1] - tolerance_sat),
        max(0, fish_color_hsv[2] - tolerance_val),
    ])
    upper_bound = np.array([
        min(179, fish_color_hsv[0] + tolerance_hue),  # HSV 色相範圍為 [0, 179]
        min(255, fish_color_hsv[1] + tolerance_sat),
        min(255, fish_color_hsv[2] + tolerance_val),
    ])

    # print(f"HSV 範圍: {lower_bound} - {upper_bound}")

    # 產生遮罩
    mask = cv2.inRange(hsv_image, lower_bound, upper_bound)

    # 找出輪廓
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE) 

    return contours, mask, image_copy
#-------------------------------------------------
# 函式：mouse_event
# 用途：cv2.setMouseCallback 的回呼函式，當滑鼠左鍵放開時，記錄該座標
#-------------------------------------------------
def mouse_event(event, x, y, flags, param):
    global mouse_x 
    global mouse_y
    global active_mouse_x 
    global active_mouse_y

    # 即時更新滑鼠座標，用來在畫面上顯示提示框
    mouse_x = x
    mouse_y = y

    # 當偵測到滑鼠左鍵放開（EVENT_LBUTTONUP），將此位置存為「可用」的偵測範圍中心
    if event == cv2.EVENT_LBUTTONUP:
        active_mouse_x = mouse_x
        active_mouse_y = mouse_y

#-------------------------------------------------
# 函式：textBox
# 用途：在 cv2 視窗底部，顯示文字資訊（如模式、是否啟動等）
#-------------------------------------------------
def textBox(text, y):
    font_scale = 1.8
    font = cv2.FONT_HERSHEY_PLAIN
    rectangle_bgr = (255, 255, 255)  # 白色背景
    # 計算文字大小，決定方框尺寸
    (text_width, text_height) = cv2.getTextSize(text, font, fontScale=font_scale, thickness=1)[0]
    text_offset_x = 5
    text_offset_y = screen.shape[0] - y
    box_coords = (
        (text_offset_x, text_offset_y),
        (text_offset_x + text_width + 2, text_offset_y - text_height - 2)
    )
    # 先畫出白色方塊，再把文字覆蓋上去
    cv2.rectangle(screen, box_coords[0], box_coords[1], rectangle_bgr, cv2.FILLED)
    cv2.putText(screen, text, (text_offset_x, text_offset_y), font, fontScale=font_scale, color=(0, 0, 0), thickness=2)

#-------------------------------------------------
# 函式：line_notify
# 用途：透過 LINE Notify API 發送訊息
#-------------------------------------------------
def line_notify(message):
    global NOTIFY_TOKEN
    url = 'https://notify-api.line.me/api/notify'
    headers = {
        'Authorization': 'Bearer ' + NOTIFY_TOKEN
    }
    data = {
        'message': message
    }
    requests.post(url, headers=headers, data=data)

#-------------------------------------------------
# 函式：fisher
# 用途：主要的影像擷取與釣魚偵測邏輯作動，並在視窗中顯示畫面與資訊
#-------------------------------------------------
def fisher():
    global screen
    global activate
    global hwnd
    global sensitive
    global mode
    global fishing_state
    global large_fish

    # 建立一個顯示畫面 window，並設定回呼函式
    cv2.namedWindow(windowName)
    # 將此視窗移動到顯示器右側，以免擋住 BlueStacks
    cv2.moveWindow(windowName, 0, bot + 30)
    # 隨時抓取視窗內滑鼠的動作
    cv2.setMouseCallback(windowName, mouse_event)

    # with mss() as sct:
    while True:
        # # 截圖 BlueStacks 範圍（0,0） 到 (right, bot)
        screen = pyautogui_screenshot(region=(0, 30, right-35, bot-20))
        # screen = np.array(sct.grab({'top': 30, 'left': 0, 'width': right-35, 'height': bot-20}))
        screen = np.array(screen)
        # screen = cv2.cvtColor(screen, cv2.COLOR_BGRA2BGR)
        screen = cv2.cvtColor(screen, cv2.COLOR_RGB2BGR)

        # 在畫面中畫一個方框，表示目前的滑鼠範圍（尚未正式鎖定）
        cv2.rectangle(
            screen,
            (mouse_x - active_x_offset, mouse_y - active_y_offset),
            (mouse_x + active_x_offset, mouse_y + active_y_offset),
            (255, 255, 255),
            1
        )

        # 顯示模式
        if mode == 0:
            textBox("Mode : keep", 480)
        elif mode == 1:
            textBox("Mode : sell", 480)
        # mode = 2 可能是後續擴充用途
        elif mode == 2:
            textBox("Mode : Big Fish", 480)
        # 顯示目前是否啟動釣魚檢測
        if activate:
            textBox("Active : on", 500)
        else:
            textBox("Active : off", 500)
        # 顯示相似度敏感度
        textBox("sensitive : " + str(sensitive), 460)



        # 若已在畫面中選定釣魚檢測區域 (active_mouse_x > 0)
        if active_mouse_x > 0:
        # 使用 mss 抓取模板區域
            # template_area = np.array(sct.grab({
            #     'top': active_mouse_y - active_y_offset,
            #     'left': active_mouse_x - active_x_offset,
            #     'width': active_x_offset * 2,
            #     'height': active_y_offset * 2
            # }))
            # template_area = cv2.cvtColor(template_area, cv2.COLOR_BGRA2GRAY)  # 注意 BGRA -> GRAY

            template_area = pyautogui_screenshot(region=(
                active_mouse_x - active_x_offset,
                active_mouse_y - active_y_offset,
                active_x_offset * 2,
                active_y_offset * 2
            ))
            template_area = np.array(template_area)
            template_area = cv2.cvtColor(template_area, cv2.COLOR_BGR2GRAY)

            # 在主畫面上以紅框標示偵測區域
            cv2.rectangle(
                screen, 
                (active_mouse_x - active_x_offset, active_mouse_y - active_y_offset),
                (active_mouse_x + active_x_offset, active_mouse_y + active_y_offset),
                (0, 0, 153),
                3
            )
                    
            # 若開啟啟動旗標，開始進行釣魚判斷
            if activate:

                # 待處理 : 訓練模型辨識驚嘆號
                # 載入白天、夜晚兩種模板，用於比對是否該按下 'c'
                day_image = cv2.imread(os.path.join(os.getcwd(), "img", "day_gray.png"))
                night_image = cv2.imread(os.path.join(os.getcwd(), "img", "knight_gray.png"))

                day_template = cv2.cvtColor(day_image, cv2.COLOR_BGR2GRAY)
                night_template = cv2.cvtColor(night_image, cv2.COLOR_BGR2GRAY)

                # matchTemplate 比對
                result_day = cv2.matchTemplate(template_area, day_template, cv2.TM_CCOEFF_NORMED)
                result_night = cv2.matchTemplate(template_area, night_template, cv2.TM_CCOEFF_NORMED)

                _, max_day, _, maxloc = cv2.minMaxLoc(result_day)
                _, max_night, _, maxloc = cv2.minMaxLoc(result_night)

                def reeling_up():
                    global fishing_state

                    """執行釣魚收線的動作。"""
                    if max_day >= sensitive:
                        pyautogui_press('c')
                        fishing_state = 0
                        print("day catch", datetime.datetime.now(), "---", max_day)
                        time.sleep(1)
                    
                    if max_night >= sensitive:
                        pyautogui_press('c')
                        fishing_state = 0
                        print("night catch", datetime.datetime.now(), "---", max_night)
                        time.sleep(1)


                # 一般魚跟大魚尺寸判斷
                # 只拉大魚
                if fishing_state == 1 : 
                    if mode == 2: 
                        results = model(screen, verbose=False)
                        confidence_threshold = 0.85  # 設定信心度閾值
                        
                        # 使用全域變數
                        global fish_buffer
                        if 'fish_buffer' not in globals():
                            fish_buffer = []  # 用於儲存最近幾幀的判斷結果
                        
                        buffer_size = 5  # 緩衝區大小（收集5幀）
                        small_fish_threshold = 0.8  # 小魚判定閾值（超過60%幀數判定為小魚才確認）
                        current_frame_result = None  # 當前幀的判斷結果

                        for result in results:
                            boxes = result.boxes
                            for box in boxes:
                                x1,y1,x2,y2 = box.xyxy[0]
                                x1,y1,x2,y2 = int(x1), int(y1), int(x2), int(y2)

                                cls = int(box.cls[0])
                                conf = float(box.conf[0])
                                
                                if conf >= confidence_threshold:
                                    current_frame_result = cls  # 記錄當前幀的判斷結果
                                    class_name = "Big Fish" if cls == 0 else "Small Fish"
                                    confidence_status = "高信心度"

                                    cv2.rectangle(screen, (x1, y1), (x2, y2), (0,255,0), 2)
                                    
                                    label = f"{class_name}: {conf:.2f} ({confidence_status})"
                                    cv2.putText(screen, label, (x1, y1 - 10), 
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                                    
                                    print(f"檢測到 {class_name}，信心度: {conf:.2f} ({confidence_status})")
                        
                        # 更新緩衝區
                        if current_frame_result is not None:
                            fish_buffer.append(current_frame_result)
                            if len(fish_buffer) > buffer_size:
                                fish_buffer.pop(0)  # 移除最舊的判斷結果
                            
                            # 只有當緩衝區已滿時才進行判斷
                            if len(fish_buffer) == buffer_size:
                                # 計算小魚（cls=1）的比例
                                small_fish_ratio = fish_buffer.count(1) / buffer_size
                                # 計算大魚（cls=0）的比例
                                big_fish_ratio = fish_buffer.count(0) / buffer_size
                                
                                if big_fish_ratio >= small_fish_threshold:
                                    large_fish = 1  # 確認是大魚
                                    fish_buffer.clear()  # 清空緩衝區
                                elif small_fish_ratio >= small_fish_threshold:
                                    large_fish = 2  # 確認是小魚
                                    fish_buffer.clear()  # 清空緩衝區
                                else:
                                    large_fish = 0  # 無法確定
                        
                        if large_fish == 1:
                            reeling_up()
                        elif large_fish == 2:
                            cv2.waitKey(100)
                            pyautogui_press('c')
                            print('Small fish (confirmed by multiple frames)')
                            fishing_state = 0
                            cv2.waitKey(100)
                            continue
                        

                    # 一般情況拉起魚
                    else:
                        # # 如果白天模板的匹配度 >= 敏感度，就按下 'c'（預設對應遊戲內的釣魚指令）
                        # if max_day >= sensitive:
                        #     pyautogui_press('c')
                        #     fishing_state = 0
                        #     print("day catch", datetime.datetime.now(), "---", max_day)
                        #     time.sleep(1)
                        
                        # # 如果夜晚模板的匹配度 >= 敏感度，也按下 'c'
                        # if max_night >= sensitive:
                        #     pyautogui_press('c')
                        #     fishing_state = 0
                        #     print("night catch", datetime.datetime.now(), "---", max_night)
                        #     time.sleep(1)
                        reeling_up()

        # 顯示畫面
        cv2.imshow(windowName, screen)

        # 取得多個快捷鍵（F1~F5、+、-）
        f1_key = win32api.GetAsyncKeyState(0x70)  # F1
        f2_key = win32api.GetAsyncKeyState(0x71)  # F2
        f3_key = win32api.GetAsyncKeyState(0x72)  # F3
        f4_key = win32api.GetAsyncKeyState(0x73)  # F4
        f5_key = win32api.GetAsyncKeyState(0x74)  # F5

        add_key = win32api.GetAsyncKeyState(0x6B)       # 數字鍵盤 '+'
        subtract_key = win32api.GetAsyncKeyState(0x6D)  # 數字鍵盤 '-'
        
        # 按下數字鍵盤 '+'，提高敏感度（每次提高 0.05，上限暫不嚴格限制）
        if add_key and add_key == -32768:
            if sensitive > 0.9:
                pass  # 避免超過 1.0
            else:
                sensitive += 0.05
                sensitive = round(sensitive, 2)

        # 按下數字鍵盤 '-'，降低敏感度（每次降低 0.05，下限暫不嚴格限制）
        if subtract_key and subtract_key == -32768:
            if sensitive < 0.45:
                pass  # 避免太低導致誤偵測
            else:
                sensitive -= 0.05
                sensitive = round(sensitive, 2)

        # F1 切換釣魚偵測 on/off
        if f1_key:
            activate = not activate
            time.sleep(0.5)

        # F2 將 mode 改為 0（keep）
        if f2_key:
            mode = 0
        # F3 將 mode 改為 1（sell）
        if f3_key:
            mode = 1
        # F5 設定為 2，抓大魚模式
        if f5_key:
            mode = 2

        key = cv2.waitKey(1)

        # F4 或是手動關閉視窗時，儲存目前的設定後離開迴圈
        if f4_key or cv2.getWindowProperty(windowName, cv2.WND_PROP_VISIBLE) < 1:
            with open('config.ini', 'w') as configfile:
                config.set(configSection, "active_mouse_x", str(active_mouse_x))
                config.set(configSection, "active_mouse_y", str(active_mouse_y))
                config.set(configSection, "mode", str(mode))
                config.set(configSection, "sensitive", str(sensitive))
                config.write(configfile)
            break

#-------------------------------------------------
# 函式：timeout_checker
# 用途：定期檢查超過兩分鐘是否沒有捕捉到魚，若超過則透過 LINE 通知
#-------------------------------------------------
def timeout_checker():
    global last_catch_time
    while True:
        with lock:
            if last_catch_time is not None:
                elapsed_time = time.time() - last_catch_time
                if elapsed_time > 120:  # 若大於兩分鐘
                    message = f"超過兩分鐘未捕捉到 is_CatchAfter 狀態。已經 {int(elapsed_time)} 秒沒有捕捉到。"
                    line_notify(message)
                    print("Line 通知已發送：", message)
                    # 重置 last_catch_time 以避免重複通知
                    last_catch_time = time.time()
        time.sleep(30)  # 每 30 秒檢查一次

#-------------------------------------------------
# 函式：status_checker
# 用途：偵測釣魚以外的其他狀態（例如主畫面、釣魚完畢後的畫面等），
#       並進行相對應的按鍵操作
#-------------------------------------------------
def status_checker():
    global activate
    global counter
    global last_catch_time
    global fishing_state
    global large_fish

    while True:
        if activate:
            # 每次都檢查 BlueStacks 視窗是否存在，若存在則置頂並前景化
            hwnd = checkBlueStack()
            if hwnd:
                try:
                    win32gui.SetWindowPos(hwnd, win32con.HWND_TOP, 0, 0, right, bot, True)
                    win32gui.SetForegroundWindow(hwnd)
                except Exception as e:
                    print(f"無法設置視窗焦點: {e}")
                    pass  # 忽略錯誤繼續執行
            
            # 以下是透過 pyautogui_locateOnScreen 搜尋指定圖示
            # is_MainScreen 用於偵測是否在「主要釣魚畫面」
            is_MainScreen = pyautogui_locateOnScreen(
                os.path.join(os.getcwd(), "img", "main.png"),
                region=(0, 0, right, bot),
                confidence=0.9
            )
            print(f"主畫面檢測: {is_MainScreen}")

            is_CatchAfter = pyautogui_locateOnScreen(
                os.path.join(os.getcwd(), "img", "catch_after2.png"),
                region=(0, 0, right, bot),
                confidence=0.7
            )
            print(f"釣魚成功提示: {is_CatchAfter}")

            is_Recycle = pyautogui_locateOnScreen(
                os.path.join(os.getcwd(), "img", "recycle2.png"),
                region=(0, 0, right, bot),
                confidence=0.7
            )
            print(f"回收視窗: {is_Recycle}")

            is_Card = pyautogui_locateOnScreen(
                os.path.join(os.getcwd(), "img", "card.png"),
                region=(0, 0, right, bot),
                confidence=0.8
            )
            print(f"卡片介面: {is_Card}")

            is_OpenCard = pyautogui_locateOnScreen(
                os.path.join(os.getcwd(), "img", "open_card.png"),
                region=(0, 0, right, bot),
                confidence=0.7
            )
            print(f"開卡按鈕: {is_OpenCard}")

            is_CardResult = pyautogui_locateOnScreen(
                os.path.join(os.getcwd(), "img", "card_result.png"),
                region=(0, 0, right, bot),
                confidence=0.8
            )
            print(f"卡片結果: {is_CardResult}")

            is_Task = pyautogui_locateOnScreen(
                os.path.join(os.getcwd(), "img", "task.png"),
                region=(0, 0, right, bot),
                confidence=0.7
            )
            print(f"任務提示: {is_Task}")
            

            # print("Check main!")

            # 如果是主畫面
            if is_MainScreen:
                print("Checking mainscreen!")
                # 若出現炫耀圖示（showoff），按下 'n' 鍵關閉
                if pyautogui_locateOnScreen(
                    os.path.join(os.getcwd(), "img", "showoff.png"),
                    region=(0, 0, right, bot),
                    confidence=0.9
                ):
                    print("is_showingoff!")
                    # pyautogui_press('n')
                    time.sleep(0.5)

                # 按下 'f' 釣魚
                pyautogui_press('f')
                print('start fishing')
                fishing_state = 1
                large_fish = 0
                time.sleep(3)

                # 釣魚開始前，可能檢查是否需要修理
                is_Repiar = pyautogui_locateOnScreen(
                    os.path.join(os.getcwd(), "img", "repair2.png"),
                    region=(0, 0, right, bot),
                    confidence=0.7
                )
                if is_Repiar:
                    print("is_Repiar!")
                    pyautogui_press('r')
                    time.sleep(3)
                    pyautogui_press('r')

            # 若偵測到釣魚完成畫面
            if is_CatchAfter:
                counter += 1
                current_time = time.time()

                with lock:
                    if last_catch_time is not None:
                        elapsed_time = current_time - last_catch_time
                    else:
                        elapsed_time = 0
                    last_catch_time = current_time

                print(f"Catch {counter} times! --- Time since last catch: {elapsed_time:.2f} seconds")

                # 依照 mode 做不同處理（0=keep, 1=sell）
                if mode == 0:  # keep
                    pyautogui_press('k')
                    time.sleep(0.1)
                elif mode == 1:  # sell
                    pyautogui_press('p')
                    time.sleep(0.1)
                    pyautogui_press('p')
                    time.sleep(0.1)
                    pyautogui_press('p')
                    time.sleep(0.1)
                    pyautogui_press('r')
                    time.sleep(0.1)
                    pyautogui_press('r')
                    time.sleep(0.1)
                    if pyautogui_locateOnScreen(
                        os.path.join(os.getcwd(), "img", "confirm2sell.png"),
                        region=(0, 0, right, bot),
                        confidence=0.7
                    ):
                        print("confirm to sell")
                        pyautogui_press('p')
                        time.sleep(0.5)
                        pyautogui_press('r')


            # 根據檢測結果執行相應操作
            if is_Recycle:
                print("is_Recycle!")
                pyautogui_press('p')

            if is_Card:
                print("is_card!")
                pyautogui_press('k')
                time.sleep(0.1)

            if is_OpenCard:
                print("open_card!")
                pyautogui_press('o')
                time.sleep(0.1)

            if is_CardResult:
                print("is_card_result!")
                pyautogui_press('y')
                time.sleep(0.1)

            if is_Task:
                print("is_task!")
                pyautogui_press('r')
                time.sleep(0.1)
                # 再次檢查 task 視窗是否存在
                is_TaskStillExists = pyautogui_locateOnScreen(
                    os.path.join(os.getcwd(), "img", "task.png"),
                    region=(0, 0, right, bot),
                    confidence=0.7
                )
                if is_TaskStillExists:
                    line_notify('新任務階段第二次檢查(按r沒用)')
                    pyautogui_press('y')
                    time.sleep(0.1)
            

                


        time.sleep(1)

def measuring(pt_x: int, pt_y: int, fish_color_rgb):
    global bot

    # fish_color_rgb = (66, 176, 195)
    windowName = 'Measuring fish size'
    scale_factor = 2  # 放大倍數
    crop_size = 50    # 擷取範圍大小
    
    # HSV 容差設定
    tolerance_hue = 15  # 色相範圍
    tolerance_sat = 20  # 飽和度範圍
    tolerance_val = 20  # 亮度範圍

    cv2.namedWindow(windowName)
    cv2.moveWindow(windowName, 0, 2*(bot + 30))

    def on_click(x, y, button, pressed):
        nonlocal pt_x, pt_y
        if pressed and button == mouse.Button.right:  # 只在右鍵按下時更新
            pt_x, pt_y = x, y
            print(f"更新位置為: ({pt_x}, {pt_y})")

    from pynput import mouse
    listener = mouse.Listener(on_click=on_click)
    listener.start()

    while True:
        # 截圖指定點位周圍的範圍
        screen = pyautogui_screenshot(region=(
            pt_x - 2*crop_size,
            pt_y - 2*crop_size,
            crop_size * 4,
            crop_size * 4
        ))
        screen = np.array(screen)
        screen = cv2.cvtColor(screen, cv2.COLOR_RGB2BGR)
        
        # 轉換到 HSV 空間
        hsv_image = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
        
        # 將魚影顏色從 RGB 轉換到 HSV
        fish_color_bgr = fish_color_rgb[::-1]
        fish_color_hsv = cv2.cvtColor(np.uint8([[fish_color_bgr]]), cv2.COLOR_BGR2HSV)[0][0]

        # 設定 HSV 範圍
        lower_bound = np.array([
            max(0, fish_color_hsv[0] - tolerance_hue),
            max(0, fish_color_hsv[1] - tolerance_sat),
            max(0, fish_color_hsv[2] - tolerance_val),
        ])
        upper_bound = np.array([
            min(179, fish_color_hsv[0] + tolerance_hue),
            min(255, fish_color_hsv[1] + tolerance_sat),
            min(255, fish_color_hsv[2] + tolerance_val),
        ])

        # 產生遮罩
        mask = cv2.inRange(hsv_image, lower_bound, upper_bound)

        # 找出輪廓
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # 放大圖片
        screen = cv2.resize(screen, None, fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_LINEAR)

        # 繪製輪廓和資訊
        for contour in contours:
            area = cv2.contourArea(contour)
            if area > 50:  # 過濾小區域
                try:
                    # 縮放輪廓點
                    scaled_contour = contour * scale_factor
                    # 確保輪廓包含點
                    if len(scaled_contour) > 0:
                        # 畫輪廓
                        cv2.drawContours(screen, [scaled_contour], -1, (0, 0, 255), 2)  # 紅色輪廓

                        # 畫邊界矩形
                        x, y, w, h = cv2.boundingRect(contour)
                        x, y, w, h = [int(v * scale_factor) for v in [x, y, w, h]]
                        cv2.rectangle(screen, (x, y), (x + w, y + h), (0, 255, 0), 2)  # 綠色矩形框

                        # 顯示面積資訊
                        cv2.putText(screen, f"Area: {area:.0f}", (10, 30), 
                                cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                except Exception as e:
                    print(f"繪製輪廓時發生錯誤: {e}")
                    continue

        # 在放大後的圖片中心畫十字線
        h, w = screen.shape[:2]
        center_x, center_y = w // 2, h // 2
        cv2.line(screen, (center_x, 0), (center_x, h), (0, 255, 0), 1)
        cv2.line(screen, (0, center_y), (w, center_y), (0, 255, 0), 1)

        # 顯示畫面
        cv2.imshow(windowName, screen)
        
        if cv2.waitKey(1) & 0xFF == ord('q') or cv2.getWindowProperty(windowName, cv2.WND_PROP_VISIBLE) < 1:
            break

    cv2.destroyWindow(windowName)
    listener.stop()

#-------------------------------------------------
# 函式：main
# 用途：程式進入點，分別啟動三個執行緒：
#       1. fisher() - 截圖與釣魚偵測
#       2. status_checker() - 釣魚後的一些判斷與按鍵操作
#       3. timeout_checker() - 監聽若超過兩分鐘沒捕捉到魚則發送 LINE 通知
#-------------------------------------------------
def main():
    # pt, rgb_value = Getinput() # 抓取浮標位置

    fishThread = threading.Thread(target=fisher)
    # measureThread = threading.Thread(target=measuring, args=(pt[0], pt[1], rgb_value))
    statusCheckerThread = threading.Thread(target=status_checker)
    timeoutCheckerThread = threading.Thread(target=timeout_checker)
    

    # 設定部分執行緒為 daemon，使主程式關閉時能自動結束
    statusCheckerThread.daemon = True
    # measureThread.daemon = True
    timeoutCheckerThread.daemon = True

    fishThread.start()
    # measureThread.start()
    statusCheckerThread.start()
    timeoutCheckerThread.start()

# 真正的程式執行入口
if __name__ == "__main__":
    main()
