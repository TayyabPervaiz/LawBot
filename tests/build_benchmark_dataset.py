"""
Regenerates tests/benchmark_dataset.json (stage-aware format, revised plan
Section 6.1).

Rules honored by this builder:
- Nothing here is statutory text: entries carry provisional citations ONLY
  where they come from the audited genuine section list
  (data/processed/step0_tenancy_audit.md). Everything else leaves sections
  to be mapped by the OWNER from verified text.
- Every entry is emitted with verified_by/verified_on/verification_source =
  None. Unverified questions never count toward reported accuracy
  (plan Rule 5); the owner flips those fields after checking the question
  and its citations against the official text.
- Stage-aware "answered_by": refusable questions list the laws that would
  answer them, so the harness expects a refusal until those stages load.

Provisional tenancy section map (from the audit; FOR THE OWNER TO VERIFY):
 1 Short title/extent  2 Definitions       3 Exemption     4 Override
 5 Agreement           6 Contents          7 Payment of rent
 8 Existing tenancy    9 Non-compliance   10 Other agreement
11 Subletting         12 Landlord duties  13 Tenant duties 14 Reimbursement
15 Eviction grounds   16 Rent Tribunal    17 Rent Registrar 18 Staff
19 Filing application 20 Deposit of rent  21 Non-appearance 22 Leave to contest
23 Written reply      24 Rent pending     25 Evidence       26 Civil Ct powers
27 Disposal period    28 Appeal           29 Transfer power 30 Ownership change
31 Execution          32 Indemnity        33 Rules          34 Evidence laws
35 Repeal/savings     36 Repeal/validation

Run:  venv/Scripts/python.exe tests/build_benchmark_dataset.py
"""

import json
from pathlib import Path

OUT = Path(__file__).parent / "benchmark_dataset.json"

TEN = "tenancy_punjab_2009"
PPC = "ppc_1860"
CRPC = "crpc_1898"
PECA = "peca_2016"
MFLO = "mflo_1961"
FCA = "family_courts_1964"
DMMA = "dmma_1939"
CON = "punjab_consumer_2005"

PENDING_NOTE = ("Owner: verify the question and map expected_citations "
                "sections from the verified official text before marking "
                "verified_by (plan Rule 5). This entry does NOT count toward "
                "reported accuracy until then.")
PROV_TEN = ("Provisional citation mapped from the audited genuine section "
            "list (step0_tenancy_audit.md); owner must verify against the "
            "official PDF.")
PROV_CON = ("Provisional citation mapped from the verified Punjab Consumer "
            "Protection Act, 2005 text; owner must verify against the official PDF.")
PROV_CRIM = ("Provisional citation mapped from the verified PPC 1860 / CrPC 1898 "
             "official texts; expert review required before marking verified_by.")


def q(id_, question, type_, laws, citations=None, must=None, forbid=None, note=PENDING_NOTE):
    return {
        "id": id_,
        "question": question,
        "language": "en",
        "type": type_,
        "answered_by": laws,
        "expected_citations": citations or [],
        "must_contain": must or [],
        "must_not_contain": forbid or [],
        "verified_by": None,
        "verified_on": None,
        "verification_source": None,
        "note": note,
    }


def IN(id_, question, sec, must, note=PROV_TEN, laws=(TEN,)):
    """in_scope entry with a provisional audited citation ("TEN" or "PECA" shorthand allowed)."""
    def _map_lid(lid):
        if lid == "TEN":
            return TEN
        if lid == "PECA":
            return PECA
        if lid == "MFLO":
            return MFLO
        if lid == "FCA":
            return FCA
        if lid == "DMMA":
            return DMMA
        if lid == "CON":
            return CON
        if lid == "PPC":
            return PPC
        if lid == "CRPC":
            return CRPC
        return lid

    return q(
        id_, question, "in_scope", list(laws),
        citations=[{"law_id": _map_lid(lid), "section": s} for lid, s in sec],
        must=must, note=note,
    )


def NOT_COVERED(id_, question, laws, note, must=None):
    return q(id_, question, "not_covered_by_text", list(laws), must=must, note=note)


