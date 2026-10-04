# -*- coding: utf-8 -*-
"""
构建自解压安装包(纯 Python 实现, 不依赖 NSIS / IExpress)
================================================================
把 payload 目录里的文件(桌面版 exe / 网页版 exe / README / 安装脚本)打包进
一个"自解压 exe", 双击即可完成安装:

  原理: 产物 = [自解压启动器 exe] + [zip 归档(直接追加在 exe 尾部)]
        Python 的 zipfile 模块会自动识别"前置了其它数据"的 zip(计算
        concat 偏移), 因此启动器可以直接用 zipfile.ZipFile(sys.argv[0])
        打开自身并解压, 无需手工计算偏移。

  之所以自带启动器: 用户机器上不一定有 Python / 7-Zip / NSIS,
  而目标是"双击一个 exe 就能装好"。

用法: python build_installer.py <payload_dir> <输出exe>
"""
import os
import sys
import shutil
import zipfile
import tempfile
import subprocess


LAUNCHER_SRC = r'''# -*- coding: utf-8 -*-
"""红包乱斗 安装包自解压启动器(由 build_installer.py 自动生成, 请勿手改)。

原理: 本 exe = 启动器代码 + 追加在尾部的 zip 归档。Python 的 zipfile 会自动
处理"前置了其它字节"的 zip(通过计算中央目录与本地头之间的偏移差), 因此这里
可以直接用 zipfile.ZipFile(自身) 打开并解压出安装脚本。
"""
import os
import sys
import zipfile
import shutil
import tempfile
import subprocess


def main():
    me = os.path.abspath(sys.argv[0])
    tmp = tempfile.mkdtemp(prefix="aram_setup_")
    try:
        with zipfile.ZipFile(me) as z:
            z.extractall(tmp)
        setup = None
        for cand in ("setup.cmd", "安装.cmd", "install.cmd"):
            p = os.path.join(tmp, cand)
            if os.path.exists(p):
                setup = p
                break
        if setup is None:
            print("[错误] 安装包内缺少安装脚本")
            input("按回车键退出...")
            return 1
        return subprocess.call(["cmd", "/c", setup], cwd=tmp)
    except Exception as e:
        print("[错误] 安装包解压失败:", e)
        input("按回车键退出...")
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
'''


def _build_launcher(dest: str):
    """用本机 Python + PyInstaller 编一个 console 版启动器 exe(安装过程要显示文字)。"""
    tmp = tempfile.mkdtemp(prefix="aram_launcher_")
    try:
        src = os.path.join(tmp, "launcher.py")
        with open(src, "w", encoding="utf-8") as f:
            f.write(LAUNCHER_SRC)
        subprocess.check_call([
            sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
            "--onefile", "--console", "--name", "aram_setup_launcher",
            "--distpath", tmp, "--workpath", os.path.join(tmp, "work"),
            "--specpath", tmp, src,
        ])
        built = os.path.join(tmp, "aram_setup_launcher.exe")
        shutil.copyfile(built, dest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def build(payload: str, out_exe: str) -> int:
    payload = os.path.abspath(payload)
    out_exe = os.path.abspath(out_exe)
    if not os.path.isdir(payload):
        print("[错误] payload 目录不存在:", payload)
        return 1
    files = [f for f in sorted(os.listdir(payload))
             if os.path.isfile(os.path.join(payload, f))]
    if not files:
        print("[错误] payload 目录为空:", payload)
        return 1
    print("[1/3] 打包 %d 个文件到 zip ..." % len(files))
    tmp_zip = out_exe + ".zip.tmp"
    with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=6) as z:
        for name in files:
            z.write(os.path.join(payload, name), arcname=name)

    print("[2/3] 编译自解压启动器 ...")
    _build_launcher(out_exe)

    print("[3/3] 追加归档 (%.1f MB) ..." % (os.path.getsize(tmp_zip) / 1048576))
    with open(out_exe, "ab") as out, open(tmp_zip, "rb") as zf:
        shutil.copyfileobj(zf, out, 1024 * 1024)
    os.remove(tmp_zip)

    print("完成: %s  (%.1f MB)" % (out_exe, os.path.getsize(out_exe) / 1048576))
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python build_installer.py <payload_dir> <输出exe>")
        sys.exit(1)
    sys.exit(build(sys.argv[1], sys.argv[2]))
