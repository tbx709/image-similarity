#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 samples/ 下的示例图片，用于测试 compare.py

用法:
    python samples/make_samples.py
"""

import os
import random

from PIL import Image, ImageDraw, ImageEnhance

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = HERE


def scene(seed, size=(512, 512)):
    """生成一个随机场景（形状/颜色不同），用于模拟真实图片"""
    rnd = random.Random(seed)
    img = Image.new("RGB", size)
    d = ImageDraw.Draw(img)
    base_hue = rnd.choice([(30, 60, 160), (160, 60, 40), (20, 130, 90), (90, 40, 150)])
    for y in range(size[1]):
        t = y / size[1]
        color = tuple(int(base_hue[i] * (0.4 + 0.6 * t)) for i in range(3))
        d.line([(0, y), (size[0], y)], fill=color)
    for _ in range(rnd.randint(6, 12)):
        x, y = rnd.randint(0, size[0]), rnd.randint(0, size[1])
        r = rnd.randint(20, 90)
        col = tuple(rnd.randint(0, 255) for _ in range(3))
        if rnd.random() < 0.5:
            d.ellipse([x, y, x + r, y + r], fill=col)
        else:
            d.rectangle([x, y, x + r, y + r], fill=col)
        d.line([(x, y), (x + rnd.randint(-160, 160), y + rnd.randint(-160, 160))],
               fill=(255, 255, 255), width=3)
    return img


def main():
    base = scene(1)
    base.save(os.path.join(OUT, "base.png"))            # 原图
    base.save(os.path.join(OUT, "same.jpg"), quality=70)  # 压缩后的同一张图

    edit = ImageEnhance.Brightness(base).enhance(1.15)
    edit = edit.resize((450, 450), Image.LANCZOS)
    edit.save(os.path.join(OUT, "edited.png"))          # 缩放 + 提亮后的版本

    scene(42).save(os.path.join(OUT, "different.png"))  # 完全不同的图
    print(f"示例图片已生成到 {OUT}")


if __name__ == "__main__":
    main()
