/* Narrow first physical EQ test: -6 dB once, then restore 0 dB immediately.
 * No CLI-supplied request values; no retries, reboot, or flash operations. */
#include <libusb.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

static const uint8_t expected_caps[12] = {
    0x45, 0x4f, 0x49, 0x43, 0x01, 0x00, 0x08, 0x00, 0x00, 0x00, 0x00, 0x00
};

static int transfer(libusb_device_handle *h, uint8_t bm, uint8_t req,
                    uint16_t value, uint16_t index, unsigned char *data,
                    uint16_t length, unsigned timeout) {
    return libusb_control_transfer(h, bm, req, value, index, data, length, timeout);
}

static int query(libusb_device_handle *h, const char *command, uint16_t len,
                 const char *expected, uint16_t response_len) {
    unsigned char response[32] = {0};
    int n = transfer(h, 0x40, 6, 0, 0, (unsigned char *)command, len, 2000);
    if (n != len) {
        fprintf(stderr, "%s_OUT_FAILED result=%d\n", command, n);
        return -1;
    }
    n = transfer(h, 0xc0, 12, 0, 0, response, response_len, 2000);
    if (n != response_len || memcmp(response, expected, response_len)) {
        fprintf(stderr, "%s_RESPONSE_FAILED result=%d\n", command, n);
        return -1;
    }
    printf("%s_RESPONSE=", command);
    for (unsigned i = 0; i < response_len; i++) printf("%s%02x", i ? " " : "", response[i]);
    putchar('\n');
    return 0;
}

int main(void) {
    libusb_context *ctx = NULL;
    libusb_device **devices = NULL;
    libusb_device_handle *h = NULL;
    int rc = 1;
    if (libusb_init(&ctx) != 0) {
        fputs("ABORT=libusb_init\n", stderr);
        return 1;
    }
    ssize_t count = libusb_get_device_list(ctx, &devices);
    if (count < 0) {
        fputs("ABORT=enumeration\n", stderr);
        goto done;
    }
    unsigned matches = 0;
    libusb_device *match = NULL;
    for (ssize_t i = 0; i < count; i++) {
        struct libusb_device_descriptor d;
        if (libusb_get_device_descriptor(devices[i], &d) != 0) {
            fputs("ABORT=descriptor\n", stderr);
            goto done;
        }
        if (d.idVendor == 0x04e8 && d.idProduct == 0xa05e) {
            matches++;
            match = devices[i];
            printf("USB_ID=04e8:a05e bus=%u address=%u\n",
                   libusb_get_bus_number(devices[i]),
                   libusb_get_device_address(devices[i]));
        }
    }
    if (matches != 1) {
        fprintf(stderr, "ABORT=expected_one_04e8:a05e observed=%u\n", matches);
        goto done;
    }
    if (libusb_open(match, &h) != 0) {
        fputs("ABORT=open\n", stderr);
        goto done;
    }
    struct libusb_device_descriptor opened;
    if (libusb_get_device_descriptor(libusb_get_device(h), &opened) != 0 ||
        opened.idVendor != 0x04e8 || opened.idProduct != 0xa05e) {
        fputs("ABORT=opened_identity_changed\n", stderr);
        goto done;
    }
    libusb_free_device_list(devices, 1);
    devices = NULL;

    unsigned char minus6[4] = {0x00, 0x00, 0xc0, 0xc0};
    printf("SET_EQ_TEST_MINUS6 setup=40 e1 4f 45 43 49 04 00 payload=00 00 c0 c0\n");
    int n = transfer(h, 0x40, 0xe1, 0x454f, 0x4943, minus6, 4, 5000);
    if (n != 4) {
        fprintf(stderr, "SET_EQ_TEST_MINUS6_FAILED result=%d; no retry or restore sent\n", n);
        goto done;
    }
    puts("SET_EQ_TEST_MINUS6_ACK=YES");

    unsigned char zero[4] = {0, 0, 0, 0};
    printf("SET_EQ_TEST_RESTORE_0DB setup=40 e1 4f 45 43 49 04 00 payload=00 00 00 00\n");
    n = transfer(h, 0x40, 0xe1, 0x454f, 0x4943, zero, 4, 5000);
    if (n != 4) {
        fprintf(stderr, "SET_EQ_TEST_RESTORE_FAILED result=%d; no retry\n", n);
        goto done;
    }
    puts("SET_EQ_TEST_RESTORE_ACK=YES");

    const char version[] = "0.23_051101_ab";
    const char check[] = "1.1";
    if (query(h, "QUERY_SW_VER", 12, version, 14) != 0 ||
        query(h, "CHECK", 5, check, 3) != 0) goto done;

    unsigned char caps[12] = {0};
    n = transfer(h, 0xc0, 0xe0, 0x454f, 0x4943, caps, sizeof(caps), 1500);
    if (n != 12 || memcmp(caps, expected_caps, sizeof(caps))) {
        fprintf(stderr, "POST_RESTORE_CAPS_FAILED result=%d\n", n);
        goto done;
    }
    printf("POST_RESTORE_GET_EOIC_CAPS=");
    for (unsigned i = 0; i < sizeof(caps); i++) printf("%s%02x", i ? " " : "", caps[i]);
    puts("\nEQ_TEST_SEQUENCE=PASS");
    rc = 0;
done:
    if (devices) libusb_free_device_list(devices, 1);
    if (h) libusb_close(h);
    libusb_exit(ctx);
    return rc;
}
