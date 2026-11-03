/**
 * How a Gathering's location reads, in one place.
 *
 * Four fields, two audiences
 * --------------------------
 * The creator fills in up to four things, and the API decides which of
 * them a given viewer may have:
 *
 *   venue_name           Venue name — the name of the place. Public.
 *   venue_locality       Public address — whatever the creator is
 *                        comfortable showing everyone: a suburb, or a
 *                        full street address if they choose. Public.
 *   venue_address        Private address — optional, more specific,
 *                        and arriving only for a confirmed attendee or
 *                        a caretaker. `null` for everyone else, and
 *                        that gate is the server's, not this module's.
 *   access_instructions  Arrival instructions. Same gate, rendered
 *                        separately — never folded into the address.
 *
 * What this module decides is only *how the two or three strings a
 * viewer legitimately holds should read*. It cannot widen anything:
 * a private address it never receives is one it cannot print.
 *
 * Why it exists
 * -------------
 * The Gathering page used to render three consecutive lines — the
 * public address, then `venue_name`, then `venue_address` — and
 * because the API was overwriting `venue_name` with the public
 * address, the first two were frequently the same string. A creator
 * who had typed "Arrabri Community House" into the name and
 * "Arrabri Community House - 42 Allambanan Drive, Bayswater North"
 * into the public address saw the venue twice and the street once.
 *
 * One name, one address.
 */

export type AttendanceFormat = 'online' | 'in_person' | 'hybrid'

export interface GatheringLocationInput {
  attendanceFormat: AttendanceFormat | string | null | undefined
  /** `venue_name`. */
  venueName?: string | null
  /** `venue_locality` — the public address. */
  publicAddress?: string | null
  /**
   * `venue_address` — the private address. Pass exactly what the API
   * returned: `null` when the viewer is not entitled to it. Never
   * substitute the public address here; the fallback is below.
   */
  privateAddress?: string | null
}

export interface GatheringLocation {
  /** The venue's name, shown once, or `null`. */
  name: string | null
  /**
   * The one address line, or `null`. Already de-duplicated against
   * `name`, so rendering both never repeats.
   */
  address: string | null
  /**
   * True when `address` came from the private field *and* says
   * something the public address did not. Lets a surface mark the line
   * as attendee-only without comparing strings itself.
   */
  isPrivateAddress: boolean
  /** False when there is nothing to show — online, or nothing filled in. */
  hasLocation: boolean
}

function clean(value: string | null | undefined): string | null {
  const text = (value ?? '').trim().replace(/\s+/g, ' ')
  return text || null
}

/** Case- and punctuation-insensitive, for comparison only. */
function key(value: string): string {
  return value.toLowerCase().replace(/[.,·|–—-]/g, ' ').replace(/\s+/g, ' ').trim()
}

/**
 * The address with a leading repeat of the venue name removed.
 *
 * "Arrabri Community House - 42 Allambanan Drive" beside a venue named
 * "Arrabri Community House" becomes "42 Allambanan Drive".
 *
 * Deliberately narrow. The name must be a *leading* run of the address
 * and must be followed by a real separator — a comma, dash, pipe or
 * middot — never merely whitespace, because "Arrabri Community House
 * Hall" is a different place and not a repeat. Anything else is
 * returned whole: a partial overlap is not permission to delete
 * somebody's address.
 */
function withoutLeadingName(address: string, name: string): string {
  const a = key(address)
  const n = key(name)
  if (!n || !a.startsWith(n) || a === n) return address

  // Walk the original string to the same offset the normalised prefix
  // ends at, counting only characters that normalisation keeps.
  let consumed = 0
  let index = 0
  for (; index < address.length && consumed < n.length; index += 1) {
    const normalised = key(address.slice(0, index + 1))
    if (normalised.length > consumed) consumed = normalised.length
    if (consumed >= n.length) { index += 1; break }
  }
  const rest = address.slice(index)
  const separated = rest.match(/^\s*[,\-–—·|]+\s*(.+)$/)
  if (!separated) return address
  return separated[1].trim() || address
}

/**
 * Compose the location for one viewer.
 *
 * The private-address fallback lives here: when the creator left it
 * blank, a confirmed attendee is shown the public address rather than
 * nothing, so nobody has to type the same address twice. A blank
 * private address and one that merely repeats the public address are
 * treated the same *for display* — but only for display. Neither this
 * function nor anything downstream writes to the stored value.
 */
export function composeGatheringLocation(
  input: GatheringLocationInput,
): GatheringLocation {
  const empty: GatheringLocation = {
    name: null, address: null, isPrivateAddress: false, hasLocation: false,
  }
  if (input.attendanceFormat === 'online') return empty

  const name = clean(input.venueName)
  const publicAddress = clean(input.publicAddress)
  const privateAddress = clean(input.privateAddress)

  const chosen = privateAddress ?? publicAddress
  const isPrivateAddress = Boolean(
    privateAddress
    && (!publicAddress || key(privateAddress) !== key(publicAddress)),
  )

  let address = chosen
  if (address && name) {
    if (key(address) === key(name)) {
      // The address says only what the name already said.
      address = null
    } else {
      address = withoutLeadingName(address, name)
    }
  }

  return {
    name,
    address,
    isPrivateAddress: isPrivateAddress && address !== null,
    hasLocation: Boolean(name || address),
  }
}

/**
 * The one-line form, for a heading or a summary row.
 *
 * "In person · Arrabri Community House, 42 Allambanan Drive" — the
 * format first, then whatever of the location the viewer holds.
 */
export function gatheringLocationSummary(
  formatLabel: string,
  location: GatheringLocation,
): string {
  const parts = [location.name, location.address].filter(Boolean)
  return parts.length ? `${formatLabel} · ${parts.join(', ')}` : formatLabel
}
