"""Order operations: placing, paying and cancelling purchases."""
from datetime import datetime
from typing import Dict

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Book, Member, MemberTier, Order, OrderItem, OrderStatus
from app.schemas import OrderCreate
from app.services.members import ensure_can_access_restricted


# Percentage discount granted by each membership tier.
TIER_DISCOUNT_PERCENT: Dict[str, int] = {
    MemberTier.APPRENTICE.value: 0,
    MemberTier.ADEPT.value: 5,
    MemberTier.MASTER.value: 10,
    MemberTier.SUPREME.value: 15,
}

# Extra discount when the total quantity across all items reaches the threshold.
BULK_QUANTITY_THRESHOLD = 10
BULK_DISCOUNT_PERCENT = 5


def calculate_discount_percent(member: Member, total_quantity: int) -> int:
    """Return the combined membership and bulk discount percentage."""
    discount = TIER_DISCOUNT_PERCENT[member.tier]

    if total_quantity >= BULK_QUANTITY_THRESHOLD:
        discount += BULK_DISCOUNT_PERCENT

    return discount


def create_order(db: Session, data: OrderCreate, now: datetime) -> Order:
    """Place a pending order and reserve stock.

    Validation order:
    1. Schema handles empty items, invalid quantities, and duplicates.
    2. Member and all books must exist.
    3. Restricted books require master or higher.
    4. Every book must have sufficient stock.
    5. Only then are stock and order data changed.
    """
    
    # TODO:
    # 1. Load the member (404) and every book (404).
    # 2. If any book is restricted, check the member's tier (403).
    # 3. Check stock for every item before changing anything (409).
    # 4. Decrement stock and build OrderItems with the current price as unit_price_cents.
    # 5. Compute subtotal, discount_percent (calculate_discount_percent), discount_cents, total.
    # 6. Save the pending Order with created_at = now and return it.
    
    
    # 1. Member must exist.
    member = db.get(Member, data.member_id)

    if member is None:
        raise HTTPException(
            status_code=404,
            detail="Member not found",
        )

    # 2. Load every book before checking restrictions or stock.
    # This guarantees:
    # 404 missing book happens before 403 restricted-book checks.
    books: Dict[int, Book] = {}

    for item in data.items:
        book = db.get(Book, item.book_id)

        if book is None:
            raise HTTPException(
                status_code=404,
                detail="Book not found",
            )

        books[item.book_id] = book

    # 3. Check restricted-book access.
    # Do this before stock so a restricted + insufficient-stock request
    # returns 403, as required by the tests.
    for item in data.items:
        book = books[item.book_id]

        if book.restricted:
            ensure_can_access_restricted(member)

    # 4. Check ALL stock before modifying ANY stock.
    # This gives us the required all-or-nothing behavior.
    for item in data.items:
        book = books[item.book_id]

        if book.stock < item.quantity:
            raise HTTPException(
                status_code=409,
                detail=f"Insufficient stock for book {book.id}",
            )

    # 5. Calculate pricing using the current book prices.
    total_quantity = sum(item.quantity for item in data.items)

    subtotal_cents = 0

    order_items = []

    for item in data.items:
        book = books[item.book_id]

        line_total_cents = book.price_cents * item.quantity
        subtotal_cents += line_total_cents

        order_items.append(
            OrderItem(
                book_id=book.id,
                quantity=item.quantity,
                unit_price_cents=book.price_cents,
            )
        )

    discount_percent = calculate_discount_percent(
        member,
        total_quantity,
    )

    discount_cents = (
        subtotal_cents * discount_percent
    ) // 100

    total_cents = subtotal_cents - discount_cents

    # 6. Reserve stock.

    for item in data.items:
        book = books[item.book_id]
        book.stock -= item.quantity

    # 7. Create the order.

    order = Order(
        member_id=member.id,
        status=OrderStatus.PENDING.value,
        subtotal_cents=subtotal_cents,
        discount_percent=discount_percent,
        discount_cents=discount_cents,
        total_cents=total_cents,
        created_at=now,
    )

    for order_item in order_items:
        order.items.append(order_item)

    db.add(order)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(order)

    return order


def get_order(db: Session, order_id: int) -> Order:
    """Return an order by id, or raise 404."""
    order = db.get(Order, order_id)

    if order is None:
        raise HTTPException(
            status_code=404,
            detail="Order not found",
        )

    return order


def pay_order(db: Session, order_id: int) -> Order:
    """Mark a pending order as paid.

    Stock remains unchanged because it was already reserved at creation.
    """
    order = get_order(db, order_id)

    if order.status != OrderStatus.PENDING.value:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot pay an order that is {order.status}",
        )

    order.status = OrderStatus.PAID.value

    db.commit()
    db.refresh(order)

    return order


def cancel_order(db: Session, order_id: int) -> Order:
    """Cancel a pending order and restore all reserved stock."""
    order = get_order(db, order_id)

    if order.status != OrderStatus.PENDING.value:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel an order that is {order.status}",
        )

    # Restore the stock reserved by this order.
    for item in order.items:
        book = db.get(Book, item.book_id)

        if book is not None:
            book.stock += item.quantity

    order.status = OrderStatus.CANCELLED.value

    db.commit()
    db.refresh(order)

    return order