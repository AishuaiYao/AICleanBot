"""
ESP32 模型推理测试客户端
部署位置: PC端 (Windows/Linux/Mac)
功能: 发送图片到ESP32进行推理，接收二值图结果并拼接保存

配套服务端: E:\AICleanBot\main\inference_test.cpp (ESP32端)
使用方式:
    1. 编译烧录 inference_test.cpp 到 ESP32
    2. 连接 ESP32 WiFi 热点
    3. 运行此脚本进行模型推理测试
"""

import socket
import struct
import numpy as np
import cv2
import time
import os
from pathlib import Path


class ModelTestClient:
    def __init__(self, server_ip="192.168.4.1", server_port=5000):
        self.server_ip = server_ip
        self.server_port = server_port
        self.client_socket = None
        
        # 图像尺寸
        self.input_width = 160
        self.input_height = 120

    def connect(self):
        """连接ESP32并握手"""
        print(f"[连接] 尝试连接 {self.server_ip}:{self.server_port}")
        
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.client_socket.settimeout(5.0)
        self.client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        
        self.client_socket.connect((self.server_ip, self.server_port))
        print("[连接] TCP连接成功")
        
        # 发送握手
        self.client_socket.send(b"HELLO\n")
        
        # 接收设备信息
        response = self.client_socket.recv(64)
        if not response:
            raise Exception("握手失败：无响应")
        
        device_info = response.decode('utf-8').strip()
        print(f"[握手] 设备信息: {device_info}")
        
        return True

    def send_image(self, image_path):
        """发送单张图片进行推理"""
        # 读取图片
        img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise Exception(f"无法读取图片: {image_path}")
        
        # 调整尺寸
        img_resized = cv2.resize(img, (self.input_width, self.input_height))
        
        # 发送PREDICT命令
        self.client_socket.send(b"PREDICT\n")
        
        # 等待命令被接收
        time.sleep(0.01)
        
        # 发送图片大小 (4字节, 大端序)
        image_size = self.input_width * self.input_height
        size_buf = struct.pack('>I', image_size)
        self.client_socket.send(size_buf)
        
        # 发送图片数据
        image_data = img_resized.tobytes()
        total_sent = 0
        while total_sent < image_size:
            sent = self.client_socket.send(image_data[total_sent:])
            if sent == 0:
                raise Exception("发送图片失败")
            total_sent += sent
        
        print(f"  [发送] 图片大小: {image_size} bytes")
        
        # 接收结果大小
        result_size_buf = self._recv_bytes(4)
        result_size = struct.unpack('>I', result_size_buf)[0]
        
        print(f"  [接收] 结果大小: {result_size} bytes")
        
        # 接收二值图数据
        result_data = self._recv_bytes(result_size)
        
        # 转换为numpy数组
        pred_img = np.frombuffer(result_data, dtype=np.uint8)
        pred_img = pred_img.reshape((self.input_height, self.input_width))
        
        return img_resized, pred_img

    def _recv_bytes(self, num_bytes):
        """可靠接收指定字节数"""
        data = b''
        remaining = num_bytes
        
        while remaining > 0:
            chunk = self.client_socket.recv(min(8192, remaining))
            if not chunk:
                raise Exception("连接断开")
            data += chunk
            remaining -= len(chunk)
        
        return data

    def test_directory(self, input_dir, output_dir):
        """测试目录下所有图片"""
        input_path = Path(input_dir)
        output_path = Path(output_dir)
        
        # 检查输入目录
        if not input_path.exists():
            raise Exception(f"输入目录不存在: {input_dir}")
        
        # 创建输出目录
        output_path.mkdir(parents=True, exist_ok=True)
        
        # 获取所有图片
        image_extensions = {'.png', '.jpg', '.jpeg', '.bmp'}
        image_files = [f for f in input_path.iterdir() 
                       if f.suffix.lower() in image_extensions]
        image_files.sort()
        
        if not image_files:
            raise Exception(f"输入目录中没有图片: {input_dir}")
        
        print(f"\n[测试] 找到 {len(image_files)} 张图片")
        print(f"[测试] 输入目录: {input_dir}")
        print(f"[测试] 输出目录: {output_dir}\n")
        
        start_time = time.time()
        success_count = 0
        
        for i, img_file in enumerate(image_files, 1):
            try:
                print(f"[{i}/{len(image_files)}] 处理: {img_file.name}")
                
                # 发送图片并接收结果
                original, prediction = self.send_image(img_file)
                
                # 拼接原图和预测图
                concat_img = np.hstack([original, prediction])
                
                # 保存结果
                output_file = output_path / f"{img_file.stem}_concat.png"
                cv2.imwrite(str(output_file), concat_img)
                
                print(f"  [保存] {output_file.name}\n")
                success_count += 1
                
            except Exception as e:
                print(f"  [错误] {e}\n")
                continue
        
        # 统计
        total_time = time.time() - start_time
        print("=" * 50)
        print(f"[完成] 成功处理: {success_count}/{len(image_files)}")
        print(f"[完成] 总耗时: {total_time:.1f} 秒")
        print(f"[完成] 平均耗时: {total_time/max(success_count,1):.2f} 秒/张")
        print("=" * 50)

    def close(self):
        """关闭连接"""
        if self.client_socket:
            self.client_socket.send(b"EXIT\n")
            self.client_socket.close()
            print("[断开] 连接已关闭")


def main():
    # 配置参数
    SERVER_IP = "192.168.4.1"
    SERVER_PORT = 5000
    
    # 输入输出目录 (相对于脚本位置)
    script_dir = Path(__file__).parent
    input_dir = script_dir / "../test_images"
    output_dir = script_dir / "../test_results"
    os.makedirs(output_dir, exist_ok=True)
    
    print("=" * 50)
    print("ESP32 模型测试客户端")
    print("=" * 50)
    print(f"服务器: {SERVER_IP}:{SERVER_PORT}")
    print(f"输入目录: {input_dir}")
    print(f"输出目录: {output_dir}")
    print("=" * 50)
    
    client = ModelTestClient(SERVER_IP, SERVER_PORT)
    
    try:
        # 连接
        client.connect()
        
        # 测试
        client.test_directory(input_dir, output_dir)
        
    except KeyboardInterrupt:
        print("\n[中断] 用户取消")
    except Exception as e:
        print(f"\n[错误] {e}")
        import traceback
        traceback.print_exc()
    finally:
        client.close()


if __name__ == '__main__':
    main()
