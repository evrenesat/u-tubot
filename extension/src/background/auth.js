/**
 * The bearer token goes only to the stored backend: the same scheme, host and port, and a target path under the
 * backend's path. A prefix of the text is not enough. No token, no header.
 */

function segments(url) {
  return url.pathname.split("/").filter(Boolean);
}

export function stripTrailingSlash(address) {
  const value = (address ?? "").trim();
  return value.endsWith("/") ? value.slice(0, -1) : value;
}

export function isUnderBackend(baseUrl, absoluteUrl) {
  if (!absoluteUrl) {
    return false;
  }

  let base;
  let target;

  try {
    base = new URL(stripTrailingSlash(baseUrl));
    target = new URL(absoluteUrl.trim());
  } catch {
    return false;
  }

  if (base.protocol !== target.protocol || base.hostname.toLowerCase() !== target.hostname.toLowerCase() || base.port !== target.port) {
    return false;
  }

  const basePath = segments(base);
  const targetPath = segments(target);

  if (targetPath.length < basePath.length) {
    return false;
  }

  return targetPath.slice(0, basePath.length).every((segment, index) => segment === basePath[index]);
}

export function authorizationFor(baseUrl, token, absoluteUrl) {
  const bearer = (token ?? "").trim();

  if (!bearer || !isUnderBackend(baseUrl, absoluteUrl)) {
    return null;
  }

  return `Bearer ${bearer}`;
}
