#!/bin/sh
# Integrate SukiSU-Nova into this kernel tree (non-GKI, Linux 4.19).
# Usage: sh scripts/nova/setup_nova.sh [commit-or-tag]
#   env KSU_VERSION_PIN=<int>   pin KSU_VERSION reported by the kernel (default 35000)
set -eu

REF="${1:-c60f21b9e00e35e898f8d21e0612465b76b9beec}"
KSU_VERSION_PIN="${KSU_VERSION_PIN:-35000}"
ROOT="$(pwd)"

[ -d drivers ] || { echo "[!] must run from kernel root"; exit 1; }
command -v git >/dev/null || { echo "[!] git missing"; exit 1; }

echo "[*] SukiSU-Nova ref: $REF"
rm -rf KernelSU
git clone --depth 1 --filter=blob:none --no-checkout \
    https://github.com/SukiSU-Nova/SukiSU-Nova.git KernelSU
(
    cd KernelSU
    git fetch --depth 1 origin "$REF"
    git checkout -q FETCH_HEAD
    echo "[*] checked out $(git rev-parse --short=8 HEAD)"
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
for f in "$K/feature/sucompat.c" "$K/feature/patch_memory.c" "$K/hook/arm64/patch_memory.c"; do
    [ -f "$f" ] && sed -i '/#include <linux\/pgtable.h>/d' "$f"
done
# 3) MODULE_IMPORT_NS shim
if [ -f "$K/kernel_compat.h" ] && ! grep -q 'KSU_MODULE_IMPORT_NS_SHIM' "$K/kernel_compat.h"; then
    cat >> "$K/kernel_compat.h" <<'EOF'

/* KSU_MODULE_IMPORT_NS_SHIM */
#ifndef MODULE_IMPORT_NS
#define MODULE_IMPORT_NS(x)
#endif
EOF
fi

# 4) MODULE_IMPORT_NS is used in core/init.c, which does not include kernel_compat.h
if [ -f "$K/core/init.c" ] && ! grep -q 'KSU_MODULE_IMPORT_NS_SHIM' "$K/core/init.c"; then
    python3 - "$K/core/init.c" <<'PY'
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
print('[*] MODULE_IMPORT_NS shim injected into core/init.c')
PY
fi

# ---------- build knobs ----------
if [ -f "$K/Makefile" ]; then
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
