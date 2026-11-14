/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * PS4 Linux Desktop — OpenOrbis Homebrew Launcher (`eboot.bin`)
 *
 * This is a clean-room Orbis OS userland application built exclusively with the
 * OpenOrbis-PS4-Toolchain (GPL-3.0). It contains **zero** Sony SDK files, zero
 * Sony proprietary libraries and zero retail signing keys.
 *
 * Runtime behaviour (Decision D-01 — internal HDD MUST stay untouched):
 *   1. Reads its own package payload from `/app0/assets/boot/` (read-only mount).
 *   2. Creates `/mnt/usb0/PS4LINUX/` and copies the boot assets there.
 *      Only an external USB mass-storage mount is ever written.
 *   3. Streams `kexec.bin` (fail0verflow/ps4-kexec ring-0 payload, BSD-2-Clause)
 *      to the GoldHEN BinLoader socket on 127.0.0.1:9090.
 *   4. Never calls sceKernelUnlink/sceKernelRmdir/sceKernelFormat on internal
 *      devices, never touches `/dev/sda*`, `/user/`, or any Orbis partition.
 *
 * The launcher deliberately does NOT sign anything: FSELF signatures produced by
 * `create-fself` are *fake* signatures (auth id 0x3800000000000011) and are only
 * accepted by GoldHEN/HEN consoles. This package is NOT installable on a retail,
 * non-jailbroken PS4. See PS4-EXTERNAL-BUILD.md.
 */

#include <errno.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>

#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>

#include <orbis/libkernel.h>

/*
 * The console mounts removable storage under different roots depending on the
 * model, the port and the firmware: /mnt/usb0 is the common one on Fat/Belize,
 * but /mnt/usb1, /mnt/ext0 and /mnt/ext1 are all seen in the wild. Hard-coding
 * /mnt/usb0 made the launcher treat a perfectly good stick as "missing".
 */
static const char *const PS4LD_USB_ROOTS[] = {
    "/mnt/usb0",
    "/mnt/usb1",
    "/mnt/ext0",
    "/mnt/ext1",
};
#define PS4LD_USB_ROOT_COUNT ((int)(sizeof(PS4LD_USB_ROOTS) / sizeof(PS4LD_USB_ROOTS[0])))
#define PS4LD_USB_SUBDIR "PS4LINUX"
#define PS4LD_APP_ASSETS "/app0/assets/boot/"

#define PS4LD_BINLOADER_IP "127.0.0.1"
#define PS4LD_BINLOADER_PORT 9090
#define PS4LD_CONNECT_RETRIES 10

/* FreeBSD/Orbis open(2) flags (Orbis libkernel uses the FreeBSD values). */
#define PS4LD_O_RDONLY 0
#define PS4LD_O_WRONLY 1
#define PS4LD_O_CREAT 0x200
#define PS4LD_O_TRUNC 0x400

static const char *const BOOT_ASSETS[] = {
    "bzImage",
    "initramfs.cpio.gz",
    "bootargs.txt",
    "vram.txt",
    "kexec.bin",
};
#define BOOT_ASSET_COUNT ((int)(sizeof(BOOT_ASSETS) / sizeof(BOOT_ASSETS[0])))

/* ------------------------------------------------------------------------- */
/* Logging: klog (GoldHEN kernel log) + stdout                                */
/* ------------------------------------------------------------------------- */

static void klog(const char *fmt, ...)
{
    char buf[512];
    va_list ap;

    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);

    sceKernelDebugOutText(0, "%s", buf);
    printf("%s", buf);
}

/* ------------------------------------------------------------------------- */
/* File helpers — libkernel only (no stdio buffering surprises on Orbis)      */
/* ------------------------------------------------------------------------- */

/*
 * copy_file() streams one file from the read-only package mount to the USB
 * stick. Returns the number of bytes copied, or a negative error code.
 */
