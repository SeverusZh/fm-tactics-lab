use std::{
    env,
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
    connection::{connection_info, health_url, ConnectionInfo},
    ready::parse_ready_line,
    token::generate_token,
};
use tauri::{AppHandle, Emitter, Manager, RunEvent, State};

const MAX_RESTARTS: usize = 3;
const STARTUP_TIMEOUT: Duration = Duration::from_secs(30);

#[derive(Default)]
struct SidecarState {
    child: Mutex<Option<Child>>,
    connection: Mutex<Option<ConnectionInfo>>,
    shutting_down: AtomicBool,
    manual_restart: AtomicBool,
    restarts: AtomicUsize,
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

fn is_success_status(line: &str) -> bool {
    line.contains(" 200 ") || line.ends_with(" 200")
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

fn post_shutdown(connection: &ConnectionInfo) {
    let Some(port) = parse_port(&connection.url) else {
        return;
    };
    let Ok(address) = format!("127.0.0.1:{port}").parse() else {
        return;
    };
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_secs(2)) else {
        return;
    };
    let _ = stream.set_write_timeout(Some(Duration::from_secs(2)));
    let request = format!(
        "POST /api/shutdown HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nAuthorization: Bearer {}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
        connection.token
    );
    let _ = stream.write_all(request.as_bytes());
    let _ = stream.read_to_end(&mut Vec::new());
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

fn start_sidecar(app: &AppHandle) -> Result<ConnectionInfo, String> {
    let state = app.state::<SidecarState>();
    state.manual_restart.store(false, Ordering::SeqCst);
    clear_connection(&state);
    kill_child(&state);
    let (program, args, cwd) = launch_spec(app)?;
    let data_dir = app
        .path()
        .app_local_data_dir()
        .map_err(|error| format!("data directory is unavailable: {error}"))?;
    let token = generate_token().map_err(|error| format!("token generation failed: {error}"))?;
    let engine_root = env::var("FM27_ENGINE_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|_| data_dir.join("engine"));
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
        .stderr(Stdio::inherit());
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
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "sidecar stdout is unavailable".to_string())?;
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
                return Err("sidecar closed before readiness".to_string());
            }
        }
    };
    let health_deadline = Instant::now() + STARTUP_TIMEOUT;
    while Instant::now() < health_deadline {
        if health_ok(&connection) {
            if let Ok(mut guard) = state.child.lock() {
                *guard = Some(child);
            }
            if let Ok(mut guard) = state.connection.lock() {
                *guard = Some(connection.clone());
            }
            let _ = app.emit("sidecar-ready", &connection);
            return Ok(connection);
        }
        if matches!(child.try_wait(), Ok(Some(_))) {
            break;
        }
        thread::sleep(Duration::from_millis(200));
    }
    let _ = child.kill();
    let _ = child.wait();
    clear_connection(&state);
    Err("sidecar health check did not become ready".to_string())
}

fn monitor(app: AppHandle) {
    let mut attempts = 0usize;
    loop {
        let state = app.state::<SidecarState>();
        if state.shutting_down.load(Ordering::SeqCst) {
            return;
        }
        if state.manual_restart.swap(false, Ordering::SeqCst) {
            continue;
        }
        let child = state.child.lock().ok().and_then(|mut guard| guard.take());
        if let Some(mut child) = child {
            let _ = child.wait();
            if state.shutting_down.load(Ordering::SeqCst) {
                return;
            }
            if state.manual_restart.swap(false, Ordering::SeqCst) {
                continue;
            }
            clear_connection(&state);
            let _ = app.emit("sidecar-down", "sidecar exited");
            attempts += 1;
            state.restarts.store(attempts, Ordering::SeqCst);
            if attempts > MAX_RESTARTS {
                let _ = app.emit("sidecar-failed", "restart limit reached");
                return;
            }
            let delay = Backoff::new(500, MAX_RESTARTS)
                .delays()
                .get(attempts - 1)
                .copied()
                .unwrap_or(4_000);
            thread::sleep(Duration::from_millis(delay));
        } else {
            thread::sleep(Duration::from_millis(500));
        }
        match start_sidecar(&app) {
            Ok(connection) => {
                let _ = app.emit("sidecar-ready", connection);
            }
            Err(error) => {
                let _ = app.emit("sidecar-error", error);
                attempts += 1;
                if attempts > MAX_RESTARTS {
                    let _ = app.emit("sidecar-failed", "restart limit reached");
                    return;
                }
            }
        }
    }
}

fn stop_sidecar(state: &SidecarState) {
    state.shutting_down.store(true, Ordering::SeqCst);
    if let Ok(guard) = state.connection.lock() {
        if let Some(connection) = guard.as_ref() {
            post_shutdown(connection);
        }
    }
    kill_child(state);
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
    let running = state
        .child
        .lock()
        .map_err(|_| "sidecar lock poisoned")?
        .as_mut()
        .is_some_and(|child| matches!(child.try_wait(), Ok(None)));
    Ok(serde_json::json!({
        "running": running,
        "url": connection.as_ref().map(|item| item.url.clone()),
        "api": connection.as_ref().map(|item| item.api.clone()),
        "restarts": state.restarts.load(Ordering::SeqCst),
    }))
}

#[tauri::command]
fn restart_sidecar(app: AppHandle, state: State<SidecarState>) -> Result<ConnectionInfo, String> {
    state.manual_restart.store(true, Ordering::SeqCst);
    kill_child(&state);
    clear_connection(&state);
    start_sidecar(&app)
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
        .plugin(tauri_plugin_opener::init())
        .manage(SidecarState::default())
        .setup(|app| {
            let handle = app.handle().clone();
            match start_sidecar(&handle) {
                Ok(connection) => {
                    let _ = handle.emit("sidecar-ready", connection);
                }
                Err(error) => {
                    let _ = handle.emit("sidecar-error", &error);
                }
            }
            thread::spawn(move || monitor(handle));
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
}
