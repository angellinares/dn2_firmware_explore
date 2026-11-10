//! `dnfw.codec.aplibpack` in Rust. It must give the same bytes as the Python packer:
//! test/test_aplibpack_rust.py checks every compressed stock section and a set of edge inputs.
//! The method and the reasons for each constant are in src/dnfw/codec/aplibpack.py.
//!
//!     aplibpack [--depth N] [--max-offset N] < data > stream
//!
//! Python calls it when it is built (`cargo build --release` in this folder), and packs in
//! Python when it is not.

use std::io::{Read, Write};

// dnfw.codec.aplib and dnfw.codec.limits
const OFFSET_BIAS: i64 = 767;
const REUSE_GAMMA: u64 = 2;
const FAR_THRESHOLD: i64 = 3328;
const MIN_MATCH: usize = 2;
const MAX_MATCH: usize = 2048;
const PACK_MAX_OFFSET: i64 = (1 << 20) - 4096;
const LITERAL_BITS: i64 = 9;
const DEFAULT_CHAIN_DEPTH: usize = 32;

struct Writer {
    out: Vec<u8>,
    tag_pos: usize,
    tag_bits: u32,
}

impl Writer {
    fn bit(&mut self, value: bool) {
        if self.tag_bits == 0 {
            self.tag_pos = self.out.len();
            self.out.push(0);
            self.tag_bits = 8;
        }
        if value {
            self.out[self.tag_pos] |= 1 << (self.tag_bits - 1);
        }
        self.tag_bits -= 1;
    }

    fn gamma(&mut self, value: u64) {
        let width = 64 - value.leading_zeros() as i64;
        let mut i = width - 2;
        while i >= 0 {
            self.bit((value >> i) & 1 == 1);
            self.bit(i == 0);
            i -= 1;
        }
    }

    fn literal(&mut self, value: u8) {
        self.bit(true);
        self.out.push(value);
    }

    fn match_(&mut self, offset: i64, length: usize, last_offset: i64) -> i64 {
        self.bit(false);
        let mut last = last_offset;
        if offset == last_offset {
            self.gamma(REUSE_GAMMA);
        } else {
            let raw = (offset + OFFSET_BIAS) as u64;
            self.gamma(raw >> 8);
            self.out.push((raw & 0xFF) as u8);
            last = offset;
        }
        let base = (length - 1 - usize::from(offset > FAR_THRESHOLD)) as u64;
        if base <= 3 {
            self.bit(base >> 1 == 1);
            self.bit(base & 1 == 1);
        } else {
            self.bit(false);
            self.bit(false);
            self.gamma(base - 2);
        }
        last
    }

    fn end(&mut self) {
        self.bit(false);
        self.gamma(0x1000002);
        self.out.push(0xFF);
    }
}

fn gamma_cost(value: i64) -> i64 {
    2 * (63 - (value as u64).leading_zeros() as i64)
}

fn match_cost(offset: i64, length: usize, last_offset: i64) -> i64 {
    let mut bits = 1 + if offset == last_offset { 2 } else { gamma_cost((offset + OFFSET_BIAS) >> 8) + 8 };
    let base = length as i64 - 1 - i64::from(offset > FAR_THRESHOLD);
    bits += if base <= 3 { 2 } else { 2 + gamma_cost(base - 2) };
    bits
}

fn min_match(offset: i64) -> usize {
    if offset > FAR_THRESHOLD { MIN_MATCH + 1 } else { MIN_MATCH }
}

fn run(data: &[u8], a: usize, b: usize, cap: usize) -> usize {
    let mut n = 0;
    while n < cap && data[a + n] == data[b + n] {
        n += 1;
    }
    n
}

struct Chains {
    head: Vec<i64>, // by the 2-byte key, -1 for none
    prev: Vec<i64>,
}

fn key(data: &[u8], k: usize) -> usize {
    (data[k] as usize) << 8 | data[k + 1] as usize
}

/// The best match so far: longest wins, then the lower cost.
struct Best {
    offset: i64,
    length: usize,
    cost: i64,
}

impl Best {
    fn consider(&mut self, offset: i64, length: usize, last_offset: i64) {
        if length < min_match(offset) {
            return;
        }
        let cost = match_cost(offset, length, last_offset);
        if length > self.length || (length == self.length && cost < self.cost) {
            *self = Best { offset, length, cost };
        }
    }
}

/// The best match at `i`, or length 0 for none.
fn best(data: &[u8], i: usize, cap: usize, ch: &Chains, last_offset: i64, depth: usize, max_offset: i64) -> Best {
    let mut b = Best { offset: 0, length: 0, cost: 0 };
    if 0 < last_offset && last_offset <= (i as i64).min(max_offset) {
        b.consider(last_offset, run(data, i - last_offset as usize, i, cap), last_offset);
    }
    if i + 2 <= data.len() {
        let mut candidate = ch.head[key(data, i)];
        let mut left = depth;
        while candidate >= 0 && left > 0 {
            if i as i64 - candidate > max_offset {
                break; // nearest first: every later candidate is further back
            }
            b.consider(i as i64 - candidate, run(data, candidate as usize, i, cap), last_offset);
            if b.length >= cap {
                break;
            }
            candidate = ch.prev[candidate as usize];
            left -= 1;
        }
    }
    b
}

fn pack(data: &[u8], depth: usize, max_offset: i64) -> Vec<u8> {
    let mut w = Writer { out: Vec::with_capacity(data.len() / 2), tag_pos: 0, tag_bits: 0 };
    let size = data.len();
    let mut ch = Chains { head: vec![-1; 1 << 16], prev: vec![-1; size] };
    let mut last_offset: i64 = 1;
    let mut i = 0;
    while i < size {
        let cap = (size - i).min(MAX_MATCH);
        let Best { offset, mut length, cost } = best(data, i, cap, &ch, last_offset, depth, max_offset);
        if length > 0 && i + 1 < size {
            // lazy: a literal here and the next position's match, if cheaper per byte
            let next_cap = (size - i - 1).min(MAX_MATCH);
            let alt = best(data, i + 1, next_cap, &ch, last_offset, depth, max_offset);
            if alt.length > 0 && (LITERAL_BITS + alt.cost) * (length as i64) < cost * (1 + alt.length as i64) {
                length = 0;
            }
        }
        let step = if length > 0 {
            last_offset = w.match_(offset, length, last_offset);
            length
        } else {
            w.literal(data[i]);
            1
        };
        let limit = (i + step).min((size + 1).saturating_sub(2));
        for k in i..limit {
            let h = key(data, k);
            ch.prev[k] = ch.head[h];
            ch.head[h] = k as i64;
        }
        i += step;
    }
    w.end();
    w.out
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let (mut depth, mut max_offset) = (DEFAULT_CHAIN_DEPTH, PACK_MAX_OFFSET);
    let mut it = args.iter();
    while let Some(a) = it.next() {
        let value = it.next().and_then(|v| v.parse::<i64>().ok());
        match (a.as_str(), value) {
            ("--depth", Some(v)) if v >= 0 => depth = v as usize,
            ("--max-offset", Some(v)) if v >= 0 => max_offset = v,
            _ => {
                eprintln!("usage: aplibpack [--depth N] [--max-offset N] < data > stream");
                std::process::exit(2);
            }
        }
    }
    let mut data = Vec::new();
    std::io::stdin().read_to_end(&mut data).expect("read stdin");
    std::io::stdout().write_all(&pack(&data, depth, max_offset)).expect("write stdout");
}
