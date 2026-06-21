import os
import re
import shutil
from pathlib import Path

# ========== 配置 ==========
SOURCE_DIR  = r"E:\9-照片备份"
MERGE_DIR   = os.path.join(SOURCE_DIR, "merge")
# ==========================

def is_date_prefix_folder(name: str) -> bool:
    """判断文件夹名是否以日期格式开头, 例如:
       2024-01-01xxx, 20240101xxx, 2024_01_01xxx,
       2024年01月01日xxx, 2024.01.01xxx,
       202106__  (年月+后缀), 202308_a"""
    patterns = [
        r'^\d{6}_',                  # 202106__, 202308_a 等 (年月+下划线后缀)
        r'^\d{4}-\d{2}-\d{2}',      # 2024-01-01
        r'^\d{8}',                   # 20240101
        r'^\d{4}_\d{2}_\d{2}',      # 2024_01_01
        r'^\d{4}\.\d{2}\.\d{2}',    # 2024.01.01
        r'^\d{4}年\d{2}月\d{2}日',   # 2024年01月01日
        r'^\d{4}/\d{2}/\d{2}',       # 2024/01/01
    ]
    return any(re.match(p, name) for p in patterns)


def main():
    if not os.path.isdir(SOURCE_DIR):
        print(f"错误: 源目录不存在 -> {SOURCE_DIR}")
        return

    os.makedirs(MERGE_DIR, exist_ok=True)

    date_folders = []
    for entry in os.listdir(SOURCE_DIR):
        full = os.path.join(SOURCE_DIR, entry)
        if os.path.isdir(full) and entry != "merge" and is_date_prefix_folder(entry):
            date_folders.append(entry)

    if not date_folders:
        print("未找到任何日期开头的子文件夹。")
        return

    print(f"找到 {len(date_folders)} 个日期开头的文件夹:")
    for f in date_folders:
        print(f"  - {f}")

    total_copied = 0
    total_skipped = 0

    for folder_name in date_folders:
        folder_path = os.path.join(SOURCE_DIR, folder_name)
        for root, _, files in os.walk(folder_path):
            for filename in files:
                src = os.path.join(root, filename)
                dst = os.path.join(MERGE_DIR, filename)

                # 处理重名: 若目标已存在, 加序号
                if os.path.exists(dst):
                    name, ext = os.path.splitext(filename)
                    counter = 1
                    while True:
                        new_name = f"{name}_{counter}{ext}"
                        dst = os.path.join(MERGE_DIR, new_name)
                        if not os.path.exists(dst):
                            break
                        counter += 1
                    print(f"  重名处理: {filename} -> {new_name}")

                shutil.copy2(src, dst)   # copy2 保留元数据(时间戳等)
                total_copied += 1

    print(f"\n完成! 共复制 {total_copied} 个文件到 {MERGE_DIR}")

if __name__ == "__main__":
    main()
