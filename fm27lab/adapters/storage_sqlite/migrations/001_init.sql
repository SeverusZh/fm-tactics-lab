CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  note TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS saves (
  id TEXT PRIMARY KEY,
  source_path TEXT NOT NULL,
  source_sha256 TEXT NOT NULL,
  status TEXT NOT NULL,
  stage TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS saves_sha256 ON saves(source_sha256);

CREATE TABLE IF NOT EXISTS save_leagues (
  save_id TEXT NOT NULL,
  league_key TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  PRIMARY KEY (save_id, league_key),
  FOREIGN KEY (save_id) REFERENCES saves(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS save_clubs (
  save_id TEXT NOT NULL,
  club_uid INTEGER NOT NULL,
  payload_json TEXT NOT NULL,
  PRIMARY KEY (save_id, club_uid),
  FOREIGN KEY (save_id) REFERENCES saves(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  status TEXT NOT NULL,
  name TEXT,
  config_json TEXT NOT NULL,
  summary_json TEXT NOT NULL DEFAULT '{}',
  workers INTEGER NOT NULL DEFAULT 1,
  total INTEGER NOT NULL DEFAULT 0,
  completed INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);
CREATE INDEX IF NOT EXISTS jobs_status_created ON jobs(status, created_at);

CREATE TABLE IF NOT EXISTS job_runs (
  job_id TEXT NOT NULL,
  sequence INTEGER NOT NULL,
  variant TEXT NOT NULL,
  seed INTEGER NOT NULL,
  score_home INTEGER,
  score_away INTEGER,
  verified INTEGER NOT NULL DEFAULT 0,
  stats_json TEXT NOT NULL DEFAULT '{}',
  events_json TEXT,
  log_path TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY (job_id, sequence),
  FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS drafts (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  scenario_json TEXT NOT NULL,
  source_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pool_entries (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  weight INTEGER NOT NULL DEFAULT 1,
  tactic_json TEXT NOT NULL,
  roster_json TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
  id TEXT PRIMARY KEY,
  job_id TEXT,
  kind TEXT NOT NULL,
  path TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  bytes INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS idempotency (
  key TEXT PRIMARY KEY,
  request_hash TEXT NOT NULL,
  response_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
