import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from phase3.db.models import Base, TenantRow, UserRow, TenantMembershipRow


@pytest.mark.skipif(
    not os.environ.get("CAPSTONE_TEST_DATABASE_URL"),
    reason="PostgreSQL service URL is only configured in the dev CI job",
)
def test_phase3_schema_round_trip_on_postgres():
    engine = create_engine(os.environ["CAPSTONE_TEST_DATABASE_URL"], future=True)
    tenant_id = f"ci-tenant-{uuid4().hex}"
    user_id = f"ci-user-{uuid4().hex}"

    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            session.add_all(
                [
                    TenantRow(tenant_id=tenant_id, name="CI Tenant", source_mode="synthetic"),
                    UserRow(
                        user_id=user_id,
                        email=f"{user_id}@example.test",
                        password_hash="ci-hash",
                    ),
                ]
            )
            session.flush()
            membership = TenantMembershipRow(
                membership_id=f"ci-membership-{uuid4().hex}",
                user_id=user_id,
                tenant_id=tenant_id,
                role="OWNER",
            )
            session.add(membership)
            session.commit()

            persisted = session.get(TenantMembershipRow, membership.membership_id)
            assert persisted is not None
            assert persisted.tenant_id == tenant_id
            assert persisted.user_id == user_id
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
