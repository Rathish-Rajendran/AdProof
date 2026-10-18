"""Deliberately narrow mock intelligence behind replaceable async interfaces.

These deterministic pattern checks are demo fixtures, not Gemini, OCR, platform
policy enforcement, or clinical fact checking.
"""

import hashlib
import re

from .fixtures import LANDING, SAFE_COPY


def image_digest(image_url):
    # Identifies our immutable synthetic fixture, not downloaded image bytes.
    return hashlib.sha256(("adproof-synthetic-v1:" + image_url).encode()).hexdigest()


async def inspect_creative(campaign, *, phase):
    copy = campaign["creative"]["ad_copy"]
    image = campaign["creative"]["image_url"]
    claims = []

    def add(text, kind, source, value=None):
        claim = {
            "claim_id": f"{phase.lower()}_claim_{len(claims) + 1:02d}",
            "claim": text,
            "claim_type": kind,
            "source": source,
        }
        if value is not None:
            claim["value"] = value
        claims.append(claim)

    health = re.search(r"lose\s+\d+(?:\.\d+)?\s+(?:pounds?|lbs?)[^.!?]*", copy, re.I)
    if health:
        add(health.group().strip("—- "), "HEALTH_OUTCOME", "AD_COPY")
    if re.search(r"clinically\s+proven", copy, re.I):
        add("The product is clinically proven.", "CLINICAL_EVIDENCE", "AD_COPY")
    if re.search(r"(?:recommended|endorsed|approved)\s+by\s+doctors", copy, re.I):
        add("The product is recommended by doctors.", "ENDORSEMENT", "AD_COPY")
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*%\s*(?:off|discount)", copy, re.I):
        add(f"The advertised discount is {match.group(1)}%.", "PRICE_DISCOUNT", "AD_COPY", float(match.group(1)))
    if re.search(r"(?:cures?|guaranteed\s+(?:weight|results?|to))", copy, re.I):
        add("The copy promises a cure or guaranteed outcome.", "HEALTH_OUTCOME", "AD_COPY")
    prices = re.findall(r"\$(\d+(?:\.\d{1,2})?)", copy)
    for price in prices:
        add(f"The creative includes a price of ${float(price):.2f}.", "PRODUCT_FACT", "AD_COPY", float(price))

    visible_text = ["Acme Balance"]
    if image.endswith("/unsafe.svg"):
        visible_text.extend(["CLINICALLY PROVEN", "50% OFF"])
        add("The product is clinically proven.", "CLINICAL_EVIDENCE", "IMAGE_TEXT")
        add("The advertised discount is 50%.", "PRICE_DISCOUNT", "IMAGE_TEXT", 50.0)
    return {
        "request_id": campaign["request_id"],
        "visible_text": visible_text,
        "visual_assertions": [],
        "atomic_claims": claims,
        "inspection_warnings": ["Synthetic fixture inspection; no OCR or AI model was called."],
        "image_sha256": image_digest(image),
    }


async def verify_campaign(request):
    verified, issues = [], []
    discount = (LANDING["previous_price"] - LANDING["current_price"]) / LANDING["previous_price"] * 100
    evidence = {
        "source_type": "LANDING_PAGE",
        "source_url": LANDING["source_url"],
        "excerpt": LANDING["text"],
        "relation": "CONTEXT",
    }
    for claim in request["inspection"]["atomic_claims"]:
        kind = claim["claim_type"]
        status, category, severity, reason, fix = "SUPPORTED", None, None, "", ""
        if kind in {"HEALTH_OUTCOME", "CLINICAL_EVIDENCE"}:
            status, category, severity = "INSUFFICIENT", "UNSUPPORTED_HEALTH_CLAIM", "CRITICAL"
            reason = "The fictional landing page supplies no study supporting this claim."
            fix = "Remove the health result and clinical-proof statement from every creative surface."
        elif kind == "ENDORSEMENT":
            status, category, severity = "INSUFFICIENT", "UNSUPPORTED_ENDORSEMENT", "MAJOR"
            reason = "No doctor endorsement is supplied in the demo evidence."
            fix = "Remove the endorsement unless substantiating evidence is provided."
        elif kind == "PRICE_DISCOUNT" and abs(claim["value"] - discount) > 0.1:
            status, category, severity = "CONTRADICTED", "PRICE_MISMATCH", "MAJOR"
            reason = f"${LANDING['previous_price']:.2f} → ${LANDING['current_price']:.2f} is about {discount:.0f}% off, not {claim['value']:g}%."
            fix = "Use the supported prices or a rounded 20% discount."
        elif kind == "PRODUCT_FACT" and claim.get("value") not in {39.99, 49.99}:
            status, category, severity = "CONTRADICTED", "PRICE_MISMATCH", "MAJOR"
            reason = "This price does not match either price on the fictional landing page."
            fix = "Use $39.99 current price and $49.99 previous price."

        ref = dict(evidence, relation="CONTRADICTS" if status == "CONTRADICTED" else ("SUPPORTS" if status == "SUPPORTED" else "CONTEXT"))
        verified.append({**claim, "status": status, "evidence": [ref], "confidence": 1.0})
        if category:
            issues.append({
                "issue_id": f"{request['phase'].lower()}_issue_{len(issues) + 1:02d}",
                "category": category,
                "severity": severity,
                "explanation": reason,
                "policy": {"authority": "DEMO_POLICY", "title": "Synthetic AdProof demo rules", "url": "/fixture/policy"},
                "related_claim_ids": [claim["claim_id"]],
                "source": claim["source"],
                "suggested_fix": fix,
                "auto_fixable": claim["source"] == "AD_COPY",
            })
    decision = "BLOCK" if any(x["severity"] == "CRITICAL" for x in issues) else ("FIX_REQUIRED" if issues else "PASS")
    return {
        "candidate_id": request["candidate_id"], "phase": request["phase"],
        "claims": verified, "issues": issues, "decision": decision,
        "retrieval_warnings": ["Evidence is a bundled synthetic fixture; no live URL was fetched."],
        "policy_pack_version": "synthetic-demo-v1",
        "source_snapshots": [{"source_url": LANDING["source_url"], "content_sha256": hashlib.sha256(LANDING["text"].encode()).hexdigest()}],
    }


async def repair_copy(request):
    issues = request["verification"]["issues"]
    return {
        "repaired_copy": SAFE_COPY,
        "changes": [
            {"reason": issue["suggested_fix"], "related_issue_ids": [issue["issue_id"]]}
            for issue in issues if issue["auto_fixable"]
        ],
        "unresolved_issue_ids": [issue["issue_id"] for issue in issues if not issue["auto_fixable"]],
    }
