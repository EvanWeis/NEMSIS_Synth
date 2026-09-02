"""Write the scenario library.

Fixture value comes from clinical spread, not from repetition: a hundred COPD
records exercise one code path a hundred times. These cover medical, trauma,
behavioural, obstetric, paediatric and toxicological presentations across BLS and
ALS, with a range of ages, acuities and dispositions - so a defect tier lands on a
different clinical shape each time it is generated.

Run once: python scripts/build_scenarios.py
"""

from __future__ import annotations

from pathlib import Path

import yaml

OUT = Path(__file__).resolve().parent.parent / "scenarios"

SCENARIOS: dict[str, dict] = {
    "chf_exacerbation_als": {
        "patient": {
            "age": 79,
            "sex": "female",
            "history": ["CHF", "atrial fibrillation", "CKD stage 3"],
            "acuity": "ALS",
        },
        "scene": {
            "location": "private residence",
            "time_of_day": "04:40",
            "conditions": ("found upright in recliner, unable to lie flat, pitting oedema"),
            "disposition": "transported ALS to emergency department",
        },
        "assessment": {
            "presentation": "acute dyspnoea, orthopnoea, pink frothy sputum",
            "lung_sounds": "coarse crackles to mid-lung fields bilaterally",
            "initial_vitals": {"spo2": 86, "respiratory_rate": 30, "heart_rate": 124, "sbp": 186},
            "after_treatment": {
                "spo2": 93,
                "respiratory_rate": 24,
                "heart_rate": 108,
                "sbp": 158,
            },
            "mental_status": "alert, anxious, oriented x4",
        },
        "interventions": [
            "CPAP 10 cm H2O",
            "nitroglycerin 0.4 mg SL x2",
            "IV access",
            "12-lead ECG",
            "continuous cardiac monitoring",
        ],
        "narrative_outline": (
            "Acute decompensated heart failure with pulmonary oedema. CPAP and nitrates "
            "en route with improvement. Positive pressure could not have been maintained "
            "outside an ambulance."
        ),
    },
    "hypoglycemia_als": {
        "patient": {"age": 54, "sex": "male", "history": ["type 1 diabetes"], "acuity": "ALS"},
        "scene": {
            "location": "workplace loading dock",
            "time_of_day": "16:15",
            "conditions": "found confused and diaphoretic by coworkers",
            "disposition": "treated and transported ALS to emergency department",
        },
        "assessment": {
            "presentation": "altered mental status, diaphoresis, tremor",
            "initial_vitals": {
                "spo2": 98,
                "respiratory_rate": 18,
                "heart_rate": 110,
                "sbp": 142,
                "glucose": 38,
            },
            "after_treatment": {
                "spo2": 99,
                "respiratory_rate": 16,
                "heart_rate": 88,
                "sbp": 132,
                "glucose": 112,
            },
            "mental_status": "initially confused and combative, GCS 13; baseline after treatment",
        },
        "interventions": [
            "blood glucose check",
            "IV access",
            "dextrose 10% 25 g IV",
            "repeat glucose and mental status reassessment",
        ],
        "narrative_outline": (
            "Symptomatic hypoglycaemia corrected with IV dextrose. Mental status returned "
            "to baseline; monitored transport still required for recurrence risk."
        ),
    },
    "seizure_peds_als": {
        "patient": {
            "age": 4,
            "sex": "female",
            "history": ["febrile seizure at age 2"],
            "acuity": "ALS",
        },
        "scene": {
            "location": "daycare centre",
            "time_of_day": "10:50",
            "conditions": "witnessed generalised tonic-clonic seizure lasting about 4 minutes",
            "disposition": "transported ALS to paediatric-capable facility",
        },
        "assessment": {
            "presentation": "postictal, sleepy but rousable, febrile to touch",
            "initial_vitals": {
                "spo2": 95,
                "respiratory_rate": 26,
                "heart_rate": 148,
                "sbp": 92,
                "temperature": 39.4,
                "glucose": 96,
            },
            "after_treatment": {
                "spo2": 98,
                "respiratory_rate": 22,
                "heart_rate": 128,
                "sbp": 94,
            },
            "mental_status": "postictal GCS 12, improving to 15 en route",
        },
        "interventions": [
            "airway positioning and suction",
            "supplemental oxygen",
            "blood glucose check",
            "passive cooling",
            "continuous monitoring",
        ],
        "narrative_outline": (
            "Febrile seizure in a young child, postictal on arrival. Airway monitoring "
            "required throughout; parent transport was unsafe given recurrence risk."
        ),
    },
    "stroke_als": {
        "patient": {
            "age": 68,
            "sex": "male",
            "history": ["hypertension", "hyperlipidaemia"],
            "acuity": "ALS",
        },
        "scene": {
            "location": "private residence",
            "time_of_day": "07:25",
            "conditions": "last known well 06:50, onset witnessed by spouse",
            "disposition": "transported ALS emergent to comprehensive stroke centre",
        },
        "assessment": {
            "presentation": "right facial droop, right arm drift, expressive aphasia",
            "initial_vitals": {
                "spo2": 97,
                "respiratory_rate": 18,
                "heart_rate": 82,
                "sbp": 178,
                "glucose": 104,
            },
            "after_treatment": {
                "spo2": 98,
                "respiratory_rate": 18,
                "heart_rate": 78,
                "sbp": 170,
            },
            "stroke_scale": "Cincinnati positive on all three components",
            "mental_status": "alert, follows commands, expressive deficit",
        },
        "interventions": [
            "stroke scale assessment",
            "blood glucose check",
            "IV access x2",
            "stroke alert to receiving facility",
            "continuous monitoring",
        ],
        "narrative_outline": (
            "Acute ischaemic stroke inside the thrombolytic window. Stroke alert "
            "transmitted from scene; time-critical monitored transport required."
        ),
    },
    "opioid_overdose_als": {
        "patient": {
            "age": 31,
            "sex": "male",
            "history": ["opioid use disorder"],
            "acuity": "ALS",
        },
        "scene": {
            "location": "public restroom",
            "time_of_day": "23:10",
            "conditions": "found unresponsive by staff, bystander naloxone before arrival",
            "disposition": "transported ALS to emergency department",
        },
        "assessment": {
            "presentation": "depressed respirations, pinpoint pupils, improving after naloxone",
            "initial_vitals": {"spo2": 88, "respiratory_rate": 8, "heart_rate": 64, "sbp": 104},
            "after_treatment": {
                "spo2": 97,
                "respiratory_rate": 16,
                "heart_rate": 76,
                "sbp": 112,
            },
            "mental_status": "initially unresponsive GCS 7; GCS 14 after naloxone",
        },
        "interventions": [
            "bag-valve-mask ventilation",
            "naloxone 1 mg intranasal",
            "IV access",
            "waveform capnography",
            "continuous monitoring",
        ],
        "narrative_outline": (
            "Opioid overdose with respiratory depression reversed by naloxone. "
            "Re-sedation risk required monitored transport."
        ),
    },
    "behavioral_bls": {
        "patient": {"age": 23, "sex": "female", "history": ["bipolar disorder"], "acuity": "BLS"},
        "scene": {
            "location": "university dormitory",
            "time_of_day": "21:40",
            "conditions": "police on scene, patient agitated but cooperative with EMS",
            "disposition": "transported BLS to emergency department for evaluation",
        },
        "assessment": {
            "presentation": "acute agitation, pressured speech, no trauma or intoxication",
            "initial_vitals": {
                "spo2": 99,
                "respiratory_rate": 20,
                "heart_rate": 104,
                "sbp": 128,
                "glucose": 88,
            },
            "after_treatment": {
                "spo2": 99,
                "respiratory_rate": 18,
                "heart_rate": 92,
                "sbp": 122,
            },
            "mental_status": "alert, oriented x4, calming with verbal de-escalation",
        },
        "interventions": [
            "verbal de-escalation",
            "blood glucose check",
            "serial vital signs",
            "continuous observation",
        ],
        "narrative_outline": (
            "Behavioural emergency managed without restraint or sedation. Continuous "
            "observation required for patient and crew safety during transport."
        ),
    },
    "obstetric_field_delivery_als": {
        "patient": {
            "age": 27,
            "sex": "female",
            "history": ["G3P2, 39 weeks gestation"],
            "acuity": "ALS",
        },
        "scene": {
            "location": "private residence",
            "time_of_day": "03:05",
            "conditions": "contractions two minutes apart, crowning on arrival",
            "disposition": "delivery on scene, mother and neonate transported ALS",
        },
        "assessment": {
            "presentation": "active labour, spontaneous vaginal delivery on scene",
            "initial_vitals": {"spo2": 98, "respiratory_rate": 22, "heart_rate": 112, "sbp": 132},
            "after_treatment": {
                "spo2": 99,
                "respiratory_rate": 18,
                "heart_rate": 94,
                "sbp": 124,
            },
            "neonate": "term male, APGAR 8 at 1 minute and 9 at 5 minutes, vigorous",
            "mental_status": "alert, oriented x4",
        },
        "interventions": [
            "assisted delivery",
            "cord clamping and cutting",
            "neonatal drying, warming and stimulation",
            "fundal massage",
            "IV access",
        ],
        "narrative_outline": (
            "Precipitous field delivery. Mother and neonate both required monitored "
            "transport; no alternative transport was appropriate."
        ),
    },
    "mvc_chest_trauma_als": {
        "patient": {"age": 42, "sex": "male", "history": [], "acuity": "ALS"},
        "scene": {
            "location": "highway, two-vehicle collision",
            "time_of_day": "18:20",
            "conditions": "restrained driver, moderate intrusion, airbag deployed, self-extricated",
            "disposition": "transported ALS to Level I trauma centre",
        },
        "assessment": {
            "presentation": "chest wall pain, seatbelt bruising, mild dyspnoea",
            "lung_sounds": "diminished on the left",
            "initial_vitals": {"spo2": 94, "respiratory_rate": 24, "heart_rate": 104, "sbp": 128},
            "after_treatment": {
                "spo2": 97,
                "respiratory_rate": 20,
                "heart_rate": 96,
                "sbp": 124,
            },
            "mental_status": "alert, oriented x4, GCS 15",
        },
        "interventions": [
            "spinal motion restriction",
            "supplemental oxygen",
            "IV access",
            "continuous monitoring",
            "trauma centre pre-alert",
        ],
        "narrative_outline": (
            "Blunt chest trauma with suspected pneumothorax. Mechanism and findings met "
            "trauma triage criteria; immobilised transport required."
        ),
    },
    "abdominal_pain_bls": {
        "patient": {
            "age": 35,
            "sex": "female",
            "history": ["prior cholecystectomy"],
            "acuity": "BLS",
        },
        "scene": {
            "location": "private residence",
            "time_of_day": "13:15",
            "conditions": "ambulatory to the stretcher, in obvious discomfort",
            "disposition": "transported BLS to emergency department",
        },
        "assessment": {
            "presentation": "right lower quadrant pain, nausea, no vomiting, pain 7 of 10",
            "initial_vitals": {
                "spo2": 99,
                "respiratory_rate": 18,
                "heart_rate": 96,
                "sbp": 124,
                "temperature": 37.8,
            },
            "after_treatment": {
                "spo2": 99,
                "respiratory_rate": 16,
                "heart_rate": 88,
                "sbp": 120,
            },
            "mental_status": "alert, oriented x4",
        },
        "interventions": [
            "position of comfort",
            "serial vital signs",
            "pain assessment and reassessment",
        ],
        "narrative_outline": (
            "Undifferentiated abdominal pain with low-grade fever. Ambulatory but in "
            "significant pain - a borderline necessity case by design."
        ),
    },
    "chest_pain_nstemi_als": {
        "patient": {
            "age": 61,
            "sex": "male",
            "history": ["prior coronary stent", "hypertension"],
            "acuity": "ALS",
        },
        "scene": {
            "location": "gymnasium",
            "time_of_day": "19:05",
            "conditions": "onset during exercise, partially relieved at rest",
            "disposition": "transported ALS to PCI-capable centre",
        },
        "assessment": {
            "presentation": "substernal chest pressure 6 of 10, mild dyspnoea, no radiation",
            "initial_vitals": {"spo2": 96, "respiratory_rate": 20, "heart_rate": 92, "sbp": 148},
            "after_treatment": {
                "spo2": 98,
                "respiratory_rate": 18,
                "heart_rate": 84,
                "sbp": 132,
            },
            "ecg": "12-lead without ST elevation, nonspecific T-wave changes",
            "mental_status": "alert, oriented x4",
        },
        "interventions": [
            "12-lead ECG",
            "aspirin 324 mg chewed",
            "nitroglycerin 0.4 mg SL",
            "IV access",
            "continuous monitoring",
        ],
        "narrative_outline": (
            "Suspected acute coronary syndrome without ST elevation. Serial ECG and "
            "monitoring required en route; arrhythmia risk made private transport unsafe."
        ),
    },
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, body in SCENARIOS.items():
        payload = {"name": name, **body}
        path = OUT / f"{name}.yaml"
        path.write_text(
            yaml.safe_dump(payload, sort_keys=False, width=96, allow_unicode=True),
            encoding="utf-8",
        )
    print(f"wrote {len(SCENARIOS)} scenarios to {OUT}")


if __name__ == "__main__":
    main()