static long copy_file(const char *src, const char *dst)
{
    static char buf[64 * 1024];
    int in, out;
    long total = 0;
    size_t off;

    in = sceKernelOpen(src, PS4LD_O_RDONLY, 0);
    if (in < 0) {
        return -1;
    }

    out = sceKernelOpen(dst, PS4LD_O_WRONLY | PS4LD_O_CREAT | PS4LD_O_TRUNC, 0777);
    if (out < 0) {
        sceKernelClose(in);
        return -2;
    }

    for (;;) {
        ssize_t n = (ssize_t)sceKernelRead(in, buf, sizeof(buf));

        if (n < 0) {
            total = -3;
            break;
        }
        if (n == 0) {
            break;
        }

        off = 0;
        while (off < (size_t)n) {
            size_t written = sceKernelWrite(out, buf + off, (size_t)n - off);

            if (written == 0 || (ssize_t)written < 0) {
                total = -4;
                break;
            }
            off += written;
        }
        if (total < 0) {
            break;
        }
        total += (long)n;
    }

    sceKernelClose(out);
    sceKernelClose(in);
    return total;
}

/*
 * find_writable_usb_dir() probes every removable-storage root and returns the
 * first "<root>/PS4LINUX" directory that actually accepts a write, or NULL.
 *
 * The previous implementation returned a hard error for anything but
 * /mnt/usb0 and main() then did `return 1`; on Orbis an application that exits
 * non-zero is reported by the system as CE-34878-0, i.e. an immediate "the app
 * crashed" dialog with no UI ever drawn. Missing storage is a user-fixable
 * condition, never a crash: report it in the kernel log and keep running.
 */
static const char *find_writable_usb_dir(void)
{
    static char chosen[64];
    int i;

    for (i = 0; i < PS4LD_USB_ROOT_COUNT; i++) {
        char dir[64];
        char probe[96];
        int fd;

        snprintf(dir, sizeof(dir), "%s/%s", PS4LD_USB_ROOTS[i], PS4LD_USB_SUBDIR);
        if (sceKernelMkdir(PS4LD_USB_ROOTS[i], 0777) < 0) {
            klog("[ps4ld] %s not present/present-already (errno=%d)\n",
                 PS4LD_USB_ROOTS[i], errno);
        }
        if (sceKernelMkdir(dir, 0777) < 0) {
            klog("[ps4ld] %s not creatable (errno=%d)\n", dir, errno);
        }

        snprintf(probe, sizeof(probe), "%s/.ps4ld-writable", dir);
        fd = sceKernelOpen(probe, PS4LD_O_WRONLY | PS4LD_O_CREAT | PS4LD_O_TRUNC, 0777);
        if (fd < 0) {
            klog("[ps4ld] %s not writable (errno=%d)\n", dir, errno);
            continue;
        }
        sceKernelClose(fd);
        sceKernelUnlink(probe);
        snprintf(chosen, sizeof(chosen), "%s", dir);
        klog("[ps4ld] using writable staging directory %s\n", chosen);
        return chosen;
    }
    return NULL;
}

/* ------------------------------------------------------------------------- */
/* GoldHEN BinLoader transmission                                            */
/* ------------------------------------------------------------------------- */

/*
 * send_payload_to_binloader() streams a raw payload file to GoldHEN's BinLoader
 * server. GoldHEN executes whatever it receives as a ring-0 ELF payload.
 */
static int send_payload_to_binloader(const char *path)
{
    static char buf[64 * 1024];
    struct sockaddr_in addr;
    int fd, sock, rc = -3, attempt;
    size_t off;

    fd = sceKernelOpen(path, PS4LD_O_RDONLY, 0);
    if (fd < 0) {
        return -1;
    }

    sock = socket(AF_INET, SOCK_STREAM, 0);
    if (sock < 0) {
        sceKernelClose(fd);
        return -2;
    }

    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(PS4LD_BINLOADER_PORT);
    addr.sin_addr.s_addr = inet_addr(PS4LD_BINLOADER_IP);

    for (attempt = 0; attempt < PS4LD_CONNECT_RETRIES; attempt++) {
        if (connect(sock, (struct sockaddr *)&addr, sizeof(addr)) == 0) {
            rc = 0;
            break;
        }
        klog("[ps4ld] BinLoader connect %d/%d failed (errno=%d), retrying...\n",
             attempt + 1, PS4LD_CONNECT_RETRIES, errno);
        sceKernelSleep(1);
    }

    if (rc == 0) {
        for (;;) {
            ssize_t n = (ssize_t)sceKernelRead(fd, buf, sizeof(buf));

            if (n < 0) {
                rc = -4;
                break;
            }
            if (n == 0) {
                break;
            }

            off = 0;
            while (off < (size_t)n) {
                ssize_t sent = send(sock, buf + off, (size_t)n - off, 0);

                if (sent <= 0) {
                    rc = -5;
                    break;
                }
                off += (size_t)sent;
            }
            if (rc != 0) {
                break;
            }
        }
    }

    close(sock);
    sceKernelClose(fd);
    return rc;
}

