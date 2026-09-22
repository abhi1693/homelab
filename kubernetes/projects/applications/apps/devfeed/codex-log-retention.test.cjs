const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { DatabaseSync } = require("node:sqlite");
const test = require("node:test");
const { retain, maintain, cleanupLegacy, MAX_ROWS, MAX_BYTES, MAX_AGE_SECONDS } = require("./codex-log-retention.cjs");

function fixture(t) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "devfeed-log-retention-"));
  const filename = path.join(directory, "logs_2.sqlite");
  const db = new DatabaseSync(filename);
  db.exec(`PRAGMA journal_mode=WAL;
    CREATE TABLE logs (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL,
      level TEXT NOT NULL, feedback_log_body TEXT, estimated_bytes INTEGER NOT NULL DEFAULT 0);
    CREATE INDEX idx_logs_ts ON logs(ts DESC);
    CREATE TABLE _sqlx_migrations(version INTEGER PRIMARY KEY);
    INSERT INTO _sqlx_migrations VALUES (1);`);
  t.after(() => { db.close(); fs.rmSync(directory, { recursive: true, force: true }); });
  return { directory, filename, db, insert: db.prepare("INSERT INTO logs(ts,level,feedback_log_body,estimated_bytes) VALUES (?,?,?,?)") };
}

test("removes verbose and expired records while preserving recent operational logs and schema", (t) => {
  const { filename, db, insert } = fixture(t);
  const now = Math.floor(Date.now() / 1000);
  for (const level of ["DEBUG", "TRACE", "INFO", "WARN", "ERROR"]) insert.run(now, level, "message", 7);
  insert.run(now - MAX_AGE_SECONDS - 1, "ERROR", "old", 3);
  retain(filename, now);
  assert.deepEqual(db.prepare("SELECT level FROM logs ORDER BY id").all().map(r => r.level), ["INFO", "WARN", "ERROR"]);
  assert.equal(db.prepare("SELECT version FROM _sqlx_migrations").get().version, 1);
});

test("keeps the newest rows and reclaims physical space under the byte budget", (t) => {
  const { filename, db, insert } = fixture(t);
  const now = Math.floor(Date.now() / 1000);
  db.exec("BEGIN");
  for (let i = 0; i < MAX_ROWS + 50; i++) insert.run(now, "INFO", "small", 5);
  db.exec("COMMIT");
  retain(filename, now);
  assert.equal(db.prepare("SELECT COUNT(*) AS n FROM logs").get().n, MAX_ROWS);
  assert.equal(db.prepare("SELECT MIN(id) AS id FROM logs").get().id, 51);
  db.exec("BEGIN");
  // Deliberately incorrect estimates must not bypass the actual body-byte cap.
  for (let i = 0; i < 400; i++) insert.run(now, "WARN", "x".repeat(128 * 1024), 1);
  db.exec("COMMIT; PRAGMA wal_checkpoint(TRUNCATE)");
  assert.ok(fs.statSync(filename).size > 40 * 1024 * 1024);
  const result = retain(filename, now);
  assert.ok(db.prepare("SELECT SUM(length(CAST(feedback_log_body AS BLOB)) + 512) AS n FROM logs").get().n <= MAX_BYTES);
  assert.ok(result.bytes < 24 * 1024 * 1024);
  assert.equal(result.walBytes, 0);
});

test("a concurrent writer causes a bounded retry without deleting committed records", (t) => {
  const { filename, db, insert } = fixture(t);
  insert.run(Math.floor(Date.now() / 1000), "DEBUG", "message", 7);
  db.exec("BEGIN IMMEDIATE");
  assert.throws(() => retain(filename), /locked/);
  db.exec("ROLLBACK");
  assert.equal(db.prepare("SELECT COUNT(*) AS n FROM logs").get().n, 1);
  assert.equal(retain(filename).rows, 0);
});

test("maintenance and idempotent legacy cleanup preserve authentication and other state", (t) => {
  const { directory } = fixture(t);
  const preserved = ["auth.json", "config.toml", "state_5.sqlite", "models_cache.json"];
  for (const name of preserved) fs.writeFileSync(path.join(directory, name), "preserve exactly");
  maintain(directory);
  assert.ok(Number(fs.readFileSync(path.join(directory, ".retention-health"), "utf8")) > 0);
  // Use separate inactive legacy files; never unlink a database with live writers.
  const legacy = path.join(directory, "legacy");
  fs.mkdirSync(legacy);
  for (const name of [...preserved, "logs_2.sqlite", "logs_2.sqlite-wal", "logs_2.sqlite-shm"]) {
    fs.writeFileSync(path.join(legacy, name), "preserve exactly");
  }
  cleanupLegacy(legacy);
  cleanupLegacy(legacy);
  assert.deepEqual(fs.readdirSync(legacy).sort(), preserved.sort());
  for (const name of preserved) {
    assert.equal(fs.readFileSync(path.join(directory, name), "utf8"), "preserve exactly");
    assert.equal(fs.readFileSync(path.join(legacy, name), "utf8"), "preserve exactly");
  }
});
