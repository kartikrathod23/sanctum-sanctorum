"""Library loan operations: borrowing and returning books."""
from datetime import datetime, timedelta
from math import ceil
from typing import Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Book, Loan, Member, MemberTier
from app.schemas import LoanCreate, LoanOut, LoanStatus
from app.services.members import ensure_can_access_restricted

# Maximum concurrent unreturned loans per tier (None = unlimited).
TIER_LOAN_LIMIT: Dict[str, Optional[int]] = {
    MemberTier.APPRENTICE.value: 1,
    MemberTier.ADEPT.value: 3,
    MemberTier.MASTER.value: 5,
    MemberTier.SUPREME.value: None,
}

LOAN_PERIOD = timedelta(days=14)
LATE_FEE_PER_DAY_CENTS = 25


def loan_status(loan: Loan, now: datetime) -> LoanStatus:
    """Compute the current status of a loan."""
    if loan.returned_at is not None:
        return "returned"

    if now > loan.due_at:
        return "overdue"

    return "active"


def to_loan_out(loan: Loan, now: datetime) -> LoanOut:
    """Serialize a loan, computing its status at read time."""
    return LoanOut(
        id=loan.id,
        member_id=loan.member_id,
        book_id=loan.book_id,
        borrowed_at=loan.borrowed_at,
        due_at=loan.due_at,
        returned_at=loan.returned_at,
        late_fee_cents=loan.late_fee_cents,
        status=loan_status(loan, now),
    )


def calculate_late_fee(
    due_at: datetime,
    returned_at: datetime,
    price_cents: int,
) -> int:
    """Calculate late fee at 25 cents per started late day, capped by book price."""
    if returned_at <= due_at:
        return 0

    elapsed = returned_at - due_at
    days_late = ceil(elapsed.total_seconds() / timedelta(days=1).total_seconds())

    return min(days_late * LATE_FEE_PER_DAY_CENTS, price_cents)


def create_loan(db: Session, data: LoanCreate, now: datetime) -> LoanOut:
    """Borrow a book for 14 days."""

    # 1. Member must exist.
    member = db.get(Member, data.member_id)
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")

    # 1. Book must exist.
    book = db.get(Book, data.book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    # 2. Restricted-book access check must happen before overdue/limit/stock.
    if book.restricted:
        ensure_can_access_restricted(member)

    # Fetch all unreturned loans for this member.
    active_loans = list(
        db.scalars(
            select(Loan).where(
                Loan.member_id == member.id,
                Loan.returned_at.is_(None),
            )
        )
    )

    # 3. Any overdue loan blocks new borrowing.
    if any(loan_status(loan, now) == "overdue" for loan in active_loans):
        raise HTTPException(
            status_code=409,
            detail="Member has an overdue loan",
        )

    # 4. Same book cannot be borrowed twice simultaneously.
    if any(loan.book_id == book.id for loan in active_loans):
        raise HTTPException(
            status_code=409,
            detail="Member already has this book on loan",
        )

    # 5. Check tier loan limit.
    limit = TIER_LOAN_LIMIT.get(member.tier)

    if limit is not None and len(active_loans) >= limit:
        raise HTTPException(
            status_code=409,
            detail="Member has reached their loan limit",
        )

    # 6. Check stock last.
    if book.stock <= 0:
        raise HTTPException(
            status_code=409,
            detail="Book is out of stock",
        )

    borrowed_at = now
    due_at = now + LOAN_PERIOD

    loan = Loan(
        member_id=member.id,
        book_id=book.id,
        borrowed_at=borrowed_at,
        due_at=due_at,
        returned_at=None,
        late_fee_cents=0,
    )

    book.stock -= 1

    db.add(loan)
    db.commit()
    db.refresh(loan)

    return to_loan_out(loan, now)


def get_loan(db: Session, loan_id: int, now: datetime) -> LoanOut:
    """Return a loan by id."""
    loan = db.get(Loan, loan_id)

    if loan is None:
        raise HTTPException(status_code=404, detail="Loan not found")

    return to_loan_out(loan, now)


def return_loan(db: Session, loan_id: int, now: datetime) -> LoanOut:
    """Return a borrowed book."""
    loan = db.get(Loan, loan_id)

    if loan is None:
        raise HTTPException(status_code=404, detail="Loan not found")

    if loan.returned_at is not None:
        raise HTTPException(
            status_code=409,
            detail="Loan has already been returned",
        )

    book = db.get(Book, loan.book_id)

    # Foreign key guarantees this normally exists, but keep the service safe.
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    loan.returned_at = now
    loan.late_fee_cents = calculate_late_fee(
        loan.due_at,
        now,
        book.price_cents,
    )

    book.stock += 1

    db.commit()
    db.refresh(loan)

    return to_loan_out(loan, now)


def list_member_loans(
    db: Session,
    member_id: int,
    now: datetime,
    status: Optional[LoanStatus] = None,
) -> List[LoanOut]:
    """List a member's loans ordered by id."""
    member = db.get(Member, member_id)

    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")

    loans = list(
        db.scalars(
            select(Loan)
            .where(Loan.member_id == member_id)
            .order_by(Loan.id)
        )
    )

    result = [to_loan_out(loan, now) for loan in loans]

    if status is not None:
        result = [loan for loan in result if loan.status == status]

    return result