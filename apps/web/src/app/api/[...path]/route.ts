import { NextRequest } from "next/server";

// Runtime proxy to the backend. Unlike next.config rewrites (whose target is
// baked into the standalone build), this reads API_URL when each request
// arrives, so the same image works locally (http://localhost:8000) and on any
// host (e.g. Sliplane internal networking) by just setting the env var.
function apiUrl(): string {
  return process.env.API_URL ?? "http://localhost:8000";
}

export const dynamic = "force-dynamic";

async function proxy(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  const search = new URL(request.url).search;
  const target = `${apiUrl()}/api/${path.join("/")}${search}`;

  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("connection");

  const hasBody = !["GET", "HEAD"].includes(request.method);
  const upstream = await fetch(target, {
    method: request.method,
    headers,
    body: hasBody ? request.body : undefined,
    // @ts-expect-error: Node fetch requires duplex for streamed request bodies
    duplex: "half",
    redirect: "manual",
    cache: "no-store",
  });

  const responseHeaders = new Headers(upstream.headers);
  responseHeaders.delete("content-encoding");
  responseHeaders.delete("content-length");
  responseHeaders.delete("transfer-encoding");

  // Streams SSE and file downloads through without buffering.
  return new Response(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

export {
  proxy as GET,
  proxy as POST,
  proxy as PUT,
  proxy as PATCH,
  proxy as DELETE,
};