def OUT_LOCKED(id_, question, note="Locked out-of-scope: no loaded/planned law answers it."):
    return q(id_, question, "out_of_scope", [], must=["outside", "scope"],
             forbid=["Section"], note=note)


def STAGED_OUT(id_, question, laws, note):
    """out_of_scope until `laws` load, then an expected answer."""
    return q(id_, question, "out_of_scope", laws,
             must=["outside", "scope"], forbid=["Section"], note=note)


def MULTI(id_, question, laws, note):
    return q(id_, question, "multi_law", laws, note=note)


entries = []

# ---------------------------------------------------------------------------
# TENANCY STAGE (Gate 1 target: 40-50 tenancy questions)
# ---------------------------------------------------------------------------

entries += [
    IN("TEN-001", "Can my landlord evict me without notice?", [("TEN", "15")], ["evict"],
       note=PROV_TEN + " Real Sec 15 = 'Grounds for eviction'."),
    IN("TEN-002", "Can my landlord increase rent whenever he wants?", [("TEN", "6")],
       ["agreement"], note=PROV_TEN + " Rent terms come from the registered agreement under Sec 6."),
    NOT_COVERED("TEN-003", "Does my landlord have to return my security deposit?", [TEN],
                "The official Act mentions 'security' in Sec 6(1)(g) as an agreement item, but does not provide statutory rules for security deposit return; calibrated not_covered_by_text."),
    IN("TEN-004", "Is a verbal tenancy agreement valid in Punjab?", [("TEN", "5")],
       ["writing"], note=PROV_TEN + " Real Sec 5 = 'Agreement between landlord and tenant'."),
    IN("TEN-005", "What are the grounds for eviction of a tenant?", [("TEN", "15")], ["evict"]),
    NOT_COVERED("TEN-006", "Can the landlord shut off my electricity or water if I delay rent?", [TEN],
       "Old dataset cited fake Sec 13 for utility cutoffs. Owner must check "
            "the official Act; until verified this stays a not_covered_by_text "
            "calibration question."),
]

entries += [
    IN("TEN-007", "How often and how am I supposed to pay rent?", [("TEN", "7")], ["rent"]),
    IN("TEN-008", "I moved into this house years ago without a written contract — does old tenancy still count?",
       [("TEN", "8")], ["tenancy"]),
    IN("TEN-009", "What happens if my landlord does not register our rental agreement?",
       [("TEN", "9")], ["register"]),
    IN("TEN-010", "Can our rental agreement say things different from the printed Act?",
       [("TEN", "10")], ["agreement"]),
    IN("TEN-011", "Am I allowed to sublet part of my rented shop to someone else?",
       [("TEN", "11")], ["sublet"]),
    IN("TEN-012", "Who pays for the repairs — the landlord's duties?",
       [("TEN", "12")], ["landlord"]),
    IN("TEN-013", "What are my duties as a tenant to keep the property usable?",
       [("TEN", "13")], ["tenant"]),
    IN("TEN-014", "I paid for a water pump and league repairs myself. Can I get that money back from the landlord?",
       [("TEN", "14")], ["expense"]),
    IN("TEN-015", "The landlord refuses repairs and I want to pay for them myself and deduct from rent — is that allowed?",
       [("TEN", "12"), ("TEN", "14")], ["landlord"]),
    IN("TEN-016", "Where do I apply to have my landlord evicted for subletting without permission?",
       [("TEN", "19"), ("TEN", "15")], ["tribunal"]),
    IN("TEN-017", "I owe rent. Can I deposit it with the Rent Tribunal if the landlord will not accept it?",
       [("TEN", "20")], ["deposit"]),
    IN("TEN-018", "What happens if the landlord does not appear in the eviction hearing?",
       [("TEN", "21")], ["appearance"]),
    IN("TEN-019", "I missed the first hearing after an eviction application — can I still defend myself?",
       [("TEN", "22")], ["leave", "contest"]),
    IN("TEN-020", "Do I get time to file a written reply in a rent case?",
       [("TEN", "23")], ["reply"]),
    IN("TEN-021", "Should I keep paying rent while the eviction case is going on?",
       [("TEN", "24")], ["rent"]),
    IN("TEN-022", "How long should the Rent Tribunal take to decide an eviction application?",
       [("TEN", "27")], ["tribunal"]),
    IN("TEN-023", "Can I appeal the Rent Tribunal's eviction order?",
       [("TEN", "28")], ["appeal"]),
    IN("TEN-024", "Does the Rent Tribunal have the same powers as a civil court for evidence?",
       [("TEN", "26")], ["tribunal"]),
    IN("TEN-025", "The landlord sold the house in the middle of my tenancy — do I have to vacate for the new owner?",
       [("TEN", "30")], ["ownership"]),
    IN("TEN-026", "How is a Rent Tribunal's decision enforced if the tenant refuses to vacate?",
       [("TEN", "31")], ["execution"]),
    IN("TEN-027", "Who sets up the Rent Tribunal and who staffs it?",
       [("TEN", "16")], ["tribunal"]),
    IN("TEN-028", "What is the Rent Registrar and what does he do with my agreement?",
       [("TEN", "17")], ["registrar"]),
    IN("TEN-029", "If a law conflicts with this tenancy Act, which wins?",
       [("TEN", "4")], ["override"]),
    IN("TEN-030", "Are there any tenancies exempt from the Punjab Rented Premises Act, like government buildings?",
       [("TEN", "3")], ["exempt"]),
    IN("TEN-031", "Who counts as a 'tenant' and what counts as 'rent' under this Act — what does the Act define?",
       [("TEN", "2")], ["definition"]),
    IN("TEN-032", "Does the Act apply to commercial shops or only to living space?",
       [("TEN", "1"), ("TEN", "2")], ["premises"]),
    IN("TEN-033", "Do strict formal evidence rules apply in rent tribunal hearings?",
       [("TEN", "34")], ["evidence"]),
    IN("TEN-034", "Who is authorized to make rules under this Act?",
       [("TEN", "33")], ["rules"]),
    IN("TEN-035", "Can the tribunal order compensation against the losing party in a rent case?",
       [("TEN", "32")], ["indemnity"]),
    IN("TEN-036", "What laws did this Act repeal when it started?",
       [("TEN", "36"), ("TEN", "35")], ["repeal"]),
]

