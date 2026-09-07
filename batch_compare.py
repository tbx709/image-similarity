#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""batch_compare.py — 批量扫描图片文件夹，找出相似/重复图片

用法:
    python batch_compare.py 图片文件夹                     # 单文件夹内找相似
    python batch_compare.py 图片文件夹 --threshold 0.88    # 自定义阈值
    python batch_compare.py 文件夹A --folder-b 文件夹B     # 两个文件夹交叉对比
    python batch_compare.py 图片文件夹 --csv 报告.csv      # 导出 CSV 报告

说明: 默认用感知哈希(phash)比较，相似度 0~1，默认阈值 0.90。
"""

import argparse
import csv
import os
import sys
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from compare import ahash, dhash, phash

IMG_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}

_POP16 = np.array([bin(i).count("1") for i in range(1 << 16)], dtype=np.uint8)


def pack_bits(bits):
    """把布尔哈希位串打包成一个 uint64 整数（汉明距离更快）"""
    return int.from_bytes(np.packbits(bits.ravel()).tobytes(), "little")


def _popcnt(x):
    return (_POP16[x & 0xFFFF] + _POP16[(x >> 16) & 0xFFFF]
            + _POP16[(x >> 32) & 0xFFFF] + _POP16[(x >> 48) & 0xFFFF]).astype(np.float64)


def _row_sim(hash_i, hashes_j):
    """一个哈希与一组哈希的汉明相似度(1D 数组)"""
    if len(hashes_j) == 0:
        return np.zeros(0, dtype=np.float64)
    return 1.0 - _popcnt(hash_i ^ np.array(hashes_j, dtype=np.uint64)) / 64.0


@dataclass
class ScanResult:
    folder: str
    files: list
    unreadable: list
    threshold: float
    method: str
    groups: list
    cross: list = None


def list_images(folder):
    files = []
    for root, _dirs, names in os.walk(folder):
        for name in sorted(names):
            if os.path.splitext(name)[1].lower() in IMG_EXTS:
                files.append(os.path.join(root, name))
    return sorted(files)


def hash_file(path, method):
    with Image.open(path) as im:
        img = im.convert("RGB")
    fn = {"phash": phash, "dhash": dhash, "ahash": ahash}[method]
    return pack_bits(fn(img))


def hash_files(files, method, progress=None):
    hashes, unreadable = [], []
    total = len(files)
    for n, path in enumerate(files, 1):
        try:
            hashes.append(hash_file(path, method))
        except Exception:
            unreadable.append(path)
        if progress and (n % 10 == 0 or n == total):
            progress(n, total)
    return hashes, unreadable


def _union_find(n):
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    return union, find


def scan_folder(folder, threshold=0.90, method="phash", progress=None):
    """扫描单文件夹，返回按相似度分组的 ScanResult"""
    files = list_images(folder)
    hashes, unreadable = hash_files(files, method, progress)

    # 逐行增量计算与分组(内存 O(n), 不上万张图秒级完成)
    union, find = _union_find(len(hashes))
    for i in range(len(hashes)):
        row = _row_sim(hashes[i], hashes[i + 1:])
        for j in np.where(row >= threshold)[0]:
            union(i, i + 1 + int(j))

    groups = {}
    for i in range(len(hashes)):
        groups.setdefault(find(i), []).append(i)

    result_groups = []
    for members in groups.values():
        if len(members) < 2:
            continue
        anchor = members[0]
        sims = {}
        for m in members[1:]:
            s = 1.0 - bin(hashes[anchor] ^ hashes[m]).count("1") / 64.0
            sims[files[m]] = float(s)
        result_groups.append({"files": [files[m] for m in members], "sims": sims})
    result_groups.sort(key=lambda g: -len(g["files"]))

    return ScanResult(folder=folder, files=files, unreadable=unreadable,
                      threshold=threshold, method=method, groups=result_groups)


def compare_folders(folder_a, folder_b, threshold=0.90, method="phash", progress=None):
    """交叉对比两个文件夹，返回互相匹配的图片对"""
    files_a = list_images(folder_a)
    files_b = list_images(folder_b)
    ha, ua = hash_files(files_a, method, progress)
    hb, ub = hash_files(files_b, method, progress)

    matches = []
    for i in range(len(ha)):
        row = _row_sim(ha[i], hb)
        for j in np.where(row >= threshold)[0]:
            matches.append({"a": files_a[i], "b": files_b[int(j)], "sim": float(row[int(j)])})
    matches.sort(key=lambda m: -m["sim"])

    return ScanResult(folder=folder_a, files=files_a + files_b,
                      unreadable=ua + ub, threshold=threshold, method=method,
                      groups=[], cross=matches)


def report_text(res, folder_b=None):
    lines = ["=== 批量相似图片扫描 ===", ""]
    scope = f"{res.folder}  vs  {folder_b}" if res.cross else res.folder
    lines.append(f"目录: {scope}")
    lines.append(f"图片数: {len(res.files)}  (无法读取 {len(res.unreadable)} 张)")
    lines.append(f"阈值: 相似度 >= {res.threshold:.2f}  ({res.method})")
    lines.append("")
    if res.cross:
        if not res.cross:
            lines.append("未找到跨目录相似图片。")
        else:
            lines.append(f"找到 {len(res.cross)} 对跨目录相似图片:")
            for k, m in enumerate(res.cross, 1):
                lines.append(f"  #{k}: {m['a']}  <->  {m['b']}  (相似度 {m['sim']:.2f})")
    else:
        if not res.groups:
            lines.append("未发现相似图片(互相之间都不相似)。")
        else:
            lines.append(f"发现 {len(res.groups)} 组相似图片:")
            for i, g in enumerate(res.groups, 1):
                lines.append("")
                lines.append(f"  组 #{i} ({len(g['files'])} 张):")
                lines.append(f"    基准: {g['files'][0]}")
                for f, s in g["sims"].items():
                    tag = "完全相同" if s >= 1.0 else ("高度相似" if s >= 0.95 else "相似")
                    lines.append(f"    {f}  (相似度 {s:.2f}, {tag})")
    if res.unreadable:
        lines.append("")
        lines.append("无法读取(已跳过):")
        for f in res.unreadable:
            lines.append(f"  {f}")
    return "\n".join(lines)


def write_csv(res, path, folder_b=None):
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        if res.cross:
            w.writerow(["跨目录匹配", "文件A", "文件B", "相似度"])
            for m in res.cross:
                w.writerow(["-", m["a"], m["b"], f"{m['sim']:.4f}"])
        else:
            w.writerow(["组号", "文件", "组内基准", "相似度"])
            for i, g in enumerate(res.groups, 1):
                w.writerow([i, g["files"][0], g["files"][0], 1.0])
                for f, s in g["sims"].items():
                    w.writerow([i, f, g["files"][0], f"{s:.4f}"])


def main():
    # Windows 下输出重定向到文件时保证 UTF-8, 避免中文乱码
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="批量扫描图片文件夹，找出相似/重复图片")
    ap.add_argument("folder", help="图片文件夹")
    ap.add_argument("--folder-b", help="另一个文件夹(交叉对比模式)")
    ap.add_argument("-t", "--threshold", type=float, default=0.90, help="相似度阈值 0~1 (默认 0.90)")
    ap.add_argument("-m", "--method", default="phash", choices=["phash", "dhash", "ahash"],
                    help="哈希方法 (默认 phash)")
    ap.add_argument("--csv", help="导出 CSV 报告路径")
    args = ap.parse_args()

    if not os.path.isdir(args.folder):
        sys.exit(f"文件夹不存在: {args.folder}")
    if args.folder_b and not os.path.isdir(args.folder_b):
        sys.exit(f"文件夹不存在: {args.folder_b}")

    def progress(done, total):
        if sys.stdout.isatty():
            print(f"\r  已处理 {done}/{total} 张...", end="", flush=True)
        if done == total and sys.stdout.isatty():
            print()

    if args.folder_b:
        res = compare_folders(args.folder, args.folder_b, args.threshold, args.method, progress)
        text = report_text(res, args.folder_b)
    else:
        res = scan_folder(args.folder, args.threshold, args.method, progress)
        text = report_text(res)

    print(text)
    if args.csv:
        write_csv(res, args.csv)
        print(f"\nCSV 报告已导出: {args.csv}")


if __name__ == "__main__":
    main()
