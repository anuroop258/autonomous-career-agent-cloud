from profile_reasoner import ProfileReasoner

r = ProfileReasoner()

cases = [
    (
        "Do you have hands-on experience with Python and Generative AI/LLMs?",
        ["Save"],
        "Yes",
    ),
    (
        "Do you have hands-on experience with Python and Generative AI/LLMs?",
        ["Yes, I have hands-on experience", "No, I don't have hands-on experience", "Save"],
        "Yes, I have hands-on experience",
    ),
    (
        "Are you willing to relocate?",
        ["Yes, I am willing to relocate", "No, I am not willing to relocate", "Save"],
        "Yes, I am willing to relocate",
    ),
    (
        "How many years of experience do you have in Python?",
        ["Save"],
        "0",
    ),
    (
        "Would you be open to committing to a one-year employment bond with the company?",
        ["Yes", "No", "Save"],
        "No",
    ),
]

for q, options, expected in cases:
    result = r.reason(q, options)
    actual = None if result is None else result.get("answer")
    print("Q:", q)
    print("OPTIONS:", options)
    print("RESULT:", result)
    assert actual == expected, (q, actual, expected)

print("ALL v18.9 QA REGRESSION TESTS PASSED")
