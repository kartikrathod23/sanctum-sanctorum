from datetime import timedelta


def place_order(client, member_id, *items):
    return client.post(
        "/orders",
        json={
            "member_id": member_id,
            "items": [
                {"book_id": book_id, "quantity": quantity}
                for book_id, quantity in items
            ],
        },
    )


def stock_of(client, book):
    return client.get(f"/books/{book['id']}").json()["stock"]


class TestBookEdgeCases:
    def test_unknown_patch_fields_are_ignored(self, client, make_book):
        book = make_book(stock=7, price_cents=1200)

        response = client.patch(
            f"/books/{book['id']}",
            json={
                "unknown_field": "should be ignored",
                "another_unknown_field": 123,
            },
        )

        assert response.status_code == 200
        assert response.json() == book


class TestOrderEdgeCases:
    def test_missing_book_in_multi_item_order_changes_nothing(
        self, client, make_member, make_book
    ):
        member = make_member()
        available = make_book(stock=5)

        response = place_order(
            client,
            member["id"],
            (available["id"], 2),
            (9999, 1),
        )

        assert response.status_code == 404

        # The valid book must not have been reserved.
        assert stock_of(client, available) == 5

        # No partial order must have been created.
        assert client.get(f"/members/{member['id']}/orders").json() == []

    def test_restricted_book_in_multi_item_order_changes_nothing(
        self, client, make_member, make_book
    ):
        member = make_member(tier="apprentice")
        public_book = make_book(stock=5)
        restricted_book = make_book(stock=5, restricted=True)

        response = place_order(
            client,
            member["id"],
            (public_book["id"], 2),
            (restricted_book["id"], 1),
        )

        assert response.status_code == 403

        # Authorization failure must happen before any stock mutation.
        assert stock_of(client, public_book) == 5
        assert stock_of(client, restricted_book) == 5

        assert client.get(f"/members/{member['id']}/orders").json() == []

    def test_supreme_bulk_discount_is_exactly_20_percent(
        self, client, make_member, make_book
    ):
        member = make_member(tier="supreme")
        book = make_book(price_cents=101, stock=10)

        response = place_order(
            client,
            member["id"],
            (book["id"], 10),
        )

        assert response.status_code == 201
        body = response.json()

        assert body["subtotal_cents"] == 1010
        assert body["discount_percent"] == 20

        # 1010 * 20 // 100 = 202
        assert body["discount_cents"] == 202
        assert body["total_cents"] == 808


class TestLoanEdgeCases:
    def test_late_fee_uses_book_price_at_return_time(
        self, client, clock, make_member, make_book
    ):
        member = make_member()
        book = make_book(price_cents=1000)

        response = client.post(
            "/loans",
            json={
                "member_id": member["id"],
                "book_id": book["id"],
            },
        )
        assert response.status_code == 201
        loan = response.json()

        # The book becomes cheaper after it was borrowed.
        client.patch(
            f"/books/{book['id']}",
            json={"price_cents": 60},
        )

        # 2 days late => 50 cents, which is below the new price.
        clock.advance(days=16)

        returned = client.post(f"/loans/{loan['id']}/return")

        assert returned.status_code == 200
        assert returned.json()["late_fee_cents"] == 50

    def test_late_fee_is_zero_until_loan_is_returned(
        self, client, clock, make_member, make_book
    ):
        member = make_member()
        book = make_book(price_cents=1000)

        response = client.post(
            "/loans",
            json={
                "member_id": member["id"],
                "book_id": book["id"],
            },
        )
        assert response.status_code == 201
        loan = response.json()

        clock.advance(days=20)

        # The loan is overdue, but it hasn't been returned yet.
        fetched = client.get(f"/loans/{loan['id']}")

        assert fetched.status_code == 200
        assert fetched.json()["status"] == "overdue"
        assert fetched.json()["late_fee_cents"] == 0


class TestReportEdgeCases:
    def test_report_uses_current_book_title(
        self, client, make_member, make_book
    ):
        member = make_member()
        book = make_book(title="Original Title", stock=5)

        order = place_order(
            client,
            member["id"],
            (book["id"], 2),
        )
        assert order.status_code == 201

        order_id = order.json()["id"]
        assert client.post(f"/orders/{order_id}/pay").status_code == 200

        # Reports should use the book's CURRENT title.
        updated = client.patch(
            f"/books/{book['id']}",
            json={"title": "Updated Title"},
        )
        assert updated.status_code == 200

        response = client.get("/reports/top-books")

        assert response.status_code == 200
        assert response.json() == [
            {
                "book_id": book["id"],
                "title": "Updated Title",
                "copies_sold": 2,
            }
        ]