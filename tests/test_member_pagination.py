import pytest

def member_ids(response) -> list:
    return [member["id"] for member in response.json()["items"]]

class TestListMembers:
    def test_empty_store(self, client):
        response = client.get("/members")

        assert response.status_code == 200
        assert response.json() == {
            "items": [],
            "total": 0,
            "limit": 20,
            "offset": 0,
        }

    def test_members_are_returned_in_id_order(self, client, make_member):
        first = make_member(name="First", email="first@sanctum.org")
        second = make_member(name="Second", email="second@sanctum.org")
        third = make_member(name="Third", email="third@sanctum.org")

        response = client.get("/members")

        assert response.status_code == 200
        assert member_ids(response) == [
            first["id"],
            second["id"],
            third["id"],
        ]

    def test_items_are_full_member_objects(self, client, make_member):
        member = make_member()

        response = client.get("/members")

        assert response.status_code == 200
        assert response.json()["items"] == [member]

    def test_pagination_with_limit_and_offset(self, client, make_member):
        members = [
            make_member(
                name=f"Member {i}",
                email=f"member{i}@sanctum.org",
            )
            for i in range(5)
        ]

        response = client.get(
            "/members",
            params={"limit": 2, "offset": 2},
        )

        assert response.status_code == 200

        body = response.json()

        assert [member["id"] for member in body["items"]] == [
            members[2]["id"],
            members[3]["id"],
        ]
        assert body["total"] == 5
        assert body["limit"] == 2
        assert body["offset"] == 2

    def test_default_limit_is_20(self, client, make_member):
        for i in range(21):
            make_member(
                name=f"Member {i}",
                email=f"member{i}@sanctum.org",
            )

        body = client.get("/members").json()

        assert len(body["items"]) == 20
        assert body["total"] == 21

    def test_offset_past_end_returns_no_items_but_total(self,client,make_member,):
        make_member()
        make_member()

        body = client.get(
            "/members",
            params={"offset": 10},
        ).json()

        assert body["items"] == []
        assert body["total"] == 2

    @pytest.mark.parametrize("limit", [1, 100])
    def test_limit_bounds_are_accepted(self, client, limit):
        response = client.get(
            "/members",
            params={"limit": limit},
        )

        assert response.status_code == 200

    @pytest.mark.parametrize(
        "params",
        [
            {"limit": 0},
            {"limit": 101},
            {"offset": -1},
        ],
    )
    def test_out_of_range_pagination_returns_422(self, client, params):
        response = client.get("/members", params=params)

        assert response.status_code == 422