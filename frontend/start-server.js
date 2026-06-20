#!/usr/bin/env node

const fs = require("fs");
const path = require("path");

const root = __dirname;
const standaloneDir = path.join(root, ".next", "standalone");
const serverEntry = path.join(standaloneDir, "server.js");

// With `output: "standalone"` (see next.config.ts), `next build` produces a
// minimal server bundle that does NOT include the static assets or the public/
// folder. If they are missing, every /_next/static/* chunk 404s and the app
// renders a blank page. So we sync them into the standalone tree on each start
// — no manual `cp -r` needed, and it always matches the latest build.
function syncDir(src, dest) {
  if (!fs.existsSync(src)) return;
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.rmSync(dest, { recursive: true, force: true });
  fs.cpSync(src, dest, { recursive: true });
}

if (!fs.existsSync(serverEntry)) {
  console.error(
    "[start-server] .next/standalone/server.js not found.\n" +
      "Run `npm run build` first to produce the production build.",
  );
  process.exit(1);
}

// Copy static assets and the public folder into the standalone output.
syncDir(
  path.join(root, ".next", "static"),
  path.join(standaloneDir, ".next", "static"),
);
syncDir(path.join(root, "public"), path.join(standaloneDir, "public"));

// Default to the frontend port used by this deployment; override with PORT=...
if (!process.env.PORT) {
  process.env.PORT = "3675";
}

console.log(`[start-server] Starting Next.js standalone server on port ${process.env.PORT}`);

// Start the Next.js standalone server
require(serverEntry);
