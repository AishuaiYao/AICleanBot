import matplotlib.pyplot as plt
import numpy as np

# 原始数据
cur_L = [6303, 6383, 6463, 6544, 6592, 6642, 6706, 6808, 6917, 7021, 7124, 7224, 7322, 7417, 7529, 7618, 7676, 7731]
cur_R = [6478, 6561, 6660, 6764, 6893, 7037, 7156, 7235, 7308, 7384, 7462, 7541, 7624, 7710, 7811, 7898, 7977, 8053]
delta_L = [0, 80, 80, 81, 48, 50, 64, 102, 109, 104, 103, 100, 98, 95, 112, 89, 58, 55]
delta_R = [0, 83, 99, 104, 129, 144, 119, 79, 73, 76, 78, 79, 83, 86, 101, 87, 79, 76]
change_L = [0, 80, 0, 1, 33, 2, 14, 38, 7, 5, 1, 3, 2, 3, 17, 23, 31, 3]
change_R = [0, 83, 16, 5, 25, 15, 25, 40, 6, 3, 2, 1, 4, 3, 15, 14, 8, 3]
running = [0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]

idx = np.arange(len(cur_L))

# 创建4张子图
fig, axes = plt.subplots(4, 1, figsize=(14, 12), sharex=True)
plt.rcParams['font.sans-serif'] = ['SimHei']
plt.rcParams['axes.unicode_minus'] = False

# 1. cur 累计脉冲
axes[0].plot(idx, cur_L, 'b-o', label='左轮cur', markersize=4)
axes[0].plot(idx, cur_R, 'r-s', label='右轮cur', markersize=4)
axes[0].set_title('左右轮当前总脉冲 cur L/R')
axes[0].legend()
axes[0].grid(True, alpha=0.3)

# 2. delta 单帧增量
axes[1].plot(idx, delta_L, 'b-o', label='delta L', markersize=4)
axes[1].plot(idx, delta_R, 'r-s', label='delta R', markersize=4)
axes[1].axhline(y=50, c='k', ls='--', label='阈值thr=50')
axes[1].set_title('单帧脉冲增量 delta L/R')
axes[1].legend()
axes[1].grid(True, alpha=0.3)

# 3. change有效变化量
axes[2].plot(idx, change_L, 'b-o', label='change L', markersize=4)
axes[2].plot(idx, change_R, 'r-s', label='change R', markersize=4)
axes[2].set_title('有效变化量 change L/R')
axes[2].legend()
axes[2].grid(True, alpha=0.3)

# 4. running运行状态
axes[3].step(idx, running, 'g-', where='mid', linewidth=2, label='running(0静止/1运动)')
axes[3].set_title('运行状态 running')
axes[3].set_xlabel('采样序号')
axes[3].set_yticks([0,1])
axes[3].legend()
axes[3].grid(True, alpha=0.3)

plt.tight_layout()
plt.show()