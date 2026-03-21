import cv2
import os
import glob
import numpy as np

# 可配置参数
scale_size = 700  # 展示用的缩放宽度（不影响最终保存）
line_expand = 4  # 线段扩展像素（核心可调节，建议2-5，数字越大线段越粗）
img_dir = r'E:\AICleanBot\py_scripts\dataset\FRAME_QQVGA'  # 原始图片目录（完全保留，不修改）
gray_save_dir = r'E:\AICleanBot\py_scripts\dataset\FRAME_QQVGA'  # 缩放后灰度图的保存目录（256×256）
label_save_dir = gray_save_dir + '_label'  # 绘制线段后的真值图保存目录（256×256）

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

total = len(img_paths)
processed = 0
skipped = 0

print(f"\n总图片数：{total}")
print("-" * 50)

# 遍历处理
for idx, img_path in enumerate(img_paths):
    img_name = os.path.basename(img_path)
    gray_path = os.path.join(gray_save_dir, img_name)
    label_path = os.path.join(label_save_dir, img_name)
    
    # 检查是否已处理
    if os.path.exists(gray_path) and os.path.exists(label_path):
        skipped += 1
        processed += 1
        progress = (processed / total) * 100
        print(f"[{processed}/{total} {progress:5.1f}%] 跳过已处理：{img_name} (剩余：{total - processed})")
        continue
    
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
    
    # 判断并转换为灰度图
    if len(img.shape) == 3 and img.shape[2] == 3:
        img_original_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        img_original_gray = img  # 已经是单通道
    
    orig_h, orig_w = img_original_gray.shape[:2]
    label_original = np.zeros_like(img_original_gray, dtype=np.uint8)

    # 展示图缩放
    scale_show = scale_size / orig_w
    show_h = int(orig_h * scale_show)
    img_resize = cv2.resize(img_original_gray, (scale_size, show_h), interpolation=cv2.INTER_LINEAR)
    img_gray_show = img_resize
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

    progress = (processed / total) * 100
    print(f"\n[{processed + 1}/{total} {progress:5.1f}% → ", end="")
    print(f"{((processed + 1) / total) * 100:5.1f}%] 处理：{img_name} (剩余：{total - processed - 1})")
    print("左键：起点→终点画线段，回车保存，空格跳过当前，ESC退出")

    while True:
        key = cv2.waitKey(1) & 0xFF
        if key == 13:  # 回车保存
            # 保存原图尺寸的灰度图和标签图
            cv2.imwrite(gray_path, img_original_gray)
            cv2.imwrite(label_path, label_original)
            processed += 1
            print(f"已保存：{img_name} (原图尺寸: {orig_w}x{orig_h})")
            break
        elif key == 32:  # 空格跳过当前
            processed += 1
            print(f"空格：跳过当前图片 {img_name}")
            break
        elif key == 27:  # ESC退出
            print("ESC：退出程序")
            break
    if key == 27:
        print(f"\n提前退出 - 已处理：{processed}/{total} ({processed/total*100:.1f}%)，跳过：{skipped}")
        break

    cv2.destroyAllWindows()

cv2.destroyAllWindows()
print(f"\n全部完成 - 已处理：{processed}/{total} ({processed/total*100:.1f}%)，跳过：{skipped}")