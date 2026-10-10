from phase3.db.session import PlatformSessionFactory


def test_factory_keeps_config_injected():
    cfg = {"database_url": "sqlite:///:memory:", "db_echo": False}
    factory = PlatformSessionFactory(cfg)

    assert factory.cfg == cfg
    assert factory.build_engine().dialect.name == "sqlite"


def test_session_factory_creates_session_obj():
    factory = PlatformSessionFactory({"database_url": "sqlite:///:memory:"})
    session = factory.create_session()

    assert session is not None
    session.close()
