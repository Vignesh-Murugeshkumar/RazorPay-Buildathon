# SentinelDispute — 5-Minute Pitch & Video Script
### *Track: Razorpay AI Risk Manager*
**Theme:** Evidence-Grounded Dispute Defense & Adversarial Investigation  
**Core Pipeline:** $\text{Evidence} \to \text{Claim} \to \text{Challenge} \to \text{Verification} \to \text{Policy} \to \text{Decision} \to \text{Provenance}$

---

## 🏛️ Visual Slide / Screen 1: The Architecture Diagram
*(Keep this diagram displayed during the first 60 seconds of your video or presentation slide deck)*

```mermaid
flowchart TD
    RZP[Razorpay Webhook Ingress] -->|HMAC-SHA256 + Replay Nonce| EE[1. Canonical Evidence Engine EV-001..EV-007]
    
    subgraph S1["1. Evidence Ingestion & Hashing"]
        EE -->|Canonical Extraction & SHA-256 Digest| ITEMS[Immutable Evidence Items]
    end
    
    subgraph S2["2. Investigation & Adversarial Reasoning Layer"]
        ITEMS --> INV[AI Investigator: Candidate Claims CLM-xxx]
        KB[(Local Scheme KB)] -->|Deterministic Extraction| INV
        INV --> CHAL[🥊 Claim Challenger: Disproving Analysis & Counter-Evidence Search]
    end
    
    subgraph S3["3. Independent Verification & Policy Engine"]
        CHAL --> VERIF[🛡️ Independent Verifier: Grounding Ratio & Contradiction Veto]
        ITEMS -.->|Grounding Truth| VERIF
        VERIF --> POL[Deterministic Policy Engine: Visa CE 3.0 / MC FPT / RuPay]
        POL --> EV[Expected Value Engine E[V]]
        EV --> GATE[Deterministic Safety Gate]
    end
    
    GATE -->|Verified, Compliant, E[V] > 0| AUTO[AUTO_DISPATCHED]
    GATE -->|Gaps, Contradictions, or Overturned Claims| HITL[ROUTE_TO_HITL_QUEUE]
    GATE -->|Negative E[V], Unprovable, or Missing Evidence| ACCEPT[AUTO_ACCEPT_OR_REFUND]
    
    AUTO --> PROV[(6-Tier Provenance DAG & Tamper-Evident SHA-256 Ledger)]
    HITL --> PROV
    ACCEPT --> PROV

    style S2 fill:#0f172a,stroke:#38bdf8,stroke-width:2px
    style S3 fill:#0f172a,stroke:#10b981,stroke-width:2px
    style CHAL fill:#701a75,stroke:#c084fc,stroke-width:2px
    style VERIF fill:#064e3b,stroke:#34d399,stroke-width:2px
    style GATE fill:#78350f,stroke:#fbbf24,stroke-width:2px
```

---

## ⏱️ Video Timestamp Breakdown (5:00 Total)

| Timestamp | Segment | Visual On Screen | Key Takeaway |
| :--- | :--- | :--- | :--- |
| **0:00 – 0:45** | **The Problem & Fatal AI Mistake** | Architecture Slide / Dashboard Hero | Why LLMs cannot have direct financial authority |
| **0:45 – 1:45** | **Hero Demo: Challenger Disproves AI Claim** | Click `🥊 Hero Demo` button & Modal | AI overturned by counter-evidence |
| **1:45 – 2:45** | **Independent Verification & Decision Explainer** | Modal Reasoning Chain & 7-part explainer | Auditable, deterministic, multi-phase logic |
| **2:45 – 3:45** | **Automated Defense & Provenance Graph** | `Visa 10.4` simulation + 6-tier DAG | Zero hallucinations; full cryptographic audit trail |
| **3:45 – 4:30** | **Expected Value & Economic Protection** | Negative E[V] simulation | Protects merchant from ₹1,500 bank fees |
| **4:30 – 5:00** | **Live 115-Scenario Benchmark & Ledger** | Click `⚡ Benchmark` + Verify Ledger | 100% Precision, 0 False Positives, intact ledger |

---

# 🎙️ Complete Video Pitch Script

---