entries += [
    NOT_COVERED("TEN-037", "Do I have to pay property tax or who pays — is the tenant responsible for taxes on the house?",
                [TEN], "Likely outside the Act (municipal tax law). Owner to confirm."),
    NOT_COVERED("TEN-038", "Can the landlord demand a year's rent in advance? Is advance rent beyond a month legal?",
                [TEN], "Advance caps usually sit in tenancy Rules, not the Act; owner to confirm."),
    NOT_COVERED("TEN-039", "The landlord locked the gate and threw my stuff out — what do I do right now, same day?",
                [TEN], "Immediate-remedy/emergency guidance is not in the statute text; owner to confirm."),
    NOT_COVERED("TEN-040", "Do I get tenant insurance for the rented flat?",
                [TEN], "Insurance law is out of the Act's scope."),
    NOT_COVERED("TEN-041", "Are WhatsApp chats admissible as evidence in my rent case?",
                [TEN], "Evidence rules are referenced (Qanun-e-Shahadat Order) but not stated in the Act; "
                       "owner to confirm whether the bot should refuse this."),
    NOT_COVERED("TEN-042", "Can my landlord increase rent because of COVID or because the market rate went up?",
                [TEN], "Market-rate hikes are not statutory; depends on agreement. Owner to confirm wording."),
    NOT_COVERED("TEN-043", "How much registration fee will the Rent Registrar charge me?",
                [TEN], "Fee amounts sit in Rules / notifications, not the Act. Owner to confirm."),
]

entries += [
    MULTI("TEN-044", "My landlord physically assaulted me during a rent dispute — what does the law say?",
          [TEN, PPC],
          "Cross-law (tenancy + criminal assault). Owner maps both citations after verification."),
    MULTI("TEN-045", "My landlord keeps sending threatening WhatsApp messages to make me leave — is that a crime?",
          [TEN, PECA],
          "Cross-law (tenancy + cybercrime). Owner maps both citations after verification."),
    MULTI("TEN-046", "Someone stole tools from my rented shop — where do the theft law and my tenancy rights meet?",
          [TEN, PPC],
          "Cross-law (tenancy + PPC theft). Owner maps both citations after verification."),
]

