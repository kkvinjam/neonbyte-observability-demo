"""Demo shoppers. There is no login: the shopper is picked from this list (cookie
``nb_user``), and checkout is pre-filled with that shopper's name and address."""

DEMO_USERS: dict[str, dict] = {
    "user001": {"name": "Ava Martinez", "street": "1200 Pine St", "city": "Seattle", "state": "WA", "zip": "98101"},
    "user002": {"name": "Liam Chen", "street": "88 King St", "city": "San Francisco", "state": "CA", "zip": "94107"},
    "user003": {"name": "Sofia Patel", "street": "350 5th Ave", "city": "New York", "state": "NY", "zip": "10118"},
    "user004": {"name": "Noah Johnson", "street": "233 S Wacker Dr", "city": "Chicago", "state": "IL", "zip": "60606"},
    "user005": {"name": "Mia Okafor", "street": "1 Congress Ave", "city": "Austin", "state": "TX", "zip": "78701"},
    "user006": {"name": "Ethan Kim", "street": "1600 Broadway", "city": "Denver", "state": "CO", "zip": "80202"},
    "user007": {"name": "Isabella Rossi", "street": "100 Peachtree St", "city": "Atlanta", "state": "GA", "zip": "30303"},
    "user008": {"name": "Lucas Nguyen", "street": "800 Boylston St", "city": "Boston", "state": "MA", "zip": "02199"},
    "user009": {"name": "Amelia Schmidt", "street": "701 Brickell Ave", "city": "Miami", "state": "FL", "zip": "33131"},
    "user010": {"name": "Mateo Silva", "street": "1001 SW 5th Ave", "city": "Portland", "state": "OR", "zip": "97204"},
}
DEFAULT_USER = "user001"


def shipping_for(user_id: str) -> dict:
    user = DEMO_USERS.get(user_id)
    if user:
        return dict(user)
    return {"name": f"Guest {user_id}", "street": "410 Terry Ave N", "city": "Seattle", "state": "WA", "zip": "98109"}
