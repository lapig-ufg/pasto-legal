from app.services.session_migration import migrate_session_state


def test_migrate_v0_to_v1_maintains_data():
    raw_state = {
        "all_properties": [{"car_code": "GO-1111111-1111AAAA2222BBBB3333CCCC4444DDDD", "spatial_features": {"total_area": 50.0}}],
        "user_persona": {"name": "Produtor Teste", "role": "Produtor"},
        "some_legacy_flag": True
    }
    
    migrated = migrate_session_state(raw_state)
    
    assert migrated.get("workflow_state", {}).get("schema_version") == 1
    assert migrated["all_properties"] == raw_state["all_properties"]
    assert migrated["user_persona"] == raw_state["user_persona"]
    assert "_legacy_data" in migrated


def test_migrate_idempotency():
    raw_state = {
        "workflow_state": {"schema_version": 1, "is_feedback_active": False},
        "all_properties": [],
        "user_persona": {},
        "_legacy_data": {}
    }
    
    migrated = migrate_session_state(raw_state)
    
    assert migrated == raw_state


def test_migrate_empty_state_resilience():
    raw_state = {}
    
    migrated = migrate_session_state(raw_state)
    
    assert migrated.get("workflow_state", {}).get("schema_version") == 1
    assert isinstance(migrated.get("all_properties"), list)
    assert isinstance(migrated.get("user_persona"), dict)
    assert isinstance(migrated.get("_legacy_data"), dict)