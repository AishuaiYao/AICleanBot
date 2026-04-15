"""
工具脚本集合
功能: 提供模型导出、文件重命名、GPU测试、模型分析、标签可视化等常用工具函数
部署位置: PC端 (Windows/Linux/Mac)
"""

import os
import re
import glob
import random
import shutil
import cv2
import numpy as np
import torch
import onnx


def export_onnx(model, save_dir, input_shape=(1, 1, 120, 160), model_name='model.onnx'):
    """
    导出PyTorch模型为ONNX格式
    
    功能:
        将已加载权重的PyTorch模型导出为ONNX格式，用于模型部署
    
    入参:
        model: torch.nn.Module - PyTorch模型（已加载权重）
        save_dir: str - 保存目录路径
        input_shape: tuple - 输入形状 (N, C, H, W)，默认 (1, 1, 120, 160)
        model_name: str - 模型文件名，默认 'model.onnx'
    
    出参:
        str - ONNX模型文件的完整路径
    """
    model_cpu = model.cpu().eval()
    onnx_path = os.path.join(save_dir, model_name)
    
    print(f"\n正在导出ONNX模型...")
    torch.onnx.export(
        model_cpu,
        torch.randn(*input_shape),
        onnx_path,
        input_names=["input"],
        output_names=["output"],
        opset_version=11,
        dynamic_axes={
            "input": {0: "batch", 2: "height", 3: "width"},
            "output": {0: "batch", 2: "height", 3: "width"}
        }
    )
    print(f"ONNX模型已导出：{onnx_path}")
    
    return onnx_path


def export_pth_to_onnx(model_class, pth_path, save_dir, input_shape=(1, 1, 120, 160), model_name='model.onnx'):
    """
    从.pth权重文件导出ONNX模型
    
    功能:
        从.pth权重文件加载模型并导出为ONNX格式（独立于训练流程）
    
    入参:
        model_class: type - 模型类（如UNetMiniExp2）
        pth_path: str - .pth权重文件路径
        save_dir: str - 保存目录路径
        input_shape: tuple - 输入形状 (N, C, H, W)，默认 (1, 1, 120, 160)
        model_name: str - 模型文件名，默认 'model.onnx'
    
    出参:
        str - ONNX模型文件的完整路径
    """
    # 实例化模型
    model = model_class()
    
    # 加载权重
    model.load_state_dict(torch.load(pth_path, map_location='cpu'))
    
    # 导出
    return export_onnx(model, save_dir, input_shape, model_name)


def batch_rename_files(directory, start_num=1, digits=5):
    """
    批量重命名PNG文件为数字编号格式
    
    功能:
        将目录下所有PNG文件按自然排序后重命名为数字编号格式（如 00001.png）
    
    入参:
        directory: str - 目标文件夹路径
        start_num: int - 起始编号，默认 1
        digits: int - 编号位数（如5位表示00001），默认 5
    
    出参:
        None
    """
    # 1. 获取所有png文件并自然排序
    png_files = glob.glob(os.path.join(directory, "*.png"))
    file_names = [os.path.basename(f) for f in png_files]
    
    # 自然排序（解决10排在2前面的问题）
    def natural_sort(s):
        return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', s)]
    sorted_files = sorted(file_names, key=natural_sort)
    
    # 2. 批量重命名
    start_num = 540
    for idx, old_name in enumerate(sorted_files):
        new_name = f"{start_num + idx:0{digits}d}.png"  # 生成新名字
        old_path = os.path.join(directory, old_name)
        new_path = os.path.join(directory, new_name)
        os.rename(old_path, new_path)
        print(f"重命名：{old_name} → {new_name}")


