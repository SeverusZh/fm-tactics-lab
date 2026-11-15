use std::{
    env,
    fs::File,
    io::{BufRead, BufReader, Read, Write},
    net::{SocketAddr, TcpStream},
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        mpsc, Mutex,
    },
    thread,
    time::{Duration, Instant},
};

use fm27lab_core::{
    backoff::Backoff,
    connection::{connection_info, ConnectionInfo},
    ready::parse_ready_line,
    token::generate_token,
};
use tauri::{AppHandle, Emitter, Manager, RunEvent, State};

const MAX_RESTARTS: usize = 3;
const STARTUP_TIMEOUT: Duration = Duration::from_secs(30);
const SHUTDOWN_WAIT: Duration = Duration::from_secs(10);
const HEALTH_INTERVAL: Duration = Duration::from_secs(5);

#[derive(Default)]
struct SidecarState {
    child: Mutex<Option<Child>>,
    connection: Mutex<Option<ConnectionInfo>>,
    lifecycle: Mutex<()>,
    stopping: AtomicBool,
    manual_restart: AtomicBool,
    paused: AtomicBool,
    restart_in_progress: AtomicBool,
    restarts: AtomicUsize,
    data_dir: Mutex<Option<PathBuf>>,
}

fn project_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("src-tauri lives inside the repository")
        .to_path_buf()
}

fn launch_spec(app: &AppHandle) -> Result<(PathBuf, Vec<String>, PathBuf), String> {
    if let Ok(path) = env::var("FM27LAB_SIDECAR") {
        let executable = PathBuf::from(path);
        let cwd = executable
            .parent()
            .map(PathBuf::from)
            .unwrap_or_else(project_root);
        return Ok((executable, Vec::new(), cwd));
    }
    if cfg!(debug_assertions) {
        let python = env::var("FM27LAB_PYTHON").unwrap_or_else(|_| {
            if cfg!(windows) {
                "python.exe".to_string()
            } else {
                "python3".to_string()
            }
        });
        return Ok((
            PathBuf::from(python),
            vec!["-m".into(), "fm27lab".into(), "serve".into()],
            project_root(),
        ));
    }
    let resource = app
        .path()
        .resource_dir()
        .map_err(|error| format!("resource directory is unavailable: {error}"))?;
    let executable = resource.join("sidecar").join(if cfg!(windows) {
        "fm27lab-sidecar.exe"
    } else {
        "fm27lab-sidecar"
    });
    Ok((executable, Vec::new(), resource))
}

fn parse_port(url: &str) -> Option<u16> {
    url.rsplit_once(':')?.1.parse().ok()
}

fn is_status(line: &str, code: &str) -> bool {
    line.contains(&format!(" {code} ")) || line.ends_with(&format!(" {code}"))
}

fn is_success_status(line: &str) -> bool {
    is_status(line, "200")
}

fn http_probe(connection: &ConnectionInfo, request_path: &str) -> Option<String> {
    let port = parse_port(&connection.url)?;
    let address: SocketAddr = format!("127.0.0.1:{port}").parse().ok()?;
    let mut stream = TcpStream::connect_timeout(&address, Duration::from_secs(2)).ok()?;
    stream.set_read_timeout(Some(Duration::from_secs(2))).ok()?;
    stream
        .set_write_timeout(Some(Duration::from_secs(2)))
        .ok()?;
    let request = format!(
        "GET {request_path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nAuthorization: Bearer {}\r\nConnection: close\r\n\r\n",
        connection.token
    );
    stream.write_all(request.as_bytes()).ok()?;
    let mut reader = BufReader::new(stream);
    let mut line = String::new();
    reader.read_line(&mut line).ok()?;
    Some(line.trim_end().to_string())
}

fn health_ok(connection: &ConnectionInfo) -> bool {
    http_probe(connection, "/api/health").is_some_and(|line| is_success_status(&line))
}

