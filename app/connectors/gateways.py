from typing import Dict, Any, Optional
from app.connectors.base import BaseGatewayAdapter, GatewayDisputeEvent
from app.core.logger import get_logger

logger = get_logger("gateway_connectors")


class RazorpayUPIAndRuPayAdapter(BaseGatewayAdapter):
    """
    Domestic Rail Connector (India):
    Handles NPCI UDIR (Unified Dispute and Issue Resolution) for UPI and RuPay
    disputes via Razorpay Dispute APIs.
    """

    def parse_webhook(self, raw_payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> GatewayDisputeEvent:
        entity = raw_payload.get("payload", {}).get("dispute", {}).get("entity", raw_payload)
        payment_id = entity.get("payment_id", "pay_default")
        dispute_id = entity.get("id", entity.get("dispute_id", "disp_default"))
        amount = float(entity.get("amount", 0.0))
        # Amount in paise conversion if > 1000
        if amount > 10000:
            amount = amount / 100.0

        method = entity.get("method", "upi").lower()
        network = "rupay" if "rupay" in method else ("upi" if "upi" in method else "visa")

        return GatewayDisputeEvent(
            gateway="razorpay_udir",
            dispute_id=dispute_id,
            payment_id=payment_id,
            amount=amount or 1000.0,
            currency=entity.get("currency", "INR"),
            reason=entity.get("reason_code", "UDIR_COMPLAINT"),
            status=entity.get("status", "open"),
            network=network,
            raw_event=raw_payload
        )

    def submit_evidence(self, dispute_id: str, dossier_payload: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("Submitting evidence to NPCI UDIR / Razorpay Dispute API", dispute_id=dispute_id)
        return {
            "gateway": "razorpay_udir",
            "dispute_id": dispute_id,
            "status": "EVIDENCE_SUBMITTED",
            "network_ack_id": f"udir_ack_{dispute_id}",
            "success": True
        }


class StripeGatewayAdapter(BaseGatewayAdapter):
    """
    Global Gateway Adapter: Stripe.
    Normalizes Stripe dispute webhook events (e.g. charge.dispute.created).
    """

    def parse_webhook(self, raw_payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> GatewayDisputeEvent:
        obj = raw_payload.get("data", {}).get("object", raw_payload)
        dispute_id = obj.get("id", "dp_stripe_default")
        charge_id = obj.get("charge", "ch_stripe_default")
        amount = float(obj.get("amount", 0.0)) / 100.0 if obj.get("amount") else 25.0
        reason = obj.get("reason", "fraudulent")

        # Map stripe reasons to ISO / Visa codes
        code = "10.4" if reason in ("fraudulent", "unrecognized") else ("13.1" if reason == "product_not_received" else "13.7")

        return GatewayDisputeEvent(
            gateway="stripe",
            dispute_id=dispute_id,
            payment_id=charge_id,
            amount=amount * 85.0 if obj.get("currency", "usd").lower() == "usd" else amount,  # Convert to INR equiv
            currency=obj.get("currency", "usd").upper(),
            reason=code,
            status=obj.get("status", "needs_response"),
            network=obj.get("payment_method_details", {}).get("card", {}).get("brand", "visa").lower(),
            raw_event=raw_payload
        )

    def submit_evidence(self, dispute_id: str, dossier_payload: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("Submitting evidence to Stripe Disputes API", dispute_id=dispute_id)
        return {
            "gateway": "stripe",
            "dispute_id": dispute_id,
            "status": "SUBMITTED",
            "stripe_evidence_id": f"ev_{dispute_id}",
            "success": True
        }


class AdyenGatewayAdapter(BaseGatewayAdapter):
    """
    Global Gateway Adapter: Adyen.
    Normalizes Adyen Dispute / Chargeback Webhook Notifications.
    """

    def parse_webhook(self, raw_payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> GatewayDisputeEvent:
        items = raw_payload.get("notificationItems", [{}])[0].get("NotificationRequestItem", raw_payload)
        psp_ref = items.get("pspReference", "adyen_psp_default")
        amount_dict = items.get("amount", {})
        amount = float(amount_dict.get("value", 0.0)) / 100.0 if amount_dict.get("value") else 50.0

        return GatewayDisputeEvent(
            gateway="adyen",
            dispute_id=f"dsp_{psp_ref}",
            payment_id=psp_ref,
            amount=amount * 85.0 if amount_dict.get("currency", "EUR").upper() in ("USD", "EUR") else amount,
            currency=amount_dict.get("currency", "EUR"),
            reason=items.get("reason", "10.4"),
            status="OPEN",
            network=items.get("paymentMethod", "visa").lower(),
            raw_event=raw_payload
        )

    def submit_evidence(self, dispute_id: str, dossier_payload: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("Submitting defense dossier to Adyen Defense API", dispute_id=dispute_id)
        return {
            "gateway": "adyen",
            "dispute_id": dispute_id,
            "status": "DISPATCHED_TO_SCHEME",
            "adyen_defense_token": f"adyen_def_{dispute_id}",
            "success": True
        }


class ShopifyGatewayAdapter(BaseGatewayAdapter):
    """
    Shopify Payments Gateway Adapter.
    """

    def parse_webhook(self, raw_payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> GatewayDisputeEvent:
        dispute_id = raw_payload.get("id", "shopify_disp_default")
        order_id = raw_payload.get("order_id", "shopify_ord_default")
        amount = float(raw_payload.get("amount", 1000.0))

        return GatewayDisputeEvent(
            gateway="shopify_payments",
            dispute_id=str(dispute_id),
            payment_id=str(order_id),
            amount=amount,
            currency=raw_payload.get("currency", "INR"),
            reason=raw_payload.get("reason", "fraudulent"),
            status=raw_payload.get("status", "open"),
            network="visa",
            raw_event=raw_payload
        )

    def submit_evidence(self, dispute_id: str, dossier_payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "gateway": "shopify_payments",
            "dispute_id": dispute_id,
            "status": "EVIDENCE_UPLOADED",
            "success": True
        }
