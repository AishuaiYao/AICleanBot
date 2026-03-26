"""
极简工具脚本 - 仅保留核心功能
"""
import os
import re
import glob
import cv2
import numpy as np
import torch
import onnx


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


def test_gpu():
    """
    测试GPU可用性
    
    === GPU测试报告 ===
    CUDA可用: True
    GPU数量: 1

    --- GPU 0 ---
    型号: NVIDIA GeForce GTX 1650
    显存总量: 4.00 GB
    计算能力: 7.5

    CUDA版本: 12.1
    PyTorch版本: 2.5.0+cu121

    正在执行GPU计算测试...
    ✓ 测试通过！GPU工作正常
    """
    print("\n=== GPU测试报告 ===")
    
    # CUDA可用性
    cuda_available = torch.cuda.is_available()
    print(f"CUDA可用: {cuda_available}")
    
    if not cuda_available:
        print("GPU不可用，将使用CPU")
        return
    
    # GPU数量
    gpu_count = torch.cuda.device_count()
    print(f"GPU数量: {gpu_count}")
    
    # GPU信息
    for i in range(gpu_count):
        print(f"\n--- GPU {i} ---")
        print(f"型号: {torch.cuda.get_device_name(i)}")
        
        # 显存信息
        props = torch.cuda.get_device_properties(i)
        total_memory = props.total_memory / (1024**3)  # 转换为GB
        print(f"显存总量: {total_memory:.2f} GB")
        print(f"计算能力: {props.major}.{props.minor}")
    
    # CUDA版本
    print(f"\nCUDA版本: {torch.version.cuda}")
    print(f"PyTorch版本: {torch.__version__}")
    
    # GPU计算测试
    print("\n正在执行GPU计算测试...")
    device = torch.device('cuda:0')
    x = torch.randn(1000, 1000, device=device)
    y = torch.randn(1000, 1000, device=device)
    z = torch.mm(x, y)
    
    if z.shape == (1000, 1000):
        print("✓ 测试通过！GPU工作正常")
    else:
        print("✗ 测试失败！")


def analyze_onnx_model(onnx_path, input_shape=(1, 1, 256, 256)):
    """
    分析ONNX模型的参数量和计算量
    :param onnx_path: ONNX模型路径
    :param input_shape: 输入形状 (N, C, H, W)
    """
    model = onnx.load(onnx_path)
    graph = model.graph
    
    # 参数量：遍历所有initializer
    params = 0
    for init in graph.initializer:
        params += np.prod(init.dims)
    
    # 计算量：估算各算子FLOPs
    flops = 0
    tensor_shapes = {}
    
    # 获取输入形状
    for inp in graph.input:
        if inp.name:
            tensor_shapes[inp.name] = input_shape
    
    # 遍历节点计算FLOPs
    for node in graph.node:
        # Conv
        if node.op_type == 'Conv':
            # 获取属性
            attrs = {a.name: a for a in node.attribute}
            kernel_shape = attrs['kernel_shape'].ints if 'kernel_shape' in attrs else (3, 3)
            strides = attrs['strides'].ints if 'strides' in attrs else (1, 1)
            pads = attrs['pads'].ints if 'pads' in attrs else (0, 0, 0, 0)
            groups = attrs['group'].i if 'group' in attrs else 1
            
            # 估算输出形状
            in_shape = tensor_shapes.get(node.input[0], input_shape)
            _, Cin, H, W = in_shape
            Kh, Kw = kernel_shape
            
            # 从权重推断输出通道
            for init in graph.initializer:
                if init.name == node.input[1]:
                    Cout = init.dims[0]
                    break
            else:
                Cout = Cin
            
            # 输出尺寸
            Oh = (H + pads[0] + pads[2] - Kh) // strides[0] + 1
            Ow = (W + pads[1] + pads[3] - Kw) // strides[1] + 1
            
            # FLOPs: 2 * Cout * (Cin/groups) * Kh * Kw * Oh * Ow
            flops += 2 * Cout * (Cin // groups) * Kh * Kw * Oh * Ow
            tensor_shapes[node.output[0]] = (1, Cout, Oh, Ow)
        
        # ConvTranspose
        elif node.op_type == 'ConvTranspose':
            attrs = {a.name: a for a in node.attribute}
            kernel_shape = attrs['kernel_shape'].ints if 'kernel_shape' in attrs else (2, 2)
            strides = attrs['strides'].ints if 'strides' in attrs else (2, 2)
            
            in_shape = tensor_shapes.get(node.input[0], input_shape)
            _, Cin, H, W = in_shape
            Kh, Kw = kernel_shape
            
            for init in graph.initializer:
                if init.name == node.input[1]:
                    Cout = init.dims[1] * (attrs['group'].i if 'group' in attrs else 1)
                    break
            else:
                Cout = Cin
            
            Oh = (H - 1) * strides[0] + Kh
            Ow = (W - 1) * strides[1] + Kw
            
            flops += 2 * Cout * Cin * Kh * Kw * H * W
            tensor_shapes[node.output[0]] = (1, Cout, Oh, Ow)
        
        # BatchNorm (推理时为线性变换)
        elif node.op_type == 'BatchNormalization':
            in_shape = tensor_shapes.get(node.input[0], input_shape)
            flops += 2 * np.prod(in_shape)
            tensor_shapes[node.output[0]] = in_shape
        
        # Add/Mul/Sub (逐元素)
        elif node.op_type in ['Add', 'Mul', 'Sub', 'Div']:
            in_shape = tensor_shapes.get(node.input[0], input_shape)
            flops += np.prod(in_shape)
            tensor_shapes[node.output[0]] = in_shape
        
        # Relu/Sigmoid (逐元素)
        elif node.op_type in ['Relu', 'Sigmoid', 'LeakyRelu']:
            in_shape = tensor_shapes.get(node.input[0], input_shape)
            flops += np.prod(in_shape)
            tensor_shapes[node.output[0]] = in_shape
        
        # MaxPool/AveragePool
        elif node.op_type in ['MaxPool', 'AveragePool']:
            in_shape = tensor_shapes.get(node.input[0], input_shape)
            tensor_shapes[node.output[0]] = in_shape
        
        # Concat
        elif node.op_type == 'Concat':
            out_shape = None
            for inp in node.input:
                if inp in tensor_shapes:
                    out_shape = tensor_shapes[inp]
                    break
            tensor_shapes[node.output[0]] = out_shape
        
        # Reshape/Transpose/Squeeze/Unsqueeze
        elif node.op_type in ['Reshape', 'Transpose', 'Squeeze', 'Unsqueeze', 'Flatten']:
            in_shape = tensor_shapes.get(node.input[0], input_shape)
            tensor_shapes[node.output[0]] = in_shape
    
    # 打印结果
    print(f"\n{'='*50}")
    print(f"ONNX模型分析: {os.path.basename(onnx_path)}")
    print(f"{'='*50}")
    print(f"参数量: {params:,} ({params/1e6:.2f}M)")
    print(f"计算量: {flops/1e9:.2f} GFLOPs")
    print(f"{'='*50}")
    
    return params, flops


if __name__ == "__main__":

    test_gpu()

    # 默认：批量重命名
    # target_directory = r"E:\AICleanBot\py_scripts\dataset\FRAME_QQVGA"
    # batch_rename_files(target_directory, start_num=1, digits=5)