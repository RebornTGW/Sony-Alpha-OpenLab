/* ogpatch.h - Open Gate patch descriptor format + helper API.
 *
 * Clean-room MIT. No Sony firmware bytes live here: this header defines a
 * generic binary patch-descriptor format and a tiny apply engine. The actual
 * patch bytes travel in an external blob (built by the host from profiles/*.json
 * plus the git-ignored payloads/*.bin), never in this repo.
 *
 * Target: aarch64-linux-gnu (Sony CE Linux 4.9 on BIONZ XR). Freestanding:
 * no libc dependency.
 *
 * Blob format "OGP1" (little-endian):
 *
 *   offset  size  field
 *   0       4     magic  = 'O','G','P','1'
 *   4       4     count  (uint32)  number of records
 *   8       ...   records[count]
 *
 * each record:
 *   0       8     vaddr  (uint64)  virtual address in the mapped window
 *   8       4     len    (uint32)  bytes to verify/write
 *   12      4     flags  (uint32)  bit0 = OG_FLAG_CODE (needs icache flush)
 *   16      len   stock  expected current bytes (verify before write)
 *   16+len  len   target bytes to write
 *   (next record follows immediately)
 */
#ifndef OGPATCH_H
#define OGPATCH_H

#include <stdint.h>
#include <stddef.h>

#define OG_MAGIC0 'O'
#define OG_MAGIC1 'G'
#define OG_MAGIC2 'P'
#define OG_MAGIC3 '1'

#define OG_FLAG_CODE 0x1u   /* record patches executable code -> flush i-cache */

#define OG_LINE 64u         /* BIONZ XR cache line: writes are 64-byte aligned */

/* Return / error codes (negative = failure, index encoded where useful). */
enum {
    OG_OK            =  0,
    OG_ERR_MAGIC     = -1,   /* bad magic / truncated header */
    OG_ERR_TRUNCATED = -2,   /* a record runs past the blob end */
    OG_ERR_RANGE     = -3,   /* vaddr/len outside the mapped window */
    OG_ERR_STOCK     = -4,   /* current bytes != expected stock (abort, no write) */
    OG_ERR_READBACK  = -5    /* post-write readback != target */
};

/* A linear mapping of [base_vaddr, base_vaddr + size) onto `base`.
 * On camera this is an mmap of physical RAM; on a host test it is a buffer. */
typedef struct {
    uint8_t *base;        /* local pointer to the start of the window */
    uint64_t base_vaddr;  /* virtual address that `base` corresponds to */
    size_t   size;        /* window length in bytes */
} og_window;

/* Apply every record in `blob`.
 *  - verifies each record's stock bytes first; on any mismatch returns
 *    -(OG_ERR_STOCK) - index*... see og_result below, and writes nothing more.
 *  - writes target bytes in 64-byte-aligned lines, reads them back.
 *  - flushes the instruction cache for OG_FLAG_CODE records.
 * Does NOT roll back already-applied records: the host keeps the stock bytes
 * and drives rollback (RAII) on failure.
 *
 * Returns the number of records applied on full success, or a negative
 * og_result on the first failing record. */
int og_apply(const uint8_t *blob, size_t blob_len, const og_window *win);

/* Encode (error_code, record_index) into one negative int and back. */
static inline int og_result(int err, uint32_t index) {
    return -(((int)index << 3) | (-err & 0x7));
}
static inline int og_result_err(int r) { return -((-r) & 0x7); }
static inline uint32_t og_result_index(int r) { return (uint32_t)((-r) >> 3); }

/* ARM64 instruction-cache maintenance to the Point of Unification, for a
 * freshly written code region [start, start+len). Portable fallback uses the
 * compiler builtin. Exposed for callers that stage code writes themselves. */
void og_clear_icache(void *start, size_t len);

#endif /* OGPATCH_H */
