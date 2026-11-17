use std::{
    collections::VecDeque,
    env,
    ffi::OsStr,
    fs::File,
    io::{BufRead, BufReader, Read, Write},
    net::{SocketAddr, TcpStream},
    path::{Path, PathBuf},
    process::{Child, ChildStderr, Command, Stdio},
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        mpsc, Arc, Mutex,
    },
    thread,
    time::{Duration, Instant},
};

use fm27lab_core::{
    connection::{connection_info, ConnectionInfo},
    ready::parse_ready_line,
    supervisor::{self, Phase, ShutdownStep},
    token::generate_token,
};
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Emitter, Manager, RunEvent, State,
};

const STARTUP_TIMEOUT: Duration = Duration::from_secs(30);
const SHUTDOWN_WAIT: Duration = Duration::from_secs(10);
const HEALTH_INTERVAL: Duration = Duration::from_secs(5);

const TRAY_SHOW: &str = "tray-show";
const TRAY_HIDE: &str = "tray-hide";
const TRAY_RESTART: &str = "tray-restart";
const TRAY_QUIT: &str = "tray-quit";

fn normalize_external_url(raw: &str) -> Result<String, String> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return Err("链接不能为空".to_string());
    }
    let illegal = |character: char| {
        character.is_whitespace()
            || character.is_control()
            || matches!(character, '"' | '<' | '>' | '\\' | '^' | '|' | '`' | '{' | '}')
    };
    if trimmed.chars().any(illegal) {
        return Err("只允许 http 或 https 链接".to_string());
    }
    let Some((scheme, rest)) = trimmed.split_once("://") else {
        return Err("只允许 http 或 https 链接".to_string());
    };
    if !(scheme.eq_ignore_ascii_case("http") || scheme.eq_ignore_ascii_case("https")) {
        return Err("只允许 http 或 https 链接".to_string());
    }
    let authority = rest
        .split(|character: char| character == '/' || character == '?' || character == '#')
        .next()
        .unwrap_or("");
    if authority.is_empty() || authority.contains('@') {
        return Err("只允许 http 或 https 链接".to_string());
    }
    Ok(trimmed.to_string())
}

fn system_open(target: &OsStr) -> Result<(), String> {
    // Windows 走 FileProtocolHandler，避免 cmd.exe 重新解析 & | ^ % 等字符
    let mut command = if cfg!(windows) {
        let mut command = Command::new("rundll32.exe");
        command.arg("url.dll,FileProtocolHandler");
        command
    } else if cfg!(target_os = "macos") {
        Command::new("open")
    } else {
        Command::new("xdg-open")
    };
    command
        .arg(target)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map(|_| ())
        .map_err(|error| format!("cannot open {target:?}: {error}"))
}

fn open_directory(path: &OsStr) -> Result<(), String> {
    // 目录交给系统文件管理器，Windows 用 explorer 而非 URL 协议处理器
    let mut command = if cfg!(windows) {
        Command::new("explorer.exe")
    } else if cfg!(target_os = "macos") {
        Command::new("open")
    } else {
        Command::new("xdg-open")
    };
    command
        .arg(path)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map(|_| ())
        .map_err(|error| format!("cannot open directory {path:?}: {error}"))
}

fn show_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn hide_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.hide();
    }
}

fn restart_sidecar_in_background(app: &AppHandle) {
    let handle = app.clone();
    thread::spawn(move || {
        if let Err(error) = restart_sidecar_inner(&handle) {
            let _ = handle.emit("sidecar-error", error);
        }
    });
}

