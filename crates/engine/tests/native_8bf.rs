#![cfg(all(not(target_arch = "wasm32"), unix))]
use photocraft_engine::{Session, jobs::Started};
use photocraft_geom::Rect;
use photocraft_plugins::native_8bf::{self, client::Launch};
use serde_json::json;
use std::{path::PathBuf, time::Duration};
fn pe(path: &std::path::Path) {
    let mut b = vec![0u8; 1024];
    b[..2].copy_from_slice(b"MZ");
    b[60..64].copy_from_slice(&128u32.to_le_bytes());
    b[128..132].copy_from_slice(b"PE\0\0");
    b[132..134].copy_from_slice(&0x14cu16.to_le_bytes());
    b[134..136].copy_from_slice(&1u16.to_le_bytes());
    b[148..150].copy_from_slice(&224u16.to_le_bytes());
    b[150..152].copy_from_slice(&0x2000u16.to_le_bytes());
    b[152..154].copy_from_slice(&0x10bu16.to_le_bytes());
    b[248..252].copy_from_slice(&4096u32.to_le_bytes());
    b[252..256].copy_from_slice(&40u32.to_le_bytes());
    b[384..388].copy_from_slice(&512u32.to_le_bytes());
    b[388..392].copy_from_slice(&4096u32.to_le_bytes());
    b[392..396].copy_from_slice(&512u32.to_le_bytes());
    b[396..400].copy_from_slice(&512u32.to_le_bytes());
    b[536..540].copy_from_slice(&1u32.to_le_bytes());
    b[544..548].copy_from_slice(&4160u32.to_le_bytes());
    b[576..580].copy_from_slice(&4176u32.to_le_bytes());
    b[592..603].copy_from_slice(b"PluginMain\0");
    std::fs::write(path, b).unwrap();
}
fn fixture(name: &str, script: &str) -> (String, PathBuf) {
    let path = std::env::temp_dir().join(format!("pc-engine-8bf-{}-{name}.8bf", std::process::id()));
    pe(&path);
    let launch = Launch { program: "python3".into(), args: vec!["-c".into(), script.into()], environment: Default::default(), timeout: Duration::from_secs(3) };
    let p = native_8bf::install_with_launch(&path, launch).unwrap();
    (p.descriptor.id.clone(), path)
}
const INVERT: &str = r#"import sys,struct,json,time
r=sys.stdin.buffer;w=sys.stdout.buffer
r.read(8);n,p=struct.unpack('<IQ',r.read(12));m=json.loads(r.read(n));d=r.read(p)
time.sleep(.1)
h=json.dumps({'status':'ok','message':'','width':m['width'],'height':m['height'],'channels':3,'depth':8}).encode();w.write(b'PC8BF001'+struct.pack('<IQ',len(h),p)+h+bytes(255-v for v in d))
"#;
fn doc() -> Session {
    let mut s = Session::new();
    s.execute("file.new", json!({"width":3,"height":1})).unwrap();
    s.edit("fixture", |d, a| {
        d.layer_mut(a.unwrap())
            .unwrap()
            .surface_mut()
            .unwrap()
            .write_region(Rect::new(0, 0, 3, 1), &[0.2, 0.4, 0.6, 0.5, 0.2, 0.4, 0.6, 0.5, 0.2, 0.4, 0.6, 0.5]);
        let mut mask = photocraft_raster::Surface::new(photocraft_color::PixelFormat::GRAY8);
        mask.write_region(Rect::new(0, 0, 3, 1), &[0.0, 0.5, 1.0]);
        d.selection = Some(mask);
        Ok(())
    })
    .unwrap();
    s
}
fn pixels(s: &Session) -> Vec<f32> {
    let d = s.active().unwrap();
    d.doc.layer(d.active_layer.unwrap()).unwrap().surface().unwrap().read_region(Rect::new(0, 0, 3, 1))
}
#[test]
fn applies_background_result_as_one_undo_with_alpha_and_selection() {
    let (id, path) = fixture("invert", INVERT);
    let mut s = doc();
    let before = pixels(&s);
    let depth = s.active().unwrap().history.past_len();
    let started = s.start("plugin.8bf.run", json!({"id":id,"show_ui":false})).unwrap();
    let Started::Job(job) = started else { panic!("expected background job") };
    assert_eq!(pixels(&s), before);
    s.wait_job(job).unwrap();
    let after = pixels(&s);
    assert_eq!(&after[..4], &before[..4]);
    assert_eq!(after[7], before[7]);
    assert_eq!(after[11], before[11]);
    assert!((after[8] - 0.8).abs() < 0.01);
    assert_eq!(s.active().unwrap().history.past_len(), depth + 1);
    s.execute("edit.undo", json!({})).unwrap();
    assert_eq!(pixels(&s), before);
    s.execute("edit.redo", json!({})).unwrap();
    assert_eq!(pixels(&s), after);
    s.execute("plugin.8bf.remove", json!({"id":id})).unwrap();
    std::fs::remove_file(path).unwrap();
}
#[test]
fn errors_and_invalid_targets_leave_document_and_history_intact() {
    let (id, path) = fixture("crash", "import sys;sys.exit(19)");
    let mut s = doc();
    let before = pixels(&s);
    let depth = s.active().unwrap().history.past_len();
    for p in [json!({"id":id,"target":"mask"}), json!({"id":id,"show_ui":"yes"}), json!({"id":id,"show_ui":false})] {
        assert!(s.execute("plugin.8bf.run", p).is_err());
        assert_eq!(pixels(&s), before);
        assert_eq!(s.active().unwrap().history.past_len(), depth);
    }
    s.execute("plugin.8bf.remove", json!({"id":id})).unwrap();
    std::fs::remove_file(path).unwrap();
}

#[test]
fn cancelling_background_native_filter_keeps_document_and_history_unchanged() {
    let (id, path) = fixture("cancel", "import time;time.sleep(60)");
    let mut s = doc();
    let before = pixels(&s);
    let depth = s.active().unwrap().history.past_len();
    let Started::Job(job) = s.start("plugin.8bf.run", json!({"id":id,"show_ui":false})).unwrap() else { panic!("expected background job") };
    assert!(s.cancel_job(job));
    assert!(s.wait_job(job).is_err());
    assert_eq!(pixels(&s), before);
    assert_eq!(s.active().unwrap().history.past_len(), depth);
    native_8bf::remove(&id);
    std::fs::remove_file(path).unwrap();
}
