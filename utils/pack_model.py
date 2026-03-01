#!/usr/bin/env python3
"""
将.espdl模型文件转换为C头文件
"""

import os
import argparse


def convert_espdl_to_header(input_file, output_file, array_name="model_data"):
    """将.espdl二进制文件转换为C头文件"""
    # 读取二进制文件
    with open(input_file, 'rb') as f:
        data = f.read()

    # 生成头文件内容
    header_content = f"""#ifndef MODEL_DATA_H
#define MODEL_DATA_H

#include <stdint.h>
#include <stddef.h>

// 模型数据
const uint8_t {array_name}[] = {{
"""

    # 添加十六进制数据，每行16字节
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        hex_str = ', '.join([f'0x{b:02x}' for b in chunk])
        header_content += f"    {hex_str},\n"

    # 添加模型大小信息
    header_content += f"""}};

// 模型数据大小（字节）
const size_t {array_name}_size = sizeof({array_name});

#endif // MODEL_DATA_H
"""

    # 写入头文件
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(header_content)

    print(f"成功转换: {input_file} -> {output_file}")
    print(f"模型大小: {len(data)} 字节")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="将.espdl文件转换为C头文件")
    parser.add_argument(
        "--input",
        default="E:\AICleanBot\models\sin_model.espdl",
        help="输入.espdl文件路径"
    )
    parser.add_argument(
        "--output",
        default="E:\AICleanBot\dev_esp\model_data.h",
        help="输出头文件路径"
    )
    parser.add_argument(
        "--array-name",
        default="model_data",
        help="C数组名称"
    )

    args = parser.parse_args()

    # 转换路径为绝对路径
    input_path = os.path.abspath(args.input)
    output_path = os.path.abspath(args.output)

    convert_espdl_to_header(input_path, output_path, args.array_name)