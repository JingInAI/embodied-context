"""Render the implemented context pipeline; no component execution required."""
from pathlib import Path
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch


def main():
    font_path = Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
    if font_path.exists():
        font_manager.fontManager.addfont(str(font_path))
        family = font_manager.FontProperties(fname=str(font_path)).get_name()
    else:
        family = 'sans-serif'
    plt.rcParams.update({'font.family': family, 'svg.fonttype': 'path'})
    fig, ax = plt.subplots(figsize=(16, 19), dpi=150)
    fig.patch.set_facecolor('#f6f8fc')
    ax.set_facecolor('#f6f8fc')
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 19)
    ax.axis('off')

    def box(x, y, w, h, title, detail='', fill='#ffffff', edge='#ccd6e4', size=18):
        ax.add_patch(FancyBboxPatch((x-w/2, y-h/2), w, h,
                     boxstyle='round,pad=0.05,rounding_size=0.12',
                     facecolor=fill, edgecolor=edge, linewidth=1.3, zorder=3))
        if detail:
            ax.text(x, y+0.17, title, ha='center', va='center', fontsize=size,
                    fontweight='bold', color='#182d47', zorder=4)
            ax.text(x, y-0.23, detail, ha='center', va='center', fontsize=14,
                    color='#425570', linespacing=1.5, zorder=4)
        else:
            ax.text(x, y, title, ha='center', va='center', fontsize=size,
                    color='#182d47', linespacing=1.6, zorder=4)

    def arrow(points, dashed=False, color='#60738c'):
        for a, b in zip(points[:-2], points[1:-1]):
            ax.plot([a[0], b[0]], [a[1], b[1]], color=color,
                    linewidth=1.5, linestyle='--' if dashed else '-', zorder=2)
        ax.add_patch(FancyArrowPatch(points[-2], points[-1], arrowstyle='-|>',
                     mutation_scale=13, linewidth=1.5, color=color,
                     linestyle='--' if dashed else '-', zorder=2))

    ax.text(0.55, 18.45, '任务上下文的准备流程', fontsize=34, weight='bold', color='#182d47')
    ax.text(0.55, 17.97, 'scripts_v1：根据当前任务，整理 agent 需要的信息，并保留后续有用的记录',
            fontsize=17, color='#60738c')

    box(8, 17.1, 14.7, 0.9, '外部系统提供任务资料',
        '要完成什么、当前观测、环境设置、执行结果，以及允许使用的资料', fill='#e9eff9')
    box(3.6, 15.65, 5.9, 1.0, '把不同评测任务的资料转成统一格式',
        '支持 11 项评测，检查版本、任务和可用信息')
    box(11.55, 15.65, 5.9, 1.0, '直接提交已整理好的资料',
        '可以调用一个组件，也可以组合多个组件')
    arrow([(3.6, 16.65), (3.6, 16.2)])
    arrow([(11.55, 16.65), (11.55, 16.2)])
    box(3.6, 14.2, 5.9, 1.0, '检查转换结果，决定怎样继续',
        '补齐缺失资料，或调整要使用的组件')
    arrow([(3.6, 15.1), (3.6, 14.75)])
    box(8, 12.75, 14.7, 1.05, '开始处理：运行选中的组件',
        '单个组件直接运行；多个组件先检查依赖关系，再按先后顺序运行', fill='#e5eefb')
    arrow([(3.6, 13.65), (3.6, 13.33)])
    arrow([(11.55, 15.1), (11.55, 13.33)])

    box(5.2, 11.3, 9.1, 1.05, '检查资料是否可用、是否属于当前任务',
        '核对格式、来源、访问范围，以及历史记录和前面组件的结果')
    box(12.9, 11.3, 4.9, 1.05, '外部系统提供处理能力',
        '资料读取、处理工具及使用限额', fill='#eef8f4')
    arrow([(5.2, 12.17), (5.2, 11.88)])
    arrow([(10.4, 11.3), (9.82, 11.3)], dashed=True)

    ax.add_patch(FancyBboxPatch((0.6, 7.75), 14.8, 2.7,
                 boxstyle='round,pad=0.05,rounding_size=0.15',
                 facecolor='#edf3fb', edgecolor='#bccce3', zorder=0))
    ax.text(8, 10.08, '按当前需要选择组件，每个组件负责一类信息',
            ha='center', fontsize=18, weight='bold', color='#294d79')
    arrow([(5.2, 10.72), (5.2, 10.48)])
    components = [
        ('任务与进度', '目标及完成依据'),
        ('观测与记忆', '当前线索和历史记录'),
        ('位置与空间', '坐标、距离和投影'),
        ('操作说明', '操作含义和使用限制'),
        ('执行结果', '实际完成了哪些操作'),
        ('经验与预测', '类似操作的效果依据'),
        ('资源余量', '还能支持多少工作'),
        ('资料与来源', '有哪些资料、能否读取'),
        ('工具与反馈', '工具用途和调用结果'),
        ('答案要求', '格式是否符合要求'),
    ]
    for i, (name, purpose) in enumerate(components):
        box(2.05+(i % 5)*2.97, 9.35-(i//5)*0.95, 2.73, 0.72,
            name, purpose, size=17)

    box(8, 6.95, 14.7, 0.95, '检查处理结果，附上依据和必要记录',
        '保留资料来源、问题说明和可复用记录，并检查内容是否超过长度限制', fill='#e5eefb')
    arrow([(8, 7.7), (8, 7.48)])
    box(8, 5.6, 14.7, 0.95, '汇总为 agent 可使用的上下文',
        '整理各组件的结果和错误；检查多个组件是否对同一份记录提出冲突修改')
    arrow([(8, 6.42), (8, 6.13)])

    box(4.15, 4.15, 7.0, 1.0, '准备交给 agent 的内容',
        '数据、文字或图像等；满足条件时可只发送变化', fill='#edf8f4')
    box(11.9, 4.15, 7.0, 1.0, '外部系统检查要保存的记录',
        '确认旧记录没有被其他处理过程改动，再保存', fill='#fff5e8')
    arrow([(4.15, 5.08), (4.15, 4.7)])
    arrow([(11.9, 5.08), (11.9, 4.7)], dashed=True)
    box(4.15, 2.65, 7.0, 1.0, '外部系统把上下文交给 agent',
        '只发变化时先还原完整内容，并确认实际接收', fill='#edf8f4')
    box(11.9, 2.65, 7.0, 1.0, '下一轮带上已保存的历史记录',
        '记录冲突就重新计算；换任务或重置时区分记录', fill='#fff5e8')
    arrow([(4.15, 3.6), (4.15, 3.2)])
    arrow([(11.9, 3.6), (11.9, 3.2)], dashed=True)

    ax.text(0.7, 1.5, '分工：组件整理信息；外部系统保存记录、发送消息并执行任务。组件不连接机器人或仿真环境。',
            fontsize=14, color='#425570')
    ax.text(0.7, 1.06, '实线：处理或传递信息    虚线：按需提供或由外部系统衔接',
            fontsize=14, color='#60738c')
    ax.text(0.7, 0.62, '出错时：依赖该结果的后续步骤无法继续；不依赖它的其他步骤可以继续。',
            fontsize=14, color='#60738c')
    fig.subplots_adjust(left=0.01, right=0.99, bottom=0.01, top=0.99)
    root = Path(__file__).resolve().parent
    for suffix in ('svg', 'png'):
        target = root / ('scripts_v1_execution_flow.' + suffix)
        fig.savefig(target, facecolor=fig.get_facecolor(), dpi=160)
        print(target)
    plt.close(fig)


if __name__ == '__main__':
    main()
