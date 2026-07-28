SCHEMA_VERSION = 1
SCHEMA_ID = "publishing-workspace.catalog/v1"

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
    created_at TEXT NOT NULL,
    warnings_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS import_items (
    import_id TEXT NOT NULL REFERENCES imports(import_id) ON DELETE CASCADE,
    source_order INTEGER NOT NULL,
    source_path TEXT NOT NULL,
    resolved_path TEXT,
    display_name TEXT NOT NULL,
    asset_id TEXT REFERENCES assets(asset_id),
    status TEXT NOT NULL,
    warnings_json TEXT NOT NULL,
    PRIMARY KEY (import_id, source_order)
);
CREATE INDEX IF NOT EXISTS idx_import_items_asset ON import_items(asset_id);

CREATE TABLE IF NOT EXISTS export_states (
    exporter TEXT NOT NULL,
    view_key TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    outputs_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (exporter, view_key)
);
"""
