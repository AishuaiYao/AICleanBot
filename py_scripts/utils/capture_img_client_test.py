import socket
import struct
import numpy as np
import cv2
import os

"""

测试脚本：发送CAPTURE命令并保存图像
"""
SERVER_IP = "192.168.4.1"
SERVER_PORT = 5000
WIDTH = 320
HEIGHT = 120

def test_capture():
    # 连接ESP32
    print(f"连接到 {SERVER_IP}:{SERVER_PORT}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(30.0)
    
    try:
        sock.connect((SERVER_IP, SERVER_PORT))
        print("连接成功!")
    except Exception as e:
        print(f"连接失败: {e}")
        return
    
    try:
        while True:
            # 等待用户输入
            input("按回车采集图像 (Ctrl+C 退出)...")
            
            # 发送CAPTURE命令
            print(">>> 发送CAPTURE命令...")
            sock.send(b'CAPTURE\n')
            
            # 接收帧头 (4字节)
            header = b''
            while len(header) < 4:
                chunk = sock.recv(4 - len(header))
                if not chunk:
                    print("连接断开")
                    return
                header += chunk
            
            frame_size = struct.unpack('>I', header)[0]
            print(f"<<< 接收图像: {frame_size} 字节 (预期 {WIDTH*HEIGHT})")
            
            # 接收图像数据
            image_data = b''
            while len(image_data) < frame_size:
                chunk = sock.recv(min(8192, frame_size - len(image_data)))
                if not chunk:
                    print("接收中断")
                    return
                image_data += chunk
                print(f"\r  接收进度: {len(image_data)}/{frame_size}", end='', flush=True)
            
            print(f"\n<<< 接收完成!")
            
            # 转换为图像
            gray_array = np.frombuffer(image_data, dtype=np.uint8)
            gray_array = gray_array.reshape((HEIGHT, WIDTH))
            
            # 保存
            script_dir = os.path.dirname(os.path.abspath(__file__))
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = os.path.join(script_dir, f"capture_{timestamp}.png")
            cv2.imwrite(filename, gray_array)
            print(f">>> 已保存: {filename}")
            
            # 显示
            cv2.imshow('Capture', gray_array)
            cv2.waitKey(500)
            
    except KeyboardInterrupt:
        print("\n用户中断")
    finally:
        sock.close()
        cv2.destroyAllWindows()
        print("结束")

if __name__ == '__main__':
    import time
    test_capture()