### ⏱️ [0:00 – 0:45] The Problem & The Trust Boundary
**Visual on Screen:**  
Start on the Architecture Slide (or full dashboard view at `http://localhost:8000/`). Point to the top header badges: `SHA-256 Ledger: Verified` and `Deterministic State Engine`.

**Speaker:**
> *"Good morning, judges. When merchants sell online, cardholder disputes and chargebacks bleed billions in margins.
>
> Most people entering an AI buildathon make a fatal engineering mistake: they hook an LLM up to a payment API and let the model directly decide whether to dispute or refund. But here is the reality of financial risk: if an LLM hallucinates a tracking number, claims a delivery that never happened, or files an unprovable dispute, the merchant loses both the item and pays an automatic, non-refundable **₹1,500 bank arbitration fee**—or up to **₹45,000 in pre-arbitration penalties**.
>
> That is why we built **SentinelDispute**. SentinelDispute is not a chatbot. It is an **Evidence-Grounded AI Risk Investigation Engine** where:
> **AI is strictly advisory, and deterministic policy holds all financial authority.**
>
> The pipeline follows a strict, defensible 7-stage invariant:  
> **Evidence $\to$ Claim $\to$ Challenge $\to$ Verification $\to$ Policy $\to$ Decision $\to$ Provenance.**
> Let's see this in action."*

---

### ⏱️ [0:45 – 1:45] The Hero Demo: The AI Changes Its Mind (Adversarial Challenger)
**Visual on Screen:**  
Move to the dashboard. Click the purple button: **`🥊 Hero Demo: Challenger Disproves Claim`**.  
The table updates immediately. Click the **`Inspect`** button next to the new dispute `disp_hero_challenger_...`.

**Speaker:**
> *"Any system can claim an LLM found fraud. What makes a true risk engine is its ability to disprove itself.
>
> Watch this scenario: an incoming dispute for ₹8,500 arrives with two valid past transactions and confirmed carrier tracking. 
>
> In a naive LLM system, the model would immediately draft an auto-representment letter saying: 'Customer has two prior orders and tracking shows delivered.'
>
> But look at our investigation chain:
> First, the **AI Investigator** formulated candidate claim `[CLM-001]`: *'Physical delivery verified by carrier tracking.'*
> 
> But then, our **Adversarial Claim Challenger** ran a disproving query: *'What evidence makes this claim false?'*
> 
> It checked courier GPS coordinates against the shipping address and discovered: **the delivery occurred 150 meters outside the customer's delivery perimeter.**
> 
> The Challenger flagged `CONF-003` with 85% disproof strength and marked: **`CLAIM OVERTURNED`**.
> 
> The **Deterministic Verifier** immediately downgraded the claim's verified confidence to **0%**, and the **Deterministic Policy Engine** vetoed autonomous dispatch, safely routing the case to the Human-in-the-Loop review queue. 
> 
> The AI literally changed its conclusion because the challenger found contradictory evidence."*

---

### ⏱️ [1:45 – 2:45] The 7-Part Decision Explainer & Independent Verification
**Visual on Screen:**  
Scroll down inside the modal to the **`💡 7-PART DETERMINISTIC DECISION EXPLAINER`** and the **Central Evidence Items** table.

**Speaker:**
> *"Notice that the final decision is never generated prose. It is generated by a deterministic policy engine and translated into a standardized 7-part Decision Explainer:
>
> 1. **Finding:** What the system found.
> 2. **Evidence:** Every supported canonical token (`EV-001` through `EV-007`).
> 3. **Counter-Evidence:** What argued against it.
> 4. **Verification:** What survived independent deterministic verification.
> 5. **Policy:** Which card scheme rule applied (Visa CE 3.0, Mastercard FPT, or NPCI UDIR).
> 6. **Uncertainty:** Explicit risk taxonomy (`INSUFFICIENT_EVIDENCE` or `UNCERTAIN`).
> 7. **Decision:** The deterministic next action.
>
> Every claim is strictly bound to evidence IDs. An LLM cannot invent evidence tokens like `EV-999`—the independent verifier rejects hallucinated IDs instantly with 100% precision."*

---

