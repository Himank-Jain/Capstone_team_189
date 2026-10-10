from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from phase3.db.models import Base, TenantRow, TenantMembershipRow, UserRow


def test_platform_schema_round_trip():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        user = UserRow(user_id="user-1", email="alice@example.com", password_hash="hash")
        tenant = TenantRow(tenant_id="tenant-1", name="Acme", source_mode="synthetic")
        membership = TenantMembershipRow(
            membership_id="m-1",
            user_id="user-1",
            tenant_id="tenant-1",
            role="OWNER",
        )

        session.add_all([user, tenant, membership])
        session.commit()

        rows = session.query(TenantMembershipRow).all()
        assert len(rows) == 1
        assert rows[0].role == "OWNER"
        assert session.query(TenantRow).count() == 1
