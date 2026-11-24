/**
 * Host-permission helpers. `permissions.request` runs only directly inside a click handler (never after an await);
 * a refused request stores nothing.
 */
import { permissionsContains, permissionsRemove, permissionsRequest } from "../shared/api.js";

export function hasOrigins(origins) {
  return permissionsContains(origins);
}

export function requestOrigins(origins) {
  return permissionsRequest(origins);
}

export function removeOrigins(origins) {
  return permissionsRemove(origins);
}
