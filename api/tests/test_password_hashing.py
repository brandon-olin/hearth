from life_dashboard.auth.hashing import hash_password, verify_password


def test_hash_is_not_plaintext():
    h = hash_password("correct horse battery staple")
    assert h != "correct horse battery staple"
    assert len(h) > 20


def test_verify_accepts_correct_password():
    h = hash_password("s3cret-pw")
    assert verify_password("s3cret-pw", h) is True


def test_verify_rejects_wrong_password():
    h = hash_password("s3cret-pw")
    assert verify_password("wrong-pw", h) is False


def test_two_hashes_of_same_password_differ():
    assert hash_password("abc") != hash_password("abc")