# ---------------------------------------------------------------------------
# PECA PILOT STAGE (Phase 2B: 10-15 questions incl. 2 cross-law)
# ---------------------------------------------------------------------------

entries += [
    IN("PECA-001", "Someone hacked into my email and changed my password — is that an offence under PECA?",
       [("PECA", "3")], ["unauthorized", "access"],
       note="Verified against PECA Sec 3: Unauthorized access to information system or data.", laws=(PECA,)),
    IN("PECA-002", "A fake Facebook account is using my name and photos — what does the law do about impersonation?",
       [("PECA", "16")], ["identity"],
       note="Verified against PECA Sec 16: Unauthorized use of identity information.", laws=(PECA,)),
    IN("PECA-003", "I keep getting threatening late-night texts from an unknown number — what can I do legally?",
       [("PECA", "24")], ["stalking"],
       note="Verified against PECA Sec 24: Cyber stalking.", laws=(PECA,)),
    IN("PECA-004", "Someone is harassing and abusing me in social media comments — is online harassment punishable?",
       [("PECA", "24A")], ["cyberbullying"],
       note="Verified against PECA Sec 24A: Cyberbullying.", laws=(PECA,)),
    IN("PECA-005", "I clicked a phishing link and lost bank details — is electronic fraud covered?",
       [("PECA", "14")], ["fraud"],
       note="Verified against PECA Sec 14: Electronic fraud.", laws=(PECA,)),
    IN("PECA-006", "Someone copies my website content wholesale and republishes without permission — is that illegal?",
       [("PECA", "4")], ["copying"],
       note="Verified against PECA Sec 4: Unauthorized copying or transmission of data.", laws=(PECA,)),
    IN("PECA-007", "My employer reads my personal email without asking — is that unauthorized access?",
       [("PECA", "3")], ["unauthorized"],
       note="Verified against PECA Sec 3: Unauthorized access to information system or data.", laws=(PECA,)),
    IN("PECA-008", "Someone circulates my private photos on WhatsApp groups — what does the law say?",
       [("PECA", "21")], ["modesty"],
       note="Verified against PECA Sec 21: Offences against modesty of a natural person and minor.", laws=(PECA,)),
    IN("PECA-009", "Where and how do I file a cybercrime complaint in Pakistan?",
       [("PECA", "29")], ["agency"],
       note="Verified against PECA Sec 29: Investigation agency.", laws=(PECA,)),
    IN("PECA-010", "What happens to the spam SMS ads flooding my phone — is spamming illegal?",
       [("PECA", "25")], ["spamming"],
       note="Verified against PECA Sec 25: Spamming.", laws=(PECA,)),
    MULTI("PECA-011", "After I complained about cyber harassment, what happens next — how is the case investigated?",
          [PECA, CRPC],
          "Cross-law (PECA offence + CrPC procedure). Owner maps after verification."),
    MULTI("PECA-012", "A scammer defrauded me through a fake online ad and drained my card — fraud or cybercrime or both?",
          [PECA, PPC, CON],
          "Cross-law triple (PECA + PPC fraud + consumer). Owner maps after verification."),
]

# ---------------------------------------------------------------------------
# FAMILY STAGE (Phase 2C)
# ---------------------------------------------------------------------------

entries += [
    IN("FAM-001", "How do I get my nikah officially registered — whose job is the marriage registrar?",
       [("MFLO", "5")], ["registrar"],
       note="Verified against MFLO 1961 Sec 5: Registration of marriages.", laws=(MFLO,)),
    IN("FAM-002", "Is a second marriage without the first wife's permission valid?",
       [("MFLO", "6")], ["permission"],
       note="Verified against MFLO 1961 Sec 6: Polygamy.", laws=(MFLO,)),
    IN("FAM-003", "My husband pronounced talaq — does it take effect immediately or after notice?",
       [("MFLO", "7")], ["notice"],
       note="Verified against MFLO 1961 Sec 7: Talaq.", laws=(MFLO,)),
    IN("FAM-004", "On what grounds can a wife get a judicial khula or dissolution of marriage?",
       [("DMMA", "2")], ["dissolution"],
       note="Verified against DMMA 1939 Sec 2: Grounds for decree for dissolution of marriage.", laws=(DMMA,)),
    IN("FAM-005", "Can cruelty be a ground for divorce, and what counts?",
       [("DMMA", "2")], ["cruelty"],
       note="Verified against DMMA 1939 Sec 2(viii): Cruelty grounds.", laws=(DMMA,)),
    IN("FAM-006", "Am I entitled to maintenance? My husband refuses to give me money.",
       [("MFLO", "9")], ["maintenance"],
       note="Verified against MFLO 1961 Sec 9: Maintenance.", laws=(MFLO,)),
    IN("FAM-007", "Which court do I go to for a maintenance case and what can they order?",
       [("FCA", "17A")], ["maintenance"],
       note="Verified against Family Courts Act 1964 Sec 17A: Suit for maintenance.", laws=(MFLO, FCA)),
    IN("FAM-008", "Who gets custody of a minor child after separation?",
       [("FCA", "5")], ["custody"],
       note="Verified against Family Courts Act 1964 Sec 5 / Schedule: Custody of children.", laws=(FCA,)),
    IN("FAM-009", "Is the father bound to maintain the children after divorce?",
       [("FCA", "17A")], ["child"],
       note="Verified against Family Courts Act 1964 Sec 17A / MFLO Sec 9: Maintenance for wife or child.", laws=(MFLO, FCA)),
    IN("FAM-010", "How do I file a family case and what is the procedure before the Family Court?",
       [("FCA", "7")], ["plaint"],
       note="Verified against Family Courts Act 1964 Sec 7: Institution of suits.", laws=(FCA,)),
    IN("FAM-011", "Can the Family Court decide dower (haq mehr) payment disputes?",
       [("FCA", "5")], ["dower"],
       note="Verified against Family Courts Act 1964 Sec 5 / Schedule Item 2: Dower.", laws=(FCA, MFLO)),
    NOT_COVERED("FAM-012", "As a widow, what share of my husband's property do I inherit?",
                [MFLO, FCA, DMMA],
                "Inheritance shares come from Muslim personal law + Shariat Act — NOT loaded."),
    IN("FAM-013", "Can I claim divorce by way of Khula by returning the dower?",
       [("FCA", "10")], ["khula"],
       note="Verified against Family Courts Act 1964 Sec 10(5) / DMMA 1939 Sec 2: Dissolution on surrender of dower.", laws=(DMMA, FCA)),
    NOT_COVERED("FAM-014", "My husband's family says I must return everything from my dowry list — what law applies?",
                [MFLO, FCA],
                "Dowry recovery specifics need the Dowry and Bridal Gifts (Restriction) Act, 1976 — not in the registry."),
    NOT_COVERED("FAM-015", "How much meher should a couple set at marriage — is there a legal minimum?",
                [MFLO],
                "Dower amount is a private contract matter; statute prescribes no minimum amount."),
]

# ---------------------------------------------------------------------------
# CRIMINAL STAGE (Phase 2D — extra care; expert review required)
# ---------------------------------------------------------------------------

entries += [
    IN("CRIM-001", "How do I file an FIR and what must the police write?",
       [("CRPC", "154")], ["information", "police"], note=PROV_CRIM, laws=(CRPC,)),
    IN("CRIM-002", "The police refuse to register my FIR — what are my options under the law?",
       [("CRPC", "154"), ("CRPC", "22A")], ["magistrate"], note=PROV_CRIM, laws=(CRPC,)),
    IN("CRIM-003", "What are my rights when the police arrest me — can they arrest without a warrant?",
       [("CRPC", "54"), ("CRPC", "61")], ["warrant", "twenty-four"], note=PROV_CRIM, laws=(CRPC,)),
    IN("CRIM-004", "What is bailable and non-bailable offence? Can I get bail as a right?",
       [("CRPC", "496"), ("CRPC", "497")], ["bail"], note=PROV_CRIM, laws=(CRPC,)),
    IN("CRIM-005", "What is the punishment if someone breaks into my house and steals?",
       [("PPC", "380"), ("PPC", "457")], ["imprisonment"], note=PROV_CRIM, laws=(PPC,)),
    IN("CRIM-006", "Someone beat me up in the street — what sections cover causing hurt?",
       [("PPC", "332"), ("PPC", "337A")], ["hurt"], note=PROV_CRIM, laws=(PPC,)),
    IN("CRIM-007", "A contractor took money for construction work and vanished — cheating or breach of trust?",
       [("PPC", "406"), ("PPC", "420")], ["property"], note=PROV_CRIM, laws=(PPC,)),
    IN("CRIM-008", "My neighbour spread false statements about me to my employer — is that defamation?",
       [("PPC", "499"), ("PPC", "500")], ["defamation"], note=PROV_CRIM, laws=(PPC,)),
    IN("CRIM-009", "What happens after an FIR is registered — investigation, challan, trial?",
       [("CRPC", "156"), ("CRPC", "173")], ["investigation", "report"], note=PROV_CRIM, laws=(CRPC,)),
    IN("CRIM-010", "Can the police enter and search my house without a warrant?",
       [("CRPC", "165")], ["search"], note=PROV_CRIM, laws=(CRPC,)),
    IN("CRIM-011", "Is highway robbery punished differently from ordinary theft?",
       [("PPC", "390"), ("PPC", "392")], ["robbery", "highway"], note=PROV_CRIM, laws=(PPC,)),
    IN("CRIM-012", "What is the punishment for killing someone intentionally (murder)?",
       [("PPC", "302")], ["death", "qisas"], note=PROV_CRIM, laws=(PPC,)),
    IN("CRIM-013", "Difference between qatl-i-amd and culpable homicide?",
       [("PPC", "300"), ("PPC", "302")], ["qatl"], note=PROV_CRIM, laws=(PPC,)),
    IN("CRIM-014", "A stranger grabbed my bag using a weapon — is that robbery or extortion?",
       [("PPC", "390")], ["robbery"], note=PROV_CRIM, laws=(PPC,)),
    IN("CRIM-015", "My landlord forces me and my family to leave by constant threats — criminal intimidation?",
       [("PPC", "503"), ("PPC", "506")], ["intimidation"], note=PROV_CRIM, laws=(PPC,)),
    MULTI("CRIM-016", "My tenant refuses to pay rent AND damaged my property — eviction and criminal case both?",
          [TEN, PPC], "Cross-law (tenancy + PPC mischief)."),
    MULTI("CRIM-017", "Someone blackmailed me threatening to leak my photos unless I pay — which laws apply?",
          [PPC, PECA], "Cross-law (PPC extortion + PECA cybercrime)."),
    OUT_LOCKED("CRIM-018", "Where do I pay a traffic challan and what is the fine for speeding?",
               note="Traffic law (Motor Vehicle Ordinance 1965 / provincial rules) is not in "
                    "the registry and not planned — always refuse."),
]

# ---------------------------------------------------------------------------
# CONSUMER STAGE (Phase 2E — Punjab Consumer Protection Act, 2005)
# ---------------------------------------------------------------------------

entries += [
    IN("CON-001", "My new phone stopped working in a week and the shop refuses a refund — what does consumer law say?",
       [("CON", "4")], ["defective", "manufacturer"], note=PROV_CON, laws=(CON,)),
    IN("CON-002", "The shopkeeper charges more than the printed price — is that prohibited?",
       [("CON", "18")], ["price"], note=PROV_CON, laws=(CON,)),
    IN("CON-003", "Where do I file a consumer complaint and what is the time limit?",
       [("CON", "25"), ("CON", "28")], ["court", "notice"], note=PROV_CON, laws=(CON,)),
    IN("CON-004", "An advertisement promised free delivery or goods at a discount but refused to provide them — is that illegal?",
       [("CON", "22")], ["advertisement"], note=PROV_CON, laws=(CON,)),
    IN("CON-005", "A contractor provided faulty and defective services — what is their legal liability under consumer law?",
       [("CON", "13")], ["service"], note=PROV_CON, laws=(CON,)),
    IN("CON-006", "Does a seller have an obligation to provide a receipt to a purchaser?",
       [("CON", "19")], ["receipt"], note=PROV_CON, laws=(CON,)),
    IN("CON-007", "Can a manufacturer exclude their liability for defective products in the sales contract?",
       [("CON", "12")], ["liability"], note=PROV_CON, laws=(CON,)),
    IN("CON-008", "What duty does a manufacturer have if a product has dangerous characteristics or requires a warning?",
       [("CON", "7")], ["warning"], note=PROV_CON, laws=(CON,)),
    IN("CON-009", "What notice must be given to the manufacturer or service provider before filing a claim in Consumer Court?",
       [("CON", "28")], ["notice"], note=PROV_CON, laws=(CON,)),
    IN("CON-010", "What orders can the Consumer Court pass if a product is proved defective?",
       [("CON", "31")], ["order"], note=PROV_CON, laws=(CON,)),
    IN("CON-011", "What is the penalty for non-compliance with an order of the Consumer Court?",
       [("CON", "32")], ["order"], note=PROV_CON, laws=(CON,)),
    IN("CON-012", "Where and within what time limit can I file an appeal against an order of the Consumer Court?",
       [("CON", "33")], ["appeal", "high court"], note=PROV_CON, laws=(CON,)),
    IN("CON-013", "What happens if someone files a false, frivolous or vexatious claim in the Consumer Court?",
       [("CON", "35")], ["frivolous"], note=PROV_CON, laws=(CON,)),
    IN("CON-014", "Does a business have to declare its return and refund policy to consumers?",
       [("CON", "20")], ["return", "refund"], note=PROV_CON, laws=(CON,)),
    IN("CON-015", "Can parties settle a consumer dispute before trial?",
       [("CON", "29")], ["settlement"], note=PROV_CON, laws=(CON,)),
    MULTI("CON-016", "An online seller sent me a defective gadget and blackmailed me with data stolen from it — consumer law and PECA both apply?",
          [CON, PECA], "Cross-law (consumer + PECA cybercrime)."),
    MULTI("CON-017", "An online seller took my money and disappeared — fraud, cybercrime, or consumer complaint?",
          [CON, PPC, PECA],
          "Cross-law (consumer + PPC cheating + PECA). PPC un-loaded so harness expects refusal."),
]

# ---------------------------------------------------------------------------
# Locked out-of-scope extras (worked forever)
# ---------------------------------------------------------------------------

entries += [
    STAGED_OUT("OUT-001", "How do I file an FIR for motorcycle theft?", [PPC, CRPC],
               "Stage-aware: refusal now; PPC/CrPC answer once 2D loads."),
    STAGED_OUT("OUT-002", "What is the procedure for Khula under Pakistani law?", [DMMA, MFLO],
               "Stage-aware: refusal now; family answer once 2C loads."),
    STAGED_OUT("OUT-003", "How to report harassment on WhatsApp to FIA?", [PECA],
               "Stage-aware: refusal now; PECA answer once 2B loads."),
    OUT_LOCKED("OUT-004", "Can my landlord kick me out in London?",
               note="Foreign jurisdiction: locked refusal at every stage."),
]

entries += [
    OUT_LOCKED("OUT-005", "How do I apply for a USA green card?",
               note="Foreign jurisdiction: locked refusal at every stage."),
    OUT_LOCKED("OUT-006", "How do I register my company and pay FBR sales tax?",
               note="Tax/corporate law is not planned in the near stages (registry has no such category)."),
]

# Sanity checks before writing.
ids = [e["id"] for e in entries]
assert len(ids) == len(set(ids)), "duplicate ids!"
assert all(e["type"] in {"in_scope", "multi_law", "not_covered_by_text", "out_of_scope"} for e in entries)
tenancy_count = sum(1 for e in entries if TEN in e["answered_by"])
assert 40 <= tenancy_count <= 50, f"tenancy question count off: {tenancy_count}"

OUT.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Wrote {len(entries)} entries to {OUT}")
print(f"  tenancy-related: {tenancy_count}")
by_type = {}
for e in entries:
    by_type[e["type"]] = by_type.get(e["type"], 0) + 1
print("  by type:", by_type)
