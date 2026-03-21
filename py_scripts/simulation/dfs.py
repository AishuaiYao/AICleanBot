"""
DFS遍历10x10矩阵的交互式可视化演示（包含回溯路径）- 优化版
使用matplotlib绘制节点和边，支持自动播放和手动控制
- P键：播放/暂停自动演示
- 空格键：前进一步（暂停模式）
- 退格键(Backspace)：后退一步（暂停模式）
起点：(3, 4)

优化点：
1. 减少深拷贝操作，使用浅拷贝或引用
2. 提取重复的边处理逻辑
3. 使用类常量替代魔法数字
4. 优化条件判断逻辑
5. 缓存重复计算的值
"""
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.patches import FancyBboxPatch, Circle
import numpy as np
from mock_data_generator import *
import time
from matplotlib.animation import FuncAnimation
from copy import deepcopy

# 设置matplotlib样式
plt.style.use('seaborn-v0_8-darkgrid')

# ==================== 配置参数 ====================
# 选择要使用的矩阵函数
MATRIX_FUNCTION = matrix2  # 修改这里来切换不同的矩阵

# 动画速度控制（单位：毫秒/帧）
# 数值越小速度越快，数值越大速度越慢
# 推荐范围：100-1000
ANIMATION_SPEED = 400  # 默认400毫秒每帧

# 起点坐标
START_ROW = 4
START_COL = 2

# 图形大小
FIGURE_WIDTH = 14
FIGURE_HEIGHT = 13
# ==================================================

