"""Book catalogue operations."""
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Book
from app.schemas import BookCreate, BookPage, BookSort, BookUpdate


def create_book(db: Session, data: BookCreate) -> Book:
    """Add a book to the catalogue.

    Rules: the normalized ISBN must be unique -> 409 otherwise.
    """
    existing = db.scalar(
        select(Book).where(Book.isbn == data.isbn)
    )

    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="ISBN already exists",
        )

    book = Book(**data.model_dump())
    db.add(book)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="ISBN already exists",
        )

    db.refresh(book)
    return book


def get_book(db: Session, book_id: int) -> Book:
    """Return a book by id, or raise 404."""
    book = db.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return book


def update_book(db: Session, book_id: int, data: BookUpdate) -> Book:
    """Apply a partial update. Only explicitly provided fields are changed."""
    book = get_book(db, book_id)

    for field in data.model_fields_set:
        setattr(book, field, getattr(data, field))

    db.commit()
    db.refresh(book)

    return book


def list_books(
    db: Session,
    q: Optional[str] = None,
    restricted: Optional[bool] = None,
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
    sort: Optional[BookSort] = None,
    limit: int = 20,
    offset: int = 0,
) -> BookPage:
    """Search, filter, sort, and paginate the catalogue."""
    query = select(Book)

    # Search title OR author, case-insensitively.
    if q:
        pattern = f"%{q}%"
        query = query.where(
            Book.title.ilike(pattern) | Book.author.ilike(pattern)
        )

    # Filters.
    if restricted is not None:
        query = query.where(Book.restricted == restricted)

    if min_price is not None:
        query = query.where(Book.price_cents >= min_price)

    if max_price is not None:
        query = query.where(Book.price_cents <= max_price)

    # Sorting.
    if sort == "title":
        query = query.order_by(
            Book.title.asc(),
            Book.id.asc(),
        )
    elif sort == "-title":
        query = query.order_by(
            Book.title.desc(),
            Book.id.asc(),
        )
    elif sort == "price":
        query = query.order_by(
            Book.price_cents.asc(),
            Book.id.asc(),
        )
    elif sort == "-price":
        query = query.order_by(
            Book.price_cents.desc(),
            Book.id.asc(),
        )
    else:
        query = query.order_by(Book.id.asc())

    # Count BEFORE pagination.
    total = (
        db.scalar(
            select(func.count())
            .select_from(query.order_by(None).subquery())
        )
        or 0
    )

    # Apply pagination only after calculating total.
    books = db.scalars(
        query.limit(limit).offset(offset)
    ).all()

    return BookPage(
        items=books,
        total=total,
        limit=limit,
        offset=offset,
    )