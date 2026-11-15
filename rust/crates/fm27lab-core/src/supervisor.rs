//! Pure decisions for supervising the sidecar process.

use crate::backoff::Backoff;
use std::{
    path::{Path, PathBuf},
    time::Duration,
};

/// Automatic restart attempts allowed before the supervisor pauses.
pub const MAX_RESTARTS: usize = 3;
const RESTART_BASE_MS: u64 = 500;
/// Consecutive failed health probes that force a restart.
pub const HEALTH_FAILURE_LIMIT: usize = 3;
/// Uptime after which the restart counter is cleared.
pub const STABLE_WINDOW_MS: u64 = 30_000;

/// Lifecycle position of the supervised sidecar.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Phase {
    /// No live child; eligible for an automatic start.
    Stopped,
    /// A start or restart is in progress.
    Starting,
    /// A child process is alive.
    Running,
    /// Shutdown has begun.
    Stopping,
    /// Restarts are exhausted or suspended; only a manual restart starts the sidecar.
    Failed,
}

/// Whether a start is allowed; automatic starts require a stopped sidecar, manual restarts are only refused during shutdown.
pub fn start_allowed(phase: Phase, allow_restart: bool) -> bool {
    if allow_restart {
        phase != Phase::Stopping
    } else {
        phase == Phase::Stopped
    }
}

/// Delay before the given 1-based restart attempt, or `None` once the attempt budget is exhausted.
pub fn restart_delay_ms(attempt: usize) -> Option<u64> {
    if attempt == 0 || attempt > MAX_RESTARTS {
        return None;
    }
    Backoff::new(RESTART_BASE_MS, MAX_RESTARTS)
        .delays()
        .get(attempt - 1)
        .copied()
}

/// Whether consecutive health failures reached the restart threshold.
pub fn health_escalated(failures: usize) -> bool {
    failures >= HEALTH_FAILURE_LIMIT
}

/// Whether uptime is long enough to clear the restart counter.
pub fn restarts_settled(elapsed: Duration, restarts: usize) -> bool {
    restarts > 0 && elapsed > Duration::from_millis(STABLE_WINDOW_MS)
}

/// Health classification of a probe.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Health {
    Healthy,
    Unhealthy,
}

impl Health {
    pub fn is_healthy(self) -> bool {
        matches!(self, Self::Healthy)
    }
}

/// Classify a probe response: a missing status line and any non-200 status are unhealthy.
pub fn classify_health(status_line: Option<&str>) -> Health {
    match status_line {
        Some(line) if is_success_status(line) => Health::Healthy,
        _ => Health::Unhealthy,
    }
}

/// Whether a status line carries the given code as its own token.
pub fn status_matches(status_line: &str, code: &str) -> bool {
    status_line.contains(&format!(" {code} ")) || status_line.ends_with(&format!(" {code}"))
}

pub fn is_success_status(status_line: &str) -> bool {
    status_matches(status_line, "200")
}

pub fn is_shutdown_accepted(status_line: &str) -> bool {
    status_matches(status_line, "202")
}

/// Port of a connection URL; `None` when the URL carries no valid port.
pub fn parse_port(url: &str) -> Option<u16> {
    url.rsplit_once(':')?.1.parse().ok()
}

/// Files removed when the endpoint handshake file is cleaned up.
pub fn endpoint_paths(data_dir: &Path) -> [PathBuf; 2] {
    let endpoint = data_dir.join("agent").join("endpoint.json");
    let temporary = endpoint.with_extension("json.tmp");
    [endpoint, temporary]
}

/// Health probe request for a local sidecar.
pub fn probe_request(port: u16, token: &str, request_path: &str) -> String {
    format!(
        "GET {request_path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nAuthorization: Bearer {token}\r\nConnection: close\r\n\r\n"
    )
}

/// Shutdown request for a local sidecar.
pub fn shutdown_request(port: u16, token: &str) -> String {
    format!(
        "POST /api/shutdown HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nAuthorization: Bearer {token}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
    )
}

/// A step of the sidecar shutdown sequence.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ShutdownStep {
    RequestShutdown,
    TerminateChild,
    RemoveEndpoint,
}

/// Shutdown order: notify the sidecar, terminate the child, then drop the endpoint file.
pub const SHUTDOWN_STEPS: [ShutdownStep; 3] = [
    ShutdownStep::RequestShutdown,
    ShutdownStep::TerminateChild,
    ShutdownStep::RemoveEndpoint,
];
