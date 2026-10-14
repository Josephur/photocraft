//! Converts an RGB8 surface to the worker's RGB8 wire format, retaining alpha and selection.
use super::{client::Launch, wire::Request};
use photocraft_geom::Rect;
use photocraft_raster::Surface;
use std::io;
pub fn apply(
    launch: &Launch,
    request: Request,
    surface: &Surface,
    area: Rect,
    selection: Option<&Surface>,
    cancelled: impl Fn() -> bool,
) -> io::Result<Surface> {
    use photocraft_color::{ColorMode, SampleType};
    let fmt = surface.format();
    if fmt.mode != ColorMode::Rgb || fmt.sample != SampleType::U8 {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "8BF bridge currently supports RGB8 and RGBA8 pixel layers only"));
    }
    let count = u64::from(request.width).checked_mul(u64::from(request.height)).ok_or_else(|| io::Error::other("8BF dimensions overflow"))?;
    if area.is_empty()
        || area.width() != request.width
        || area.height() != request.height
        || count.checked_mul(3).is_none_or(|n| n > super::wire::MAX_PIXELS as u64)
    {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "8BF image dimensions exceed supported limit"));
    }
    let mut original = surface.read_region(area);
    let channels = surface.channels();
    let bytes: Vec<u8> = original.chunks_exact(channels).flat_map(|p| p.iter().take(3).map(|v| (v.clamp(0.0, 1.0) * 255.0 + 0.5) as u8)).collect();
    let result = super::client::exchange(launch, request, bytes, &cancelled)?;
    if cancelled() {
        return Err(io::Error::new(io::ErrorKind::Interrupted, "8BF filter cancelled"));
    }
    let coverage = selection.map(|s| (s.read_region(area), s.channels()));
    for (i, pixel) in original.chunks_exact_mut(channels).enumerate() {
        let k = coverage.as_ref().map_or(1.0, |(values, n)| values.get(i * n).copied().filter(|v| v.is_finite()).unwrap_or(0.0).clamp(0.0, 1.0));
        if k == 0.0 {
            continue;
        }
        for (channel, value) in pixel.iter_mut().take(3).enumerate() {
            let output = result.get(i * 3 + channel).ok_or_else(|| io::Error::other("8BF RGB buffer is truncated"))?;
            *value += (f32::from(*output) / 255.0 - *value) * k;
        }
    }
    let mut output = surface.clone();
    output.write_region(area, &original);
    Ok(output)
}
#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use photocraft_color::PixelFormat;
    #[test]
    fn native_result_preserves_alpha_and_exact_outside_selection() {
        let area = Rect::new(0, 0, 3, 1);
        let mut source = Surface::new(PixelFormat::RGBA8);
        source.write_region(area, &[0.2, 0.4, 0.6, 0.5, 0.2, 0.4, 0.6, 0.5, 0.2, 0.4, 0.6, 0.5]);
        let mut selection = Surface::new(PixelFormat::GRAY8);
        selection.write_region(area, &[0.0, 0.5, 1.0]);
        let script = r#"import sys,struct,json
r=sys.stdin.buffer; w=sys.stdout.buffer
r.read(8); n,p=struct.unpack('<IQ',r.read(12)); m=json.loads(r.read(n)); d=r.read(p)
h=json.dumps({'status':'ok','message':'','width':m['width'],'height':m['height'],'channels':3,'depth':8}).encode(); w.write(b'PC8BF001'+struct.pack('<IQ',len(h),p)+h+bytes(255-v for v in d))
"#;
        let launch = Launch {
            program: "python3".into(),
            args: vec!["-c".into(), script.into()],
            environment: Default::default(),
            timeout: std::time::Duration::from_secs(3),
        };
        let request = Request { path: "test.8bf".into(), entry: "PluginMain".into(), width: 3, height: 1, channels: 3, depth: 8, show_ui: false };
        let out = apply(&launch, request, &source, area, Some(&selection), || false).unwrap();
        assert_eq!(out.pixel(0, 0), source.pixel(0, 0));
        assert_eq!(out.pixel(1, 0)[3], source.pixel(1, 0)[3]);
        assert_eq!(out.pixel(2, 0)[3], source.pixel(2, 0)[3]);
        assert!((out.pixel(1, 0)[0] - 0.5).abs() < 0.01);
        assert!((out.pixel(2, 0)[0] - 0.8).abs() < 0.01);
        assert!(
            apply(
                &launch,
                Request { path: "test".into(), entry: "PluginMain".into(), width: 3, height: 1, channels: 3, depth: 8, show_ui: false },
                &Surface::new(PixelFormat::RGBA16),
                area,
                None,
                || false
            )
            .is_err()
        );
    }
}
