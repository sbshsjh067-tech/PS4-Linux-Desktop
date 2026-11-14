// SPDX-License-Identifier: GPL-2.0-only
/*
 * ps4_hdmi_guard.c — Freestanding Jaguar-Pure Initramfs HDMI Bridge Guard & EDID Verifier
 *
 * Built freestanding (`-static -nostdlib -march=btver2 -mno-avx2 -mno-fma -mno-bmi2`)
 * directly over Linux x86_64 syscalls so:
 *   1. Binary size inside initramfs.cpio.gz is ~9 KiB (instead of ~680 KiB glibc static).
 *   2. ZERO multi-arch glibc AVX2/AVX-512 IFUNC stubs exist anywhere in the ELF image.
 *   3. Runs safely on every PS4 Linux kernel (5.4, 6.15, 7.0-Clean) with zero shared libs.
 *
 * Hardware Function (BOOT STAGE 6 & BOOT STAGE 7):
 *   - Inspects /sys/bus/pci/devices/0000:00:01.0/device and /sys/class/drm/card0-HDMI-A-1/edid
 *   - On MN864729 consoles (PS4 Fat Belize 0x9922/0x9923 & Slim/Pro 0x9924), monitors
 *     HDMI output enable (0x1e00 bit 0, 0x1e02 bits 4..6) and video mute (0x705f bit 7)
 *     via /dev/icc (char major 73, minor 0, ICC service 0x10), restoring output if muted.
 */

#include <stdint.h>
#include <stddef.h>

/* Linux x86_64 syscall numbers */
#define SYS_read      0
#define SYS_write     1
#define SYS_close     3
#define SYS_ioctl     16
#define SYS_nanosleep 35
#define SYS_exit      60
#define SYS_openat    257
#define SYS_mknodat   259

#define AT_FDCWD      (-100)
#define O_RDONLY      00
#define O_WRONLY      01
#define O_RDWR        02
#define O_CLOEXEC     02000000
#define S_IFCHR       0020000

struct ps4_timespec {
    long tv_sec;
    long tv_nsec;
};

struct ps4_icc_cmd {
    uint8_t major;
    uint16_t minor;
    void *data;
    uint16_t length;
    void *reply;
    uint16_t reply_length;
};

/* _IOWR('I', 1, struct ps4_icc_cmd) on x86_64 (sizeof(struct ps4_icc_cmd) == 32 == 0x20) */
#define PS4_ICC_IOCTL_CMD (0xC0000000UL | ((unsigned long)sizeof(struct ps4_icc_cmd) << 16) | ('I' << 8) | 1UL)
#define PS4_ICC_MAJOR_NR  73
#define PS4_BRIDGE_SVC    0x10

#define REG_HDMI_OUT_EN   0x1e00
#define REG_HDMI_LANE_EN  0x1e02
#define REG_VMUTECNT      0x705f

static inline long sys1(long nr, long a1)
{
    long ret;
    __asm__ volatile("syscall" : "=a"(ret) : "a"(nr), "D"(a1) : "rcx", "r11", "memory");
    return ret;
}

static inline long sys2(long nr, long a1, long a2)
{
    long ret;
    __asm__ volatile("syscall" : "=a"(ret) : "a"(nr), "D"(a1), "S"(a2) : "rcx", "r11", "memory");
    return ret;
}

static inline long sys3(long nr, long a1, long a2, long a3)
{
    long ret;
    __asm__ volatile("syscall" : "=a"(ret) : "a"(nr), "D"(a1), "S"(a2), "d"(a3) : "rcx", "r11", "memory");
    return ret;
}

static inline long sys4(long nr, long a1, long a2, long a3, long a4)
{
    long ret;
    register long r10 __asm__("r10") = a4;
    __asm__ volatile("syscall" : "=a"(ret) : "a"(nr), "D"(a1), "S"(a2), "d"(a3), "r"(r10) : "rcx", "r11", "memory");
    return ret;
}

static size_t s_len(const char *s)
{
    size_t n = 0;
    while (s[n])
        n++;
    return n;
}

static int s_eq(const char *a, const char *b)
{
    size_t i = 0;
    while (a[i] && b[i]) {
        if (a[i] != b[i])
            return 0;
        i++;
    }
    return a[i] == b[i];
}

static void b_zero(void *dst, size_t n)
{
    uint8_t *p = (uint8_t *)dst;
    for (size_t i = 0; i < n; i++)
        p[i] = 0;
}

static void b_copy(void *dst, const void *src, size_t n)
{
    uint8_t *d = (uint8_t *)dst;
    const uint8_t *s = (const uint8_t *)src;
    for (size_t i = 0; i < n; i++)
        d[i] = s[i];
}

static size_t append_str(char *buf, size_t cap, size_t pos, const char *s)
{
    while (*s && pos + 1 < cap) {
        buf[pos++] = *s++;
    }
    buf[pos] = '\0';
    return pos;
}

