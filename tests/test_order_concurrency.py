from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import Book, Member, Order, OrderItem, OrderStatus
from app.schemas import OrderCreate
from app.services.orders import create_order


def test_concurrent_last_copy_allows_only_one_order():
    with TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "concurrency.db"

        engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={
                "check_same_thread": False,
                "timeout": 10,
            },
        )

        Base.metadata.create_all(engine)

        SessionLocal = sessionmaker(
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
        )

        with SessionLocal() as db:
            book = Book(
                title="Last Copy Book",
                author="Concurrency Author",
                isbn="9780000000017",
                price_cents=1000,
                stock=1,
                restricted=False,
            )

            first_member = Member(
                name="First Buyer",
                email="first@concurrency.test",
                tier="apprentice",
                created_at=datetime(2026, 1, 1, 12, 0, 0),
            )

            second_member = Member(
                name="Second Buyer",
                email="second@concurrency.test",
                tier="apprentice",
                created_at=datetime(2026, 1, 1, 12, 0, 0),
            )

            db.add_all([
                book,
                first_member,
                second_member,
            ])
            db.commit()

            book_id = book.id
            first_member_id = first_member.id
            second_member_id = second_member.id

        def attempt_order(member_id: int):
            with SessionLocal() as db:
                try:
                    order = create_order(
                        db,
                        OrderCreate(
                            member_id=member_id,
                            items=[
                                {
                                    "book_id": book_id,
                                    "quantity": 1,
                                }
                            ],
                        ),
                        datetime(2026, 1, 1, 12, 0, 0),
                    )

                    return ("success", order.id)

                except HTTPException as exc:
                    return ("error", exc.status_code)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    attempt_order,
                    first_member_id,
                ),
                executor.submit(
                    attempt_order,
                    second_member_id,
                ),
            ]

            results = [future.result() for future in futures]

        assert sum(
            result[0] == "success"
            for result in results
        ) == 1

        assert sum(
            result == ("error", 409)
            for result in results
        ) == 1

        with SessionLocal() as db:
            book = db.get(Book, book_id)

            assert book is not None
            assert book.stock == 0

            order_items = db.scalars(
                select(OrderItem).where(
                    OrderItem.book_id == book_id
                )
            ).all()

            assert len(order_items) == 1

            order = db.get(
                Order,
                order_items[0].order_id,
            )

            assert order is not None
            assert order.status == OrderStatus.PENDING.value

        engine.dispose()