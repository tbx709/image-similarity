#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dedup.py — 文件夹内图片去重归档

把重复（或高度相似）的图片，移动到以「基准图片」命名的子文件夹里，
基准图片本身留在原位，一眼就能看出哪张是原件。

例子: 文件夹里有 a.png / b.png / c.png，其中 b、c 与 a 内容一样，
      执行后变成 a.png  +  a/(b.png, c.png)，a/ 就是以基准图命名的归档文件夹。

用法:
    python dedup.py 图片文件夹                       # 预演(默认): 只打印计划, 不动文件
    python dedup.py 图片文件夹 --apply               # 真正执行移动
    python dedup.py 图片文件夹 --mode similar --apply # 按"相似"归并(压缩/缩放/改亮度也算)
    python dedup.py 图片文件夹 --keep largest --apply # 保留体积最大的那张作基准
    python dedup.py 图片文件夹 --undo 日志.json      # 撤销上一次移动, 原样还原

安全设计（移动文件不可逆，所以这里做得保守）:
    * 默认只预演，必须显式加 --apply 才会动文件;
    * 每次移动都写 JSON 日志，可用 --undo 一键还原;
    * 归档文件夹里放一个 .dedup-group.json 标记，下次扫描自动跳过，重复运行不会越套越深;
    * 目标重名自动加 _1/_2 后缀，绝不覆盖任何已有文件。
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time

IMG_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
MARKER = ".dedup-group.json"          # 放在归档文件夹里的标记, 用于识别/跳过
LOG_PREFIX = ".dedup-log-"
CHUNK = 1 << 20

_POP16 = None                          # 汉明距离用的 16 位查表(惰性构建)


# ---------------------------------------------------------------- 基础工具

def rel(path, root):
    """尽量显示相对路径，报告更短更好读"""
    try:
        return os.path.relpath(path, root)
    except ValueError:                 # Windows 跨盘符
        return path


def natural_key(text):
    """自然排序: a2.png 排在 a10.png 前面"""
    return [(0, int(p)) if p.isdigit() else (1, p.lower())
            for p in re.split(r"(\d+)", text)]


def is_archive_dir(path):
    """带 .dedup-group.json 标记的目录 = 本工具建的归档文件夹"""
    return os.path.isfile(os.path.join(path, MARKER))


def list_images(root, recursive=True):
    """列出图片文件; 归档文件夹整个跳过(所以重复运行不会越套越深)"""
    files = []
    if recursive:
        for dirpath, dirnames, names in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames
                                 if not is_archive_dir(os.path.join(dirpath, d)))
            for name in sorted(names):
                if os.path.splitext(name)[1].lower() in IMG_EXTS:
                    files.append(os.path.join(dirpath, name))
    else:
        for name in sorted(os.listdir(root)):
            path = os.path.join(root, name)
            if os.path.isfile(path) and os.path.splitext(name)[1].lower() in IMG_EXTS:
                files.append(path)
    return files


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def unique_path(path):
    """目标已存在时改成 xxx_1.ext / xxx_2.ext, 绝不覆盖"""
    if not os.path.exists(path):
        return path
    folder, base = os.path.split(path)
    stem, ext = os.path.splitext(base)
    for n in range(1, 10000):
        cand = os.path.join(folder, f"{stem}_{n}{ext}")
        if not os.path.exists(cand):
            return cand
    raise RuntimeError(f"同名文件太多, 无法归档: {path}")


def _popcnt(arr):
    """numpy uint64 数组的按位 1 计数"""
    global _POP16
    if _POP16 is None:
        import numpy as np
        _POP16 = np.array([bin(i).count("1") for i in range(1 << 16)], dtype=np.uint8)
    return (_POP16[arr & 0xFFFF] + _POP16[(arr >> 16) & 0xFFFF]
            + _POP16[(arr >> 32) & 0xFFFF] + _POP16[(arr >> 48) & 0xFFFF]).astype(float)


# ---------------------------------------------------------------- 分组: 完全相同(exact)

