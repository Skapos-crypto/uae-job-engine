"""Filter checks against real titles seen in UAE job alerts and boards. Run: python -m tests.test_filters"""
from datetime import date

from engine.util import (classify, elsewhere, evidence, is_agency, is_uae, job_key, min_years, nationals,
                         norm_company, parse_date, seniority)

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
    # second week, November 2026
    ("Odoo Developer", "software"),
    ("Data Quality Analyst", "data_analyst"),
    ("Associate Analyst, Business Administration- Launch Program 2027", "analyst"),
    ("Data Analyst - Intern", "data_analyst"),
    ("Finance Data Analyst", "data_analyst"),
    ("Software Development Engineer 2", "software"),  # like "II": kept
    ("Claims Data Analyst", "data_analyst"),  # insurance, but a data role
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
    # second week, November 2026: rows that got through
    "Trainee Optometrist. Operations. Grand Optics Ajman City Centre",
    "Data Recovery Hardware Engineer",
    "Odoo & Email Marketing Specialist",
    "Officer, Lab Technical Support",
    "Middle Distillates Analyst (Gasoil, Jet and ULSD) (8E87445)",
    "Dubai Holding Entertainment: Technology & Data Talent Pool",
    "Engineering & Technical Services Open Day| Tuesday, 10 November | 10AM",
    "Executive Risk Management - National Talent - Fresh Graduate role",  # Emirati programme
    "Senior Operations Associate - Shops",
    "Commercial Finance Analyst",
    "Analyst – Portfolio Management",
    "Quality Control Analyst",
    "Automation Engineer, Reliability Maintenance Engineering",  # warehouse machinery, not software
    "Software Development Engineer 3",  # a level, like "III"
    "Claims Associate Analyst",  # insurance claims handling
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
    # one job, one key: real pairs that showed up twice in early November 2026
    same_job = [
        (("Etihad", "Data Analyst – Databricks AI/BI & FinOps"),
         ("Etihad Airways", "Databricks Data Analyst – AI/BI & FinOps")),
        (("Amazon", "Trans Topology Data Analyst"), ("Amazon.com", "Trans Topology Data Analyst")),
        (("ADIB", "HR Data Analyst"), ("ADIB - Abu Dhabi Islamic Bank", "HR Data Analyst")),
        (("Buro Happold", "Graduate Analyst - Advisory"),
         ("Buro Happold Engineer India Private Limited", "Graduate Analyst - Advisory")),
        (("Aventus", "Metadata & Data Catalog Consultant (Informatica)"),
         ("Aventus Global Talent", "Metadata & Data Catalog Consultant (Informatica)")),
        (("Cognita Schools", "Business Analyst, CRM (12-Month Fixed-Term Contract)"),
         ("COGNITA SCHOOLS", "CRM Business Analyst (12-Month Fixed-Term Contract)")),
        (("Referment", "Middle Distillates Analyst (Gasoil, Jet and ULSD) (5AD7)"),
         ("Referment", "Middle Distillates Analyst (Gasoil, Jet and ULSD) (8E87)")),
        (("Halian | Managed Services", "Data Scientist (m/f/d)"), ("Halian", "Data Scientist")),
        # one employer under several names: its own site names the brand, the job sites the group
        (("dnata Cargo", "Data Analyst, dnata Cargo"), ("The Emirates Group", "Data Analyst, dnata Cargo")),
        (("dnata", "Data Analyst, dnata Cargo"), ("Emirates", "Data Analyst, dnata Cargo")),
        (("ADNOC", "Specialist, Logistics (Performance & Reporting)"),
         ("ADNOC Logistics & Services", "Specialist, Logistics (Performance & Reporting)")),
        (("talabat", "Software Engineer l - Backend"), ("Delivery Hero", "Software Engineer l - Backend")),
    ]
    for a, b in same_job:
        assert job_key(*a) == job_key(*b), (a, b)
    different_jobs = [
        (("Emirates", "Data Analyst"), ("Emirates NBD", "Data Analyst")),
        (("Amazon", "Data Analyst"), ("Amazon Web Services", "Data Analyst")),
        (("Acme", "Software Engineer I"), ("Acme", "Software Engineer II")),
        (("New York University Abu Dhabi", "Junior Research Scientist in the Center for Interdisciplinary Data Science"),
         ("New York University Abu Dhabi", "Research Engineer in the Center for Interdisciplinary Data Science")),
    ]
    for a, b in different_jobs:
        assert job_key(*a) != job_key(*b), (a, b)
    # one employer, two spellings: dedupe on the same key
    assert norm_company("Masdar (Abu Dhabi Future Energy Company)") == norm_company("Masdar") == "masdar"
    assert norm_company("Halian | Managed Services, Recruitment") == "halian"
    assert norm_company("Bayut | dubizzle") == "dubizzle"
    # the words behind a description-level rejection, kept so that it can be checked by eye
    assert "open to UAE Nationals only" in evidence(
        "Data Analyst", "A great team. This role is open to UAE Nationals only. Apply today.", "nationals-only")
    assert evidence("Graduate Trainee (UAEN)", "", "nationals-only") == "Graduate Trainee (UAEN)"
    assert "6 years of experience" in evidence("Data Analyst", "Minimum 6 years of experience in banking", "4+ years")
    assert "cannot offer visa sponsorship" in evidence(
        "Data Analyst", "Please note we cannot offer visa sponsorship for this role.", "no-sponsorship")
    assert evidence("Data Analyst", "", "4+ years") == ""  # facts from the cache: no words at hand
    # "associate" alone no longer rescues a senior title; other junior words still do
    assert seniority("Senior Operations Associate - Shops") == "senior"
    assert seniority("Associate Analyst") == "junior" and seniority("Senior Graduate Programme Associate") == "junior"
    assert nationals("Engineering Positions (National Talent)", "") == "only"
    # Workday location codes count as the UAE
    assert is_uae("AE-DUBAI-TECHNO PARK") and is_uae("AE-ABU DHABI-AL GHAITH HOLDING TOWER, AIRPORT ROAD")
    assert not is_uae("MACAE-BRAZIL")
    # agencies and unnamed posters are flagged
    assert is_agency("Halian | Managed Services, Recruitment Agency") and is_agency("Confidential Careers")
    assert is_agency("Alliance Recruitment Agency") and is_agency("Madison Pearl") and is_agency("Aventus Global Talent")
    assert not is_agency("Emirates NBD") and not is_agency("Dubai Holding") and not is_agency("Deloitte Consulting")

    if bad:
        print("\n".join(bad))
        raise SystemExit("%d filter cases failed" % len(bad))
    assert seniority("Software Development Engineer 3") == "senior" and seniority("Data Analyst II") == "unspecified"
    # a programme "for UAE National students" is a nationals programme; "for UAE nationals and expats" is not
    assert nationals("Discover Emirates Group Internship Programme", "Discover is our internship programme "
                     "for UAE National students and fresh graduates.") == "only"
    assert nationals("Graduate Programme", "A graduate programme for UAE nationals and expatriates alike.") is None
    # a ceiling is not a requirement
    assert min_years("Experience: Up to 7 Years. Mandatory skills: strong Java") is None
    assert min_years("Less than 2 years of experience is fine. Minimum 1 year of experience with SQL.") == 1
    assert min_years("Requirements: 5+ years of experience in analytics") == 5
    # recruiters and job platforms seen in the second week
    assert is_agency("Jobgether") and is_agency("Kingston Stanley") and is_agency("Salt")
    assert not is_agency("Kraken") and not is_agency("Salt Bae Restaurants") and not is_agency("Emirates Group")
    print("all %d filter cases pass" % (len(KEEP) + len(DROP) + 70))


if __name__ == "__main__":
    main()
