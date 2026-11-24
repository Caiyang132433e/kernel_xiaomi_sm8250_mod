#!/bin/sh
# Integrate SukiSU-Nova into this kernel tree (non-GKI, Linux 4.19).
#
#   sh scripts/nova/setup_nova.sh [branch] [commit-or-tag]
#     branch  : builtin (default, manual hooks) | main (kprobes) | builtin-new
#     ref     : commit/tag/branch to check out
#   env KSU_VERSION_PIN=<int>   pin the KSU_VERSION reported to the manager
set -eu

BRANCH="${1:-builtin}"
REF="${2:-4bec532dd447e2852aa8932afa768255350c103a}"
KSU_VERSION_PIN="${KSU_VERSION_PIN:-30007}"
ROOT="$(pwd)"

[ -d drivers ] || { echo "[!] must run from kernel root"; exit 1; }
command -v git >/dev/null || { echo "[!] git missing"; exit 1; }

echo "[*] SukiSU-Nova branch=$BRANCH ref=$REF"
rm -rf KernelSU
git clone --depth 1 --filter=blob:none --no-checkout \
    --branch "$BRANCH" https://github.com/SukiSU-Nova/SukiSU-Nova.git KernelSU
(
    cd KernelSU
    git fetch --depth 1 origin "$REF" 2>/dev/null || true
    git checkout -q "$REF" 2>/dev/null || git checkout -q FETCH_HEAD
    echo "[*] checked out $(git rev-parse --short=8 HEAD) on $(git rev-parse --abbrev-ref HEAD)"
)

K=KernelSU/kernel
[ -d "$K" ] || { echo "[!] KernelSU/kernel not found"; exit 1; }

# ---------- Linux 4.19 compatibility fixes ----------
# 1) static_call.h / hex.h do not exist in 4.19
[ -f "$K/kernel_includes.h" ] && \
    sed -i '/#include <linux\/static_call.h>/d; /#include <linux\/hex.h>/d' "$K/kernel_includes.h"
for f in $(grep -rl '#include <linux/hex.h>' "$K" 2>/dev/null || true); do
    sed -i 's|#include <linux/hex.h>|#include <linux/kernel.h>|' "$f"
done
for f in $(grep -rl '#include <linux/minmax.h>' "$K" 2>/dev/null || true); do
    sed -i 's|#include <linux/minmax.h>|#include <linux/kernel.h>|' "$f"
done
# 2) linux/pgtable.h does not exist in 4.19
for f in $(grep -rl '#include <linux/pgtable.h>' "$K" 2>/dev/null || true); do
    sed -i '/#include <linux\/pgtable.h>/d' "$f"
done

# 3) MODULE_IMPORT_NS shim (added in 5.4). Inject wherever it is actually used,
#    because some translation units do not include kernel_compat.h.
shim_module_import_ns() {
    f="$1"
    [ -f "$f" ] || return 0
    grep -q 'MODULE_IMPORT_NS' "$f" || return 0
    grep -q 'KSU_MODULE_IMPORT_NS_SHIM' "$f" && return 0
    python3 - "$f" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
shim = ('/* KSU_MODULE_IMPORT_NS_SHIM */\n'
        '#ifndef MODULE_IMPORT_NS\n'
        '#define MODULE_IMPORT_NS(x)\n'
        '#endif\n')
if '#include <linux/module.h>' in s:
    s = s.replace('#include <linux/module.h>', '#include <linux/module.h>\n' + shim, 1)
else:
    s = shim + s
open(p, 'w').write(s)
print('[*] MODULE_IMPORT_NS shim ->', p)
PY
}
[ -f "$K/kernel_compat.h" ] && shim_module_import_ns "$K/kernel_compat.h"
[ -f "$K/core/init.c" ] && shim_module_import_ns "$K/core/init.c"

# 4) KPM glue guarded by CONFIG_KPM (4.19 has no <linux/set_memory.h> niceties)
if [ -f "$K/kernel_compat.h" ] && grep -q '^#define KSU_CAN_USE_KPM' "$K/kernel_compat.h" \
   && ! grep -q 'KSU_CAN_USE_KPM_GUARD' "$K/kernel_compat.h"; then
    sed -i 's|^#define KSU_CAN_USE_KPM|/* KSU_CAN_USE_KPM_GUARD */\n#if defined(CONFIG_KPM)\n#define KSU_CAN_USE_KPM|' "$K/kernel_compat.h"
    sed -i '/#define KSU_CAN_USE_KPM/a #endif' "$K/kernel_compat.h"
fi

# ---------- build knobs ----------
if [ -f "$K/Makefile" ]; then
    grep -q 'Wno-unused-variable' "$K/Makefile" || \
        sed -i '/^ccflags-y += -Wno-strict-prototypes/i ccflags-y += -Wno-unused-variable -Wno-macro-redefined' "$K/Makefile"
    python3 - "$K/Makefile" "$KSU_VERSION_PIN" <<'PY'
import re, sys
path, ver = sys.argv[1], sys.argv[2]
s = open(path).read()
s2, n = re.subn(r'^KSU_VERSION\s*:=.*$', 'KSU_VERSION     := %s' % ver, s, count=1, flags=re.M)
if n:
    open(path, 'w').write(s2)
print('[*] KSU_VERSION pinned to', ver)
PY
fi

# ---------- wire into the kernel tree ----------
ln -sfn "$ROOT/KernelSU/kernel" drivers/kernelsu
grep -q 'kernelsu' drivers/Makefile || echo 'obj-$(CONFIG_KSU) += kernelsu/' >> drivers/Makefile
grep -q 'drivers/kernelsu/Kconfig' drivers/Kconfig || \
    sed -i '/endmenu/i source "drivers/kernelsu/Kconfig"' drivers/Kconfig

echo "[*] SukiSU-Nova integrated into drivers/kernelsu"