fn post_shutdown(connection: &ConnectionInfo) -> bool {
    let Some(port) = parse_port(&connection.url) else {
        return false;
    };
    let Ok(address) = format!("127.0.0.1:{port}").parse() else {
        return false;
    };
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_secs(2)) else {
        return false;
    };
    let _ = stream.set_write_timeout(Some(Duration::from_secs(2)));
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let request = format!(
        "POST /api/shutdown HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nAuthorization: Bearer {}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
        connection.token
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut status = String::new();
    if BufReader::new(stream).read_line(&mut status).is_err() {
        return false;
    }
    is_status(&status, "202")
}

fn remove_endpoint(data_dir: &std::path::Path) {
    let endpoint = data_dir.join("agent").join("endpoint.json");
    let _ = std::fs::remove_file(&endpoint);
    let _ = std::fs::remove_file(endpoint.with_extension("json.tmp"));
}

fn clear_connection(state: &SidecarState) {
    if let Ok(mut guard) = state.connection.lock() {
        *guard = None;
    }
}

fn kill_child(state: &SidecarState) {
    if let Ok(mut guard) = state.child.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

fn child_running(state: &SidecarState) -> bool {
    let mut guard = match state.child.lock() {
        Ok(guard) => guard,
        Err(_) => return false,
    };
    match guard.as_mut() {
        Some(child) => matches!(child.try_wait(), Ok(None)),
        None => false,
    }
}

fn start_allowed(state: &SidecarState, allow_restart: bool) -> bool {
    if state.stopping.load(Ordering::SeqCst) {
        return false;
    }
    if allow_restart {
        return true;
    }
    !state.paused.load(Ordering::SeqCst)
        && !state.restart_in_progress.load(Ordering::SeqCst)
        && !child_running(state)
}

fn should_start(state: &SidecarState) -> bool {
    start_allowed(state, false)
}

fn take_dead_child(state: &SidecarState) -> Option<Child> {
    let mut guard = state.child.lock().ok()?;
    let exited = guard
        .as_mut()
        .is_some_and(|child| !matches!(child.try_wait(), Ok(None)));
    if exited {
        guard.take()
    } else {
        None
    }
}

fn start_sidecar(app: &AppHandle) -> Result<ConnectionInfo, String> {
    start_sidecar_inner(app, false)
}

fn start_sidecar_inner(app: &AppHandle, allow_restart: bool) -> Result<ConnectionInfo, String> {
    let state = app.state::<SidecarState>();
    let _lifecycle = state
        .lifecycle
        .lock()
        .map_err(|_| "lifecycle lock poisoned")?;
    if !start_allowed(&state, allow_restart) {
        return Err("sidecar start is not allowed".to_string());
    }
    let data_dir = app
        .path()
        .app_local_data_dir()
        .map_err(|error| format!("data directory is unavailable: {error}"))?;
    remove_endpoint(&data_dir);
    clear_connection(&state);
    kill_child(&state);
    let (program, args, cwd) = launch_spec(app)?;
    let token = generate_token().map_err(|error| format!("token generation failed: {error}"))?;
    let engine_root = env::var("FM27_ENGINE_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|_| data_dir.join("engine"));
    let log_dir = data_dir.join("logs");
    let _ = std::fs::create_dir_all(&log_dir);
    let mut command = Command::new(&program);
    command
        .args(&args)
        .current_dir(&cwd)
        .env("FM27LAB_DATA", &data_dir)
        .env("FM27LAB_TOKEN", &token)
        .env("FM27_ENGINE_ROOT", &engine_root)
        .env("FM27LAB_PORT", "0")
        .env("PYTHONUTF8", "1")
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    if cfg!(debug_assertions) {
        command.env("FM27LAB_DEV", "1");
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000);
    }
    let mut child = command
        .spawn()
        .map_err(|error| format!("cannot start sidecar {program:?}: {error}"))?;
    if let Some(mut stderr) = child.stderr.take() {
        let log_path = log_dir.join(format!("sidecar-{}.stderr.log", child.id()));
        thread::spawn(move || {
            if let Ok(mut file) = File::create(log_path) {
                let _ = std::io::copy(&mut stderr, &mut file);
            }
        });
    }
    let Some(stdout) = child.stdout.take() else {
        let _ = child.kill();
        let _ = child.wait();
        remove_endpoint(&data_dir);
        return Err("sidecar stdout is unavailable".to_string());
    };
    let (sender, receiver) = mpsc::channel();
    thread::spawn(move || {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if sender.send(line).is_err() {
                return;
            }
        }
    });
    let deadline = Instant::now() + STARTUP_TIMEOUT;
    let connection = loop {
        let now = Instant::now();
        if now >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            remove_endpoint(&data_dir);
            return Err("sidecar did not report readiness within 30 seconds".to_string());
        }
        match receiver.recv_timeout(deadline - now) {
            Ok(line) => {
                if let Ok(ready) = parse_ready_line(&line) {
                    break connection_info("127.0.0.1", ready.port, &token);
                }
            }
            Err(_) => {
                let _ = child.kill();
                let _ = child.wait();
                remove_endpoint(&data_dir);
                return Err("sidecar closed before readiness".to_string());
            }
        }
    };
    while Instant::now() < deadline {
        if health_ok(&connection) {
            if let Ok(mut guard) = state.child.lock() {
                *guard = Some(child);
            }
            if let Ok(mut guard) = state.connection.lock() {
                *guard = Some(connection.clone());
            }
            if let Ok(mut guard) = state.data_dir.lock() {
                *guard = Some(data_dir.clone());
            }
            return Ok(connection);
        }
        if matches!(child.try_wait(), Ok(Some(_))) {
            break;
        }
        thread::sleep(Duration::from_millis(200));
    }
    let _ = child.kill();
    let _ = child.wait();
    remove_endpoint(&data_dir);
    clear_connection(&state);
    Err("sidecar health check did not become ready".to_string())
}

