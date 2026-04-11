"""
ESP32 图像采集服务端
部署位置: ESP32端
运行环境: MicroPython (需要摄像头驱动支持)
功能: 创建WiFi热点，启动TCP服务器，采集并发送摄像头图像

配套客户端: capture_img_client.py (PC端)
"""

import network
import time
import socket
import camera
from machine import Pin

# ===========================
# WiFi AP 配置 (ESP32作为热点)
# ===========================
AP_SSID = "CAM-AP"
AP_PASSWORD = "*HA39&q2Iah"

# ===========================
# 引脚定义 (使用你已验证的配置)
# ===========================
CAM_PIN_PWDN = -1
CAM_PIN_RESET = -1
CAM_PIN_XCLK = 15
CAM_PIN_SIOD = 4
CAM_PIN_SIOC = 5

CAM_PIN_D7 = 16  # Y9
CAM_PIN_D6 = 17  # Y8
CAM_PIN_D5 = 18  # Y7
CAM_PIN_D4 = 12  # Y6
CAM_PIN_D3 = 10  # Y5
CAM_PIN_D2 = 8  # Y4
CAM_PIN_D1 = 9  # Y3
CAM_PIN_D0 = 11  # Y2

CAM_PIN_VSYNC = 6
CAM_PIN_HREF = 7
CAM_PIN_PCLK = 13


# ===========================
# 创建WiFi热点函数 (使用AP模式)
# ===========================
def create_wifi_ap():
    """
    创建WiFi热点，让PC连接
    返回AP的IP地址
    """
    # 创建AP接口
    ap = network.WLAN(network.AP_IF)

    # 先禁用STA模式，避免冲突
    sta = network.WLAN(network.STA_IF)
    sta.active(False)

    # 配置AP
    ap.active(True)
    # 重要：使用正确的config方法
    ap.config(essid=AP_SSID, password=AP_PASSWORD, authmode=network.AUTH_WPA_WPA2_PSK)

    # 等待AP启动
    max_wait = 10
    while max_wait > 0:
        if ap.active():
            break
        max_wait -= 1
        time.sleep(1)
        print('.', end='')

    if not ap.active():
        print("\nAP启动失败")
        return None

    # 获取IP配置
    ip_info = ap.ifconfig()
    print('\nWiFi热点已创建:')
    print(f'SSID: {AP_SSID}')
    print(f'密码: {AP_PASSWORD}')
    print(f'IP地址: {ip_info[0]}')
    print(f'子网掩码: {ip_info[1]}')
    print(f'网关: {ip_info[2]}')

    return ip_info[0]


# ===========================
# 摄像头初始化函数 (使用你已验证的配置)
# ===========================
def init_camera():
    try:
        # 尝试先释放
        try:
            camera.deinit()
        except Exception:
            pass

        # 使用你已验证的参数
        camera.init(0, format=camera.GRAYSCALE, framesize=camera.FRAME_QQVGA,
                    xclk_freq=camera.XCLK_20MHz,
                    d0=CAM_PIN_D0, d1=CAM_PIN_D1, d2=CAM_PIN_D2, d3=CAM_PIN_D3,
                    d4=CAM_PIN_D4, d5=CAM_PIN_D5, d6=CAM_PIN_D6, d7=CAM_PIN_D7,
                    vsync=CAM_PIN_VSYNC, href=CAM_PIN_HREF, pclk=CAM_PIN_PCLK,
                    xclk=CAM_PIN_XCLK, siod=CAM_PIN_SIOD, sioc=CAM_PIN_SIOC,
                    reset=CAM_PIN_RESET, pwdn=CAM_PIN_PWDN)

        # 可选：调整图像质量
        try:
            camera.quality(0)  # 设置图像质量（0-63，越小质量越高）
        except:
            pass

        print("摄像头初始化成功")
        return True

    except Exception as e:
        print(f"摄像头初始化失败: {e}")
        return False


# ===========================
# TCP图像服务器
# ===========================
class ImageServer:
    def __init__(self, ip, port=5000):
        self.ip = ip
        self.port = port
        self.server_socket = None
        self.client_socket = None
        self.running = False
        self.frame_count = 0

    def start(self):
        """启动TCP服务器"""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(('', self.port))
        self.server_socket.listen(1)
        print(f"图像服务器已启动，等待连接...")
        print(f"IP: {self.ip}:{self.port}")

        self.running = True
        while self.running:
            try:
                self.client_socket, addr = self.server_socket.accept()
                print(f"客户端已连接: {addr}")
                self.send_images()
            except Exception as e:
                if self.running:
                    print(f"连接错误: {e}")
                continue

    def send_images(self):
        """向当前客户端发送图像，断开后返回"""
        while self.running and self.client_socket:
            buf = camera.capture()
            if buf:
                frame_size = len(buf)
                header = frame_size.to_bytes(4, 'big')
                try:
                    self.client_socket.sendall(header + buf)
                    self.frame_count += 1
                    print(f"{self.frame_count} 已发送 {frame_size} 字节")
                except (socket.error, OSError) as e:
                    print(f"客户端断开连接: {e}")
                    if self.client_socket:
                        self.client_socket.close()
                        self.client_socket = None
                    print("等待新客户端连接...")
                    break
                except Exception as e:
                    print(f"发送错误: {e}")
                    continue

    def cleanup(self):
        """清理资源"""
        self.running = False
        if self.client_socket:
            self.client_socket.close()
        if self.server_socket:
            self.server_socket.close()
        print(f"服务器已停止，总共发送 {self.frame_count} 帧")


# ===========================
# 主程序
# ===========================
def main():
    print("=" * 50)
    print("ESP32-S3 摄像头服务器 (AP模式)")
    print("=" * 50)

    # 1. 创建WiFi热点
    ip = create_wifi_ap()

    if ip:
        # 2. 初始化摄像头
        if init_camera():
            # 3. 启动图像服务器
            server = ImageServer(ip, port=5000)
            try:
                server.start()
            except KeyboardInterrupt:
                print("\n程序被用户中断")
            except Exception as e:
                print(f"服务器错误: {e}")
            finally:
                server.cleanup()
        else:
            print("摄像头初始化失败，服务器未启动")
    else:
        print("WiFi热点创建失败")


if __name__ == '__main__':
    main()
