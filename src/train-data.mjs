/** JSON transport for timetable snapshots, route shards and optional RailGo queries. */
export async function getJSON(url, timeout = 30000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(url, {
      signal: controller.signal,
      // Protected site assets need the current session. Cross-origin services
      // such as RailGo must not receive that session's credentials.
      credentials: 'same-origin',
      cache: 'no-cache',
    });
    if (!response.ok) {
      const error = new Error(`HTTP ${response.status}`);
      error.status = response.status;
      throw error;
    }
    // Keep the deadline active while the response body is being read, too.
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}