class InteractiveDFSVisualizer:
    # ==================== 颜色常量 ====================
    # 背景色
    BG_COLOR = '#f8f9fa'
    GRID_COLOR = '#dee2e6'
    
    # 边的颜色
    EDGE_REMAINING = '#6c757d'
    EDGE_FORWARD = '#20c997'
    EDGE_FORWARD_SHADOW = '#28a745'
    EDGE_BACKTRACK = '#ffc107'
    EDGE_BACKTRACK_SHADOW = '#fd7e14'
    EDGE_CROSS = '#a855f7'
    EDGE_CROSS_SHADOW = '#6f42c1'
    EDGE_OBSTACLE = '#dc3545'
    EDGE_OBSTACLE_BLOCKED = '#e74c3c'
    EDGE_BOUNDARY = '#fd7e14'
    EDGE_BOUNDARY_BLOCKED = '#ff8c00'
    EDGE_STACK = '#17a2b8'
    
    # 节点颜色
    NODE_START = '#ff6b35'
    NODE_START_EDGE = '#e63946'
    NODE_CURRENT = '#dc3545'
    NODE_CURRENT_EDGE = '#c82333'
    NODE_STACK = '#17a2b8'
    NODE_STACK_EDGE = '#138496'
    NODE_VISITED = '#28a745'
    NODE_VISITED_EDGE = '#218838'
    NODE_UNVISITED = '#007bff'
    NODE_UNVISITED_EDGE = '#0056b3'
    NODE_OBSTACLE = '#495057'
    NODE_OBSTACLE_EDGE = '#343a40'
    NODE_OBSTACLE_X = '#adb5bd'
    
    # 尺寸常量
    NODE_SIZE_START = 550
    NODE_SIZE_CURRENT = 550
    NODE_SIZE_STACK = 450
    NODE_SIZE_NORMAL = 400
    
    EDGE_WIDTH_NORMAL = 2.5
    EDGE_WIDTH_HIGHLIGHT = 5
    EDGE_WIDTH_SHADOW = 7
    # ==================================================
    
    def __init__(self, matrix, start_row=START_ROW, start_col=START_COL):
        """
        初始化交互式DFS可视化器

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

        # 访问状态
        self.visited = [[False] * self.cols for _ in range(self.rows)]
        self.visit_order = []

        # 边的集合：使用集合存储所有边（无向边，用排序后的元组表示）
        self.all_edges = set()
        self.remaining_edges = set()
        self.traversed_edges = []

        # 四个方向
        self.directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]

        # 初始化所有边（包括与障碍物和边界的边）
        self._initialize_edges()

        # DFS遍历步骤记录
        self.steps = []
        self.current_step = 0

        # 执行DFS收集所有步骤
        self._collect_dfs_steps()

        # matplotlib图形对象
        self.fig = None
        self.ax = None
        self.anim = None
        
        # 播放控制
        self.is_playing = False

    def _initialize_edges(self):
        """初始化所有边（提取为独立方法以提高可读性）"""
        for i in range(self.rows):
            for j in range(self.cols):
                # 跳过障碍物节点（值为0的节点）
                if self.matrix[i][j] == 0:
                    continue

                for di, dj in self.directions:
                    ni, nj = i + di, j + dj
                    edge = self._create_edge(i, j, ni, nj)
                    if edge:
                        self.all_edges.add(edge)

        self.remaining_edges = self.all_edges.copy()

    def _create_edge(self, r1, c1, r2, c2):
        """
        创建边的辅助方法，统一边的创建逻辑
        
        Returns:
            边的元组表示，或None如果不需要创建
        """
        if 0 <= r2 < self.rows and 0 <= c2 < self.cols:
            if self.matrix[r2][c2] != 0:
                # 正常边：连接两个非障碍物节点
                return tuple(sorted([(r1, c1), (r2, c2)]))
            else:
                # 障碍物边：从当前节点指向障碍物
                return ((r1, c1), (r2, c2), 'obstacle')
        else:
            # 边界边：从当前节点指向边界外
            return ((r1, c1), (r2, c2), 'boundary')

    def _create_step_data(self, step_type, temp_remaining, temp_traversed, call_stack, **kwargs):
        """
        创建步骤数据的辅助方法，减少重复代码
        
        Args:
            step_type: 步骤类型
            temp_remaining: 剩余边集合（引用）
            temp_traversed: 已遍历边列表（引用）
            call_stack: 调用栈（引用）
            **kwargs: 其他步骤特定的数据
        
        Returns:
            步骤数据字典
        """
        # 只深拷贝visited，其他使用引用（因为我们会在每步创建新的副本）
        step_data = {
            'type': step_type,
            'remaining_edges': temp_remaining.copy(),
            'traversed_edges': temp_traversed[:],  # 浅拷贝列表
            'visited': [row[:] for row in self.visited],  # 深拷贝visited
            'call_stack': call_stack[:]  # 浅拷贝列表
        }
        step_data.update(kwargs)
        return step_data

    def _add_edge_step(self, action, edge, from_node, to_node, temp_remaining, 
                       temp_traversed, call_stack, current_node):
        """添加边遍历步骤的辅助方法"""
        if edge in temp_remaining:
            temp_remaining.remove(edge)
            temp_traversed.append(edge)
            self.steps.append(self._create_step_data(
                'traverse_edge',
                temp_remaining,
                temp_traversed,
                call_stack,
                action=action,
                edge=edge,
                from_=from_node,
                to=to_node,
                current_node=current_node
            ))

    def _collect_dfs_steps(self):
        """收集DFS遍历的所有步骤（包括回溯）"""
        # 重置状态
        self.visited = [[False] * self.cols for _ in range(self.rows)]
        self.visit_order = []
        temp_remaining = self.all_edges.copy()
        temp_traversed = []

        # 记录DFS调用栈，用于回溯可视化
        call_stack = []

        def dfs(row, col, parent_row=None, parent_col=None):
            # 边界检查和障碍物检查合并
            if not (0 <= row < self.rows and 0 <= col < self.cols) or \
               self.matrix[row][col] == 0 or self.visited[row][col]:
                return

            # 如果从父节点过来，记录边的遍历（前进）
            if parent_row is not None:
                edge = tuple(sorted([(parent_row, parent_col), (row, col)]))
                self._add_edge_step('forward', edge, (parent_row, parent_col), 
                                   (row, col), temp_remaining, temp_traversed, 
                                   call_stack, (row, col))

            # 标记访问
            self.visited[row][col] = True
            self.visit_order.append((row, col))
            call_stack.append((row, col))

            self.steps.append(self._create_step_data(
                'visit_node',
                temp_remaining,
                temp_traversed,
                call_stack,
                node=(row, col),
                current_node=(row, col)
            ))

            # 递归访问邻居（尝试所有四个方向）
            for dr, dc in self.directions:
                new_row, new_col = row + dr, col + dc

                # 检查是否超出边界
                if not (0 <= new_row < self.rows and 0 <= new_col < self.cols):
                    edge = ((row, col), (new_row, new_col), 'boundary')
                    self._add_edge_step('blocked_boundary', edge, (row, col),
                                       (new_row, new_col), temp_remaining, 
                                       temp_traversed, call_stack, (row, col))
                    continue

                # 检查是否是障碍物
                if self.matrix[new_row][new_col] == 0:
                    edge = ((row, col), (new_row, new_col), 'obstacle')
                    self._add_edge_step('blocked_obstacle', edge, (row, col),
                                       (new_row, new_col), temp_remaining,
                                       temp_traversed, call_stack, (row, col))
                    continue

                # 正常的非障碍物节点
                if not self.visited[new_row][new_col]:
                    dfs(new_row, new_col, row, col)

                    # 从递归返回后，添加回溯步骤
                    self.steps.append(self._create_step_data(
                        'backtrack',
                        temp_remaining,
                        temp_traversed,
                        call_stack,
                        action='backtrack',
                        from_=(new_row, new_col),
                        to=(row, col),
                        current_node=(row, col)
                    ))
                else:
                    # 检查是否有未遍历的边
                    edge = tuple(sorted([(row, col), (new_row, new_col)]))
                    if edge in temp_remaining and not (new_row == parent_row and new_col == parent_col):
                        self._add_edge_step('cross_edge', edge, (row, col),
                                           (new_row, new_col), temp_remaining,
                                           temp_traversed, call_stack, (row, col))

            # 从当前节点返回前，弹出调用栈
            if call_stack:
                call_stack.pop()

        # 从起点开始DFS
        dfs(self.start_row, self.start_col)

    def _draw_edge(self, ax, c1, r1, c2, r2, color, linewidth, alpha=1.0, 
                   linestyle='-', shadow=False, shadow_color=None):
        """绘制边的辅助方法"""
        if shadow and shadow_color:
            ax.plot([c1, c2], [r1, r2], color=shadow_color, 
                   linewidth=linewidth + 2, alpha=alpha * 0.3, 
                   zorder=1.8, linestyle=linestyle, solid_capstyle='round')
        ax.plot([c1, c2], [r1, r2], color=color, linewidth=linewidth,
               alpha=alpha, zorder=2 if not shadow else 2,
               linestyle=linestyle, solid_capstyle='round')

    def _draw_edge_label(self, ax, x, y, text, color):
        """绘制边标签的辅助方法"""
        ax.annotate(text, xy=(x, y - 0.15), fontsize=7, color=color,
                   fontweight='bold', ha='center', style='italic',
                   bbox=dict(boxstyle='round,pad=0.2', facecolor='white',
                            edgecolor=color, alpha=0.8, linewidth=1))

    def _draw_highlighted_edge(self, ax, step_data):
        """绘制高亮边（当前操作的边）"""
        step_type = step_data.get('type')
        action = step_data.get('action', '')

        edge_configs = {
            ('traverse_edge', 'forward'): {
                'color': self.EDGE_FORWARD,
                'shadow_color': self.EDGE_FORWARD_SHADOW,
                'label': 'Forward',
                'linestyle': '-'
            },
            ('backtrack', 'backtrack'): {
                'color': self.EDGE_BACKTRACK,
                'shadow_color': self.EDGE_BACKTRACK_SHADOW,
                'label': 'Backtrack',
                'linestyle': '--'
            },
            ('traverse_edge', 'cross_edge'): {
                'color': self.EDGE_CROSS,
                'shadow_color': self.EDGE_CROSS_SHADOW,
                'label': 'Cross',
                'linestyle': '-'
            },
            ('traverse_edge', 'blocked_obstacle'): {
                'color': self.EDGE_OBSTACLE_BLOCKED,
                'shadow_color': self.EDGE_OBSTACLE,
                'label': 'Blocked!',
                'linestyle': ':'
            },
            ('traverse_edge', 'blocked_boundary'): {
                'color': self.EDGE_BOUNDARY_BLOCKED,
                'shadow_color': self.EDGE_BOUNDARY,
                'label': 'Boundary!',
                'linestyle': ':'
            }
        }

        config = edge_configs.get((step_type, action))
        if not config:
            return

        # 获取边的坐标
        if step_type == 'traverse_edge':
            from_node = step_data.get('from_')
            to_node = step_data.get('to')
        else:  # backtrack
            from_node = step_data.get('from_')
            to_node = step_data.get('to')

        if not from_node or not to_node:
            return

        r1, c1 = from_node
        r2, c2 = to_node

        # 处理边界情况
        if action == 'blocked_boundary':
            if 0 <= c1 < self.cols and 0 <= r1 < self.rows:
                c2 = max(-0.5, min(self.cols - 0.5, c2))
                r2 = max(-0.5, min(self.rows - 0.5, r2))

        # 绘制边
        self._draw_edge(ax, c1, r1, c2, r2, config['color'], 
                       self.EDGE_WIDTH_HIGHLIGHT, alpha=0.95,
                       linestyle=config['linestyle'], shadow=True,
                       shadow_color=config['shadow_color'])

        # 绘制标签
        self._draw_edge_label(ax, (c1 + c2) / 2, (r1 + r2) / 2,
                             config['label'], config['shadow_color'])

    def draw_graph(self, ax, step_data):
        """
        绘制图的当前状态（专业美化版）

        Args:
            ax: matplotlib轴对象
            step_data: 当前步骤的数据
        """
        ax.clear()

        # Set background color - professional style
        ax.set_facecolor(self.BG_COLOR)

        # Adjust limits to provide much more space and avoid title overlap
        ax.set_xlim(-1.0, self.cols)
        ax.set_ylim(self.rows, -2.0)  # Inverted, with extra space at top for title
        ax.set_aspect('equal')

        # Draw refined grid
        for i in range(self.rows + 1):
            ax.axhline(y=i - 0.5, color=self.GRID_COLOR, linewidth=1, alpha=0.6, linestyle='-')
        for j in range(self.cols + 1):
            ax.axvline(x=j - 0.5, color=self.GRID_COLOR, linewidth=1, alpha=0.6, linestyle='-')

        # 绘制剩余的边（未遍历的边）
        remaining_edges = step_data.get('remaining_edges', set())
        for edge in remaining_edges:
            if len(edge) == 2:
                # 正常边：连接两个节点
                (r1, c1), (r2, c2) = edge
                self._draw_edge(ax, c1, r1, c2, r2, self.EDGE_REMAINING,
                               self.EDGE_WIDTH_NORMAL, alpha=0.4)
            elif len(edge) == 3:
                # 特殊边：障碍物边或边界边
                (r1, c1), (r2, c2), edge_type = edge
                color = self.EDGE_OBSTACLE if edge_type == 'obstacle' else self.EDGE_BOUNDARY
                
                # 计算终点（边界边需要特殊处理）
                if edge_type == 'boundary':
                    if r2 < 0:
                        end_r, end_c = -0.4, c1
                    elif r2 >= self.rows:
                        end_r, end_c = self.rows - 0.6, c1
                    elif c2 < 0:
                        end_r, end_c = r1, -0.4
                    elif c2 >= self.cols:
                        end_r, end_c = r1, self.cols - 0.6
                    else:
                        end_r, end_c = r2, c2
                else:
                    end_r, end_c = r2, c2
                
                self._draw_edge(ax, c1, r1, end_c, end_r, color,
                               self.EDGE_WIDTH_NORMAL, alpha=0.5, linestyle=':')

        # 绘制调用栈路径
        call_stack = step_data.get('call_stack', [])
        if len(call_stack) > 1:
            for i in range(len(call_stack) - 1):
                r1, c1 = call_stack[i]
                r2, c2 = call_stack[i + 1]
                self._draw_edge(ax, c1, r1, c2, r2, self.EDGE_STACK,
                               self.EDGE_WIDTH_NORMAL, alpha=0.4, linestyle=':')

        # 高亮当前正在操作的边
        self._draw_highlighted_edge(ax, step_data)

        # 绘制节点
        self._draw_nodes(ax, step_data)

        # 设置标题和标签
        self._set_title_and_labels(ax, step_data)

    def _draw_nodes(self, ax, step_data):
        """绘制所有节点"""
        visited = step_data.get('visited', [[False] * self.cols for _ in range(self.rows)])
        current_node = step_data.get('current_node')
        call_stack = step_data.get('call_stack', [])
        traversed_edges = step_data.get('traversed_edges', [])

        for i in range(self.rows):
            for j in range(self.cols):
                if self.matrix[i][j] == 0:
                    self._draw_obstacle_node(ax, i, j)
                else:
                    self._draw_normal_node(ax, i, j, visited, current_node, 
                                          call_stack, traversed_edges)

    def _draw_obstacle_node(self, ax, i, j):
        """绘制障碍物节点"""
        rect = FancyBboxPatch((j-0.35, i-0.35), 0.7, 0.7,
                             boxstyle="round,pad=0.05",
                             facecolor=self.NODE_OBSTACLE,
                             edgecolor=self.NODE_OBSTACLE_EDGE,
                             linewidth=2, alpha=0.6, zorder=2.5)
        ax.add_patch(rect)
        # 绘制X标记
        ax.plot([j-0.2, j+0.2], [i-0.2, i+0.2], color=self.NODE_OBSTACLE_X,
               linewidth=3, alpha=0.8, zorder=2.6)
        ax.plot([j-0.2, j+0.2], [i+0.2, i-0.2], color=self.NODE_OBSTACLE_X,
               linewidth=3, alpha=0.8, zorder=2.6)

    def _draw_normal_node(self, ax, i, j, visited, current_node, call_stack, traversed_edges):
        """绘制普通节点"""
        # 计算剩余边数
        initial_edge_count = self.matrix[i][j]
        traversed_count = sum(1 for edge in traversed_edges if (i, j) in edge)
        remaining_count = initial_edge_count - traversed_count

        # 确定节点样式
        node_style = self._get_node_style(i, j, visited, current_node, call_stack)

        # 绘制节点阴影
        ax.scatter([j], [i], c='black', s=node_style['size']+50, 
                  alpha=0.15, zorder=2.9)

        # 绘制光晕效果（起点和当前节点）
        if node_style.get('glow'):
            ax.scatter([j], [i], c=node_style['color'], 
                      s=node_style['size']+150, alpha=0.2, zorder=2.8)

        # 绘制节点
        ax.scatter([j], [i], c=node_style['color'], s=node_style['size'],
                  zorder=3, edgecolors=node_style['edgecolor'],
                  linewidths=node_style['linewidth'], alpha=node_style['alpha'])

        # 显示剩余边数
        text_color = 'white' if node_style.get('white_text') else '#212529'
        ax.text(j, i, str(remaining_count), ha='center', va='center',
               fontsize=12, fontweight='bold', color=text_color, zorder=4,
               bbox=dict(boxstyle='circle,pad=0.1', facecolor=node_style['color'],
                        edgecolor='none', alpha=0.3) if remaining_count > 0 else None)

    def _get_node_style(self, i, j, visited, current_node, call_stack):
        """获取节点样式配置"""
        if (i, j) == (self.start_row, self.start_col):
            return {
                'color': self.NODE_START,
                'size': self.NODE_SIZE_START,
                'edgecolor': self.NODE_START_EDGE,
                'linewidth': 4,
                'alpha': 1.0,
                'glow': True,
                'white_text': True
            }
        elif current_node and current_node == (i, j):
            return {
                'color': self.NODE_CURRENT,
                'size': self.NODE_SIZE_CURRENT,
                'edgecolor': self.NODE_CURRENT_EDGE,
                'linewidth': 4,
                'alpha': 1.0,
                'glow': True,
                'white_text': True
            }
        elif (i, j) in call_stack:
            return {
                'color': self.NODE_STACK,
                'size': self.NODE_SIZE_STACK,
                'edgecolor': self.NODE_STACK_EDGE,
                'linewidth': 3,
                'alpha': 0.95,
                'glow': False,
                'white_text': False
            }
        elif visited[i][j]:
            return {
                'color': self.NODE_VISITED,
                'size': self.NODE_SIZE_NORMAL,
                'edgecolor': self.NODE_VISITED_EDGE,
                'linewidth': 2.5,
                'alpha': 0.85,
                'glow': False,
                'white_text': False
            }
        else:
            return {
                'color': self.NODE_UNVISITED,
                'size': self.NODE_SIZE_NORMAL,
                'edgecolor': self.NODE_UNVISITED_EDGE,
                'linewidth': 2.5,
                'alpha': 0.7,
                'glow': False,
                'white_text': False
            }

    def _set_title_and_labels(self, ax, step_data):
        """设置标题和标签"""
        step_type = step_data.get('type')
        action = step_data.get('action', '')
        
        # 构建标题
        title, title_color = self._build_title(step_data, step_type, action)
        
        # 计算统计信息
        total_edges = len(self.all_edges)
        remaining_edges = step_data.get('remaining_edges', set())
        remaining_count = len(remaining_edges)
        traversed_count = len(step_data.get('traversed_edges', []))
        progress = (traversed_count / total_edges * 100) if total_edges > 0 else 0
        call_stack = step_data.get('call_stack', [])
        
        # 播放状态
        play_status = "[PLAYING]" if self.is_playing else "[PAUSED]"
        
        # 设置标题
        title_line1 = f"{title} | {play_status}"
        title_line2 = f"Step: {self.current_step + 1}/{len(self.steps)} | Progress: {progress:.1f}% | Total: {total_edges} | Traversed: {traversed_count} | Remaining: {remaining_count} | Stack: {len(call_stack)}"
        
        ax.set_title(f"{title_line1}\n{title_line2}", fontsize=9, fontweight='bold',
                    color=title_color, pad=10,
                    bbox=dict(boxstyle='round,pad=0.4', facecolor='white',
                             edgecolor=title_color, linewidth=1.2, alpha=0.95))
        
        # 设置轴标签
        ax.set_xlabel('Column', fontsize=11, fontweight='bold', color='#495057')
        ax.set_ylabel('Row', fontsize=11, fontweight='bold', color='#495057')
        
        # 设置刻度
        ax.set_xticks(range(self.cols))
        ax.set_yticks(range(self.rows))
        ax.tick_params(axis='both', which='major', labelsize=10,
                      colors='#6c757d', width=1.5, length=6)
        
        # 添加边框
        for spine in ax.spines.values():
            spine.set_edgecolor(self.GRID_COLOR)
            spine.set_linewidth(2)

    def _build_title(self, step_data, step_type, action):
        """构建标题文本和颜色"""
        if step_type == 'visit_node':
            node = step_data['node']
            return f"[VISIT] Node ({node[0]}, {node[1]})", self.NODE_VISITED
        elif step_type == 'traverse_edge':
            from_node = step_data.get('from_')
            to_node = step_data.get('to')
            title_map = {
                'forward': (f"[FORWARD] ({from_node[0]},{from_node[1]}) -> ({to_node[0]},{to_node[1]})", self.EDGE_FORWARD),
                'cross_edge': (f"[CROSS] ({from_node[0]},{from_node[1]}) <-> ({to_node[0]},{to_node[1]})", self.EDGE_CROSS),
                'blocked_obstacle': (f"[BLOCKED-OBSTACLE] ({from_node[0]},{from_node[1]}) X ({to_node[0]},{to_node[1]})", self.EDGE_OBSTACLE),
                'blocked_boundary': (f"[BLOCKED-BOUNDARY] ({from_node[0]},{from_node[1]}) X ({to_node[0]},{to_node[1]})", self.EDGE_BOUNDARY)
            }
            return title_map.get(action, (f"[EDGE] ({from_node[0]},{from_node[1]}) - ({to_node[0]},{to_node[1]})", '#6c757d'))
        elif step_type == 'backtrack':
            from_node = step_data.get('from_')
            to_node = step_data.get('to')
            return f"[BACKTRACK] ({from_node[0]},{from_node[1]}) <- ({to_node[0]},{to_node[1]})", self.EDGE_BACKTRACK
        else:
            return "DFS Graph Traversal Visualization", '#212529'

    def on_key_press(self, event):
        """
        处理键盘事件
        
        Args:
            event: 键盘事件对象
        """
        if event.key == 'p':  # P键 - 播放/暂停
            self.is_playing = not self.is_playing
            print(f"▶️  开始自动播放" if self.is_playing else f"⏸️  暂停自动播放")
            self.draw_graph(self.ax, self.steps[self.current_step])
            self.fig.canvas.draw()
        
        elif event.key == ' ' and not self.is_playing:  # 空格键 - 前进
            if self.current_step < len(self.steps) - 1:
                self.current_step += 1
                self.draw_graph(self.ax, self.steps[self.current_step])
                self.fig.canvas.draw()
                print(f"⏩ 前进到步骤 {self.current_step + 1}/{len(self.steps)}")
            else:
                print(f"⚠️  已经是最后一步了！")
        
        elif event.key == 'backspace' and not self.is_playing:  # 退格键 - 后退
            if self.current_step > 0:
                self.current_step -= 1
                self.draw_graph(self.ax, self.steps[self.current_step])
                self.fig.canvas.draw()
                print(f"⏪ 后退到步骤 {self.current_step + 1}/{len(self.steps)}")
            else:
                print(f"⚠️  已经是第一步了！")
        
        elif event.key == 'r':  # R键 - 重置
            self.current_step = 0
            self.draw_graph(self.ax, self.steps[self.current_step])
            self.fig.canvas.draw()
            print(f"🔄 重置到第一步")
        
        elif event.key == 'e':  # E键 - 跳到结束
            self.current_step = len(self.steps) - 1
            self.draw_graph(self.ax, self.steps[self.current_step])
            self.fig.canvas.draw()
            print(f"⏭️  跳到最后一步")
        
        elif event.key in ('q', 'escape'):  # Q或ESC键 - 退出
            print(f"👋 退出程序")
            plt.close(self.fig)

    def update_animation(self, frame):
        """
        动画更新函数（用于自动播放）
        
        Args:
            frame: 当前帧号（由FuncAnimation自动传入）
        """
        if self.is_playing:
            if self.current_step < len(self.steps) - 1:
                self.current_step += 1
            else:
                self.is_playing = False
                print(f"✅ 播放完成！")
        
        self.draw_graph(self.ax, self.steps[self.current_step])
        return self.ax,

    def show_interactive(self):
        """显示交互式可视化（支持自动播放和手动控制）"""
        self.fig = plt.figure(figsize=(FIGURE_WIDTH, FIGURE_HEIGHT), facecolor='#ffffff')
        self.ax = self.fig.add_subplot(111)
        self.fig.patch.set_facecolor('#ffffff')

        # 绘制初始状态
        self.draw_graph(self.ax, self.steps[self.current_step])

        # 连接键盘事件
        self.fig.canvas.mpl_connect('key_press_event', self.on_key_press)

        # 创建动画
        self.anim = FuncAnimation(self.fig, self.update_animation, 
                                 frames=len(self.steps),
                                 interval=ANIMATION_SPEED, 
                                 repeat=True, 
                                 blit=False)

        plt.tight_layout(pad=2.0)
        self.fig.canvas.manager.set_window_title('DFS Interactive Visualization - Press P to Play/Pause')
        plt.show()


def main():
    """主函数 - 交互式版本（支持自动播放）"""
    matrix = MATRIX_FUNCTION()

    # 打印专业的标题
    print("\n" + "╔" + "═" * 78 + "╗")
    print("║" + " " * 16 + "🎯 DFS 图遍历交互式可视化系统 (优化版)" + " " * 17 + "║")
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
    visualizer = InteractiveDFSVisualizer(matrix, start_row=START_ROW, start_col=START_COL)

    print(f"   ✓ 已生成 {len(visualizer.steps)} 个遍历步骤")

    # 图例说明
    print(f"\n🎨 可视化图例:")
    print(f"\n   边的类型:")
    print(f"   ├─ 灰色实线 ━━━━ 未遍历的正常边")
    print(f"   ├─ 红色虚线 ┄┄┄┄ 未遍历的障碍物边")
    print(f"   ├─ 橙色虚线 ┄┄┄┄ 未遍历的边界边")
    print(f"   ├─ 绿色粗线 ━━━━ 前进边（探索新节点）")
    print(f"   ├─ 黄色虚线 ┄┄┄┄ 回溯边（返回父节点）")
    print(f"   ├─ 紫色粗线 ━━━━ 横向边（已访问节点间）")
    print(f"   ├─ 红色点线 ┈┈┈┈ 被障碍物阻挡")
    print(f"   ├─ 橙色点线 ┈┈┈┈ 被边界阻挡")
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

    print(f"\n⌨️  键盘控制:")
    print(f"   ├─ P键 → 播放/暂停自动演示")
    print(f"   ├─ 空格键(Space) → 前进一步（暂停模式）")
    print(f"   ├─ 退格键(Backspace) → 后退一步（暂停模式）")
    print(f"   ├─ R键 → 重置到第一步")
    print(f"   ├─ E键 → 跳到最后一步")
    print(f"   └─ Q键/ESC键 → 退出程序")

    print(f"\n🚀 正在启动交互式可视化...")
    print(f"   提示: 按P键开始自动播放，或使用空格/退格键手动控制\n")

    # 显示交互式可视化
    visualizer.show_interactive()

    print(f"\n✅ 可视化完成！")


if __name__ == "__main__":
    main()