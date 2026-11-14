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

#define PS4LD_USB_ROOT "/mnt/usb0"
#define PS4LD_USB_DIR PS4LD_USB_ROOT "/PS4LINUX"
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

static int ensure_usb_dir(void)
{
    if (sceKernelMkdir(PS4LD_USB_ROOT, 0777) < 0) {
        klog("[ps4ld] %s already present or unmountable (errno=%d), continuing\n",
             PS4LD_USB_ROOT, errno);
    }
    if (sceKernelMkdir(PS4LD_USB_DIR, 0777) < 0) {
        klog("[ps4ld] %s already present or unmountable (errno=%d), continuing\n",
             PS4LD_USB_DIR, errno);
    }

    /* Probe writability by opening a marker file. */
    {
        const char *probe = PS4LD_USB_DIR "/.ps4ld-writable";
        int fd = sceKernelOpen(probe, PS4LD_O_WRONLY | PS4LD_O_CREAT | PS4LD_O_TRUNC, 0777);

        if (fd < 0) {
            return -1;
        }
        sceKernelClose(fd);
        sceKernelUnlink(probe);
    }
    return 0;
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
    int i;
    int copied = 0;
    int payload_rc;

    setvbuf(stdout, NULL, _IONBF, 0);

    klog("=====================================================\n");
    klog("[ps4ld] PS4 Linux Desktop launcher (OpenOrbis clean-room build)\n");
    klog("[ps4ld] Decision D-01: writes ONLY to %s\n", PS4LD_USB_DIR);
    klog("[ps4ld] Orbis internal HDD is never mounted, repartitioned or written.\n");
    klog("=====================================================\n");

    if (ensure_usb_dir() != 0) {
        klog("[ps4ld] ERROR: %s is not writable. Insert a FAT32/exFAT USB stick "
             "and re-run the launcher (errno=%d).\n", PS4LD_USB_DIR, errno);
        sceKernelSleep(5);
        return 1;
    }

    for (i = 0; i < BOOT_ASSET_COUNT; i++) {
        long bytes;

        snprintf(src, sizeof(src), "%s%s", PS4LD_APP_ASSETS, BOOT_ASSETS[i]);
        snprintf(dst, sizeof(dst), "%s/%s", PS4LD_USB_DIR, BOOT_ASSETS[i]);

        bytes = copy_file(src, dst);
        if (bytes < 0) {
            klog("[ps4ld] WARN: could not stage %s -> %s (error %ld)\n",
                 src, dst, bytes);
            continue;
        }
        klog("[ps4ld] staged %-20s %8ld bytes -> %s\n", BOOT_ASSETS[i], bytes, dst);
        copied++;
    }

    klog("[ps4ld] staged %d/%d boot assets onto external USB storage\n",
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

    sceKernelSleep(3);
    return 0;
}