fn setup_tray(app: &AppHandle) -> Result<(), String> {
    let show = MenuItem::with_id(app, TRAY_SHOW, "显示主窗口", true, None::<&str>)
        .map_err(|error| format!("tray menu item failed: {error}"))?;
    let hide = MenuItem::with_id(app, TRAY_HIDE, "隐藏主窗口", true, None::<&str>)
        .map_err(|error| format!("tray menu item failed: {error}"))?;
    let restart = MenuItem::with_id(app, TRAY_RESTART, "重启 sidecar", true, None::<&str>)
        .map_err(|error| format!("tray menu item failed: {error}"))?;
    let quit = MenuItem::with_id(app, TRAY_QUIT, "退出", true, None::<&str>)
        .map_err(|error| format!("tray menu item failed: {error}"))?;
    let menu = Menu::with_items(app, &[&show, &hide, &restart, &quit])
        .map_err(|error| format!("tray menu failed: {error}"))?;
    let icon = app
        .default_window_icon()
        .cloned()
        .ok_or_else(|| "tray icon is unavailable".to_string())?;
    let tray = TrayIconBuilder::new()
        .icon(icon)
        .tooltip("FM Tactics Lab")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| {
            let id = event.id.as_ref();
            if id == TRAY_SHOW {
                show_main_window(app);
            } else if id == TRAY_HIDE {
                hide_main_window(app);
            } else if id == TRAY_RESTART {
                restart_sidecar_in_background(app);
            } else if id == TRAY_QUIT {
                app.exit(0);
            }
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                show_main_window(tray.app_handle());
            }
        })
        .build(app)
        .map_err(|error| format!("tray icon failed: {error}"))?;
    std::mem::forget(tray);
    Ok(())
}

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

fn http_probe(connection: &ConnectionInfo, request_path: &str) -> Option<String> {
    let port = supervisor::parse_port(&connection.url)?;
    let address: SocketAddr = format!("127.0.0.1:{port}").parse().ok()?;
    let mut stream = TcpStream::connect_timeout(&address, Duration::from_secs(2)).ok()?;
    stream.set_read_timeout(Some(Duration::from_secs(2))).ok()?;
    stream
        .set_write_timeout(Some(Duration::from_secs(2)))
        .ok()?;
    let request = supervisor::probe_request(port, &connection.token, request_path);
    stream.write_all(request.as_bytes()).ok()?;
    let mut reader = BufReader::new(stream);
    let mut line = String::new();
    reader.read_line(&mut line).ok()?;
    Some(line.trim_end().to_string())
}

fn health_ok(connection: &ConnectionInfo) -> bool {
    let status = http_probe(connection, "/api/health");
    supervisor::classify_health(status.as_deref()).is_healthy()
}

