"""Filter checks against real titles seen in UAE job alerts and boards. Run: python -m tests.test_filters"""
from datetime import date

from engine.util import classify, elsewhere, is_uae, min_years, nationals, norm_company, parse_date, seniority

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
    # first live runs, November 2026
    ("Associate Support Engineer - Treasury & Risk", "it"),  # treasury no longer hides a tech role
    ("AML Data Analyst", "data_analyst"),
    ("Credit Risk Modelling Analyst", "analyst"),
    ("Forward Deployed Engineer - UAE", "software"),
    ("BIE Engineer", "bi"),  # Amazon's Business Intelligence Engineer
    ("Sales Analyst eCommerce - UAE & Oman", "analyst"),
    ("Biostatistician-Clinical Trials Unit Section", "data_science"),
    ("Data Center Technician - 2027 Internship", "it"),
    ("Trans Topology Data Analyst, Supply Chain Transportation Planning", "data_analyst"),
    ("QA Engineer", "software"),
    ("Junior Test Automation Engineer", "software"),
    ("Early Talent Programme 2027", "graduate"),
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
    # first live runs, November 2026
    "Graduate Trainee – Internal Shariah Control (UAEN)",
    "Tableau Account Executive - Middle East",
    "GPU/AI  Global Sales - Customer Acquisition",
    "Junior Sales Analyst - Inside Sales",
    "Junior Business Development Representative (Graduate/Early Careers)",
    "Merchant Acquisition Intern",
    "Animator Intern",
    "Product Specialist, Oncology",
    "Principle Fiat Product Specialist",
    "Deputy CTO (AI Agents, TypeScript, Kafka, Kubernetes)",
    "Engineer - NOC & Permits (AUH)",
    "Applied Behavioural Analyst",
    "Applied Behavioral Analyst (Sakina)",
    "Cost Analyst - Business Finance",
    "Financial Reporting specialist",
    "Freelance F&B Financial & Performance ANALYST",
    "People Operations Associate",
    "Workplace Operations Analyst",
    "2027 Facilities Coordinator Intern",
    "2027 Operations Intern, FC Operations",
    "Graduate Area Manager",
    "Embedded Software Engineer II",
    "IAM Business Analyst (SailPoint)",
    "Intern-People and Organization",
    "Watani Business Enablement Solutions Graduate Programme",  # PwC's UAE-nationals programme
    "Marketing Associate - Maseeraty Graduate Program, UAE",
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

    # nationals-only roles that the first live runs let through
    assert nationals("Graduate Trainee (UAEN)", "") == "only"
    assert nationals("Officer, Treasury Operations (Emiritization)", "") == "only"
    assert nationals("Associate Technical Support Engineer",
                     "Role : Associate Technical Support Engineer ( UAE National ) Location : Abu Dhabi") == "only"
    assert nationals("Management Trainee Program 2025-2026",
                     "Are you an ambitious UAE National with a minimum GPA of 3.7?") == "only"
    assert nationals("AI Graduate Programme", "This programme is central to our mission: developing UAE "
                     "National talent into the next generation of tech leaders.") == "only"
    assert nationals("Senior Specialist - New Business Enablement",
                     "Senior Specialist - New Business Enablement (For UAEN applicants) Embark on a journey") == "only"
    assert nationals("Management Trainee Program 2025-2026", "a structured development initiative aimed at "
                     "preparing UAE Nationals for critical middle management roles") == "only"
    assert nationals("Management Trainee Program", "Requirements: UAE National with a Family Book") == "only"
    assert nationals("Product Management Intern, Summer 2027 – Dubai, UAE (UAE Nationals Preferred)",
                     "") == "preferred"
    assert nationals("Data Analyst", "We welcome UAE nationals and expatriates alike.") is None
    # titles naming another country although the listing says Dubai
    assert elsewhere("IAM Business Analyst (SailPoint) - Riyadh, KSA") and elsewhere("Data Analyst - Doha")
    assert not elsewhere("Sales Analyst eCommerce - UAE & Oman") and not elsewhere("Data Analyst")
    assert not elsewhere("Junior Research Scientist (Computer Science) – Lab of Dr. Riyadh A.")  # a first name
    # date shapes from the newer job systems (Avature list, RSS feeds)
    assert parse_date("09-Oct-2026") == date(2026, 10, 9)
    assert parse_date("Mon, 02 Nov 2026 12:05:49 +0400") == date(2026, 11, 2)
    # one employer, two spellings: dedupe on the same key
    assert norm_company("Masdar (Abu Dhabi Future Energy Company)") == norm_company("Masdar") == "masdar"
    assert norm_company("Halian | Managed Services, Recruitment") == "halian"
    assert norm_company("Bayut | dubizzle") == "dubizzle"

    if bad:
        print("\n".join(bad))
        raise SystemExit("%d filter cases failed" % len(bad))
    print("all %d filter cases pass" % (len(KEEP) + len(DROP) + 29))


if __name__ == "__main__":
    main()
