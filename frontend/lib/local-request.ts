// The host names the proxy answers to. A Host header is chosen by whoever sends the request, so
// it is compared with this list, and the Origin is compared with it too.
const LOCAL_HOSTNAMES = new Set(["127.0.0.1", "localhost", "[::1]"]);

function hostnameOf(url: string): string | null {
  try {
    return new URL(url).hostname;
  } catch {
    return null;
  }
}

export function isLocalRequest(host: string | null, origin: string | null): boolean {
  const hostname = host === null ? null : hostnameOf(`http://${host}`);
  if (hostname === null || !LOCAL_HOSTNAMES.has(hostname)) return false;
  if (origin === null) return true;
  const originHostname = hostnameOf(origin);
  return originHostname !== null && LOCAL_HOSTNAMES.has(originHostname);
}
