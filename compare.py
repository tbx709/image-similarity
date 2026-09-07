#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""compare.py — 图片相似度比较工具

用法示例：
    python compare.py 图片A.png 图片B.jpg
    python compare.py 图片A.png 图片B.jpg --method phash
    python compare.py 图片A.png 图片B.jpg --threshold 0.80

内置 6 种比较方法（--method 选择，默认 auto 综合判断）：
    ahash  平均哈希：内容整体轮廓是否一致
    dhash  差异哈希：对亮度、缩放变化更鲁棒
    phash  感知哈希：DCT 频率特征，识别"同一张图的变体"最常用
    ssim   结构相似度：逐像素结构对比，适合压缩/缩放后的图
    hist   颜色直方图：色彩分布是否接近
    mse    均方误差：严格像素对比，仅适合几乎完全相同的图
"""

import argparse
import sys

import numpy as np
from PIL import Image


# ---------------------------------------------------------------- 基础工具

def load_image(path):
    try:
        with Image.open(path) as im:
            return im.convert("RGB")
    except Exception as exc:
        sys.exit(f"无法打开图片: {path} ({exc})")


def gray_arr(img, size=None):
    g = img.convert("L")
    if size is not None:
        g = g.resize(size, Image.LANCZOS)
    return np.asarray(g, dtype=np.float64)


# ---------------------------------------------------------------- 感知哈希 (aHash / dHash / pHash)

def _dct2_mat(n):
    """DCT-II 变换矩阵 (n x n)，用于感知哈希"""
    j = np.arange(n)
    c = np.cos(np.pi * (2 * j + 1)[None, :] * np.arange(n)[:, None] / (2.0 * n))
    c *= np.sqrt(2.0 / n)
    c[0] /= np.sqrt(2.0)
    return c


def _hash_sim(bits_a, bits_b):
    """两个哈希位串的相似度 = 1 - 汉明距离 / 总位数 (0~1)"""
    hamming = int(np.count_nonzero(bits_a != bits_b))
    return 1.0 - hamming / float(bits_a.size)


def ahash(img, hash_size=8):
    a = gray_arr(img, (hash_size + 1, hash_size))
    return a[:, 1:] > a[:, :-1]


def dhash(img, hash_size=8):
    a = gray_arr(img, (hash_size, hash_size + 1))
    return a[1:, :] > a[:-1, :]


def phash(img, hash_size=8, highfreq_factor=4):
    side = hash_size * highfreq_factor
    a = gray_arr(img, (side, side))
    c = _dct2_mat(side)
    dct = c @ a @ c.T
    low = dct[:hash_size, :hash_size]
    return low > np.median(low)


# ---------------------------------------------------------------- SSIM 结构相似度

def _box_mean(a, k):
    """k x k 均值滤波（边缘复制），返回与原图同尺寸数组"""
    pad = k // 2
    ap = np.pad(a, ((pad, pad), (pad, pad)), mode="edge")
    ii = np.zeros((ap.shape[0] + 1, ap.shape[1] + 1))
    ii[1:, 1:] = ap.cumsum(0).cumsum(1)
    h, w = a.shape
    win = ii[k:, k:] - ii[:h, k:] - ii[k:, :w] + ii[:h, :w]
    return win / (k * k)


def ssim(img_a, img_b, win=11):
    """返回 (归一化相似度 0~1, 原始 SSIM -1~1)"""
    size = (min(img_a.width, img_b.width), min(img_a.height, img_b.height))
    a = gray_arr(img_a, size)
    b = gray_arr(img_b, size)
    c1, c2 = (0.01 * 255.0) ** 2, (0.03 * 255.0) ** 2
    mu1, mu2 = _box_mean(a, win), _box_mean(b, win)
    s11, s22, s12 = _box_mean(a * a, win), _box_mean(b * b, win), _box_mean(a * b, win)
    sg11, sg22, sg12 = s11 - mu1 * mu1, s22 - mu2 * mu2, s12 - mu1 * mu2
    num = (2.0 * mu1 * mu2 + c1) * (2.0 * sg12 + c2)
    den = (mu1 * mu1 + mu2 * mu2 + c1) * (sg11 + sg22 + c2)
    raw = float(np.mean(num / den))
    return (raw + 1.0) / 2.0, raw


# ---------------------------------------------------------------- 色彩直方图 (Bhattacharyya 系数)

def hist_sim(img_a, img_b, bins=16):
    def to_hist(img):
        a = np.asarray(img.resize((256, 256)), dtype=np.int64)
        scale = 256 // bins
        idx = ((a[:, :, 0] // scale) * bins * bins
               + (a[:, :, 1] // scale) * bins
               + (a[:, :, 2] // scale))
        h = np.bincount(idx.ravel(), minlength=bins ** 3).astype(np.float64)
        return h / h.sum()
    ha, hb = to_hist(img_a), to_hist(img_b)
    return float(np.sum(np.sqrt(ha * hb)))


# ---------------------------------------------------------------- 像素均方误差

def mse_score(img_a, img_b):
    a = np.asarray(img_a.resize((256, 256)), dtype=np.float64)
    b = np.asarray(img_b.resize((256, 256)), dtype=np.float64)
    mse = float(np.mean((a - b) ** 2))
    return mse, float(max(0.0, 1.0 - np.sqrt(mse) / 255.0))


# ---------------------------------------------------------------- 判定

def label(score, threshold):
    if score >= threshold:
        return "相似"
    if score >= threshold - 0.20:
        return "相近"
    return "不相似"


def auto_verdict(ph, ss, hh):
    # 强否定信号: 感知哈希和色彩分布都低，直接判不同（避免 SSIM 在平滑图上高估）
    if ph < 0.60 and hh < 0.35:
        return "不相似 —— 感知哈希与色彩分布均表明两张图内容不同"
    if ph >= 0.90 or (ph >= 0.75 and ss >= 0.90):
        return "相似 —— 很可能为同一张图（或其压缩/缩放/微调版本）"
    if ss >= 0.80 and ph >= 0.55:
        return "相似 —— 结构高度接近，可能经过明显修改"
    if hh >= 0.95:
        return "色彩分布几乎一致（结构可能有差异），请结合其他方法判断"
    if ph >= 0.65 or ss >= 0.60:
        return "相近 —— 有一定相似性，是否同一张图请人工确认"
    return "不相似 —— 可以判定为不同图片"


def print_row(name, score, threshold):
    print(f"  {name:<20} {score:8.4f}    {label(score, threshold)}")


# ---------------------------------------------------------------- 主流程

def main():
    # Windows 下输出重定向到文件时保证 UTF-8, 避免中文乱码
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="比较两张图片的相似度")
    ap.add_argument("img_a", help="图片 A 路径")
    ap.add_argument("img_b", help="图片 B 路径")
    ap.add_argument("-m", "--method", default="auto",
                    choices=["auto", "ahash", "dhash", "phash", "ssim", "hist", "mse"],
                    help="比较方法 (默认 auto 综合判断)")
    ap.add_argument("-t", "--threshold", type=float, default=0.85,
                    help="判定为“相似”的阈值 0~1 (默认 0.85)")
    args = ap.parse_args()

    img_a = load_image(args.img_a)
    img_b = load_image(args.img_b)
    threshold = min(max(args.threshold, 0.0), 1.0)

    print(f"图片 A: {args.img_a}  ({img_a.width}x{img_a.height})")
    print(f"图片 B: {args.img_b}  ({img_b.width}x{img_b.height})")
    print()

    method = args.method
    if method == "auto":
        ph = _hash_sim(phash(img_a), phash(img_b))
        ss, ss_raw = ssim(img_a, img_b)
        hh = hist_sim(img_a, img_b)
        mse, ms = mse_score(img_a, img_b)
        print("  方法                相似度     判定")
        print_row("phash    感知哈希", ph, 0.85)
        print_row("ssim     结构相似度", ss, 0.85)
        print_row("hist     色彩直方图", hh, 0.90)
        print_row("mse      像素均方误差", ms, 0.95)
        print(f"  (ssim 原始值: {ss_raw:+.4f}   mse 原始值: {mse:8.2f})")
        print()
        print(f"综合判定: {auto_verdict(ph, ss, hh)}")

    elif method in ("ahash", "dhash", "phash"):
        fn = {"ahash": ahash, "dhash": dhash, "phash": phash}[method]
        score = _hash_sim(fn(img_a), fn(img_b))
        print(f"  方法: {method} ({fn.__doc__ or ''})")
        print_row(method, score, threshold)

    elif method == "ssim":
        score, raw = ssim(img_a, img_b)
        print(f"  方法: ssim (结构相似度, 已归一化到 0~1, 原始值 {raw:+.4f})")
        print_row("ssim", score, threshold)

    elif method == "hist":
        score = hist_sim(img_a, img_b)
        print(f"  方法: hist (色彩直方图 Bhattacharyya 系数)")
        print_row("hist", score, max(threshold, 0.90))

    else:  # mse
        mse, score = mse_score(img_a, img_b)
        print(f"  方法: mse (像素均方误差, 原始值 {mse:8.2f})")
        print_row("mse", score, max(threshold, 0.95))

    print()
    print("注: 相似度取值 0~1, 越大越相似。")


if __name__ == "__main__":
    main()
