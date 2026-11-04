// Content negotiation for the evidence pages (argus-claims 02-sa-service-map §5.1), in the landing's pattern
// (OneDro1d/onedroid-landing middleware.js): Routing Middleware on the Node.js runtime, no imports, the
// x-middleware-rewrite / x-middleware-next headers. It runs before the filesystem check, which is the only hook that can
// intercept a path cleanUrls already resolves to a .html file.
//
// Accept containing text/markdown -> the page's .md twin; containing application/json and not text/html -> its .json
// twin; everyone else, browsers and AI fetchers alike, gets the HTML. No user-agent rule (D-15; the landing dropped
// its own on 27 Oct 2026 after ChatGPT and Perplexity could not read a text/markdown page they were handed).
// Vary: Accept is set for every /evidence response in vercel.json.

export const config = {
  runtime: "nodejs",
  matcher: ["/evidence", "/evidence/:path*"],
};

// Twins, record files (every published one ends in .json, .jsonl, .md or .sha256) and the agent surfaces are served
// as they are.
const AS_IS = /\.(?:html|md|json|jsonl|txt|xml|sha256)$/;

// Continuing must be explicit on the Node.js runtime (the landing measured an empty 200 otherwise, 2026-09-13).
function passThrough() {
  return new Response(null, { headers: { "x-middleware-next": "1" } });
}

export default function middleware(request) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, "") || "/";
  if (!(path === "/evidence" || path.startsWith("/evidence/")) || AS_IS.test(path)) {
    return passThrough();
  }
  const accept = (request.headers.get("accept") || "").toLowerCase();
  let ext = null;
  if (accept.includes("text/markdown")) ext = ".md";
  else if (accept.includes("application/json") && !accept.includes("text/html")) ext = ".json";
  if (ext === null) return passThrough();
  const twin = (path === "/evidence" ? "/evidence/index" : path) + ext;
  return new Response(null, {
    headers: { "x-middleware-rewrite": new URL(twin, request.url).toString(), Vary: "Accept" },
  });
}
