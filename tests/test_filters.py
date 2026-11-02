"""Filter checks against real titles seen in UAE job alerts and boards. Run: python -m tests.test_filters"""
from engine.util import classify, is_uae, min_years, nationals, seniority

KEEP = [
    ("Backend Engineer", "software"),
    ("HR Data Analyst", "data_analyst"),
    ("HR Governance & MIS Specialist", "bi"),
    ("AI & BUSINESS AUTOMATION ENGINEER", "ai_ml"),
    ("Machine Learning Engineer, Applied AI - Deployed", "ai_ml"),
    ("Specialist- Data Scientist", "data_science"),
    ("Data Scientist AI - 36 Months", "data_science"),
    ("Data Reporting Engineer", "bi"),
    ("Business Analyst - CRM", "business"),
    ("Software Engineering Intern", "software"),
    ("Management Trainee", "graduate"),
    ("Data Analyst II", "data_analyst"),
    ("Junior Data Analyst", "data_analyst"),
    ("Associate Product Manager", "product"),
    ("Product Owner - Digital Banking", "product"),
    ("Power BI Developer", "bi"),
    ("IT Support Engineer", "it"),
    ("Application Support Analyst", "it"),
    ("Python Developer", "software"),
    ("Graduate Trainee - Data & Analytics", "data_analyst"),
    ("Operations Analyst", "business"),
    ("Analyst, Corporate Strategy", "analyst"),
    ("AI Specialist", "ai_ml"),
]

DROP = [
    "Sr. Manager Data Science (Dark Stores Intelligence)",
    "Graduate - Mechanical Engineering إماراتيين (خلاصة القيد)",
    "Quantity Surveyor",
    "Junior UI/UX Designer Intern",
    "Assistant, Associate, or Full Professor in Artificial Intelligence/Machine Learning",
    "Head of Data & AI",
    "Release Manager",
    "AI Architect",
    "MENA Fixed Income Sales - Vice President",
    "Senior Data Analyst",
    "Lead Data Engineer",
    "Cyber Security Analyst",
    "Credit Risk Analyst",
    "Data Entry Operator",
    "Frontend Developer",
    "Inspector - Mechanical",
    "Associate Director, Data Strategy",
    "Graduate Trainee - Finance",
]


def kept(title):
    family, _ = classify(title)
    return family is not None and seniority(title) != "senior" and nationals(title, "") != "only"


def main():
    bad = []
    for title, family in KEEP:
        got, _ = classify(title)
        if got != family or not kept(title):
            bad.append("KEEP %-60s family=%s seniority=%s nat=%s" % (
                title, got, seniority(title), nationals(title, "")))
    for title in DROP:
        if kept(title):
            bad.append("DROP %-60s family=%s seniority=%s" % (title, classify(title)[0], seniority(title)))

    assert nationals("Associate Product Specialist (UAE National Preferred)", "") == "preferred"
    assert nationals("Data Analyst", "This role is open to UAE Nationals only.") == "only"
    assert nationals("Data Analyst", "We support Emiratisation across the bank.") is None
    assert min_years("Requirements: 5+ years of experience in analytics") == 5
    assert min_years("0-2 years of experience with SQL") == 0
    assert min_years("3-5 years experience in a similar role") == 3
    assert min_years("For over 20 years we have served clients; experience a great culture") is None
    assert is_uae("Dubai, Dubai, AE") and is_uae("Abu Dhabi, United Arab Emirates")
    assert not is_uae("Riyadh, Saudi Arabia")

    if bad:
        print("\n".join(bad))
        raise SystemExit("%d filter cases failed" % len(bad))
    print("all %d filter cases pass" % (len(KEEP) + len(DROP) + 9))


if __name__ == "__main__":
    main()
