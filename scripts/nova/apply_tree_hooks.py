#!/usr/bin/env python3
"""Adapt this 4.19 tree to what SukiSU-Nova(builtin) actually expects.

1) fs/exec.c
   The tree calls, on the "hook disabled" branch:
       ksu_handle_execveat_sucompat((int *)AT_FDCWD, &filename, NULL, NULL, NULL);
   Nova's implementation dereferences argv (sulog capture), so this NULL
   dereferences as soon as an app execs /system/bin/su:
       Unable to handle kernel NULL pointer dereference
       pc : ksu_handle_execveat_sucompat+0xc0
   Fix: pass the real &argv / &envp locals.

2) kernel/reboot.c
   Nova's supercall channel is reboot(2) with magic numbers. The tree never
   calls ksu_handle_sys_reboot(), so the manager cannot talk to the kernel.
   Fix: add the hook at the top of SYSCALL_DEFINE4(reboot).

Both edits are idempotent and fail loudly if the anchors move.
"""
import re
import sys

MARK = "/* KSU_MANUAL_HOOK */"

EXEC_OLD = "ksu_handle_execveat_sucompat((int *)AT_FDCWD, &filename, NULL, NULL, NULL)"
EXEC_NEW = "ksu_handle_execveat_sucompat((int *)AT_FDCWD, &filename, &argv, &envp, NULL)"

REBOOT_BLOCK = f"""{MARK}
#ifdef CONFIG_KSU
	{{
		extern int ksu_handle_sys_reboot(int, int, unsigned int, void __user **);
		ksu_handle_sys_reboot(magic1, magic2, cmd, &arg);
	}}
#endif
"""


def patch_exec():
    p = "fs/exec.c"
    s = open(p, encoding="utf-8", errors="surrogateescape").read()
    if EXEC_NEW in s:
        print("[=] fs/exec.c: already patched")
        return
    n = s.count(EXEC_OLD)
    if n != 2:
        sys.exit(f"[!] fs/exec.c: expected 2 NULL-arg call sites, found {n}")
    s = s.replace(EXEC_OLD, EXEC_NEW)
    open(p, "w", encoding="utf-8", errors="surrogateescape").write(s)
    print("[+] fs/exec.c: 2 call sites now pass real argv/envp")


def patch_reboot():
    p = "kernel/reboot.c"
    s = open(p, encoding="utf-8", errors="surrogateescape").read()
    if MARK in s:
        print("[=] kernel/reboot.c: already patched")
        return
    m = re.search(r"SYSCALL_DEFINE4\(reboot,\s*int,\s*magic1", s)
    if not m:
        sys.exit("[!] kernel/reboot.c: reboot syscall anchor not found")
    brace = s.find("{", m.end())
    if brace < 0:
        sys.exit("[!] kernel/reboot.c: no opening brace")
    # insert after the last declaration ("int ret = 0;") to stay
    # -Wdeclaration-after-statement clean
    decl = s.find("int ret = 0;", brace)
    if decl < 0:
        sys.exit("[!] kernel/reboot.c: 'int ret = 0;' not found")
    eol = s.find("\n", decl)
    s = s[: eol + 1] + "\n" + REBOOT_BLOCK + s[eol + 1 :]
    open(p, "w", encoding="utf-8", errors="surrogateescape").write(s)
    print("[+] kernel/reboot.c: ksu_handle_sys_reboot hook added")


if __name__ == "__main__":
    patch_exec()
    patch_reboot()
