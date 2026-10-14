//! The process-local native FFI boundary. Never linked into PhotoCraft.
use crate::{
    pixels::{self, Rect},
    record::{O, Record},
    wire::Request,
};
use std::{
    cell::Cell,
    collections::HashMap,
    ffi::{CString, c_void},
    ptr,
};
use windows_sys::Win32::{
    Foundation::{FreeLibrary, GetLastError},
    System::LibraryLoader::{GetProcAddress, LOAD_WITH_ALTERED_SEARCH_PATH, LoadLibraryExW},
    UI::WindowsAndMessaging::{CreateWindowExW, DestroyWindow, WS_OVERLAPPEDWINDOW},
};

thread_local! { static ACTIVE:Cell<*mut Host>=const{Cell::new(ptr::null_mut())}; }
fn with_host<R>(fallback: R, f: impl FnOnce(&mut Host) -> R) -> R {
    ACTIVE.with(|slot| {
        let p = slot.get();
        if p.is_null() {
            fallback
        } else {
            // SAFETY: run installs one boxed Host for this thread until all DLL callbacks return.
            // No reference to that Host is held across calls into the plug-in.
            unsafe { f(&mut *p) }
        }
    })
}
struct Handle {
    bytes: Vec<u8>,
    pointer: Box<*mut u8>,
    logical_size: i32,
}
struct Host {
    record: Record,
    width: u32,
    height: u32,
    input: Vec<u8>,
    output: Vec<u8>,
    input_tile: Vec<u8>,
    output_tile: Vec<u8>,
    pending: Option<(Rect, i16, i16)>,
    handles: HashMap<usize, Handle>,
    buffers: HashMap<usize, Vec<u8>>,
    error: Option<String>,
}
impl Host {
    fn advance(&mut self) -> Result<(), String> {
        self.flush()?;
        let ir = self.record.rect(O.input);
        let or = self.record.rect(O.output);
        self.record.set_ptr(O.input_data, 0);
        self.record.set_ptr(O.output_data, 0);
        if !ir.empty() {
            let lo = self.record.i16(O.input_low);
            let hi = self.record.i16(O.input_low + 2);
            self.input_tile = pixels::pack(&self.input, self.width, self.height, ir, lo, hi)?;
            self.record.set32(O.input_stride, (ir.right - ir.left) * i32::from(hi - lo + 1));
            self.record.set_ptr(O.input_data, self.input_tile.as_mut_ptr() as usize);
        }
        if !or.empty() {
            let lo = self.record.i16(O.output_low);
            let hi = self.record.i16(O.output_low + 2);
            self.output_tile = pixels::pack(&self.output, self.width, self.height, or, lo, hi)?;
            self.record.set32(O.output_stride, (or.right - or.left) * i32::from(hi - lo + 1));
            self.record.set_ptr(O.output_data, self.output_tile.as_mut_ptr() as usize);
            self.pending = Some((or, lo, hi));
        }
        Ok(())
    }
    fn flush(&mut self) -> Result<(), String> {
        if let Some((r, lo, hi)) = self.pending.take() {
            pixels::unpack(&mut self.output, self.width, self.height, r, lo, hi, &self.output_tile)?;
        }
        Ok(())
    }
}
extern "C" fn abort() -> u8 {
    0
}
extern "C" fn progress(_done: i32, _total: i32) {}
extern "C" fn advance() -> i16 {
    with_host(-1, |h| match h.advance() {
        Ok(()) => 0,
        Err(e) => {
            h.error = Some(e);
            -1
        }
    })
}
extern "C" fn new_handle(size: i32) -> *mut *mut u8 {
    if size < 0 || size as usize > crate::wire::MAX_PIXELS {
        return ptr::null_mut();
    }
    with_host(ptr::null_mut(), |h| {
        let mut bytes = Vec::new();
        if bytes.try_reserve_exact((size as usize).max(1)).is_err() {
            return ptr::null_mut();
        }
        bytes.resize((size as usize).max(1), 0);
        let mut pointer = Box::new(bytes.as_mut_ptr());
        let key = (&mut *pointer) as *mut *mut u8;
        h.handles.insert(key as usize, Handle { bytes, pointer, logical_size: size });
        key
    })
}
extern "C" fn dispose_handle(handle: *mut *mut u8) {
    with_host((), |h| {
        h.handles.remove(&(handle as usize));
    });
}
extern "C" fn handle_size(handle: *mut *mut u8) -> i32 {
    with_host(0, |h| h.handles.get(&(handle as usize)).map_or(0, |a| a.logical_size))
}
extern "C" fn resize_handle(handle: *mut *mut u8, size: i32) -> i16 {
    if size < 0 || size as usize > crate::wire::MAX_PIXELS {
        return -1;
    }
    with_host(-1, |h| {
        let Some(a) = h.handles.get_mut(&(handle as usize)) else {
            return -1;
        };
        let n = (size as usize).max(1);
        if n > a.bytes.len() && a.bytes.try_reserve_exact(n - a.bytes.len()).is_err() {
            return -1;
        }
        a.bytes.resize(n, 0);
        a.logical_size = size;
        *a.pointer = a.bytes.as_mut_ptr();
        0
    })
}
extern "C" fn lock_handle(handle: *mut *mut u8, _move_high: u8) -> *mut u8 {
    with_host(ptr::null_mut(), |h| h.handles.get_mut(&(handle as usize)).map_or(ptr::null_mut(), |a| a.bytes.as_mut_ptr()))
}
extern "C" fn unlock_handle(_handle: *mut *mut u8) {}
extern "C" fn allocate_buffer(size: i32, out: *mut usize) -> i16 {
    if out.is_null() || size < 0 || size as usize > crate::wire::MAX_PIXELS {
        return -1;
    }
    with_host(-1, |h| {
        let mut b = Vec::new();
        if b.try_reserve_exact((size as usize).max(1)).is_err() {
            return -1;
        }
        b.resize((size as usize).max(1), 0);
        let key = b.as_mut_ptr() as usize;
        h.buffers.insert(key, b);
        // SAFETY: the DLL supplies a writable output slot under the callback contract.
        unsafe { out.write_unaligned(key) };
        0
    })
}
extern "C" fn lock_buffer(key: usize, _move_high: u8) -> *mut u8 {
    with_host(ptr::null_mut(), |h| h.buffers.get_mut(&key).map_or(ptr::null_mut(), |b| b.as_mut_ptr()))
}
extern "C" fn unlock_buffer(_key: usize) {}
extern "C" fn free_buffer(key: usize) {
    with_host((), |h| {
        h.buffers.remove(&key);
    });
}
extern "C" fn buffer_space() -> i32 {
    256 * 1024 * 1024
}
#[repr(C)]
struct Suite<const N: usize> {
    version: i16,
    count: i16,
    functions: [usize; N],
}

