"""
DFS遍历10x10矩阵的图形可视化演示（包含回溯路径）
使用matplotlib绘制节点和边，动态显示遍历过程
起点：(3, 4)
"""
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.animation import FuncAnimation
from matplotlib.patches import FancyBboxPatch, Circle
import numpy as np
from test_data import *
import time

# 设置matplotlib样式
plt.style.use('seaborn-v0_8-darkgrid')

# ==================== 配置参数 ====================
# 选择要使用的矩阵函数
# 可选: matrix1, matrix2, matrix3 或自定义的矩阵函数
MATRIX_FUNCTION = matrix4  # 修改这里来切换不同的矩阵

# 矩阵大小
MATRIX_ROWS = 10
MATRIX_COLS = 10

# 动画速度控制（单位：毫秒/帧）
# 数值越小速度越快，数值越大速度越慢
# 推荐范围：100-1000
ANIMATION_SPEED = 100  # 默认400毫秒每帧

# 起点坐标
START_ROW = 3
START_COL = 4

# 图形大小
FIGURE_WIDTH = 14
FIGURE_HEIGHT = 13
# ==================================================
class GraphDFSVisualizer:
    def __init__(self, matrix, start_row=START_ROW, start_col=START_COL):
        """
        初始化图形DFS可视化器

        Args:
            matrix: 邻居数量矩阵（每个节点的边数）
            start_row: 起始行
            start_col: 起始列
        """
        self.matrix = matrix
        self.rows = len(matrix)
        self.cols = len(matrix[0]) if matrix else 0
        self.start_row = start_row
        self.start_col = start_col
        self.start_col = start_col

        # 访问状态
        self.visited = [[False for _ in range(self.cols)] for _ in range(self.rows)]
        self.visit_order = []

        # 边的集合：使用集合存储所有边（无向边，用排序后的元组表示）
        self.all_edges = set()
        self.remaining_edges = set()
        self.traversed_edges = []

        # 初始化所有边（只在非障碍物节点之间创建边）
        directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]
        for i in range(self.rows):
            for j in range(self.cols):
                # 跳过障碍物节点（值为0的节点）
                if matrix[i][j] == 0:
                    continue

                for di, dj in directions:
                    ni, nj = i + di, j + dj
                    # 只在两个非障碍物节点之间创建边
                    if (0 <= ni < self.rows and 0 <= nj < self.cols and
                        matrix[ni][nj] != 0):
                        # 使用排序后的元组表示无向边
                        edge = tuple(sorted([(i, j), (ni, nj)]))
                        self.all_edges.add(edge)

        self.remaining_edges = self.all_edges.copy()

        # DFS遍历步骤记录
        self.steps = []
        self.current_step = 0

        # 四个方向
        self.directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]

        # 执行DFS收集所有步骤
        self._collect_dfs_steps()

    def _collect_dfs_steps(self):
        """收集DFS遍历的所有步骤（包括回溯）"""
        # 重置状态
        self.visited = [[False for _ in range(self.cols)] for _ in range(self.rows)]
        self.visit_order = []
        temp_remaining = self.all_edges.copy()
        temp_traversed = []

        # 记录DFS调用栈，用于回溯可视化
        call_stack = []

        def dfs(row, col, parent_row=None, parent_col=None):
            # 检查边界
            if row < 0 or row >= self.rows or col < 0 or col >= self.cols:
                return

            # 如果节点值为0（障碍物），不能访问
            if self.matrix[row][col] == 0:
                return

            # 如果已访问，返回
            if self.visited[row][col]:
                return

            # 如果从父节点过来，记录边的遍历（前进）
            if parent_row is not None and parent_col is not None:
                edge = tuple(sorted([(parent_row, parent_col), (row, col)]))
                if edge in temp_remaining:
                    temp_remaining.remove(edge)
                    temp_traversed.append(edge)
                    self.steps.append({
                        'type': 'traverse_edge',
                        'action': 'forward',  # 前进
                        'edge': edge,
                        'from': (parent_row, parent_col),
                        'to': (row, col),
                        'remaining_edges': temp_remaining.copy(),
                        'traversed_edges': temp_traversed.copy(),
                        'visited': [row[:] for row in self.visited],
                        'current_node': (row, col),
                        'call_stack': call_stack.copy()
                    })

            # 标记访问
            self.visited[row][col] = True
            self.visit_order.append((row, col))
            call_stack.append((row, col))

            self.steps.append({
                'type': 'visit_node',
                'node': (row, col),
                'remaining_edges': temp_remaining.copy(),
                'traversed_edges': temp_traversed.copy(),
                'visited': [row[:] for row in self.visited],
                'current_node': (row, col),
                'call_stack': call_stack.copy()
            })

            # 递归访问邻居
            for dr, dc in self.directions:
                new_row, new_col = row + dr, col + dc

                # 检查邻居是否在范围内且不是障碍物
                if (0 <= new_row < self.rows and 0 <= new_col < self.cols and
                    self.matrix[new_row][new_col] != 0):

                    if not self.visited[new_row][new_col]:
                        dfs(new_row, new_col, row, col)

                        # 从递归返回后，添加回溯步骤
                        self.steps.append({
                            'type': 'backtrack',
                            'action': 'backtrack',  # 回溯
                            'from': (new_row, new_col),
                            'to': (row, col),
                            'remaining_edges': temp_remaining.copy(),
                            'traversed_edges': temp_traversed.copy(),
                            'visited': [row[:] for row in self.visited],
                            'current_node': (row, col),
                            'call_stack': call_stack.copy()
                        })
                    else:
                        # 检查是否有未遍历的边
                        edge = tuple(sorted([(row, col), (new_row, new_col)]))
                        if edge in temp_remaining and not (new_row == parent_row and new_col == parent_col):
                            temp_remaining.remove(edge)
                            temp_traversed.append(edge)
                            self.steps.append({
                                'type': 'traverse_edge',
                                'action': 'cross_edge',  # 横向边
                                'edge': edge,
                                'from': (row, col),
                                'to': (new_row, new_col),
                                'remaining_edges': temp_remaining.copy(),
                                'traversed_edges': temp_traversed.copy(),
                                'visited': [row[:] for row in self.visited],
                                'current_node': (row, col),
                                'call_stack': call_stack.copy()
                            })

            # 从当前节点返回前，弹出调用栈
            if call_stack:
                call_stack.pop()

        # 从起点开始DFS
        dfs(self.start_row, self.start_col)

    def draw_graph(self, ax, step_data):
        """
        绘制图的当前状态（专业美化版）

        Args:
            ax: matplotlib轴对象
            step_data: 当前步骤的数据
        """
        ax.clear()

        # Set background color - professional style
        ax.set_facecolor('#f8f9fa')

        # Adjust limits to provide much more space and avoid title overlap
        ax.set_xlim(-1.0, self.cols)
        ax.set_ylim(self.rows, -1.5)  # Inverted, with extra space at top
        ax.set_aspect('equal')

        # Draw refined grid
        for i in range(self.rows + 1):
            ax.axhline(y=i - 0.5, color='#dee2e6', linewidth=1, alpha=0.6, linestyle='-')
        for j in range(self.cols + 1):
            ax.axvline(x=j - 0.5, color='#dee2e6', linewidth=1, alpha=0.6, linestyle='-')

        # 绘制剩余的边（未遍历的边）- 使用专业配色
        remaining_edges = step_data.get('remaining_edges', set())
        for edge in remaining_edges:
            (r1, c1), (r2, c2) = edge
            ax.plot([c1, c2], [r1, r2], color='#6c757d', linewidth=2.5,
                   alpha=0.4, zorder=1, solid_capstyle='round')

        # 已遍历的边直接消失，不再绘制

        # 高亮当前正在操作的边 - 使用专业配色和阴影效果
        step_type = step_data.get('type')
        action = step_data.get('action', '')

        if step_type == 'traverse_edge' and action == 'forward':
            # 前进的边 - 现代绿色渐变
            edge = step_data['edge']
            (r1, c1), (r2, c2) = edge
            # 绘制阴影
            ax.plot([c1, c2], [r1, r2], color='#28a745', linewidth=7,
                   alpha=0.3, zorder=1.8, solid_capstyle='round')
            # 绘制主线
            ax.plot([c1, c2], [r1, r2], color='#20c997', linewidth=5,
                   alpha=0.95, zorder=2, solid_capstyle='round')
            # Label - smaller font
            ax.annotate('Forward', xy=((c1+c2)/2, (r1+r2)/2 - 0.15),
                       fontsize=7, color='#28a745', fontweight='bold',
                       ha='center', style='italic',
                       bbox=dict(boxstyle='round,pad=0.2', facecolor='white',
                                edgecolor='#28a745', alpha=0.8, linewidth=1))
        elif step_type == 'backtrack':
            # 回溯的边 - 现代橙色
            from_node = step_data['from']
            to_node = step_data['to']
            # 绘制阴影
            ax.plot([from_node[1], to_node[1]], [from_node[0], to_node[0]],
                   color='#fd7e14', linewidth=7, alpha=0.3, zorder=1.8,
                   linestyle='--', solid_capstyle='round')
            # 绘制主线
            ax.plot([from_node[1], to_node[1]], [from_node[0], to_node[0]],
                   color='#ffc107', linewidth=5, alpha=0.95, zorder=2,
                   linestyle='--', solid_capstyle='round')
            # Label - smaller font
            ax.annotate('Backtrack', xy=((from_node[1]+to_node[1])/2,
                                    (from_node[0]+to_node[0])/2 - 0.15),
                       fontsize=7, color='#fd7e14', fontweight='bold',
                       ha='center', style='italic',
                       bbox=dict(boxstyle='round,pad=0.2', facecolor='white',
                                edgecolor='#fd7e14', alpha=0.8, linewidth=1))
        elif step_type == 'traverse_edge' and action == 'cross_edge':
            # 横向边 - 现代紫色
            edge = step_data['edge']
            (r1, c1), (r2, c2) = edge
            # 绘制阴影
            ax.plot([c1, c2], [r1, r2], color='#6f42c1', linewidth=7,
                   alpha=0.3, zorder=1.8, solid_capstyle='round')
            # 绘制主线
            ax.plot([c1, c2], [r1, r2], color='#a855f7', linewidth=5,
                   alpha=0.95, zorder=2, solid_capstyle='round')
            # Label - smaller font
            ax.annotate('Cross', xy=((c1+c2)/2, (r1+r2)/2 - 0.15),
                       fontsize=7, color='#6f42c1', fontweight='bold',
                       ha='center', style='italic',
                       bbox=dict(boxstyle='round,pad=0.2', facecolor='white',
                                edgecolor='#6f42c1', alpha=0.8, linewidth=1))

        # 绘制调用栈路径（用现代青色连线）
        call_stack = step_data.get('call_stack', [])
        if len(call_stack) > 1:
            for i in range(len(call_stack) - 1):
                r1, c1 = call_stack[i]
                r2, c2 = call_stack[i + 1]
                ax.plot([c1, c2], [r1, r2], color='#17a2b8', linewidth=2.5,
                       alpha=0.4, zorder=0.5, linestyle=':', solid_capstyle='round')

        # 绘制节点
        visited = step_data.get('visited', [[False] * self.cols for _ in range(self.rows)])
        current_node = step_data.get('current_node')

        for i in range(self.rows):
            for j in range(self.cols):
                # 检查节点是否为0（不存在的节点）
                if self.matrix[i][j] == 0:
                    # 值为0的节点 - 用现代风格障碍物标记
                    # 绘制障碍物背景
                    rect = FancyBboxPatch((j-0.35, i-0.35), 0.7, 0.7,
                                         boxstyle="round,pad=0.05",
                                         facecolor='#495057', edgecolor='#343a40',
                                         linewidth=2, alpha=0.6, zorder=2.5)
                    ax.add_patch(rect)
                    # 绘制X标记
                    ax.plot([j-0.2, j+0.2], [i-0.2, i+0.2], color='#adb5bd',
                           linewidth=3, alpha=0.8, zorder=2.6)
                    ax.plot([j-0.2, j+0.2], [i+0.2, i-0.2], color='#adb5bd',
                           linewidth=3, alpha=0.8, zorder=2.6)
                    continue

                # 计算该节点剩余的边数
                remaining_count = 0
                for edge in remaining_edges:
                    if (i, j) in edge:
                        remaining_count += 1

                # 节点颜色 - 使用现代专业配色
                if (i, j) == (self.start_row, self.start_col):
                    # 起点 - 现代橙色渐变
                    color = '#ff6b35'
                    size = 550
                    edgecolor = '#e63946'
                    linewidth = 4
                    alpha = 1.0
                    # 添加光晕效果
                    ax.scatter([j], [i], c='#ff6b35', s=700, alpha=0.2, zorder=2.8)
                elif current_node and current_node == (i, j):
                    # 当前节点 - 现代红色
                    color = '#dc3545'
                    size = 550
                    edgecolor = '#c82333'
                    linewidth = 4
                    alpha = 1.0
                    # 添加脉冲效果
                    ax.scatter([j], [i], c='#dc3545', s=700, alpha=0.3, zorder=2.8)
                elif (i, j) in call_stack:
                    # 在调用栈中的节点 - 现代青色
                    color = '#17a2b8'
                    size = 450
                    edgecolor = '#138496'
                    linewidth = 3
                    alpha = 0.95
                elif visited[i][j]:
                    # 已访问的节点 - 现代绿色
                    color = '#28a745'
                    size = 400
                    edgecolor='#218838'
                    linewidth = 2.5
                    alpha = 0.85
                else:
                    # 未访问的节点 - 现代蓝色
                    color = '#007bff'
                    size = 400
                    edgecolor = '#0056b3'
                    linewidth = 2.5
                    alpha = 0.7

                # 绘制节点阴影
                ax.scatter([j], [i], c='black', s=size+50, alpha=0.15, zorder=2.9)

                # 绘制节点
                ax.scatter([j], [i], c=color, s=size, zorder=3,
                          edgecolors=edgecolor, linewidths=linewidth, alpha=alpha)

                # 显示剩余边数 - 使用更好的字体样式
                text_color = 'white' if (i, j) == (self.start_row, self.start_col) or \
                            (current_node and current_node == (i, j)) else '#212529'
                ax.text(j, i, str(remaining_count),
                       ha='center', va='center', fontsize=12, fontweight='bold',
                       color=text_color, zorder=4,
                       bbox=dict(boxstyle='circle,pad=0.1', facecolor=color,
                                edgecolor='none', alpha=0.3) if remaining_count > 0 else None)

        # Title information - Modern professional style
        if step_type == 'visit_node':
            node = step_data['node']
            title = f"🔍 Visit Node ({node[0]}, {node[1]})"
            title_color = '#28a745'
        elif step_type == 'traverse_edge':
            from_node = step_data['from']
            to_node = step_data['to']
            if action == 'forward':
                title = f"➡️ Forward: ({from_node[0]},{from_node[1]}) → ({to_node[0]},{to_node[1]})"
                title_color = '#20c997'
            else:
                title = f"↔️ Cross Edge: ({from_node[0]},{from_node[1]}) ↔ ({to_node[0]},{to_node[1]})"
                title_color = '#a855f7'
        elif step_type == 'backtrack':
            from_node = step_data['from']
            to_node = step_data['to']
            title = f"↩️ Backtrack: ({from_node[0]},{from_node[1]}) ⤴ ({to_node[0]},{to_node[1]})"
            title_color = '#ffc107'
        else:
            title = "DFS Graph Traversal Visualization"
            title_color = '#212529'

        total_edges = len(self.all_edges)
        remaining_count = len(remaining_edges)
        traversed_edges = step_data.get('traversed_edges', [])
        traversed_count = len(traversed_edges)

        # Calculate progress percentage
        progress = (traversed_count / total_edges * 100) if total_edges > 0 else 0

        # Set title - Compact format to avoid overlap
        title_line1 = f"{title}"
        title_line2 = f"Progress: {progress:.1f}% | Total: {total_edges} | Traversed: {traversed_count} | Remaining: {remaining_count} | Stack: {len(call_stack)}"

        ax.set_title(f"{title_line1}\n{title_line2}",
                    fontsize=9, fontweight='bold',
                    color=title_color, pad=10,
                    bbox=dict(boxstyle='round,pad=0.4', facecolor='white',
                             edgecolor=title_color, linewidth=1.2, alpha=0.95))

        # Set axis labels - Better style
        ax.set_xlabel('Column', fontsize=11, fontweight='bold', color='#495057')
        ax.set_ylabel('Row', fontsize=11, fontweight='bold', color='#495057')

        # 设置刻度样式
        ax.set_xticks(range(self.cols))
        ax.set_yticks(range(self.rows))
        ax.tick_params(axis='both', which='major', labelsize=10,
                      colors='#6c757d', width=1.5, length=6)

        # 添加边框
        for spine in ax.spines.values():
            spine.set_edgecolor('#dee2e6')
            spine.set_linewidth(2)

    def animate(self):
        """创建动画 - 专业美化版"""
        # 创建图形，使用更专业的样式
        fig = plt.figure(figsize=(FIGURE_WIDTH, FIGURE_HEIGHT), facecolor='#ffffff')
        ax = fig.add_subplot(111)

        # 设置整体样式
        fig.patch.set_facecolor('#ffffff')

        def update(frame):
            if frame < len(self.steps):
                self.draw_graph(ax, self.steps[frame])
            return ax,

        anim = FuncAnimation(fig, update, frames=len(self.steps),
                           interval=ANIMATION_SPEED, repeat=True, blit=False)

        # 调整布局，留出更多空间
        plt.tight_layout(pad=2.0)

        # Set window title
        fig.canvas.manager.set_window_title('DFS Graph Traversal Visualization - Professional')

        plt.show()

    def save_animation(self, filename='dfs_animation.gif'):
        """保存动画为GIF - 专业美化版"""
        fig = plt.figure(figsize=(FIGURE_WIDTH, FIGURE_HEIGHT), facecolor='#ffffff')
        ax = fig.add_subplot(111)
        fig.patch.set_facecolor('#ffffff')

        def update(frame):
            if frame < len(self.steps):
                self.draw_graph(ax, self.steps[frame])
            return ax,

        # GIF的fps根据ANIMATION_SPEED计算
        fps = 1000 / ANIMATION_SPEED
        anim = FuncAnimation(fig, update, frames=len(self.steps),
                           interval=ANIMATION_SPEED, repeat=True, blit=False)

        plt.tight_layout(pad=2.0)

        print(f"⏳ 正在保存动画到: {filename}")
        anim.save(filename, writer='pillow', fps=fps, dpi=100)
        print(f"✅ 动画已成功保存到: {filename}")
        plt.close()


