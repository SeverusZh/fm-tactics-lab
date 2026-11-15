use serde::Deserialize;
use std::fmt;

#[derive(Debug, Deserialize, PartialEq, Eq)]
pub struct ReadyMessage {
    pub port: u16,
    #[serde(default)]
    pub pid: Option<u32>,
}

#[derive(Debug, PartialEq, Eq)]
pub enum ReadyError {
    InvalidJson,
    NotReady,
    InvalidPort,
}

impl fmt::Display for ReadyError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidJson => write!(formatter, "ready line is not valid JSON"),
            Self::NotReady => write!(formatter, "line is not a ready event"),
            Self::InvalidPort => write!(formatter, "ready event has an invalid port"),
        }
    }
}

impl std::error::Error for ReadyError {}

pub fn parse_ready_line(line: &str) -> Result<ReadyMessage, ReadyError> {
    let value: serde_json::Value =
        serde_json::from_str(line).map_err(|_| ReadyError::InvalidJson)?;
    if value.get("event").and_then(|event| event.as_str()) != Some("ready") {
        return Err(ReadyError::NotReady);
    }
    let port = value
        .get("port")
        .and_then(|port| port.as_u64())
        .filter(|port| (1..=65_535).contains(port))
        .ok_or(ReadyError::InvalidPort)?;
    let pid = value
        .get("pid")
        .and_then(|pid| pid.as_u64())
        .map(|pid| pid.min(u32::MAX as u64) as u32);
    Ok(ReadyMessage {
        port: port as u16,
        pid,
    })
}
