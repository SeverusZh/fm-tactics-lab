use fm27lab_core::supervisor::{
    classify_health, endpoint_paths, exit_code_label, health_escalated, is_shutdown_accepted,
    is_success_status, parse_port, probe_request, restart_delay_ms, restarts_settled,
    shutdown_request, start_allowed, startup_failure, status_matches, Health, Phase, ShutdownStep,
    HEALTH_FAILURE_LIMIT, MAX_RESTARTS, SHUTDOWN_STEPS, STABLE_WINDOW_MS, STDERR_TAIL_LINES,
};
use std::path::Path;
use std::time::Duration;

const AUTOMATIC: bool = false;
const MANUAL: bool = true;

#[test]
fn automatic_start_needs_a_stopped_sidecar() {
    assert!(start_allowed(Phase::Stopped, AUTOMATIC));
    for phase in [Phase::Starting, Phase::Running, Phase::Failed] {
        assert!(
            !start_allowed(phase, AUTOMATIC),
            "{phase:?} must not start automatically"
        );
    }
    assert!(!start_allowed(Phase::Stopping, AUTOMATIC));
}

#[test]
fn manual_restart_overrides_every_phase_except_shutdown() {
    assert!(start_allowed(Phase::Stopped, MANUAL));
    for phase in [Phase::Starting, Phase::Running, Phase::Failed] {
        assert!(
            start_allowed(phase, MANUAL),
            "{phase:?} must accept a manual restart"
        );
    }
    assert!(!start_allowed(Phase::Stopping, MANUAL));
}

#[test]
fn restart_delays_follow_bounded_exponential_backoff() {
    let delays: Vec<u64> = (1..=MAX_RESTARTS).filter_map(restart_delay_ms).collect();
    assert_eq!(delays, vec![500, 1_000, 2_000]);
    assert_eq!(delays.len(), MAX_RESTARTS);
    assert!(delays.windows(2).all(|pair| pair[0] < pair[1]));
    assert_eq!(restart_delay_ms(MAX_RESTARTS + 1), None);
    assert_eq!(restart_delay_ms(0), None);
}

#[test]
fn health_classification_accepts_only_200() {
    assert_eq!(classify_health(Some("HTTP/1.1 200 OK")), Health::Healthy);
    assert!(classify_health(Some("HTTP/1.0 200")).is_healthy());
    assert_eq!(classify_health(None), Health::Unhealthy);
    assert_eq!(
        classify_health(Some("HTTP/1.1 503 Service Unavailable")),
        Health::Unhealthy
    );
    assert_eq!(classify_health(Some("HTTP/1.1 204 No Content")), Health::Unhealthy);
    assert_eq!(classify_health(Some("")), Health::Unhealthy);
}

#[test]
fn status_matching_requires_a_whole_code() {
    assert!(status_matches("HTTP/1.1 202 Accepted", "202"));
    assert!(status_matches("HTTP/1.1 202", "202"));
    assert!(!status_matches("HTTP/1.1 2020 Accepted", "202"));
    assert!(!status_matches("HTTP/1.1 1202 Accepted", "202"));
    assert!(is_success_status("HTTP/1.1 200 OK"));
    assert!(is_success_status("HTTP/1.0 200"));
    assert!(!is_success_status("HTTP/1.1 2000 OK"));
    assert!(!is_success_status("HTTP/1.1 503 Service Unavailable"));
    assert!(is_shutdown_accepted("HTTP/1.1 202 Accepted"));
    assert!(!is_shutdown_accepted("HTTP/1.1 200 OK"));
}

#[test]
fn health_failures_escalate_at_the_limit() {
    assert!(!health_escalated(0));
    assert!(!health_escalated(HEALTH_FAILURE_LIMIT - 1));
    assert!(health_escalated(HEALTH_FAILURE_LIMIT));
    assert!(health_escalated(HEALTH_FAILURE_LIMIT + 1));
}

