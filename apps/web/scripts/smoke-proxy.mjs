import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { existsSync } from "node:fs";
import { createServer } from "node:http";
import { join, resolve } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";

const webRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const standaloneServer = join(webRoot, ".next", "standalone", "server.js");

const requestBody = async (request) => {
  const chunks = [];
  for await (const chunk of request) {
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
};

const backend = createServer(async (request, response) => {
  const url = new URL(request.url ?? "/", "http://proxy-smoke.local");

  if (url.pathname === "/api/json") {
    response.writeHead(200, {
      "content-type": "application/json",
      "x-proxy-smoke": "json",
    });
    response.end(JSON.stringify({ method: request.method, path: url.pathname, query: url.search }));
    return;
  }

  if (url.pathname === "/api/upload") {
    const body = await requestBody(request);
    response.writeHead(200, { "content-type": "application/json" });
    response.end(
      JSON.stringify({
        method: request.method,
        body: body.toString("utf8"),
        contentType: request.headers["content-type"],
      }),
    );
    return;
  }

  if (url.pathname === "/api/events") {
    response.writeHead(200, {
      "content-type": "text/event-stream",
      "cache-control": "no-cache",
    });
    response.flushHeaders();
    response.write("data: first\n\n");
    await delay(2_000);
    response.end("data: second\n\n");
    return;
  }

  if (url.pathname === "/api/download") {
    response.writeHead(200, {
      "content-type": "application/octet-stream",
      "content-disposition": 'attachment; filename="course.bin"',
    });
    response.end(Buffer.from([0, 1, 2, 254, 255]));
    return;
  }

  response.writeHead(404);
  response.end();
});

const listen = async (server) => {
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  assert(address && typeof address !== "string");
  return address.port;
};

const reservePort = async () => {
  const server = createServer();
  const port = await listen(server);
  server.close();
  await once(server, "close");
  return port;
};

const waitForProxy = async (baseUrl, child, logs) => {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`Standalone server exited early.\n${logs.join("")}`);
    }
    try {
      const response = await fetch(`${baseUrl}/api/json?ready=1`);
      if (response.ok) {
        return;
      }
    } catch {
      // The standalone server is still starting.
    }
    await delay(150);
  }
  throw new Error(`Timed out waiting for the standalone server.\n${logs.join("")}`);
};

if (!existsSync(standaloneServer)) {
  throw new Error("Run `npm run build` before `npm run test:proxy`.");
}

const backendPort = await listen(backend);
const frontendPort = await reservePort();
const logs = [];
const frontend = spawn(process.execPath, [standaloneServer], {
  cwd: webRoot,
  env: {
    ...process.env,
    API_URL: `http://127.0.0.1:${backendPort}`,
    HOSTNAME: "127.0.0.1",
    NODE_ENV: "production",
    PORT: String(frontendPort),
  },
  stdio: ["ignore", "pipe", "pipe"],
});
frontend.stdout.on("data", (chunk) => logs.push(chunk.toString()));
frontend.stderr.on("data", (chunk) => logs.push(chunk.toString()));

const baseUrl = `http://127.0.0.1:${frontendPort}`;

try {
  await waitForProxy(baseUrl, frontend, logs);

  const jsonResponse = await fetch(`${baseUrl}/api/json?course=security`);
  assert.equal(jsonResponse.status, 200);
  assert.equal(jsonResponse.headers.get("x-proxy-smoke"), "json");
  assert.deepEqual(await jsonResponse.json(), {
    method: "GET",
    path: "/api/json",
    query: "?course=security",
  });

  for (const method of ["POST", "PUT", "PATCH", "DELETE"]) {
    const uploadResponse = await fetch(`${baseUrl}/api/upload`, {
      method,
      headers: { "content-type": "application/octet-stream" },
      body: `body-${method.toLowerCase()}`,
    });
    assert.equal(uploadResponse.status, 200);
    assert.deepEqual(await uploadResponse.json(), {
      method,
      body: `body-${method.toLowerCase()}`,
      contentType: "application/octet-stream",
    });
  }

  const streamStartedAt = Date.now();
  const streamResponse = await fetch(`${baseUrl}/api/events`);
  assert.match(streamResponse.headers.get("content-type") ?? "", /^text\/event-stream/);
  assert(streamResponse.body);
  const reader = streamResponse.body.getReader();
  const firstChunk = await reader.read();
  assert.equal(firstChunk.done, false);
  assert.match(new TextDecoder().decode(firstChunk.value), /data: first/);
  assert(
    Date.now() - streamStartedAt < 1_500,
    "The first SSE event was buffered instead of being streamed.",
  );
  let remainingStream = "";
  for (;;) {
    const chunk = await reader.read();
    if (chunk.done) {
      break;
    }
    remainingStream += new TextDecoder().decode(chunk.value);
  }
  assert.match(remainingStream, /data: second/);

  const downloadResponse = await fetch(`${baseUrl}/api/download`);
  assert.equal(
    downloadResponse.headers.get("content-disposition"),
    'attachment; filename="course.bin"',
  );
  assert.deepEqual(
    Buffer.from(await downloadResponse.arrayBuffer()),
    Buffer.from([0, 1, 2, 254, 255]),
  );

  console.log("Standalone proxy smoke test passed.");
} finally {
  backend.close();
  await once(backend, "close");
  if (frontend.exitCode === null) {
    frontend.kill("SIGTERM");
    await Promise.race([once(frontend, "exit"), delay(5_000)]);
  }
  if (frontend.exitCode === null) {
    frontend.kill("SIGKILL");
  }
}