fn monitor(app: AppHandle) {
    let mut health_failures = 0usize;
    let mut last_health = Instant::now();
    let mut stable_since = Instant::now();
    loop {
        thread::sleep(Duration::from_millis(500));
        let state = app.state::<SidecarState>();
        if state.stopping.load(Ordering::SeqCst) {
            return;
        }
        if state.paused.load(Ordering::SeqCst) {
            if state.manual_restart.swap(false, Ordering::SeqCst) {
                state.paused.store(false, Ordering::SeqCst);
                state.restarts.store(0, Ordering::SeqCst);
                stable_since = Instant::now();
            } else {
                continue;
            }
        }
        if state.manual_restart.swap(false, Ordering::SeqCst) {
            stable_since = Instant::now();
            continue;
        }
        if let Some(mut child) = take_dead_child(&state) {
            let _ = child.wait();
            clear_connection(&state);
            let _ = app.emit("sidecar-down", "sidecar exited");
            let attempt = state.restarts.fetch_add(1, Ordering::SeqCst) + 1;
            if attempt > MAX_RESTARTS {
                state.paused.store(true, Ordering::SeqCst);
                let _ = app.emit("sidecar-failed", "restart limit reached");
                continue;
            }
            let delay = Backoff::new(500, MAX_RESTARTS)
                .delays()
                .get(attempt - 1)
                .copied()
                .unwrap_or(4_000);
            thread::sleep(Duration::from_millis(delay));
            if !should_start(&state) {
                continue;
            }
            match start_sidecar(&app) {
                Ok(connection) => {
                    stable_since = Instant::now();
                    let _ = app.emit("sidecar-ready", connection);
                }
                Err(error) => {
                    let _ = app.emit("sidecar-error", error);
                }
            }
            continue;
        }
        if !child_running(&state) {
            if state.restart_in_progress.load(Ordering::SeqCst) {
                continue;
            }
            let attempt = state.restarts.fetch_add(1, Ordering::SeqCst) + 1;
            if attempt > MAX_RESTARTS {
                state.paused.store(true, Ordering::SeqCst);
                let _ = app.emit("sidecar-failed", "restart limit reached");
                continue;
            }
            let delay = Backoff::new(500, MAX_RESTARTS)
                .delays()
                .get(attempt - 1)
                .copied()
                .unwrap_or(4_000);
            thread::sleep(Duration::from_millis(delay));
            if !should_start(&state) {
                continue;
            }
            match start_sidecar(&app) {
                Ok(connection) => {
                    stable_since = Instant::now();
                    let _ = app.emit("sidecar-ready", connection);
                }
                Err(error) => {
                    let _ = app.emit("sidecar-error", error);
                }
            }
            continue;
        }
        if stable_since.elapsed() > Duration::from_secs(30)
            && state.restarts.load(Ordering::SeqCst) > 0
        {
            state.restarts.store(0, Ordering::SeqCst);
        }
        if last_health.elapsed() >= HEALTH_INTERVAL {
            last_health = Instant::now();
            if let Ok(_guard) = state.lifecycle.try_lock() {
                let connection = state.connection.lock().ok().and_then(|guard| guard.clone());
                if let Some(connection) = connection {
                    if health_ok(&connection) {
                        health_failures = 0;
                    } else {
                        health_failures += 1;
                        if health_failures >= 3 {
                            let _ = app.emit("sidecar-down", "sidecar health check failed");
                            kill_child(&state);
                            health_failures = 0;
                        }
                    }
                }
            }
        }
    }
}

fn stop_sidecar(state: &SidecarState) {
    state.stopping.store(true, Ordering::SeqCst);
    let _lifecycle = match state.lifecycle.lock() {
        Ok(guard) => guard,
        Err(_) => return,
    };
    if let Ok(guard) = state.connection.lock() {
        if let Some(connection) = guard.as_ref() {
            post_shutdown(connection);
        }
    }
    let mut child = state.child.lock().ok().and_then(|mut guard| guard.take());
    if let Some(child) = child.as_mut() {
        let deadline = Instant::now() + SHUTDOWN_WAIT;
        while Instant::now() < deadline {
            match child.try_wait() {
                Ok(Some(_)) => break,
                Ok(None) => thread::sleep(Duration::from_millis(100)),
                Err(_) => break,
            }
        }
        if matches!(child.try_wait(), Ok(None)) {
            let _ = child.kill();
        }
        let _ = child.wait();
    }
    if let Some(data_dir) = state.data_dir.lock().ok().and_then(|guard| guard.clone()) {
        remove_endpoint(&data_dir);
    }
    clear_connection(state);
}

#[tauri::command]
fn get_connection(state: State<SidecarState>) -> Result<ConnectionInfo, String> {
    state
        .connection
        .lock()
        .map_err(|_| "connection lock poisoned")?
        .clone()
        .ok_or_else(|| "sidecar is not connected".to_string())
}

#[tauri::command]
fn sidecar_status(state: State<SidecarState>) -> Result<serde_json::Value, String> {
    let connection = state
        .connection
        .lock()
        .map_err(|_| "connection lock poisoned")?
        .clone();
    let running = child_running(&state);
    Ok(serde_json::json!({
        "running": running,
        "url": connection.as_ref().map(|item| item.url.clone()),
        "api": connection.as_ref().map(|item| item.api.clone()),
        "restarts": state.restarts.load(Ordering::SeqCst),
    }))
}

#[tauri::command]
fn restart_sidecar(app: AppHandle, state: State<SidecarState>) -> Result<ConnectionInfo, String> {
    if state.stopping.load(Ordering::SeqCst) {
        return Err("sidecar is stopping".to_string());
    }
    state.restart_in_progress.store(true, Ordering::SeqCst);
    state.manual_restart.store(true, Ordering::SeqCst);
    state.paused.store(false, Ordering::SeqCst);
    state.restarts.store(0, Ordering::SeqCst);
    kill_child(&state);
    clear_connection(&state);
    let result = start_sidecar_inner(&app, true);
    state.restart_in_progress.store(false, Ordering::SeqCst);
    if let Ok(connection) = &result {
        let _ = app.emit("sidecar-ready", connection);
    }
    result
}

