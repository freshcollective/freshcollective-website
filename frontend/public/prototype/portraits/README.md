# Mock portrait assets — Ways to Connect prototype

Local abstract portrait SVGs used by the Ways to Connect
prototype (`frontend/src/app/ways-to-connect/_prototype/`).

Deliberately **not photographs of people**. Deliberately not
identifying: no faces, no silhouettes readable as a particular
gender or age or ethnicity. Just soft atmospheric compositions
so the prototype can demonstrate the "photo" render state
alongside the "initial fallback" state without any avatar
service inferring identity from a mock name.

Real member profile photos replace these 1:1 when the
introduction recommendation service goes live. Delete this
folder when the prototype is retired.

Each portrait pairs with a mock member in
`mockIntroductions.ts`. Pairings are hand-assigned there and
stay stable across every render state (introduction cards,
incoming invitation, accepted conversation intro panel).
