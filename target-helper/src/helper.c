/* helper.c - Open Gate on-camera micro-helper (clean-room MIT, freestanding).
 *
 * Reads an OGP1 patch blob and applies each record into a mapped memory window:
 *   verify stock -> write 64-byte-aligned line(s) -> read back -> flush i-cache
 *   for code records. No libc, no external deps, no Sony firmware bytes.
 *
 * Build: aarch64-linux-gnu, -ffreestanding -nostdlib -fPIC -shared (see Makefile
 * / build.zig). The physical-memory mapping is supplied by the loader as an
 * og_window; this object only contains logic.
 */
#include "ogpatch.h"

/* ---- tiny freestanding mem helpers (avoid libc) ------------------------- */

static int og_memcmp(const uint8_t *a, const uint8_t *b, uint32_t n) {
    for (uint32_t i = 0; i < n; i++) {
        if (a[i] != b[i]) return (int)a[i] - (int)b[i];
    }
    return 0;
}

static void og_memcpy(uint8_t *d, const uint8_t *s, uint32_t n) {
    for (uint32_t i = 0; i < n; i++) d[i] = s[i];
}

static uint32_t og_rd_u32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8)
         | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static uint64_t og_rd_u64(const uint8_t *p) {
    return (uint64_t)og_rd_u32(p) | ((uint64_t)og_rd_u32(p + 4) << 32);
}

/* ---- ARM64 cache maintenance ------------------------------------------- */

void og_clear_icache(void *start, size_t len) {
#if defined(__aarch64__)
    uintptr_t base = (uintptr_t)start & ~(uintptr_t)(OG_LINE - 1);
    uintptr_t end  = ((uintptr_t)start + len + (OG_LINE - 1))
                     & ~(uintptr_t)(OG_LINE - 1);
    /* clean D-cache to Point of Unification, line by line */
    for (uintptr_t a = base; a < end; a += OG_LINE)
        __asm__ __volatile__("dc cvau, %0" :: "r"(a) : "memory");
    __asm__ __volatile__("dsb ish" ::: "memory");
    /* invalidate I-cache to PoU, line by line */
    for (uintptr_t a = base; a < end; a += OG_LINE)
        __asm__ __volatile__("ic ivau, %0" :: "r"(a) : "memory");
    __asm__ __volatile__("dsb ish" ::: "memory");
    __asm__ __volatile__("isb" ::: "memory");
#else
    /* portable fallback for host builds / non-aarch64 */
    __builtin___clear_cache((char *)start, (char *)start + len);
#endif
}

/* data-cache clean + barrier for a plain (non-code) data write, so the new
 * bytes are visible to other observers before we read them back. */
static void og_flush_data(void *start, size_t len) {
#if defined(__aarch64__)
    uintptr_t base = (uintptr_t)start & ~(uintptr_t)(OG_LINE - 1);
    uintptr_t end  = ((uintptr_t)start + len + (OG_LINE - 1))
                     & ~(uintptr_t)(OG_LINE - 1);
    for (uintptr_t a = base; a < end; a += OG_LINE)
        __asm__ __volatile__("dc civac, %0" :: "r"(a) : "memory");
    __asm__ __volatile__("dsb ish" ::: "memory");
#else
    (void)start; (void)len;
#endif
}

/* ---- apply one record --------------------------------------------------- */

/* Resolve a [vaddr, vaddr+len) record to a local pointer inside the window,
 * or return 0 if it is out of range. */
static uint8_t *og_resolve(const og_window *win, uint64_t vaddr, uint32_t len) {
    if (vaddr < win->base_vaddr) return 0;
    uint64_t off = vaddr - win->base_vaddr;
    if (off > win->size || (uint64_t)len > win->size - off) return 0;
    return win->base + off;
}

static int og_apply_record(const og_window *win, uint64_t vaddr, uint32_t len,
                           uint32_t flags, const uint8_t *stock,
                           const uint8_t *target) {
    uint8_t *dst = og_resolve(win, vaddr, len);
    if (!dst) return OG_ERR_RANGE;

    /* 1. verify stock before touching anything */
    if (og_memcmp(dst, stock, len) != 0) return OG_ERR_STOCK;

    /* 2. atomic-per-line write: we touch only [dst, dst+len), but the store is
     *    issued on 64-byte-aligned cache lines (the BIONZ XR write unit). Here
     *    the bytes are copied in place; the following cache ops publish the whole
     *    affected line range to the Point of Unification. */
    og_memcpy(dst, target, len);

    if (flags & OG_FLAG_CODE) {
        og_clear_icache(dst, len);      /* code: D-clean + I-invalidate + ISB */
    } else {
        og_flush_data(dst, len);        /* data: D-clean so readback is true */
    }

    /* 3. readback verify */
    if (og_memcmp(dst, target, len) != 0) return OG_ERR_READBACK;
    return OG_OK;
}

