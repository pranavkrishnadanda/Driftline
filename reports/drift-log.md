# Drift log

Every document version change, newest first. Generated from the Driftline database.

- Data as of: 2026-04-22 (the newest version's start date)
- Tenant: drift-watch
- Documents: 7 · versions: 30 · version changes: 23
- Drift verdicts on watched answers: changed 0 · broken 0 · still valid 0
- LLM: offline (`DRIFTLINE_LLM_OFFLINE=true`). No paid key is used: claim checks run on the deterministic extractive judge, not Claude, and supersession extraction is off.

## Documents

| Document | Source | Versions | Current | In force since |
|---|---|---|---|---|
| Deployments<br>`content/en/docs/concepts/workloads/controllers/deployment.md` | git_docs | 2 | v2 (`release-1.36`) | 2026-04-22 |
| Deprecated API Migration Guide<br>`content/en/docs/reference/using-api/deprecation-guide.md` | git_docs | 1 | v1 (`release-1.35`) | 2025-12-17 |
| JANTOVEN (WARFARIN SODIUM) TABLET [UPSHER-SMITH LABORATORIES, LLC]<br>`19a69a72-ac5d-45d5-a94d-a5aaecbe4730` | openfda | 10 | v10 (`13`) | 2025-07-08 |
| LIPITOR (ATORVASTATIN CALCIUM) TABLET, FILM COATED [VIATRIS SPECIALTY LLC]<br>`a60cc18b-0631-4cf0-b021-9f52224ece65` | openfda | 3 | v3 (`7`) | 2024-04-15 |
| PAXLOVID (NIRMATRELVIR AND RITONAVIR) KIT [PFIZER LABORATORIES DIV PFIZER INC]<br>`8a99d6d6-fd9e-45bb-b1bf-48c7f761232a` | openfda | 8 | v8 (`12`) | 2026-02-19 |
| PLAVIX (CLOPIDOGREL) TABLET, FILM COATED [SANOFI-AVENTIS U.S. LLC]<br>`de8b0b67-eb25-4684-83b5-7ad785314227` | openfda | 4 | v4 (`5`) | 2025-05-30 |
| ZOLOFT (SERTRALINE HYDROCHLORIDE) TABLET, FILM COATED ZOLOFT (SERTRALINE HYDROCHLORIDE) SOLUTION, CONCENTRATE [VIATRIS SPECIALTY LLC]<br>`fda754f6-d0f3-4dce-a17a-927d64f912f7` | openfda | 2 | v2 (`2`) | 2023-08-15 |

## Changes

### 2026-04-22 · Deployments · v1 → v2

`content/en/docs/concepts/workloads/controllers/deployment.md` (git_docs) · version key `release-1.35` → `release-1.36`

- Sections: 0 added, 2 changed, 0 removed
  - Changed: `Updating a Deployment > Label selector updates`, `Writing a Deployment Spec > Progress Deadline Seconds`
- Verdicts: changed 0 · broken 0 · still valid 0

#### Updating a Deployment > Label selector updates

```diff
@@ -3,12 +3,16 @@
 it cannot be updated via `kubectl patch`, `kubectl edit`, `kubectl apply`, or tools like `helm upgrade`.
 
 If you must change the selector, you have to delete the Deployment and recreate it.
+By default, deleting the Deployment also deletes its running Pods, causing downtime; use
+`--cascade=orphan` if you need those Pods to keep running while you recreate the Deployment
+(see the implications below).
 Exercise great caution and ensure you grasp the following implications:
 
 * **Additions:** When you create a new Deployment with a narrower selector, the new Deployment **must** also have a suitable Pod template.
   If you have an existing manifest and you edit the manifest to narrow the selector, you need to edit the metadata of the Pod template inside that Deployment, adding the
   new labels
... diff truncated
```

#### Writing a Deployment Spec > Progress Deadline Seconds

```diff
@@ -2,7 +2,6 @@
 to wait for your Deployment to progress before the system reports back that the Deployment has
 [failed progressing](#failed-deployment) - surfaced as a condition with `type: Progressing`, `status: "False"`.
 and `reason: ProgressDeadlineExceeded` in the status of the resource. The Deployment controller will keep
-retrying the Deployment. This defaults to 600. In the future, once automatic rollback will be implemented, the Deployment
-controller will roll back a Deployment as soon as it observes such a condition.
+retrying the Deployment. This defaults to 600.
 
 If specified, this field needs to be greater than `.spec.minReadySeconds`.
```

### 2026-02-19 · PAXLOVID (NIRMATRELVIR AND RITONAVIR) KIT [PFIZER LABORATORIES DIV PFIZER INC] · v7 → v8

`8a99d6d6-fd9e-45bb-b1bf-48c7f761232a` (openfda) · version key `10` → `12`

- Sections: 0 added, 6 changed, 0 removed
  - Changed: `2 DOSAGE AND ADMINISTRATION > 2.1 Important Dosage and Administration Information`, `2 DOSAGE AND ADMINISTRATION > 2.3 Dosage in Patients with Renal Impairment`, `4 CONTRAINDICATIONS`, `7 DRUG INTERACTIONS > 7.3 Established and Other Potentially Significant Drug Interactions`, `SPL PATIENT PACKAGE INSERT SECTION`, `SPL UNCLASSIFIED SECTION`
- Verdicts: changed 0 · broken 0 · still valid 0

#### 2 DOSAGE AND ADMINISTRATION > 2.1 Important Dosage and Administration Information

```diff
@@ -1,3 +1,3 @@
-PAXLOVID is nirmatrelvir tablets co-packaged with ritonavir tablets. There are three different dose packs available: •PAXLOVID (nirmatrelvir; ritonavir) co-packaged for oral use 300 mg;100 mg [see Dosage and Administration (2.2)]. •PAXLOVID (nirmatrelvir; ritonavir) co-packaged for oral use 150 mg;100 mg for patients with moderate renal impairment [see Dosage and Administration (2.3)]. • PAXLOVID (nirmatrelvir; ritonavir) co-packaged for oral use 300 mg;100 mg (Day 1) and 150 mg;100 mg (Days 2-5) for patients with severe renal impairment [see Dosage and Administration (2.3)]. Nirmatrelvir must be co-administered with ritonavir. Failure to correctly co-administer nirmatrelvir with ritonavir may result in plasma levels of nirmatrelvir that are insufficient to achieve the desired therapeutic effect.
+PAXLOVID is nirmatrelvir tablets co-packaged with ritonavir tablets. There are three different dose packs available: •PAXLOVID (nirmatrelvir; ritonavir) co-packaged for oral use 300 mg;100 mg [see Dosage and Administration (2.2)]. •PAXLOVID (nirmatrelvir; ritonavir) co-packaged for oral use 150 mg;100 mg for patients with moderate renal impairment [see Dosage and Administration (2.3)]. •PAXLOVID (nirmatrelvir; ritonavir) co-packaged for oral use 300 mg;100 mg (Day 1) and 150 mg;100 mg (Days 2-5) for patients with severe renal impairment [see Dosage and Administration (2.3)]. Nirmatrelvir must be co-administered with ritonavir. Failure to correctly co-administer nirmatrelvir with ritonavir may result in plasma levels of nirmatrelvir that are insufficient to achieve the desired therapeutic effect.
 Prescriptions should specify the numeric dose of each active ingredient within PAXLOVID [see Dosage and Administration (2.2, 2.3)]. Completion of the full 5-day treatment course and continued isolation in accordance with public health recommendations are important to maximize viral clearance and minimize transmission of SARS-CoV-2. The 5-day treatment course of PAXLOVID should be initiated as soon as possible after a diagnosis of COVID-19 has been made, and within 5 days of symptom onset even if baseline COVID-19 symptoms are mild. Should a patient require hospitalization due to severe or critical COVID-19 after starting treatment with PAXLOVID, the patient should complete the full 5-day treatment course per the healthcare provider's discretion. If the patient misses a dose of PAXLOVID within 8 hours of the time it is usually taken, the patient should take it as soon as possible and resume the normal dosing schedule. If the patient misses a dose by more than 8 hours, the patient should not take the missed dose and instead take the next dose at the regularly scheduled time. The patient should not double the dose to make up for a missed dose.
 The patient should not double the dose to make up for a missed dose. PAXLOVID (both nirmatrelvir and ritonavir tablets) can be taken with or without food [see Clinical Pharmacology (12.3)]. The tablets should be swallowed whole and not chewed, broken, or crushed.
```

#### 2 DOSAGE AND ADMINISTRATION > 2.3 Dosage in Patients with Renal Impairment

```diff
@@ -1,2 +1,2 @@
 Prescriptions should specify the numeric dose of each active ingredient within PAXLOVID. Providers should counsel patients about renal dosing instructions [see Patient Counseling Information (17)]. No dosage adjustment is recommended in patients with mild renal impairment [estimated glomerular filtration rate (eGFR) ≥60 to <90 mL/min]. In patients with moderate renal impairment (eGFR ≥30 to <60 mL/min) or with severe renal impairment (eGFR <30 mL/min) including those requiring hemodialysis, the dosage of PAXLOVID should be reduced as shown in Table 1. PAXLOVID should be administered at approximately the same time each day for 5 days. On days patients with severe renal impairment undergo hemodialysis, the PAXLOVID dose should be administered after hemodialysis [see Use in Specific Populations (8.6), Clinical Pharmacology (12.3), and How Supplied/Storage and Handling (16)]. Table 1: Recommended Dose and Regimen for Patients with Renal Impairment Abbreviation: eGFR=estimated glomerular filtration rate.
-Renal Function Days of Treatment Dose and Dose Frequency PAXLOVID should be administered at approximately the same time each day for 5 days. Moderate renal impairment (eGFR ≥30 to <60 mL/min) Days 1-5 150 mg nirmatrelvir (one 150 mg tablet) with 100 mg ritonavir (one 100 mg tablet) twice daily Severe renal impairment (eGFR <30 mL/min) including those requiring hemodialysis On days of hemodialysis, the PAXLOVID dose should be administered after hemodialysis. Day 1 300 mg nirmatrelvir (two 150 mg tablets) with 100 mg ritonavir (one 100 mg tablet) once Days 2-5 150 mg nirmatrelvir (one 150 mg tablet) with 100 mg ritonavir (one 100 mg tablet) once daily
+Renal Function Days of Treatment Dose and Dose FrequencyPAXLOVID should be administered at approximately the same time each day for 5 days. Moderate renal impairment (eGFR ≥30 to <60 mL/min) Days 1-5 150 mg nirmatrelvir (one 150 mg tablet) with 100 mg ritonavir (one 100 mg tablet) twice daily Severe renal impairment (eGFR <30 mL/min) including those requiring hemodialysisOn days of hemodialysis, the PAXLOVID dose should be administered after hemodialysis. Day 1 300 mg nirmatrelvir (two 150 mg tablets) with 100 mg ritonavir (one 100 mg tablet) once Days 2-5 150 mg nirmatrelvir (one 150 mg tablet) with 100 mg ritonavir (one 100 mg tablet) once daily
```

#### 4 CONTRAINDICATIONS

```diff
@@ -1,4 +1,4 @@
 PAXLOVID is contraindicated in patients with a history of clinically significant hypersensitivity reactions [e.g., toxic epidermal necrolysis (TEN) or Stevens-Johnson syndrome] to its active ingredients (nirmatrelvir or ritonavir) or any other components of the product. PAXLOVID is contraindicated with drugs that are primarily metabolized by CYP3A and for which elevated concentrations are associated with serious and/or life-threatening reactions and drugs that are strong CYP3A inducers where significantly reduced nirmatrelvir or ritonavir plasma concentrations may be associated with the potential for loss of virologic response and possible resistance. There are certain other drugs for which concomitant use with PAXLOVID should be avoided and/or dose adjustment, interruption, or therapeutic monitoring is recommended. Drugs listed in this section are a guide and not considered a comprehensive list of all drugs that may be contraindicated with PAXLOVID.
 Drugs listed in this section are a guide and not considered a comprehensive list of all drugs that may be contraindicated with PAXLOVID. The healthcare provider should consult other appropriate resources such as the prescribing information for the interacting drug for comprehensive information on dosing or monitoring with concomitant use of a strong CYP3A inhibitor like PAXLOVID [see Drug Interactions (7.3)]: ➢Drugs that are primarily metabolized by CYP3A for which elevated concentrations are associated with serious and/or life-threatening reactions [see Drug Interactions (7.3)]: •Alpha 1-adrenoreceptor antagonist: alfuzosin •Antianginal: ranolazine •Antiarrhythmic: amiodarone, dronedarone, flecainide, propafenone, quinidine •Anti-gout: colchicine (in patients with renal and/or hepatic impairment [see Table 2 , Drug Interactions (7.3)] ) •Antipsychotics: lurasidone, pimozide •Benign prostatic hyperplasia agents: silodosin •Cardiovascular agents: eplerenone,
-pimozide •Benign prostatic hyperplasia agents: silodosin •Cardiovascular agents: eplerenone, ivabradine •Ergot derivatives: dihydroergotamine, ergotamine, methylergonovine •HMG-CoA reductase inhibitors: lovastatin, simvastatin (these drugs can be temporarily discontinued to allow PAXLOVID use [see Table 2 , Drug Interactions (7.3)]) •Immunosuppressants: voclosporin •Microsomal triglyceride transfer protein inhibitor: lomitapide •Migraine medications: eletriptan, ubrogepant •Mineralocorticoid receptor antagonists: finerenone •Opioid antagonists: naloxegol •PDE5 inhibitor: sildenafil (Revatio®) when used for pulmonary arterial hypertension (PAH) •Sedative/hypnotics: triazolam,
+pimozide •Benign prostatic hyperplasia agents: silodosin •Cardiovascular agents: eplerenone, ivabradine •Ergot derivatives: dihydroergotamine, ergotamine, methylergonovine •HMG-CoA reductase inhibitors: lovastatin, simvastatin (these drugs can be temporarily discontinued to allow PAXLOVID use [see Table 2 , Drug Interactions (7.3)]) •Immunosuppressants: voclosporin •Microsomal triglyceride transfer protein inhibitor: lomitapide •Migraine medications: eletriptan, ubrogepant •Mineralocorticoid receptor antagonists: finerenone • Non-opioid analgesic (selective blocker of Nav1.8 sodium channels): suzetrigine •Opioid antagonists: naloxegol •PDE5 inhibitor: sildenafil (Revatio®) when used for pulmonary arterial hypertension (PAH) •Sedative/hypnotics: triazolam,
... diff truncated
```

### 2025-07-09 · PAXLOVID (NIRMATRELVIR AND RITONAVIR) KIT [PFIZER LABORATORIES DIV PFIZER INC] · v6 → v7

`8a99d6d6-fd9e-45bb-b1bf-48c7f761232a` (openfda) · version key `9` → `10`

- Sections: 4 added, 5 changed, 0 removed
  - Added: `PRINCIPAL DISPLAY PANEL - 11 Tablet Blister Pack - 0069-5450`, `PRINCIPAL DISPLAY PANEL - 2 Tablet Blister Pack - 0069-5434`, `PRINCIPAL DISPLAY PANEL - Kit Carton - 0069-5434`, `PRINCIPAL DISPLAY PANEL – Kit Carton - 0069-5450`
  - Changed: `16 HOW SUPPLIED/STORAGE AND HANDLING > SPL UNCLASSIFIED SECTION`, `PRINCIPAL DISPLAY PANEL - 2 Tablet Blister Pack - 0069-5317`, `PRINCIPAL DISPLAY PANEL - 3 Tablet Blister Pack - 0069-5045`, `PRINCIPAL DISPLAY PANEL - 3 Tablet Blister Pack - 0069-5321`, `SPL UNCLASSIFIED SECTION`
- Verdicts: changed 0 · broken 0 · still valid 0

#### 16 HOW SUPPLIED/STORAGE AND HANDLING > SPL UNCLASSIFIED SECTION

```diff
@@ -1,4 +1,6 @@
 How Supplied PAXLOVID is nirmatrelvir tablets co-packaged with ritonavir tablets. It is supplied in three different Dose Packs. Nirmatrelvir tablets and ritonavir tablets are supplied in separate blister cavities within the same child-resistant blister card. Dose Pack Content NDC Description 300 mg nirmatrelvir; 100 mg ritonavir Each Carton Contains: 30 tablets divided in10 blister cards 0069-5045-30 Nirmatrelvir tablets: Oval, pink immediate-release, film-coated tablets debossed with "PFE" on one side and "3CL" on the other side. Ritonavir tablets: White to off-white, capsule-shaped, film-coated tablets debossed with "H" on one side and “R9” on the other side. Or 0069-5321-30 Nirmatrelvir tablets: Oval, pink immediate-release, film-coated tablets debossed with "PFE" on one side and "3CL" on the other side. Ritonavir tablets: White film-coated ovaloid tablets debossed with "NK" on one side.
 Ritonavir tablets: White film-coated ovaloid tablets debossed with "NK" on one side. Each Blister Card Contains: 2 nirmatrelvir tablets(150 mg each) and1 ritonavir tablet(100 mg) 0069-5045-06 Nirmatrelvir tablets: Oval, pink immediate-release, film-coated tablets debossed with "PFE" on one side and "3CL" on the other side. Ritonavir tablets: White to off-white, capsule-shaped, film-coated tablets debossed with "H" on one side and “R9” on the other side. Or 0069-5321-03 Nirmatrelvir tablets: Oval, pink immediate-release, film-coated tablets debossed with "PFE" on one side and "3CL" on the other side. Ritonavir tablets: White film-coated ovaloid tablets debossed with "NK" on one side.
-Ritonavir tablets: White film-coated ovaloid tablets debossed with "NK" on one side. 150 mg nirmatrelvir; 100 mg ritonavir Each Carton Contains: 20 tablets divided in10 blister cards 0069-5317-20 Nirmatrelvir tablets: Oval, pink immediate-release, film-coated tablets debossed with "PFE" on one side and "3CL" on the other side. Ritonavir tablets: White film-coated ovaloid tablets debossed with “NK” on one side. Each Blister Card Contains: 1 nirmatrelvir tablet (150 mg) and 1 ritonavir tablet (100 mg) 0069-5317-02 Nirmatrelvir tablets: Oval, pink immediate-release, film-coated tablets debossed with "PFE" on one side and "3CL" on the other side. Ritonavir tablets: White film-coated ovaloid tablets debossed with “NK” on one side.
-Ritonavir tablets: White film-coated ovaloid tablets debossed with “NK” on one side. 300 mg nirmatrelvir; 100 mg ritonavir (Day 1) 150 mg nirmatrelvir;100 mg ritonavir (Days 2-5) Each Carton Contains: 11 tablets in 1 blister card 0069-0521-11 Nirmatrelvir tablets: Oval, pink immediate-release, film-coated tablets debossed with "PFE" on one side and "3CL" on the other side. Ritonavir tablets: White film-coated ovaloid tablets debossed with “NK” on one side. Each Blister Card Contains: 6 nirmatrelvir tablets (150 mg) and 5 ritonavir tablets (100 mg) 0069-0521-11 Nirmatrelvir tablets: Oval, pink immediate-release, film-coated tablets debossed with "PFE" on one side and "3CL" on the other side. Ritonavir tablets: White film-coated ovaloid tablets debossed with “NK” on one side.
+Ritonavir tablets: White film-coated ovaloid tablets debossed with "NK" on one side. 150 mg nirmatrelvir; 100 mg ritonavir Each Carton Contains: 20 tablets divided in10 blister cards 0069-5317-20 Nirmatrelvir tablets: Oval, pink immediate-release, film-coated tablets debossed with "PFE" on one side and "3CL" on the other side. Ritonavir tablets: White film-coated ovaloid tablets debossed with “NK” on one side. Or 0069-5434-20 Nirmatrelvir tablets: Oval, pink immediate‑release, film‑coated tablets debossed with "PFE" on one side and "3CL" on the other side. Ritonavir tablets: White to off-white, capsule‑shaped, film‑coated tablets debossed with “H” on one side and “R9” on the other side.
... diff truncated
```

#### PRINCIPAL DISPLAY PANEL - 2 Tablet Blister Pack - 0069-5317

```diff
@@ -1 +1 @@
-NDC 0069-5317-02Rx only nirmatrelvirtablet(150 mg) This cavityintentionallyleft empty Take these 2 tabletstogether PAXLOVID™(nirmatrelvir tablets;ritonavir tablets),co-packaged for oral use150 mg; 100 mg This cavityintentionallyleft empty ritonavirtablet(100 mg) Dist. by Pfizer LabsDiv. of Pfizer Inc., NY, NY 10001 (01)10300695317023 LOT:EXP:PAA206982
+NDC 0069-5317-02Rx only nirmatrelvirtablet(150 mg) This cavityintentionallyleft empty Take these 2 tabletstogether PAXLOVID™(nirmatrelvir tablets;ritonavir tablets),co-packaged for oral use150 mg; 100 mg This cavityintentionallyleft empty ritonavirtablet(100 mg) Dist. by Pfizer LabsDiv. of Pfizer Inc., NY, NY 10001 LOT:EXP:PAA206982
```

#### PRINCIPAL DISPLAY PANEL - 3 Tablet Blister Pack - 0069-5045

```diff
@@ -1 +1 @@
-NDC 0069-5045-06 PAXLOVID™(nirmatrelvir tablets;ritonavir tablets),co-packaged for oral use300 mg; 100 mg nirmatrelvirtablet(150 mg) Take these 3 tabletstogether ritonavirtablet(100 mg) nirmatrelvirtablet(150 mg) Rx only PAA232044Dist. by Pfizer LabsDiv. of Pfizer Inc., NY, NY 10001 (01)10300695045063 LOT: EXP:
+NDC 0069-5045-06 PAXLOVID™(nirmatrelvir tablets;ritonavir tablets),co-packaged for oral use300 mg; 100 mg nirmatrelvirtablet(150 mg) Take these 3 tabletstogether ritonavirtablet(100 mg) nirmatrelvirtablet(150 mg) Rx only PAA232044Dist. by Pfizer LabsDiv. of Pfizer Inc., NY, NY 10001 LOT:EXP:
```

### 2025-07-08 · JANTOVEN (WARFARIN SODIUM) TABLET [UPSHER-SMITH LABORATORIES, LLC] · v9 → v10

`19a69a72-ac5d-45d5-a94d-a5aaecbe4730` (openfda) · version key `11` → `13`

- Sections: 1 added, 26 changed, 1 removed
  - Added: `SPL product data elements section`
  - Changed: `1 INDICATIONS AND USAGE`, `10 OVERDOSAGE > 10.2 Treatment`, `11 DESCRIPTION`, `12 CLINICAL PHARMACOLOGY > 12.1 Mechanism of Action`, `12 CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > SPL UNCLASSIFIED SECTION [3]`, `12 CLINICAL PHARMACOLOGY > 12.5 Pharmacogenomics > SPL UNCLASSIFIED SECTION`, `14 CLINICAL STUDIES > 14.1 Atrial Fibrillation`, `14 CLINICAL STUDIES > 14.2 Mechanical and Bioprosthetic Heart Valves`, `14 CLINICAL STUDIES > 14.3 Myocardial Infarction`, `17 PATIENT COUNSELING INFORMATION > SPL UNCLASSIFIED SECTION [4]` (+16 more)
  - Removed: `SPL PRODUCT DATA ELEMENTS SECTION`
- Verdicts: changed 0 · broken 0 · still valid 0

#### 1 INDICATIONS AND USAGE

```diff
@@ -1 +1 @@
-JANTOVEN® is indicated for: Prophylaxis and treatment of venous thrombosis and its extension, pulmonary embolism (PE). Prophylaxis and treatment of thromboembolic complications associated with atrial fibrillation (AF) and/or cardiac valve replacement. Reduction in the risk of death, recurrent myocardial infarction (MI), and thromboembolic events such as stroke or systemic embolization after myocardial infarction. Limitations of Use Warfarin Sodium has no direct effect on an established thrombus, nor does it reverse ischemic tissue damage. Once a thrombus has occurred, however, the goals of anticoagulant treatment are to prevent further extension of the formed clot and to prevent secondary thromboembolic complications that may result in serious and possibly fatal sequelae.
+JANTOVEN ®is indicated for: Prophylaxis and treatment of venous thrombosis and its extension, pulmonary embolism (PE). Prophylaxis and treatment of thromboembolic complications associated with atrial fibrillation (AF) and/or cardiac valve replacement. Reduction in the risk of death, recurrent myocardial infarction (MI), and thromboembolic events such as stroke or systemic embolization after myocardial infarction. Limitations of Use Warfarin Sodium has no direct effect on an established thrombus, nor does it reverse ischemic tissue damage. Once a thrombus has occurred, however, the goals of anticoagulant treatment are to prevent further extension of the formed clot and to prevent secondary thromboembolic complications that may result in serious and possibly fatal sequelae.
```

#### 10 OVERDOSAGE > 10.2 Treatment

```diff
@@ -1 +1,2 @@
-The treatment of excessive anticoagulation is based on the level of the INR, the presence or absence of bleeding, and clinical circumstances. Reversal of JANTOVEN anticoagulation may be obtained by discontinuing JANTOVEN therapy and, if necessary, by administration of oral or parenteral vitamin K1. The use of vitamin K1 reduces response to subsequent JANTOVEN therapy and patients may return to a pretreatment thrombotic status following the rapid reversal of a prolonged INR. Resumption of JANTOVEN administration reverses the effect of vitamin K, and a therapeutic INR can again be obtained by careful dosage adjustment. If rapid re-anticoagulation is indicated, heparin may be preferable for initial therapy. Prothrombin complex concentrate (PCC), fresh frozen plasma, or activated Factor VII treatment may be considered if the requirement to reverse the effects of JANTOVEN is urgent. A risk of hepatitis and other viral diseases is associated with the use of blood products; PCC and activated Factor VII are also associated with an increased risk of thrombosis. Therefore, these preparations should be used only in exceptional or life-threatening bleeding episodes secondary to JANTOVEN overdosage.
+The treatment of excessive anticoagulation is based on the level of the INR, the presence or absence of bleeding, and clinical circumstances. Reversal of JANTOVEN anticoagulation may be obtained by discontinuing JANTOVEN therapy and, if necessary, by administration of oral or parenteral vitamin K 1. The use of vitamin K 1reduces response to subsequent JANTOVEN therapy and patients may return to a pretreatment thrombotic status following the rapid reversal of a prolonged INR. Resumption of JANTOVEN administration reverses the effect of vitamin K, and a therapeutic INR can again be obtained by careful dosage adjustment. If rapid re-anticoagulation is indicated, heparin may be preferable for initial therapy. Prothrombin complex concentrate (PCC), fresh frozen plasma, or activated Factor VII treatment may be considered if the requirement to reverse the effects of JANTOVEN is urgent. A risk of hepatitis and other viral diseases is associated with the use of blood products; PCC and activated Factor VII are also associated with an increased risk of thrombosis.
+Therefore, these preparations should be used only in exceptional or life-threatening bleeding episodes secondary to JANTOVEN overdosage.
```

#### 11 DESCRIPTION

```diff
@@ -1,2 +1,2 @@
-JANTOVEN (Warfarin Sodium Tablets, USP) is an anticoagulant that acts by inhibiting vitamin K-dependent coagulation factors. The chemical name of warfarin sodium is 3-(α-acetonylbenzyl)-4-hydroxycoumarin sodium salt, which is a racemic mixture of the R- and S-enantiomers. Crystalline warfarin sodium is an isopropanol clathrate. Its empirical formula is C19H15NaO4, and its structural formula is represented by the following: Crystalline warfarin sodium occurs as a white, odorless, crystalline powder that is discolored by light. It is very soluble in water, freely soluble in alcohol, and very slightly soluble in chloroform and ether. JANTOVEN tablets for oral use contain: 1 mg, 2 mg, 2½ mg, 3 mg, 4 mg, 5 mg, 6 mg, 7½ mg or 10 mg of warfarin sodium, USP.
+JANTOVEN (Warfarin Sodium Tablets, USP) is an anticoagulant that acts by inhibiting vitamin K-dependent coagulation factors. The chemical name of warfarin sodium is 3-(α-acetonylbenzyl)-4-hydroxycoumarin sodium salt, which is a racemic mixture of the R- and S-enantiomers. Crystalline warfarin sodium is an isopropanol clathrate. Its empirical formula is C 19H 15NaO 4, and its structural formula is represented by the following: Crystalline warfarin sodium occurs as a white, odorless, crystalline powder that is discolored by light. It is very soluble in water, freely soluble in alcohol, and very slightly soluble in chloroform and ether. JANTOVEN tablets for oral use contain: 1 mg, 2 mg, 2½ mg, 3 mg, 4 mg, 5 mg, 6 mg, 7½ mg or 10 mg of warfarin sodium, USP.
 They also contain: All strengths: Lactose monohydrate, magnesium stearate, povidone, and pregelatinized starch (corn). 1 mg: FD&C Red #40 Aluminum Lake 2 mg: FD&C Blue #2 Aluminum Lake and FD&C Red #40 Aluminum Lake 2½ mg: D&C Yellow #10 Aluminum Lake and FD&C Blue #1 Aluminum Lake 3 mg: Brown #75 Synthetic Brown Iron Oxide 4 mg: FD&C Blue #1 Aluminum Lake 5 mg: FD&C Yellow #6 Aluminum Lake 6 mg: Yellow #10 Synthetic Yellow Iron Oxide, Black #85 Synthetic Black Iron Oxide and FD&C Blue #1 Aluminum Lake 7½ mg: D&C Yellow #10 Aluminum Lake and FD&C Yellow #6 Aluminum Lake 10 mg: Dye Free
```

### 2025-06-20 · PAXLOVID (NIRMATRELVIR AND RITONAVIR) KIT [PFIZER LABORATORIES DIV PFIZER INC] · v5 → v6

`8a99d6d6-fd9e-45bb-b1bf-48c7f761232a` (openfda) · version key `7` → `9`

- Sections: 0 added, 1 changed, 0 removed
  - Changed: `PRINCIPAL DISPLAY PANEL - 3 Tablet Blister Pack - 0069-5045`
- Verdicts: changed 0 · broken 0 · still valid 0

#### PRINCIPAL DISPLAY PANEL - 3 Tablet Blister Pack - 0069-5045

```diff
@@ -1 +1 @@
-NDC 0069-5045-06 PAXLOVID™(nirmatrelvir tablets;ritonavir tablets),co-packaged for oral use300 mg; 100 mg nirmatrelvirtablet(150 mg) Take these 3 tabletstogether ritonavirtablet(100 mg) nirmatrelvirtablet(150 mg) Rx only PAA203000Dist. by Pfizer LabsDiv. of Pfizer Inc., NY, NY 10001 (01)10300695045063 LOT:XXXXXXXEXP:MM/YYYY
+NDC 0069-5045-06 PAXLOVID™(nirmatrelvir tablets;ritonavir tablets),co-packaged for oral use300 mg; 100 mg nirmatrelvirtablet(150 mg) Take these 3 tabletstogether ritonavirtablet(100 mg) nirmatrelvirtablet(150 mg) Rx only PAA232044Dist. by Pfizer LabsDiv. of Pfizer Inc., NY, NY 10001 (01)10300695045063 LOT: EXP:
```

### 2025-05-30 · PLAVIX (CLOPIDOGREL) TABLET, FILM COATED [SANOFI-AVENTIS U.S. LLC] · v3 → v4

`de8b0b67-eb25-4684-83b5-7ad785314227` (openfda) · version key `3` → `5`

- Sections: 0 added, 2 changed, 0 removed
  - Changed: `SPL UNCLASSIFIED SECTION`, `SPL UNCLASSIFIED SECTION [2]`
- Verdicts: changed 0 · broken 0 · still valid 0

#### SPL UNCLASSIFIED SECTION

```diff
@@ -1 +1 @@
-Manufactured by:sanofi-aventis U.S. LLCBridgewater, NJ 08807A SANOFI COMPANY
+Manufactured by:sanofi-aventis U.S. LLCMorristown, NJ 07960A SANOFI COMPANY
```

#### SPL UNCLASSIFIED SECTION [2]

```diff
@@ -1 +1 @@
-Revised: September 2022 Manufactured by:sanofi-aventis U.S. LLCBridgewater, NJ 08807A SANOFI COMPANY Plavix® is a registered trademark of sanofi-aventis.All other trademarks are property of their respective owners.
+Revised: May 2025 Manufactured by:sanofi-aventis U.S. LLCMorristown, NJ 07960A SANOFI COMPANY Plavix® is a registered trademark of sanofi-aventis.All other trademarks are property of their respective owners.
```

### 2025-02-20 · PAXLOVID (NIRMATRELVIR AND RITONAVIR) KIT [PFIZER LABORATORIES DIV PFIZER INC] · v4 → v5

`8a99d6d6-fd9e-45bb-b1bf-48c7f761232a` (openfda) · version key `6` → `7`

- Sections: 0 added, 8 changed, 0 removed
  - Changed: `12 CLINICAL PHARMACOLOGY > 12.4 Microbiology > SPL UNCLASSIFIED SECTION`, `12 CLINICAL PHARMACOLOGY > 12.4 Microbiology > SPL UNCLASSIFIED SECTION [2]`, `16 HOW SUPPLIED/STORAGE AND HANDLING > SPL UNCLASSIFIED SECTION`, `2 DOSAGE AND ADMINISTRATION > 2.3 Dosage in Patients with Renal Impairment`, `4 CONTRAINDICATIONS`, `7 DRUG INTERACTIONS > 7.3 Established and Other Potentially Significant Drug Interactions`, `SPL PATIENT PACKAGE INSERT SECTION`, `SPL UNCLASSIFIED SECTION`
- Verdicts: changed 0 · broken 0 · still valid 0

#### 12 CLINICAL PHARMACOLOGY > 12.4 Microbiology > SPL UNCLASSIFIED SECTION

```diff
@@ -1,4 +1,4 @@
-Antiviral Activity Cell Culture Antiviral Activity Nirmatrelvir exhibited antiviral activity against SARS-CoV-2 (USA-WA1/2020 isolate) infection of differentiated normal human bronchial epithelial (dNHBE) cells with EC50 and EC90 values of 62 nM (31 ng/mL) and 181 nM (90 ng/mL), respectively, after 3 days of drug exposure. The antiviral activity of nirmatrelvir against the Omicron sub-variants BA.2, BA.2.12.1, BA.4, BA.4.6, BA.5, BF.7, BQ.1, BQ.1.11, and XBB.1.5 was assessed in Vero E6-TMPRSS2 cells in the presence of a P-gp inhibitor. Nirmatrelvir had a median EC50 value of 73 nM (range: 39-146 nM) against the Omicron sub-variants, reflecting EC50 value fold changes ≤1.5 relative to the USA-WA1/2020 isolate.
+Antiviral Activity Cell Culture Antiviral Activity Nirmatrelvir exhibited antiviral activity against SARS-CoV-2 (USA-WA1/2020 isolate) infection of differentiated normal human bronchial epithelial (dNHBE) cells with EC50 and EC90 values of 62 nM (31 ng/mL) and 181 nM (90 ng/mL), respectively, after 3 days of drug exposure. The antiviral activity of nirmatrelvir against the Omicron sub-variants BA.2, BA.2.12.1, BA.4, BA.4.6, BA.5, BF.7, BQ.1, BQ.1.11, XBB.1.5, EG.5, and JN.1 was assessed in Vero E6-TMPRSS2 cells in the presence of a P-gp inhibitor. Nirmatrelvir had a median EC50 value of 88 nM (range: 39-146 nM) against the Omicron sub-variants, reflecting EC50 value fold changes ≤1.8 relative to the USA-WA1/2020 isolate.
 In addition, the antiviral activity of nirmatrelvir against the SARS-CoV-2 Alpha, Beta, Gamma, Delta, Lambda, Mu, and Omicron BA.1 variants was assessed in Vero E6 P-gp knockout cells. Nirmatrelvir had a median EC50 value of 25 nM (range: 16-141 nM). The Beta variant was the least susceptible variant tested, with an EC50 value fold change of 3.7 relative to USA-WA1/2020. The other variants had EC50 value fold changes ≤1.1 relative to USA-WA1/2020.
 The other variants had EC50 value fold changes ≤1.1 relative to USA-WA1/2020. Clinical Antiviral Activity In clinical trial EPIC-HR, which enrolled subjects who were primarily infected with the SARS-CoV-2 Delta variant, PAXLOVID treatment was associated with a 0.83 log10 copies/mL greater median decline in viral RNA shedding levels in nasopharyngeal samples through Day 5 (mITT1 analysis set, all treated subjects with onset of symptoms ≤5 days who at baseline did not receive nor were expected to receive COVID-19 therapeutic mAb treatment); similar results were observed in the mITT2 analysis set (all treated subjects with onset of symptoms ≤5 days). In the EPIC-SR trial, which included subjects who were infected with SARS-CoV-2 Delta (79%) or Omicron (19%) variants, PAXLOVID treatment was associated with a 1.05 log10 copies/mL greater median decline in viral RNA shedding levels in nasopharyngeal samples through Day 5, with similar declines observed in subjects infected with Delta or Omicron variants.
 The degree of reduction in viral RNA levels relative to placebo following 5 days of PAXLOVID treatment was similar between unvaccinated high-risk subjects in EPIC-HR and vaccinated high-risk subjects in EPIC-SR.
```

#### 12 CLINICAL PHARMACOLOGY > 12.4 Microbiology > SPL UNCLASSIFIED SECTION [2]

```diff
@@ -1,7 +1,7 @@
 Antiviral Resistance In Cell Culture and Biochemical Assays SARS-CoV-2 Mpro residues potentially associated with nirmatrelvir resistance have been identified using a variety of methods, including SARS-CoV-2 resistance selection, testing of recombinant SARS-CoV-2 viruses with Mpro substitutions, and biochemical assays with recombinant SARS-CoV-2 Mpro containing amino acid substitutions. Table 7 indicates Mpro substitutions and combinations of Mpro substitutions that have been observed in SARS-CoV-2 under nirmatrelvir selective pressure in cell culture. Individual Mpro substitutions are listed regardless of whether they occurred alone or in combination with other Mpro substitutions. Note that the Mpro S301P and T304I substitutions overlap the P6 and P3 positions of the nsp5/nsp6 cleavage site located at the C-terminus of Mpro. Substitutions at other Mpro cleavage sites have not been associated with nirmatrelvir resistance in cell culture. The clinical significance of these substitutions is unknown. Abbreviation: ND=no data.
 The clinical significance of these substitutions is unknown. Abbreviation: ND=no data. Table 7: SARS-CoV-2 Mpro Amino Acid Substitutions Selected by Nirmatrelvir in Cell Culture EC50 value fold change ranges are shown in instances where multiple data points have been reported.
-Single Substitutions (EC50 value fold change in cell culture) T21I (1.1-4.6), S46F (ND), L50F (1.2-4.2), P108S (ND), T135I (ND), F140L (4.1), S144A (2.2-5.3), C160F (2.1), E166A (3.3), E166V (25‑288), L167F (1.9-2.5), T169I (ND), H172Y (15), A173V (0.9-2.3), V186A (ND), R188G (ND), A191V (0.7-1.5), A193P (ND), P252L (5.9), S301P (ND), and T304I (1.4-5.5).
-≥2 Substitutions (EC50 value fold change in cell culture) T21I+S144A (9.4), T21I+E166V (83-250), T21I+A173V (3.1), T21I+T304I (3.0-7.9), L50F+E166V (34-175), L50F+T304I (5.9), T135I+T304I (3.8), F140L+A173V (10-17), H172Y+P252L (ND), A173V+T304I (5.8-20), T21I+L50F+A193P+S301P (29), T21I+S144A+T304I (11-28), T21I+C160F+A173V+V186A+T304I (28-29), T21I+A173V+T304I (15-16), and L50F+F140L+L167F+T304I (43-55).
+Single Substitutions (EC50 value fold change in cell culture) T21I (1.1-4.8), S46F (ND), L50F (1.2-4.2), P108S (ND), T135I (ND), F140L (4.1), S144A (2.2-5.3), C160F (2.1), E166A (3.3), E166V (25‑288), L167F (1.9-2.5), T169I (ND), H172Y (15), A173V (0.9-2.3), V186A (ND), R188G (ND), A191V (0.7-1.5), A193P (ND), P252L (5.9), S301P (ND), and T304I (1.4-5.5).
+≥2 Substitutions (EC50 value fold change in cell culture) T21I+S144A (9.4), T21I+E166V (83-250), T21I+A173V (3.1-8.9), T21I+T304I (3.0-7.9), L50F+E166V (34-175), L50F+T304I (5.9), T135I+T304I (3.8), F140L+A173V (10-17), H172Y+P252L (ND), A173V+T304I (5.8-20), T21I+L50F+A193P+S301P (29), T21I+S144A+T304I (11-28), T21I+C160F+A173V+V186A+T304I (28-29), T21I+A173V+T304I (15-16), and L50F+F140L+L167F+T304I (43-55).
 Table 8 indicates Mpro substitutions and combinations of Mpro substitutions that have been found to reduce nirmatrelvir activity ≥3-fold (based on IC50 or Ki values) in biochemical assays using recombinant SARS-CoV-2 Mpro. Note that these Mpro substitutions were laboratory engineered and most were not observed in PAXLOVID-treated subjects in clinical trials. In addition, according to public sequence databases, most of these substitutions have not been observed in clinical isolates or have been observed but with global cumulative frequencies ≤0.002%. Thus, the clinical relevance of these substitutions is unclear. The following Mpro substitutions and combinations of Mpro substitutions emerged in cell culture in the presence of nirmatrelvir but conferred <3-fold reduced nirmatrelvir activity in biochemical assays: T21I, S46F, L50F, P108S, T135I, C160F, T169I, V186A, A191V, A193P, P252L, S301P, T304I, T21I+T304I, and L50F+T304I.
... diff truncated
```

#### 16 HOW SUPPLIED/STORAGE AND HANDLING > SPL UNCLASSIFIED SECTION

```diff
@@ -1,4 +1,4 @@
-How Supplied PAXLOVID is nirmatrelvir tablets co-packaged with ritonavir tablets. It is supplied in three different Dose Packs. Nirmatrelvir tablets and ritonavir tablets are supplied in separate blister cavities within the same child-resistant blister card. Dose Pack Content NDC Description 300 mg nirmatrelvir; 100 mg ritonavir Each Carton Contains: 30 tablets divided in10 blister cards 0069-5045-30 Nirmatrelvir tablets: Oval, pink immediate-release, film-coated tablets debossed with "PFE" on one side and "3CL" on the other side. Ritonavir tablets: White to off-white, capsule-shaped, film-coated tablets debossed with "H"on one side and “R9” on the other side. Or 0069-5321-30 Nirmatrelvir tablets: Oval, pink immediate-release, film-coated tablets debossed with "PFE" on one side and "3CL" on the other side. Ritonavir tablets: White film-coated ovaloid tablets debossed with "NK" on one side.
+How Supplied PAXLOVID is nirmatrelvir tablets co-packaged with ritonavir tablets. It is supplied in three different Dose Packs. Nirmatrelvir tablets and ritonavir tablets are supplied in separate blister cavities within the same child-resistant blister card. Dose Pack Content NDC Description 300 mg nirmatrelvir; 100 mg ritonavir Each Carton Contains: 30 tablets divided in10 blister cards 0069-5045-30 Nirmatrelvir tablets: Oval, pink immediate-release, film-coated tablets debossed with "PFE" on one side and "3CL" on the other side. Ritonavir tablets: White to off-white, capsule-shaped, film-coated tablets debossed with "H" on one side and “R9” on the other side. Or 0069-5321-30 Nirmatrelvir tablets: Oval, pink immediate-release, film-coated tablets debossed with "PFE" on one side and "3CL" on the other side. Ritonavir tablets: White film-coated ovaloid tablets debossed with "NK" on one side.
 Ritonavir tablets: White film-coated ovaloid tablets debossed with "NK" on one side. Each Blister Card Contains: 2 nirmatrelvir tablets(150 mg each) and1 ritonavir tablet(100 mg) 0069-5045-06 Nirmatrelvir tablets: Oval, pink immediate-release, film-coated tablets debossed with "PFE" on one side and "3CL" on the other side. Ritonavir tablets: White to off-white, capsule-shaped, film-coated tablets debossed with "H" on one side and “R9” on the other side. Or 0069-5321-03 Nirmatrelvir tablets: Oval, pink immediate-release, film-coated tablets debossed with "PFE" on one side and "3CL" on the other side. Ritonavir tablets: White film-coated ovaloid tablets debossed with "NK" on one side.
 Ritonavir tablets: White film-coated ovaloid tablets debossed with "NK" on one side. 150 mg nirmatrelvir; 100 mg ritonavir Each Carton Contains: 20 tablets divided in10 blister cards 0069-5317-20 Nirmatrelvir tablets: Oval, pink immediate-release, film-coated tablets debossed with "PFE" on one side and "3CL" on the other side. Ritonavir tablets: White film-coated ovaloid tablets debossed with “NK” on one side. Each Blister Card Contains: 1 nirmatrelvir tablet (150 mg) and 1 ritonavir tablet (100 mg) 0069-5317-02 Nirmatrelvir tablets: Oval, pink immediate-release, film-coated tablets debossed with "PFE" on one side and "3CL" on the other side. Ritonavir tablets: White film-coated ovaloid tablets debossed with “NK” on one side.
... diff truncated
```

### 2025-02-07 · PAXLOVID (NIRMATRELVIR AND RITONAVIR) KIT [PFIZER LABORATORIES DIV PFIZER INC] · v3 → v4

`8a99d6d6-fd9e-45bb-b1bf-48c7f761232a` (openfda) · version key `4` → `6`

- Sections: 3 added, 20 changed, 4 removed
  - Added: `PRINCIPAL DISPLAY PANEL - 11 Tablet Blister Pack - 0069-0521`, `PRINCIPAL DISPLAY PANEL – Kit Carton - 0069-0521`, `RECENT MAJOR CHANGES SECTION`
  - Changed: `12 CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics`, `12 CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > SPL UNCLASSIFIED SECTION`, `12 CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > SPL UNCLASSIFIED SECTION > SPL UNCLASSIFIED SECTION [3]`, `12 CLINICAL PHARMACOLOGY > 12.4 Microbiology > SPL UNCLASSIFIED SECTION`, `12 CLINICAL PHARMACOLOGY > 12.4 Microbiology > SPL UNCLASSIFIED SECTION [2]`, `14 CLINICAL STUDIES > 14.1 Efficacy in Subjects at High Risk of Progression to Severe COVID-19 (EPIC-HR)`, `16 HOW SUPPLIED/STORAGE AND HANDLING > SPL UNCLASSIFIED SECTION`, `17 PATIENT COUNSELING INFORMATION > SPL UNCLASSIFIED SECTION`, `2 DOSAGE AND ADMINISTRATION > 2.1 Important Dosage and Administration Information`, `2 DOSAGE AND ADMINISTRATION > 2.2 Recommended Dosage` (+10 more)
  - Removed: `PRINCIPAL DISPLAY PANEL - 2 Tablet Blister Pack - 0069-5017`, `PRINCIPAL DISPLAY PANEL - 3 Tablet Blister Pack - 0069-5001`, `PRINCIPAL DISPLAY PANEL - Kit Carton - 0069-5001`, `PRINCIPAL DISPLAY PANEL - Kit Carton - 0069-5017`
- Verdicts: changed 0 · broken 0 · still valid 0

#### 12 CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics

```diff
@@ -1,6 +1,6 @@
-The pharmacokinetics of nirmatrelvir/ritonavir were similar in healthy subjects and in subjects with mild-to-moderate COVID-19. Nirmatrelvir AUC increased in a less than dose proportional manner over a single dose range from 250 mg to 750 mg (0.83 to 2.5 times the approved recommended dose) and multiple dose range from 75 mg to 500 mg (0.25 to 1.67 times the approved recommended dose), when administered in combination with 100 mg ritonavir. Nirmatrelvir steady state was achieved on Day 2 following administration of the approved recommended dosage and the mean accumulation ratio was approximately 2-fold. The pharmacokinetic properties of nirmatrelvir/ritonavir are displayed in Table 2.
-The pharmacokinetic properties of nirmatrelvir/ritonavir are displayed in Table 2. Table 2: Pharmacokinetic Properties of Nirmatrelvir and Ritonavir in Healthy Subjects Nirmatrelvir (When Given With Ritonavir) Ritonavir Abbreviations: CL/F=apparent clearance; hr=hour; L/hr=liters per hour; T½=terminal elimination half-life; Tmax=the time to reach Cmax; Vz/F=apparent volume of distribution. Absorption Tmax (hr), median 3.00Represents data after a single dose of 300 mg nirmatrelvir (2 × 150 mg tablet formulation) administered together with 100 mg ritonavir tablet in healthy subjects.
+The pharmacokinetics of nirmatrelvir/ritonavir were similar in healthy subjects and in subjects with mild-to-moderate COVID-19. Nirmatrelvir AUC increased in a less than dose proportional manner over a single dose range from 250 mg to 750 mg (0.83 to 2.5 times the approved recommended dose) and multiple dose range from 75 mg to 500 mg (0.25 to 1.67 times the approved recommended dose), when administered in combination with 100 mg ritonavir. Nirmatrelvir steady state was achieved on Day 2 following administration of the approved recommended dosage and the mean accumulation ratio was approximately 2-fold. The pharmacokinetic properties of nirmatrelvir/ritonavir are displayed in Table 3.
+The pharmacokinetic properties of nirmatrelvir/ritonavir are displayed in Table 3. Table 3: Pharmacokinetic Properties of Nirmatrelvir and Ritonavir in Healthy Subjects Nirmatrelvir (When Given With Ritonavir) Ritonavir Abbreviations: CL/F=apparent clearance; hr=hour; L/hr=liters per hour; T½=terminal elimination half-life; Tmax=the time to reach Cmax; Vz/F=apparent volume of distribution. Absorption Tmax (hr), median 3.00Represents data after a single dose of 300 mg nirmatrelvir (2 × 150 mg tablet formulation) administered together with 100 mg ritonavir tablet in healthy subjects.
 3.98 Food effect Test/reference (fed/fasted) ratios of adjusted geometric means (90% CI) AUCinf and Cmax for nirmatrelvir were 119.67 (108.75, 131.68) and 161.01 (139.05, 186.44), respectively.Following a single oral dose of nirmatrelvir 300 mg boosted ritonavir 100 mg at -12 hours, 0 hours and 12 hours, administered under fed (high fat and high calorie meal) or fasted conditions. Distribution % bound to human plasma proteins 69% 98–99% Blood-to-plasma ratio 0.60 0.14Red blood cell to plasma ratio. Vz/F (L), mean 104.7300 mg nirmatrelvir (oral suspension formulation) co-administered with 100 mg ritonavir (tablet formulation) twice daily for 3 days.
 112.4 Elimination Major route of elimination Renal elimination Hepatic metabolism Half-life (T½) (hr), mean 6.05 6.15 Oral clearance (CL/F) (L/hr), mean 8.99 13.92 Metabolism Metabolic pathways Nirmatrelvir is a CYP3A substrate but when dosed with ritonavir, metabolic clearance is minimal. Major CYP3A, Minor CYP2D6 Excretion % drug-related material in feces 35.3%Determined by 19F-NMR analysis following 300 mg nirmatrelvir oral suspension administered at 0 hr enhanced with 100 mg ritonavir at -12 hours, 0 hours, 12 hours, and 24 hours. 86.4%Determined by 14C analysis following 600 mg 14C-ritonavir oral solution (6 times the approved ritonavir dose).
... diff truncated
```

#### 12 CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > SPL UNCLASSIFIED SECTION

```diff
@@ -1 +1 @@
-Effect of Food No clinically significant differences in the pharmacokinetics of nirmatrelvir were observed following administration of a high fat meal (800-1000 calories; 50% fat) to healthy subjects.
+Effect of Food No clinically significant differences in the pharmacokinetics of nirmatrelvir were observed following administration of a high fat meal (800-1,000 calories; 50% fat) to healthy subjects.
```

#### 12 CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > SPL UNCLASSIFIED SECTION > SPL UNCLASSIFIED SECTION [3]

```diff
@@ -1,3 +1,2 @@
-Patients with Renal Impairment The pharmacokinetics of nirmatrelvir in patients with renal impairment following administration of a single oral dose of nirmatrelvir 100 mg (0.33 times the approved recommended dose) co-administered with ritonavir 100 mg are presented in Table 4. Compared to healthy controls with no renal impairment, the Cmax and AUC of nirmatrelvir in patients with mild renal impairment was 30% and 24% higher, in patients with moderate renal impairment was 38% and 87% higher, and in patients with severe renal impairment was 48% and 204% higher, respectively.
-Table 4: Impact of Renal Impairment on Nirmatrelvir/Ritonavir Pharmacokinetics Normal Renal Function (n=8) Mild Renal Impairment (n=8) Moderate Renal Impairment (n=8) Severe Renal Impairment (n=8) Abbreviations: AUCinf=area under the plasma concentration-time profile from time zero extrapolated to infinite time; Cmax=the observed maximum concentration; CV=coefficient of variation; SD=standard deviation; T½=terminal elimination half-life; Tmax=the time to reach Cmax.Values are presented as geometric mean (geometric % CV) except median (range) for Tmax and arithmetic mean ± SD for T½.
-Cmax (µg/mL) 1.60 (31) 2.08 (29) 2.21 (17) 2.37 (38) AUCinf (µg*hr/mL) 14.46 (20) 17.91 (30) 27.11 (27) 44.04 (33) Tmax (hr) 2.0 (1.0 – 4.0) 2.0 (1.0 – 3.0) 2.50 (1.0 – 6.0) 3.0 (1.0 – 6.1) T½ (hr) 7.73 ± 1.82 6.60 ± 1.53 9.95 ± 3.42 13.37 ± 3.32
+Patients with Renal Impairment The pharmacokinetics of nirmatrelvir in subjects with renal impairment following administration of a single oral dose of nirmatrelvir 100 mg (0.33 times the approved recommended dose) co-administered with ritonavir 100 mg were determined. Compared to healthy controls with no renal impairment, the Cmax and AUC of nirmatrelvir in subjects with mild renal impairment was 30% and 24% higher, in subjects with moderate renal impairment was 38% and 87% higher, and in subjects with severe renal impairment was 48% and 204% higher, respectively. The pharmacokinetics of nirmatrelvir in subjects with mild-to-moderate COVID-19 and severe renal impairment (eGFR<30 mL/min) either requiring intermittent hemodialysis (n=12) or not requiring hemodialysis (n=2) were evaluated after administration of 300 mg/100 mg nirmatrelvir/ritonavir once on Day 1 followed by 150 mg/100 mg nirmatrelvir/ritonavir once daily on Days 2-5 for a total of 5 doses.
+The administration of 300 mg/100 mg nirmatrelvir/ritonavir once on Day 1 followed by 150 mg/100 mg nirmatrelvir/ritonavir once daily on Days 2-5 in subjects with severe renal impairment, either requiring intermittent hemodialysis or not requiring hemodialysis resulted in comparable exposures on Day 1 and at steady-state (AUC0-24 and Cmax) compared to those observed in subjects with normal renal function receiving 300 mg/100 mg nirmatrelvir/ritonavir twice daily for 5 days. During a 4-hour hemodialysis session, approximately 6.9% of nirmatrelvir dose was cleared through dialysis. Hemodialysis clearance was 1.83 L/h.
```

### 2024-11-25 · PAXLOVID (NIRMATRELVIR AND RITONAVIR) KIT [PFIZER LABORATORIES DIV PFIZER INC] · v2 → v3

`8a99d6d6-fd9e-45bb-b1bf-48c7f761232a` (openfda) · version key `3` → `4`

- Sections: 0 added, 5 changed, 0 removed
  - Changed: `12 CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > SPL UNCLASSIFIED SECTION [3]`, `8 USE IN SPECIFIC POPULATIONS > 8.2 Lactation > SPL UNCLASSIFIED SECTION`, `8 USE IN SPECIFIC POPULATIONS > 8.2 Lactation > SPL UNCLASSIFIED SECTION [2]`, `SPL PATIENT PACKAGE INSERT SECTION`, `SPL UNCLASSIFIED SECTION`
- Verdicts: changed 0 · broken 0 · still valid 0

#### 12 CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > SPL UNCLASSIFIED SECTION [3]

```diff
@@ -2,5 +2,5 @@
 CI=confidence interval; Cmax=observed maximum plasma concentrations. CarbamazepineCarbamazepine titrated up to 300 mg twice daily on Day 8 through Day 15 (e.g., 100 mg twice daily on Day 1 through Day 3 and 200 mg twice daily on Day 4 through Day 7). 300 mg twice daily (16 doses) 300 mg/100 mg once daily(2 doses) 10 56.82(47.04, 68.62) 44.50(33.77, 58.65) Itraconazole 200 mg once daily (8 doses) 300 mg/100 mg twice daily(5 doses) 11 118.57(112.50, 124.97) 138.82(129.25, 149.11) Table 6 describes the effect of nirmatrelvir/ritonavir on the Cmax and AUCinf of other drugs.
 Table 6: Effect of Nirmatrelvir/Ritonavir on Pharmacokinetics of Other Drugs Co-administered Drug Dose (Schedule) N Percent Ratio of Test/Reference of Geometric Means (90% CI); No Effect=100 Co-administered Drug Nirmatrelvir/ Ritonavir Cmax AUCinf Abbreviations: AUCinf=area under the plasma concentration-time curve from time zero extrapolated to infinite time; CI=confidence interval; Cmax=observed maximum plasma concentrations; CYP3A4=cytochrome P450 3A4; OATP1B1=organic anion transporter polypeptide 1B1; P-gp=p-glycoprotein. MidazolamFor midazolam, Test=nirmatrelvir/ritonavir plus midazolam, Reference=Midazolam. Midazolam is an index substrate for CYP3A4. For dabigatran, Test=nirmatrelvir/ritonavir plus dabigatran, Reference=Dabigatran. Dabigatran is an index substrate for P-gp.
 Dabigatran is an index substrate for P-gp. For rosuvastatin, Test=nirmatrelvir/ritonavir plus rosuvastatin, Reference=Rosuvastatin. Rosuvastatin is an index substrate for OATP1B1.
-Rosuvastatin is an index substrate for OATP1B1. 2 mg (1 dose) 300 mg/100 mg twice daily(9 doses) 10 368.33(318.91, 425.41) 1430.02(1204.54, 1697.71) Dabigatran 75 mg (1 dose) 300 mg/100 mg twice daily(4 doses) 24 233.06(172.14, 315.54) 194.47(155.29, 243.55) Rosuvastatin 10 mg (1 dose) 300 mg/100 mg twice daily (3 doses) 12 212.44 (174.31, 258.90) 131.18 (115.89, 148.48) In Vitro Studies Cytochrome P450 (CYP) Enzymes: •Nirmatrelvir is a reversible and time-dependent inhibitor of CYP3A, but not an inhibitor CYP1A2, CYP2B6, CYP2C8, CYP2C9, CYP2C19, or CYP2D6.
+Rosuvastatin is an index substrate for OATP1B1. 2 mg (1 dose) 300 mg/100 mg twice daily(9 doses) 10 368.33(318.91, 425.41) 1430.02(1204.54, 1697.71) Dabigatran 75 mg (1 dose) 300 mg/100 mg twice daily(4 doses) 24 233.06(172.14, 315.54) 194.47(155.29, 243.55) Rosuvastatin 10 mg (1 dose) 300 mg/100 mg twice daily(3 doses) 12 212.44 (174.31, 258.90) 131.18 (115.89, 148.48) In Vitro Studies Cytochrome P450 (CYP) Enzymes: •Nirmatrelvir is a reversible and time-dependent inhibitor of CYP3A, but not an inhibitor CYP1A2, CYP2B6, CYP2C8, CYP2C9, CYP2C19, or CYP2D6.
 Nirmatrelvir is an inducer of CYP2B6, 2C8, 2C9, and 3A4, but there is minimal risk for pharmacokinetic interactions arising from induction of these CYP enzymes at the proposed therapeutic dose. •Ritonavir is a substrate of CYP2D6 and CYP3A. Ritonavir is an inducer of CYP1A2, CYP2C9, CYP2C19, CYP2B6, and CYP3A. Transporter Systems: Nirmatrelvir is an inhibitor of P-gp and OATP1B1. Nirmatrelvir is a substrate for P-gp, but not BCRP, MATE1, MATE2K, NTCP, OAT1, OAT2, OAT3, OCT1, OCT2, PEPT1, OATP1B1, OATP1B3, OATP2B1, or OATP4C1.
```

#### 8 USE IN SPECIFIC POPULATIONS > 8.2 Lactation > SPL UNCLASSIFIED SECTION

```diff
@@ -1 +1 @@
-Risk Summary There are no available data on the presence of nirmatrelvir in human or animal milk, the effects on the breastfed infant, or the effects on milk production. A transient decrease in body weight was observed in the nursing offspring of rats administered nirmatrelvir (see Data). Limited published data reports that ritonavir is present in human milk. There is no information on the effects of ritonavir on the breastfed infant or the effects of the drug on milk production. The developmental and health benefits of breastfeeding should be considered along with the mother's clinical need for PAXLOVID and any potential adverse effects on the breastfed infant from PAXLOVID or from the underlying maternal condition. Breastfeeding individuals with COVID-19 should follow practices according to clinical guidelines to avoid exposing the infant to COVID-19.
+Risk Summary Nirmatrelvir and ritonavir are present in human breast milk in small amounts (less than 2%). In a clinical lactation study in 8 lactating women, nirmatrelvir and ritonavir were estimated to be present in human milk at a mean weight-normalized infant daily dose of 0.16 mg/kg/day (1.8% of maternal weight-adjusted daily dose) and 0.006 mg/kg/day (0.2% of maternal weight-adjusted daily dose), respectively (see Data). There are no available data on the effects of nirmatrelvir or ritonavir on the breastfed infant or on milk production. The developmental and health benefits of breastfeeding should be considered along with the mother's clinical need for PAXLOVID and any potential adverse effects on the breastfed infant from PAXLOVID or from the underlying maternal condition. Breastfeeding individuals with COVID-19 should follow practices according to clinical guidelines to avoid exposing the infant to COVID-19.
```

#### 8 USE IN SPECIFIC POPULATIONS > 8.2 Lactation > SPL UNCLASSIFIED SECTION [2]

```diff
@@ -1 +1 @@
-Data In the PPND study, transiently lower body weight (up to 8%) was observed in the offspring of pregnant rats administered nirmatrelvir at maternal systemic exposure (AUC24) approximately 9 times higher than clinical exposures at the approved human dose of PAXLOVID. No body weight changes in the offspring were noted at maternal systemic exposure (AUC24) approximately 6 times higher than clinical exposures at the approved human dose of PAXLOVID.
+Data In a clinical pharmacokinetics study, 8 healthy lactating women who were at least 12 weeks postpartum were administered 3 oral doses every 12 hours (steady state dosing) of 300 mg/100 mg nirmatrelvir/ritonavir. The mean daily amount of nirmatrelvir and ritonavir recovered in breast milk was 0.752 mg and 0.027 mg, respectively, representing 0.13% and 0.014% of the corresponding administered daily maternal doses (unadjusted for weight). The estimated daily infant dose (assuming average milk consumption of 150 mL/kg/day), was 0.16 mg/kg/day and 0.006 mg/kg/day, 1.8% and 0.2% of the maternal dose, respectively, for nirmatrelvir and ritonavir.
```

### 2024-09-24 · PAXLOVID (NIRMATRELVIR AND RITONAVIR) KIT [PFIZER LABORATORIES DIV PFIZER INC] · v1 → v2

`8a99d6d6-fd9e-45bb-b1bf-48c7f761232a` (openfda) · version key `1` → `3`

- Sections: 0 added, 4 changed, 0 removed
  - Changed: `12 CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > SPL UNCLASSIFIED SECTION [3]`, `12 CLINICAL PHARMACOLOGY > 12.4 Microbiology > SPL UNCLASSIFIED SECTION [3]`, `7 DRUG INTERACTIONS > 7.3 Established and Other Potentially Significant Drug Interactions`, `SPL UNCLASSIFIED SECTION`
- Verdicts: changed 0 · broken 0 · still valid 0

#### 12 CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > SPL UNCLASSIFIED SECTION [3]

```diff
@@ -1,5 +1,6 @@
 Clinical Drug Interaction Studies Table 5 describes the effect of other drugs on the Cmax and AUC of nirmatrelvir. Table 5: The Effect of Other Drugs on the Pharmacokinetic Parameters of Nirmatrelvir Co-administered Drug Dose (Schedule) N Percent Ratio (in combination with co-administered drug/alone) of Nirmatrelvir Pharmacokinetic Parameters (90% CI); No Effect=100 Co-administered Drug Nirmatrelvir/ Ritonavir Cmax AUC For carbamazepine, AUC=AUCinf; for itraconazole, AUC=AUCtau. Abbreviations: AUC=area under the plasma concentration-time curve; AUCinf=area under the plasma concentration-time profile from time zero extrapolated to infinite time; AUCtau=area under the plasma concentration-time profile from time zero to time tau (τ), the dosing interval. CI=confidence interval; Cmax=observed maximum plasma concentrations.
-CI=confidence interval; Cmax=observed maximum plasma concentrations. CarbamazepineCarbamazepine titrated up to 300 mg twice daily on Day 8 through Day 15 (e.g., 100 mg twice daily on Day 1 through Day 3 and 200 mg twice daily on Day 4 through Day 7). 300 mg twice daily (16 doses) 300 mg/100 mg once daily(2 doses) 10 56.82(47.04, 68.62) 44.50(33.77, 58.65) Itraconazole 200 mg once daily (8 doses) 300 mg/100 mg twice daily(5 doses) 11 118.57(112.50, 124.97) 138.82(129.25, 149.11) Table 6 describes the effect of nirmatrelvir/ritonavir on the Cmax and AUC of other drugs.
-Table 6: Effect of Nirmatrelvir/Ritonavir on Pharmacokinetics of Other Drugs Co-administered Drug Dose (Schedule) N Percent Ratio of Test/Reference of Geometric Means (90% CI); No Effect=100 Co-administered Drug Nirmatrelvir/ Ritonavir Cmax AUC AUC=AUCinf for both midazolam and dabigatran. Abbreviations: AUC=area under the plasma concentration-time curve; CI=confidence interval; Cmax=observed maximum plasma concentrations; P-gp=p-glycoprotein. MidazolamFor midazolam, Test=nirmatrelvir/ritonavir plus midazolam, Reference=Midazolam. Midazolam is an index substrate for CYP3A. For dabigatran, Test=nirmatrelvir/ritonavir plus dabigatran, Reference=Dabigatran. Dabigatran is an index substrate for P-gp.
-Dabigatran is an index substrate for P-gp. 2 mg (1 dose) 300 mg/100 mg twice daily(9 doses) 10 368.33(318.91, 425.41) 1430.02(1204.54, 1697.71) Dabigatran 75 mg (1 dose) 300 mg/100 mg twice daily(4 doses) 24 233.06(172.14, 315.54) 194.47(155.29, 243.55) In Vitro Studies Cytochrome P450 (CYP) Enzymes: •Nirmatrelvir is a reversible and time-dependent inhibitor of CYP3A, but not an inhibitor CYP1A2, CYP2B6, CYP2C8, CYP2C9, CYP2C19, or CYP2D6. Nirmatrelvir is an inducer of CYP2B6, 2C8, 2C9, and 3A4, but there is minimal risk for pharmacokinetic interactions arising from induction of these CYP enzymes at the proposed therapeutic dose.
-•Ritonavir is a substrate of CYP2D6 and CYP3A. Ritonavir is an inducer of CYP1A2, CYP2C9, CYP2C19, CYP2B6, and CYP3A. Transporter Systems: Nirmatrelvir is an inhibitor of P-gp and OATP1B1. Nirmatrelvir is a substrate for P-gp, but not BCRP, MATE1, MATE2K, NTCP, OAT1, OAT2, OAT3, OCT1, OCT2, PEPT1, OATP1B1, OATP1B3, OATP2B1, or OATP4C1.
+CI=confidence interval; Cmax=observed maximum plasma concentrations. CarbamazepineCarbamazepine titrated up to 300 mg twice daily on Day 8 through Day 15 (e.g., 100 mg twice daily on Day 1 through Day 3 and 200 mg twice daily on Day 4 through Day 7). 300 mg twice daily (16 doses) 300 mg/100 mg once daily(2 doses) 10 56.82(47.04, 68.62) 44.50(33.77, 58.65) Itraconazole 200 mg once daily (8 doses) 300 mg/100 mg twice daily(5 doses) 11 118.57(112.50, 124.97) 138.82(129.25, 149.11) Table 6 describes the effect of nirmatrelvir/ritonavir on the Cmax and AUCinf of other drugs.
... diff truncated
```

#### 12 CLINICAL PHARMACOLOGY > 12.4 Microbiology > SPL UNCLASSIFIED SECTION [3]

```diff
@@ -1,2 +1,2 @@
-Viral RNA Rebound (With and Without COVID-19 Symptoms) and Treatment-Emergent Substitutions EPIC-HR and EPIC-SR were not designed to evaluate COVID-19 rebound; exploratory analyses were conducted to assess the relationship between PAXLOVID use and rebound in viral RNA shedding levels or self-reported COVID-19 symptoms. Post-treatment increases in SARS-CoV-2 RNA shedding levels in nasopharyngeal samples were observed on Day 10 and/or Day 14 in a subset of PAXLOVID and placebo recipients in EPIC-HR and EPIC-SR, irrespective of COVID-19 symptoms. The frequency of detection of post-treatment viral RNA rebound varied according to analysis parameters, but was generally similar among PAXLOVID and placebo recipients. A similar or smaller percentage of placebo recipients compared to PAXLOVID recipients had nasopharyngeal viral RNA results < lower limit of quantitation (LLOQ) at all study timepoints in both the treatment and post-treatment periods.
-In EPIC-HR, of 59 PAXLOVID-treated subjects identified with post-treatment viral RNA rebound and with available viral sequence data, treatment-emergent substitutions in Mpro potentially reducing nirmatrelvir activity were detected in 2 (3%) subjects, including E166V in 1 subject and T304I in 1 subject. Both subjects had viral RNA shedding levels <LLOQ by Day 14. Post-treatment viral RNA rebound was not associated with the primary clinical outcome of COVID-19 related hospitalization or death from any cause through Day 28 following the single 5-day course of PAXLOVID treatment. The clinical relevance of post-treatment increases in viral RNA following PAXLOVID or placebo treatment is unknown. The frequency of symptom rebound through Day 28, irrespective of viral RNA results, was similar among PAXLOVID and placebo recipients. The frequency of combined viral RNA rebound plus symptom rebound could not be fully assessed as most episodes of symptom rebound occurred after Day 14 (the last day SARS-CoV-2 RNA levels were routinely assessed).
+Viral RNA Rebound and Treatment-Emergent Substitutions EPIC-HR and EPIC-SR were not designed to evaluate COVID-19 rebound; exploratory analyses were conducted to assess the relationship between PAXLOVID use and rebound in viral RNA shedding levels. Post-treatment increases in SARS-CoV-2 RNA shedding levels in nasopharyngeal samples were observed on Day 10 and/or Day 14 in a subset of PAXLOVID and placebo recipients in EPIC-HR and EPIC-SR, irrespective of COVID-19 symptoms. The frequency of detection of post-treatment viral RNA rebound varied according to analysis parameters, but was generally similar among PAXLOVID and placebo recipients. A similar or smaller percentage of placebo recipients compared to PAXLOVID recipients had nasopharyngeal viral RNA results < lower limit of quantitation (LLOQ) at all study timepoints in both the treatment and post-treatment periods.
+In EPIC-HR, of 59 PAXLOVID-treated subjects identified with post-treatment viral RNA rebound and with available viral sequence data, treatment-emergent substitutions in Mpro potentially reducing nirmatrelvir activity were detected in 2 (3%) subjects, including E166V in 1 subject and T304I in 1 subject. Both subjects had viral RNA shedding levels <LLOQ by Day 14. Post-treatment viral RNA rebound was not associated with the primary clinical outcome of COVID-19 related hospitalization or death from any cause through Day 28 following the single 5-day course of PAXLOVID treatment. The clinical relevance of post-treatment increases in viral RNA following PAXLOVID or placebo treatment is unknown.
```

#### 7 DRUG INTERACTIONS > 7.3 Established and Other Potentially Significant Drug Interactions

```diff
@@ -1,6 +1,6 @@
 Table 1 provides a listing of clinically significant drug interactions, including contraindicated drugs [see Contraindications (4) and Warnings and Precautions (5.1)]. Drugs listed in Table 1 are a guide and not considered a comprehensive list of all possible drugs that may interact with PAXLOVID. The healthcare provider should consult other appropriate resources such as the prescribing information for the interacting drug for comprehensive information on dosing or monitoring with concomitant use of a strong CYP3A inhibitor such as ritonavir. Table 1: Established and Other Potentially Significant Drug Interactions Drug Class Drugs within Class Effect on Concentration Clinical Comments Alpha 1-adrenoreceptor antagonist alfuzosin ↑ alfuzosin Co-administration contraindicated due to potential hypotension [see Contraindications (4)]. Alpha 1-adrenoreceptor antagonist tamsulosin ↑ tamsulosin Avoid concomitant use with PAXLOVID. Antianginal ranolazine ↑ ranolazine Co-administration contraindicated due to potential for serious and/or life-threatening reactions [see Contraindications (4)].
 Antiarrhythmics amiodarone, dronedarone, flecainide, propafenone, quinidine ↑ antiarrhythmic Co-administration contraindicated due to potential for cardiac arrhythmias [see Contraindications (4)]. Antiarrhythmics lidocaine (systemic),disopyramide ↑ antiarrhythmic Caution is warranted and therapeutic concentration monitoring is recommended for antiarrhythmics if available. Anticancer drugs apalutamide ↓ nirmatrelvir/ritonavir Co-administration contraindicated due to potential loss of virologic response and possible resistance [see Contraindications (4)]. Anticancer drugs abemaciclib, ceritinib,dasatinib, encorafenib,ibrutinib, ivosidenib, neratinib, nilotinib, venetoclax,vinblastine, vincristine ↑ anticancer drugs Avoid co-administration of encorafenib or ivosidenib due to potential risk of serious adverse events such as QT interval prolongation. Avoid use of neratinib, venetoclax or ibrutinib.
-Avoid use of neratinib, venetoclax or ibrutinib. Co-administration of vincristine and vinblastine may lead to significant hematologic or gastrointestinal side effects. For further information, refer to individual product label for anticancer drug. Anticoagulants warfarin ↑↓ warfarin Closely monitor international normalized ratio (INR) if co-administration with warfarin is necessary. rivaroxaban ↑ rivaroxaban Increased bleeding risk with rivaroxaban. Avoid concomitant use. dabigatranSee Pharmacokinetics, Drug Interaction Studies Conducted with Nirmatrelvir and Ritonavir (12.3). ↑ dabigatran Increased bleeding risk with dabigatran. Depending on dabigatran indication and renal function, reduce dose of dabigatran or avoid concomitant use. Refer to the dabigatran product label for further information. apixaban ↑ apixaban Combined P-gp and strong CYP3A inhibitors increase blood levels of apixaban and increase the risk of bleeding.
+Avoid use of neratinib, venetoclax or ibrutinib. Co-administration of vincristine and vinblastine may lead to significant hematologic or gastrointestinal side effects. For further information, refer to individual product label for anticancer drug. Anticoagulants warfarin ↑↓ warfarin Closely monitor international normalized ratio (INR) if co-administration with warfarin is necessary. rivaroxaban ↑ rivaroxaban Increased bleeding risk with rivaroxaban. Avoid concomitant use. dabigatranSee Pharmacokinetics, Clinical Drug Interaction Studies (12.3). ↑ dabigatran Increased bleeding risk with dabigatran. Depending on dabigatran indication and renal function, reduce dose of dabigatran or avoid concomitant use. Refer to the dabigatran product label for further information. apixaban ↑ apixaban Combined P-gp and strong CYP3A inhibitors increase blood levels of apixaban and increase the risk of bleeding. Dosing recommendations for co-administration of apixaban with PAXLOVID depend on the apixaban dose.
... diff truncated
```

### 2024-04-15 · LIPITOR (ATORVASTATIN CALCIUM) TABLET, FILM COATED [VIATRIS SPECIALTY LLC] · v2 → v3

`a60cc18b-0631-4cf0-b021-9f52224ece65` (openfda) · version key `5` → `7`

- Sections: 0 added, 4 changed, 0 removed
  - Changed: `PRINCIPAL DISPLAY PANEL – 10 mg`, `PRINCIPAL DISPLAY PANEL – 20 mg`, `PRINCIPAL DISPLAY PANEL – 40 mg`, `PRINCIPAL DISPLAY PANEL – 80 mg`
- Verdicts: changed 0 · broken 0 · still valid 0

#### PRINCIPAL DISPLAY PANEL – 10 mg

```diff
@@ -1 +1 @@
-NDC 58151-155-77 Lipitor® atorvastatin calcium)tablets 10 mg* 90 Tablets Rx only VIATRIS™ Store at controlled roomtemperature 20-25ºC(68-77ºF). Dispense in tightcontainers (USP). DOSAGE AND USE See package insertfor full prescribinginformation. *Each tablet containsatorvastatin 10 mg(equivalent to10.36 mg atorvastatincalcium anhydrous). Distributed by: Viatris Specialty LLC Morgantown, WV26505 U.S.A. © 2023 Viatris Inc. RUPJ155MM
+NDC 58151-155-77 Lipitor® atorvastatin calcium)tablets 10 mg* 90 Tablets Rx only VIATRIS™ Store at controlled roomtemperature 20-25ºC(68-77ºF). Dispense in tightcontainers (USP). DOSAGE AND USE See package insertfor full prescribinginformation. *Each tablet containsatorvastatin 10 mg (equivalent to 10.36 mg atorvastatincalcium anhydrous). Distributed by: Viatris Specialty LLC Morgantown, WV26505 U.S.A. © 2024 Viatris Inc. RUPJ155MM1
```

#### PRINCIPAL DISPLAY PANEL – 20 mg

```diff
@@ -1 +1 @@
-NDC 58151-156-77 Lipitor® (atorvastatin calcium)tablets 20 mg* 90 Tablets Rx only VIATRIS™ Store at controlled roomtemperature 20-25ºC(68-77ºF). Dispense in tightcontainers (USP). DOSAGE AND USE See package insertfor full prescribinginformation. *Each tablet containsatorvastatin 20 mg(equivalent to20.72 mg atorvastatincalcium anhydrous). Distributed by: Viatris Specialty LLC Morgantown, WV26505 U.S.A. © 2023 Viatris Inc. RUPJ156MM
+NDC 58151-156-77 Lipitor® (atorvastatin calcium)tablets 20 mg* 90 Tablets Rx only VIATRIS™ Store at controlled roomtemperature 20-25ºC(68-77ºF). Dispense in tightcontainers (USP). DOSAGE AND USE See package insertfor full prescribinginformation. *Each tablet containsatorvastatin 20 mg (equivalent to 20.72 mg atorvastatincalcium anhydrous). Distributed by: Viatris Specialty LLC Morgantown, WV26505 U.S.A. © 2024 Viatris Inc. RUPJ156MM1
```

#### PRINCIPAL DISPLAY PANEL – 40 mg

```diff
@@ -1 +1 @@
-NDC 58151-157-77 Lipitor® (atorvastatin calcium) 40 mg* tablets 90 Tablets Rx only VIATRIS™ Store at controlled room temperature20-25ºC (68-77ºF). Dispense in tight containers (USP). DOSAGE AND USE See package insert for full prescribinginformation. *Each tablet contains atorvastatin 40 mg(equivalent to 41.44 mg atorvastatincalcium anhydrous). Distributed by: Viatris Specialty LLC Morgantown, WV26505 U.S.A. © 2023 Viatris Inc. RUPJ157MM
+NDC 58151-157-77 Lipitor® (atorvastatin calcium) 40 mg* tablets 90 Tablets Rx only VIATRIS™ Store at controlled room temperature20-25ºC (68-77ºF). Dispense in tight containers (USP). DOSAGE AND USE See package insert for full prescribinginformation. *Each tablet contains atorvastatin 40 mg(equivalent to 41.44 mg atorvastatincalcium anhydrous). Distributed by: Viatris Specialty LLC Morgantown, WV26505 U.S.A. © 2024 Viatris Inc. RUPJ157MM1
```

### 2024-04-15 · LIPITOR (ATORVASTATIN CALCIUM) TABLET, FILM COATED [VIATRIS SPECIALTY LLC] · v1 → v2

`a60cc18b-0631-4cf0-b021-9f52224ece65` (openfda) · version key `1` → `5`

- Sections: 0 added, 14 changed, 1 removed
  - Changed: `12 CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > Drug Interactions`, `12 CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > Specific Populations > Gender`, `14 CLINICAL STUDIES`, `16 HOW SUPPLIED/STORAGE AND HANDLING`, `17 PATIENT COUNSELING INFORMATION`, `2 DOSAGE AND ADMINISTRATION > 2.1 Important Dosage Information`, `3 DOSAGE FORMS AND STRENGTHS`, `5 WARNINGS AND PRECAUTIONS > 5.1 Myopathy and Rhabdomyolysis > Steps to Prevent or Reduce the Risk of Myopathy and Rhabdomyolysis`, `5 WARNINGS AND PRECAUTIONS > 5.5 Increased Risk of Hemorrhagic Stroke in Patients on LIPITOR 80 mg with Recent Hemorrhagic Stroke`, `6 ADVERSE REACTIONS > 6.1 Clinical Trials Experience` (+4 more)
  - Removed: `RECENT MAJOR CHANGES SECTION`
- Verdicts: changed 0 · broken 0 · still valid 0

#### 12 CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > Drug Interactions

```diff
@@ -1,8 +1,8 @@
-Atorvastatin is a substrate of the hepatic transporters, OATP1B1 and OATP1B3 transporter. Metabolites of atorvastatin are substrates of OATP1B1. Atorvastatin is also identified as a substrate of the efflux transporter BCRP, which may limit the intestinal absorption and biliary clearance of atorvastatin. Table 5: Effect of Co-administered Drugs on the Pharmacokinetics of Atorvastatin Co-administered drug and dosing regimen Atorvastatin Dose (mg) Ratio of AUC Represents ratio of treatments (co-administered drug plus atorvastatin vs. atorvastatin alone). Ratio of Cmax See Sections 5.1 and 7 for clinical significance.
-atorvastatin alone). Ratio of Cmax See Sections 5.1 and 7 for clinical significance. Cyclosporine 5.2 mg/kg/day, stable dose 10 mg QDOnce daily for 28 days 8.69 10.66 Tipranavir 500 mg BIDTwice daily/ritonavir 200 mg BID, 7 days 10 mg SDSingle dose 9.36 8.58 Glecaprevir 400 mg QD/pibrentasvir 120 mg QD, 7 days 10 mg QD for 7 days 8.28 22.00 Telaprevir 750 mg q8hEvery 8 hours, 10 days 20 mg SD 7.88 10.60 , The dose of saquinavir plus ritonavir in this study is not the clinically used dose. The increase in atorvastatin exposure when used clinically is likely to be higher than what was observed in this study. Therefore, caution should be applied and the lowest dose necessary should be used.Saquinavir 400 mg BID/ritonavir 400 mg BID,
+Atorvastatin is a substrate of the hepatic transporters, OATP1B1 and OATP1B3 transporter. Metabolites of atorvastatin are substrates of OATP1B1. Atorvastatin is also identified as a substrate of the efflux transporter BCRP, which may limit the intestinal absorption and biliary clearance of atorvastatin. Table 5: Effect of Co-administered Drugs on the Pharmacokinetics of Atorvastatin Co-administered drug and dosage regimen Atorvastatin Dosage (mg) Ratio of AUC Represents ratio of treatments (co-administered drug plus atorvastatin vs. atorvastatin alone). Ratio of Cmax See Sections 5.1 and 7 for clinical significance.
+atorvastatin alone). Ratio of Cmax See Sections 5.1 and 7 for clinical significance. Cyclosporine 5.2 mg/kg/day, stable dose 10 mg QDOnce daily for 28 days 8.69 10.66 Tipranavir 500 mg BIDTwice daily/ritonavir 200 mg BID, 7 days 10 mg SDSingle dosage 9.36 8.58 Glecaprevir 400 mg QD/pibrentasvir 120 mg QD, 7 days 10 mg QD for 7 days 8.28 22.00 Telaprevir 750 mg q8hEvery 8 hours, 10 days 20 mg SD 7.88 10.60 , The dose of saquinavir plus ritonavir in this study is not the clinically used dose. The increase in atorvastatin exposure when used clinically is likely to be higher than what was observed in this study. Therefore, caution should be applied and the lowest dose necessary should be used.Saquinavir 400 mg BID/ritonavir 400 mg BID,
 Saquinavir 400 mg BID/ritonavir 400 mg BID, 15 days 40 mg QD for 4 days 3.93 4.31 Elbasvir 50 mg QD/grazoprevir 200 mg QD, 13 days 10 mg SD 1.94 4.34 Simeprevir 150 mg QD, 10 days 40 mg SD 2.12 1.70 Clarithromycin 500 mg BID, 9 days 80 mg QD for 8 days 4.54 5.38 Darunavir 300 mg BID/ritonavir 100 mg BID, 9 days 10 mg QD for 4 days 3.45 2.25 Itraconazole 200 mg QD, 4 days 40 mg SD 3.32 1.20 Letermovir 480 mg QD, 10 days 20 mg SD 3.29 2.17 Fosamprenavir 700 mg BID/ritonavir 100 mg BID, 14 days 10 mg QD for 4 days 2.
 14 days 10 mg QD for 4 days 2.53 2.84 Fosamprenavir 1400 mg BID, 14 days 10 mg QD for 4 days 2.30 4.04 Nelfinavir 1250 mg BID, 14 days 10 mg QD for 28 days 1.74 2.22 Grapefruit Juice, 240 mL QD , Greater increases in AUC (ratio of AUC up to 2.5) and/or Cmax (ratio of Cmax up to 1.71) have been reported with excessive grapefruit consumption (≥ 750 mL-1.2 liters per day).
... diff truncated
```

#### 12 CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > Specific Populations > Gender

```diff
@@ -1 +1 @@
-Plasma concentrations of LIPITOR in women differ from those in men (approximately 20% higher for Cmax and 10% lower for AUC); however, there is no clinically significant difference in LDL-C reduction with LIPITOR between men and women.
+Plasma concentrations of LIPITOR in females differ from those in males (approximately 20% higher for Cmax and 10% lower for AUC); however, there is no clinically significant difference in LDL-C reduction with LIPITOR between males and females.
```

#### 14 CLINICAL STUDIES

```diff
@@ -1,25 +1,25 @@
-Prevention of Cardiovascular Disease In the Anglo-Scandinavian Cardiac Outcomes Trial (ASCOT), the effect of LIPITOR on fatal and non-fatal coronary heart disease was assessed in 10,305 patients with hypertension, 40-80 years of age (mean of 63 years; 19% women; 95% White, 3% Black, 1% South Asian, 1% other), without a previous myocardial infarction and with total cholesterol (TC) levels ≤251 mg/dL. Additionally, all patients had at least 3 of the following cardiovascular risk factors: male gender (81%), age >55 years (85%), smoking (33%), diabetes (24%), history of CHD in a first-degree relative (26%), TC:HDL >6 (14%), peripheral vascular disease (5%), left ventricular hypertrophy (14%), prior cerebrovascular event (10%), specific ECG abnormality (14%), proteinuria/albuminuria (62%).
-In this double-blind, placebo-controlled trial, patients were treated with anti-hypertensive therapy (goal BP <140/90 mm Hg for patients without diabetes; <130/80 mm Hg for patients with diabetes) and allocated to either LIPITOR 10 mg daily (n=5168) or placebo (n=5137), using a covariate adaptive method which took into account the distribution of nine baseline characteristics of patients already enrolled and minimized the imbalance of those characteristics across the groups. Patients were followed for a median duration of 3.3 years. The effect of 10 mg/day of LIPITOR on lipid levels was similar to that seen in previous clinical trials. LIPITOR significantly reduced the rate of coronary events [either fatal coronary heart disease (46 events in the placebo group vs. 40 events in the LIPITOR group) or non-fatal MI (108 events in the placebo group vs. 60 events in the LIPITOR group)] with a relative risk reduction of 36% [(based on incidences of 1.9% for LIPITOR vs. 3.0% for placebo), p=0.0005 (see Figure 1)].
+Prevention of Cardiovascular Disease In the Anglo-Scandinavian Cardiac Outcomes Trial (ASCOT), the effect of LIPITOR on fatal and non-fatal coronary heart disease was assessed in 10,305 patients with hypertension, 40-80 years of age (mean of 63 years; 19% female; 95% White, 3% Black or African American, 1% South Asian, 1% other), without a previous myocardial infarction and with total cholesterol (TC) levels ≤251 mg/dL. Additionally, all patients had at least 3 of the following cardiovascular risk factors: male gender (81%), age >55 years (85%), smoking (33%), diabetes (24%), history of CHD in a first-degree relative (26%), TC:HDL >6 (14%), peripheral vascular disease (5%), left ventricular hypertrophy (14%), prior cerebrovascular event (10%), specific ECG abnormality (14%), proteinuria/albuminuria (62%).
+In this double-blind, placebo-controlled trial, patients were treated with anti-hypertensive therapy (goal BP <140/90 mm Hg for patients without diabetes; <130/80 mm Hg for patients with diabetes) and allocated to either LIPITOR 10 mg daily (n=5,168) or placebo (n=5,137), using a covariate adaptive method which took into account the distribution of nine baseline characteristics of patients already enrolled and minimized the imbalance of those characteristics across the groups. Patients were followed for a median duration of 3.3 years. The effect of 10 mg/day of LIPITOR on lipid levels was similar to that seen in previous clinical trials. LIPITOR significantly reduced the rate of coronary events [either fatal coronary heart disease (46 events in the placebo group vs. 40 events in the LIPITOR group) or non-fatal MI (108 events in the placebo group vs. 60 events in the LIPITOR group)] with a relative risk reduction of 36% [(based on incidences of 1.9% for LIPITOR vs. 3.0% for placebo), p=0.0005 (see Figure 1)].
... diff truncated
```

### 2023-08-15 · ZOLOFT (SERTRALINE HYDROCHLORIDE) TABLET, FILM COATED ZOLOFT (SERTRALINE HYDROCHLORIDE) SOLUTION, CONCENTRATE [VIATRIS SPECIALTY LLC] · v1 → v2

`fda754f6-d0f3-4dce-a17a-927d64f912f7` (openfda) · version key `1` → `2`

- Sections: 2 added, 11 changed, 2 removed
  - Added: `8 USE IN SPECIFIC POPULATIONS > 8.1 Pregnancy > Clinical Considerations > Disease-associated Maternal and/or Embryo/Fetal Risk`, `8 USE IN SPECIFIC POPULATIONS > 8.1 Pregnancy > Clinical Considerations > Fetal/Neonatal Adverse Reactions`
  - Changed: `1 INDICATIONS AND USAGE`, `14 CLINICAL STUDIES > 14.3 Panic Disorder`, `14 CLINICAL STUDIES > 14.4 Posttraumatic Stress Disorder`, `14 CLINICAL STUDIES > 14.5 Social Anxiety Disorder`, `17 PATIENT COUNSELING INFORMATION`, `6 ADVERSE REACTIONS > 6.1 Clinical Trials Experience`, `Medication Guide`, `PRINCIPAL DISPLAY PANEL – 100 mg`, `PRINCIPAL DISPLAY PANEL – 20 mg/mL`, `PRINCIPAL DISPLAY PANEL – 25 mg` (+1 more)
  - Removed: `8 USE IN SPECIFIC POPULATIONS > 8.1 Pregnancy > Clinical Considerations > Disease-associated maternal and/or embryo/fetal risk`, `8 USE IN SPECIFIC POPULATIONS > 8.1 Pregnancy > Clinical Considerations > Fetal/Neonatal adverse reactions`
- Verdicts: changed 0 · broken 0 · still valid 0

#### 1 INDICATIONS AND USAGE

```diff
@@ -1 +1 @@
-ZOLOFT is indicated for the treatment of the following [See Clinical Studies (14)]: •Major depressive disorder (MDD) •Obsessive-compulsive disorder (OCD) •Panic disorder (PD) •Posttraumatic stress disorder (PTSD) •Social anxiety disorder (SAD) •Premenstrual dysphoric disorder (PMDD)
+ZOLOFT is indicated for the treatment of the following [See Clinical Studies (14)]: •Major depressive disorder (MDD) • Obsessive-compulsive disorder (OCD) •Panic disorder (PD) •Posttraumatic stress disorder (PTSD) •Social anxiety disorder (SAD) •Premenstrual dysphoric disorder (PMDD)
```

#### 14 CLINICAL STUDIES > 14.3 Panic Disorder

```diff
@@ -1,4 +1,4 @@
 The effectiveness of ZOLOFT in the treatment of PD was demonstrated in three double‑blind, placebo‑controlled studies (Studies PD-1, PD-2, and PD‑3) of adult outpatients who had a primary diagnosis of PD (DSM‑III‑R), with or without agoraphobia. •Studies PD-1 and PD-2 were 10-week flexible dose studies of ZOLOFT (N=80 study PD-1 and N=88 study PD-2) compared to placebo (N=176 study PD-1 and PD-2). In both studies, ZOLOFT was initiated at 25 mg/day for the first week, then titrated in weekly increments of 50 mg per day to a maximum dose of 200 mg/day on the basis of clinical response and toleration. The mean ZOLOFT doses for completers to 10 weeks were 131 mg/day and 144 mg/day, respectively, for Studies PD-1 and PD-2.
 In these studies, ZOLOFT was shown to be statistically significantly more effective than placebo on change from baseline in panic attack frequency and on the Clinical Global Impression Severity (CGI-S) of Illness and Global Improvement (CGI-I) scores. The difference between ZOLOFT and placebo in reduction from baseline in the number of full panic attacks was approximately 2 panic attacks per week in both studies. •Study PD-3 was a 12-week randomized, double-blind fixed-dose study, including ZOLOFT doses of 50, 100, and 200 mg/day. Patients receiving ZOLOFT (50 mg N=43, 100 mg N=44, 200 mg N=45) experienced a statistically significantly greater reduction in panic attack frequency than patients receiving placebo (N=45). Study PD-3 was not readily interpretable regarding a dose response relationship for effectiveness. Subgroup analyses did not indicate that there were any differences in treatment outcomes as a function of age, race, or gender.
-Subgroup analyses did not indicate that there were any differences in treatment outcomes as a function of age, race, or gender. In Study PD-4, patients meeting DSM-III-R criteria for PD who had responded during a 52-week open trial on ZOLOFT 50-200 mg/day (n=183) were randomized to continuation of ZOLOFT or to substitution of placebo for up to 28 weeks of observation for discontinuation due to relapse or insufficient clinical response. Response during the open phase was defined as a CGI-I score of 1(very much improved) or 2 (much improved). Insufficient clinical response in the double-blind phase indicated a worsening of the patient’s condition that resulted in study discontinuation, as assessed by the investigator. Relapse during the double-blind phase was defined as the following conditions being met on three consecutive visits: (1)CGI-I ≥ 3; (2)meets DSM-III-R criteria for PD; (3)number of panic attacks greater than at baseline. Patients receiving continued ZOLOFT treatment experienced a statistically significantly lower rate of discontinuation due to relapse or insufficient clinical response over the subsequent 28 weeks compared to those receiving placebo.
... diff truncated
```

#### 14 CLINICAL STUDIES > 14.4 Posttraumatic Stress Disorder

```diff
@@ -1,4 +1,4 @@
 The effectiveness of ZOLOFT in the treatment of PTSD was established in two multicenter placebo‑controlled studies (Studies PSTD-1 and PSTD-2) of adult outpatients who met DSM‑III‑R criteria for PTSD. The mean duration of PTSD for these patients was 12 years (Studies PSTD-1 and PSTD-2 combined) and 44% of patients (169 of the 385 patients treated) had secondary depressive disorder. Studies PSTD-1 and PSTD-2 were 12‑week flexible dose studies. ZOLOFT was initiated at 25 mg/day for the first week, and titrated in weekly increments of 50 mg per day to a maximum dose of 200 mg/day on the basis of clinical response and tolerability. The mean ZOLOFT dose for completers was 146 mg/day and 151 mg/day, respectively, for Studies PSTD-1 and PSTD-2.
 Study outcome was assessed by the Clinician‑Administered PTSD Scale Part 2 (CAPS), which is a multi‑item instrument that measures the three PTSD diagnostic symptom clusters of reexperiencing/intrusion, avoidance/numbing, and hyperarousal as well as the patient‑rated Impact of Event Scale (IES), which measures intrusion and avoidance symptoms. Patients receiving ZOLOFT (N=99 and N=94, respectively) showed statistically significant improvement compared to placebo (N=83 and N=92) on change from baseline to endpoint on the CAPS, IES, and on the Clinical Global Impressions (CGI-S) Severity of Illness and Global Improvement (CGI-I) scores. In two additional placebo-controlled PTSD trials (Studies PSTD-3 and PSTD-4), the difference in response to treatment between patients receiving ZOLOFT and patients receiving placebo was not statistically significant. One of these additional studies was conducted in patients similar to those recruited for Studies PSTD-1 and PSTD-2, while the second additional study was conducted in predominantly male veterans.
 As PTSD is a more common disorder in women than men, the majority (76%) of patients in Studies PSTD-1 and PSTD-2 described above were women. Post hoc exploratory analyses revealed a statistically significant difference between ZOLOFT and placebo on the CAPS, IES and CGI in women, regardless of baseline diagnosis of comorbid major depressive disorder, but essentially no effect in the relatively smaller number of men in these studies. The clinical significance of this apparent gender effect is unknown at this time. There was insufficient information to determine the effect of race or age on outcome. In Study PSTD-5, patients meeting DSM-III-R criteria for PTSD who had responded during a 24-week open trial on ZOLOFT 50-200 mg/day (n=96) were randomized to continuation of ZOLOFT or to substitution of placebo for up to 28 weeks of observation for relapse. Response during the open phase was defined as a CGI-I of 1 (very much improved) or 2 (much improved), and a decrease in the CAPS-2 score of > 30% compared to baseline.
-Relapse during the double-blind phase was defined as the following conditions being met on two consecutive visits: (1)CGI-I ≥ 3; (2)CAPS-2 score increased by ≥ 30% and by ≥ 15 points relative to baseline; and (3)worsening of the patient's condition in the investigator's judgment. Patients receiving continued ZOLOFT treatment experienced statistically significantly lower relapse rates over the subsequent 28 weeks compared to those receiving placebo. This pattern was demonstrated in male and female subjects.
+Relapse during the double-blind phase was defined as the following conditions being met on two consecutive visits: (1) CGI-I ≥ 3; (2) CAPS-2 score increased by ≥ 30% and by ≥ 15 points relative to baseline; and (3) worsening of the patient's condition in the investigator's judgment. Patients receiving continued ZOLOFT treatment experienced statistically significantly lower relapse rates over the subsequent 28 weeks compared to those receiving placebo. This pattern was demonstrated in male and female subjects.
```

### 2022-09-22 · PLAVIX (CLOPIDOGREL) TABLET, FILM COATED [SANOFI-AVENTIS U.S. LLC] · v2 → v3

`de8b0b67-eb25-4684-83b5-7ad785314227` (openfda) · version key `2` → `3`

- Sections: 2 added, 3 changed, 1 removed
  - Added: `7 DRUG INTERACTIONS > 7.7 Other Antiplatelet Agents`, `7 DRUG INTERACTIONS > 7.8 Repaglinide (CYP2C8 Substrates)`
  - Changed: `5 WARNINGS AND PRECAUTIONS > 5.2 General Risk of Bleeding`, `SPL MEDGUIDE SECTION`, `SPL UNCLASSIFIED SECTION [2]`
  - Removed: `7 DRUG INTERACTIONS > 7.7 Repaglinide (CYP2C8 Substrates)`
- Verdicts: changed 0 · broken 0 · still valid 0

#### 5 WARNINGS AND PRECAUTIONS > 5.2 General Risk of Bleeding

```diff
@@ -1 +1 @@
-P2Y12 inhibitors (thienopyridines), including Plavix, increase the risk of bleeding. P2Y12 inhibitors (thienopyridines), inhibit platelet aggregation for the lifetime of the platelet (7–10 days). Because the half-life of clopidogrel's active metabolite is short, it may be possible to restore hemostasis by administering exogenous platelets; however, platelet transfusions within 4 hours of the loading dose or 2 hours of the maintenance dose may be less effective. Use of drugs that induce the activity of CYP2C19 would be expected to result in increased drug levels of the active metabolite of clopidogrel and might potentiate the bleeding risk. As a precaution, avoid concomitant use of strong CYP2C19 inducers [see Drug Interactions (7.1) and Clinical Pharmacology (12.3)].
+P2Y12 inhibitors (thienopyridines), including Plavix, increase the risk of bleeding. P2Y12 inhibitors (thienopyridines), inhibit platelet aggregation for the lifetime of the platelet (7–10 days). Because the half-life of clopidogrel's active metabolite is short, it may be possible to restore hemostasis by administering exogenous platelets; however, platelet transfusions within 4 hours of the loading dose or 2 hours of the maintenance dose may be less effective. Use of drugs that induce the activity of CYP2C19 would be expected to result in increased drug levels of the active metabolite of clopidogrel and might potentiate the bleeding risk. As a precaution, avoid concomitant use of strong CYP2C19 inducers [see Drug Interactions (7.1) and Clinical Pharmacology (12.3)]. Risk factors for bleeding include concomitant use of other drugs that increase the risk of bleeding (e.g., anticoagulants, antiplatelet agents, and chronic use of NSAIDs) [see Drug Interactions (7.4, 7.5, 7.6, 7.7)].
```

#### SPL MEDGUIDE SECTION

```diff
@@ -3,7 +3,7 @@
 If you must stop Plavix because of bleeding, your risk of a heart attack may be higher. What is Plavix? Plavix is a prescription medicine used to treat people who have any of the following: chest pain due to heart problems poor circulation in their legs (peripheral arterial disease) a heart attack a stroke Plavix is used alone or with aspirin to lower your chance of having another serious problem with your heart or blood vessels such as heart attack, stroke, or blood clot that can lead to death. Platelets are blood cells that help your blood clot normally. Plavix helps to prevent platelets from sticking together and forming a clot that can block an artery. It is not known if Plavix is safe and effective in children. Who should not take Plavix? Do not take Plavix if you: currently have a condition that causes bleeding, such as a stomach ulcer are allergic to clopidogrel or other ingredients in Plavix. See the end of this leaflet for a complete list of ingredients in Plavix. What should I tell my doctor before taking Plavix?
 See the end of this leaflet for a complete list of ingredients in Plavix. What should I tell my doctor before taking Plavix? Before you take Plavix, tell your doctor if you: have a history of bowel (gastrointestinal) or stomach ulcers. have a history of bleeding problems. plan to have surgery or a dental procedure. See " How should I take Plavix? " are pregnant or plan to become pregnant. It is not known if Plavix will harm your unborn baby. are breastfeeding or plan to breastfeed. It is not known if Plavix passes into your breast milk. A decision should be made with your healthcare provider to avoid or discontinue breastfeeding when continuing Plavix is needed. have had an allergy or reaction to any medicine used to treat your disease. Tell all of your doctors and your dentist that you are taking Plavix. They should talk to the doctor who prescribed Plavix for you before you have any surgery or invasive procedure. Tell your doctor about all the medicines you take, including prescription, non-prescription medicines, vitamins and herbal supplements.
 Tell your doctor about all the medicines you take, including prescription, non-prescription medicines, vitamins and herbal supplements. Plavix may affect the way other medicines work, and other medicines may affect how Plavix works. See " What is the most important information I should know about Plavix? " Plavix may increase blood levels of other medicines such as repaglinide (Prandin®). Taking Plavix with certain other medicines may increase your risk of bleeding. Especially tell your doctor if you take: aspirin, especially if you have had a stroke. Always talk to your doctor about whether you should take aspirin along with Plavix to treat your condition. nonsteroidal anti-inflammatory drugs (NSAIDs). Ask your doctor or pharmacist for a list of NSAID medicines if you are not sure. warfarin (Coumadin ® , Jantoven ® ). selective serotonin reuptake inhibitors (SSRIs) and serotonin norepinephrine reuptake inhibitors (SNRIs). Ask your doctor or pharmacist for a list of SSRI or SNRI medicines if you are not sure.
... diff truncated
```

#### SPL UNCLASSIFIED SECTION [2]

```diff
@@ -1 +1 @@
-Revised: March 2021 Manufactured by:sanofi-aventis U.S. LLCBridgewater, NJ 08807A SANOFI COMPANY Plavix® is a registered trademark of sanofi-aventis.All other trademarks are property of their respective owners.
+Revised: September 2022 Manufactured by:sanofi-aventis U.S. LLCBridgewater, NJ 08807A SANOFI COMPANY Plavix® is a registered trademark of sanofi-aventis.All other trademarks are property of their respective owners.
```

### 2021-03-05 · PLAVIX (CLOPIDOGREL) TABLET, FILM COATED [SANOFI-AVENTIS U.S. LLC] · v1 → v2

`de8b0b67-eb25-4684-83b5-7ad785314227` (openfda) · version key `1` → `2`

- Sections: 9 added, 7 changed, 6 removed
  - Added: `12 CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > SPL UNCLASSIFIED SECTION > SPL UNCLASSIFIED SECTION > SPL UNCLASSIFIED SECTION [3]`, `12 CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > SPL UNCLASSIFIED SECTION > SPL UNCLASSIFIED SECTION > SPL UNCLASSIFIED SECTION [4]`, `7 DRUG INTERACTIONS > 7.1 CYP2C19 Inducers`, `7 DRUG INTERACTIONS > 7.2 CYP2C19 Inhibitors`, `7 DRUG INTERACTIONS > 7.3 Opioids`, `7 DRUG INTERACTIONS > 7.4 Nonsteroidal Anti-inflammatory Drugs (NSAIDs)`, `7 DRUG INTERACTIONS > 7.5 Warfarin (CYP2C9 Substrates)`, `7 DRUG INTERACTIONS > 7.6 SSRIs and SNRIs`, `7 DRUG INTERACTIONS > 7.7 Repaglinide (CYP2C8 Substrates)`
  - Changed: `12 CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > SPL UNCLASSIFIED SECTION > SPL UNCLASSIFIED SECTION > SPL UNCLASSIFIED SECTION`, `12 CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > SPL UNCLASSIFIED SECTION > SPL UNCLASSIFIED SECTION > SPL UNCLASSIFIED SECTION [2]`, `12 CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > SPL UNCLASSIFIED SECTION > SPL UNCLASSIFIED SECTION [2]`, `5 WARNINGS AND PRECAUTIONS > 5.2 General Risk of Bleeding`, `8 USE IN SPECIFIC POPULATIONS > 8.2 Lactation > SPL UNCLASSIFIED SECTION`, `SPL MEDGUIDE SECTION`, `SPL UNCLASSIFIED SECTION [2]`
  - Removed: `7 DRUG INTERACTIONS > 7.1 CYP2C19 Inhibitors`, `7 DRUG INTERACTIONS > 7.2 Opioids`, `7 DRUG INTERACTIONS > 7.3 Nonsteroidal Anti-inflammatory Drugs (NSAIDs)`, `7 DRUG INTERACTIONS > 7.4 Warfarin (CYP2C9 Substrates)`, `7 DRUG INTERACTIONS > 7.5 SSRIs and SNRIs`, `7 DRUG INTERACTIONS > 7.6 Repaglinide (CYP2C8 Substrates)`
- Verdicts: changed 0 · broken 0 · still valid 0

#### 12 CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > SPL UNCLASSIFIED SECTION > SPL UNCLASSIFIED SECTION > SPL UNCLASSIFIED SECTION

```diff
@@ -1 +1 @@
-Proton pump inhibitors (PPI) The effect of proton pump inhibitors (PPI) on the systemic exposure to the clopidogrel active metabolite following multiple doses of Plavix 75 mg evaluated in dedicated drug interaction studies is presented in Figure 1. Figure 1: Exposure to Clopidogrel Active Metabolite Following Multiple Doses of Plavix 75 mg Alone or with Proton Pump Inhibitors (PPIs) Pharmacodynamic and pharmacokinetic parameters measured in these studies showed that the interaction was highest with omeprazole and least with dexlansoprazole.
+CYP2C19 inducers Concomitant use of strong inducers of CYP2C19 results in increased plasma concentration of the active metabolite of clopidogrel and an increase in platelet inhibition. Rifampin: Coadministration of rifampin 300 mg twice daily for 7 days with 600 mg loading dose of clopidogrel in healthy adults increased the mean AUC and Cmax of clopidogrel's thiol metabolites by 3.8-fold. Mean inhibition of platelet aggregation at 4 hours post dose was 34% higher in the presence of rifampin compared to clopidogrel administered alone.
```

#### 12 CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > SPL UNCLASSIFIED SECTION > SPL UNCLASSIFIED SECTION > SPL UNCLASSIFIED SECTION [2]

```diff
@@ -1 +1 @@
-Opioids Coadministration of 5 mg intravenous morphine with 600 mg loading dose of clopidogrel in healthy adults decreased the AUC and Cmax of clopidogrel's thiol metabolites by 34%. Mean platelet aggregation was higher up to 2 to 4 hours with morphine coadministration.
+CYP2C19 inhibitors Concomitant use of certain inhibitors of this enzyme results in reduced plasma concentrations of the active metabolite of clopidogrel and a reduction in platelet inhibition.
```

#### 12 CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > SPL UNCLASSIFIED SECTION > SPL UNCLASSIFIED SECTION [2]

```diff
@@ -1 +1 @@
-Effect of other drugs on Plavix Clopidogrel is metabolized to its active metabolite in part by CYP2C19. Concomitant use of certain inhibitors of this enzyme results in reduced plasma concentrations of the active metabolite of clopidogrel and a reduction in platelet inhibition.
+Effect of other drugs on Plavix Clopidogrel is metabolized to its active metabolite in part by CYP2C19.
```

### 2017-08-24 · JANTOVEN (WARFARIN SODIUM) TABLET [UPSHER-SMITH LABORATORIES, LLC] · v8 → v9

`19a69a72-ac5d-45d5-a94d-a5aaecbe4730` (openfda) · version key `10` → `11`

- Sections: 14 added, 25 changed, 11 removed
  - Added: `2 DOSAGE AND ADMINISTRATION > 2.5 Renal Impairment`, `2 DOSAGE AND ADMINISTRATION > 2.6 Missed Dose`, `5 WARNINGS AND PRECAUTIONS > 5.4 Acute Kidney Injury`, `5 WARNINGS AND PRECAUTIONS > 5.5 Systemic Atheroemboli and Cholesterol Microemboli`, `5 WARNINGS AND PRECAUTIONS > 5.6 Limb Ischemia, Necrosis, and Gangrene in Patients with HIT and HITTS`, `5 WARNINGS AND PRECAUTIONS > 5.7 Use in Pregnant Women with Mechanical Heart Valves`, `5 WARNINGS AND PRECAUTIONS > 5.8 Other Clinical Settings with Increased Risks`, `5 WARNINGS AND PRECAUTIONS > 5.9 Endogenous Factors Affecting INR`, `7 DRUG INTERACTIONS > 7.1 General Information`, `7 DRUG INTERACTIONS > 7.2 CYP450 Interactions` (+4 more)
  - Changed: `12 CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > SPL UNCLASSIFIED SECTION [2]`, `14 CLINICAL STUDIES > 14.2 Mechanical and Bioprosthetic Heart Valves`, `16 HOW SUPPLIED/STORAGE AND HANDLING`, `17 PATIENT COUNSELING INFORMATION > SPL UNCLASSIFIED SECTION`, `17 PATIENT COUNSELING INFORMATION > SPL UNCLASSIFIED SECTION [4]`, `17 PATIENT COUNSELING INFORMATION > SPL UNCLASSIFIED SECTION [5]`, `2 DOSAGE AND ADMINISTRATION > 2.3 Initial and Maintenance Dosing > SPL UNCLASSIFIED SECTION [2]`, `4 CONTRAINDICATIONS`, `5 WARNINGS AND PRECAUTIONS > 5.2 Tissue Necrosis`, `5 WARNINGS AND PRECAUTIONS > 5.3 Calciphylaxis` (+15 more)
  - Removed: `2 DOSAGE AND ADMINISTRATION > 2.5 Missed Dose`, `5 WARNINGS AND PRECAUTIONS > 5.4 Systemic Atheroemboli and Cholesterol Microemboli`, `5 WARNINGS AND PRECAUTIONS > 5.5 Limb Ischemia, Necrosis, and Gangrene in Patients with HIT and HITTS`, `5 WARNINGS AND PRECAUTIONS > 5.6 Use in Pregnant Women with Mechanical Heart Valves`, `5 WARNINGS AND PRECAUTIONS > 5.7 Other Clinical Settings with Increased Risks`, `5 WARNINGS AND PRECAUTIONS > 5.8 Endogenous Factors Affecting INR`, `7 DRUG INTERACTIONS > 7.1 CYP450 Interactions`, `7 DRUG INTERACTIONS > 7.2 Drugs that Increase Bleeding Risk`, `7 DRUG INTERACTIONS > 7.3 Antibiotics and Antifungals`, `7 DRUG INTERACTIONS > 7.4 Botanical (Herbal) Products and Foods` (+1 more)
- Verdicts: changed 0 · broken 0 · still valid 0

#### 12 CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > SPL UNCLASSIFIED SECTION [2]

```diff
@@ -1 +1 @@
-Distribution Warfarin distributes into a relatively small apparent volume of distribution of about 0.14 L/kg. A distribution phase lasting 6 to 12 hours is distinguishable after rapid intravenous or oral administration of an aqueous solution. Approximately 99% of the drug is bound to plasma proteins.
+Distribution Warfarin shows a volume of distribution of about 0.14 L/kg. Approximately 99% of the drug is bound to plasma proteins.
```

#### 14 CLINICAL STUDIES > 14.2 Mechanical and Bioprosthetic Heart Valves

```diff
@@ -1,3 +1,3 @@
-In a prospective, randomized, open-label, positive-controlled study in 254 patients with mechanical prosthetic heart valves, the thromboembolic-free interval was found to be significantly greater in patients treated with warfarin alone compared with dipyridamole/aspirin treated patients (p<0.005) and pentoxifylline/aspirin-treated patients (p<0.05). The results of this study are presented in Table 5.
+In a prospective, randomized, open-label, positive-controlled study in 254 patients with mechanical prosthetic heart valves, the thromboembolic-free interval was found to be significantly greater in patients treated with warfarin alone compared with dipyridamole/aspirin-treated patients (p<0.005) and pentoxifylline/aspirin-treated patients (p<0.05). The results of this study are presented in Table 5.
 The results of this study are presented in Table 5. Table 5: Prospective, Randomized, Open-Label, Positive-Controlled Clinical Study of Warfarin in Patients with Mechanical Prosthetic Heart Valves Patients Treated With Event Warfarin Dipyridamole/Aspirin Pentoxifylline/Aspirin py=patient years Thromboembolism 2.2/100 py 8.6/100 py 7.9/100 py Major Bleeding 2.5/100 py 0.0/100 py 0.9/100 py In a prospective, open-label, clinical study comparing moderate (INR 2.65) versus high intensity (INR 9.0) warfarin therapies in 258 patients with mechanical prosthetic heart valves, thromboembolism occurred with similar frequency in the two groups (4.0 and 3.7 events per 100 patient years, respectively). Major bleeding was more common in the high intensity group. The results of this study are presented in Table 6.
 Major bleeding was more common in the high intensity group. The results of this study are presented in Table 6. Table 6: Prospective, Open-Label Clinical Study of Warfarin in Patients with Mechanical Prosthetic Heart Valves Event Moderate Warfarin TherapyINR 2.65 High Intensity Warfarin TherapyINR 9.0 py=patient years Thromboembolism 4.0/100 py 3.7/100 py Major Bleeding 0.95/100 py 2.1/100 py In a randomized trial in 210 patients comparing two intensities of warfarin therapy (INR 2.0 to 2.25 vs. INR 2.5 to 4.0) for a three-month period following tissue heart valve replacement, thromboembolism occurred with similar frequency in the two groups (major embolic events 2.0% vs. 1.9%, respectively, and minor embolic events 10.8% vs. 10.2%, respectively). Major hemorrhages occurred in 4.6% of patients in the higher intensity INR group compared to zero in the lower intensity INR group.
```

#### 16 HOW SUPPLIED/STORAGE AND HANDLING

```diff
@@ -1,4 +1,4 @@
 Tablets JANTOVEN tablets are single scored, compressed tablets with one side scored and debossed with WRF above the score and 1, 2, 2½, 3, 4, 5, 6, 7½, or 10 below the score and with 832 debossed on the opposite side. JANTOVEN is available in bottles and unit dose blister packages with potencies and colors as follows: 1 mg – Compressed tablet, pink, round; in bottles of 100 (NDC 0832-1211-00) and 1000 (NDC 0832-1211-10) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1211-01). 2 mg – Compressed tablet, lavender, round; in bottles of 100 (NDC 0832-1212-00) and 1000 (NDC 0832-1212-10) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1212-01).
 2½ mg – Compressed tablet, green, round; in bottles of 100 (NDC 0832-1213-00) and 1000 (NDC 0832-1213-10) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1213-01). 3 mg – Compressed tablet, tan, round; in bottles of 100 (NDC 0832-1214-00) and 1000 (NDC 0832-1214-10) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1214-01). 4 mg – Compressed tablet, blue, round; in bottles of 100 (NDC 0832-1215-00) and 1000 (NDC 0832-1215-10) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1215-01).
 5 mg – Compressed tablet, peach, round; in bottles of 100 (NDC 0832-1216-00) and 1000 (NDC 0832-1216-10) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1216-01). 6 mg – Compressed tablet, teal, round; in bottles of 100 (NDC 0832-1217-00) and 1000 (NDC 0832-1217-10) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1217-01). 7½ mg – Compressed tablet, yellow, round; in bottles of 100 (NDC 0832-1218-00) and 500 (NDC 0832-1218-50) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1218-01).
-10 mg – Compressed tablet, white, round; in bottles of 100 (NDC 0832-1219-00) and 500 (NDC 0832-1219-50) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1219-01). Store at 20° to 25°C (68° to 77°F). Excursions permitted to 15° to 30°C (59° to 86°F). [See USP Controlled Room Temperature.] Protect from light and moisture. Dispense in a tight, light-resistant container with a child-resistant closure.
+10 mg – Compressed tablet, white (dye-free), round; in bottles of 100 (NDC 0832-1219-00) and 500 (NDC 0832-1219-50) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1219-01). Store at 20° to 25°C (68° to 77°F). Excursions permitted to 15° to 30°C (59° to 86°F). [See USP Controlled Room Temperature.] Protect from light and moisture. Dispense in a tight, light-resistant container with a child-resistant closure.
```

### 2016-11-28 · JANTOVEN (WARFARIN SODIUM) TABLET [UPSHER-SMITH LABORATORIES, LLC] · v7 → v8

`19a69a72-ac5d-45d5-a94d-a5aaecbe4730` (openfda) · version key `9` → `10`

- Sections: 26 added, 34 changed, 11 removed
  - Added: `16 HOW SUPPLIED/STORAGE AND HANDLING > SPL UNCLASSIFIED SECTION`, `17 PATIENT COUNSELING INFORMATION > SPL UNCLASSIFIED SECTION [2]`, `17 PATIENT COUNSELING INFORMATION > SPL UNCLASSIFIED SECTION [3]`, `17 PATIENT COUNSELING INFORMATION > SPL UNCLASSIFIED SECTION [4]`, `17 PATIENT COUNSELING INFORMATION > SPL UNCLASSIFIED SECTION [5]`, `2 DOSAGE AND ADMINISTRATION > 2.7 Treatment during Dentistry and Surgery`, `2 DOSAGE AND ADMINISTRATION > 2.8 Conversion from Other Anticoagulants`, `2 DOSAGE AND ADMINISTRATION > 2.8 Conversion from Other Anticoagulants > SPL UNCLASSIFIED SECTION`, `2 DOSAGE AND ADMINISTRATION > 2.8 Conversion from Other Anticoagulants > SPL UNCLASSIFIED SECTION [2]`, `5 WARNINGS AND PRECAUTIONS > 5.3 Calciphylaxis` (+16 more)
  - Changed: `11 DESCRIPTION`, `12 CLINICAL PHARMACOLOGY > 12.2 Pharmacodynamics`, `12 CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > SPL UNCLASSIFIED SECTION [3]`, `12 CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > SPL UNCLASSIFIED SECTION [5]`, `14 CLINICAL STUDIES > 14.1 Atrial Fibrillation`, `14 CLINICAL STUDIES > 14.2 Mechanical and Bioprosthetic Heart Valves`, `14 CLINICAL STUDIES > 14.3 Myocardial Infarction`, `15 REFERENCES`, `16 HOW SUPPLIED/STORAGE AND HANDLING`, `17 PATIENT COUNSELING INFORMATION` (+24 more)
  - Removed: `2 DOSAGE AND ADMINISTRATION > 2.7 Treatment During Dentistry and Surgery`, `2 DOSAGE AND ADMINISTRATION > 2.8 Conversion From Other Anticoagulants`, `2 DOSAGE AND ADMINISTRATION > 2.8 Conversion From Other Anticoagulants > SPL UNCLASSIFIED SECTION`, `2 DOSAGE AND ADMINISTRATION > 2.8 Conversion From Other Anticoagulants > SPL UNCLASSIFIED SECTION [2]`, `5 WARNINGS AND PRECAUTIONS > 5.3 Systemic Atheroemboli and Cholesterol Microemboli`, `5 WARNINGS AND PRECAUTIONS > 5.4 Heparin-Induced Thrombocytopenia`, `5 WARNINGS AND PRECAUTIONS > 5.5 Use in Pregnant Women with Mechanical Heart Valves`, `5 WARNINGS AND PRECAUTIONS > 5.6 Females of Reproductive Potential`, `8 USE IN SPECIFIC POPULATIONS > 8.3 Nursing Mothers`, `8 USE IN SPECIFIC POPULATIONS > 8.8 Females of Reproductive Potential` (+1 more)
- Verdicts: changed 0 · broken 0 · still valid 0

#### 11 DESCRIPTION

```diff
@@ -1,2 +1,2 @@
-JANTOVEN (Warfarin Sodium Tablets, USP) is an anticoagulant that acts by inhibiting vitamin K-dependent coagulation factors. Chemically, it is 3-(α-acetonylbenzyl)-4-hydroxycoumarin and is a racemic mixture of the R- and S-enantiomers. Its empirical formula is C19H15NaO4, and its structural formula is represented by the following: Warfarin sodium occurs as a white, odorless powder that is discolored by light. It is very soluble in water, freely soluble in alcohol, and very slightly soluble in chloroform and ether. JANTOVEN tablets for oral use contain: 1 mg, 2 mg, 2½ mg, 3 mg, 4 mg, 5 mg, 6 mg, 7½ mg or 10 mg of warfarin sodium, USP. They also contain: All strengths: Lactose monohydrate, magnesium stearate, povidone, and pregelatinized starch (corn).
-1 mg: FD&C Red #40 Aluminum Lake 2 mg: FD&C Blue #2 Aluminum Lake and FD&C Red #40 Aluminum Lake 2½ mg: D&C Yellow #10 Aluminum Lake and FD&C Blue #1 Aluminum Lake 3 mg: Brown #75 Synthetic Brown Iron Oxide 4 mg: FD&C Blue #1 Aluminum Lake 5 mg: FD&C Yellow #6 Aluminum Lake 6 mg: Yellow #10 Synthetic Yellow Iron Oxide, Black #85 Synthetic Black Iron Oxide and FD&C Blue #1 Aluminum Lake 7½ mg: D&C Yellow #10 Aluminum Lake and FD&C Yellow #6 Aluminum Lake 10 mg: Dye Free
+JANTOVEN (Warfarin Sodium Tablets, USP) is an anticoagulant that acts by inhibiting vitamin K-dependent coagulation factors. The chemical name of warfarin sodium is 3-(α-acetonylbenzyl)-4-hydroxycoumarin sodium salt, which is a racemic mixture of the R- and S-enantiomers. Crystalline warfarin sodium is an isopropanol clathrate. Its empirical formula is C19H15NaO4, and its structural formula is represented by the following: Crystalline warfarin sodium occurs as a white, odorless, crystalline powder that is discolored by light. It is very soluble in water, freely soluble in alcohol, and very slightly soluble in chloroform and ether. JANTOVEN tablets for oral use contain: 1 mg, 2 mg, 2½ mg, 3 mg, 4 mg, 5 mg, 6 mg, 7½ mg or 10 mg of warfarin sodium, USP.
+They also contain: All strengths: Lactose monohydrate, magnesium stearate, povidone, and pregelatinized starch (corn). 1 mg: FD&C Red #40 Aluminum Lake 2 mg: FD&C Blue #2 Aluminum Lake and FD&C Red #40 Aluminum Lake 2½ mg: D&C Yellow #10 Aluminum Lake and FD&C Blue #1 Aluminum Lake 3 mg: Brown #75 Synthetic Brown Iron Oxide 4 mg: FD&C Blue #1 Aluminum Lake 5 mg: FD&C Yellow #6 Aluminum Lake 6 mg: Yellow #10 Synthetic Yellow Iron Oxide, Black #85 Synthetic Black Iron Oxide and FD&C Blue #1 Aluminum Lake 7½ mg: D&C Yellow #10 Aluminum Lake and FD&C Yellow #6 Aluminum Lake 10 mg: Dye Free
```

#### 12 CLINICAL PHARMACOLOGY > 12.2 Pharmacodynamics

```diff
@@ -1 +1 @@
-An anticoagulation effect generally occurs within 24 hours after warfarin administration. However, peak anticoagulant effect may be delayed 72 to 96 hours. The duration of action of a single dose of racemic warfarin is 2 to 5 days. The effects of JANTOVEN may become more pronounced as effects of daily maintenance doses overlap. This is consistent with the half-lives of the affected vitamin K-dependent clotting factors and anticoagulation proteins: Factor II - 60 hours, VII - 4 to 6 hours, IX - 24 hours, X - 48 to 72 hours, and proteins C and S are approximately 8 hours and 30 hours, respectively.
+An anticoagulation effect generally occurs within 24 hours after warfarin administration. However, peak anticoagulant effect may be delayed 72 to 96 hours. The duration of action of a single dose of racemic warfarin is 2 to 5 days. The effects of JANTOVEN may become more pronounced as effects of daily maintenance doses overlap. This is consistent with the half-lives of the affected vitamin K-dependent clotting factors and anticoagulation proteins: Factor II – 60 hours, VII – 4 to 6 hours, IX – 24 hours, X – 48 to 72 hours, and proteins C and S are approximately 8 hours and 30 hours, respectively.
```

#### 12 CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > SPL UNCLASSIFIED SECTION [3]

```diff
@@ -1 +1 @@
-Metabolism The elimination of warfarin is almost entirely by metabolism. Warfarin is stereoselectively metabolized by hepatic cytochrome P-450 (CYP450) microsomal enzymes to inactive hydroxylated metabolites (predominant route) and by reductases to reduced metabolites (warfarin alcohols) with minimal anticoagulant activity. Identified metabolites of warfarin include dehydrowarfarin, two diastereoisomer alcohols, and 4′-, 6-, 7-, 8-, and 10-hydroxywarfarin. The CYP450 isozymes involved in the metabolism of warfarin include CYP2C9, 2C19, 2C8, 2C18, 1A2, and 3A4. CYP2C9, a polymorphic enzyme, is likely to be the principal form of human liver CYP450 that modulates the in vivo anticoagulant activity of warfarin. Patients with one or more variant CYP2C9 alleles have decreased S-warfarin clearance [see Clinical Pharmacology (12.5) ].
+Metabolism The elimination of warfarin is almost entirely by metabolism. Warfarin is stereoselectively metabolized by hepatic cytochrome P-450 (CYP450) microsomal enzymes to inactive hydroxylated metabolites (predominant route) and by reductases to reduced metabolites (warfarin alcohols) with minimal anticoagulant activity. Identified metabolites of warfarin include dehydrowarfarin, two diastereoisomer alcohols, and 4'-, 6-, 7-, 8-, and 10-hydroxywarfarin. The CYP450 isozymes involved in the metabolism of warfarin include CYP2C9, 2C19, 2C8, 2C18, 1A2, and 3A4. CYP2C9, a polymorphic enzyme, is likely to be the principal form of human liver CYP450 that modulates the in vivo anticoagulant activity of warfarin. Patients with one or more variant CYP2C9 alleles have decreased S-warfarin clearance [see Clinical Pharmacology (12.5) ].
```

### 2016-06-06 · JANTOVEN (WARFARIN SODIUM) TABLET [UPSHER-SMITH LABORATORIES, LLC] · v6 → v7

`19a69a72-ac5d-45d5-a94d-a5aaecbe4730` (openfda) · version key `7` → `9`

- Sections: 1 added, 13 changed, 2 removed
  - Added: `13 NONCLINICAL TOXICOLOGY > 13.1 Carcinogenesis, Mutagenesis, Impairment of Fertility`
  - Changed: `14 CLINICAL STUDIES > 14.2 Mechanical and Bioprosthetic Heart Valves`, `16 HOW SUPPLIED/STORAGE AND HANDLING`, `17 PATIENT COUNSELING INFORMATION > SPL UNCLASSIFIED SECTION`, `PRINCIPAL DISPLAY PANEL - 1 mg Tablet Bottle Label`, `PRINCIPAL DISPLAY PANEL - 10 mg Tablet Bottle Label`, `PRINCIPAL DISPLAY PANEL - 2 mg Tablet Bottle Label`, `PRINCIPAL DISPLAY PANEL - 2½ mg Tablet Bottle Label`, `PRINCIPAL DISPLAY PANEL - 3 mg Tablet Bottle Label`, `PRINCIPAL DISPLAY PANEL - 4 mg Tablet Bottle Label`, `PRINCIPAL DISPLAY PANEL - 5 mg Tablet Bottle Label` (+3 more)
  - Removed: `13 NONCLINICAL TOXICOLOGY > 13.1. Carcinogenesis, Mutagenesis, Impairment of Fertility`, `RECENT MAJOR CHANGES SECTION`
- Verdicts: changed 0 · broken 0 · still valid 0

#### 14 CLINICAL STUDIES > 14.2 Mechanical and Bioprosthetic Heart Valves

```diff
@@ -1,3 +1,3 @@
-In a prospective, randomized, open-label, positive-controlled study in 254 patients with mechanical prosthetic heart valves, the thromboembolic-free interval was found to be significantly greater in patients treated with warfarin alone compared with dipyridamole/aspirintreated patients (p<0.005) and pentoxifylline/aspirin-treated patients (p<0.05). The results of this study are presented in Table 5. Table 5: Prospective, Randomized, Open-Label, Positive-Controlled Clinical Study of Warfarin in Patients with Mechanical Prosthetic Heart Valves Patients Treated With Event Warfarin Dipyridamole/Aspirin Pentoxifylline/Aspirin py=patient years Thromboembolism 2.2/100 py 8.6/100 py 7.9/100 py Major Bleeding 2.5/100 py 0.0/100 py 0.9/100 py In a prospective, open-label, clinical study comparing moderate (INR 2.65) vs.
+In a prospective, randomized, open-label, positive-controlled study in 254 patients with mechanical prosthetic heart valves, the thromboembolic-free interval was found to be significantly greater in patients treated with warfarin alone compared with dipyridamole/aspirin treated patients (p<0.005) and pentoxifylline/aspirin-treated patients (p<0.05). The results of this study are presented in Table 5. Table 5: Prospective, Randomized, Open-Label, Positive-Controlled Clinical Study of Warfarin in Patients with Mechanical Prosthetic Heart Valves Patients Treated With Event Warfarin Dipyridamole/Aspirin Pentoxifylline/Aspirin py=patient years Thromboembolism 2.2/100 py 8.6/100 py 7.9/100 py Major Bleeding 2.5/100 py 0.0/100 py 0.9/100 py In a prospective, open-label, clinical study comparing moderate (INR 2.65) vs.
 high intensity (INR 9.0) warfarin therapies in 258 patients with mechanical prosthetic heart valves, thromboembolism occurred with similar frequency in the two groups (4.0 and 3.7 events per 100 patient years, respectively). Major bleeding was more common in the high intensity group. The results of this study are presented in Table 6. Table 6: Prospective, Open-Label Clinical Study of Warfarin in Patients with Mechanical Prosthetic Heart Valves Event Moderate Warfarin TherapyINR 2.65 High Intensity Warfarin TherapyINR 9.0 py=patient years Thromboembolism 4.0/100 py 3.7/100 py Major Bleeding 0.95/100 py 2.1/100 py In a randomized trial in 210 patients comparing two intensities of warfarin therapy (INR 2.0-2.25 vs. INR 2.5-4.0) for a three-month period following tissue heart valve replacement, thromboembolism occurred with similar frequency in the two groups (major embolic events 2.0% vs.
 1.9%, respectively, and minor embolic events 10.8% vs. 10.2%, respectively). Major hemorrhages occurred in 4.6% of patients in the higher intensity INR group compared to zero in the lower intensity INR group.
```

#### 16 HOW SUPPLIED/STORAGE AND HANDLING

```diff
@@ -1,4 +1,4 @@
 Tablets JANTOVEN tablets are single scored, compressed tablets with one side scored and debossed with WRF above the score and 1, 2, 2½, 3, 4, 5, 6, 7½, or 10 below the score and with 832 debossed on the opposite side. JANTOVEN is available in bottles and unit-dose blister packages with potencies and colors as follows: 1 mg - Compressed tablet, pink, round; in bottles of 100 (NDC 0832-1211-00) and 1000 (NDC 0832-1211-10) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1211-01). 2 mg - Compressed tablet, lavender, round; in bottles of 100 (NDC 0832-1212-00) and 1000 (NDC 0832-1212-10) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1212-01).
 2½ mg -Compressed tablet, green, round; in bottles of 100 (NDC 0832-1213-00) and 1000 (NDC 0832-1213-10) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1213-01). 3 mg - Compressed tablet, tan, round; in bottles of 100 (NDC 0832-1214-00) and 1000 (NDC 0832-1214-10) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1214-01). 4 mg - Compressed tablet, blue, round; in bottles of 100 (NDC 0832-1215-00) and 1000 (NDC 0832-1215-10) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1215-01).
 5 mg - Compressed tablet, peach, round; in bottles of 100 (NDC 0832-1216-00) and 1000 (NDC 0832-1216-10) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1216-01). 6 mg - Compressed tablet, teal, round; in bottles of 100 (NDC 0832-1217-00) and 1000 (NDC 0832-1217-10) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1217-01). 7½ mg - Compressed tablet, yellow, round; in bottles of 100 (NDC 0832-1218-00) and 500 (NDC 0832-1218-50) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1218-01).
-10 mg - Compressed tablet, white, round; in bottles of 100 (NDC 0832-1219-00) and 500 (NDC 0832-1219-50) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1219-01). Store at 20-25°C (68-77°F). Excursions permitted to 15-30°C (59-86°F). [See USP Controlled Room Temperature.] Protect from light and moisture. Dispense in a tight, light-resistant container with a child-resistant closure.
+10 mg - Compressed tablet, white, round; in bottles of 100 (NDC 0832-1219-00) and 500 (NDC 0832-1219-50) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1219-01). Store at 20 to 25°C (68 to 77°F). Excursions permitted to 15 to 30°C (59 to 86°F). [See USP Controlled Room Temperature.] Protect from light and moisture. Dispense in a tight, light-resistant container with a child-resistant closure.
```

#### 17 PATIENT COUNSELING INFORMATION > SPL UNCLASSIFIED SECTION

```diff
@@ -1 +1 @@
-Manufactured by UPSHER-SMITH LABORATORIES, INC. Maple Grove, MN 55369 Revised 0215
+Manufactured by UPSHER-SMITH LABORATORIES, INC. Maple Grove, MN 55369 Revised 0116
```

### 2015-03-11 · JANTOVEN (WARFARIN SODIUM) TABLET [UPSHER-SMITH LABORATORIES, LLC] · v5 → v6

`19a69a72-ac5d-45d5-a94d-a5aaecbe4730` (openfda) · version key `6` → `7`

- Sections: 72 added, 1 changed, 72 removed
  - Added: `1 INDICATIONS AND USAGE`, `10 OVERDOSAGE`, `10 OVERDOSAGE > 10.1 Signs and Symptoms`, `10 OVERDOSAGE > 10.2 Treatment`, `11 DESCRIPTION`, `12 CLINICAL PHARMACOLOGY`, `12 CLINICAL PHARMACOLOGY > 12.1 Mechanism of Action`, `12 CLINICAL PHARMACOLOGY > 12.2 Pharmacodynamics`, `12 CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics`, `12 CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > SPL UNCLASSIFIED SECTION` (+62 more)
  - Changed: `PRINCIPAL DISPLAY PANEL - 6 mg Tablet Bottle Label`
  - Removed: `1. INDICATIONS AND USAGE`, `10. OVERDOSAGE`, `10. OVERDOSAGE > 10.1 Signs and Symptoms`, `10. OVERDOSAGE > 10.2 Treatment`, `11. DESCRIPTION`, `12. CLINICAL PHARMACOLOGY`, `12. CLINICAL PHARMACOLOGY > 12.1 Mechanism of Action`, `12. CLINICAL PHARMACOLOGY > 12.2 Pharmacodynamics`, `12. CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics`, `12. CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > SPL UNCLASSIFIED SECTION` (+62 more)
- Verdicts: changed 0 · broken 0 · still valid 0

#### PRINCIPAL DISPLAY PANEL - 6 mg Tablet Bottle Label

```diff
@@ -1 +1 @@
-NDC 0832-1217-00 Jantoven ® Warfarin SodiumTablets, USP 6 mg DISPENSE WITH MEDICATION GUIDE HIGHLY POTENT ANTICOAGULANT WARNING: Serious bleeding results from overdosage. Do not use or dispense before reading directions andwarnings in accompanying product information. 100 Tablets Rx only UPSHER-SMITH
+NDC 0832-1217-00 Jantoven ® Warfarin SodiumTablets, USP 6 mg DISPENSE WITH MEDICATION GUIDE HIGHLY POTENT ANTICOAGULANT WARNING: Serious bleeding results from overdosage. Donot use or dispense before reading directions andwarnings in accompanying product information. 100 Tablets Rx only UPSHER-SMITH
```

### 2014-09-08 · JANTOVEN (WARFARIN SODIUM) TABLET [UPSHER-SMITH LABORATORIES, LLC] · v4 → v5

`19a69a72-ac5d-45d5-a94d-a5aaecbe4730` (openfda) · version key `4` → `6`

- Sections: 24 added, 4 changed, 24 removed
  - Added: `12. CLINICAL PHARMACOLOGY > 12.1 Mechanism of Action`, `12. CLINICAL PHARMACOLOGY > 12.2 Pharmacodynamics`, `12. CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics`, `12. CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > SPL UNCLASSIFIED SECTION`, `12. CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > SPL UNCLASSIFIED SECTION [2]`, `12. CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > SPL UNCLASSIFIED SECTION [3]`, `12. CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > SPL UNCLASSIFIED SECTION [4]`, `12. CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > SPL UNCLASSIFIED SECTION [5]`, `12. CLINICAL PHARMACOLOGY > 12.3 Pharmacokinetics > SPL UNCLASSIFIED SECTION [6]`, `8. USE IN SPECIFIC POPULATIONS > 8.1 Pregnancy` (+14 more)
  - Changed: `16. HOW SUPPLIED/STORAGE AND HANDLING`, `17. PATIENT COUNSELING INFORMATION > SPL UNCLASSIFIED SECTION`, `2. DOSAGE AND ADMINISTRATION > 2.3 Initial and Maintenance Dosing > SPL UNCLASSIFIED SECTION`, `SPL MEDGUIDE SECTION`
  - Removed: `12. CLINICAL PHARMACOLOGY > 12.1. Mechanism of Action`, `12. CLINICAL PHARMACOLOGY > 12.2. Pharmacodynamics`, `12. CLINICAL PHARMACOLOGY > 12.3. Pharmacokinetics`, `12. CLINICAL PHARMACOLOGY > 12.3. Pharmacokinetics > SPL UNCLASSIFIED SECTION`, `12. CLINICAL PHARMACOLOGY > 12.3. Pharmacokinetics > SPL UNCLASSIFIED SECTION [2]`, `12. CLINICAL PHARMACOLOGY > 12.3. Pharmacokinetics > SPL UNCLASSIFIED SECTION [3]`, `12. CLINICAL PHARMACOLOGY > 12.3. Pharmacokinetics > SPL UNCLASSIFIED SECTION [4]`, `12. CLINICAL PHARMACOLOGY > 12.3. Pharmacokinetics > SPL UNCLASSIFIED SECTION [5]`, `12. CLINICAL PHARMACOLOGY > 12.3. Pharmacokinetics > SPL UNCLASSIFIED SECTION [6]`, `8. USE IN SPECIFIC POPULATIONS > 8.1. Pregnancy` (+14 more)
- Verdicts: changed 0 · broken 0 · still valid 0

#### 16. HOW SUPPLIED/STORAGE AND HANDLING

```diff
@@ -1,4 +1,4 @@
 Tablets JANTOVEN tablets are single scored, compressed tablets with one side scored and debossed with WRF above the score and 1, 2, 2½, 3, 4, 5, 6, 7½, or 10 below the score and with 832 debossed on the opposite side. JANTOVEN is available in bottles and unit-dose blister packages with potencies and colors as follows: 1 mg - Compressed tablet, pink, round; in bottles of 100 (NDC 0832-1211-00) and 1000 (NDC 0832-1211-10) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1211-01). 2 mg - Compressed tablet, lavender, round; in bottles of 100 (NDC 0832-1212-00) and 1000 (NDC 0832-1212-10) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1212-01).
-2½ mg -Compressed tablet, green, round; in bottles of 100 (NDC 0832-1213-00) and 1000 (NDC 0832-1213-10) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (0832-1213-01). 3 mg - Compressed tablet, tan, round; in bottles of 100 (NDC 0832-1214-00) and 1000 (NDC 0832-1214-10) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1214-01). 4 mg - Compressed tablet, blue, round; in bottles of 100 (NDC 0832-1215-00) and 1000 (NDC 0832-1215-10) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1215-01).
+2½ mg -Compressed tablet, green, round; in bottles of 100 (NDC 0832-1213-00) and 1000 (NDC 0832-1213-10) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1213-01). 3 mg - Compressed tablet, tan, round; in bottles of 100 (NDC 0832-1214-00) and 1000 (NDC 0832-1214-10) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1214-01). 4 mg - Compressed tablet, blue, round; in bottles of 100 (NDC 0832-1215-00) and 1000 (NDC 0832-1215-10) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1215-01).
 5 mg - Compressed tablet, peach, round; in bottles of 100 (NDC 0832-1216-00) and 1000 (NDC 0832-1216-10) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1216-01). 6 mg - Compressed tablet, teal, round; in bottles of 100 (NDC 0832-1217-00) and 1000 (NDC 0832-1217-10) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1217-01). 7½ mg - Compressed tablet, yellow, round; in bottles of 100 (NDC 0832-1218-00) and 500 (NDC 0832-1218-50) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1218-01).
-10 mg- Compressed tablet, white, round; in bottles of 100 (NDC 0832-1219-00) and 500 (NDC 0832-1219-50) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1219-01). Store at 20-25°C (68-77°F). Excursions permitted to 15-30°C (59-86°F). [See USP Controlled Room Temperature.] Protect from light and moisture. Dispense in a tight, light-resistant container with a child-resistant closure.
+10 mg - Compressed tablet, white, round; in bottles of 100 (NDC 0832-1219-00) and 500 (NDC 0832-1219-50) and in unit dose cartons of 100 tablets (10 cards containing 10 tablets each) (NDC 0832-1219-01). Store at 20-25°C (68-77°F). Excursions permitted to 15-30°C (59-86°F). [See USP Controlled Room Temperature.] Protect from light and moisture. Dispense in a tight, light-resistant container with a child-resistant closure.
```

#### 17. PATIENT COUNSELING INFORMATION > SPL UNCLASSIFIED SECTION

```diff
@@ -1 +1 @@
-Manufactured byUPSHER-SMITH LABORATORIES, INC.Minneapolis, MN 55447 Revised 1011
+Manufactured by UPSHER-SMITH LABORATORIES, INC. Maple Grove, MN 55369 Revised 0213
```

#### 2. DOSAGE AND ADMINISTRATION > 2.3 Initial and Maintenance Dosing > SPL UNCLASSIFIED SECTION

```diff
@@ -1 +1 @@
-Dosing Recommendations without Consideration of Genotype If the patient's CYP2C9 and VKORC1 genotypes are not known, the initial dose of COUMADIN is usually 2 to 5 mg once daily. Determine each patient's dosing needs by close monitoring of the INR response and consideration of the indication being treated. Typical maintenance doses are 2 to 10 mg once daily.
+Dosing Recommendations without Consideration of Genotype If the patient's CYP2C9 and VKORC1 genotypes are not known, the initial dose of JANTOVEN is usually 2 to 5 mg once daily. Determine each patient's dosing needs by close monitoring of the INR response and consideration of the indication being treated. Typical maintenance doses are 2 to 10 mg once daily.
```

### 2011-12-07 · JANTOVEN (WARFARIN SODIUM) TABLET [UPSHER-SMITH LABORATORIES, LLC] · v3 → v4

`19a69a72-ac5d-45d5-a94d-a5aaecbe4730` (openfda) · version key `3` → `4`

- Sections: 80 added, 2 changed, 63 removed
  - Added: `1. INDICATIONS AND USAGE`, `10. OVERDOSAGE`, `10. OVERDOSAGE > 10.1 Signs and Symptoms`, `10. OVERDOSAGE > 10.2 Treatment`, `11. DESCRIPTION`, `12. CLINICAL PHARMACOLOGY`, `12. CLINICAL PHARMACOLOGY > 12.1. Mechanism of Action`, `12. CLINICAL PHARMACOLOGY > 12.2. Pharmacodynamics`, `12. CLINICAL PHARMACOLOGY > 12.3. Pharmacokinetics`, `12. CLINICAL PHARMACOLOGY > 12.3. Pharmacokinetics > SPL UNCLASSIFIED SECTION` (+70 more)
  - Changed: `SPL MEDGUIDE SECTION`, `WARNING: BLEEDING RISK`
  - Removed: `ADVERSE REACTIONS`, `CLINICAL PHARMACOLOGY`, `CLINICAL PHARMACOLOGY > Absorption`, `CLINICAL PHARMACOLOGY > Asians`, `CLINICAL PHARMACOLOGY > Clinical Trials`, `CLINICAL PHARMACOLOGY > Clinical Trials > Atrial Fibrillation (AF)`, `CLINICAL PHARMACOLOGY > Clinical Trials > Mechanical and Bioprosthetic Heart Valves`, `CLINICAL PHARMACOLOGY > Clinical Trials > Myocardial Infarction`, `CLINICAL PHARMACOLOGY > Distribution`, `CLINICAL PHARMACOLOGY > Elderly` (+53 more)
- Verdicts: changed 0 · broken 0 · still valid 0

#### SPL MEDGUIDE SECTION

```diff
@@ -1,9 +1,11 @@
-MEDICATION GUIDE Jantoven® Tablets (JAN-to-ven) Tablets(Warfarin Sodium Tablets, USP) Read this Medication Guide before you start taking Jantoven® Tablets (Warfarin Sodium Tablets, USP) and each time you get a refill. There may be new information. This Medication Guide does not take the place of talking to your healthcare provider about your medical condition or treatment. You and your healthcare provider should talk about Jantoven® Tablets when you start taking them and at regular checkups. What is the most important information I should know about Jantoven® Tablets? Take your Jantoven® Tablets exactly as prescribed to lower the chance of blood clots forming in your body. (See “What are Jantoven® Tablets?”). Jantoven® Tablets are very important for your health, but they can cause serious and life-threatening bleeding problems. To benefit from Jantoven® Tablets and also lower your chance for bleeding problems, you must: Get your regular blood test to check for your response to Jantoven® Tablets. This blood test is called a PT/INR test.
-This blood test is called a PT/INR test. The PT/INR test checks to see how fast your blood clots. Your healthcare provider will decide what PT/INR numbers are best for you. Your dose of Jantoven® Tablets will be adjusted to keep your PT/INR in a target range for you. Call your healthcare provider right away if you get any of the following signs or symptoms of bleeding problems: pain, swelling or discomfort headaches, dizziness, or weakness unusual bruising (bruises that develop without known cause or grow in size) nose bleeds bleeding gums bleeding from cuts takes a long time to stop menstrual bleeding or vaginal bleeding that is heavier than normal pink or brown urine red or black stools coughing up blood vomiting blood or material that looks like coffee grounds Many other medicines, including prescription and non-prescription medicines, vitamins and herbal supplements can interact with Jantoven® Tablets and: affect the dose you need, or increase Jantoven® Tablets side effects. Tell your healthcare provider about all the medicines, vitamins, and herbal supplements you take. Do not stop medicines or take anything new unless you have talked to your healthcare provider.
-Do not stop medicines or take anything new unless you have talked to your healthcare provider. Keep a list of your medicines with you at all times to show your healthcare provider and pharmacist. Do not take other medicines that contain warfarin. Warfarin is the active ingredient in Jantoven® Tablets. Some foods can interact with Jantoven® Tablets and affect your treatment and dose. Eat a normal, balanced diet. Talk to your doctor before you make any diet changes. Do not eat large amounts of leafy green vegetables. Leafy green vegetables contain Vitamin K. Certain vegetable oils also contain large amounts of Vitamin K. Too much Vitamin K can lower the effect of Jantoven® Tablets. Avoid drinking cranberry juice or eating cranberry products. Avoid drinking alcohol. Always tell all of your healthcare providers that you take Jantoven® Tablets. Wear or carry information that you take Jantoven® Tablets. What are Jantoven® Tablets? Jantoven® Tablets are an anticoagulant medicine. They are used to lower the chance of blood clots forming in your body.
... diff truncated
```

#### WARNING: BLEEDING RISK

```diff
@@ -1 +1 @@
-Warfarin sodium can cause major or fatal bleeding. Bleeding is more likely to occur during the starting period and with a higher dose (resulting in a higher INR). Risk factors for bleeding include high intensity of anticoagulation (INR >4.0), age ≥65, highly variable INRs, history of gastrointestinal bleeding, hypertension, cerebrovascular disease, serious heart disease, anemia, malignancy, trauma, renal insufficiency, concomitant drugs (see PRECAUTIONS ), and long duration of warfarin therapy. Regular monitoring of INR should be performed on all treated patients. Those at high risk of bleeding may benefit from more frequent INR monitoring, careful dose adjustment to desired INR, and a shorter duration of therapy. Patients should be instructed about prevention measures to minimize risk of bleeding and to report immediately to physicians signs and symptoms of bleeding (see PRECAUTIONS: Information for Patients ).
+Warfarin Sodium can cause major or fatal bleeding [see Warnings and Precautions (5.1) ]. Perform regular monitoring of INR in all treated patients [see Dosage and Administration (2.1) ]. Drugs, dietary changes, and other factors affect INR levels achieved with Warfarin Sodium therapy [see Drug Interactions (7) ]. Instruct patients about prevention measures to minimize risk of bleeding and to report signs and symptoms of bleeding [see Patient Counseling Information (17) ].
```

### 2010-01-30 · JANTOVEN (WARFARIN SODIUM) TABLET [UPSHER-SMITH LABORATORIES, LLC] · v2 → v3

`19a69a72-ac5d-45d5-a94d-a5aaecbe4730` (openfda) · version key `2` → `3`

- Sections: 11 added, 36 changed, 3 removed
  - Added: `PRINCIPAL DISPLAY PANEL - 1 mg Tablet Bottle Label`, `PRINCIPAL DISPLAY PANEL - 10 mg Tablet Bottle Label`, `PRINCIPAL DISPLAY PANEL - 2 mg Tablet Bottle Label`, `PRINCIPAL DISPLAY PANEL - 2.5 mg Tablet Bottle Label`, `PRINCIPAL DISPLAY PANEL - 3 mg Tablet Bottle Label`, `PRINCIPAL DISPLAY PANEL - 4 mg Tablet Bottle Label`, `PRINCIPAL DISPLAY PANEL - 5 mg Tablet Bottle Label`, `PRINCIPAL DISPLAY PANEL - 6 mg Tablet Bottle Label`, `PRINCIPAL DISPLAY PANEL - 7.5 mg Tablet Bottle Label`, `SPL LISTING DATA ELEMENTS SECTION` (+1 more)
  - Changed: `ADVERSE REACTIONS`, `CLINICAL PHARMACOLOGY > Clinical Trials > Atrial Fibrillation (AF)`, `CLINICAL PHARMACOLOGY > Clinical Trials > Mechanical and Bioprosthetic Heart Valves`, `CLINICAL PHARMACOLOGY > Clinical Trials > Myocardial Infarction`, `CLINICAL PHARMACOLOGY > Distribution`, `CLINICAL PHARMACOLOGY > Mechanism of Action`, `CLINICAL PHARMACOLOGY > Metabolism`, `CLINICAL PHARMACOLOGY > Pharmacogenomics`, `CONTRAINDICATIONS > Hemorrhagic tendencies or blood dyscrasias.`, `CONTRAINDICATIONS > Pregnancy` (+26 more)
  - Removed: `SPL SUPPLEMENTAL PATIENT MATERIAL`, `SPL SUPPLEMENTAL PATIENT MATERIAL > SPL MEDGUIDE SECTION`, `Untitled`
- Verdicts: changed 0 · broken 0 · still valid 0

#### ADVERSE REACTIONS

```diff
@@ -1,2 +1,2 @@
-Potential adverse reactions to Jantoven® Tablets (Warfarin Sodium Tablets, USP) may include:Fatal or nonfatal hemorrhage from any tissue or organ. This is a consequence of the anticoagulant effect. The signs, symptoms, and severity will vary according to the location and degree or extent of the bleeding. Hemorrhagic complications may present as paralysis; paresthesia; headache, chest, abdomen, joint, muscle or other pain; dizziness; shortness of breath, difficult breathing or swallowing; unexplained swelling; weakness; hypotension; or unexplained shock. Therefore, the possibility of hemorrhage should be considered in evaluating the condition of any anticoagulated patient with complaints which do not indicate an obvious diagnosis. Bleeding during anticoagulant therapy does not always correlate with PT/INR. (See OVERDOSAGE: Treatment.)Bleeding which occurs when the PT/INR is within the therapeutic range warrants diagnostic investigation since it may unmask a previously unsuspected lesion, e.g., tumor, ulcer, etc.Necrosis of skin and other tissues. (See WARNINGS.
-(See WARNINGS.)Adverse reactions reported infrequently include: hypersensitivity/allergic reactions, including anaphylactic reactions, systemic cholesterol microembolization, purple toes syndrome, hepatitis, cholestatic hepatic injury, jaundice, elevated liver enzymes, hypotension, vasculitis, edema, anemia, pallor, fever, rash, dermatitis, including bullous eruptions, urticaria, angina syndrome, chest pain, abdominal pain including cramping, flatulence/bloating, fatigue, lethargy, malaise, asthenia, nausea, vomiting, diarrhea, pain, headache, dizziness, loss of consciousness, syncope, coma, taste perversion, pruritus, alopecia, cold intolerance, and paresthesia including feeling cold and chills.Rare events of tracheal or tracheobronchial calcification have been reported in association with long-term warfarin therapy. The clinical significance of this event is unknown.Priapism has been associated with anticoagulant administration: however, a causal relationship has not been established.
+Potential adverse reactions to Jantoven® Tablets (Warfarin Sodium Tablets, USP) may include: Fatal or nonfatal hemorrhage from any tissue or organ. This is a consequence of the anticoagulant effect. The signs, symptoms, and severity will vary according to the location and degree or extent of the bleeding. Hemorrhagic complications may present as paralysis; paresthesia; headache, chest, abdomen, joint, muscle or other pain; dizziness; shortness of breath, difficult breathing or swallowing; unexplained swelling; weakness; hypotension; or unexplained shock. Therefore, the possibility of hemorrhage should be considered in evaluating the condition of any anticoagulated patient with complaints which do not indicate an obvious diagnosis. Bleeding during anticoagulant therapy does not always correlate with PT/INR. (See OVERDOSAGE: Treatment.) Bleeding which occurs when the PT/INR is within the therapeutic range warrants diagnostic investigation since it may unmask a previously unsuspected lesion, e.g., tumor, ulcer, etc. Necrosis of skin and other tissues. (See WARNINGS.)
... diff truncated
```

#### CLINICAL PHARMACOLOGY > Clinical Trials > Atrial Fibrillation (AF)

```diff
@@ -1,2 +1,3 @@
-In five prospective randomized controlled clinical trials involving 3711 patients with non-rheumatic AF, warfarin significantly reduced the risk of systemic thromboembolism including stroke (See Table 2). The risk reduction ranged from 60% to 86% in all except one trial (CAFA: 45%) which stopped early due to published positive results from two of these trials. The incidence of major bleeding in these trials ranged from 0.6 to 2.7% (See Table 2). Meta-analysis findings of these studies revealed that the effects of warfarin in reducing thromboembolic events including stroke were similar at either moderately high INR (2.0 - 4.5) or low INR (1.4 - 3.0). There was a significant reduction in minor bleeds at the low INR. Similar data from clinical studies in valvular atrial fibrillation patients are not available.Table 2: Clinical Studies Of Warfarin In Non-Rheumatic AF Patients* *All study results of warfarin vs.
-control are based on intention-to-treat analysis and include ischemic stroke and systemic thromboembolism, excluding hemorrhage and transient ischemic attacks. StudyNPT RatioINRThromboembolism% Major Bleeding Warfarin-Treated PatientsControl Patients% Risk Reductionp-valueWarfarin-Treated PatientsControl Patients AFASAK3353361.5-2.02.8-4.2600.0270.60.0 SPAF2102111.3-1.82.0-4.5670.011.91.9 BAATAF2122081.2-1.51.5-2.786<0.050.90.5 CAFA1871911.3-1.62.0-3.0450.252.70.5 SPINAF2602651.2-1.51.4-2.8790.0012.31.5
+In five prospective randomized controlled clinical trials involving 3711 patients with non-rheumatic AF, warfarin significantly reduced the risk of systemic thromboembolism including stroke (see Table 2 ). The risk reduction ranged from 60% to 86% in all except one trial (CAFA: 45%) which stopped early due to published positive results from two of these trials. The incidence of major bleeding in these trials ranged from 0.6% to 2.7% (see Table 2 ). Meta-analysis findings of these studies revealed that the effects of warfarin in reducing thromboembolic events including stroke were similar at either moderately high INR (2.0 - 4.5) or low INR (1.4 - 3.0). There was a significant reduction in minor bleeds at the low INR. Similar data from clinical studies in valvular atrial fibrillation patients are not available. Table 2: Clinical Studies of Warfarin In Non-Rheumatic AF PatientsAll study results of warfarin vs.
+Table 2: Clinical Studies of Warfarin In Non-Rheumatic AF PatientsAll study results of warfarin vs. control are based on intention-to-treat analysis and include ischemic stroke and systemic thromboembolism, excluding hemorrhagic stroke and transient ischemic attacks.
+Study N PT Ratio INR Thromboembolism % Major Bleeding Warfarin-Treated Patients Control Patients % Risk Reduction p -value Warfarin-Treated Patients Control Patients AFASAK 335 336 1.5-2.0 2.8-4.2 60 0.027 0.6 0.0 SPAF 210 211 1.3-1.8 2.0-4.5 67 0.01 1.9 1.9 BAATAF 212 208 1.2-1.5 1.5-2.7 86 <0.05 0.9 0.5 CAFA 187 191 1.3-1.6 2.0-3.0 45 0.25 2.7 0.5 SPINAF 260 265 1.2-1.5 1.4-2.8 79 0.001 2.3 1.5
```

#### CLINICAL PHARMACOLOGY > Clinical Trials > Mechanical and Bioprosthetic Heart Valves

```diff
@@ -1,2 +1,2 @@
-In a prospective, randomized, open label, positive-controlled study-9 in 254 patients, the thromboembolic-free interval was found to be significantly greater in patients with mechanical prosthetic heart valves treated with warfarin alone compared with dipyridamole-aspirin (p<0.005) and pentoxifylline-aspirin (p<0.05) treated patients. Rates of thromboembolic events in these groups were 2.2, 8.6, and 7.9/100 patient years, respectively. Major bleeding rates were 2.5, 0.0, and 0.9/100 patient years, respectively.In a prospective, open label, clinical trial comparing moderate (INR 2.65) vs. high intensity (INR 9.0) warfarin therapies in 258 patients with mechanical prosthetic heart valves, thromboembolism occurred with similar frequency in the two groups (4.0 and 3.7 events/100 patient years, respectively). Major bleeding was more common in the high intensity group (2.1 events/100 patient years) vs.
-Major bleeding was more common in the high intensity group (2.1 events/100 patient years) vs. 0.95 events/100 patient years in the moderate intensity group.-10In a randomized trial in 210 patients comparing two intensities of warfarin therapy (INR 2.0 - 2.25 vs. INR 2.5 - 4.0) for a three-month period following tissue heart valve replacement, thromboembolism occurred with similar frequency in the two groups (major embolic events 2.0% vs. 1.9%, respectively and minor embolic events 10.8% vs. 10.2 %, respectively). Major bleeding complications were more frequent with the higher intensity (major hemorrhages 4.6%) vs. none in the lower intensity.-11
+In a prospective, randomized, open label, positive-controlled study9 in 254 patients, the thromboembolic-free interval was found to be significantly greater in patients with mechanical prosthetic heart valves treated with warfarin alone compared with dipyridamole-aspirin (p<0.005) and pentoxifylline-aspirin (p<0.05) treated patients. Rates of thromboembolic events in these groups were 2.2, 8.6, and 7.9/100 patient years, respectively. Major bleeding rates were 2.5, 0.0, and 0.9/100 patient years, respectively. In a prospective, open label, clinical trial comparing moderate (INR 2.65) vs. high intensity (INR 9.0) warfarin therapies in 258 patients with mechanical prosthetic heart valves, thromboembolism occurred with similar frequency in the two groups (4.0 and 3.7 events/100 patient years, respectively). Major bleeding was more common in the high intensity group (2.1 events/100 patient years) vs.
+Major bleeding was more common in the high intensity group (2.1 events/100 patient years) vs. 0.95 events/100 patient years in the moderate intensity group.10 In a randomized trial in 210 patients comparing two intensities of warfarin therapy (INR 2.0 - 2.25 vs. INR 2.5 - 4.0) for a three-month period following tissue heart valve replacement, thromboembolism occurred with similar frequency in the two groups (major embolic events 2.0% vs. 1.9%, respectively and minor embolic events 10.8% vs. 10.2 %, respectively). Major bleeding complications were more frequent with the higher intensity (major hemorrhages 4.6%) vs. none in the lower intensity.11
```

### 2008-01-18 · JANTOVEN (WARFARIN SODIUM) TABLET [UPSHER-SMITH LABORATORIES, LLC] · v1 → v2

`19a69a72-ac5d-45d5-a94d-a5aaecbe4730` (openfda) · version key `1` → `2`

- Sections: 7 added, 26 changed, 6 removed
  - Added: `CLINICAL PHARMACOLOGY > Mechanism of Action`, `CLINICAL PHARMACOLOGY > Pharmacogenomics`, `DOSAGE AND ADMINISTRATION > Missed Dose > Laboratory Control`, `PRECAUTIONS > Considerations for Increased Bleeding Risk`, `PRECAUTIONS > Drug/Drug and Drug/Disease Interactions`, `SPL UNCLASSIFIED SECTION [2]`, `SPL UNCLASSIFIED SECTION [3]`
  - Changed: `ADVERSE REACTIONS`, `CLINICAL PHARMACOLOGY`, `CLINICAL PHARMACOLOGY > Clinical Trials > Atrial Fibrillation (AF)`, `CLINICAL PHARMACOLOGY > Clinical Trials > Mechanical and Bioprosthetic Heart Valves`, `CLINICAL PHARMACOLOGY > Clinical Trials > Myocardial Infarction`, `CLINICAL PHARMACOLOGY > Metabolism`, `DOSAGE AND ADMINISTRATION`, `DOSAGE AND ADMINISTRATION > Atrial Fibrillation`, `DOSAGE AND ADMINISTRATION > Duration of Therapy`, `DOSAGE AND ADMINISTRATION > Initial Dosage` (+16 more)
  - Removed: `DOSAGE AND ADMINISTRATION > Missed Dose > SPL UNCLASSIFIED SECTION [3]`, `PRECAUTIONS > Drug-Drug and Drug-Disease Interactions`, `PRECAUTIONS > Special Risk Patients`, `WARNINGS > SPL UNCLASSIFIED SECTION`, `WARNINGS > SPL UNCLASSIFIED SECTION [2]`, `WARNINGS > SPL UNCLASSIFIED SECTION [3]`
- Verdicts: changed 0 · broken 0 · still valid 0

#### ADVERSE REACTIONS

```diff
@@ -1,2 +1,2 @@
 Potential adverse reactions to Jantoven® Tablets (Warfarin Sodium Tablets, USP) may include:Fatal or nonfatal hemorrhage from any tissue or organ. This is a consequence of the anticoagulant effect. The signs, symptoms, and severity will vary according to the location and degree or extent of the bleeding. Hemorrhagic complications may present as paralysis; paresthesia; headache, chest, abdomen, joint, muscle or other pain; dizziness; shortness of breath, difficult breathing or swallowing; unexplained swelling; weakness; hypotension; or unexplained shock. Therefore, the possibility of hemorrhage should be considered in evaluating the condition of any anticoagulated patient with complaints which do not indicate an obvious diagnosis. Bleeding during anticoagulant therapy does not always correlate with PT/INR. (See OVERDOSAGE: Treatment.)Bleeding which occurs when the PT/INR is within the therapeutic range warrants diagnostic investigation since it may unmask a previously unsuspected lesion, e.g., tumor, ulcer, etc.Necrosis of skin and other tissues. (See WARNINGS.
-(See WARNINGS.)Adverse reactions reported infrequently include: hypersensitivity/allergic reactions, systemic cholesterol microembolization, purple toes syndrome, hepatitis, cholestatic hepatic injury, jaundice, elevated liver enzymes, hypotension, vasculitis, edema, anemia, pallor, fever, rash, dermatitis, including bullous eruptions, urticaria, angina syndrome, chest pain, abdominal pain including cramping, flatulence/bloating, fatigue, lethargy, malaise, asthenia, nausea, vomiting, diarrhea, pain, headache, dizziness, loss of consciousness, syncope, coma, taste perversion, pruritus, alopecia, cold intolerance, and paresthesia including feeling cold and chills.Rare events of tracheal or tracheobronchial calcification have been reported in association with long-term warfarin therapy. The clinical significance of this event is unknown.Priapism has been associated with anticoagulant administration, however, a causal relationship has not been established.
+(See WARNINGS.)Adverse reactions reported infrequently include: hypersensitivity/allergic reactions, including anaphylactic reactions, systemic cholesterol microembolization, purple toes syndrome, hepatitis, cholestatic hepatic injury, jaundice, elevated liver enzymes, hypotension, vasculitis, edema, anemia, pallor, fever, rash, dermatitis, including bullous eruptions, urticaria, angina syndrome, chest pain, abdominal pain including cramping, flatulence/bloating, fatigue, lethargy, malaise, asthenia, nausea, vomiting, diarrhea, pain, headache, dizziness, loss of consciousness, syncope, coma, taste perversion, pruritus, alopecia, cold intolerance, and paresthesia including feeling cold and chills.Rare events of tracheal or tracheobronchial calcification have been reported in association with long-term warfarin therapy. The clinical significance of this event is unknown.Priapism has been associated with anticoagulant administration: however, a causal relationship has not been established.
```

#### CLINICAL PHARMACOLOGY

```diff
@@ -1,2 +1 @@
-Jantoven® Tablets (Warfarin Sodium Tablets, USP) and other coumarin anticoagulants act by inhibiting the synthesis of vitamin K dependent clotting factors, which include Factors II, VII, IX and X, and the anticoagulant proteins C and S. Half-lives of these clotting factors are as follows: Factor II - 60 hours, VII – 4 - 6 hours, IX - 24 hours, and X – 48 - 72 hours. The half-lives of proteins C and S are approximately 8 hours and 30 hours, respectively. The resultant in vivo effect is a sequential depression of Factor VII, Protein C, Factor IX, Protein S, and Factor X and II activities. Vitamin K is an essential cofactor for the post ribosomal synthesis of the vitamin K dependent clotting factors. The vitamin promotes the biosynthesis of γ-carboxyglutamic acid residues in the proteins which are essential for biological activity. Warfarin is thought to interfere with clotting factor synthesis by inhibition of the regeneration of vitamin K1 epoxide. The degree of depression is dependent upon the dosage administered.
-The degree of depression is dependent upon the dosage administered. Therapeutic doses of warfarin decrease the total amount of the active form of each vitamin K dependent clotting factor made by the liver by approximately 30% to 50%.An anticoagulation effect generally occurs within 24 hours after drug administration. However, peak anticoagulant effect may be delayed 72 to 96 hours. The duration of action of a single dose of racemic warfarin is 2 to 5 days. The effects of Jantoven® Tablets may become more pronounced as effects of daily maintenance doses overlap. Anticoagulants have no direct effect on an established thrombus, nor do they reverse ischemic tissue damage. However, once a thrombus has occurred, the goal of anticoagulant treatment is to prevent further extension of the formed clot and prevent secondary thromboembolic complications which may result in serious and possibly fatal sequelae.
+Jantoven® Tablets (Warfarin Sodium Tablets, USP) and other coumarin anticoagulants act by inhibiting the synthesis of vitamin K dependent clotting factors, which include Factors II, VII, IX and X, and the anticoagulant proteins C and S. Half-lives of these clotting factors are as follows: Factor II - 60 hours, VII – 4 - 6 hours, IX - 24 hours, and X – 48 - 72 hours. The half-lives of proteins C and S are approximately 8 hours and 30 hours, respectively. The resultant in vivo effect is a sequential depression of Factor VII, Protein C, Factor IX, Protein S, and Factor X and II activities. Vitamin K is an essential cofactor for the post ribosomal synthesis of the vitamin K dependent clotting factors. The vitamin promotes the biosynthesis of γ-carboxyglutamic acid residues in the proteins which are essential for biological activity.
```

#### CLINICAL PHARMACOLOGY > Clinical Trials > Atrial Fibrillation (AF)

```diff
@@ -1,2 +1,2 @@
-In five prospective randomized controlled clinical trials involving 3711 patients with non-rheumatic AF, warfarin significantly reduced the risk of systemic thromboembolism including stroke (See Table 1). The risk reduction ranged from 60% to 86% in all except one trial (CAFA: 45%) which stopped early due to published positive results from two of these trials. The incidence of major bleeding in these trials ranged from 0.6 to 2.7% (See Table 1). Meta-analysis findings of these studies revealed that the effects of warfarin in reducing thromboembolic events including stroke were similar at either moderately high INR (2.0 - 4.5) or low INR (1.4 - 3.0). There was a significant reduction in minor bleeds at the low INR. Similar data from clinical studies in valvular atrial fibrillation patients are not available.Table 1: Clinical Studies Of Warfarin In Non-Rheumatic AF Patients* *All study results of warfarin vs.
+In five prospective randomized controlled clinical trials involving 3711 patients with non-rheumatic AF, warfarin significantly reduced the risk of systemic thromboembolism including stroke (See Table 2). The risk reduction ranged from 60% to 86% in all except one trial (CAFA: 45%) which stopped early due to published positive results from two of these trials. The incidence of major bleeding in these trials ranged from 0.6 to 2.7% (See Table 2). Meta-analysis findings of these studies revealed that the effects of warfarin in reducing thromboembolic events including stroke were similar at either moderately high INR (2.0 - 4.5) or low INR (1.4 - 3.0). There was a significant reduction in minor bleeds at the low INR. Similar data from clinical studies in valvular atrial fibrillation patients are not available.Table 2: Clinical Studies Of Warfarin In Non-Rheumatic AF Patients* *All study results of warfarin vs.
 control are based on intention-to-treat analysis and include ischemic stroke and systemic thromboembolism, excluding hemorrhage and transient ischemic attacks. StudyNPT RatioINRThromboembolism% Major Bleeding Warfarin-Treated PatientsControl Patients% Risk Reductionp-valueWarfarin-Treated PatientsControl Patients AFASAK3353361.5-2.02.8-4.2600.0270.60.0 SPAF2102111.3-1.82.0-4.5670.011.91.9 BAATAF2122081.2-1.51.5-2.786<0.050.90.5 CAFA1871911.3-1.62.0-3.0450.252.70.5 SPINAF2602651.2-1.51.4-2.8790.0012.31.5
```