fn post_shutdown(connection: &ConnectionInfo) -> bool {
    let Some(port) = supervisor::parse_port(&connection.url) else {
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
    let request = supervisor::shutdown_request(port, &connection.token);
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut status = String::new();
    if BufReader::new(stream).read_line(&mut status).is_err() {
        return false;
    }
    supervisor::is_shutdown_accepted(&status)
}

fn remove_endpoint(data_dir: &std::path::Path) {
    for endpoint in supervisor::endpoint_paths(data_dir) {
        let _ = std::fs::remove_file(endpoint);
    }
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

fn await_child_exit(child: &mut Child) {
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

fn phase(state: &SidecarState) -> Phase {
    if state.stopping.load(Ordering::SeqCst) {
        return Phase::Stopping;
    }
    if state.restart_in_progress.load(Ordering::SeqCst) {
        return Phase::Starting;
    }
    if state.paused.load(Ordering::SeqCst) {
        return Phase::Failed;
    }
    if child_running(state) {
        return Phase::Running;
    }
    Phase::Stopped
}

fn start_allowed(state: &SidecarState, allow_restart: bool) -> bool {
    supervisor::start_allowed(phase(state), allow_restart)
}

fn next_restart_delay(state: &SidecarState) -> Option<u64> {
    let attempt = state.restarts.fetch_add(1, Ordering::SeqCst) + 1;
    supervisor::restart_delay_ms(attempt)
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

fn capture_stderr(stderr: ChildStderr, log_path: PathBuf) -> Arc<Mutex<VecDeque<String>>> {
    let tail = Arc::new(Mutex::new(VecDeque::with_capacity(
        supervisor::STDERR_TAIL_LINES,
    )));
    let shared = Arc::clone(&tail);
    thread::spawn(move || {
        let mut file = File::create(&log_path).ok();
        let mut reader = BufReader::new(stderr);
        let mut buffer = Vec::new();
        loop {
            buffer.clear();
            match reader.read_until(b'\n', &mut buffer) {
                Ok(0) => break,
                Ok(_) => {
                    if let Some(file) = file.as_mut() {
                        let _ = file.write_all(&buffer);
                    }
                    let text = String::from_utf8_lossy(&buffer);
                    let line = text.trim_end_matches(&['\r', '\n'][..]).to_string();
                    if let Ok(mut guard) = shared.lock() {
                        if guard.len() == supervisor::STDERR_TAIL_LINES {
                            guard.pop_front();
                        }
                        guard.push_back(line);
                    }
                }
                Err(_) => break,
            }
        }
    });
    tail
}

fn stderr_tail(tail: &Option<Arc<Mutex<VecDeque<String>>>>) -> Vec<String> {
    tail.as_ref()
        .and_then(|shared| shared.lock().ok())
        .map(|guard| guard.iter().cloned().collect())
        .unwrap_or_default()
}

fn sidecar_failure(
    reason: &str,
    child: &mut Child,
    log_path: &Path,
    tail: &Option<Arc<Mutex<VecDeque<String>>>>,
    data_dir: &Path,
) -> String {
    let exit = match child.try_wait() {
        Ok(Some(status)) => status.code(),
        _ => None,
    };
    let log = if log_path.exists() {
        Some(log_path)
    } else {
        None
    };
    let mut message = supervisor::startup_failure(reason, exit, log, &stderr_tail(tail));
    let diagnostic = data_dir.join("logs").join("startup-error.txt");
    if std::fs::write(&diagnostic, format!("{message}\n")).is_ok() {
        message.push_str(&format!("; diagnostic: {}", diagnostic.display()));
    }
    message
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
    let log_path = log_dir.join(format!("sidecar-{}.stderr.log", child.id()));
    let tail = child
        .stderr
        .take()
        .map(|stderr| capture_stderr(stderr, log_path.clone()));
    let Some(stdout) = child.stdout.take() else {
        let message = sidecar_failure(
            "sidecar stdout is unavailable",
            &mut child,
            &log_path,
            &tail,
            &data_dir,
        );
        let _ = child.kill();
        let _ = child.wait();
        remove_endpoint(&data_dir);
        return Err(message);
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
            let message = sidecar_failure(
                "sidecar did not report readiness within 30 seconds",
                &mut child,
                &log_path,
                &tail,
                &data_dir,
            );
            let _ = child.kill();
            let _ = child.wait();
            remove_endpoint(&data_dir);
            return Err(message);
        }
        match receiver.recv_timeout(deadline - now) {
            Ok(line) => {
                if let Ok(ready) = parse_ready_line(&line) {
                    break connection_info("127.0.0.1", ready.port, &token);
                }
            }
            Err(_) => {
                let message = sidecar_failure(
                    "sidecar closed before readiness",
                    &mut child,
                    &log_path,
                    &tail,
                    &data_dir,
                );
                let _ = child.kill();
                let _ = child.wait();
                remove_endpoint(&data_dir);
                return Err(message);
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
    let message = sidecar_failure(
        "sidecar health check did not become ready",
        &mut child,
        &log_path,
        &tail,
        &data_dir,
    );
    let _ = child.kill();
    let _ = child.wait();
    remove_endpoint(&data_dir);
    clear_connection(&state);
    Err(message)
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
            let Some(delay) = next_restart_delay(&state) else {
                state.paused.store(true, Ordering::SeqCst);
                let _ = app.emit("sidecar-failed", "restart limit reached");
                continue;
            };
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
            let Some(delay) = next_restart_delay(&state) else {
                state.paused.store(true, Ordering::SeqCst);
                let _ = app.emit("sidecar-failed", "restart limit reached");
                continue;
            };
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
        if supervisor::restarts_settled(
            stable_since.elapsed(),
            state.restarts.load(Ordering::SeqCst),
        ) {
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
                        if supervisor::health_escalated(health_failures) {
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
    for step in supervisor::SHUTDOWN_STEPS {
        match step {
            ShutdownStep::RequestShutdown => {
                if let Ok(guard) = state.connection.lock() {
                    if let Some(connection) = guard.as_ref() {
                        post_shutdown(connection);
                    }
                }
            }
            ShutdownStep::TerminateChild => {
                let mut child = state.child.lock().ok().and_then(|mut guard| guard.take());
                if let Some(child) = child.as_mut() {
                    await_child_exit(child);
                }
            }
            ShutdownStep::RemoveEndpoint => {
                if let Some(data_dir) = state.data_dir.lock().ok().and_then(|guard| guard.clone()) {
                    remove_endpoint(&data_dir);
                }
            }
        }
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

fn restart_sidecar_inner(app: &AppHandle) -> Result<ConnectionInfo, String> {
    let state = app.state::<SidecarState>();
    if state.stopping.load(Ordering::SeqCst) {
        return Err("sidecar is stopping".to_string());
    }
    state.restart_in_progress.store(true, Ordering::SeqCst);
    state.manual_restart.store(true, Ordering::SeqCst);
    state.paused.store(false, Ordering::SeqCst);
    state.restarts.store(0, Ordering::SeqCst);
    kill_child(&state);
    clear_connection(&state);
    let result = start_sidecar_inner(app, true);
    state.restart_in_progress.store(false, Ordering::SeqCst);
    if let Ok(connection) = &result {
        let _ = app.emit("sidecar-ready", connection);
    }
    result
}

#[tauri::command]
fn restart_sidecar(app: AppHandle) -> Result<ConnectionInfo, String> {
    restart_sidecar_inner(&app)
}

#[tauri::command]
fn open_data_dir(app: AppHandle) -> Result<String, String> {
    let data_dir = app
        .path()
        .app_local_data_dir()
        .map_err(|error| format!("data directory is unavailable: {error}"))?;
    std::fs::create_dir_all(&data_dir)
        .map_err(|error| format!("cannot create data directory: {error}"))?;
    open_directory(data_dir.as_os_str())?;
    Ok(data_dir.to_string_lossy().into_owned())
}

#[tauri::command]
fn open_external_url(url: String) -> Result<String, String> {
    let target = normalize_external_url(&url)?;
    system_open(OsStr::new(&target))?;
    Ok(target)
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
            if let Err(error) = setup_tray(app.handle()) {
                eprintln!("tray setup failed: {error}");
            }
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
            shutdown_sidecar,
            open_data_dir,
            open_external_url
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
        assert!(supervisor::is_success_status("HTTP/1.1 200 OK"));
        assert!(supervisor::is_success_status("HTTP/1.0 200"));
        assert!(!supervisor::is_success_status("HTTP/1.1 503 Service Unavailable"));
    }

    #[test]
    fn parses_connection_ports() {
        assert_eq!(supervisor::parse_port("http://127.0.0.1:43210"), Some(43210));
        assert_eq!(supervisor::parse_port("not-a-url"), None);
    }

    #[test]
    fn restart_backoff_is_bounded() {
        let delays = (1..=supervisor::MAX_RESTARTS)
            .filter_map(supervisor::restart_delay_ms)
            .collect::<Vec<_>>();
        assert_eq!(delays, vec![500, 1000, 2000]);
        assert_eq!(supervisor::restart_delay_ms(0), None);
        assert_eq!(supervisor::restart_delay_ms(supervisor::MAX_RESTARTS + 1), None);
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
        assert_eq!(phase(&state), Phase::Stopped);
        assert!(should_start(&state));
        assert!(start_allowed(&state, true));
        state.stopping.store(true, Ordering::SeqCst);
        assert_eq!(phase(&state), Phase::Stopping);
        assert!(!should_start(&state));
        assert!(!start_allowed(&state, true));
        state.stopping.store(false, Ordering::SeqCst);
        state.paused.store(true, Ordering::SeqCst);
        assert_eq!(phase(&state), Phase::Failed);
        assert!(!should_start(&state));
        assert!(start_allowed(&state, true));
        state.paused.store(false, Ordering::SeqCst);
        state.restart_in_progress.store(true, Ordering::SeqCst);
        assert_eq!(phase(&state), Phase::Starting);
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
        let temporary = agent.join("endpoint.json.tmp");
        std::fs::write(&endpoint, "secret").unwrap();
        std::fs::write(&temporary, "secret").unwrap();
        remove_endpoint(&data_dir);
        assert!(!endpoint.exists());
        assert!(!temporary.exists());
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
    fn tray_menu_ids_are_distinct() {
        let ids = [TRAY_SHOW, TRAY_HIDE, TRAY_RESTART, TRAY_QUIT];
        for (index, id) in ids.iter().enumerate() {
            assert!(!id.is_empty());
            assert!(!ids[index + 1..].contains(id));
        }
    }

    #[test]
    fn external_urls_require_http_or_https() {
        assert_eq!(
            normalize_external_url(" https://github.com/SeverusZh/fm-tactics-lab ").unwrap(),
            "https://github.com/SeverusZh/fm-tactics-lab"
        );
        assert_eq!(
            normalize_external_url("HTTP://127.0.0.1:1420/health").unwrap(),
            "HTTP://127.0.0.1:1420/health"
        );
        assert!(normalize_external_url("").is_err());
        assert!(normalize_external_url("https:// example.com").is_err());
        assert!(normalize_external_url("https://").is_err());
        assert!(normalize_external_url("javascript:alert(1)").is_err());
        assert!(normalize_external_url("file:///etc/passwd").is_err());
        assert!(normalize_external_url("ftp://example.com/file").is_err());
        assert!(normalize_external_url("https://user:secret@example.com/").is_err());
        assert!(normalize_external_url("https://example.com/<calc").is_err());
        assert!(normalize_external_url("https://example.com/|calc").is_err());
        assert!(normalize_external_url("https://example.com/\"calc").is_err());
        assert!(normalize_external_url("https://example.com/`calc").is_err());
        assert!(normalize_external_url("https://example.com/?a=1&b=2").is_ok());
    }

    #[test]
    fn sidecar_failure_keeps_exit_code_log_and_diagnostic() {
        let data_dir =
            std::env::temp_dir().join(format!("fm27lab-diagnostic-{}", std::process::id()));
        std::fs::create_dir_all(data_dir.join("logs")).unwrap();
        let log_path = data_dir.join("logs").join("sidecar-1.stderr.log");
        std::fs::write(&log_path, "boom\n").unwrap();
        let mut command = if cfg!(windows) {
            let mut command = Command::new("cmd");
            command.args(["/C", "exit", "3"]);
            command
        } else {
            let mut command = Command::new("sh");
            command.args(["-c", "exit 3"]);
            command
        };
        let mut child = command.spawn().unwrap();
        let _ = child.wait();
        let tail = Some(std::sync::Arc::new(std::sync::Mutex::new(
            std::collections::VecDeque::from(vec!["first".to_string(), "boom".to_string()]),
        )));
        let message = sidecar_failure(
            "sidecar closed before readiness",
            &mut child,
            &log_path,
            &tail,
            &data_dir,
        );
        assert!(message.contains("exit code 3"), "{message}");
        assert!(message.contains("sidecar-1.stderr.log"), "{message}");
        assert!(message.contains("last stderr: first | boom"), "{message}");
        let diagnostic =
            std::fs::read_to_string(data_dir.join("logs").join("startup-error.txt")).unwrap();
        assert!(diagnostic.contains("sidecar closed before readiness"));
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
