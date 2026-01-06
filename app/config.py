"""
Configuration settings for the CHAI Health Publications Tracker.

This file contains all application settings including database location,
email configuration, and CHAI program area definitions with keywords.
"""

import os
import secrets
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Base directory of the application
BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    """Main configuration class."""

    # Flask settings
    SECRET_KEY = os.getenv('SECRET_KEY', secrets.token_hex(32))
    DEBUG = os.getenv('FLASK_DEBUG', 'False').lower() in ('true', '1', 'yes')

    # Database settings - SQLite database stored in data folder
    # Use DATABASE_URL env var if set, otherwise use relative path
    SQLALCHEMY_DATABASE_URI = os.getenv(
        'DATABASE_URL',
        f"sqlite:///{BASE_DIR / 'data' / 'chai_tracker.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Base URL for email links (unsubscribe, preferences, etc.)
    # Set this to your production domain when deploying
    BASE_URL = os.getenv('BASE_URL', 'http://localhost:5000')

    # Email settings (SMTP)
    SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    SMTP_PORT = int(os.getenv('SMTP_PORT', 587))
    EMAIL_ADDRESS = os.getenv('EMAIL_ADDRESS', '')
    EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD', '')

    # PubMed API settings
    PUBMED_EMAIL = os.getenv('PUBMED_EMAIL', '')
    PUBMED_TOOL = 'CHAI-Health-Tracker'

    # Scraping settings
    SCRAPER_DELAY_SECONDS = 2  # Delay between requests to be respectful
    PUBMED_MAX_RESULTS_PER_AREA = 50  # Max papers per program area per run
    PUBMED_DAYS_LOOKBACK = 30  # Only get papers from last N days

    # Digest settings
    MIN_RELEVANCE_SCORE = 10  # Minimum score to link publication to program area
    MAX_PUBLICATIONS_PER_DIGEST = 10  # Max publications in one digest email


# CHAI Program Areas with their keywords and subtopics for categorization
# Each program area has a display name, category, keywords, and granular subtopics
PROGRAM_AREAS = {
    # ============ INFECTIOUS DISEASES ============
    "hiv_aids": {
        "name": "HIV/AIDS",
        "category": "Infectious Diseases",
        "keywords": ["HIV", "AIDS", "human immunodeficiency virus"],
        "subtopics": {
            "art_treatment": {
                "name": "Antiretroviral Treatment (ART)",
                "keywords": ["antiretroviral", "ART", "ARV", "dolutegravir", "DTG", "tenofovir", "TDF", "lamivudine", "3TC", "efavirenz", "first-line regimen", "second-line regimen", "treatment failure", "drug resistance"]
            },
            "viral_load": {
                "name": "Viral Load Monitoring",
                "keywords": ["viral load", "viral suppression", "undetectable", "VL testing", "virological failure", "HIV RNA"]
            },
            "prep": {
                "name": "Pre-Exposure Prophylaxis (PrEP)",
                "keywords": ["PrEP", "pre-exposure prophylaxis", "oral PrEP", "CAB-LA", "cabotegravir", "lenacapavir", "injectable PrEP", "HIV prevention"]
            },
            "pmtct": {
                "name": "Prevention of Mother-to-Child Transmission (PMTCT)",
                "keywords": ["PMTCT", "mother-to-child transmission", "MTCT", "vertical transmission", "Option B+", "infant prophylaxis", "early infant diagnosis", "EID", "breastfeeding HIV"]
            },
            "pediatric_hiv": {
                "name": "Pediatric HIV",
                "keywords": ["pediatric HIV", "children HIV", "adolescent HIV", "pDTG", "pediatric dolutegravir", "pediatric ART", "child-friendly formulation", "HIV-exposed infant"]
            },
            "hiv_testing": {
                "name": "HIV Testing & Diagnosis",
                "keywords": ["HIV testing", "HIV diagnosis", "rapid test", "self-testing", "HIV self-test", "index testing", "CD4 count", "point-of-care testing"]
            },
            "advanced_hiv_disease": {
                "name": "Advanced HIV Disease (AHD)",
                "keywords": ["advanced HIV disease", "AHD", "AIDS", "opportunistic infection", "cryptococcal meningitis", "histoplasmosis", "CD4 below 200", "late presenter"]
            },
            "vmmc": {
                "name": "Voluntary Medical Male Circumcision (VMMC)",
                "keywords": ["male circumcision", "VMMC", "voluntary medical male circumcision", "circumcision HIV prevention"]
            },
            "key_populations": {
                "name": "Key Populations",
                "keywords": ["key populations", "MSM", "men who have sex with men", "sex workers", "people who inject drugs", "PWID", "transgender", "FSW", "female sex workers"]
            }
        }
    },

    "malaria": {
        "name": "Malaria & Neglected Tropical Diseases",
        "category": "Infectious Diseases",
        "keywords": ["malaria", "plasmodium", "falciparum", "vivax"],
        "subtopics": {
            "bed_nets": {
                "name": "Insecticide-Treated Bed Nets",
                "keywords": ["bed net", "LLIN", "long-lasting insecticidal net", "ITN", "insecticide-treated net", "mosquito net", "pyrethroid", "net distribution", "net coverage"]
            },
            "antimalarials": {
                "name": "Antimalarial Treatment",
                "keywords": ["antimalarial", "ACT", "artemisinin", "artemether", "lumefantrine", "artesunate", "amodiaquine", "artemisinin-based combination therapy", "chloroquine", "primaquine"]
            },
            "drug_resistance": {
                "name": "Antimalarial Drug Resistance",
                "keywords": ["artemisinin resistance", "drug resistance malaria", "partial resistance", "treatment failure malaria", "kelch13", "pfkelch13"]
            },
            "diagnostics_malaria": {
                "name": "Malaria Diagnostics",
                "keywords": ["rapid diagnostic test", "RDT", "malaria microscopy", "malaria diagnosis", "HRP2", "pLDH"]
            },
            "vector_control": {
                "name": "Vector Control & Indoor Residual Spraying",
                "keywords": ["indoor residual spraying", "IRS", "vector control", "insecticide", "larvicide", "Anopheles", "mosquito control"]
            },
            "chemoprevention": {
                "name": "Malaria Chemoprevention",
                "keywords": ["chemoprevention", "SMC", "seasonal malaria chemoprevention", "IPTp", "intermittent preventive treatment", "IPTi", "mass drug administration", "MDA"]
            },
            "malaria_surveillance": {
                "name": "Malaria Surveillance & Elimination",
                "keywords": ["malaria elimination", "malaria eradication", "surveillance", "case investigation", "foci response", "stratification", "transmission reduction"]
            },
            "malaria_vaccine": {
                "name": "Malaria Vaccines",
                "keywords": ["malaria vaccine", "RTS,S", "Mosquirix", "R21", "Matrix-M"]
            },
            "ntds": {
                "name": "Neglected Tropical Diseases (NTDs)",
                "keywords": ["neglected tropical disease", "NTD", "dengue", "lymphatic filariasis", "schistosomiasis", "soil-transmitted helminth", "trachoma", "onchocerciasis", "leishmaniasis"]
            }
        }
    },

    "tuberculosis": {
        "name": "Tuberculosis",
        "category": "Infectious Diseases",
        "keywords": ["tuberculosis", "TB", "mycobacterium"],
        "subtopics": {
            "tb_diagnostics": {
                "name": "TB Diagnostics",
                "keywords": ["GeneXpert", "Xpert MTB/RIF", "TB diagnosis", "sputum", "chest X-ray", "TB LAM", "molecular diagnostics TB", "culture TB"]
            },
            "tb_treatment": {
                "name": "TB Treatment",
                "keywords": ["TB treatment", "rifampicin", "isoniazid", "pyrazinamide", "ethambutol", "DOTS", "directly observed therapy", "TB regimen"]
            },
            "drug_resistant_tb": {
                "name": "Drug-Resistant TB (MDR-TB/XDR-TB)",
                "keywords": ["MDR-TB", "XDR-TB", "multidrug-resistant", "extensively drug-resistant", "rifampicin-resistant", "bedaquiline", "delamanid", "pretomanid", "BPaL"]
            },
            "tb_hiv": {
                "name": "TB/HIV Co-infection",
                "keywords": ["TB/HIV", "TB HIV coinfection", "co-infected", "isoniazid preventive therapy", "IPT", "TPT", "TB preventive treatment"]
            },
            "pediatric_tb": {
                "name": "Pediatric TB",
                "keywords": ["pediatric TB", "childhood tuberculosis", "child TB", "TB children"]
            },
            "latent_tb": {
                "name": "Latent TB Infection",
                "keywords": ["latent TB", "LTBI", "TB infection", "TB screening", "preventive therapy"]
            }
        }
    },

    "hepatitis": {
        "name": "Hepatitis",
        "category": "Infectious Diseases",
        "keywords": ["hepatitis", "viral hepatitis"],
        "subtopics": {
            "hepatitis_c": {
                "name": "Hepatitis C",
                "keywords": ["hepatitis C", "HCV", "sofosbuvir", "daclatasvir", "direct-acting antiviral", "DAA", "HCV cure", "HCV treatment", "HCV elimination"]
            },
            "hepatitis_b": {
                "name": "Hepatitis B",
                "keywords": ["hepatitis B", "HBV", "HBsAg", "tenofovir HBV", "HBV vaccination", "birth dose", "chronic hepatitis B"]
            },
            "hepatitis_testing": {
                "name": "Hepatitis Testing & Screening",
                "keywords": ["hepatitis screening", "HCV antibody", "HBsAg test", "hepatitis diagnosis"]
            }
        }
    },

    "oxygen_therapy": {
        "name": "Oxygen Therapy",
        "category": "Infectious Diseases",
        "keywords": ["oxygen", "medical oxygen", "hypoxemia", "oxygen therapy"],
        "subtopics": {
            "oxygen_access": {
                "name": "Oxygen Access & Infrastructure",
                "keywords": ["oxygen supply", "oxygen plant", "oxygen concentrator", "PSA plant", "oxygen cylinder", "liquid oxygen"]
            },
            "pulse_oximetry": {
                "name": "Pulse Oximetry & Hypoxemia Screening",
                "keywords": ["pulse oximetry", "pulse oximeter", "SpO2", "oxygen saturation", "hypoxemia screening"]
            },
            "oxygen_covid": {
                "name": "COVID-19 Oxygen Response",
                "keywords": ["COVID oxygen", "COVID-19 oxygen", "pandemic oxygen", "respiratory support"]
            }
        }
    },

    "covid19": {
        "name": "COVID-19",
        "category": "Infectious Diseases",
        "keywords": ["COVID-19", "coronavirus", "SARS-CoV-2", "COVID"],
        "subtopics": {
            "covid_vaccines": {
                "name": "COVID-19 Vaccines",
                "keywords": ["COVID vaccine", "COVID-19 vaccination", "mRNA vaccine", "viral vector vaccine", "booster dose"]
            },
            "covid_testing": {
                "name": "COVID-19 Testing & Diagnostics",
                "keywords": ["COVID test", "PCR", "antigen test", "rapid antigen", "COVID diagnosis"]
            },
            "covid_treatment": {
                "name": "COVID-19 Treatment",
                "keywords": ["COVID treatment", "dexamethasone", "remdesivir", "nirmatrelvir", "Paxlovid", "COVID therapeutics"]
            }
        }
    },

    # ============ WOMEN AND CHILDREN'S HEALTH ============
    "maternal_newborn_health": {
        "name": "Maternal, Newborn & Reproductive Health",
        "category": "Women and Children's Health",
        "keywords": ["maternal health", "newborn health", "reproductive health", "MNRH", "SRMNH"],
        "subtopics": {
            "antenatal_care": {
                "name": "Antenatal Care",
                "keywords": ["antenatal care", "ANC", "prenatal care", "pregnancy care", "antenatal visit", "gestational"]
            },
            "skilled_birth": {
                "name": "Skilled Birth Attendance & Delivery",
                "keywords": ["skilled birth", "facility delivery", "childbirth", "labor", "delivery care", "midwife", "obstetric", "cesarean", "C-section"]
            },
            "postnatal_care": {
                "name": "Postnatal Care",
                "keywords": ["postnatal care", "PNC", "postpartum", "post-delivery", "postnatal visit"]
            },
            "neonatal_care": {
                "name": "Neonatal Care",
                "keywords": ["neonatal", "newborn", "neonate", "neonatal mortality", "newborn resuscitation", "kangaroo mother care", "KMC", "low birth weight", "preterm"]
            },
            "maternal_mortality": {
                "name": "Maternal Mortality Reduction",
                "keywords": ["maternal mortality", "maternal death", "postpartum hemorrhage", "PPH", "pre-eclampsia", "eclampsia", "obstetric emergency", "EmONC"]
            },
            "family_planning": {
                "name": "Family Planning & Contraception",
                "keywords": ["family planning", "contraception", "contraceptive", "IUD", "implant", "injectable", "oral contraceptive", "birth spacing", "reproductive choice"]
            },
            "safe_abortion": {
                "name": "Safe Abortion Care",
                "keywords": ["safe abortion", "post-abortion care", "PAC", "medical abortion", "mifepristone", "misoprostol", "comprehensive abortion care"]
            }
        }
    },

    "diarrhea_pneumonia": {
        "name": "Diarrhea & Pneumonia",
        "category": "Women and Children's Health",
        "keywords": ["diarrhea", "pneumonia", "child mortality"],
        "subtopics": {
            "ors_zinc": {
                "name": "ORS & Zinc for Diarrhea",
                "keywords": ["ORS", "oral rehydration", "zinc", "oral rehydration salts", "zinc supplementation", "diarrhea treatment"]
            },
            "pneumonia_treatment": {
                "name": "Pneumonia Treatment",
                "keywords": ["pneumonia treatment", "amoxicillin", "respiratory infection", "ALRI", "acute respiratory infection", "pneumonia antibiotics"]
            },
            "imci": {
                "name": "Integrated Management of Childhood Illness (IMCI)",
                "keywords": ["IMCI", "integrated management", "childhood illness", "iCCM", "community case management"]
            }
        }
    },

    "vaccines_immunization": {
        "name": "Vaccines & Immunization",
        "category": "Women and Children's Health",
        "keywords": ["vaccine", "immunization", "vaccination", "immunisation"],
        "subtopics": {
            "routine_immunization": {
                "name": "Routine Immunization",
                "keywords": ["routine immunization", "EPI", "expanded programme", "immunization schedule", "vaccine coverage", "zero-dose", "under-immunized"]
            },
            "vaccine_introduction": {
                "name": "New Vaccine Introduction",
                "keywords": ["vaccine introduction", "new vaccine", "PCV", "pneumococcal", "rotavirus", "HPV vaccine", "Hib", "pentavalent"]
            },
            "cold_chain": {
                "name": "Cold Chain & Vaccine Logistics",
                "keywords": ["cold chain", "vaccine storage", "vaccine logistics", "vaccine supply chain", "refrigerator", "cold room"]
            },
            "vaccine_campaigns": {
                "name": "Vaccination Campaigns",
                "keywords": ["vaccination campaign", "mass vaccination", "catch-up campaign", "supplementary immunization", "SIA"]
            }
        }
    },

    "nutrition": {
        "name": "Nutrition",
        "category": "Women and Children's Health",
        "keywords": ["nutrition", "malnutrition", "undernutrition"],
        "subtopics": {
            "acute_malnutrition": {
                "name": "Acute Malnutrition (SAM/MAM)",
                "keywords": ["severe acute malnutrition", "SAM", "moderate acute malnutrition", "MAM", "wasting", "RUTF", "ready-to-use therapeutic food", "CMAM"]
            },
            "stunting": {
                "name": "Stunting & Chronic Malnutrition",
                "keywords": ["stunting", "chronic malnutrition", "growth faltering", "linear growth"]
            },
            "micronutrients": {
                "name": "Micronutrient Supplementation",
                "keywords": ["micronutrient", "vitamin A", "iron supplementation", "folic acid", "iodine", "multiple micronutrient", "MNP"]
            },
            "infant_feeding": {
                "name": "Infant & Young Child Feeding",
                "keywords": ["breastfeeding", "exclusive breastfeeding", "complementary feeding", "IYCF", "infant feeding"]
            },
            "nutrition_assessment": {
                "name": "Nutrition Assessment & Screening",
                "keywords": ["MUAC", "mid-upper arm circumference", "nutrition screening", "anthropometry", "weight-for-height"]
            }
        }
    },

    # ============ NON-COMMUNICABLE DISEASES ============
    "cancer": {
        "name": "Cancer",
        "category": "Non-Communicable Diseases",
        "keywords": ["cancer", "oncology", "tumor", "malignancy"],
        "subtopics": {
            "cervical_cancer": {
                "name": "Cervical Cancer",
                "keywords": ["cervical cancer", "HPV", "human papillomavirus", "VIA", "visual inspection", "cervical screening", "colposcopy", "LEEP", "cryotherapy", "thermal ablation", "cervical precancer"]
            },
            "breast_cancer": {
                "name": "Breast Cancer",
                "keywords": ["breast cancer", "mammography", "breast screening", "mastectomy", "breast examination"]
            },
            "pediatric_cancer": {
                "name": "Pediatric Cancer",
                "keywords": ["childhood cancer", "pediatric oncology", "leukemia children", "Wilms tumor", "retinoblastoma"]
            },
            "cancer_treatment": {
                "name": "Cancer Treatment Access",
                "keywords": ["chemotherapy", "radiotherapy", "cancer treatment", "oncology drugs", "cancer surgery", "cancer medicines"]
            },
            "palliative_care": {
                "name": "Palliative Care",
                "keywords": ["palliative care", "pain management", "morphine", "end-of-life care", "hospice"]
            }
        }
    },

    "diabetes_hypertension": {
        "name": "Diabetes & Hypertension",
        "category": "Non-Communicable Diseases",
        "keywords": ["diabetes", "hypertension", "cardiovascular"],
        "subtopics": {
            "diabetes_management": {
                "name": "Diabetes Management",
                "keywords": ["diabetes", "insulin", "metformin", "blood glucose", "HbA1c", "glycemic control", "type 2 diabetes", "diabetic"]
            },
            "hypertension_management": {
                "name": "Hypertension Management",
                "keywords": ["hypertension", "high blood pressure", "antihypertensive", "blood pressure control", "amlodipine", "losartan"]
            },
            "ncd_screening": {
                "name": "NCD Screening & Prevention",
                "keywords": ["NCD screening", "cardiovascular risk", "HEARTS", "PEN package", "NCD prevention"]
            }
        }
    },

    "sickle_cell": {
        "name": "Sickle Cell Disease",
        "category": "Non-Communicable Diseases",
        "keywords": ["sickle cell", "SCD", "hemoglobin"],
        "subtopics": {
            "sickle_cell_screening": {
                "name": "Sickle Cell Screening",
                "keywords": ["newborn screening", "sickle cell screening", "hemoglobin electrophoresis", "point-of-care sickle cell"]
            },
            "sickle_cell_treatment": {
                "name": "Sickle Cell Treatment",
                "keywords": ["hydroxyurea", "sickle cell treatment", "vaso-occlusive crisis", "sickle cell management"]
            }
        }
    },

    "assistive_technology": {
        "name": "Assistive Technology",
        "category": "Non-Communicable Diseases",
        "keywords": ["assistive technology", "disability", "assistive device"],
        "subtopics": {
            "mobility_aids": {
                "name": "Mobility Aids",
                "keywords": ["wheelchair", "mobility aid", "prosthetic", "orthotic", "crutches", "walker"]
            },
            "hearing_vision": {
                "name": "Hearing & Vision Aids",
                "keywords": ["hearing aid", "glasses", "eyeglasses", "vision aid", "visual impairment", "hearing loss"]
            }
        }
    },

    # ============ HEALTH SYSTEMS ============
    "health_financing": {
        "name": "Health Financing",
        "category": "Health Systems",
        "keywords": ["health financing", "health insurance", "UHC"],
        "subtopics": {
            "insurance": {
                "name": "Health Insurance",
                "keywords": ["health insurance", "national health insurance", "NHIS", "social health insurance", "insurance enrollment", "premium"]
            },
            "uhc": {
                "name": "Universal Health Coverage",
                "keywords": ["universal health coverage", "UHC", "financial protection", "out-of-pocket", "catastrophic health expenditure"]
            },
            "resource_allocation": {
                "name": "Resource Allocation & Budgeting",
                "keywords": ["health budget", "resource allocation", "health expenditure", "domestic financing", "health spending"]
            }
        }
    },

    "health_workforce": {
        "name": "Health Workforce",
        "category": "Health Systems",
        "keywords": ["health workforce", "health worker", "human resources for health"],
        "subtopics": {
            "chw": {
                "name": "Community Health Workers",
                "keywords": ["community health worker", "CHW", "village health worker", "lay health worker", "community health volunteer"]
            },
            "training": {
                "name": "Health Worker Training",
                "keywords": ["health worker training", "capacity building", "in-service training", "pre-service education", "clinical mentorship"]
            },
            "task_shifting": {
                "name": "Task Shifting & Task Sharing",
                "keywords": ["task shifting", "task sharing", "nurse-led", "decentralization", "differentiated service delivery"]
            }
        }
    },

    "digital_health": {
        "name": "Digital Health",
        "category": "Health Systems",
        "keywords": ["digital health", "eHealth", "mHealth", "health technology"],
        "subtopics": {
            "health_information": {
                "name": "Health Information Systems",
                "keywords": ["HMIS", "DHIS2", "health information system", "electronic medical record", "EMR", "patient registry"]
            },
            "mobile_health": {
                "name": "Mobile Health Applications",
                "keywords": ["mHealth", "mobile health", "SMS reminder", "telemedicine", "telehealth"]
            },
            "data_analytics": {
                "name": "Data Analytics & Decision Support",
                "keywords": ["data analytics", "dashboard", "decision support", "data-driven", "surveillance system"]
            }
        }
    },

    # ============ CROSS-CUTTING ============
    "diagnostics": {
        "name": "Diagnostics",
        "category": "Cross-Cutting",
        "keywords": ["diagnostics", "laboratory", "testing"],
        "subtopics": {
            "point_of_care": {
                "name": "Point-of-Care Testing",
                "keywords": ["point-of-care", "POC", "rapid test", "bedside testing", "near-patient testing"]
            },
            "laboratory_systems": {
                "name": "Laboratory Systems",
                "keywords": ["laboratory", "lab network", "sample transport", "quality assurance", "lab capacity"]
            }
        }
    },

    "market_shaping": {
        "name": "Market Shaping",
        "category": "Cross-Cutting",
        "keywords": ["market shaping", "procurement", "supply chain"],
        "subtopics": {
            "price_reduction": {
                "name": "Price Reduction & Negotiations",
                "keywords": ["price reduction", "price negotiation", "pooled procurement", "volume guarantee", "ceiling price"]
            },
            "supply_chain": {
                "name": "Supply Chain Strengthening",
                "keywords": ["supply chain", "logistics", "stock management", "forecasting", "quantification", "last mile delivery"]
            },
            "generic_medicines": {
                "name": "Generic Medicines Access",
                "keywords": ["generic", "generic medicine", "biosimilar", "voluntary licensing", "technology transfer"]
            }
        }
    }
}


def get_program_area_name(key):
    """Get the display name for a program area key."""
    if key in PROGRAM_AREAS:
        return PROGRAM_AREAS[key]["name"]
    return key


def get_program_area_category(key):
    """Get the category for a program area key."""
    if key in PROGRAM_AREAS:
        return PROGRAM_AREAS[key].get("category", "Other")
    return "Other"


def get_all_program_area_choices():
    """Get list of (key, name) tuples for all program areas."""
    return [(key, area["name"]) for key, area in PROGRAM_AREAS.items()]


def get_all_program_areas_with_subtopics():
    """
    Get all program areas with their subtopics, organized by category.

    Returns:
        Dictionary with structure:
        {
            category_name: {
                program_key: {
                    name: str,
                    subtopics: {subtopic_key: subtopic_name, ...}
                }
            }
        }
    """
    result = {}
    for key, area in PROGRAM_AREAS.items():
        category = area.get("category", "Other")
        if category not in result:
            result[category] = {}
        result[category][key] = {
            "name": area["name"],
            "subtopics": {
                st_key: st_info["name"]
                for st_key, st_info in area.get("subtopics", {}).items()
            }
        }
    return result


def get_subtopic_name(program_key, subtopic_key):
    """Get the display name for a subtopic."""
    if program_key in PROGRAM_AREAS:
        subtopics = PROGRAM_AREAS[program_key].get("subtopics", {})
        if subtopic_key in subtopics:
            return subtopics[subtopic_key]["name"]
    return subtopic_key


def get_subtopics_for_program(program_key):
    """Get list of (key, name) tuples for subtopics in a program area."""
    if program_key in PROGRAM_AREAS:
        subtopics = PROGRAM_AREAS[program_key].get("subtopics", {})
        return [(key, info["name"]) for key, info in subtopics.items()]
    return []


def get_all_keywords_for_program(program_key, include_subtopics=True):
    """
    Get all keywords for a program area, optionally including subtopic keywords.

    Args:
        program_key: The program area key
        include_subtopics: If True, include all subtopic keywords

    Returns:
        List of keywords
    """
    if program_key not in PROGRAM_AREAS:
        return []

    area = PROGRAM_AREAS[program_key]
    keywords = list(area.get("keywords", []))

    if include_subtopics:
        for subtopic in area.get("subtopics", {}).values():
            keywords.extend(subtopic.get("keywords", []))

    return keywords


def get_keywords_for_subtopic(program_key, subtopic_key):
    """Get keywords for a specific subtopic."""
    if program_key in PROGRAM_AREAS:
        subtopics = PROGRAM_AREAS[program_key].get("subtopics", {})
        if subtopic_key in subtopics:
            return subtopics[subtopic_key].get("keywords", [])
    return []


# LMIC Regions and Countries for geographic filtering
# Each region has a display name, region-level keywords, and list of countries
REGIONS_AND_COUNTRIES = {
    "sub_saharan_africa": {
        "name": "Sub-Saharan Africa",
        "keywords": ["Sub-Saharan Africa", "SSA"],
        "countries": [
            "Angola", "Benin", "Botswana", "Burkina Faso", "Burundi",
            "Cabo Verde", "Cape Verde", "Cameroon", "Central African Republic",
            "Chad", "Comoros", "Congo", "Republic of the Congo",
            "Democratic Republic of the Congo", "DRC", "Cote d'Ivoire",
            "Ivory Coast", "Djibouti", "Equatorial Guinea", "Eritrea",
            "Eswatini", "Swaziland", "Ethiopia", "Gabon", "Gambia", "Ghana",
            "Guinea", "Guinea-Bissau", "Kenya", "Lesotho", "Liberia",
            "Madagascar", "Malawi", "Mali", "Mauritania", "Mauritius",
            "Mozambique", "Namibia", "Niger", "Nigeria", "Rwanda",
            "Sao Tome and Principe", "Senegal", "Seychelles", "Sierra Leone",
            "Somalia", "South Africa", "South Sudan", "Sudan", "Tanzania",
            "Togo", "Uganda", "Zambia", "Zimbabwe"
        ]
    },
    "south_asia": {
        "name": "South Asia",
        "keywords": ["South Asia", "Indian subcontinent"],
        "countries": [
            "Afghanistan", "Bangladesh", "Bhutan", "India", "Maldives",
            "Nepal", "Pakistan", "Sri Lanka"
        ]
    },
    "southeast_asia": {
        "name": "Southeast Asia",
        "keywords": ["Southeast Asia", "ASEAN", "Mekong"],
        "countries": [
            "Brunei", "Cambodia", "Indonesia", "Laos", "Lao PDR",
            "Malaysia", "Myanmar", "Burma", "Philippines", "Singapore",
            "Thailand", "Timor-Leste", "East Timor", "Vietnam"
        ]
    },
    "east_asia_pacific": {
        "name": "East Asia & Pacific",
        "keywords": ["East Asia", "Pacific Islands", "Oceania"],
        "countries": [
            "China", "Fiji", "Kiribati", "Marshall Islands", "Micronesia",
            "Mongolia", "Nauru", "North Korea", "DPRK", "Palau",
            "Papua New Guinea", "PNG", "Samoa", "Solomon Islands",
            "Tonga", "Tuvalu", "Vanuatu"
        ]
    },
    "latin_america_caribbean": {
        "name": "Latin America & Caribbean",
        "keywords": ["Latin America", "Caribbean", "LAC", "Central America", "South America"],
        "countries": [
            "Antigua and Barbuda", "Argentina", "Bahamas", "Barbados",
            "Belize", "Bolivia", "Brazil", "Chile", "Colombia", "Costa Rica",
            "Cuba", "Dominica", "Dominican Republic", "Ecuador", "El Salvador",
            "Grenada", "Guatemala", "Guyana", "Haiti", "Honduras", "Jamaica",
            "Mexico", "Nicaragua", "Panama", "Paraguay", "Peru",
            "Saint Kitts and Nevis", "Saint Lucia", "Saint Vincent and the Grenadines",
            "Suriname", "Trinidad and Tobago", "Uruguay", "Venezuela"
        ]
    },
    "middle_east_north_africa": {
        "name": "Middle East & North Africa",
        "keywords": ["Middle East", "North Africa", "MENA", "Arab"],
        "countries": [
            "Algeria", "Bahrain", "Egypt", "Iran", "Iraq", "Jordan",
            "Kuwait", "Lebanon", "Libya", "Morocco", "Oman", "Palestine",
            "West Bank", "Gaza", "Qatar", "Saudi Arabia", "Syria",
            "Tunisia", "United Arab Emirates", "UAE", "Yemen"
        ]
    },
    "eastern_europe_central_asia": {
        "name": "Eastern Europe & Central Asia",
        "keywords": ["Central Asia", "Eastern Europe", "Caucasus", "Former Soviet"],
        "countries": [
            "Albania", "Armenia", "Azerbaijan", "Belarus", "Bosnia and Herzegovina",
            "Georgia", "Kazakhstan", "Kosovo", "Kyrgyzstan", "Kyrgyz Republic",
            "Moldova", "Montenegro", "North Macedonia", "Russia", "Serbia",
            "Tajikistan", "Turkey", "Turkmenistan", "Ukraine", "Uzbekistan"
        ]
    },
    "global": {
        "name": "Global (No Geographic Filter)",
        "keywords": [],
        "countries": []
    }
}

# Complete list of all countries for Country Watch feature
# This allows users to select any country regardless of region grouping
ALL_COUNTRIES = sorted(set([
    # Sub-Saharan Africa
    "Angola", "Benin", "Botswana", "Burkina Faso", "Burundi", "Cabo Verde",
    "Cameroon", "Central African Republic", "Chad", "Comoros",
    "Democratic Republic of the Congo", "Republic of the Congo",
    "Cote d'Ivoire", "Djibouti", "Equatorial Guinea", "Eritrea",
    "Eswatini", "Ethiopia", "Gabon", "Gambia", "Ghana", "Guinea",
    "Guinea-Bissau", "Kenya", "Lesotho", "Liberia", "Madagascar", "Malawi",
    "Mali", "Mauritania", "Mauritius", "Mozambique", "Namibia", "Niger",
    "Nigeria", "Rwanda", "Sao Tome and Principe", "Senegal", "Seychelles",
    "Sierra Leone", "Somalia", "South Africa", "South Sudan", "Sudan",
    "Tanzania", "Togo", "Uganda", "Zambia", "Zimbabwe",
    # South Asia
    "Afghanistan", "Bangladesh", "Bhutan", "India", "Maldives", "Nepal",
    "Pakistan", "Sri Lanka",
    # Southeast Asia
    "Brunei", "Cambodia", "Indonesia", "Laos", "Malaysia", "Myanmar",
    "Philippines", "Singapore", "Thailand", "Timor-Leste", "Vietnam",
    # East Asia & Pacific
    "China", "Fiji", "Kiribati", "Marshall Islands", "Micronesia", "Mongolia",
    "Nauru", "North Korea", "Palau", "Papua New Guinea", "Samoa",
    "Solomon Islands", "Tonga", "Tuvalu", "Vanuatu",
    # Latin America & Caribbean
    "Antigua and Barbuda", "Argentina", "Bahamas", "Barbados", "Belize",
    "Bolivia", "Brazil", "Chile", "Colombia", "Costa Rica", "Cuba",
    "Dominica", "Dominican Republic", "Ecuador", "El Salvador", "Grenada",
    "Guatemala", "Guyana", "Haiti", "Honduras", "Jamaica", "Mexico",
    "Nicaragua", "Panama", "Paraguay", "Peru", "Saint Kitts and Nevis",
    "Saint Lucia", "Saint Vincent and the Grenadines", "Suriname",
    "Trinidad and Tobago", "Uruguay", "Venezuela",
    # Middle East & North Africa
    "Algeria", "Bahrain", "Egypt", "Iran", "Iraq", "Jordan", "Kuwait",
    "Lebanon", "Libya", "Morocco", "Oman", "Palestine", "Qatar",
    "Saudi Arabia", "Syria", "Tunisia", "United Arab Emirates", "Yemen",
    # Eastern Europe & Central Asia
    "Albania", "Armenia", "Azerbaijan", "Belarus", "Bosnia and Herzegovina",
    "Georgia", "Kazakhstan", "Kosovo", "Kyrgyzstan", "Moldova", "Montenegro",
    "North Macedonia", "Russia", "Serbia", "Tajikistan", "Turkey",
    "Turkmenistan", "Ukraine", "Uzbekistan"
]))


def get_region_name(key):
    """Get the display name for a region key."""
    if key in REGIONS_AND_COUNTRIES:
        return REGIONS_AND_COUNTRIES[key]["name"]
    return key


def get_all_region_choices():
    """Get list of (key, name) tuples for all regions."""
    return [(key, region["name"]) for key, region in REGIONS_AND_COUNTRIES.items()]


def get_all_countries_for_region(region_key):
    """Get list of all countries in a region."""
    if region_key in REGIONS_AND_COUNTRIES:
        return REGIONS_AND_COUNTRIES[region_key]["countries"]
    return []


def get_all_searchable_terms_for_region(region_key):
    """Get all searchable terms (keywords + countries) for a region."""
    if region_key not in REGIONS_AND_COUNTRIES:
        return []
    region = REGIONS_AND_COUNTRIES[region_key]
    return region["keywords"] + region["countries"]


def get_all_country_choices():
    """Get list of all countries for Country Watch selection."""
    return ALL_COUNTRIES


def get_region_for_country(country_name):
    """Find which region a country belongs to."""
    for region_key, region_data in REGIONS_AND_COUNTRIES.items():
        if country_name in region_data["countries"]:
            return region_key
    return None
