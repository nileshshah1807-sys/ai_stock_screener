// A minimal Chrome DevTools Protocol client: launches the Chrome already on the
// machine headless and speaks to it over its WebSocket (Node's global
// WebSocket), so the smoke check needs no browser package.
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const CHROME_PATHS = [
  process.env.CHROME_PATH,
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
].filter(Boolean);

export async function launchChrome() {
  const chrome = CHROME_PATHS.find((path) => existsSync(path));
  if (!chrome) throw new Error("No Chrome found; set CHROME_PATH.");
  const profile = mkdtempSync(join(tmpdir(), "smoke-chrome-"));
  const proc = spawn(
    chrome,
    ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "--no-first-run", "--disable-gpu", "about:blank"],
    { stdio: ["ignore", "ignore", "pipe"] },
  );
  const endpoint = await new Promise((resolve, reject) => {
    let log = "";
    proc.stderr.on("data", (chunk) => {
      log += chunk;
      const found = log.match(/ws:\/\/\S+/);
      if (found) resolve(found[0]);
    });
    proc.on("exit", () => reject(new Error("Chrome exited before it was ready.")));
    setTimeout(() => reject(new Error("Chrome did not start in 15 s.")), 15000);
  });
  const socket = new WebSocket(endpoint);
  await new Promise((resolve, reject) => {
    socket.onopen = resolve;
    socket.onerror = () => reject(new Error("Could not connect to Chrome."));
  });

  let nextId = 0;
  const pending = new Map();
  const listeners = new Set();
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.id === undefined) return listeners.forEach((listener) => listener(message));
    const call = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) call.reject(new Error(`${call.method}: ${message.error.message}`));
    else call.resolve(message.result);
  };
  const send = (method, params = {}, sessionId) =>
    new Promise((resolve, reject) => {
      const id = ++nextId;
      pending.set(id, { resolve, reject, method });
      socket.send(JSON.stringify({ id, method, params, sessionId }));
    });

  const { targetId } = await send("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
  return {
    send: (method, params) => send(method, params, sessionId),
    // Events of the one page only.
    on: (listener) => {
      const wrapped = (message) => message.sessionId === sessionId && listener(message);
      listeners.add(wrapped);
      return () => listeners.delete(wrapped);
    },
    close: async () => {
      socket.close();
      const exited = new Promise((resolve) => proc.once("exit", resolve));
      proc.kill();
      await exited; // Chrome writes to the profile until it is gone
      rmSync(profile, { recursive: true, force: true, maxRetries: 5 });
    },
  };
}
