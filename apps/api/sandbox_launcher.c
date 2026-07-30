#define _GNU_SOURCE

#include <errno.h>
#include <fcntl.h>
#include <linux/landlock.h>
#include <seccomp.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <unistd.h>

#ifndef LANDLOCK_ACCESS_FS_REFER
#define LANDLOCK_ACCESS_FS_REFER (1ULL << 13)
#endif
#ifndef LANDLOCK_ACCESS_FS_TRUNCATE
#define LANDLOCK_ACCESS_FS_TRUNCATE (1ULL << 14)
#endif

static void fail(const char *message) {
    fprintf(stderr, "sandbox-launcher: %s: %s\n", message, strerror(errno));
    exit(125);
}

static int landlock_create_ruleset(
    const struct landlock_ruleset_attr *attr,
    size_t size,
    uint32_t flags
) {
    return (int)syscall(__NR_landlock_create_ruleset, attr, size, flags);
}

static int landlock_add_path_rule(int ruleset_fd, const char *path, uint64_t access) {
    int path_fd = open(path, O_PATH | O_CLOEXEC);
    if (path_fd < 0) {
        return -1;
    }
    struct landlock_path_beneath_attr rule = {
        .allowed_access = access,
        .parent_fd = path_fd,
    };
    int result = (int)syscall(
        __NR_landlock_add_rule,
        ruleset_fd,
        LANDLOCK_RULE_PATH_BENEATH,
        &rule,
        0
    );
    int saved_errno = errno;
    close(path_fd);
    errno = saved_errno;
    return result;
}

static uint64_t handled_access_for_abi(int abi) {
    uint64_t access =
        LANDLOCK_ACCESS_FS_EXECUTE |
        LANDLOCK_ACCESS_FS_WRITE_FILE |
        LANDLOCK_ACCESS_FS_READ_FILE |
        LANDLOCK_ACCESS_FS_READ_DIR |
        LANDLOCK_ACCESS_FS_REMOVE_DIR |
        LANDLOCK_ACCESS_FS_REMOVE_FILE |
        LANDLOCK_ACCESS_FS_MAKE_CHAR |
        LANDLOCK_ACCESS_FS_MAKE_DIR |
        LANDLOCK_ACCESS_FS_MAKE_REG |
        LANDLOCK_ACCESS_FS_MAKE_SOCK |
        LANDLOCK_ACCESS_FS_MAKE_FIFO |
        LANDLOCK_ACCESS_FS_MAKE_BLOCK |
        LANDLOCK_ACCESS_FS_MAKE_SYM;
    if (abi >= 2) {
        access |= LANDLOCK_ACCESS_FS_REFER;
    }
    if (abi >= 3) {
        access |= LANDLOCK_ACCESS_FS_TRUNCATE;
    }
    return access;
}

static void add_runtime_roots(int ruleset_fd, uint64_t read_access) {
    const char *raw_roots = getenv("SANDBOX_RUNTIME_ROOTS");
    if (raw_roots == NULL || raw_roots[0] == '\0') {
        errno = EINVAL;
        fail("missing runtime roots");
    }
    char *roots = strdup(raw_roots);
    if (roots == NULL) {
        fail("copying runtime roots");
    }
    char *saveptr = NULL;
    for (char *root = strtok_r(roots, ":", &saveptr);
         root != NULL;
         root = strtok_r(NULL, ":", &saveptr)) {
        if (landlock_add_path_rule(ruleset_fd, root, read_access) < 0) {
            free(roots);
            fail("allowing a runtime root");
        }
    }
    free(roots);
}

