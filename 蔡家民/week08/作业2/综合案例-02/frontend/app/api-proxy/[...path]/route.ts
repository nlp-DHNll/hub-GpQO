import { NextRequest } from "next/server";

const API = process.env.API_INTERNAL_URL || "http://127.0.0.1:8000";

async function forward(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const target = `${API}/${path.join("/")}${request.nextUrl.search}`;
  const headers = new Headers();
  for (const name of ["content-type", "cookie", "accept"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const body = ["GET", "HEAD"].includes(request.method) ? undefined : await request.arrayBuffer();
  const upstream = await fetch(target, { method: request.method, headers, body, cache: "no-store", redirect: "manual" });
  const responseHeaders = new Headers();
  for (const name of ["content-type", "content-disposition", "set-cookie", "cache-control", "x-accel-buffering"]) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
}

export const GET = forward;
export const POST = forward;
export const DELETE = forward;
