# target-helper — on-camera micro-helper (clean-room MIT, C99)

A tiny, freestanding native helper for **aarch64-linux-gnu** (Sony CE Linux 4.9,
BIONZ XR). It reads an **OGP1 patch blob** and applies each record into a mapped
memory window:

```
verify stock  ->  write 64-byte-aligned line(s)  ->  read back  ->  flush cache
```

- **Clean-room MIT.** No Sony firmware bytes. The format and the engine are original;
  the patch bytes travel in an external blob the host builds from
  [`../profiles/*.json`](../profiles/) plus the git-ignored `payloads/*.bin`.
- **No libc / no external deps.** Built freestanding (`-ffreestanding -nostdlib`).
- **ARM64 cache correctness.** Code records run `DC CVAU → DSB ISH → IC IVAU →
  DSB ISH → ISB` (with `__builtin___clear_cache` as the non-aarch64 fallback); data
  records clean the D-cache so the readback is true.

## Memory access is injected, not assumed

`og_apply()` takes an `og_window { base, base_vaddr, size }` — a linear mapping of
`[base_vaddr, base_vaddr+size)` onto a local pointer. On camera the loader passes an
`mmap` of physical RAM; in the host self-test it is a plain buffer. The helper holds
**logic only** — no `/dev/mem` path, no device assumptions.

## Build

```bash
# aarch64 .so via cross-gcc
make                      # -> build/libogpatch.so   (needs aarch64-linux-gnu-gcc)

# aarch64 .so via Zig (bundles the toolchain; no cross-gcc needed)
zig build                 # -> zig-out/lib/libogpatch.so   (Zig 0.17.1)
zig build test            # builds + runs test/test_helper.c on the host

# host logic self-test via Make (any native C compiler, no aarch64, no camera)
make test                 # builds + runs build/test_helper  -> "OK"
```

## OGP1 blob format

Little-endian. Header `"OGP1"` + `uint32 count`, then `count` records of
`vaddr:u64, len:u32, flags:u32, stock[len], target[len]`. `flags` bit 0
(`OG_FLAG_CODE`) marks a record that patches executable code (i-cache flush).
Full layout is documented at the top of [`include/ogpatch.h`](include/ogpatch.h).
The host crate [`../host-injector`](../host-injector) emits this blob from the JSON
profiles.

## Stateful toggle (`og_toggle`, `og_current_mode`, `og_rollback`)

A successful `og_apply()` caches its records (up to `OG_TOGGLE_MAX_RECORDS`, each up
to `OG_TOGGLE_MAX_LEN` bytes — sized for small geometry words like L13/L16/S16, not
the much larger encoder payload) in static state. `og_toggle()` then flips every
cached record between its stock and target bytes — write + i-cache/d-cache flush +
readback, same as `og_apply()`, but **without** re-checking the current bytes against
the mode being left first (the table was already proven correct by that initial
apply). `og_current_mode()` reports which side it's on (`OG_MODE_STOCK` /
`OG_MODE_OPENGATE`); `og_rollback()` forces it back to stock regardless of the
current mode. Still per-record readback-verified: a failed toggle returns
`OG_ERR_READBACK` + the failing index, same encoding as `og_apply()`.

## Safety

The helper refuses any record whose current bytes do not match the expected stock
(`OG_ERR_STOCK`, nothing written) and reports the failing record index. It never
rolls back **a failed `og_apply()`** on its own — the host keeps the stock bytes and
drives that rollback. `og_rollback()` is a different thing: an explicit, always-
available revert of whatever session `og_apply()` already cached. RAM only: a cold
boot (battery out ~10 s) reverts everything regardless.
