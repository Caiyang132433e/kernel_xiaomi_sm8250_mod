#!/usr/bin/env python3
"""Wire the in-tree SUSFS 1.5.7 into SukiSU-Nova (builtin).

Why a separate symbol: fs/Makefile builds fs/susfs.o on CONFIG_KSU_SUSFS, but
Nova's own code keys 2.x API paths off the same symbol.  We rename the build
switch to CONFIG_KSU_SUSFS_LEGACY and provide a legacy Kconfig menu whose
sub-options (CONFIG_KSU_SUSFS_SUS_PATH, ...) are exactly what the in-tree
fs/*.c hooks already test.

Edits (all idempotent, fail loudly if an anchor moves):
  1. fs/Makefile                : obj-$(CONFIG_KSU_SUSFS) -> _LEGACY
  2. KernelSU/kernel/Kconfig    : drop 2.x SUSFS menu, add legacy menu
  3. kernel/sys.c               : prctl hook -> susfs_legacy_prctl()
  4. KernelSU/kernel/ksu_main.c : call susfs_legacy_init()
  5. KernelSU/kernel/Kbuild     : build feature/susfs_legacy.o
  6. copy scripts/nova/susfs_legacy.c into KernelSU/kernel/feature/
"""
import re
import shutil
import sys
from pathlib import Path

MARK = "/* KSU_SUSFS_LEGACY_HOOK */"

LEGACY_KCONFIG = """
menu "KernelSU - SUSFS (legacy 1.5.7)"

config KSU_SUSFS_LEGACY
	bool "SUSFS 1.5.7 support (legacy glue)"
	depends on KSU
	default y
	help
	  Build the in-tree SUSFS 1.5.7 implementation and its prctl glue.
	  Do NOT confuse with the upstream 2.x option set, which is removed
	  by the build scripts.

config KSU_SUSFS_SUS_PATH
	bool "hide suspicious paths"
	depends on KSU_SUSFS_LEGACY
	default y

config KSU_SUSFS_SUS_MOUNT
	bool "hide suspicious mounts"
	depends on KSU_SUSFS_LEGACY
	default y

config KSU_SUSFS_SUS_KSTAT
	bool "spoof suspicious kstat"
	depends on KSU_SUSFS_LEGACY
	default y

config KSU_SUSFS_TRY_UMOUNT
	bool "try umount for current mnt ns"
	depends on KSU_SUSFS_LEGACY
	default y

config KSU_SUSFS_SPOOF_UNAME
	bool "spoof uname"
	depends on KSU_SUSFS_LEGACY
	default y

config KSU_SUSFS_ENABLE_LOG
	bool "enable susfs log"
	depends on KSU_SUSFS_LEGACY
	default y

config KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS
	bool "hide ksu/susfs symbols"
	depends on KSU_SUSFS_LEGACY
	default y

config KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG
	bool "spoof cmdline / bootconfig"
	depends on KSU_SUSFS_LEGACY
	default y

config KSU_SUSFS_OPEN_REDIRECT
	bool "open redirect"
	depends on KSU_SUSFS_LEGACY
	default n

config KSU_SUSFS_SUS_SU
	bool "sus_su"
	depends on KSU_SUSFS_LEGACY
	default n

config KSU_SUSFS_HAS_MAGIC_MOUNT
	bool
	depends on KSU_SUSFS_LEGACY
	default n

config KSU_SUSFS_SUS_OVERLAYFS
	bool
	depends on KSU_SUSFS_LEGACY
	default n

endmenu
"""


def patch_makefile():
    p = Path("fs/Makefile")
    s = p.read_text(encoding="utf-8", errors="surrogateescape")
    old = "obj-$(CONFIG_KSU_SUSFS) += susfs.o"
    new = "obj-$(CONFIG_KSU_SUSFS_LEGACY) += susfs.o"
    if new in s:
        print("[=] fs/Makefile already patched")
        return
    if old not in s:
        sys.exit("[!] fs/Makefile: susfs.o line not found")
    p.write_text(s.replace(old, new, 1), encoding="utf-8", errors="surrogateescape")
    print("[+] fs/Makefile: susfs.o now keyed on CONFIG_KSU_SUSFS_LEGACY")