static size_t append_int(char *buf, size_t cap, size_t pos, int val)
{
    char tmp[16];
    int n = 0;
    if (val < 0) {
        if (pos + 1 < cap)
            buf[pos++] = '-';
        val = -val;
    }
    if (val == 0) {
        tmp[n++] = '0';
    } else {
        while (val > 0 && n < (int)sizeof(tmp)) {
            tmp[n++] = (char)('0' + (val % 10));
            val /= 10;
        }
    }
    while (n > 0 && pos + 1 < cap) {
        buf[pos++] = tmp[--n];
    }
    buf[pos] = '\0';
    return pos;
}

static size_t append_hex2(char *buf, size_t cap, size_t pos, uint8_t v)
{
    static const char hex[] = "0123456789abcdef";
    if (pos + 4 < cap) {
        buf[pos++] = '0';
        buf[pos++] = 'x';
        buf[pos++] = hex[(v >> 4) & 0x0f];
        buf[pos++] = hex[v & 0x0f];
        buf[pos] = '\0';
    }
    return pos;
}

static void emit_log(int to_stdout, const char *line)
{
    size_t len = s_len(line);
    if (to_stdout) {
        (void)sys3(SYS_write, 1, (long)line, (long)len);
    }
    long kfd = sys4(SYS_openat, AT_FDCWD, (long)"/dev/kmsg", O_WRONLY | O_CLOEXEC, 0);
    if (kfd >= 0) {
        (void)sys3(SYS_write, kfd, (long)line, (long)len);
        (void)sys1(SYS_close, kfd);
    }
}

static void sleep_sec(long sec)
{
    struct ps4_timespec ts;
    ts.tv_sec = sec;
    ts.tv_nsec = 0;
    (void)sys2(SYS_nanosleep, (long)&ts, 0);
}

static int read_small_text(const char *path, char *out, size_t cap)
{
    long fd = sys4(SYS_openat, AT_FDCWD, (long)path, O_RDONLY | O_CLOEXEC, 0);
    if (fd < 0) {
        out[0] = '\0';
        return -1;
    }
    long n = sys3(SYS_read, fd, (long)out, (long)(cap - 1));
    (void)sys1(SYS_close, fd);
    if (n < 0) {
        out[0] = '\0';
        return -1;
    }
    out[n] = '\0';
    while (n > 0 && (out[n - 1] == '\n' || out[n - 1] == '\r' || out[n - 1] == ' ')) {
        out[--n] = '\0';
    }
    return (int)n;
}

static int verify_edid_file(const char *path)
{
    uint8_t edid[256];
    long fd = sys4(SYS_openat, AT_FDCWD, (long)path, O_RDONLY | O_CLOEXEC, 0);
    if (fd < 0)
        return -1;
    long n = sys3(SYS_read, fd, (long)edid, (long)sizeof(edid));
    (void)sys1(SYS_close, fd);
    if (n < 128)
        return 0;
    static const uint8_t magic[8] = {0x00, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x00};
    for (int i = 0; i < 8; i++) {
        if (edid[i] != magic[i])
            return 0;
    }
    uint32_t sum = 0;
    for (int i = 0; i < 128; i++)
        sum += edid[i];
    return ((sum & 0xff) == 0) ? 1 : 0;
}

static int bridge_run_cmd(long icc_fd, uint8_t code, uint8_t major, uint8_t minor,
                          const uint8_t *ops, uint8_t count, uint8_t op_len,
                          uint8_t *reply, size_t reply_cap)
{
    uint8_t req[64];
    uint16_t body_len = (uint16_t)(4 + count * op_len);
    uint16_t total_len = (uint16_t)(4 + body_len);
    if (total_len > sizeof(req))
        return -1;

    req[0] = code;
    req[1] = (uint8_t)(total_len & 0xff);
    req[2] = (uint8_t)(total_len >> 8);
    req[3] = 1;
    req[4] = major;
    req[5] = (uint8_t)body_len;
    req[6] = minor;
    req[7] = count;
    b_copy(req + 8, ops, (size_t)count * op_len);

    struct ps4_icc_cmd cmd;
    b_zero(&cmd, sizeof(cmd));
    cmd.major = PS4_BRIDGE_SVC;
    cmd.minor = 0;
    cmd.data = req;
    cmd.length = total_len;
    cmd.reply = reply;
    cmd.reply_length = (uint16_t)reply_cap;

    long rc = sys3(SYS_ioctl, icc_fd, (long)PS4_ICC_IOCTL_CMD, (long)&cmd);
    if (rc < 5 || reply[0] != 0 || reply[1] != 0)
        return -1;
    return (int)rc;
}

static int bridge_read_u8(long icc_fd, uint16_t reg)
{
    uint8_t reply[0x7f0];
    uint8_t op[4] = {1, (uint8_t)(reg >> 8), (uint8_t)(reg & 0xff), 0};
    if (bridge_run_cmd(icc_fd, 1, 1, 1, op, 1, 4, reply, sizeof(reply)) < 9)
        return -1;
    return reply[8];
}