### ⏱️ [2:45 – 3:45] Autonomous Representment & 6-Tier Provenance Graph
**Visual on Screen:**  
Close modal. Click **`➕ Visa 10.4 (CE 3.0)`**.  
Click **`Inspect`** on the auto-dispatched case. Click **`📄 PDF`** button to show the downloaded signed representment package. Then scroll to the **`🧬 Evidence Provenance Graph`**.

**Speaker:**
> *"Now let's see a fully qualifying case. When a customer files an unauthorized dispute on Visa, Visa Compelling Evidence 3.0 requires two undisputed transactions between 120 and 365 days ago with matching IP or device fingerprints.
>
> When the evidence qualifies, the system computes:
> - **Confidence Score:** 100/100
> - **Estimated Win Probability:** 99%
> - **Expected Value:** +₹3,707 net profit
> - **Verdict:** `🛡️ AUTO-DISPATCHED`
>
> Click 'PDF'—SentinelDispute instantly generates an official, bank-ready legal evidence package sealed with SHA-256 cryptographic hashes.
>
> And look at the **Provenance DAG**:
> Every decision traces through 6 tiers:  
> **Source $\to$ Evidence Item $\to$ Claim $\to$ Challenge $\to$ Verification $\to$ Policy $\to$ Decision.**
> Any compliance auditor or bank reviewer can reconstruct the exact chain of custody."*

---

### ⏱️ [3:45 – 4:30] The Economic Engine: Expected Value & Zero Fee Bleed
**Visual on Screen:**  
Close modal. Click **`🛑 Negative E[V] (Auto-Refund)`**.  
Show that the dispute is immediately resolved as `AUTO_ACCEPT_OR_REFUND`.

**Speaker:**
> *"Why do merchants lose so much money on chargebacks? Because they defend cases where the math doesn't make sense.
> 
> If a dispute is for ₹450, and your win probability is 20%, defending it risks a ₹1,500 bank penalty. The expected value is deeply negative:
> $$E[V] = P(\text{win}) \cdot \text{Amount} - (1 - P(\text{win})) \cdot \text{Fee}_{\text{dispute}} - \text{Cost}_{\text{ops}}$$
>
> When $E[V] \le 0$, SentinelDispute **automatically accepts the loss and refunds the customer**, saving the merchant ₹1,500 in non-refundable bank fees. We defend only when mathematically profitable."*

---

### ⏱️ [4:30 – 5:00] Live 115-Scenario Benchmark & Tamper-Evident Ledger
**Visual on Screen:**  
Click **`⚡ 115-Scenario Benchmark (A-P)`**.  
Wait ~8 seconds as 115 live state machines execute. Read the alert popup.  
Then click **`⛓️ Cryptographic Ledger`** tab and click **`🔍 Verify Full Chain Integrity`**.

**Speaker:**
> *"Finally, we don't just test single happy paths. We benchmarked SentinelDispute against a **115-scenario held-out synthetic test suite** across 16 adversarial cohorts (A through P)—including prompt injection attacks, missing carrier proofs, and hallucination traps.
> 
> - **Autonomous Precision:** 100.00%
> - **False Positives:** 0 (vs. 28 false positives in ungrounded LLM systems)
> - **Unwinnable Fee Bleed Saved:** ₹1,46,994
> - **Full Test Suite:** 148 automated tests passed
> 
> And every single event—from webhook ingress to challenger overturn—is hashed in an append-only, tamper-evident SHA-256 audit ledger.
>
> Click 'Verify Full Chain Integrity': **100% Intact.**
> 
> SentinelDispute turns dispute management from an expensive, risky chore into an evidence-grounded, mathematical risk engine built for Razorpay. Thank you!"*

---

## 💡 Top Tips for Your Recording
1. **Resolution:** 1080p (1920x1080) in Dark Mode looks crisp and professional.
2. **Speed & Clarity:** Deliver with confidence. When speaking about the Challenger disproving the AI, emphasize: *"This is the differentiator—the system actively tries to disprove its own claims before spending money."*
3. **Pacing:** Let the browser animate naturally. When you click **Hero Demo**, let the modal open smoothly and highlight the purple/red Challenger box.
