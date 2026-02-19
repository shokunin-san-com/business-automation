/**
 * Auth utilities for client and server components.
 */

/**
 * Check if user is authenticated (client-side).
 * Returns session or null.
 */
export async function getServerSession() {
  // Dynamic import to avoid issues during build
  const { getServerSession: getSession } = await import("next-auth");
  return getSession();
}