def test_gpu():
    """
    测试GPU可用性
    
    功能:
        检测CUDA环境并打印GPU信息，执行简单计算测试验证GPU是否正常工作
    
    入参:
        None
    
    出参:
        None (打印GPU测试报告到控制台)
    
    输出示例:
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


def analyze_onnx_model(onnx_path, input_shape=(1, 1, 120, 160)):
    """
    分析ONNX模型的参数量和计算量
    
    功能:
        解析ONNX模型结构，统计参数量、计算量（FLOPs）和网络层类型
    
    入参:
        onnx_path: str - ONNX模型文件路径
        input_shape: tuple - 输入形状 (N, C, H, W)，默认 (1, 1, 120, 160)
    
    出参:
        tuple - (params, flops)
            params: int - 参数总数
            flops: float - 计算量（FLOPs）
    
    输出示例:
        ==================================================
        ONNX模型分析: model.onnx
        ==================================================
        参数量: 1,234,567 (1.23M)
        计算量: 0.45 GFLOPs
        ==================================================
        网络层结构 (共42层):
          Conv: 10
          BatchNormalization: 8
          Relu: 8
        ==================================================
    """
    model = onnx.load(onnx_path)
    graph = model.graph
    
    # 参数量：遍历所有initializer
    params = 0
    for init in graph.initializer:
        params += np.prod(init.dims)
    
    # 统计网络层类型
    layer_stats = {}
    for node in graph.node:
        layer_stats[node.op_type] = layer_stats.get(node.op_type, 0) + 1
    
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
    print(f"网络层结构 (共{len(graph.node)}层):")
    for op_type, count in sorted(layer_stats.items()):
        print(f"  {op_type}: {count}")
    print(f"{'='*50}")
    
    return params, flops


def visualize_labels(image_dir, label_dir=None, output_dir=None):
    """
    可视化标签图像
    
    功能:
        将原图与标签图叠加显示，用于验证标注质量
        标签区域以紫色半透明覆盖显示
    
    入参:
        image_dir: str - 原图目录路径
        label_dir: str - 标签图目录路径，默认为 image_dir + '_label'
        output_dir: str - 输出目录路径，默认为 image_dir + '_visual'
    
    出参:
        None (结果保存到 output_dir)
    
    输出示例:
        总图片数：100
        总label数：100
        共有的图片数：100
        --------------------------------------------------
        [1/100] 00001.png
        [2/100] 00002.png
        ...
        完成，保存在：output_dir
    """
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


def split_dataset(image_dir, label_dir, train_dir, val_dir, train_ratio=0.8, seed=42):
    """
    划分数据集为训练集和验证集
    
    功能:
        按照指定随机种子和比例将数据集划分为训练集和验证集，复制到指定目录
        仅保留图像和标签都存在的样本
    
    入参:
        image_dir: str - 原图目录路径
        label_dir: str - 标签图目录路径
        train_dir: str - 训练集输出目录（会在其下创建images和labels子目录）
        val_dir: str - 验证集输出目录（会在其下创建images和labels子目录）
        train_ratio: float - 训练集比例，默认 0.8
        seed: int - 随机种子，默认 42
    
    出参:
        tuple - (train_count, val_count)
            train_count: int - 训练集样本数
            val_count: int - 验证集样本数
    
    输出示例:
        Total samples: 262
        Train samples: 209
        Val samples:   53
        
        Copying training set...
        Copying validation set...
        
        Done!
        Train set saved to: E:\AICleanBot\py_scripts\dataset\train
        Val set saved to:   E:\AICleanBot\py_scripts\dataset\val
    """
    # 固定随机种子
    random.seed(seed)
    
    # 创建输出目录
    train_img_dir = os.path.join(train_dir, 'images')
    train_label_dir = os.path.join(train_dir, 'labels')
    val_img_dir = os.path.join(val_dir, 'images')
    val_label_dir = os.path.join(val_dir, 'labels')
    
    for dir_path in [train_img_dir, train_label_dir, val_img_dir, val_label_dir]:
        os.makedirs(dir_path, exist_ok=True)
    
    # 获取文件名（支持 jpg, jpeg, png, bmp）
    img_files = set(glob.glob(os.path.join(image_dir, '*.[jp][pn]g')) + glob.glob(os.path.join(image_dir, '*.bmp')))
    label_files = set(glob.glob(os.path.join(label_dir, '*.[jp][pn]g')) + glob.glob(os.path.join(label_dir, '*.bmp')))
    
    img_names = {os.path.basename(p) for p in img_files}
    label_names = {os.path.basename(p) for p in label_files}
    common_names = sorted(list(img_names & label_names))
    
    print(f"Total samples: {len(common_names)}")
    
    # 随机打乱
    random.shuffle(common_names)
    
    # 划分数据集
    train_size = int(len(common_names) * train_ratio)
    train_names = common_names[:train_size]
    val_names = common_names[train_size:]
    
    print(f"Train samples: {len(train_names)}")
    print(f"Val samples:   {len(val_names)}")
    
    # 复制训练集
    print("\nCopying training set...")
    for name in train_names:
        shutil.copy2(os.path.join(image_dir, name), os.path.join(train_img_dir, name))
        shutil.copy2(os.path.join(label_dir, name), os.path.join(train_label_dir, name))
    
    # 复制验证集
    print("Copying validation set...")
    for name in val_names:
        shutil.copy2(os.path.join(image_dir, name), os.path.join(val_img_dir, name))
        shutil.copy2(os.path.join(label_dir, name), os.path.join(val_label_dir, name))
    
    print(f"\nDone!")
    print(f"Train set saved to: {train_dir}")
    print(f"Val set saved to:   {val_dir}")
    
    return len(train_names), len(val_names)


if __name__ == "__main__":
    # # 默认：批量重命名
    # target_directory = r"E:\AICleanBot\py_scripts\dataset\FRAME_QQVGA"
    # batch_rename_files(target_directory, start_num=1, digits=5)

    # 可视化标签
    # images = r'E:\AICleanBot\py_scripts\dataset\FRAME_QQVGA'
    # labels = r'E:\AICleanBot\py_scripts\dataset\FRAME_QQVGA_label'
    # visualize_labels(images, labels)

    # 测试gpu
    # test_gpu()
    
    # # 分析ONNX模型
    # # 从.pth导出ONNX示例
    import sys
    sys.path.append(r'E:\AICleanBot\py_scripts\net')
    from train_student import UNetMiniExp5
    export_pth_to_onnx(
        UNetMiniExp5,
        r"E:\AICleanBot\py_scripts\models\20260412_180030_UNetMiniExp5\best_model.pth",
        r"E:\AICleanBot\py_scripts\models\20260412_180030_UNetMiniExp5",
        input_shape=(1, 1, 120, 160)
    )

    # 分析ONNX模型示例
    analyze_onnx_model(r"E:\AICleanBot\py_scripts\models\20260412_180030_UNetMiniExp5\model.onnx")
    





    
