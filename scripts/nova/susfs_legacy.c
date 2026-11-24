// SPDX-License-Identifier: GPL-2.0
/*
 * SUSFS 1.5.7 <-> SukiSU-Nova glue.
 *
 * SUSFS 1.5.x talks to the kernel through prctl(2):
 *     prctl(0xDEADBEEF, CMD_SUSFS_*, data, NULL, &error)
 * and only uid 0 may issue commands.  Nova has no prctl handler, so this
 * file provides one plus the few symbols the in-tree fs/susfs.c expects.
 *
 * Enabled by CONFIG_KSU_SUSFS_LEGACY.  The umbrella CONFIG_KSU_SUSFS is
 * deliberately NOT defined: Nova's 2.x SUSFS code paths key off it.
 */
#ifdef CONFIG_KSU_SUSFS_LEGACY

#include <linux/kernel.h>
#include <linux/cred.h>
#include <linux/uaccess.h>
#include <linux/susfs.h>
#include <linux/susfs_def.h>

#include "klog.h" // IWYU pragma: keep

#define SUSFS_PRLCT_OPTION 0xDEADBEEF

/* fs/susfs.c calls this to decide whether the caller may change state. */
bool susfs_is_current_ksu_domain(void)
{
	return current_uid().val == 0;
}

static void susfs_put_err(int __user *errp, int err)
{
	if (errp && copy_to_user(errp, &err, sizeof(err)))
		pr_info("susfs: copy_to_user(err) failed\n");
}

static bool susfs_arg_ok(const void __user *p, size_t len)
{
	return p && access_ok(VERIFY_WRITE, p, len);
}

int susfs_legacy_prctl(int option, unsigned long cmd, unsigned long arg3,
		       unsigned long arg4, unsigned long arg5)
{
	void __user *data = (void __user *)arg3;
	int __user *errp = (int __user *)arg5;
	int error = 0;

	if (option != SUSFS_PRLCT_OPTION)
		return 0;
	/* only the root context may drive susfs */
	if (current_uid().val != 0)
		return 0;

	switch (cmd) {
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
	case CMD_SUSFS_ADD_SUS_PATH:
		if (!susfs_arg_ok(data, sizeof(struct st_susfs_sus_path))) {
			error = -EFAULT;
			break;
		}
		error = susfs_add_sus_path((struct st_susfs_sus_path __user *)data);
		break;
#endif
#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT
	case CMD_SUSFS_ADD_SUS_KSTAT:
	case CMD_SUSFS_ADD_SUS_KSTAT_STATICALLY:
		if (!susfs_arg_ok(data, sizeof(struct st_susfs_sus_kstat))) {
			error = -EFAULT;
			break;
		}
		error = susfs_add_sus_kstat((struct st_susfs_sus_kstat __user *)data);
		break;
	case CMD_SUSFS_UPDATE_SUS_KSTAT:
		if (!susfs_arg_ok(data, sizeof(struct st_susfs_sus_kstat))) {
			error = -EFAULT;
			break;
		}
		error = susfs_update_sus_kstat((struct st_susfs_sus_kstat __user *)data);
		break;
#endif
#ifdef CONFIG_KSU_SUSFS_TRY_UMOUNT
	case CMD_SUSFS_ADD_TRY_UMOUNT:
		if (!susfs_arg_ok(data, sizeof(struct st_susfs_try_umount))) {
			error = -EFAULT;
			break;
		}
		error = susfs_add_try_umount((struct st_susfs_try_umount __user *)data);
		break;
	case CMD_SUSFS_RUN_UMOUNT_FOR_CURRENT_MNT_NS:
		susfs_try_umount(current_uid().val);
		break;
#endif
#ifdef CONFIG_KSU_SUSFS_SPOOF_UNAME
	case CMD_SUSFS_SET_UNAME:
		if (!susfs_arg_ok(data, sizeof(struct st_susfs_uname))) {
			error = -EFAULT;
			break;
		}
		error = susfs_set_uname((struct st_susfs_uname __user *)data);
		break;
#endif
#ifdef CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG
	case CMD_SUSFS_SET_CMDLINE_OR_BOOTCONFIG:
		error = susfs_set_cmdline_or_bootconfig((char __user *)data);
		break;
#endif
#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
	case CMD_SUSFS_ADD_OPEN_REDIRECT:
		if (!susfs_arg_ok(data, sizeof(struct st_susfs_open_redirect))) {
			error = -EFAULT;
			break;
		}
		error = susfs_add_open_redirect(
			(struct st_susfs_open_redirect __user *)data);
		break;
#endif
#ifdef CONFIG_KSU_SUSFS_ENABLE_LOG
	case CMD_SUSFS_ENABLE_LOG:
		susfs_set_log(!!arg3);
		break;
#endif
	case CMD_SUSFS_SHOW_VERSION: {
		const char *ver = SUSFS_VERSION;
		size_t len = strlen(ver) + 1;

		if (!susfs_arg_ok(data, len)) {
			error = -EFAULT;
			break;
		}
		if (copy_to_user(data, ver, len))
			error = -EFAULT;
		break;
	}
	case CMD_SUSFS_SHOW_ENABLED_FEATURES: {
		u64 features = 0;

#ifdef CONFIG_KSU_SUSFS_SUS_PATH
		features |= 1ULL << 0;
#endif
#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
		features |= 1ULL << 1;
#endif
#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT
		features |= 1ULL << 4;
#endif
#ifdef CONFIG_KSU_SUSFS_TRY_UMOUNT
		features |= 1ULL << 6;
#endif
#ifdef CONFIG_KSU_SUSFS_SPOOF_UNAME
		features |= 1ULL << 8;
#endif
#ifdef CONFIG_KSU_SUSFS_ENABLE_LOG
		features |= 1ULL << 9;
#endif
#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
		features |= 1ULL << 12;
#endif
#ifdef CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG
		features |= 1ULL << 13;
#endif
		if (!susfs_arg_ok(data, sizeof(features))) {
			error = -EFAULT;
			break;
		}
		if (copy_to_user(data, &features, sizeof(features)))
			error = -EFAULT;
		break;
	}
	case CMD_SUSFS_SHOW_VARIANT: {
		const char *variant = SUSFS_VARIANT;
		size_t len = strlen(variant) + 1;

		if (!susfs_arg_ok(data, len)) {
			error = -EFAULT;
			break;
		}
		if (copy_to_user(data, variant, len))
			error = -EFAULT;
		break;
	}
	default:
		pr_info("susfs: unsupported cmd 0x%lx\n", cmd);
		error = -EINVAL;
		break;
	}

	susfs_put_err(errp, error);
	return 0;
}

void susfs_legacy_init(void)
{
	susfs_init();
	pr_info("susfs: legacy glue ready, version %s\n", SUSFS_VERSION);
}

#endif /* CONFIG_KSU_SUSFS_LEGACY */