def main():
    """主函数 - 专业美化版"""
    # 使用配置的矩阵函数创建矩阵
    matrix = MATRIX_FUNCTION(MATRIX_ROWS, MATRIX_COLS)

    # 打印专业的标题
    print("\n" + "╔" + "═" * 78 + "╗")
    print("║" + " " * 20 + "🎯 DFS 图遍历可视化系统 - 专业版" + " " * 22 + "║")
    print("╚" + "═" * 78 + "╝")

    print(f"\n📋 配置信息:")
    print(f"   ├─ 使用矩阵: {MATRIX_FUNCTION.__name__}")
    print(f"   ├─ 矩阵大小: {len(matrix)}×{len(matrix[0])}")
    print(f"   ├─ 起始点: ({START_ROW}, {START_COL})")
    print(f"   └─ 动画速度: {ANIMATION_SPEED}ms/帧")

    # 统计信息
    total_nodes = len(matrix) * len(matrix[0])
    obstacle_count = sum(1 for row in matrix for val in row if val == 0)
    valid_nodes = total_nodes - obstacle_count
    total_edges = sum(sum(row) for row in matrix) // 2

    print(f"\n📊 图统计:")
    print(f"   ├─ 总节点数: {total_nodes}")
    print(f"   ├─ 有效节点: {valid_nodes}")
    if obstacle_count > 0:
        print(f"   ├─ 障碍物数: {obstacle_count} ({obstacle_count/total_nodes*100:.1f}%)")
    print(f"   └─ 总边数: {total_edges}")

    # 创建可视化器
    print(f"\n⚙️  正在生成DFS遍历步骤...")
    visualizer = GraphDFSVisualizer(matrix, start_row=START_ROW, start_col=START_COL)

    print(f"   ✓ 已生成 {len(visualizer.steps)} 个遍历步骤")

    # 图例说明 - 使用更专业的格式
    print(f"\n🎨 可视化图例:")
    print(f"\n   边的类型:")
    print(f"   ├─ 灰色线 ━━━━ 未遍历的边")
    print(f"   ├─ 绿色粗线 ━━━━ 前进边（探索新节点）")
    print(f"   ├─ 橙色虚线 ┄┄┄┄ 回溯边（返回父节点）")
    print(f"   ├─ 紫色粗线 ━━━━ 横向边（已访问节点间）")
    print(f"   ├─ 青色点线 ┈┈┈┈ DFS调用栈路径")
    print(f"   └─ 已遍历的边会消失")

    print(f"\n   节点的类型:")
    print(f"   ├─ ⬛ 灰色方块 → 障碍物（值为0）")
    print(f"   ├─ 🟠 橙色圆圈 → 起点 ({START_ROW}, {START_COL})")
    print(f"   ├─ 🔴 红色圆圈 → 当前访问节点")
    print(f"   ├─ 🔵 青色圆圈 → DFS调用栈中")
    print(f"   ├─ 🟢 绿色圆圈 → 已访问节点")
    print(f"   ├─ 🔵 蓝色圆圈 → 未访问节点")
    print(f"   └─ 数字 → 剩余未遍历的边数")

    print(f"\n🚀 正在启动可视化动画...")
    print(f"   提示: 关闭窗口可退出程序\n")

    # 显示动画
    visualizer.animate()

    print(f"\n✅ 可视化完成！")


if __name__ == "__main__":
    main()