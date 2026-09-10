# -*- coding: utf-8 -*-
"""dedup.py 的自动化测试 — 覆盖预演/执行/撤销/重名/相似模式等各条路径

用法:
    python tests/test_dedup.py

测试全部在系统临时目录里进行, 不会碰你的真实图片。
"""
import hashlib, os, shutil, subprocess, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(REPO, ".venv", "bin", "python")
WS = tempfile.mkdtemp(prefix="dedup-test-")   # 临时目录, 用完即删
sys.path.insert(0, os.path.join(REPO, "samples"))
from make_samples import scene
from PIL import Image

fails = []


def check(name, cond, detail=""):
    print(("  [OK]   " if cond else "  [FAIL] ") + name + ("" if cond else f"  <- {detail}"))
    if not cond:
        fails.append(name)


def snap(root, skip_log=True):
    out = {}
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            if skip_log and (f.startswith(".dedup-log") or f == ".dedup-group.json"):
                continue
            p = os.path.join(dp, f)
            out[os.path.relpath(p, root)] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    return out


def run(*args):
    r = subprocess.run([PY, "dedup.py", *args], cwd=REPO, capture_output=True, text=True)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def fresh(name):
    d = os.path.join(WS, name)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    return d


shutil.rmtree(WS, ignore_errors=True)
A, D = scene(1), scene(42)

print("A. 完全相同模式: 内容不变 + 撤销原样还原")
d = fresh("a")
for n in ("a.png", "b.png", "c.png", "sub/e.png"):
    p = os.path.join(d, n)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    A.save(p)
D.save(os.path.join(d, "d.png"))
before = snap(d)
code, out = run(d, "--apply")
after = snap(d)
check("退出码 0", code == 0, out)
check("归档结构 a.png + a/{b,c,e}.png",
      sorted(after) == ["a.png", "a/b.png", "a/c.png", "a/e.png", "d.png"], sorted(after))
check("移动后每个文件字节不变", all(after[k] == before[k] for k in after if k in before))
log = [f for f in os.listdir(d) if f.startswith(".dedup-log")][0]
code, out = run("--undo", os.path.join(d, log))
check("撤销后目录与最初完全一致", snap(d) == before, f"{sorted(snap(d))} != {sorted(before)}")
check("空的归档文件夹已清理", not os.path.exists(os.path.join(d, "a")))

print("B. 只有一张重复图时也建文件夹")
d = fresh("b")
A.save(os.path.join(d, "a.png"))
A.save(os.path.join(d, "b.png"))
run(d, "--apply")
check("得到 a.png + a/b.png", sorted(snap(d)) == ["a.png", "a/b.png"], sorted(snap(d)))

print("C. 已存在同名文件夹时不覆盖, 自动退让成 a_1/")
d = fresh("c")
A.save(os.path.join(d, "a.png"))
A.save(os.path.join(d, "b.png"))
os.makedirs(os.path.join(d, "a"))
open(os.path.join(d, "a", "别人的文件.txt"), "w").write("keep me")
run(d, "--apply")
check("别人的文件夹未被写入", open(os.path.join(d, "a", "别人的文件.txt")).read() == "keep me")
check("退让成 a_1/ 归档",
      sorted(snap(d)) == sorted(["a.png", "a_1/b.png", "a/别人的文件.txt"]), sorted(snap(d)))

print("D. --keep newest / --no-recursive")
d = fresh("d")
A.save(os.path.join(d, "a.png"))
A.save(os.path.join(d, "b.png"))
os.utime(os.path.join(d, "a.png"), (1000, 1000))
os.utime(os.path.join(d, "b.png"), (2000, 2000))
run(d, "--apply", "--keep", "newest")
check("--keep newest 保留 b.png",
      sorted(snap(d)) == ["b.png", "b/a.png"], sorted(snap(d)))
d = fresh("e")
A.save(os.path.join(d, "a.png"))
os.makedirs(os.path.join(d, "sub"))
A.save(os.path.join(d, "sub", "e.png"))
run(d, "--apply", "--no-recursive")
check("--no-recursive 不碰子目录", sorted(snap(d)) == ["a.png", "sub/e.png"], sorted(snap(d)))

print("E. 相似模式(phash, 0.95): 压缩/缩放版本也归并")
d = fresh("f")
base = scene(7)
base.save(os.path.join(d, "base.png"))
base.save(os.path.join(d, "same.jpg"), quality=70)
base.resize((400, 400), Image.LANCZOS).save(os.path.join(d, "edited.png"))
scene(99).save(os.path.join(d, "different.png"))
code, out = run(d, "--apply", "--mode", "similar", "-t", "0.95")
check("压缩/缩放版本归并到 base/",
      sorted(snap(d)) == ["base.png", "base/edited.png", "base/same.jpg", "different.png"],
      sorted(snap(d)))
check("报告里标出相似度", "相似度" in out)

print("F. 中文文件名 与 预演安全")
d = fresh("g")
A.save(os.path.join(d, "原图.png"))
A.save(os.path.join(d, "副本一.png"))
A.save(os.path.join(d, "副本二.png"))
before = snap(d)
code, out = run(d)
check("预演后文件一个没动", snap(d) == before)
check("预演输出提示 --apply", "--apply" in out)
code, out = run(d, "--apply")
check("中文名归档成功",
      sorted(snap(d)) == sorted(["副本一.png", "副本一/原图.png", "副本一/副本二.png"]), sorted(snap(d)))

print("G. --keep oldest")
d = fresh("h")
A.save(os.path.join(d, "a.png"))
A.save(os.path.join(d, "b.png"))
os.utime(os.path.join(d, "a.png"), (1000, 1000))
os.utime(os.path.join(d, "b.png"), (2000, 2000))
run(d, "--apply", "--keep", "oldest")
check("--keep oldest 保留 a.png", sorted(snap(d)) == ["a.png", "a/b.png"], sorted(snap(d)))

print("H. 参数边界与错误处理")
d = fresh("i")
A.save(os.path.join(d, "a.png"))
A.save(os.path.join(d, "b.png"))
code, out = run(d, "--mode", "similar", "-t", "9", "--apply")
check("阈值 9 被夹到 1.00 而不是崩溃", code == 0 and "1.00" in out, out[:200])
code, out = run(os.path.join(WS, "不存在的目录_xyz"))
check("目录不存在时明确报错", code != 0 and "不存在" in out, out)
code, out = run("--undo", os.path.join(WS, "没有这个日志.json"))
check("日志不存在时明确报错", code != 0 and "不存在" in out, out)
code, out = run(d, "--undo", os.path.join(WS, "没有这个日志.json"), "--apply")
check("--apply 与 --undo 互斥", code != 0 and "不能同时" in out, out)

print("I. 归档文件夹里的图片不会被二次扫描")
d = fresh("j")
A.save(os.path.join(d, "a.png"))
A.save(os.path.join(d, "b.png"))
run(d, "--apply")
code, out = run(d, "--apply")
check("重复执行无操作", "没有发现重复" in out, out)

shutil.rmtree(WS, ignore_errors=True)
print()
print("失败项:", fails if fails else "无 —— 全部通过")
sys.exit(1 if fails else 0)
