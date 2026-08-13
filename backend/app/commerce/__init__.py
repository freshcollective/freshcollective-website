"""Commerce module.

Home of the Payment Options architecture as it evolves from the
legacy polymorphic ``PaymentOption.attaches_to_*`` shape into the
Collective-level Option + multi-experience grants model.

B1 shipped the ``PaymentOptionGrant`` table.
B2 ships the idempotent backfill from legacy fields.
Later commits (B3+) will move runtime behaviour onto the grants.
"""