/* ---- apply the whole blob ---------------------------------------------- */

/* ---- stateful toggle: cached session, swap without re-parsing/re-verify -- */

typedef struct {
    uint64_t vaddr;
    uint32_t len;
    uint32_t flags;
    uint8_t  stock[OG_TOGGLE_MAX_LEN];
    uint8_t  target[OG_TOGGLE_MAX_LEN];
} og_cached_record;

static og_window       g_cache_win;
static og_cached_record g_cache[OG_TOGGLE_MAX_RECORDS];
static uint32_t        g_cache_count = 0;
static int             g_cached = 0;   /* 0 until a first og_apply() caches */
static og_mode         g_mode = OG_MODE_STOCK;

/* Called once per successful og_apply(), after every record has already been
 * verified+written+read-back by the normal path above. Only caches the first
 * (initial) successful session - a later og_apply() call doesn't touch the
 * cache (matches the "initial og_apply()" contract; the cache is still valid
 * since og_apply() only ever reaches this point when every write landed). */
static void og_cache_record(const og_window *win, uint64_t vaddr, uint32_t len,
                             uint32_t flags, const uint8_t *stock,
                             const uint8_t *target) {
    if (g_cached && g_cache_count > 0) {
        /* already have a cached session from an earlier og_apply(); keep it */
        return;
    }
    if (len > OG_TOGGLE_MAX_LEN || g_cache_count >= OG_TOGGLE_MAX_RECORDS) {
        return; /* out of scope for toggling (e.g. a large payload record) */
    }
    g_cache_win = *win;
    og_cached_record *r = &g_cache[g_cache_count++];
    r->vaddr = vaddr;
    r->len = len;
    r->flags = flags;
    og_memcpy(r->stock, stock, len);
    og_memcpy(r->target, target, len);
}

/* Write `bytes` (stock or target) into one cached record's window slot, flush
 * per its flags, and read back against `bytes` - no stock-vs-current check
 * first, unlike og_apply_record(): the table is already proven correct. */
static int og_toggle_write_one(const og_cached_record *r, const uint8_t *bytes) {
    uint8_t *dst = og_resolve(&g_cache_win, r->vaddr, r->len);
    if (!dst) return OG_ERR_RANGE;

    og_memcpy(dst, bytes, r->len);
    if (r->flags & OG_FLAG_CODE) {
        og_clear_icache(dst, r->len);
    } else {
        og_flush_data(dst, r->len);
    }
    if (og_memcmp(dst, bytes, r->len) != 0) return OG_ERR_READBACK;
    return OG_OK;
}

static int og_toggle_to(og_mode target_mode) {
    if (!g_cached || g_cache_count == 0) return OG_ERR_NOT_CACHED;
    for (uint32_t i = 0; i < g_cache_count; i++) {
        const og_cached_record *r = &g_cache[i];
        const uint8_t *bytes = (target_mode == OG_MODE_OPENGATE) ? r->target : r->stock;
        int rc = og_toggle_write_one(r, bytes);
        if (rc != OG_OK) return og_result(rc, i);
    }
    g_mode = target_mode;
    return OG_OK;
}

og_mode og_current_mode(void) {
    return g_mode;
}

int og_toggle(void) {
    og_mode target = (g_mode == OG_MODE_OPENGATE) ? OG_MODE_STOCK : OG_MODE_OPENGATE;
    return og_toggle_to(target);
}

int og_rollback(void) {
    return og_toggle_to(OG_MODE_STOCK);
}

int og_apply(const uint8_t *blob, size_t blob_len, const og_window *win) {
    if (!blob || blob_len < 8 || !win || !win->base) return OG_ERR_MAGIC;
    if (blob[0] != OG_MAGIC0 || blob[1] != OG_MAGIC1 ||
        blob[2] != OG_MAGIC2 || blob[3] != OG_MAGIC3) return OG_ERR_MAGIC;

    uint32_t count = og_rd_u32(blob + 4);
    size_t off = 8;
    for (uint32_t i = 0; i < count; i++) {
        if (off + 16 > blob_len) return og_result(OG_ERR_TRUNCATED, i);
        uint64_t vaddr = og_rd_u64(blob + off);
        uint32_t len   = og_rd_u32(blob + off + 8);
        uint32_t flags = og_rd_u32(blob + off + 12);
        size_t body = off + 16;
        if ((uint64_t)len * 2 > blob_len - body) return og_result(OG_ERR_TRUNCATED, i);
        const uint8_t *stock  = blob + body;
        const uint8_t *target = blob + body + len;

        int r = og_apply_record(win, vaddr, len, flags, stock, target);
        if (r != OG_OK) return og_result(r, i);

        og_cache_record(win, vaddr, len, flags, stock, target);
        off = body + (size_t)len * 2;
    }
    g_cached = 1;
    g_mode = OG_MODE_OPENGATE; /* og_apply()'s own records are the "target" state */
    return (int)count;
}