def patch_kconfig():
    p = Path("KernelSU/kernel/Kconfig")
    s = p.read_text(encoding="utf-8", errors="surrogateescape")
    if "KSU_SUSFS_LEGACY" in s:
        print("[=] Nova Kconfig already has the legacy menu")
        return
    i = s.find('menu "KernelSU - SUSFS"')
    if i < 0:
        sys.exit('[!] Nova Kconfig: menu "KernelSU - SUSFS" not found')
    j = s.find("\nendmenu", i)
    if j < 0:
        sys.exit("[!] Nova Kconfig: matching endmenu not found")
    s = s[:i] + s[j + len("\nendmenu"):]
    s = s.rstrip("\n") + "\n" + LEGACY_KCONFIG
    p.write_text(s, encoding="utf-8", errors="surrogateescape")
    print("[+] Nova Kconfig: 2.x SUSFS menu removed, legacy menu added")


def patch_sys_prctl():
    p = Path("kernel/sys.c")
    s = p.read_text(encoding="utf-8", errors="surrogateescape")
    if MARK in s:
        print("[=] kernel/sys.c already patched")
        return
    m = re.search(r"SYSCALL_DEFINE5\(prctl,", s)
    if not m:
        sys.exit("[!] kernel/sys.c: prctl syscall not found")
    decl = s.find("\tlong error;", m.end())
    if decl < 0:
        sys.exit("[!] kernel/sys.c: 'long error;' not found in prctl")
    eol = s.find("\n", decl)
    hook = f"""
{MARK}
#ifdef CONFIG_KSU_SUSFS_LEGACY
	{{
		extern int susfs_legacy_prctl(int, unsigned long, unsigned long,
					      unsigned long, unsigned long);
		susfs_legacy_prctl(option, arg2, arg3, arg4, arg5);
	}}
#endif
"""
    s = s[: eol + 1] + hook + s[eol + 1:]
    p.write_text(s, encoding="utf-8", errors="surrogateescape")
    print("[+] kernel/sys.c: prctl hook installed")


def patch_ksu_init():
    p = Path("KernelSU/kernel/ksu_main.c")
    s = p.read_text(encoding="utf-8", errors="surrogateescape")
    if "susfs_legacy_init" in s:
        print("[=] ksu_main.c already patched")
        return
    anchor = "\tksu_feature_init();"
    if anchor not in s:
        sys.exit("[!] ksu_main.c: ksu_feature_init() anchor not found")
    block = ("#ifdef CONFIG_KSU_SUSFS_LEGACY\n"
             "\tsusfs_legacy_init();\n"
             "#endif\n")
    s = s.replace(anchor, block + anchor, 1)
    # forward declaration, the object lives in feature/
    s = s.replace("int __init kernelsu_init(void)",
                  "void susfs_legacy_init(void);\n\nint __init kernelsu_init(void)", 1)
    p.write_text(s, encoding="utf-8", errors="surrogateescape")
    print("[+] ksu_main.c: susfs_legacy_init() wired")


def patch_kbuild():
    p = Path("KernelSU/kernel/Kbuild")
    s = p.read_text(encoding="utf-8", errors="surrogateescape")
    line = "kernelsu-objs += feature/susfs_legacy.o"
    if line in s:
        print("[=] Kbuild already patched")
        return
    anchor = "kernelsu-objs += feature/adb_root.o"
    if anchor not in s:
        sys.exit("[!] Kbuild: adb_root anchor not found")
    s = s.replace(anchor, line + "\n" + anchor, 1)
    p.write_text(s, encoding="utf-8", errors="surrogateescape")
    print("[+] Kbuild: feature/susfs_legacy.o added")


def copy_glue():
    src = Path("scripts/nova/susfs_legacy.c")
    dst = Path("KernelSU/kernel/feature/susfs_legacy.c")
    if not src.is_file():
        sys.exit(f"[!] glue source missing: {src}")
    shutil.copyfile(src, dst)
    print(f"[+] copied {src} -> {dst}")


if __name__ == "__main__":
    patch_makefile()
    patch_kconfig()
    patch_sys_prctl()
    patch_ksu_init()
    patch_kbuild()
    copy_glue()
    print("[*] SUSFS 1.5.7 legacy glue applied")
