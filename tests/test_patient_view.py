from neurogrip.patient_view import build_prompt


def test_prompt_compares_with_last_session():
    p = build_prompt({"reps": 12, "activation_rate": 70}, {"reps": 8, "activation_rate": 55})
    assert '"reps": 12' in p and '"reps": 8' in p and "supportive coach" in p


def test_prompt_first_session():
    assert "first session" in build_prompt({"reps": 3})
