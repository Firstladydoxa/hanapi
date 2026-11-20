import type { NextRequest } from "next/server";

/**
 * Same-origin proxy: the browser only ever talks to this app; the server forwards `/v1/*` to the backend.
 * HAN_BACKEND_URL is read at REQUEST time (a build-time rewrite would bake the URL into the image).
 * The backend, not this proxy, is the security control: cookies, CSRF headers and responses pass through unchanged.
 */
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const HOP_BY_HOP = new Set(["connection", "keep-alive", "transfer-encoding", "upgrade", "proxy-authenticate", "proxy-authorization", "te", "trailer", "host", "content-length", "content-encoding"]);
const FORWARD_REQUEST = ["cookie", "content-type", "x-csrf-token", "x-request-id", "accept", "accept-language", "user-agent"];

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }): Promise<Response> {
  const { path } = await ctx.params;
  const base = (process.env.HAN_BACKEND_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
  const target = `${base}/v1/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;

  const headers = new Headers();
  for (const name of FORWARD_REQUEST) {
    const v = req.headers.get(name);
    if (v) headers.set(name, v);
  }
  const forwarded = req.headers.get("x-forwarded-for");
  if (forwarded) headers.set("x-forwarded-for", forwarded);

  const hasBody = !["GET", "HEAD"].includes(req.method);
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers,
      body: hasBody ? await req.arrayBuffer() : undefined,
      redirect: "manual",
      cache: "no-store",
    });
  } catch {
    return Response.json({ detail: { code: "service_unavailable", message: "I'm sorry, I couldn't complete that at the moment. Please try again shortly." } }, { status: 503 });
  }

  const out = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase()) && key.toLowerCase() !== "set-cookie") out.set(key, value);
  });
  for (const cookie of upstream.headers.getSetCookie()) out.append("set-cookie", cookie);
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE };
