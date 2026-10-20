# STEP 0 AUDIT — Punjab Tenancy Data (per NEXT_PHASE_PLAN Revised)

Date: 2026-10-20. Status: **FAILED — existing raw text is NOT the genuine Act.**

## Hard evidence

1. **Section count mismatch.** Current `data/raw/tenancy_punjab/punjab_rented_premises_act_2009.txt` (11,361 chars) parses into exactly **25 sections** / 27 chunks. The genuine Punjab Act VII of 2009 has **36 sections** plus a Schedule.
2. **Section titles disagree — not just the count.** Verified against full-text mirrors:
   - Real Sec 3 = "Exemption"; current file Sec 3 = "Scope of the Act".
   - Real Sec 15 = "Grounds for eviction"; current file Sec 15 = "Application for eviction".
   - Real Sec 13 = "Obligations of tenant"; current file Sec 13 = "Prohibition of certain acts by landlord".
   - "Determination of fair rent" and "Revision of fair rent" (current Secs 11–12) are not section titles in the genuine Act; real "Appeal" is Sec 28 (not 18); real last section is 36 "Repeal and validation" (current ends at 25).
   - Real chapters: five (I Preliminary, II Creation of Tenancy, III Obligations of the Parties and Grounds for Eviction, IV Establishment of Rent Tribunal and Procedure, V Miscellaneous). Current file uses different chapter structure.

## Conclusion (Rule 3 of the revised plan)

The file is an abridged/reconstructed (very likely model-written or third-party paraphrased) text, not a transcription of the official Act. **It must be replaced before any indexing or benchmark verification.** All 10 existing benchmark questions cite section numbers from the fake text (15, 6 & 10, 6, 5, 13) and are all treated as currently unverified.

## Where the real text comes from

- Official: https://punjabcode.punjab.gov.pk/uploads/articles/THE_PUNJAB_RENTED_PREMISES_ACT_2009.doc.pdf (fetch from here failed with a 500 error at audit time — retry manually).
- Cross-check mirrors (verified readable): http://nasirlawsite.com/laws/rent2009.htm and http://pljlawsite.com/Statuteview.asp?ID=7361 (full 1–36 title index).

## Owner actions (blocking)

1. Download the official PDF into `data\source_pdfs\tenancy_punjab\`.
2. Extract to `data\raw\tenancy_punjab\punjab_rented_premises_act_2009.txt` (ask the model to run extraction — the model never retypes or reconstructs law text).
3. Ask the model to re-run parser validation and compare against this audit.

## Genuine section list (for the owner's comparison)

1. Short title, extent and commencement — 2. Definitions — 3. Exemption — 4. Act to override other laws — 5. Agreement between landlord and tenant — 6. Contents of tenancy agreement — 7. Payment of rent — 8. Existing tenancy — 9. Effect of non-compliance — 10. Effect of other agreement — 11. Subletting — 12. Obligations of landlord — 13. Obligations of tenant — 14. Reimbursement of expenses — 15. Grounds for eviction — 16. Establishment of Rent Tribunal — 17. Rent Registrar — 18. Staff and establishment — 19. Filing of application — 20. Application for deposit of rent — 21. Appearance of parties and consequences of non-appearance — 22. Leave to contest — 23. Written reply — 24. Payment of rent and other dues pending proceedings — 25. Recording of evidence — 26. Rent Tribunal to exercise powers of Civil Court — 27. Period for disposal of application — 28. Appeal — 29. General power of transfer — 30. Transfer of ownership — 31. Execution of orders — 32. Indemnity — 33. Power to make rules — 34. Provisions of Qanun-e-Shahadat Order and CPC not to apply — 35. Repeal and savings — 36. Repeal and validation.
