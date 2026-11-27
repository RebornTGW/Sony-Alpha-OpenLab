/* test_helper.c - host self-test for the OGP1 apply engine.
 *
 * Builds tiny blobs in memory and applies them to a local buffer window, so the
 * logic (stock verify, write, readback, record iteration, error codes) can be
 * checked on any host with a C compiler - no aarch64 and no camera needed.
 *
 *   cc -I../include -o test_helper test_helper.c ../src/helper.c && ./test_helper
 */
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include "ogpatch.h"

static int fails = 0;
#define CHECK(cond, msg) do { \
    if (cond) { printf("  ok   %s\n", msg); } \
    else { printf("  FAIL %s\n", msg); fails++; } } while (0)

/* append one record to buf at *pos */
static void put_record(uint8_t *buf, size_t *pos, uint64_t vaddr,
                       const uint8_t *stock, const uint8_t *target, uint32_t len,
                       uint32_t flags) {
    uint8_t *p = buf + *pos;
    for (int i = 0; i < 8; i++) p[i] = (uint8_t)(vaddr >> (8 * i));
    for (int i = 0; i < 4; i++) p[8 + i] = (uint8_t)(len >> (8 * i));
    for (int i = 0; i < 4; i++) p[12 + i] = (uint8_t)(flags >> (8 * i));
    memcpy(p + 16, stock, len);
    memcpy(p + 16 + len, target, len);
    *pos += 16 + (size_t)len * 2;
}

static void put_header(uint8_t *buf, size_t *pos, uint32_t count) {
    buf[0] = 'O'; buf[1] = 'G'; buf[2] = 'P'; buf[3] = '1';
    for (int i = 0; i < 4; i++) buf[4 + i] = (uint8_t)(count >> (8 * i));
    *pos = 8;
}

int main(void) {
    const uint64_t BASE = 0x401000000ull;
    uint8_t mem[256];
    og_window win = { mem, BASE, sizeof(mem) };

    /* seed window with "stock" pattern */
    for (size_t i = 0; i < sizeof(mem); i++) mem[i] = (uint8_t)(i & 0xff);

    uint8_t blob[512];
    size_t pos;

    /* --- test 1: apply two good records (one data, one code) --- */
    {
        put_header(blob, &pos, 2);
        uint8_t s0[4] = { 0x10, 0x11, 0x12, 0x13 };   /* mem[16..19] */
        uint8_t t0[4] = { 0x00, 0x0f, 0x00, 0x0a };   /* 3840x2560 word */
        put_record(blob, &pos, BASE + 16, s0, t0, 4, 0);
        uint8_t s1[2] = { 0x80, 0x81 };               /* mem[128..129] */
        uint8_t t1[2] = { 0xde, 0xad };
        put_record(blob, &pos, BASE + 128, s1, t1, 2, OG_FLAG_CODE);

        int r = og_apply(blob, pos, &win);
        CHECK(r == 2, "apply returns 2 records");
        CHECK(mem[16] == 0x00 && mem[19] == 0x0a, "data record written");
        CHECK(mem[128] == 0xde && mem[129] == 0xad, "code record written");
    }

    /* --- test 2: stock mismatch aborts on that record, index reported --- */
    {
        for (size_t i = 0; i < sizeof(mem); i++) mem[i] = (uint8_t)(i & 0xff);
        put_header(blob, &pos, 1);
        uint8_t bad_stock[4] = { 0xAA, 0xBB, 0xCC, 0xDD };  /* != mem[16..] */
        uint8_t t[4] = { 1, 2, 3, 4 };
        put_record(blob, &pos, BASE + 16, bad_stock, t, 4, 0);
        int r = og_apply(blob, pos, &win);
        CHECK(r < 0 && og_result_err(r) == -OG_ERR_STOCK, "stock mismatch -> OG_ERR_STOCK");
        CHECK(og_result_index(r) == 0, "failing index is 0");
        CHECK(mem[16] == 0x10, "nothing written on stock mismatch");
    }

    /* --- test 3: out-of-range vaddr --- */
    {
        put_header(blob, &pos, 1);
        uint8_t s[2] = { 0, 0 }, t[2] = { 1, 1 };
        put_record(blob, &pos, BASE + 1000, s, t, 2, 0);  /* past 256-byte window */
        int r = og_apply(blob, pos, &win);
        CHECK(r < 0 && og_result_err(r) == -OG_ERR_RANGE, "range check -> OG_ERR_RANGE");
    }

    /* --- test 4: bad magic --- */
    {
        uint8_t junk[8] = { 'X', 'X', 'X', 'X', 0, 0, 0, 0 };
        int r = og_apply(junk, sizeof(junk), &win);
        CHECK(r == OG_ERR_MAGIC, "bad magic -> OG_ERR_MAGIC");
    }

    printf(fails ? "\nFAILED (%d)\n" : "\nOK\n", fails);
    return fails ? 1 : 0;
}
