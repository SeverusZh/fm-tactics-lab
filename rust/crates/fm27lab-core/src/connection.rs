use serde::Serialize;

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct ConnectionInfo {
    pub url: String,
    pub token: String,
    pub api: String,
}

pub fn connection_info(host: &str, port: u16, token: &str) -> ConnectionInfo {
    ConnectionInfo {
        url: format!("http://{host}:{port}"),
        token: token.to_owned(),
        api: "fm27lab/v2".to_owned(),
    }
}

pub fn health_url(base_url: &str) -> String {
    format!("{}/api/health", base_url.trim_end_matches('/'))
}

impl ConnectionInfo {
    pub fn to_json(&self) -> String {
        serde_json::to_string(self).expect("serializing ConnectionInfo cannot fail")
    }
}
