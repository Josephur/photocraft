//! Original conformance DLL, built by validate-workers.py for both architectures.
#![allow(dead_code)]
#[path = "../src/pixels.rs"]
mod pixels;
#[path = "../src/record.rs"]
mod record;
use pixels::Rect;
use record::{O, Record};
use std::ffi::c_void;

#[unsafe(no_mangle)]
pub unsafe extern "C" fn PluginMain(selector: i16, block: *mut c_void, _data: *mut isize, result: *mut i16) {
    // SAFETY: the conformance host passes live records and result slots of our shared layout.
    let r = unsafe { &mut *block.cast::<Record>() };
    unsafe {
        *result = 0;
    }
    let mode = std::env::var("PHOTOCRAFT_8BF_FIXTURE_MODE").unwrap_or_default();
    if selector == 3 {
        if mode == "crash" {
            std::process::exit(7);
        }
        if mode == "noise" {
            println!("A plug-in wrote diagnostic output");
        }
        if mode == "cancel" {
            unsafe {
                *result = -128;
            }
            return;
        }
        let mut rect = r.rect(O.filter);
        if mode == "bad_rect" || mode == "ignored_callback" {
            rect.left = -1;
        }
        r.set_rect(O.input, rect);
        r.set_rect(O.output, rect);
        r.set16(O.input_low, 0);
        r.set16(O.input_low + 2, 2);
        r.set16(O.output_low, 0);
        r.set16(O.output_low + 2, 2);
        if mode == "ignored_callback" {
            let at = if cfg!(target_pointer_width = "64") { 0x118 } else { 0xe0 };
            let f = usize::from_le_bytes(r.get(at));
            // SAFETY: the worker supplies this callback with the independently established ABI.
            let f: extern "C" fn() -> i16 = unsafe { std::mem::transmute(f) };
            let _ = f();
            r.set_rect(O.input, Rect::default());
            r.set_rect(O.output, Rect::default());
        }
    } else if selector == 4 {
        let rect = r.rect(O.output);
        let len = ((rect.right - rect.left) * (rect.bottom - rect.top) * 3) as usize;
        let source = usize::from_le_bytes(r.get(O.input_data)) as *const u8;
        let dest = usize::from_le_bytes(r.get(O.output_data)) as *mut u8;
        // SAFETY: worker callback has supplied len bytes of input and output for this rectangle.
        unsafe {
            let input = std::slice::from_raw_parts(source, len);
            let output = std::slice::from_raw_parts_mut(dest, len);
            for (a, b) in input.iter().zip(output.iter_mut()) {
                *b = 255 - *a;
            }
        }
        r.set_rect(O.input, Rect::default());
        r.set_rect(O.output, Rect::default());
    }
}
