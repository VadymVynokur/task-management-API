from scripts.check_commit_message import validate_message


def test_valid_commit_message() -> None:
    assert validate_message("feat(auth): add refresh rotation") == []


def test_merge_commit_is_ignored() -> None:
    assert validate_message("Merge branch 'develop' into feature") == []


def test_invalid_type_is_rejected() -> None:
    errors = validate_message("update: change things")

    assert errors


def test_description_must_start_lowercase() -> None:
    errors = validate_message("feat: Add things")

    assert errors


def test_description_must_not_end_with_period() -> None:
    errors = validate_message("feat: add things.")

    assert errors


def test_breaking_change_requires_footer() -> None:
    assert validate_message("feat!: change token format")
    assert validate_message("feat!: change token format\n\nBREAKING CHANGE: tokens changed") == []
