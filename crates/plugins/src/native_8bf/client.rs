//! Process transport: no native library is ever loaded into PhotoCraft.
use super::wire::{Request, Response};
use std::{collections::BTreeMap, ffi::OsString, io, path::PathBuf, time::Duration};
#[derive(Clone, Debug)]
pub struct Launch {
    pub program: PathBuf,
    pub args: Vec<OsString>,
    pub environment: BTreeMap<OsString, OsString>,
    pub timeout: Duration,
}
impl Launch {
    pub fn from_environment(architecture: super::pe::Architecture) -> io::Result<Self> {
        let (key, file) = match architecture {
            super::pe::Architecture::X86 => ("PHOTOCRAFT_8BF_WORKER32", "photocraft-8bf-worker32.exe"),
            super::pe::Architecture::X64 => ("PHOTOCRAFT_8BF_WORKER64", "photocraft-8bf-worker64.exe"),
        };
        let worker = match std::env::var_os(key) {
            Some(path) => PathBuf::from(path),
            None => std::env::current_exe()?.parent().ok_or_else(|| io::Error::other("cannot find PhotoCraft executable folder"))?.join(file),
        };
        #[cfg(target_os = "windows")]
        let (program, args, environment) = (worker, Vec::new(), BTreeMap::new());
        #[cfg(not(target_os = "windows"))]
        let (program, args, environment) = {
            let mut environment = BTreeMap::new();
            let config = std::env::var_os("XDG_CONFIG_HOME")
                .map(PathBuf::from)
                .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".config")))
                .ok_or_else(|| io::Error::other("configure XDG_CONFIG_HOME for an isolated 8BF Wine prefix"))?;
            let prefix = std::env::var_os("PHOTOCRAFT_8BF_WINEPREFIX").map(PathBuf::from).unwrap_or_else(|| config.join("photocraft/8bf-wine"));
            if !prefix.is_absolute() {
                return Err(io::Error::new(io::ErrorKind::InvalidInput, "8BF Wine prefix must be an absolute path"));
            }
            environment.insert("WINEPREFIX".into(), prefix.into_os_string());
            environment.insert("WINEDEBUG".into(), "-all".into());
            (std::env::var_os("PHOTOCRAFT_8BF_WINE").map(PathBuf::from).unwrap_or_else(|| "wine".into()), vec![worker.into_os_string()], environment)
        };
        Ok(Self { program, args, environment, timeout: Duration::from_secs(600) })
    }
}
/// Worker runs on Windows; Wine's Z: drive maps the Linux absolute filesystem.
pub fn windows_path(path: &std::path::Path) -> io::Result<String> {
    let path = path.to_str().ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "8BF path must be valid UTF-8"))?;
    #[cfg(target_os = "windows")]
    {
        Ok(path.into())
    }
    #[cfg(not(target_os = "windows"))]
    {
        if !path.starts_with('/') {
            return Err(io::Error::new(io::ErrorKind::InvalidInput, "8BF path must be absolute"));
        }
        Ok(format!("Z:{}", path.replace('/', "\\")))
    }
}
fn invalid(message: impl Into<String>) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message.into())
}
struct Process(std::process::Child);
impl Process {
    fn terminate(&mut self) {
        // Wine can spawn descendants inheriting the pipes: kill the private process group,
        // then reap the direct child. This never touches a user's other Wine sessions.
        #[cfg(unix)]
        {
            let _ = std::process::Command::new("kill")
                .args(["-KILL", "--", &format!("-{}", self.0.id())])
                .stdout(std::process::Stdio::null())
                .stderr(std::process::Stdio::null())
                .status();
        }
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}
impl Drop for Process {
    fn drop(&mut self) {
        self.terminate();
    }
}
pub fn exchange(launch: &Launch, request: Request, pixels: Vec<u8>, cancelled: impl Fn() -> bool) -> io::Result<Vec<u8>> {
    use std::{
        io::Read,
        process::{Command, Stdio},
        sync::mpsc,
        time::Instant,
    };
    let expected =
        u64::from(request.width).checked_mul(u64::from(request.height)).and_then(|v| v.checked_mul(3)).ok_or_else(|| invalid("8BF dimensions overflow"))?;
    if request.width == 0
        || request.height == 0
        || request.channels != 3
        || request.depth != 8
        || expected != pixels.len() as u64
        || pixels.len() > super::wire::MAX_PIXELS
    {
        return Err(invalid("8BF request must contain bounded RGB8 pixels"));
    }
    if cancelled() {
        return Err(io::Error::new(io::ErrorKind::Interrupted, "8BF filter cancelled"));
    }
    let mut command = Command::new(&launch.program);
    command.env_remove("WINEARCH").args(&launch.args).envs(&launch.environment).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped());
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }
    let mut process = Process(command.spawn().map_err(|e| {
        io::Error::new(
            e.kind(),
            format!("Could not start 8BF worker {}: {e}. Configure PHOTOCRAFT_8BF_WORKER32/64 and install Wine on Linux.", launch.program.display()),
        )
    })?);
    let input = process.0.stdin.take().ok_or_else(|| io::Error::other("8BF worker stdin unavailable"))?;
    let output = process.0.stdout.take().ok_or_else(|| io::Error::other("8BF worker stdout unavailable"))?;
    let mut error = process.0.stderr.take().ok_or_else(|| io::Error::other("8BF worker stderr unavailable"))?;
    let (write_tx, write_rx) = mpsc::sync_channel(1);
    let outgoing = request.clone();
    std::thread::Builder::new().name("8bf-send".into()).spawn(move || {
        let _ = write_tx.send(super::wire::write_frame(input, &outgoing, &pixels));
    })?;
    let (read_tx, read_rx) = mpsc::sync_channel(1);
    std::thread::Builder::new().name("8bf-receive".into()).spawn(move || {
        let _ = read_tx.send(super::wire::read_frame::<Response>(output));
    })?;
    let (error_tx, error_rx) = mpsc::sync_channel(1);
    std::thread::Builder::new().name("8bf-stderr".into()).spawn(move || {
        let mut retained = Vec::new();
        let mut buffer = [0u8; 4096];
        loop {
            match error.read(&mut buffer) {
                Ok(0) | Err(_) => break,
                Ok(n) => {
                    let room = 4096usize.saturating_sub(retained.len());
                    retained.extend_from_slice(buffer.get(..n.min(room)).unwrap_or_default());
                }
            }
        }
        let _ = error_tx.send(String::from_utf8_lossy(&retained).into_owned());
    })?;
    let start = Instant::now();
    let mut sent = false;
    let mut received = None;
    loop {
        if cancelled() {
            return Err(io::Error::new(io::ErrorKind::Interrupted, "8BF filter cancelled"));
        }
        if start.elapsed() > launch.timeout {
            return Err(io::Error::new(io::ErrorKind::TimedOut, "8BF worker timed out; no pixels were applied"));
        }
        if !sent {
            match write_rx.try_recv() {
                Ok(r) => {
                    r?;
                    sent = true;
                }
                Err(mpsc::TryRecvError::Disconnected) => return Err(io::Error::other("8BF input writer disconnected")),
                Err(mpsc::TryRecvError::Empty) => {}
            }
        }
        if received.is_none() {
            match read_rx.try_recv() {
                Ok(r) => received = Some(r?),
                Err(mpsc::TryRecvError::Disconnected) => return Err(io::Error::other("8BF response reader disconnected")),
                Err(mpsc::TryRecvError::Empty) => {}
            }
        }
        if let Some(status) = process.0.try_wait()? {
            if !status.success() {
                let detail = error_rx.try_recv().unwrap_or_default();
                return Err(io::Error::other(format!("8BF worker exited {status}: {detail}")));
            }
            if sent && let Some((response, bytes)) = received.take() {
                match response.status.as_str() {
                    "cancelled" => return Err(io::Error::new(io::ErrorKind::Interrupted, "8BF filter cancelled in plug-in dialog")),
                    "error" => return Err(io::Error::other(format!("8BF filter: {}", response.message))),
                    "ok" => {}
                    _ => return Err(invalid("unknown 8BF response status")),
                }
                if response.width != request.width
                    || response.height != request.height
                    || response.channels != 3
                    || response.depth != 8
                    || bytes.len() as u64 != expected
                {
                    return Err(invalid("8BF worker returned inconsistent pixel dimensions or format"));
                }
                return Ok(bytes);
            }
        }
        std::thread::sleep(Duration::from_millis(10));
    }
}
#[cfg(all(test, unix))]
mod tests {
    use super::*;
    fn request() -> Request {
        Request { path: "ignored.8bf".into(), entry: "PluginMain".into(), width: 2, height: 1, channels: 3, depth: 8, show_ui: false }
    }
    fn launch(script: &str) -> Launch {
        Launch { program: "python3".into(), args: vec!["-c".into(), script.into()], environment: BTreeMap::new(), timeout: Duration::from_secs(3) }
    }
    #[test]
    fn child_transport_roundtrips_and_rejects_malformed_or_crashed_worker() {
        let script = r#"import sys,struct,json
r=sys.stdin.buffer; w=sys.stdout.buffer
assert r.read(8)==b'PC8BF001'
n,p=struct.unpack('<IQ',r.read(12)); m=json.loads(r.read(n)); pixels=r.read(p)
m={'status':'ok','message':'','width':m['width'],'height':m['height'],'channels':3,'depth':8}
h=json.dumps(m).encode(); w.write(b'PC8BF001'+struct.pack('<IQ',len(h),len(pixels))+h+bytes(255-v for v in pixels)); w.flush()
"#;
        assert_eq!(exchange(&launch(script), request(), vec![1, 2, 3, 4, 5, 6], || false).unwrap(), [254, 253, 252, 251, 250, 249]);
        for script in ["import sys; sys.exit(17)", "import sys; sys.stdout.buffer.write(b'bad reply')"] {
            assert!(exchange(&launch(script), request(), vec![0; 6], || false).is_err());
        }
    }
    #[test]
    fn blocked_worker_cancels_and_times_out_without_hanging() {
        let mut l = launch("import time; time.sleep(60)");
        l.timeout = Duration::from_millis(60);
        let start = std::time::Instant::now();
        assert_eq!(exchange(&l, request(), vec![0; 6], || false).unwrap_err().kind(), io::ErrorKind::TimedOut);
        assert!(start.elapsed() < Duration::from_secs(2));
        let start = std::time::Instant::now();
        assert_eq!(exchange(&l, request(), vec![0; 6], || start.elapsed() > Duration::from_millis(20)).unwrap_err().kind(), io::ErrorKind::Interrupted);
        assert!(start.elapsed() < Duration::from_secs(2));
    }
}
