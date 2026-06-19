#!/usr/bin/env node
/**
 * Robust clean script for Next.js / Turbopack caches on Windows.
 *
 * Turbopack stores a RocksDB-style persistence database under
 * `.next/dev/cache/turbopack/`. When those files end up locked or
 * marked read-only (common after a crash / forced shutdown), the
 * naive `fs.rmSync` silently fails and `next dev` later crashes with:
 *   "Failed to open database ... Access is denied. (os error 5)"
 *
 * This script:
 *   1. Clears the read-only attribute on Windows before deleting.
 *   2. Retries deletion a few times (handles transient locks).
 *   3. Exits with a non-zero code (instead of swallowing the error)
 *      so `predev` actually stops `next dev` from running on a dirty
 *      cache instead of printing a fake "Cleaned" message.
 */
const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

const cwd = process.cwd();
const targets = [".next", "tsc_errors.txt"];

function clearReadOnly(target) {
  if (process.platform !== "win32") return;
  try {
    // Recursively clear the read-only attribute.
    execSync(`attrib -R "${target}\\*" /S /D`, { stdio: "ignore" });
  } catch {
    /* ignore — best effort */
  }
}

function remove(target) {
  if (!fs.existsSync(target)) return;
  clearReadOnly(target);
  fs.rmSync(target, { recursive: true, force: true, maxRetries: 3, retryDelay: 200 });
}

let failed = false;
for (const name of targets) {
  const target = path.join(cwd, name);
  try {
    remove(target);
  } catch (err) {
    failed = true;
    console.error(`Failed to remove ${name}: ${err && err.message ? err.message : err}`);
  }
}

if (failed) {
  console.error(
    "Clean failed. Close any running dev server / editor holding .next, then retry."
  );
  process.exit(1);
}

console.log("Cleaned .next cache");