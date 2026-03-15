import cv2
import os
import glob
import numpy as np


def visualize_labels(image_dir, label_dir=None, output_dir=None):
    if label_dir is None:
        label_dir = image_dir + '_label'
    if output_dir is None:
        output_dir = image_dir + '_visual'
    
    os.makedirs(output_dir, exist_ok=True)
    
    img_paths = glob.glob(os.path.join(image_dir, '*.[jp][pn]g')) + glob.glob(os.path.join(image_dir, '*.bmp'))
    img_names = [os.path.basename(p) for p in img_paths]
    
    label_paths = glob.glob(os.path.join(label_dir, '*.[jp][pn]g')) + glob.glob(os.path.join(label_dir, '*.bmp'))
    label_names = [os.path.basename(p) for p in label_paths]
    
    common_names = sorted(set(img_names) & set(label_names))
    total = len(common_names)
    
    print(f"总图片数：{len(img_names)}")
    print(f"总label数：{len(label_names)}")
    print(f"共有的图片数：{total}")
    print("-" * 50)
    
    for idx, img_name in enumerate(common_names):
        img_path = os.path.join(image_dir, img_name)
        label_path = os.path.join(label_dir, img_name)
        output_path = os.path.join(output_dir, img_name)
        
        img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
        label = cv2.imread(label_path, cv2.IMREAD_GRAYSCALE)
        
        img_bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        
        mask = (label > 0)
        alpha = 0.1
        result = img_bgr.copy()
        result[mask] = (img_bgr[mask].astype(float) * (1 - alpha) + np.array([128, 0, 128]) * alpha).astype(np.uint8)
        
        cv2.imwrite(output_path, result)
        print(f"[{idx + 1}/{total}] {img_name}")
    
    print(f"完成，保存在：{output_dir}")


if __name__ == '__main__':
    image_dir = r'E:\AICleanBot\py_scripts\dataset\FRAME_QQVGA'
    visualize_labels(image_dir)
