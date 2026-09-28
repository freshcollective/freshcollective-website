"""Creator CRUD for discount codes.

Registered against the shared ``creator.routes.router`` as a side effect
of import, the same way ``_space_payment_options_routes`` is, and guarded
the same way: ``get_creator_user`` establishes a Creator, and
``_get_managed_space`` establishes that this Creator manages *this*
Collective. Every query is then scoped by ``space.id``, so another
Collective's code is not refused — it is simply not found, which is the
convention the Payment Option routes already use and the reason a
refusal cannot confirm that someone else's code exists.

What may be edited depends on whether the code has been redeemed. Before
the first redemption a code is a draft and anything about it may change.
After it, the *definition* is frozen — code, type, value, scope — because
the Creator has made a promise somebody has acted on. Operational fields
(active, expiry, maximum) stay editable, because they say what happens
next rather than what already happened.

Redemption counts are read from ``discount_redemptions``, the ledger.
``DiscountCode.redemption_count`` is a denormalised cache that redemption
fulfilment will maintain; nothing here reads it, so the two cannot drift
into meaning different things.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from fastapi import Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.creator.routes import (
    _get_managed_space,
    get_creator_user,
    router,
)
from app.creator.schemas import (
    DiscountCodeCreateRequest,
    DiscountCodeResponse,
    DiscountCodeUpdateRequest,
)
from app.models.discount_code import DiscountCode, DiscountRedemption
from app.services.discount_pricing import (
    expiry_date_in_timezone,
    resolve_expiry_instant,
)
from app.models.payment_option import PaymentOption
from app.models.user import User

#: Fields frozen once a code has been redeemed. Scope is included
#: deliberately — see the module docstring and the Work Item 2 report.
FROZEN_AFTER_REDEMPTION: tuple[str, ...] = (
    "code", "discount_type", "percent_bps", "amount_cents", "currency",
    "scope_kind", "scope_id",
)


class _Merged:
    """Attribute access over the merged patch, so the validator reads the
    same way whether it is handed a row or a dict."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def _uid() -> str:
    return f"dc_{uuid4().hex[:12]}"


def _redemption_count(db: Session, code_id: str) -> int:
    """From the ledger, never from the cached column."""
    return (
        db.query(func.count(DiscountRedemption.id))
        .filter(DiscountRedemption.discount_code_id == code_id)
        .scalar()
    ) or 0


