SCHEMA_VERSION = 2
SCHEMA_ID = "publishing-workspace.catalog/v2"

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS schema_meta (
    schema_id TEXT NOT NULL,
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS assets (
    asset_id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE,
    size INTEGER NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    image_format TEXT NOT NULL,
    metadata_format TEXT NOT NULL,
    reader TEXT NOT NULL,
    warnings_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS asset_paths (
    path_key TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    asset_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
    size INTEGER NOT NULL,
    modified_ns INTEGER NOT NULL,
    available INTEGER NOT NULL DEFAULT 1,
    last_seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_asset_paths_asset ON asset_paths(asset_id);

CREATE TABLE IF NOT EXISTS asset_nodes (
    asset_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    node_index INTEGER NOT NULL,
    node_id TEXT NOT NULL DEFAULT '',
    ref TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (asset_id, role, node_index, node_id, ref)
);
CREATE INDEX IF NOT EXISTS idx_asset_nodes_role ON asset_nodes(role, node_id);

CREATE TABLE IF NOT EXISTS imports (
    import_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    source_fingerprint TEXT,
    mode TEXT NOT NULL,
    strict INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    pipeline_stage TEXT NOT NULL,
    total_items INTEGER NOT NULL DEFAULT 0,
    planned_items INTEGER NOT NULL DEFAULT 0,
    processed_items INTEGER NOT NULL DEFAULT 0,
    reused_path_items INTEGER NOT NULL DEFAULT 0,
    reused_content_items INTEGER NOT NULL DEFAULT 0,
    parsed_new_items INTEGER NOT NULL DEFAULT 0,
    missing_items INTEGER NOT NULL DEFAULT 0,
    failed_items INTEGER NOT NULL DEFAULT 0,
    held_problem_items INTEGER NOT NULL DEFAULT 0,
    warnings_json TEXT NOT NULL,
    error_json TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS import_items (
    import_id TEXT NOT NULL REFERENCES imports(import_id) ON DELETE CASCADE,
    source_order INTEGER NOT NULL,
    source_path TEXT NOT NULL,
    resolved_path TEXT,
    display_name TEXT NOT NULL,
    observed_size INTEGER,
    observed_modified_ns INTEGER,
    decision TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    asset_id TEXT REFERENCES assets(asset_id),
    problem_id TEXT,
    warnings_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (import_id, source_order)
);
CREATE INDEX IF NOT EXISTS idx_import_items_asset ON import_items(asset_id);
CREATE INDEX IF NOT EXISTS idx_import_items_status ON import_items(import_id, status, source_order);

CREATE TABLE IF NOT EXISTS import_problems (
    problem_id TEXT PRIMARY KEY,
    import_id TEXT NOT NULL REFERENCES imports(import_id) ON DELETE CASCADE,
    source_order INTEGER NOT NULL,
    path_key TEXT,
    source_path TEXT NOT NULL,
    error_code TEXT NOT NULL,
    message TEXT NOT NULL,
    observed_size INTEGER,
    observed_modified_ns INTEGER,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_import_problems_fingerprint
ON import_problems(status, path_key, observed_size, observed_modified_ns);

CREATE TABLE IF NOT EXISTS workspace_locks (
    lock_name TEXT PRIMARY KEY,
    owner_run_id TEXT NOT NULL,
    owner_token TEXT NOT NULL,
    lease_expires_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS classification_profiles (
    profile_hash TEXT PRIMARY KEY,
    hierarchy_json TEXT NOT NULL,
    missing_value TEXT NOT NULL,
    skip_missing INTEGER NOT NULL,
    builder_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS asset_view_memberships (
    profile_hash TEXT NOT NULL,
    asset_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
    view_key TEXT NOT NULL,
    view_path_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (profile_hash, asset_id, view_key)
);

CREATE TABLE IF NOT EXISTS export_states (
    exporter TEXT NOT NULL,
    view_key TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    outputs_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (exporter, view_key)
);

CREATE TABLE IF NOT EXISTS asset_marks (
    asset_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
    mark TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (asset_id, mark)
);
CREATE INDEX IF NOT EXISTS idx_asset_marks_mark ON asset_marks(mark);
"""