#[test]
fn restarts_settle_only_after_a_stable_window() {
    let window = Duration::from_millis(STABLE_WINDOW_MS);
    assert!(!restarts_settled(window, 1));
    assert!(restarts_settled(window + Duration::from_millis(1), 1));
    assert!(!restarts_settled(window + Duration::from_millis(1), 0));
}

#[test]
fn parses_ports_from_connection_urls() {
    assert_eq!(parse_port("http://127.0.0.1:43210"), Some(43210));
    assert_eq!(parse_port("http://127.0.0.1:1"), Some(1));
    assert_eq!(parse_port("http://127.0.0.1"), None);
    assert_eq!(parse_port("http://127.0.0.1:70000"), None);
    assert_eq!(parse_port("not-a-url"), None);
    assert_eq!(parse_port(""), None);
}

#[test]
fn endpoint_cleanup_targets_the_handshake_files() {
    let data_dir = Path::new("/data/fm27lab");
    let paths = endpoint_paths(data_dir);
    assert_eq!(paths[0], data_dir.join("agent").join("endpoint.json"));
    assert_eq!(paths[1], data_dir.join("agent").join("endpoint.json.tmp"));
}

#[test]
fn health_probe_request_carries_the_bearer_token() {
    let request = probe_request(43210, "secret", "/api/health");
    assert!(request.starts_with("GET /api/health HTTP/1.1\r\n"));
    assert!(request.contains("Host: 127.0.0.1:43210\r\n"));
    assert!(request.contains("Authorization: Bearer secret\r\n"));
    assert!(request.ends_with("\r\n\r\n"));
}

#[test]
fn shutdown_request_posts_an_empty_body() {
    let request = shutdown_request(43211, "secret");
    assert!(request.starts_with("POST /api/shutdown HTTP/1.1\r\n"));
    assert!(request.contains("Host: 127.0.0.1:43211\r\n"));
    assert!(request.contains("Authorization: Bearer secret\r\n"));
    assert!(request.contains("Content-Length: 0\r\n"));
    assert!(request.ends_with("\r\n\r\n"));
}

#[test]
fn shutdown_sequence_notifies_before_cleanup() {
    assert_eq!(
        SHUTDOWN_STEPS,
        [
            ShutdownStep::RequestShutdown,
            ShutdownStep::TerminateChild,
            ShutdownStep::RemoveEndpoint,
        ]
    );
}
#[test]
fn startup_failure_keeps_exit_code_log_and_tail() {
    let tail = vec![
        "first".to_string(),
        "  second  ".to_string(),
        "".to_string(),
    ];
    let message = startup_failure(
        "sidecar closed before readiness",
        Some(-1073741515),
        Some(Path::new("/data/logs/sidecar-7.stderr.log")),
        &tail,
    );
    assert!(message.starts_with("sidecar closed before readiness (exit code 0xC0000135)"));
    assert!(message.contains("stderr log: /data/logs/sidecar-7.stderr.log"));
    assert!(message.contains("last stderr: first | second"));
    assert!(!message.contains(" |  |"));
}

#[test]
fn startup_failure_without_exit_or_log_stays_readable() {
    let message = startup_failure("sidecar did not report readiness", None, None, &[]);
    assert_eq!(
        message,
        "sidecar did not report readiness (exit code unknown)"
    );
    assert_eq!(exit_code_label(Some(3)), "3");
    assert_eq!(exit_code_label(None), "unknown");
}

#[test]
fn startup_failure_truncates_each_line() {
    let long = "x".repeat(400);
    let tail = vec![long, "".to_string(), "short".to_string()];
    let message = startup_failure("failure", Some(1), None, &tail);
    assert!(message.contains(&"x".repeat(300)));
    assert!(!message.contains(&"x".repeat(301)));
    assert!(message.contains(" | short"));
    assert!(!message.contains(" |  |"));
}

#[test]
fn startup_failure_keeps_only_the_last_lines() {
    let tail: Vec<String> = (0..20).map(|index| format!("line-{index}")).collect();
    let message = startup_failure("failure", Some(1), None, &tail);
    assert!(!message.contains("line-11"));
    assert_eq!(message.matches("line-").count(), STDERR_TAIL_LINES);
}
