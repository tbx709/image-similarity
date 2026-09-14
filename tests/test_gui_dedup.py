# -*- coding: utf-8 -*-
"""去重归档页(DedupTab)的自动化测试：真的建窗口、真的点按钮、真的移动文件

用法:
    python tests/test_gui_dedup.py

需要有图形显示(DISPLAY)；没有显示的环境会打印“跳过”并以 0 退出。
测试全部在系统临时目录里进行，不会碰你的真实图片。
"""

import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "samples"))

fails = []


def check(name, cond, detail=""):
    print(("  [OK]   " if cond else "  [FAIL] ") + name + ("" if cond else f"  <- {detail}"))
    if not cond:
        fails.append(name)


def pump(root, cond, timeout=60.0):
    """转动事件循环直到条件成立(或超时)"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        root.update()
        if cond():
            return True
        time.sleep(0.02)
    return False


def main():
    import gui
    from make_samples import scene

    if not gui.HAVE_TK:
        print("跳过: 当前环境没有 tkinter")
        return 0
    try:
        root, have_dnd = gui.create_root()
    except Exception as exc:
        print(f"跳过: 无法打开图形显示 ({exc})")
        return 0

    # 弹窗全部自动化: 确认框一律“是”, 警告/提示收集起来
    popups = []
    gui.messagebox.askyesno = lambda title, msg, **kw: (popups.append(("ask", title)), True)[1]
    gui.messagebox.showinfo = lambda title, msg, **kw: popups.append(("info", title))
    gui.messagebox.showwarning = lambda title, msg, **kw: popups.append(("warn", title))
    gui.messagebox.showerror = lambda title, msg, **kw: popups.append(("error", title, msg))

    ws = tempfile.mkdtemp(prefix="dedup-gui-test-")
    try:
        app = gui.App(root, have_dnd)
        root.update_idletasks()
        tab = app.dedup_tab

        print("A. 界面结构")
        nb = root.winfo_children()[0]
        check("共 3 个页签", len(nb.tabs()) == 3, len(nb.tabs()))
        check("页签名含“去重归档”", "去重归档" in nb.tab(nb.tabs()[2], "text"))
        check("没有预演时归档/撤销按钮是灰的",
              str(tab.btn_apply["state"]) == "disabled" and str(tab.btn_undo["state"]) == "disabled")
        check("相似模式外的阈值输入框是灰的", str(tab.spin["state"]) == "disabled")

        # 造素材: a/b/c 内容相同, d 不同
        folder = os.path.join(ws, "相册")
        os.makedirs(folder)
        img = scene(1)
        img.save(os.path.join(folder, "a.png"))
        img.save(os.path.join(folder, "b.png"))
        img.save(os.path.join(folder, "c.png"))
        scene(42).save(os.path.join(folder, "d.png"))

        print("B. 预演: 选文件夹 -> 列表")
        tab.folder.set(folder)
        tab.preview()
        check("预演能跑完", pump(root, lambda: not tab.busy and tab.plan is not None),
              tab.status["text"])
        rows = [tab.tree.item(i, "values") for i in tab.tree.get_children()]
        check("列表共 3 行(基准 + 2 个重复)", len(rows) == 3, rows)
        check("第一行是基准 a.png", rows and rows[0][1] == "a.png" and "基准" in rows[0][2], rows[:1])
        check("另外两行是 b.png / c.png", sorted(r[1] for r in rows[1:]) == ["b.png", "c.png"], rows)
        check("说明列标“完全相同”", all(r[2] == "完全相同" for r in rows[1:]), rows)
        check("状态栏给出待移动数量", "待移动 2 张" in tab.status["text"], tab.status["text"])
        check("预演完归档按钮可用", str(tab.btn_apply["state"]) == "normal")
        check("预演没有动任何文件", sorted(os.listdir(folder)) == ["a.png", "b.png", "c.png", "d.png"],
              sorted(os.listdir(folder)))

        print("C. 一键归档: 移动文件")
        tab.apply_now()
        check("归档能跑完", pump(root, lambda: not tab.busy and tab.last_log),
              tab.status["text"])
        check("出现了确认弹窗", any(p[0] == "ask" for p in popups), popups)
        check("a.png 留在原位", os.path.isfile(os.path.join(folder, "a.png")))
        check("b.png / c.png 被移进 a/",
              sorted(os.listdir(os.path.join(folder, "a"))) == [".dedup-group.json", "b.png", "c.png"],
              sorted(os.listdir(os.path.join(folder, "a"))))
        check("d.png 没被动", os.path.isfile(os.path.join(folder, "d.png")))
        check("归档后撤销按钮可用", str(tab.btn_undo["state"]) == "normal")
        check("状态栏说明可以撤销", "撤销" in tab.status["text"], tab.status["text"])
        check("表格列出已移动的文件",
              [tab.tree.item(i, "values")[2] for i in tab.tree.get_children()] == ["已移动", "已移动"],
              [tab.tree.item(i, "values") for i in tab.tree.get_children()])
        check("没有弹出错误框", not [p for p in popups if p[0] == "error"], popups)

        print("D. 一键撤销: 原样还原")
        tab.undo_last()
        check("撤销能跑完", pump(root, lambda: not tab.busy and tab.last_log is None),
              tab.status["text"])
        left = [n for n in sorted(os.listdir(folder)) if not n.startswith(".dedup-log")]
        check("文件全部回到原位(日志文件按设计保留)", left == ["a.png", "b.png", "c.png", "d.png"], left)
        check("归档文件夹已清理", not os.path.exists(os.path.join(folder, "a")))
        check("撤销后按钮复位",
              str(tab.btn_undo["state"]) == "disabled" and str(tab.btn_apply["state"]) == "disabled")

        print("E. 相似模式与无重复的情况")
        tab.mode.set("相似(感知哈希)")
        tab._on_mode()
        check("切到相似模式后阈值可编辑", str(tab.spin["state"]) == "normal")
        tab.folder.set(os.path.join(ws, "没有重复"))
        os.makedirs(os.path.join(ws, "没有重复"))
        scene(7).save(os.path.join(ws, "没有重复", "x.png"))
        scene(99).save(os.path.join(ws, "没有重复", "y.png"))
        tab.preview()
        check("无重复时预演正常结束", pump(root, lambda: not tab.busy), tab.status["text"])
        check("无重复时提示且归档按钮保持灰",
              "没有需要归档" in tab.status["text"] and str(tab.btn_apply["state"]) == "disabled",
              tab.status["text"])
        check("表格是空的", not tab.tree.get_children())
        check("全程没有错误框", not [p for p in popups if p[0] == "error"], popups)

        print("F. 按日志撤销(第三个按钮, 用于撤销更早的某次归档)")
        folder2 = os.path.join(ws, "相册2")
        os.makedirs(folder2)
        img.save(os.path.join(folder2, "m.png"))
        img.save(os.path.join(folder2, "n.png"))
        tab.mode.set("完全相同(逐字节比对)")
        tab._on_mode()
        tab.folder.set(folder2)
        tab.preview()
        pump(root, lambda: not tab.busy and tab.plan is not None)
        tab.apply_now()
        check("第二次归档成功", pump(root, lambda: not tab.busy and tab.last_log), tab.status["text"])
        log2 = tab.last_log
        gui.filedialog.askopenfilename = lambda **kw: log2      # 模拟选了日志文件
        tab.undo_from_file()
        check("按日志撤销能跑完", pump(root, lambda: not tab.busy and tab.last_log is None),
              tab.status["text"])
        left2 = [n for n in sorted(os.listdir(folder2)) if not n.startswith(".dedup-log")]
        check("按日志撤销后文件回到原位", left2 == ["m.png", "n.png"], left2)
        check("全程没有错误框", not [p for p in popups if p[0] == "error"], popups)
    finally:
        try:
            root.destroy()
        except Exception:
            pass
        shutil.rmtree(ws, ignore_errors=True)

    print()
    print("失败项:", fails if fails else "无 —— 全部通过")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
