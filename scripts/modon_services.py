"""MODON services guide 2025 -> tidy CSV with English names, categories and burden counts.
Usage: python scripts/modon_services.py GUIDE_XLSX data/modon/modon_services_2025.csv"""
import re
import sys

import pandas as pd

EN = [  # (English name, category) in the guide's row order; translations by Claude, check against the Arabic
    ("Attracting private industrial cities and complexes", "Land allocation and development"),
    ("Early booking of units", "Land allocation and development"),
    ("Real estate developers", "Land allocation and development"),
    ("Land allocation for data centres", "Land allocation and development"),
    ("Land allocation for telecom towers", "Land allocation and development"),
    ("Allocation for industrial applications", "Land allocation and development"),
    ("Allocation for service applications", "Land allocation and development"),
    ("Allocation of operating-company contracts", "Land allocation and development"),
    ("Contract renewal", "Contracts"),
    ("Contract data update", "Contracts"),
    ("Modify or add products", "Contracts"),
    ("Merge two or more contracts", "Contracts"),
    ("Split a contract", "Contracts"),
    ("Add partners", "Contracts"),
    ("Transfer of an owner's share or full ownership", "Contracts"),
    ("Name change", "Contracts"),
    ("Change of activity", "Contracts"),
    ("Register a sub-lease contract", "Contracts"),
    ("Entity inside a factory (complementary)", "Contracts"),
    ("Extend a sub-lease contract", "Contracts"),
    ("Land relinquishment by the investor", "Contracts"),
    ("Land withdrawal", "Contracts"),
    ("Notice of non-renewal", "Contracts"),
    ("Refund", "Contracts"),
    ("Reopen a contract", "Contracts"),
    ("Replacement for a lost contract", "Contracts"),
    ("Approval of a new site plan", "Planning and building"),
    ("Approval of a modification or expansion plan", "Planning and building"),
    ("Approval of an as-built plan", "Planning and building"),
    ("Approval of a safety plan", "Planning and building"),
    ("Qualification of engineering offices", "Planning and building"),
    ("Issue or renew a building permit", "Planning and building"),
    ("Amend a building permit", "Planning and building"),
    ("Issue an operating licence", "Operating licences"),
    ("Building completion and occupancy certificate", "Planning and building"),
    ("Issue or renew a group housing licence", "Operating licences"),
    ("Issue or renew a food or commercial establishment licence", "Operating licences"),
    ("Cancel a food or commercial establishment licence", "Operating licences"),
    ("Fence permit", "Site works permits"),
    ("Civil works permit", "Site works permits"),
    ("Gates permit", "Site works permits"),
    ("Excavation and asphalting permit", "Site works permits"),
    ("Demolition and removal", "Site works permits"),
    ("Planting permit", "Site works permits"),
    ("Equipment installation and transport permit", "Site works permits"),
    ("Security and safety installations permit", "Site works permits"),
    ("Mock evacuation drill permit", "Site works permits"),
    ("Evening truck entry permit", "Site works permits"),
    ("Firefighting training inside a factory permit", "Site works permits"),
    ("Telecom tower maintenance permit", "Site works permits"),
    ("Power connection letter", "Utilities"),
    ("Power energisation letter", "Utilities"),
    ("Load increase letter", "Utilities"),
    ("Electricity (under 5 MW)", "Utilities"),
    ("Electricity (over 5 MW)", "Utilities"),
    ("Gas", "Utilities"),
    ("Telecommunications", "Utilities"),
    ("Treated water connection for industrial use", "Utilities"),
    ("Environmental disclosure form assessment", "Environment and health"),
    ("Chemical materials disclosure", "Environment and health"),
    ("Issue or renew a health certificate", "Environment and health"),
    ("Cancel a health certificate", "Environment and health"),
    ("Reopen a food or commercial establishment after closure", "Operating licences"),
    ("Licence to develop a private industrial city or complex", "Land allocation and development"),
    ("Licence to operate a private industrial city or complex", "Land allocation and development"),
    ("Electronic auction", "Land allocation and development"),
    ("National productivity", "Other"),
    ("Billboards", "Other"),
    ("Photography permit", "Other"),
]
LOGISTICS = {"Evening truck entry permit", "Equipment installation and transport permit"}

guide, out = sys.argv[1], sys.argv[2]
d = pd.read_excel(guide, header=None, skiprows=2)
d.columns = ["service_ar", "description_ar", "applicant_type_ar", "applicant_ar", "steps_ar", "documents_ar"]
d = d.dropna(subset=["service_ar"]).reset_index(drop=True)
assert len(d) == len(EN), (len(d), len(EN))
clean = lambda s: re.sub(r"[​\s]+", " ", str(s)).strip() if pd.notna(s) else ""
for c in d.columns:
    d[c] = d[c].map(clean) if c != "steps_ar" and c != "documents_ar" else d[c].fillna("").astype(str)
d.insert(1, "service_en", [e for e, _ in EN])
d.insert(2, "category", [c for _, c in EN])
d["n_steps"] = d.steps_ar.map(lambda s: len(re.findall(r"(?m)^\s*\d+\s*[\.\-)]", s)))
d["n_documents"] = d.documents_ar.map(lambda s: 0 if "لا يوجد" in s or not s.strip() else max(1, s.count("•")))
d["decided_by_city_official"] = d.steps_ar.str.contains("مسئول المدينة الصناعية|مسؤول المدينة الصناعية")
d["logistics_related"] = d.service_en.isin(LOGISTICS)
d["source"] = "MODON services guide 2025 (دليل الخدمات في مدن لعام 2025); English names and categories translated by Claude"
d.to_csv(out, index=False, encoding="utf-8-sig")  # BOM so Excel shows the Arabic correctly

print(f"{len(d)} services -> {out}")
print(d.groupby("category").agg(services=("service_en", "size"), median_steps=("n_steps", "median"),
                                max_steps=("n_steps", "max"), median_docs=("n_documents", "median"),
                                max_docs=("n_documents", "max")).sort_values("services", ascending=False).to_string())
print("\nmost steps + documents:")
d["burden"] = d.n_steps + d.n_documents
print(d.nlargest(6, "burden")[["service_en", "n_steps", "n_documents"]].to_string(index=False))
print("\ndecided by the industrial city official:", int(d.decided_by_city_official.sum()))
print("unparsed steps:", d.loc[d.n_steps == 0, "service_en"].tolist())
