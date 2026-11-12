#[derive(Debug, Clone)]
pub struct Backoff {
    base_ms: u64,
    attempts: usize,
    cap_ms: u64,
}

impl Backoff {
    pub fn new(base_ms: u64, attempts: usize) -> Self {
        Self {
            base_ms,
            attempts,
            cap_ms: 60_000,
        }
    }

    pub fn delays(&self) -> Vec<u64> {
        let mut value = self.base_ms;
        let mut delays = Vec::with_capacity(self.attempts);
        for _ in 0..self.attempts {
            delays.push(value);
            value = value.saturating_mul(2).min(self.cap_ms);
        }
        delays
    }
}
