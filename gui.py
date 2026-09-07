#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gui.py — 图片相似度比较工具（图形界面）

用法:
    python gui.py            # 打开图形界面（装 tkinterdnd2 后支持拖拽文件）
    python gui.py --selftest # 自检：构建界面后立即关闭（供脚本/无头环境验证）

依赖:
    - Pillow, numpy
    - tkinter（Python 自带；Linux 若缺失: sudo apt install python3-tk）
    - 可选 tkinterdnd2: pip install tkinterdnd2   # 启用拖拽图片到窗口
"""

import os
import queue
import sys
import threading

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    from PIL import Image, ImageTk
    HAVE_TK = True
except Exception:  # tkinter 缺失时提供桩对象, 保证模块可导入(供脚本/编译检查)
    HAVE_TK = False
    import types as _types
    tk = _types.SimpleNamespace(StringVar=lambda: None, Label=object, Toplevel=object)
    ttk = _types.SimpleNamespace(Frame=object, Label=object, Entry=object, Button=object,
                                 Notebook=object, Combobox=object, Spinbox=object,
                                 Progressbar=object, Treeview=object)
    filedialog = _types.SimpleNamespace(askopenfilename=None, askdirectory=None,
                                        asksaveasfilename=None)
    messagebox = _types.SimpleNamespace(showwarning=None, showerror=None, showinfo=None)
    ImageTk = None

import batch_compare
from compare import (phash, ssim, hist_sim, mse_score, auto_verdict, _hash_sim)

GREEN = "#1a7f37"
ORANGE = "#b45309"
RED = "#b91c1c"
GRAY = "#666666"

POLL_MS = 100


# ---------------------------------------------------------------- 根窗口(支持可选拖拽)

def create_root():
    """返回 (root, have_dnd)，优先使用 tkinterdnd2 以获得拖拽支持"""
    try:
        from tkinterdnd2 import DND_FILES, TkinterDnD
    except Exception:
        return tk.Tk(), False
    root = TkinterDnD.Tk()
    root._dnd = DND_FILES
    return root, True


# ---------------------------------------------------------------- 单张比较页

class CompareTab(ttk.Frame):
    def __init__(self, master, root, have_dnd):
        super().__init__(master, padding=10)
        self.root = root
        self.have_dnd = have_dnd
        self.queue = queue.Queue()
        self.photo_a = None
        self.photo_b = None
        self.path_a = tk.StringVar()
        self.path_b = tk.StringVar()

        tk.Label(self, text="选择两张图片进行相似度比较", font=("", 13, "bold")).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))

        self._image_block(1, "图片 A", self.path_a, "a")
        self._image_block(3, "图片 B", self.path_b, "b")

        btn_row = ttk.Frame(self)
        btn_row.grid(row=5, column=0, columnspan=4, pady=10)
        ttk.Button(btn_row, text="开始比较", command=self.compare).pack(side="left", padx=5)
        self.status = tk.Label(btn_row, text="", fg=GRAY)
        self.status.pack(side="left", padx=10)

        cols = ("method", "score", "judge")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=6)
        for c, w, txt in zip(cols, (200, 120, 260), ("方法", "相似度", "判定")):
            self.tree.heading(c, text=txt)
            self.tree.column(c, width=w, anchor="center" if c == "score" else "w")
        self.tree.grid(row=6, column=0, columnspan=4, sticky="nsew")
        self.verdict = tk.Label(self, text="", font=("", 14, "bold"), fg=GRAY, anchor="w")
        self.verdict.grid(row=7, column=0, columnspan=4, sticky="we", pady=(8, 0))

        self.columnconfigure(0, weight=1)
        self.rowconfigure(6, weight=1)
        self.root.after(POLL_MS, self._poll)

    def _image_block(self, row, name, var, side):
        ttk.Label(self, text=name).grid(row=row, column=0, sticky="w", padx=(0, 8))
        ent = ttk.Entry(self, textvariable=var)
        ent.grid(row=row, column=1, sticky="we")
        ttk.Button(self, text="浏览...", command=lambda: self._browse(var, side)).grid(
            row=row, column=2, sticky="w", padx=5)
        thumb = tk.Label(self, text="点击选择图片\n(拖拽文件到这里)", fg=GRAY,
                         bd=1, relief="groove", width=30, height=8)
        thumb.grid(row=row, column=3, rowspan=2, padx=10, sticky="n")
        thumb.bind("<Button-1>", lambda _e: self._browse(var, side))
        setattr(self, f"thumb_{side}", thumb)

        if self.have_dnd:
            for w in (ent, thumb):
                try:
                    w.drop_target_register(self.root._dnd)
                    w.dnd_bind("<<Drop>>", lambda e, v=var, s=side: self._on_drop(e, v, s))
                except Exception:
                    pass

    def _browse(self, var, side):
        path = filedialog.askopenfilename(title="选择图片", filetypes=[
            ("图片文件", "*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff"),
            ("所有文件", "*.*")])
        if not path:
            return
        var.set(path)
        self._show_thumb(side, path)

    def _on_drop(self, event, var, side):
        try:
            paths = list(self.root.tk.splitlist(event.data))
        except Exception:
            paths = [event.data]
        if not paths:
            return
        self.path_a.set(paths[0])
        self._show_thumb("a", paths[0])
        if len(paths) > 1:
            self.path_b.set(paths[1])
            self._show_thumb("b", paths[1])
        elif side == "a":
            self.path_b.set("")
            self._show_thumb("b", "")

    def _show_thumb(self, side, path):
        thumb = getattr(self, f"thumb_{side}")
        if not path:
            thumb.configure(image="", text="点击选择图片\n(拖拽文件到这里)")
            setattr(self, f"photo_{side}", None)
            return
        try:
            im = Image.open(path).convert("RGB")
            im.thumbnail((170, 170))
            photo = ImageTk.PhotoImage(im)
            setattr(self, f"photo_{side}", photo)
            thumb.configure(image=photo, text="", width=170, height=170)
        except Exception:
            thumb.configure(image="", text=f"无法打开:\n{path}", fg=RED)

    def compare(self):
        pa, pb = self.path_a.get().strip(), self.path_b.get().strip()
        if not pa or not pb:
            messagebox.showwarning("提示", "请先选择两张图片")
            return
        self.status.config(text="计算中...")
        self.verdict.config(text="")
        for item in self.tree.get_children():
            self.tree.delete(item)
        threading.Thread(target=self._work, args=(pa, pb), daemon=True).start()

    def _work(self, pa, pb):
        try:
            from compare import load_image
            img_a, img_b = load_image(pa), load_image(pb)
            ph = _hash_sim(phash(img_a), phash(img_b))
            ss, ss_raw = ssim(img_a, img_b)
            hh = hist_sim(img_a, img_b)
            mse, ms = mse_score(img_a, img_b)
            rows = [
                ("phash 感知哈希", f"{ph:.4f}", "相似" if ph >= 0.85 else ("相近" if ph >= 0.65 else "不相似")),
                ("ssim 结构相似度", f"{ss:.4f}", "相似" if ss >= 0.85 else ("相近" if ss >= 0.65 else "不相似")),
                ("hist 色彩直方图", f"{hh:.4f}", "相似" if hh >= 0.90 else ("相近" if hh >= 0.70 else "不相似")),
                (f"mse 像素误差({mse:.1f})", f"{ms:.4f}", "相似" if ms >= 0.95 else ("相近" if ms >= 0.75 else "不相似")),
            ]
            verdict = auto_verdict(ph, ss, hh)
            self.queue.put(("done", rows, verdict))
        except Exception as exc:
            self.queue.put(("error", str(exc)))

    def _poll(self):
        try:
            while True:
                msg = self.queue.get_nowait()
                if msg[0] == "done":
                    _rows, verdict = msg[1], msg[2]
                    self.status.config(text="完成")
                    for name, score, judge in _rows:
                        color = GREEN if judge == "相似" else (ORANGE if judge == "相近" else RED)
                        self.tree.insert("", "end",
                                         values=(name, score, judge),
                                         tags=(color,))
                        self.tree.tag_configure(color, foreground=color)
                    self.verdict.config(text=f"综合判定: {verdict}", fg=GREEN if "相似" in verdict
                                        else (ORANGE if "相近" in verdict else RED))
                elif msg[0] == "error":
                    self.status.config(text="出错")
                    self.verdict.config(text=f"错误: {msg[1]}", fg=RED)
        except queue.Empty:
            pass
        self.root.after(POLL_MS, self._poll)


# ---------------------------------------------------------------- 批量扫描页

class BatchTab(ttk.Frame):
    def __init__(self, master, root):
        super().__init__(master, padding=10)
        self.root = root
        self.queue = queue.Queue()
        self.last_res = None
        self.mode = tk.StringVar(value="单文件夹内查找相似图片")
        self.threshold = tk.StringVar(value="0.90")
        self.folder_a = tk.StringVar()
        self.folder_b = tk.StringVar()

        tk.Label(self, text="批量查找相似 / 重复图片", font=("", 13, "bold")).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))

        ttk.Label(self, text="图片文件夹:").grid(row=1, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(self, textvariable=self.folder_a).grid(row=1, column=1, sticky="we")
        ttk.Button(self, text="浏览...", command=lambda: self._browse(self.folder_a)).grid(
            row=1, column=2, sticky="w", padx=5)

        ttk.Label(self, text="文件夹 B(对比):").grid(row=2, column=0, sticky="w", padx=(0, 8))
        self.ent_b = ttk.Entry(self, textvariable=self.folder_b)
        self.ent_b.grid(row=2, column=1, sticky="we")
        self.btn_b = ttk.Button(self, text="浏览...", command=lambda: self._browse(self.folder_b))
        self.btn_b.grid(row=2, column=2, sticky="w", padx=5)
        self._set_b_state("disabled")

        opt = ttk.Frame(self)
        opt.grid(row=3, column=0, columnspan=4, sticky="w", pady=8)
        ttk.Label(opt, text="模式:").pack(side="left")
        self.mode_cb = ttk.Combobox(opt, textvariable=self.mode, state="readonly", width=24,
                                    values=["单文件夹内查找相似图片", "两个文件夹交叉对比"])
        self.mode_cb.pack(side="left", padx=5)
        self.mode_cb.bind("<<ComboboxSelected>>", self._on_mode)
        ttk.Label(opt, text="阈值:").pack(side="left", padx=(10, 0))
        self.spin = ttk.Spinbox(opt, from_=0.70, to=1.00, increment=0.01, width=6,
                                textvariable=self.threshold)
        self.spin.pack(side="left", padx=5)
        ttk.Button(opt, text="开始扫描", command=self.scan).pack(side="left", padx=10)
        self.btn_export = ttk.Button(opt, text="导出 CSV", command=self.export_csv, state="disabled")
        self.btn_export.pack(side="left", padx=5)

        self.bar = ttk.Progressbar(self, mode="determinate")
        self.bar.grid(row=4, column=0, columnspan=4, sticky="we", pady=(4, 6))

        cols = ("group", "file", "sim")
        self.tree = ttk.Treeview(self, columns=cols, show="headings")
        for c, w, txt in zip(cols, (80, 520, 140), ("组", "文件", "相似度")):
            self.tree.heading(c, text=txt)
            self.tree.column(c, width=w, anchor="center" if c in ("group", "sim") else "w")
        self.tree.grid(row=5, column=0, columnspan=4, sticky="nsew")
        self.tree.bind("<Double-1>", self._preview)

        self.status = tk.Label(self, text="", fg=GRAY, anchor="w")
        self.status.grid(row=6, column=0, columnspan=4, sticky="we", pady=(4, 0))

        self.columnconfigure(1, weight=1)
        self.rowconfigure(5, weight=1)
        self.root.after(POLL_MS, self._poll)

    def _set_b_state(self, state):
        for w in (self.ent_b, self.btn_b):
            w.configure(state=state)

    def _on_mode(self, _e=None):
        self._set_b_state("normal" if self.mode.get().startswith("两个") else "disabled")

    def _browse(self, var):
        path = filedialog.askdirectory(title="选择文件夹")
        if path:
            var.set(path)

    def scan(self):
        fa = self.folder_a.get().strip()
        if not fa:
            messagebox.showwarning("提示", "请先选择图片文件夹")
            return
        two = self.mode.get().startswith("两个")
        fb = self.folder_b.get().strip() if two else None
        if two and not fb:
            messagebox.showwarning("提示", "请选择文件夹 B")
            return
        try:
            th = float(self.threshold.get())
        except ValueError:
            th = 0.90
        th = min(max(th, 0.0), 1.0)
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.bar.configure(value=0, maximum=1)
        self.status.config(text="扫描中...")
        self.btn_export.configure(state="disabled")
        threading.Thread(target=self._work, args=(fa, fb, th), daemon=True).start()

    def _work(self, fa, fb, th):
        def progress(done, total):
            self.queue.put(("progress", done, total))
        try:
            if fb:
                res = batch_compare.compare_folders(fa, fb, th, progress=progress)
            else:
                res = batch_compare.scan_folder(fa, th, progress=progress)
            self.queue.put(("done", res))
        except Exception as exc:
            self.queue.put(("error", str(exc)))

    def _poll(self):
        try:
            while True:
                msg = self.queue.get_nowait()
                kind = msg[0]
                if kind == "progress":
                    self.bar.configure(maximum=max(1, msg[2]), value=msg[1])
                    self.status.config(text=f"扫描中... {msg[1]}/{msg[2]}")
                elif kind == "done":
                    res = msg[1]
                    self.last_res = res
                    self.bar.configure(value=self.bar.cget("maximum"))
                    self._fill_tree(res)
                    self.btn_export.configure(state="normal")
                    if res.cross:
                        n = len(res.cross)
                    else:
                        n = len(res.groups)
                    self.status.config(text=f"完成: 发现 {n} 组相似图片(共 {len(res.files)} 张, "
                                            f"无法读取 {len(res.unreadable)} 张)")
                elif kind == "error":
                    self.status.config(text=f"出错: {msg[1]}")
        except queue.Empty:
            pass
        self.root.after(POLL_MS, self._poll)

    def _fill_tree(self, res):
        if res.cross:
            for i, m in enumerate(res.cross, 1):
                self.tree.insert("", "end", values=("-", f"{m['a']}  <->  {m['b']}", f"{m['sim']:.2f}"),
                                 iid=f"c{i}", tags=("path",))
                self._set_path(f"c{i}", m)
        else:
            for gi, g in enumerate(res.groups, 1):
                self.tree.insert("", "end", values=(f"组{gi}", g["files"][0], "基准"),
                                 iid=f"g{gi}x0", tags=("anchor",))
                self._set_path(f"g{gi}x0", g["files"][0])
                for k, (f, s) in enumerate(g["sims"].items(), 1):
                    iid = f"g{gi}x{k}"
                    self.tree.insert("", "end", values=(f"组{gi}", f, f"{s:.2f}"),
                                     iid=iid, tags=("path",))
                    self._set_path(iid, f)
        self.tree.tag_configure("anchor", foreground=GRAY)

    def _set_path(self, iid, m_or_path):
        self.tree._paths = getattr(self.tree, "_paths", {})
        if isinstance(m_or_path, dict):
            self.tree._paths[iid] = m_or_path
        else:
            self.tree._paths[iid] = m_or_path

    def _preview(self, event):
        iid = self.tree.identify_row(event.y)
        paths = getattr(self.tree, "_paths", {})
        if iid not in paths:
            return
        data = paths[iid]
        path = data["a"] if isinstance(data, dict) else data
        try:
            im = Image.open(path).convert("RGB")
            im.thumbnail((420, 420))
            win = tk.Toplevel(self)
            win.title(os.path.basename(path))
            photo = ImageTk.PhotoImage(im)
            lbl = tk.Label(win, image=photo)
            lbl.image = photo
            lbl.pack()
            tk.Label(win, text=path, fg=GRAY).pack()
        except Exception as exc:
            messagebox.showerror("预览失败", str(exc))

    def export_csv(self):
        if not self.last_res:
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                                            filetypes=[("CSV 文件", "*.csv")])
        if path:
            batch_compare.write_csv(self.last_res, path)
            messagebox.showinfo("导出成功", f"已导出: {path}")


# ---------------------------------------------------------------- 入口

class App:
    def __init__(self, root, have_dnd):
        self.root = root
        root.title("图片相似度比较工具")
        root.geometry("980x680")
        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True)
        self.compare_tab = CompareTab(nb, root, have_dnd)
        self.batch_tab = BatchTab(nb, root)
        nb.add(self.compare_tab, text=" 单张比较 ")
        nb.add(self.batch_tab, text=" 批量扫描 ")


def selftest():
    """无头自检: 构建界面 → 刷新 → 关闭。返回 0 表示通过"""
    if not HAVE_TK:
        print("自检失败: 当前环境缺少 tkinter (Linux 可执行 sudo apt install python3-tk)")
        return 1
    root, have_dnd = create_root()
    app = App(root, have_dnd)
    root.update_idletasks()
    root.update()
    tabs = len(root.winfo_children()[0].tabs()) if root.winfo_children() else 0
    root.destroy()
    if tabs == 2:
        print(f"GUI 自检通过 (2 个页面, 拖拽支持: {'有' if have_dnd else '无'})")
        return 0
    print("自检失败: 界面结构不正确")
    return 1


def main():
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    if not HAVE_TK:
        print("无法启动图形界面: 需要 tkinter。\n  Linux: sudo apt install python3-tk\n  Windows/macOS: 使用 python.org 官方安装包(自带 tkinter)")
        sys.exit(1)
    root, have_dnd = create_root()
    App(root, have_dnd)
    root.mainloop()


if __name__ == "__main__":
    main()
