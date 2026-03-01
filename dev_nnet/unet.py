import cv2
import os
import glob
import numpy as np

# 可配置参数
scale_size = 500  # 展示用的缩放宽度（不影响最终保存）
target_size = 256  # 最终保存的目标尺寸，长边对齐256，短边等比后填充0
line_expand = 2  # 线段扩展像素（核心可调节，建议2-5，数字越大线段越粗）
img_dir = r'dataset\data'  # 原始图片目录（完全保留，不修改）
gray_save_dir = r'dataset\image'  # 缩放后灰度图的保存目录（256×256）
label_save_dir = r'dataset\label'  # 绘制线段后的真值图保存目录（256×256）

# 全局变量
click_points = []
img_concat_show = None
label_show = None
label_original = None
img_original_gray = None
current_img_path = None

# 自动创建所需目录
os.makedirs(gray_save_dir, exist_ok=True)
os.makedirs(label_save_dir, exist_ok=True)


# 核心函数1：长边256，等比缩放+0填充
def resize_and_pad(img, target_size=256):
    h, w = img.shape[:2]
    max_side = max(h, w)
    scale = target_size / max_side
    new_w = int(w * scale)
    new_h = int(h * scale)
    img_resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    img_padded = np.zeros((target_size, target_size), dtype=np.uint8)
    x_offset = (target_size - new_w) // 2
    y_offset = (target_size - new_h) // 2
    img_padded[y_offset:y_offset + new_h, x_offset:x_offset + new_w] = img_resized
    return img_padded, (scale, x_offset, y_offset)


# 核心函数2：只对当前新线段做膨胀，再叠加到label上，修复越画越粗的bug
def draw_thick_line_on_single_channel(label, pt1, pt2, expand=2):
    # 新建临时空白图，只画当前这条线
    temp_line = np.zeros_like(label, dtype=np.uint8)
    cv2.line(temp_line, pt1, pt2, 255, thickness=1, lineType=cv2.LINE_AA)

    # 只膨胀这一条新线
    if expand > 0:
        kernel_size = 2 * expand + 1
        kernel = np.ones((kernel_size, kernel_size), dtype=np.uint8)
        temp_line = cv2.dilate(temp_line, kernel, iterations=1)

    # 把粗线叠加到label上，不影响之前已画的内容
    label = cv2.bitwise_or(label, temp_line)
    return label


# 鼠标回调函数
def mouse_click(event, x, y, flags, param):
    global click_points, img_concat_show, label_show, label_original, line_expand
    if event == cv2.EVENT_LBUTTONDOWN:
        click_points.append((x, y))
        print(f"点击坐标：({x}, {y})，累计点击{len(click_points)}次")

        # 成对，画一条新线段
        if len(click_points) % 2 == 0:
            pt1 = click_points[-2]
            pt2 = click_points[-1]
            line_thickness = 2 * line_expand + 1

            # 1. 在展示图上画绿色线
            cv2.line(img_concat_show, pt1, pt2, (0, 255, 0), thickness=line_thickness, lineType=cv2.LINE_AA)

            # 2. 在展示用的label上画粗线（修复后）
            label_show = draw_thick_line_on_single_channel(label_show, pt1, pt2, expand=line_expand)
            # 更新拼接图右侧的label显示
            img_concat_show[:, scale_size:] = cv2.cvtColor(label_show, cv2.COLOR_GRAY2BGR)

            # 3. 坐标映射到原始尺寸label，并画粗线（修复后）
            show_h, show_w = label_show.shape[:2]
            orig_h, orig_w = label_original.shape[:2]
            scale_x = orig_w / scale_size
            scale_y = orig_h / show_h

            pt1_orig = (int(pt1[0] * scale_x), int(pt1[1] * scale_y))
            pt2_orig = (int(pt2[0] * scale_x), int(pt2[1] * scale_y))

            label_original = draw_thick_line_on_single_channel(label_original, pt1_orig, pt2_orig, expand=line_expand)

            # 刷新窗口
            cv2.imshow('img+label', img_concat_show)


# 获取图片路径
img_paths = glob.glob(os.path.join(img_dir, '*.[jp][pn]g')) + glob.glob(os.path.join(img_dir, '*.bmp'))
if not img_paths:
    print("警告：未找到图片")
    exit()

# 遍历处理
for idx, img_path in enumerate(img_paths):
    current_img_path = img_path
    click_points = []
    img_concat_show = None
    label_show = None
    label_original = None
    img_original_gray = None

    img = cv2.imread(img_path)
    if img is None:
        print(f"警告：无法读取 {img_path}，跳过")
        continue
    orig_h, orig_w = img.shape[:2]
    img_original_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    label_original = np.zeros_like(img_original_gray, dtype=np.uint8)

    # 展示图缩放
    scale_show = scale_size / orig_w
    show_h = int(orig_h * scale_show)
    img_resize = cv2.resize(img, (scale_size, show_h), interpolation=cv2.INTER_LINEAR)
    img_gray_show = cv2.cvtColor(img_resize, cv2.COLOR_BGR2GRAY)
    label_show = np.zeros_like(img_gray_show, dtype=np.uint8)

    # 拼接展示图
    img_gray_show_3c = cv2.cvtColor(img_gray_show, cv2.COLOR_GRAY2BGR)
    label_show_3c = cv2.cvtColor(label_show, cv2.COLOR_GRAY2BGR)
    img_concat_show = np.hstack((img_gray_show_3c, label_show_3c))
    concat_h, concat_w = img_concat_show.shape[:2]

    # 窗口与鼠标
    cv2.namedWindow('img+label', cv2.WINDOW_NORMAL)
    cv2.resizeWindow('img+label', concat_w, concat_h)
    cv2.setMouseCallback('img+label', mouse_click)
    cv2.imshow('img+label', img_concat_show)

    print(f"\n[{idx + 1}/{len(img_paths)}] 处理：{os.path.basename(img_path)}")
    print("左键：起点→终点画线段，回车保存，ESC跳过/退出")

    while True:
        key = cv2.waitKey(1) & 0xFF
        if key == 13:  # 回车保存
            img_gray_256, _ = resize_and_pad(img_original_gray, target_size)
            label_256, _ = resize_and_pad(label_original, target_size)
            img_name = os.path.basename(img_path)
            cv2.imwrite(os.path.join(gray_save_dir, img_name), img_gray_256)
            cv2.imwrite(os.path.join(label_save_dir, img_name), label_256)
            print(f"已保存：{img_name}")
            break
        elif key == 27:  # ESC
            print("ESC：跳过当前图片")
            break
    if key == 27:
        print("退出程序")
        break

    cv2.destroyAllWindows()

cv2.destroyAllWindows()
print("\n全部处理完成")