#[tauri::command]
fn shutdown_sidecar(state: State<SidecarState>) -> Result<(), String> {
    stop_sidecar(&state);
    Ok(())
}

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .manage(SidecarState::default())
        .setup(|app| {
            let handle = app.handle().clone();
            thread::spawn(move || {
                match start_sidecar(&handle) {
                    Ok(connection) => {
                        let _ = handle.emit("sidecar-ready", connection);
                    }
                    Err(error) => {
                        let _ = handle.emit("sidecar-error", &error);
                    }
                }
                monitor(handle);
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_connection,
            sidecar_status,
            restart_sidecar,
            shutdown_sidecar
        ])
        .build(tauri::generate_context!())
        .expect("error while building FM Tactics Lab");
    app.run(|app_handle, event| {
        if let RunEvent::Exit = event {
            let state = app_handle.state::<SidecarState>();
            stop_sidecar(&state);
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;

    #[test]
    fn parses_success_status_lines() {
        assert!(is_success_status("HTTP/1.1 200 OK"));
        assert!(is_success_status("HTTP/1.0 200"));
        assert!(!is_success_status("HTTP/1.1 503 Service Unavailable"));
    }

    #[test]
    fn parses_connection_ports() {
        assert_eq!(parse_port("http://127.0.0.1:43210"), Some(43210));
        assert_eq!(parse_port("not-a-url"), None);
    }

    #[test]
    fn restart_backoff_is_bounded() {
        assert_eq!(Backoff::new(500, 3).delays(), vec![500, 1000, 2000]);
    }

    #[test]
    fn health_probe_accepts_200() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut buffer = [0u8; 512];
            let _ = stream.read(&mut buffer);
            let _ = stream.write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n");
        });
        let connection = connection_info("127.0.0.1", port, "token");
        assert!(health_ok(&connection));
        server.join().unwrap();
    }

    #[test]
    fn start_gate_blocks_stopping_paused_and_restarting() {
        let state = SidecarState::default();
        assert!(should_start(&state));
        assert!(start_allowed(&state, true));
        state.stopping.store(true, Ordering::SeqCst);
        assert!(!should_start(&state));
        assert!(!start_allowed(&state, true));
        state.stopping.store(false, Ordering::SeqCst);
        state.paused.store(true, Ordering::SeqCst);
        assert!(!should_start(&state));
        assert!(start_allowed(&state, true));
        state.paused.store(false, Ordering::SeqCst);
        state.restart_in_progress.store(true, Ordering::SeqCst);
        assert!(!should_start(&state));
        assert!(start_allowed(&state, true));
    }

    #[test]
    fn endpoint_cleanup_removes_token_file() {
        let data_dir =
            std::env::temp_dir().join(format!("fm27lab-endpoint-{}", std::process::id()));
        let agent = data_dir.join("agent");
        std::fs::create_dir_all(&agent).unwrap();
        let endpoint = agent.join("endpoint.json");
        std::fs::write(&endpoint, "secret").unwrap();
        remove_endpoint(&data_dir);
        assert!(!endpoint.exists());
        let _ = std::fs::remove_dir_all(data_dir);
    }

    #[test]
    fn stop_sidecar_removes_endpoint_and_child() {
        let data_dir = std::env::temp_dir().join(format!("fm27lab-stop-{}", std::process::id()));
        let agent = data_dir.join("agent");
        std::fs::create_dir_all(&agent).unwrap();
        let endpoint = agent.join("endpoint.json");
        std::fs::write(&endpoint, "{}").unwrap();
        let state = SidecarState::default();
        *state.data_dir.lock().unwrap() = Some(data_dir.clone());
        let mut command = if cfg!(windows) {
            let mut command = Command::new("cmd");
            command.args(["/C", "exit", "0"]);
            command
        } else {
            let mut command = Command::new("sh");
            command.args(["-c", "exit 0"]);
            command
        };
        *state.child.lock().unwrap() = Some(command.spawn().unwrap());
        stop_sidecar(&state);
        assert!(!endpoint.exists());
        assert!(state.child.lock().unwrap().is_none());
        let _ = std::fs::remove_dir_all(data_dir);
    }

    #[test]
    fn shutdown_posts_bearer_token() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut buffer = [0u8; 1024];
            let read = stream.read(&mut buffer).unwrap();
            let request = String::from_utf8_lossy(&buffer[..read]).to_string();
            let _ = stream.write_all(b"HTTP/1.1 202 Accepted\r\nContent-Length: 0\r\n\r\n");
            request
        });
        let connection = connection_info("127.0.0.1", port, "secret-token");
        assert!(post_shutdown(&connection));
        let request = server.join().unwrap();
        assert!(request.contains("POST /api/shutdown"));
        assert!(request.contains("Bearer secret-token"));
    }
}
