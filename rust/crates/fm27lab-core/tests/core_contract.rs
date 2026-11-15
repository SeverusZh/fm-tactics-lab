use fm27lab_core::backoff::Backoff;
use fm27lab_core::connection::{connection_info, health_url};
use fm27lab_core::ready::{parse_ready_line, ReadyError};
use fm27lab_core::token::generate_token;

#[test]
fn parses_only_ready_events() {
    let ready = parse_ready_line("{\"event\":\"ready\",\"port\":54321,\"pid\":42}").unwrap();
    assert_eq!(ready.port, 54321);
    assert_eq!(ready.pid, Some(42));
    assert!(matches!(
        parse_ready_line("{\"event\":\"log\",\"message\":\"x\"}"),
        Err(ReadyError::NotReady)
    ));
    assert!(matches!(
        parse_ready_line("not json"),
        Err(ReadyError::InvalidJson)
    ));
    assert!(matches!(
        parse_ready_line("{\"event\":\"ready\",\"port\":0}"),
        Err(ReadyError::InvalidPort)
    ));
}

#[test]
fn tokens_are_64_hex_characters_and_unique() {
    let first = generate_token().unwrap();
    let second = generate_token().unwrap();
    assert_eq!(first.len(), 64);
    assert!(first.chars().all(|c| c.is_ascii_hexdigit()));
    assert_ne!(first, second);
}

#[test]
fn backoff_delays_are_bounded_and_deterministic() {
    let delays = Backoff::new(500, 4).delays();
    assert_eq!(delays, vec![500, 1000, 2000, 4000]);
    assert_eq!(Backoff::new(1000, 0).delays(), Vec::<u64>::new());
}

#[test]
fn connection_info_and_health_url_are_explicit() {
    let info = connection_info("127.0.0.1", 43210, "abc123");
    assert_eq!(info.url, "http://127.0.0.1:43210");
    assert_eq!(info.api, "fm27lab/v2");
    assert_eq!(health_url(&info.url), "http://127.0.0.1:43210/api/health");
    assert!(info.to_json().contains("\"token\":\"abc123\""));
    let debug = format!("{info:?}");
    assert!(!debug.contains("abc123"));
    assert!(debug.contains("redacted"));
}