/* ------------------------------------------------------------------------- */

int main(void)
{
    char src[256];
    char dst[256];
    const char *usb_dir;
    int i;
    int copied = 0;
    int payload_rc;

    setvbuf(stdout, NULL, _IONBF, 0);

    klog("=====================================================\n");
    klog("[ps4ld] PS4 Linux Desktop launcher (OpenOrbis clean-room build)\n");
    klog("[ps4ld] Decision D-01: writes ONLY to removable storage\n");
    klog("[ps4ld] Orbis internal HDD is never mounted, repartitioned or written.\n");
    klog("=====================================================\n");

    usb_dir = find_writable_usb_dir();
    if (usb_dir == NULL) {
        klog("[ps4ld] WARNING: no writable removable storage found "
             "(tried /mnt/usb0, /mnt/usb1, /mnt/ext0, /mnt/ext1).\n");
        klog("[ps4ld] Insert a FAT32/exFAT USB stick, then relaunch. "
             "The kexec payload will still be offered to GoldHEN.\n");
    } else {
        for (i = 0; i < BOOT_ASSET_COUNT; i++) {
            long bytes;

            snprintf(src, sizeof(src), "%s%s", PS4LD_APP_ASSETS, BOOT_ASSETS[i]);
            snprintf(dst, sizeof(dst), "%s/%s", usb_dir, BOOT_ASSETS[i]);

            bytes = copy_file(src, dst);
            if (bytes < 0) {
                klog("[ps4ld] WARN: could not stage %s -> %s (error %ld)\n",
                     src, dst, bytes);
                continue;
            }
            klog("[ps4ld] staged %-20s %8ld bytes -> %s\n", BOOT_ASSETS[i], bytes, dst);
            copied++;
        }
    }

    klog("[ps4ld] staged %d/%d boot assets onto removable storage\n",
         copied, BOOT_ASSET_COUNT);

    /* Hand the ring-0 kexec payload to GoldHEN if BinLoader is listening. */
    snprintf(src, sizeof(src), "%s%s", PS4LD_APP_ASSETS, "kexec.bin");
    payload_rc = send_payload_to_binloader(src);
    if (payload_rc == 0) {
        klog("[ps4ld] kexec payload streamed to GoldHEN BinLoader %s:%d\n",
             PS4LD_BINLOADER_IP, PS4LD_BINLOADER_PORT);
        klog("[ps4ld] The console should now kexec the PS4 Linux kernel from USB.\n");
    } else {
        klog("[ps4ld] BinLoader transmission skipped/failed (rc=%d).\n", payload_rc);
        klog("[ps4ld] Boot assets are already on the USB stick; send "
             "kexec.bin with `bin/ps4-send-payload` from a PC instead.\n");
    }

    klog("[ps4ld] Launcher finished. See PS4-EXTERNAL-BUILD.md for the "
         "hardware-verification checklist (NOT executed on real hardware).\n");

    if (usb_dir == NULL) {
        /* Give the user ~60 s to read the reason in the GoldHEN log instead of
         * being hit by an error dialog the instant they open the app. */
        klog("[ps4ld] holding for 60s so the log can be captured; "
             "the launcher will then exit normally.\n");
        for (i = 0; i < 12; i++) {
            sceKernelSleep(5);
        }
    }

    /* Orbis reports a non-zero process exit as CE-34878-0: always exit 0. */
    sceKernelSleep(3);
    return 0;
}
