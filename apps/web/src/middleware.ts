import { NextRequest, NextResponse } from "next/server";

const SESSION_COOKIE = "factory_session";
const PUBLIC_PATHS = new Set(["/login", "/privacy"]);

// Cheap presence check only — the API verifies the cookie signature on every
// request. This just keeps unauthenticated visitors out of app pages.
export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const hasSession = request.cookies.has(SESSION_COOKIE);
  const isPublicPath = PUBLIC_PATHS.has(pathname);

  if (!hasSession && !isPublicPath) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  if (hasSession && pathname === "/login") {
    return NextResponse.redirect(new URL("/", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
