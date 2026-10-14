//! Checked rectangle/plane packing at the native filter boundary.

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Rect {
    pub top: i32,
    pub left: i32,
    pub bottom: i32,
    pub right: i32,
}
impl Rect {
    pub fn empty(self) -> bool {
        self.bottom <= self.top || self.right <= self.left
    }
}

fn layout(len: usize, width: u32, height: u32, r: Rect, lo: i16, hi: i16) -> Result<(usize, usize, usize, usize), String> {
    let full = u64::from(width).checked_mul(u64::from(height)).and_then(|n| n.checked_mul(3)).ok_or("image overflow")?;
    if full > 512 * 1024 * 1024 || full != len as u64 {
        return Err("invalid image length".into());
    }
    if lo < 0 || hi < lo || hi > 2 {
        return Err("unsupported channel range".into());
    }
    if r.top < 0 || r.left < 0 || r.bottom < r.top || r.right < r.left || r.bottom as u32 > height || r.right as u32 > width {
        return Err("filter requested pixels outside image bounds".into());
    }
    Ok((width as usize, (r.right - r.left) as usize, (r.bottom - r.top) as usize, (hi - lo + 1) as usize))
}

pub fn pack(source: &[u8], width: u32, height: u32, r: Rect, lo: i16, hi: i16) -> Result<Vec<u8>, String> {
    let (stride, w, h, planes) = layout(source.len(), width, height, r, lo, hi)?;
    let mut out = vec![0; w * h * planes];
    for row in 0..h {
        let start = ((r.top as usize + row) * stride + r.left as usize) * 3;
        let input = source.get(start..start + w * 3).ok_or("input row outside image")?;
        let output = out.get_mut(row * w * planes..(row + 1) * w * planes).ok_or("output row outside allocation")?;
        if planes == 3 {
            output.copy_from_slice(input);
        } else {
            for (src, dst) in input.chunks_exact(3).zip(output.chunks_exact_mut(planes)) {
                dst.copy_from_slice(src.get(lo as usize..=hi as usize).ok_or("channel out of range")?);
            }
        }
    }
    Ok(out)
}

pub fn unpack(output: &mut [u8], width: u32, height: u32, r: Rect, lo: i16, hi: i16, packed: &[u8]) -> Result<(), String> {
    let (stride, w, h, planes) = layout(output.len(), width, height, r, lo, hi)?;
    if packed.len() != w * h * planes {
        return Err("filter output length mismatch".into());
    }
    for row in 0..h {
        let start = ((r.top as usize + row) * stride + r.left as usize) * 3;
        let dst = output.get_mut(start..start + w * 3).ok_or("output row outside image")?;
        let src = packed.get(row * w * planes..(row + 1) * w * planes).ok_or("input row outside allocation")?;
        if planes == 3 {
            dst.copy_from_slice(src);
        } else {
            for (src, dst) in src.chunks_exact(planes).zip(dst.chunks_exact_mut(3)) {
                dst.get_mut(lo as usize..=hi as usize).ok_or("channel out of range")?.copy_from_slice(src);
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn packs_subset_planes_and_commits_only_requested_rectangle() {
        let source: Vec<u8> = (0..36).collect();
        let rect = Rect { top: 1, left: 1, bottom: 2, right: 3 };
        let packed = pack(&source, 4, 3, rect, 1, 2).unwrap();
        assert_eq!(packed, vec![16, 17, 19, 20]);
        let mut output = source.clone();
        unpack(&mut output, 4, 3, rect, 1, 2, &[100, 101, 102, 103]).unwrap();
        assert_eq!(&output[15..21], &[15, 100, 101, 18, 102, 103]);
        assert_eq!(&output[..15], &source[..15]);
        assert_eq!(&output[21..], &source[21..]);
    }
    #[test]
    fn rejects_invalid_rectangles_planes_and_buffers() {
        for rect in [
            Rect { top: -1, left: 0, bottom: 2, right: 2 },
            Rect { top: 0, left: 0, bottom: 3, right: 2 },
            Rect { top: 0, left: 0, bottom: 2, right: i32::MAX },
        ] {
            assert!(pack(&[0; 12], 2, 2, rect, 0, 2).is_err());
        }
        let rect = Rect { top: 0, left: 0, bottom: 2, right: 2 };
        assert!(pack(&[0; 11], 2, 2, rect, 0, 2).is_err());
        assert!(pack(&[0; 12], 2, 2, rect, -1, 2).is_err());
        assert!(pack(&[0; 12], 2, 2, rect, 0, 3).is_err());
        assert!(unpack(&mut [0; 12], 2, 2, rect, 0, 2, &[0; 11]).is_err());
    }
}