#[cfg(target_pointer_width = "32")]
const EXTRA: (usize, usize, usize, usize, usize) = (0xc0, 0xd0, 0xe0, 0x17c, 0xcc);
#[cfg(target_pointer_width = "64")]
const EXTRA: (usize, usize, usize, usize, usize) = (0xe0, 0x100, 0x118, 0x1e0, 0xf8);

pub fn run(request: &Request, pixels: Vec<u8>) -> Result<Vec<u8>, String> {
    let expected = u64::from(request.width) * u64::from(request.height) * 3;
    if request.width == 0
        || request.height == 0
        || request.width > 32767
        || request.height > 32767
        || request.channels != 3
        || request.depth != 8
        || expected != pixels.len() as u64
        || expected > crate::wire::MAX_PIXELS as u64
    {
        return Err("8BF worker supports bounded RGB8 images up to 32767 pixels per dimension".into());
    }
    let path: Vec<u16> = request.path.encode_utf16().chain(Some(0)).collect();
    if request.path.contains('\0') {
        return Err("invalid plug-in path".into());
    }
    let symbol = CString::new(request.entry.as_str()).map_err(|_| "invalid entry point")?;
    // SAFETY: Windows owns the module; path is NUL-terminated and remains alive for the call.
    let module = unsafe { LoadLibraryExW(path.as_ptr(), ptr::null_mut(), LOAD_WITH_ALTERED_SEARCH_PATH) };
    if module.is_null() {
        return Err(format!("Cannot load 8BF (Windows error {}). Check architecture and companion DLLs.", unsafe { GetLastError() }));
    }
    // SAFETY: handle is loaded and symbol is NUL-terminated.
    let proc = unsafe { GetProcAddress(module, symbol.as_ptr().cast()) };
    let Some(proc) = proc else {
        unsafe { FreeLibrary(module) };
        return Err(format!("8BF entry point {} is missing", request.entry));
    };
    let class: Vec<u16> = "STATIC".encode_utf16().chain(Some(0)).collect();
    let title: Vec<u16> = "PhotoCraft 8BF Filter".encode_utf16().chain(Some(0)).collect();
    // SAFETY: stock STATIC class needs no custom window procedure; window lives until filter returns.
    let hwnd = unsafe {
        CreateWindowExW(0, class.as_ptr(), title.as_ptr(), WS_OVERLAPPEDWINDOW, 0, 0, 640, 480, ptr::null_mut(), ptr::null_mut(), ptr::null_mut(), ptr::null())
    };
    let mut platform = [hwnd as usize, 0, 0, 0];
    let buffers = Suite {
        version: 2,
        count: 5,
        functions: [
            allocate_buffer as *const () as usize,
            lock_buffer as *const () as usize,
            unlock_buffer as *const () as usize,
            free_buffer as *const () as usize,
            buffer_space as *const () as usize,
        ],
    };
    let handles = Suite {
        version: 1,
        count: 6,
        functions: [
            new_handle as *const () as usize,
            dispose_handle as *const () as usize,
            handle_size as *const () as usize,
            resize_handle as *const () as usize,
            lock_handle as *const () as usize,
            unlock_handle as *const () as usize,
        ],
    };
    let mut h = Box::new(Host {
        record: Record::new(),
        width: request.width,
        height: request.height,
        output: pixels.clone(),
        input: pixels,
        input_tile: Vec::new(),
        output_tile: Vec::new(),
        pending: None,
        handles: HashMap::new(),
        buffers: HashMap::new(),
        error: None,
    });
    h.record.set_ptr(4, abort as *const () as usize);
    h.record.set_ptr(4 + size_of::<usize>(), progress as *const () as usize);
    h.record.set16(O.size, request.height as i16);
    h.record.set16(O.size + 2, request.width as i16);
    h.record.set16(O.planes, 3);
    h.record.set_rect(O.filter, Rect { top: 0, left: 0, bottom: request.height as i32, right: request.width as i32 });
    h.record.set32(O.input - 8, 256 * 1024 * 1024);
    h.record.set32(O.signature, i32::from_be_bytes(*b"PhCr"));
    h.record.set16(O.mode, 3);
    h.record.set_ptr(O.platform, platform.as_mut_ptr() as usize);
    h.record.set_ptr(EXTRA.0, &buffers as *const _ as usize);
    h.record.set_ptr(EXTRA.1, &handles as *const _ as usize);
    h.record.set_ptr(EXTRA.2, advance as *const () as usize);
    h.record.set32(EXTRA.3, 8);
    h.record.set_ptr(EXTRA.4, crate::preview::display as *const () as usize);
    h.record.set_ptr(O.parameters, 0);
    ACTIVE.with(|slot| slot.set(&mut *h));
    type Entry = unsafe extern "C" fn(i16, *mut c_void, *mut isize, *mut i16);
    // SAFETY: metadata declares the filter entrypoint; its cdecl ABI was independently verified.
    let entry: Entry = unsafe { std::mem::transmute(proc) };
    let record = h.record.ptr();
    let mut data = 0isize;
    let mut invoke = |selector: i16| -> Result<(), String> {
        let mut result = 0i16;
        eprintln!("8BF selector {selector}");
        // SAFETY: record, callback tables, platform and data slots outlive this DLL call.
        unsafe { entry(selector, record, &mut data, &mut result) };
        if let Some(e) = with_host(None, |h| h.error.take()) {
            return Err(e);
        }
        if result == 0 {
            Ok(())
        } else if result == -128 {
            Err("cancelled".into())
        } else {
            Err(format!("8BF selector {selector} returned {result}"))
        }
    };
    let result: Result<(), String> = (|| {
        if request.show_ui {
            invoke(1)?;
        }
        invoke(2)?;
        invoke(3)?;
        let processing: Result<(), String> = (|| {
            for _ in 0..1_000_000 {
                if h.record.rect(O.input).empty() && h.record.rect(O.output).empty() && h.record.rect(O.mask).empty() {
                    h.flush()?;
                    return Ok(());
                }
                h.advance()?;
                invoke(4)?;
                if let Some(e) = h.error.take() {
                    return Err(e);
                }
            }
            Err("8BF exceeded its iteration budget".into())
        })();
        let finish = invoke(5);
        processing?;
        finish?;
        h.flush()?;
        Ok(())
    })();
    // SAFETY: no callbacks execute after the selector sequence, all DLL-owned code has returned.
    unsafe {
        if !hwnd.is_null() {
            DestroyWindow(hwnd);
        }
        FreeLibrary(module);
    }
    ACTIVE.with(|slot| slot.set(ptr::null_mut()));
    result?;
    Ok(std::mem::take(&mut h.output))
}
