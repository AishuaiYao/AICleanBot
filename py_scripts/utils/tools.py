"""
极简工具脚本 - 仅保留核心功能
"""
import os
import re
import glob
import cv2
import numpy as np


def batch_rename_files(directory, start_num=1, digits=5):
    """
    极简版批量重命名：把目录下的png文件改成 000xx.png 格式
    :param directory: 目标文件夹路径
    :param start_num: 起始编号
    :param digits: 编号位数（比如5位就是00001）
    """
    # 1. 获取所有png文件并自然排序
    png_files = glob.glob(os.path.join(directory, "*.png"))
    file_names = [os.path.basename(f) for f in png_files]
    
    # 自然排序（解决10排在2前面的问题）
    def natural_sort(s):
        return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', s)]
    sorted_files = sorted(file_names, key=natural_sort)
    
    # 2. 批量重命名
    for idx, old_name in enumerate(sorted_files, start_num):
        new_name = f"{idx:0{digits}d}.png"  # 生成新名字
        old_path = os.path.join(directory, old_name)
        new_path = os.path.join(directory, new_name)
        os.rename(old_path, new_path)
        print(f"重命名：{old_name} → {new_name}")


if __name__ == "__main__":
    # 示例用法
    target_directory = r"E:\AICleanBot\py_scripts\dataset\FRAME_QQVGA"  # 替换成你的目录路径
    batch_rename_files(target_directory, start_num=1, digits=5)