def _get_code_or_404(db: Session, space, code_id: str) -> DiscountCode:
    """Scoped by Collective, so another Creator's code reads as absent."""
    row = (
        db.query(DiscountCode)
        .filter(DiscountCode.id == code_id, DiscountCode.space_id == space.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Discount code not found.")
    return row


def _resolve_scope_option(db: Session, space, scope_id: str) -> PaymentOption:
    """A scoped code may only name a Payment Option in its own Collective.

    400 rather than 404: the request is malformed, not the code missing —
    matching how the Payment Option routes report a Pathway or Series
    that does not belong to the Collective.
    """
    option = (
        db.query(PaymentOption)
        .filter(PaymentOption.id == scope_id, PaymentOption.space_id == space.id)
        .first()
    )
    if not option:
        raise HTTPException(
            status_code=400,
            detail="Payment Option not found in this Collective.",
        )
    return option


def _to_response(db: Session, row: DiscountCode, space=None) -> DiscountCodeResponse:
    redeemed = _redemption_count(db, row.id)
    tz_name = getattr(space, "timezone", None)
    if tz_name is None:
        from app.models.platform import Space
        tz_name = (
            db.query(Space.timezone).filter(Space.id == row.space_id).scalar()
        )
    option_name = None
    if row.scope_kind == "payment_option" and row.scope_id:
        option_name = (
            db.query(PaymentOption.name)
            .filter(PaymentOption.id == row.scope_id)
            .scalar()
        )
    return DiscountCodeResponse(
        id=row.id,
        space_id=row.space_id,
        code=row.code,
        discount_type=row.discount_type,
        percent_bps=row.percent_bps,
        amount_cents=row.amount_cents,
        currency=row.currency,
        scope_kind=row.scope_kind,
        scope_id=row.scope_id,
        scope_payment_option_name=option_name,
        is_active=row.is_active,
        expires_on=expiry_date_in_timezone(row.expires_at, tz_name),
        expires_at=row.expires_at,
        max_redemptions=row.max_redemptions,
        redemption_count=redeemed,
        definition_editable=(redeemed == 0),
        deletable=(redeemed == 0),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _reject_duplicate(db: Session, space, code: str, exclude_id: str | None = None):
    """Uniqueness is per Collective. 409, because the request is
    well-formed and the conflict is with existing state."""
    q = db.query(DiscountCode).filter(
        DiscountCode.space_id == space.id, DiscountCode.code == code,
    )
    if exclude_id:
        q = q.filter(DiscountCode.id != exclude_id)
    if q.first():
        raise HTTPException(
            status_code=409,
            detail=f"You already have a discount code called {code}.",
        )


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

@router.get(
    "/spaces/{slug}/discount-codes",
    response_model=list[DiscountCodeResponse],
    summary="List this Collective's discount codes",
)
def list_discount_codes(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[DiscountCodeResponse]:
    space = _get_managed_space(slug, current_user, db)
    rows = (
        db.query(DiscountCode)
        .filter(DiscountCode.space_id == space.id)
        .order_by(DiscountCode.created_at.desc())
        .all()
    )
    return [_to_response(db, r, space) for r in rows]


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

@router.post(
    "/spaces/{slug}/discount-codes",
    response_model=DiscountCodeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a discount code",
)
def create_discount_code(
    slug: str,
    body: DiscountCodeCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> DiscountCodeResponse:
    space = _get_managed_space(slug, current_user, db)

    # The request schema has already canonicalised the code and checked
    # its shape; these are the two rules that need the Collective.
    _reject_duplicate(db, space, body.code)
    if body.scope_kind == "payment_option":
        _resolve_scope_option(db, space, body.scope_id)

    row = DiscountCode(
        id=_uid(),
        space_id=space.id,
        code=body.code,
        discount_type=body.discount_type,
        percent_bps=body.percent_bps,
        amount_cents=body.amount_cents,
        currency=body.currency,
        scope_kind=body.scope_kind,
        scope_id=body.scope_id,
        is_active=body.is_active,
        # The Creator chose a day; the Collective's timezone decides when
        # that day ends. Never the browser's.
        expires_at=resolve_expiry_instant(body.expires_on, space.timezone),
        max_redemptions=body.max_redemptions,
        redemption_count=0,
        created_by_user_id=current_user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_response(db, row, space)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

@router.get(
    "/spaces/{slug}/discount-codes/{code_id}",
    response_model=DiscountCodeResponse,
    summary="Read one discount code",
)
def get_discount_code(
    slug: str,
    code_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> DiscountCodeResponse:
    space = _get_managed_space(slug, current_user, db)
    return _to_response(db, _get_code_or_404(db, space, code_id), space)


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

@router.patch(
    "/spaces/{slug}/discount-codes/{code_id}",
    response_model=DiscountCodeResponse,
    summary="Update a discount code",
)
def update_discount_code(
    slug: str,
    code_id: str,
    body: DiscountCodeUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> DiscountCodeResponse:
    space = _get_managed_space(slug, current_user, db)
    row = _get_code_or_404(db, space, code_id)
    redeemed = _redemption_count(db, row.id)
    supplied = body.model_dump(exclude_unset=True)

    # ── Frozen once somebody has acted on the promise ────────────────
    if redeemed:
        blocked = [f for f in FROZEN_AFTER_REDEMPTION if f in supplied]
        if blocked:
            raise HTTPException(
                status_code=409,
                detail=(
                    "This code has been redeemed, so its definition can no "
                    f"longer change ({', '.join(sorted(blocked))}). You can "
                    "deactivate it or adjust its expiry and limit instead."
                ),
            )

    # ── A limit cannot be set below what has already been used ───────
    if "max_redemptions" in supplied and supplied["max_redemptions"] is not None:
        if supplied["max_redemptions"] < 1:
            raise HTTPException(
                status_code=422, detail="Maximum redemptions must be at least 1.",
            )
        if supplied["max_redemptions"] < redeemed:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"This code has already been redeemed {redeemed} times, "
                    "so the maximum cannot be lower than that."
                ),
            )

    # ── Definition edits, only reachable before the first redemption ──
    if "code" in supplied and supplied["code"] != row.code:
        _reject_duplicate(db, space, supplied["code"], exclude_id=row.id)

    merged_kind = supplied.get("scope_kind", row.scope_kind)
    merged_scope_id = supplied.get("scope_id", row.scope_id)
    if "scope_kind" in supplied or "scope_id" in supplied:
        if merged_kind == "payment_option":
            if not merged_scope_id:
                raise HTTPException(
                    status_code=422,
                    detail="Choose the Payment Option this code applies to.",
                )
            _resolve_scope_option(db, space, merged_scope_id)
        elif merged_kind == "space":
            merged_scope_id = None
        else:
            raise HTTPException(
                status_code=422, detail="Scope must be 'space' or 'payment_option'.",
            )

    # Validate the MERGED values BEFORE touching the row. A patch sending
    # only ``discount_type`` would otherwise leave a percentage code
    # carrying an amount — and since the rejection happens after the
    # mutation, the next query's autoflush would hit the database CHECK
    # instead of the message a Creator can act on.
    writable = (
        "code", "discount_type", "percent_bps", "amount_cents", "currency",
        "max_redemptions", "is_active",
    )
    merged = {f: supplied.get(f, getattr(row, f)) for f in writable}
    _validate_merged_value_shape(merged)

    for field in writable:
        if field in supplied:
            setattr(row, field, supplied[field])
    if "expires_on" in supplied:
        row.expires_at = resolve_expiry_instant(supplied["expires_on"], space.timezone)
    if "scope_kind" in supplied or "scope_id" in supplied:
        row.scope_kind = merged_kind
        row.scope_id = merged_scope_id

    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return _to_response(db, row, space)


def _validate_merged_value_shape(row: dict) -> None:
    """Takes the merged values, not the ORM row — so a rejection leaves
    nothing dirty in the session."""
    from app.services.discount_pricing import MAX_PERCENT_BPS

    row = _Merged(**row)
    if row.discount_type == "percentage":
        if row.amount_cents is not None:
            raise HTTPException(
                status_code=422,
                detail="A percentage code cannot also carry an amount.",
            )
        if row.percent_bps is None or not 1 <= row.percent_bps <= MAX_PERCENT_BPS:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Percentage must be between 0.01% and "
                    f"{MAX_PERCENT_BPS / 100:g}%."
                ),
            )
    elif row.discount_type == "fixed_amount":
        if row.percent_bps is not None:
            raise HTTPException(
                status_code=422,
                detail="A fixed-amount code cannot also carry a percentage.",
            )
        if row.amount_cents is None or row.amount_cents <= 0:
            raise HTTPException(
                status_code=422,
                detail="A fixed-amount code needs an amount above zero.",
            )
        if not row.currency:
            raise HTTPException(
                status_code=422, detail="A fixed-amount code needs a currency.",
            )
    else:
        raise HTTPException(
            status_code=422,
            detail="Discount type must be 'percentage' or 'fixed_amount'.",
        )


# ---------------------------------------------------------------------------
# Activate / deactivate — the everyday action, given its own verb
# ---------------------------------------------------------------------------

@router.post(
    "/spaces/{slug}/discount-codes/{code_id}/activate",
    response_model=DiscountCodeResponse,
    summary="Reactivate a discount code",
)
def activate_discount_code(
    slug: str,
    code_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> DiscountCodeResponse:
    return _set_active(db, slug, code_id, current_user, active=True)


@router.post(
    "/spaces/{slug}/discount-codes/{code_id}/deactivate",
    response_model=DiscountCodeResponse,
    summary="Deactivate a discount code",
)
def deactivate_discount_code(
    slug: str,
    code_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> DiscountCodeResponse:
    return _set_active(db, slug, code_id, current_user, active=False)


def _set_active(
    db: Session, slug: str, code_id: str, current_user: User, *, active: bool,
) -> DiscountCodeResponse:
    """Always permitted, redeemed or not — it is the alternative to
    deleting, so refusing it would leave a redeemed code no way to stop."""
    space = _get_managed_space(slug, current_user, db)
    row = _get_code_or_404(db, space, code_id)
    row.is_active = active
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return _to_response(db, row, space)


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@router.delete(
    "/spaces/{slug}/discount-codes/{code_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a discount code that has never been redeemed",
)
def delete_discount_code(
    slug: str,
    code_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
    row = _get_code_or_404(db, space, code_id)

    # A redeemed code is part of somebody's purchase history. The
    # transaction carries its own frozen snapshot, so deleting the
    # definition would not corrupt the record — but it would remove the
    # Creator's own view of what they offered, and the ledger row with
    # it (the FK cascades). Deactivation is the reversible answer.
    if _redemption_count(db, row.id):
        raise HTTPException(
            status_code=409,
            detail=(
                "This code has been redeemed and is part of your purchase "
                "history. Deactivate it instead so it can no longer be used."
            ),
        )

    db.delete(row)
    db.commit()