def group_exact(files, progress=None):
    """按文件内容分组: 先比大小, 再比 SHA-256。返回 [[路径, ...], ...]"""
    by_size = {}
    for path in files:
        try:
            by_size.setdefault(os.path.getsize(path), []).append(path)
        except OSError:
            pass
    groups, done, total = [], 0, len(files)
    for paths in by_size.values():
        if len(paths) < 2:                     # 大小都不同, 不可能完全相同
            done += len(paths)
            if progress:
                progress(min(done, total), total)
            continue
        by_hash = {}
        for path in paths:
            by_hash.setdefault(sha256_file(path), []).append(path)
            done += 1
            if progress:
                progress(min(done, total), total)
        for same in by_hash.values():
            if len(same) >= 2:
                groups.append(sorted(same))
    return groups


# ---------------------------------------------------------------- 分组: 相似(similar)

def group_similar(files, threshold=0.95, method="phash", progress=None):
    """按感知哈希分组(复用 batch_compare 的哈希实现)。返回 (分组, 路径->哈希, 读不了的)"""
    import numpy as np

    from batch_compare import hash_file   # 惰性导入: exact 模式不需要 Pillow/numpy

    hashes, unreadable, keep = [], [], []
    for n, path in enumerate(files, 1):
        try:
            hashes.append(hash_file(path, method))
            keep.append(path)
        except Exception:
            unreadable.append(path)
        if progress:
            progress(n, len(files))

    arr = np.array(hashes, dtype=np.uint64)
    parent = list(range(len(keep)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(keep)):             # 逐行向量化比汉明距离, 几千张也很快
        row = 1.0 - _popcnt(arr[i] ^ arr[i + 1:]) / 64.0
        for j in np.where(row >= threshold)[0]:
            a, b = find(i), find(i + 1 + int(j))
            if a != b:
                parent[b] = a

    buckets = {}
    for i, path in enumerate(keep):
        buckets.setdefault(find(i), []).append(path)
    groups = [sorted(m) for m in buckets.values() if len(m) >= 2]

    hash_by_path = dict(zip(keep, hashes))
    return groups, hash_by_path, unreadable


# ---------------------------------------------------------------- 归档计划

def pick_keeper(members, keep, root):
    """从一组里挑基准图; 同分时按文件名自然排序, 所以 a.png 优先于 b.png"""
    if keep == "first":
        return sorted(members, key=lambda p: natural_key(rel(p, root)))[0]
    if keep == "largest":
        return sorted(members, key=lambda p: (-os.path.getsize(p),
                                              natural_key(rel(p, root))))[0]
    if keep == "oldest":
        return sorted(members, key=lambda p: (os.path.getmtime(p),
                                              natural_key(rel(p, root))))[0]
    if keep == "newest":
        return sorted(members, key=lambda p: (-os.path.getmtime(p),
                                              natural_key(rel(p, root))))[0]
    raise ValueError(f"未知的 keep 选项: {keep}")


def make_folder_path(keeper, taken):
    """归档文件夹名 = 基准图文件名去掉扩展名; 被占用就退让成 a_1/a_2, 绝不碰已有目录"""
    folder, base = os.path.split(keeper)
    stem, _ext = os.path.splitext(base)
    names = [stem] if stem else []
    for n in range(1, 1000):                         # 名字被占用: a_1, a_2 ...
        name = f"{stem}_{n}"
        if name not in names:
            names.append(name)
    for name in names:
        path = os.path.join(folder, name)
        if path != keeper and not os.path.exists(path) and path not in taken:
            return path
    return None


def build_plan(root, groups, keep, hash_by_path=None):
    """把分组变成可执行的归档计划"""
    plan, taken = [], set()
    for members in groups:
        keeper = pick_keeper(members, keep, root)
        folder = make_folder_path(keeper, taken)
        others = [p for p in members if p != keeper]
        sims = None
        if hash_by_path:
            anchor = hash_by_path[keeper]
            sims = {p: 1.0 - bin(hash_by_path[p] ^ anchor).count("1") / 64.0 for p in others}
        if folder:
            taken.add(folder)
        plan.append({"keeper": keeper, "folder": folder, "others": others, "sims": sims})
    plan.sort(key=lambda g: natural_key(rel(g["keeper"], root)))
    return plan


# ---------------------------------------------------------------- 执行 / 撤销

def write_json(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def apply_plan(root, plan, mode, keep, log_path=None, threshold=None, method=None):
    """真正移动文件; 返回 (日志路径, 已移动数, 失败列表)"""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    log_path = log_path or os.path.join(root, f"{LOG_PREFIX}{stamp}.json")
    moves, folders, failed = [], [], []

    for group in plan:
        if not group["folder"]:
            failed.append((group["keeper"], "找不到可用的归档文件夹名"))
            continue
        folder = group["folder"]
        os.makedirs(folder, exist_ok=True)
        folders.append(folder)
        moved_here = []
        for src in group["others"]:
            dst = unique_path(os.path.join(folder, os.path.basename(src)))
            try:
                shutil.move(src, dst)
            except Exception as exc:
                failed.append((src, f"移动失败: {exc}"))
                continue
            moves.append({"src": src, "dst": dst})
            moved_here.append({"name": os.path.basename(dst),
                               "from": rel(os.path.dirname(src), root)})
            print(f"  移动 {rel(src, root)}  ->  {rel(dst, root)}")
        write_json(os.path.join(folder, MARKER), {
            "tool": "dedup.py",
            "mode": mode, "method": method, "threshold": threshold, "keep": keep,
            "keeper": os.path.basename(group["keeper"]),
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "moved": moved_here,
        })

    write_json(log_path, {
        "tool": "dedup.py", "root": root, "mode": mode, "keep": keep,
        "method": method, "threshold": threshold,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "moves": moves, "folders": folders,
    })
    return log_path, len(moves), failed


def run_undo(log_path):
    """按日志把文件原样移回去, 并清理空的归档文件夹"""
    with open(log_path, encoding="utf-8") as fh:
        data = json.load(fh)

    moved_back, skipped = 0, []
    for item in reversed(data.get("moves", [])):     # 倒序还原
        src, dst = item["src"], item["dst"]
        if not os.path.exists(dst):
            skipped.append((dst, "文件已不在归档文件夹里"))
            continue
        if os.path.exists(src):
            skipped.append((src, "原位置已有同名文件, 未覆盖"))
            continue
        os.makedirs(os.path.dirname(src), exist_ok=True)
        try:
            shutil.move(dst, src)
            moved_back += 1
            print(f"  还原 {rel(src, data.get('root', '.'))}")
        except Exception as exc:
            skipped.append((dst, f"还原失败: {exc}"))

    removed = 0
    for folder in reversed(data.get("folders", [])):
        marker = os.path.join(folder, MARKER)
        if os.path.isfile(marker):
            os.remove(marker)
        try:
            os.rmdir(folder)                         # 只在空目录时成功
            removed += 1
        except OSError:
            pass
    return moved_back, removed, skipped


# ---------------------------------------------------------------- 报告

def report_plan(root, plan, mode, threshold, method, keep, unreadable, skipped_dirs):
    if mode == "exact":
        mode_desc = "完全相同 (SHA-256 逐字节比对)"
    else:
        mode_desc = f"相似 (感知哈希 {method}, 阈值 {threshold:.2f})"
    total_moves = sum(len(g["others"]) for g in plan)

    lines = ["=== 图片去重归档 ===", ""]
    lines.append(f"目录: {root}")
    lines.append(f"模式: {mode_desc}    基准图选择: {keep}")
    if unreadable:
        lines.append(f"无法读取(已跳过): {len(unreadable)} 张")
    if skipped_dirs:
        lines.append(f"已跳过 {skipped_dirs} 个本工具建的归档文件夹")
    lines.append("")

    if not plan:
        lines.append("没有发现重复图片，不需要归档。")
        return "\n".join(lines)

    lines.append(f"发现 {len(plan)} 组重复/相似图片，共 {total_moves} 张待移动:")
    for i, group in enumerate(plan, 1):
        if not group["folder"]:
            lines.append("")
            lines.append(f"  组 #{i}: 基准 {rel(group['keeper'], root)}")
            lines.append("    [!] 归档文件夹名被占用, 本组跳过")
            continue
        lines.append("")
        lines.append(f"  组 #{i} ({len(group['others']) + 1} 张): "
                     f"基准 {rel(group['keeper'], root)}  →  归档到 {rel(group['folder'], root)}/")
        for src in group["others"]:
            note = "完全相同" if group["sims"] is None else f"相似度 {group['sims'][src]:.2f}"
            lines.append(f"    ← {rel(src, root)}   ({note})")
    return "\n".join(lines)


def print_progress(done, total):
    if sys.stdout.isatty():
        print(f"\r  已处理 {done}/{total} 张...", end="", flush=True)
        if done >= total:
            print()


# ---------------------------------------------------------------- 主流程

def main():
    try:                                   # Windows 重定向输出时保证 UTF-8
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(
        description="文件夹内图片去重: 把重复图片移动到以基准图命名的子文件夹里",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="例: python dedup.py 图片文件夹            # 先看计划(不动文件)\n"
               "    python dedup.py 图片文件夹 --apply    # 确认后再执行")
    ap.add_argument("folder", nargs="?", help="图片文件夹")
    ap.add_argument("--apply", action="store_true", help="真正移动文件(默认只预演, 不动任何文件)")
    ap.add_argument("--mode", default="exact", choices=["exact", "similar"],
                    help="exact=完全相同(默认) / similar=感知哈希相似")
    ap.add_argument("-t", "--threshold", type=float, default=0.95,
                    help="similar 模式的相似度阈值 0~1 (默认 0.95)")
    ap.add_argument("-m", "--method", default="phash", choices=["phash", "dhash", "ahash"],
                    help="similar 模式的哈希方法 (默认 phash)")
    ap.add_argument("-k", "--keep", default="first",
                    choices=["first", "largest", "oldest", "newest"],
                    help="哪张作基准图: first=文件名最前(默认) / largest / oldest / newest")
    ap.add_argument("--no-recursive", action="store_true", help="只扫描顶层, 不进子文件夹")
    ap.add_argument("--log", metavar="路径", help="指定日志文件路径")
    ap.add_argument("--undo", metavar="日志文件", help="按日志撤销上一次移动")
    args = ap.parse_args()

    if args.undo:
        if args.apply:
            sys.exit("--undo 与 --apply 不能同时使用")
        if not os.path.isfile(args.undo):
            sys.exit(f"日志文件不存在: {args.undo}")
        print(f"=== 撤销去重归档 ===\n\n日志: {args.undo}\n")
        moved_back, removed, skipped = run_undo(args.undo)
        print(f"\n已还原 {moved_back} 个文件，清理 {removed} 个空归档文件夹。")
        if skipped:
            print("\n未处理(需人工确认):")
            for path, why in skipped:
                print(f"  {path}  ({why})")
        print("\n日志文件仍保留，确认无误后可自行删除。")
        return

    if not args.folder:
        sys.exit("请指定图片文件夹（或用 --undo 日志文件 撤销）")
    root = os.path.abspath(args.folder)
    if not os.path.isdir(root):
        sys.exit(f"文件夹不存在: {args.folder}")

    recursive = not args.no_recursive
    files = list_images(root, recursive)
    skipped_dirs = 0
    if recursive:                          # 统计一下跳过了几个归档文件夹, 报告里说明
        for dirpath, dirnames, _names in os.walk(root):
            skipped_dirs += sum(1 for d in dirnames if is_archive_dir(os.path.join(dirpath, d)))

    if not files:
        sys.exit(f"没有找到图片文件: {root}")

    print(f"=== 图片去重归档 ({'执行' if args.apply else '预演, 不会改动文件'}) ===")
    print(f"\n正在扫描 {len(files)} 张图片...")

    if args.mode == "exact":
        groups, unreadable, hash_by_path = group_exact(files, print_progress), [], None
    else:
        threshold = min(max(args.threshold, 0.0), 1.0)
        groups, hash_by_path, unreadable = group_similar(
            files, threshold=threshold, method=args.method, progress=print_progress)
        args.threshold = threshold

    plan = build_plan(root, groups, args.keep, hash_by_path)
    print()
    print(report_plan(root, plan, args.mode, args.threshold, args.method,
                      args.keep, unreadable, skipped_dirs))
    print()

    if not plan:
        return
    if not args.apply:
        print("以上只是预演，没有移动任何文件。")
        print(f"确认无误后执行:  python {os.path.basename(__file__)} {args.folder} --apply")
        return

    print("开始归档...")
    log_path, moved, failed = apply_plan(root, plan, args.mode, args.keep, args.log,
                                         args.threshold, args.method)
    print(f"\n完成: 移动 {moved} 张图片到 {sum(1 for g in plan if g['folder'])} 个归档文件夹。")
    print(f"日志: {log_path}")
    print(f"撤销: python {os.path.basename(__file__)} --undo {log_path}")
    if failed:
        print("\n以下条目未能处理:")
        for path, why in failed:
            print(f"  {path}  ({why})")


if __name__ == "__main__":
    main()
