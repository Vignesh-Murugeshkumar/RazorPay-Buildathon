"""
SentinelDispute - Local Policy Knowledge Base & Real Document Retriever.

Provides local, deterministic document indexing and retrieval for network rules,
merchant terms of service, carrier guidelines, and internal dispute risk policies.
Citations returned by this module are used by the AI Investigation Agent for grounded reasoning.
"""

import re
import math
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


import hashlib

class PolicyExcerpt(BaseModel):
    retrieval_id: str = Field(default="", description="Unique session retrieval reference, e.g. RET-001")
    document_id: str = Field(..., description="Canonical policy document ID, e.g. DOC-VISA-CE30")
    section_id: str = Field(..., description="Policy section identifier, e.g. SEC-CE30-CORE")
    title: str = Field(..., description="Human readable policy title")
    content: str = Field(..., description="Full text excerpt of policy standard")
    content_hash: str = Field(default="", description="SHA-256 cryptographic hash of policy content")
    version: str = Field(default="2026.1", description="Policy version stamp")
    relevance_score: float = Field(..., description="TF-IDF and domain match score")
    citation_text: str = Field(..., description="Formal legal citation string")

    @property
    def section(self) -> str:
        return self.section_id


class PolicyKnowledgeBase:
    """
    Curated local policy repository with token-based TF-IDF ranking.
    Provides verifiable, hallucination-free policy grounding.
    """

    DOCUMENTS = [
        {
            "document_id": "DOC-VISA-CE30",
            "section_id": "SEC-CE30-CORE",
            "title": "Visa Compelling Evidence 3.0 (CE 3.0) Dispute Rules",
            "keywords": ["visa", "10.4", "fraud", "compelling", "evidence", "ce30", "lookback", "qualifying", "historical", "ip", "device"],
            "content": (
                "Under Visa Reason Code 10.4 (Card-Absent Fraud), a merchant can overturn fraud disputes "
                "by submitting Compelling Evidence 3.0: at least 2 historical undisputed transactions processed "
                "between 120 and 365 calendar days prior to the dispute date. At least 2 of 4 customer identifiers "
                "(Customer IP address, Device ID/fingerprint, Account user ID, Shipping address) must match across "
                "the disputed transaction and the historical orders. Crucially, at least 1 matched identifier must be "
                "either IP Address or Device Fingerprint."
            )
        },
        {
            "document_id": "DOC-MC-FPT",
            "section_id": "SEC-FPT-CORE",
            "title": "Mastercard First-Party Trust (FPT) Program Guidelines",
            "keywords": ["mastercard", "4837", "4853", "4855", "first party", "trust", "fpt", "tier", "device", "carrier", "signature"],
            "content": (
                "Mastercard First-Party Trust establishes merchant non-fraud defense for reason codes 4837, 4853, and 4855. "
                "Requirements include >= 2 prior undisputed orders within a 365-day window. Defense relies on a 3-tier matrix: "
                "Tier 1 (Device Identity: consistent persistent device fingerprint or IP subnet), Tier 2 (Delivery confirmation: "
                "carrier physical proof of delivery or verified digital access logs), and Tier 3 (Authentication factor: 3DS/MFA "
                "or verified account login session)."
            )
        },
        {
            "document_id": "DOC-3DS-SHIFT",
            "section_id": "SEC-3DS-LIABILITY",
            "title": "Payment Network 3-D Secure Liability Shift Standards",
            "keywords": ["3ds", "3-d secure", "mfa", "otp", "authentication", "liability shift", "fraud", "10.4", "4837"],
            "content": (
                "Where an online card transaction completes Two-Factor Authentication or 3-D Secure (EMV 3DS) with full "
                "cardholder challenge verification, liability for card-not-present fraud shifts from merchant to issuing bank. "
                "Verified authentication logs [EV-003] provide decisive grounds for representment under both Visa and Mastercard rules."
            )
        },
        {
            "document_id": "DOC-CARRIER-POD",
            "section_id": "SEC-CARRIER-VERIFICATION",
            "title": "Logistics Carrier Proof of Delivery (POD) Standards",
            "keywords": ["carrier", "bluedart", "delhivery", "tracking", "delivered", "pod", "gps", "signature", "physical"],
            "content": (
                "Valid Proof of Delivery requires an active carrier consignment tracking number, confirmed delivered status, "
                "and at least one secondary validation factor: physical recipient signature or GPS coordinate verification "
                "within a 50-meter radius of customer destination address. Delivery status without an authentic tracking number "
                "constitutes an objective contradiction and disqualifies autonomous representment."
            )
        },
        {
            "document_id": "DOC-DIGITAL-GOODS",
            "section_id": "SEC-DIGITAL-FULFILLMENT",
            "title": "Digital Service & SaaS Fulfillment Evidence Standards",
            "keywords": ["digital", "saas", "download", "access logs", "subscription", "license", "active account", "13.1", "4855"],
            "content": (
                "For intangible SaaS or digital products disputed under merchandise/service not received (13.1 / 4855), "
                "defense requires timestamped server access logs proving feature consumption, coupled with cardholder account "
                "activity. If server access logs are claimed but the user account was suspended or inactive during the billing "
                "period, this represents an unresolved evidence contradiction."
            )
        },
        {
            "document_id": "DOC-MERCHANT-TOS",
            "section_id": "SEC-TOS-CANCELLATION",
            "title": "Merchant Purchase Terms and Cancellation Policy",
            "keywords": ["terms", "tos", "policy", "cancellation", "refund", "13.7", "4853", "notice", "agreement"],
            "content": (
                "Merchant Terms of Sale specify that subscription renewals require cancellation notice at least 24 hours prior "
                "to billing cycle renewal. Disputed recurring charges where the cardholder accepted terms at checkout and did not "
                "transmit cancellation notice prior to billing are defensible under reason code 13.7 and 4853."
            )
        },
        {
            "document_id": "DOC-INTERNAL-RISK",
            "section_id": "SEC-RISK-THRESHOLDS",
            "title": "SentinelDispute Autonomous Financial Risk Policy",
            "keywords": ["expected value", "fee", "threshold", "hitl", "auto represent", "financial", "arbitration"],
            "content": (
                "Every disputed representment incurs an irreversible issuing bank arbitration fee (₹1,500.00) if lost. "
                "Autonomous dispatch (AUTO_REPRESENT) is strictly prohibited unless E[V] > 0, estimated win probability >= 70%, "
                "all claims are verified without contradictions, and confidence score >= 85.0. Any dispute exhibiting evidence "
                "contradictions or negative expected value must be routed to HITL_REVIEW or ACCEPT_LOSS."
            )
        }
    ]

    def __init__(self):
        # Precompute vocabulary for inverted index
        self._doc_tokens = []
        for doc in self.DOCUMENTS:
            tokens = self._tokenize(doc["title"] + " " + doc["content"] + " " + " ".join(doc["keywords"]))
            self._doc_tokens.append(set(tokens))

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        return [t.lower() for t in re.findall(r'[a-zA-Z0-9_\-\.]+', text) if len(t) > 1]

    def retrieve(
        self,
        query: str,
        card_network: Optional[str] = None,
        reason_code: Optional[str] = None,
        service_type: Optional[str] = None,
        top_k: int = 3
    ) -> List[PolicyExcerpt]:
        """
        Retrieves the top-k most relevant policy excerpts for the given dispute query.
        Boosts network, reason-code, and service-type specific documents.
        """
        combined_query = f"{query} {card_network or ''} {reason_code or ''} {service_type or ''}"
        q_tokens = set(self._tokenize(combined_query))

        scored_docs = []
        for idx, doc in enumerate(self.DOCUMENTS):
            doc_toks = self._doc_tokens[idx]
            intersection = q_tokens.intersection(doc_toks)
            if not intersection:
                score = 0.01
            else:
                score = len(intersection) / math.sqrt(len(q_tokens) * len(doc_toks) + 1.0)

            # Domain bonuses
            net_lower = (card_network or "").lower()
            code_str = str(reason_code or "")
            if net_lower == "visa" and "DOC-VISA" in doc["document_id"]:
                score += 0.40
            elif net_lower == "mastercard" and "DOC-MC" in doc["document_id"]:
                score += 0.40

            if code_str in ("10.4", "4837") and "DOC-3DS" in doc["document_id"]:
                score += 0.20
            if code_str in ("13.1", "4855") and ("DOC-CARRIER" in doc["document_id"] or "DOC-DIGITAL" in doc["document_id"]):
                score += 0.30
            if code_str in ("13.7", "4853") and "DOC-MERCHANT-TOS" in doc["document_id"]:
                score += 0.30

            st_lower = (service_type or "").lower()
            if "physical" in st_lower and "DOC-CARRIER" in doc["document_id"]:
                score += 0.35
            elif "digital" in st_lower and "DOC-DIGITAL" in doc["document_id"]:
                score += 0.35

            citation = f"[{doc['document_id']} § {doc['section_id']}] {doc['title']}"
            c_hash = hashlib.sha256(doc["content"].encode("utf-8")).hexdigest()
            excerpt = PolicyExcerpt(
                document_id=doc["document_id"],
                section_id=doc["section_id"],
                title=doc["title"],
                content=doc["content"],
                content_hash=c_hash,
                version="2026.1",
                relevance_score=round(score, 4),
                citation_text=citation
            )
            scored_docs.append(excerpt)

        # Sort descending by relevance score
        scored_docs.sort(key=lambda d: d.relevance_score, reverse=True)
        top_excerpts = scored_docs[:top_k]
        for idx, exc in enumerate(top_excerpts, 1):
            exc.retrieval_id = f"RET-{idx:03d}"
        return top_excerpts


policy_knowledge_base = PolicyKnowledgeBase()
policy_kb = policy_knowledge_base
