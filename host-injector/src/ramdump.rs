//! Chunked RAM dump: read an arbitrary `[addr, addr+len)` window off a live session
//! in fixed-size pieces. Pure chunk-planning logic lives in `chunk_plan` so it's
//! unit-testable without a camera; `dump_ram` drives it over any `RamTransport`
//! (the real `ServiceLink`, whose `read()` builds each chunk's RMEM frame via
//! `pmca::mem_read_request`, or `MockRam` in tests).

use crate::transport::RamTransport;
use crate::Result;

/// Split `[addr, addr+len)` into `chunk`-sized pieces (the last one may be
/// shorter). `len == 0` yields no pieces; `chunk == 0` is treated as 1 to avoid an
/// infinite loop on a bad caller value rather than panicking.
pub fn chunk_plan(addr: u64, len: usize, chunk: usize) -> Vec<(u64, usize)> {
    let chunk = chunk.max(1);
    let mut out = Vec::with_capacity(len.div_ceil(chunk));
    let mut done = 0usize;
    while done < len {
        let n = chunk.min(len - done);
        out.push((addr + done as u64, n));
        done += n;
    }
    out
}

/// Read `len` bytes starting at `addr`, in `chunk`-sized reads, concatenated in
/// order. Stops and returns the first error (e.g. a stale/unwired transport, or a
/// real USB failure partway through) - whatever was read so far is discarded
/// rather than returned half-complete.
pub fn dump_ram<T: RamTransport>(t: &mut T, addr: u64, len: usize, chunk: usize) -> Result<Vec<u8>> {
    let mut out = Vec::with_capacity(len);
    for (off, n) in chunk_plan(addr, len, chunk) {
        out.extend(t.read(off, n)?);
    }
    Ok(out)
}

// --------------------------------------------------------------------------- //
#[cfg(test)]
mod tests {
    use super::*;
    use crate::transport::MockRam;

    #[test]
    fn chunk_plan_even_split() {
        let plan = chunk_plan(0x1000, 0x40, 0x10);
        assert_eq!(
            plan,
            vec![(0x1000, 0x10), (0x1010, 0x10), (0x1020, 0x10), (0x1030, 0x10)]
        );
    }

    #[test]
    fn chunk_plan_last_chunk_shorter() {
        let plan = chunk_plan(0x1000, 0x25, 0x10);
        assert_eq!(plan, vec![(0x1000, 0x10), (0x1010, 0x10), (0x1020, 0x05)]);
    }

    #[test]
    fn chunk_plan_chunk_larger_than_len() {
        assert_eq!(chunk_plan(0x1000, 0x05, 0x8000), vec![(0x1000, 0x05)]);
    }

    #[test]
    fn chunk_plan_zero_len_is_empty() {
        assert_eq!(chunk_plan(0x1000, 0, 0x10), Vec::<(u64, usize)>::new());
    }

    #[test]
    fn chunk_plan_zero_chunk_does_not_hang() {
        // Pathological input: treated as chunk size 1, not an infinite loop.
        let plan = chunk_plan(0x1000, 3, 0);
        assert_eq!(plan, vec![(0x1000, 1), (0x1001, 1), (0x1002, 1)]);
    }

    #[test]
    fn dump_ram_reassembles_chunks_in_order() {
        let mut ram = MockRam::new();
        let data: Vec<u8> = (0u8..0x40).collect(); // 0x00, 0x01, ..., 0x3f
        ram.seed(0x2000, &data);
        let got = dump_ram(&mut ram, 0x2000, data.len(), 0x11).unwrap(); // uneven chunk size
        assert_eq!(got, data);
    }

    #[test]
    fn dump_ram_single_chunk_when_chunk_covers_whole_len() {
        let mut ram = MockRam::new();
        ram.seed(0x3000, &[0xAA, 0xBB, 0xCC]);
        let got = dump_ram(&mut ram, 0x3000, 3, 0x8000).unwrap();
        assert_eq!(got, vec![0xAA, 0xBB, 0xCC]);
    }

    #[test]
    fn dump_ram_propagates_transport_error() {
        use crate::transport::NullTransport;
        let mut t = NullTransport;
        assert!(dump_ram(&mut t, 0x1000, 0x10, 0x8).is_err());
    }
}