static void bridge_unmute_mn864729(long icc_fd)
{
    uint8_t reply[0x7f0];
    uint8_t masks[10] = {
        1, 0x1e, 0x02, 0x70, 0x70,
        1, 0x1e, 0x00, 0x01, 0x01
    };
    uint8_t unmute[4] = {1, 0x70, 0x5f, 0x10};
    (void)bridge_run_cmd(icc_fd, 4, 2, 3, masks, 2, 5, reply, sizeof(reply));
    (void)bridge_run_cmd(icc_fd, 4, 2, 2, unmute, 1, 4, reply, sizeof(reply));
}

int guard_main(int argc, char **argv)
{
    const char *sysfs_root = "/sys";
    int once = 0;
    int self_test = 0;

    for (int i = 1; i < argc; i++) {
        if (s_eq(argv[i], "once") || s_eq(argv[i], "--once")) {
            once = 1;
        } else if (s_eq(argv[i], "--self-test")) {
            self_test = 1;
            once = 1;
        } else if (s_eq(argv[i], "--sysfs-root") && i + 1 < argc) {
            sysfs_root = argv[++i];
        }
    }

    char pci_path[256];
    char edid_path[256];
    char status_path[256];
    size_t p = 0;
    p = append_str(pci_path, sizeof(pci_path), 0, sysfs_root);
    append_str(pci_path, sizeof(pci_path), p, "/bus/pci/devices/0000:00:01.0/device");

    p = append_str(edid_path, sizeof(edid_path), 0, sysfs_root);
    append_str(edid_path, sizeof(edid_path), p, "/class/drm/card0-HDMI-A-1/edid");

    p = append_str(status_path, sizeof(status_path), 0, sysfs_root);
    append_str(status_path, sizeof(status_path), p, "/class/drm/card0-HDMI-A-1/status");

    char pci_id[32];
    read_small_text(pci_path, pci_id, sizeof(pci_id));

    char conn_status[32];
    if (read_small_text(status_path, conn_status, sizeof(conn_status)) < 0) {
        append_str(conn_status, sizeof(conn_status), 0, "unknown");
    }
    int edid_ok = verify_edid_file(edid_path);

    if (self_test) {
        char msg[256];
        size_t m = append_str(msg, sizeof(msg), 0, "ps4_hdmi_guard: self-test pci_id=");
        m = append_str(msg, sizeof(msg), m, pci_id[0] ? pci_id : "non-ps4");
        m = append_str(msg, sizeof(msg), m, " connector=");
        m = append_str(msg, sizeof(msg), m, conn_status);
        m = append_str(msg, sizeof(msg), m, " edid_valid=");
        m = append_int(msg, sizeof(msg), m, edid_ok);
        m = append_str(msg, sizeof(msg), m, "\n");
        emit_log(1, msg);
        return 0;
    }

    if (!s_eq(pci_id, "0x9922") && !s_eq(pci_id, "0x9923") && !s_eq(pci_id, "0x9924")) {
        return 0;
    }

    long icc_fd = -1;
    for (int tries = 0; icc_fd < 0 && tries < 30; tries++) {
        /* makedev(73, 0) = (73 << 8) = 0x4900 */
        (void)sys4(SYS_mknodat, AT_FDCWD, (long)"/dev/icc", S_IFCHR | 0600, (PS4_ICC_MAJOR_NR << 8));
        icc_fd = sys4(SYS_openat, AT_FDCWD, (long)"/dev/icc", O_RDWR | O_CLOEXEC, 0);
        if (icc_fd < 0)
            sleep_sec(1);
    }
    if (icc_fd < 0)
        return 1;

    for (;;) {
        int en = bridge_read_u8(icc_fd, REG_HDMI_OUT_EN);
        int mute = bridge_read_u8(icc_fd, REG_VMUTECNT);
        if (en >= 0 && mute >= 0 && (!(en & 0x01) || (mute & 0x80))) {
            char msg[160];
            size_t m = append_str(msg, sizeof(msg), 0, "ps4_hdmi_guard: restoring muted MN864729 (0x1e00=");
            m = append_hex2(msg, sizeof(msg), m, (uint8_t)en);
            m = append_str(msg, sizeof(msg), m, " 0x705f=");
            m = append_hex2(msg, sizeof(msg), m, (uint8_t)mute);
            m = append_str(msg, sizeof(msg), m, ")\n");
            emit_log(0, msg);
            bridge_unmute_mn864729(icc_fd);
        }
        if (once)
            break;
        sleep_sec(2);
    }

    (void)sys1(SYS_close, icc_fd);
    return 0;
}

__asm__(
    ".text\n"
    ".globl _start\n"
    "_start:\n"
    "    xor %ebp, %ebp\n"
    "    mov (%rsp), %rdi\n"
    "    lea 8(%rsp), %rsi\n"
    "    and $-16, %rsp\n"
    "    call guard_main\n"
    "    mov %eax, %edi\n"
    "    mov $60, %eax\n"
    "    syscall\n"
);
