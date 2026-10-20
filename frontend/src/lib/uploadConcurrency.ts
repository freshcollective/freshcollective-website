/**
 * A memory-proportionate concurrency gate for large proxied uploads.
 *
 * fc-web runs on Render Starter — 0.5 CPU, 512 MB — the same as fc-api.
 * Measured inside a hard 512 MB cgroup with the streaming proxy, peak
 * resident memory against ~158 MB idle:
 *
 *     1 concurrent 50 MB upload    232 MB
 *     2                            285 MB
 *     4                            395 MB
 *     6                            499 MB      ← 13 MB of headroom
 *
 * So roughly 57 MB per in-flight upload, and six at once is at the
 * cliff edge. fc-api caps its own concurrent uploads at two, but that
 * limit is applied *after* the body has arrived — fc-web has already
 * carried every stream by then, so fc-api's gate does nothing for
 * fc-web's memory. This is the gate that does.
 *
 * Why a size threshold rather than a path list
 * --------------------------------------------
 *
 * The thing being protected is memory, and memory cost tracks body
 * size, not which endpoint is being called. Gating on
 * ``Content-Length`` means a 40 MB Media Library video takes a slot and
 * a 200 KB avatar never waits — where a path list would have to be
 * extended every time an upload surface is added, and would be wrong
 * the first time somebody forgot.
 *
 * Deliberately per-process. Each instance protects its own heap, which
 * is the correct scaling behaviour for a memory guard: two instances
 * genuinely can carry two large uploads each.
 */

/** Bodies at or above this take a slot. Below it, memory is noise. */
export const LARGE_UPLOAD_BYTES = 8 * 1024 * 1024

/**
 * Total bytes the process will carry at once, beyond the first upload.
 *
 * A count alone is not enough, because streaming does not make memory
 * *constant* — measured at 512 MB, fc-web holds roughly 1.2x whatever
 * is in flight:
 *
 *     50 MB x1   232 MB      50 MB x2   286 MB      50 MB x4   395 MB
 *    250 MB x1   449 MB     250 MB x2   OOM
 *
 * Two concurrent 50 MB Offering files are comfortable; two concurrent
 * 250 MB Media Library videos are not. A budget expressed in bytes
 * distinguishes those two cases where "max 2" cannot.
 *
 * 120 MB covers two files at the Offerings ceiling with room to spare,
 * and refuses a second upload once a very large one is already running.
 */
export const IN_FLIGHT_BYTE_BUDGET = 120 * 1024 * 1024

/**
 * Simultaneous large uploads this process will carry.
 *
 * Two, matching fc-api's own ``MAX_CONCURRENT_UPLOADS`` and the
 * conservative ceiling agreed for launch. At 2 the measured peak is
 * 285 MB of 512 MB — a little over half the box, with the rest left for
 * ordinary request handling, which must not degrade because somebody is
 * uploading.
 */
export const MAX_CONCURRENT_LARGE_UPLOADS = 2

let inFlight = 0
let inFlightBytes = 0

/** Current occupancy. Exported for tests and diagnostics. */
export function largeUploadsInFlight(): number {
  return inFlight
}

/** Bytes currently being carried. Exported for tests. */
export function largeUploadBytesInFlight(): number {
  return inFlightBytes
}

/** Reset. Tests only — never called by request handling. */
export function resetLargeUploadGate(): void {
  inFlight = 0
  inFlightBytes = 0
}

/**
 * Does this request need a slot?
 *
 * An absent or unparseable ``Content-Length`` returns ``false``: the
 * header is client-supplied and a gate is not a security control. The
 * authoritative limits are fc-api's counting check and the
 * ``proxyClientMaxBodySize`` ceiling, both of which act on bytes that
 * actually arrive. This only has to catch the honest large upload,
 * which is every real one.
 */
/**
 * Is this body large enough to stream rather than buffer?
 *
 * The same threshold the concurrency gate uses, so "large" means one
 * thing. Below it the proxy buffers, which keeps an upstream's early
 * response (a 401, a 403, a validation error raised before the body is
 * read) working — streaming such a request makes the failed body write
 * reject the whole fetch and lose the response.
 */
export function isLargeBody(contentLength: string | null): boolean {
  if (!contentLength) return false
  const bytes = Number.parseInt(contentLength, 10)
  return Number.isFinite(bytes) && bytes >= LARGE_UPLOAD_BYTES
}

export function needsSlot(method: string, contentLength: string | null): boolean {
  const m = method.toUpperCase()
  if (m === 'GET' || m === 'HEAD') return false
  if (!contentLength) return false
  const bytes = Number.parseInt(contentLength, 10)
  return Number.isFinite(bytes) && bytes >= LARGE_UPLOAD_BYTES
}

/**
 * Take a slot, or refuse.
 *
 * Returns a release function on success and ``null`` when full. The
 * caller must release in a ``finally`` — a leaked slot would wedge
 * uploads until the process restarted.
 *
 * Non-blocking by design. Queueing would hold a request open while
 * occupying a connection, which is the opposite of shedding load.
 */
export function acquireLargeUploadSlot(bytes: number): (() => void) | null {
  if (inFlight >= MAX_CONCURRENT_LARGE_UPLOADS) return null
  // The first upload is always admitted, whatever its size. Refusing it
  // would mean a 250 MB video could never be uploaded at all, which is
  // a limit reduction by the back door — and one upload of any
  // permitted size has been measured to fit.
  if (inFlight > 0 && inFlightBytes + bytes > IN_FLIGHT_BYTE_BUDGET) {
    return null
  }
  inFlight += 1
  inFlightBytes += bytes
  let released = false
  return () => {
    if (released) return
    released = true
    inFlight -= 1
    inFlightBytes -= bytes
  }
}