static void install_landlock(void) {
    int abi = landlock_create_ruleset(NULL, 0, LANDLOCK_CREATE_RULESET_VERSION);
    if (abi < 1) {
        fail("Landlock is unavailable");
    }
    uint64_t handled_access = handled_access_for_abi(abi);
    struct landlock_ruleset_attr ruleset = {
        .handled_access_fs = handled_access,
    };
    int ruleset_fd = landlock_create_ruleset(&ruleset, sizeof(ruleset), 0);
    if (ruleset_fd < 0) {
        fail("creating Landlock ruleset");
    }

    uint64_t read_access =
        LANDLOCK_ACCESS_FS_EXECUTE |
        LANDLOCK_ACCESS_FS_READ_FILE |
        LANDLOCK_ACCESS_FS_READ_DIR;
    uint64_t write_access =
        LANDLOCK_ACCESS_FS_WRITE_FILE |
        LANDLOCK_ACCESS_FS_READ_FILE |
        LANDLOCK_ACCESS_FS_READ_DIR |
        LANDLOCK_ACCESS_FS_REMOVE_DIR |
        LANDLOCK_ACCESS_FS_REMOVE_FILE |
        LANDLOCK_ACCESS_FS_MAKE_CHAR |
        LANDLOCK_ACCESS_FS_MAKE_DIR |
        LANDLOCK_ACCESS_FS_MAKE_REG |
        LANDLOCK_ACCESS_FS_MAKE_SOCK |
        LANDLOCK_ACCESS_FS_MAKE_FIFO |
        LANDLOCK_ACCESS_FS_MAKE_BLOCK |
        LANDLOCK_ACCESS_FS_MAKE_SYM;
    if (abi >= 2) {
        write_access |= LANDLOCK_ACCESS_FS_REFER;
    }
    if (abi >= 3) {
        write_access |= LANDLOCK_ACCESS_FS_TRUNCATE;
    }

    add_runtime_roots(ruleset_fd, read_access);
    const char *work_dir = getenv("SANDBOX_WORK_DIR");
    const char *runner_path = getenv("SANDBOX_RUNNER_PATH");
    if (work_dir == NULL || runner_path == NULL) {
        close(ruleset_fd);
        errno = EINVAL;
        fail("missing sandbox paths");
    }
    if (landlock_add_path_rule(ruleset_fd, work_dir, write_access) < 0) {
        close(ruleset_fd);
        fail("allowing workspace");
    }
    if (landlock_add_path_rule(
            ruleset_fd,
            runner_path,
            LANDLOCK_ACCESS_FS_READ_FILE
        ) < 0) {
        close(ruleset_fd);
        fail("allowing trusted runner");
    }
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) < 0) {
        close(ruleset_fd);
        fail("setting no_new_privs");
    }
    if (syscall(__NR_landlock_restrict_self, ruleset_fd, 0) < 0) {
        close(ruleset_fd);
        fail("enforcing Landlock");
    }
    close(ruleset_fd);
}

static void deny_named_syscall(scmp_filter_ctx context, const char *name) {
    int syscall_number = seccomp_syscall_resolve_name(name);
    if (syscall_number == __NR_SCMP_ERROR) {
        return;
    }
    if (seccomp_rule_add(
            context,
            SCMP_ACT_ERRNO(EPERM),
            syscall_number,
            0
        ) < 0) {
        errno = EINVAL;
        fail("adding seccomp rule");
    }
}

static void install_seccomp(void) {
    const char *denied[] = {
        "accept", "accept4", "bind", "bpf", "chroot", "clone", "clone3",
        "connect", "delete_module", "execveat", "finit_module", "fork",
        "getpeername", "getsockname", "getsockopt", "init_module",
        "io_uring_enter", "io_uring_register", "io_uring_setup", "kexec_file_load",
        "kexec_load", "keyctl", "kill", "listen", "memfd_create", "migrate_pages",
        "mount", "move_pages", "name_to_handle_at", "open_by_handle_at",
        "perf_event_open", "pidfd_getfd", "pidfd_open", "pidfd_send_signal",
        "pivot_root", "process_vm_readv", "process_vm_writev", "ptrace",
        "recvfrom", "recvmmsg", "recvmsg", "request_key", "sendmmsg", "sendmsg",
        "sendto", "setns", "setsockopt", "shmat", "shmctl", "shmdt", "shmget",
        "shutdown", "socket", "socketpair", "swapoff", "swapon", "tgkill", "tkill",
        "umount2", "unshare", "userfaultfd", "vfork",
    };
    scmp_filter_ctx context = seccomp_init(SCMP_ACT_ALLOW);
    if (context == NULL) {
        errno = ENOMEM;
        fail("creating seccomp filter");
    }
    size_t count = sizeof(denied) / sizeof(denied[0]);
    for (size_t index = 0; index < count; index++) {
        deny_named_syscall(context, denied[index]);
    }
    if (seccomp_load(context) < 0) {
        seccomp_release(context);
        fail("loading seccomp filter");
    }
    seccomp_release(context);
}

int main(int argc, char **argv) {
    if (argc < 2) {
        errno = EINVAL;
        fail("missing command");
    }
    install_landlock();
    install_seccomp();
    execvp(argv[1], &argv[1]);
    fail("starting isolated Python");
    return 125;
}
