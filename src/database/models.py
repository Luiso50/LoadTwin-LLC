from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class LoadStatus(StrEnum):
    AVAILABLE = "available"
    MATCHED = "matched"
    BOOKED = "booked"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class TripStatus(StrEnum):
    PENDING = "pending"
    OFFERED = "offered"
    ACCEPTED = "accepted"
    IN_TRANSIT = "in_transit"
    DELAYED = "delayed"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class InvoiceStatus(StrEnum):
    DRAFT = "draft"
    ISSUED = "issued"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    OVERDUE = "overdue"
    VOID = "void"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


class StopStatus(StrEnum):
    PENDING = "pending"
    ARRIVED = "arrived"
    LOADED = "loaded"
    UNLOADED = "unloaded"
    SKIPPED = "skipped"


class DriverStatus(StrEnum):
    ONBOARDING = "onboarding"
    ACTIVE = "active"
    INACTIVE = "inactive"


class OnboardingStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"


class DocumentType(StrEnum):
    MC = "mc"
    DOT = "dot"
    INSURANCE = "insurance"
    W9 = "w9"
    CARRIER_PACKET = "carrier_packet"


class EvidenceType(StrEnum):
    WHATSAPP = "whatsapp"
    EMAIL = "email"
    RATE_CONFIRMATION = "rate_confirmation"
    BOL = "bol"
    POD = "pod"
    INVOICE = "invoice"
    NOTE = "note"


class ContractStatus(StrEnum):
    DRAFT = "draft"
    SENT = "sent"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class CommissionStatus(StrEnum):
    PENDING = "pending"
    INVOICED = "invoiced"
    PAID = "paid"


class ProposalStatus(StrEnum):
    SENT = "sent"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"


class BookingCaseStatus(StrEnum):
    DRIVER_ACCEPTED = "driver_accepted"
    PENDING_TRULOS = "pending_trulos"
    ORDERED = "ordered"
    IN_TRANSIT = "in_transit"
    COMPLETED = "completed"


class Address(BaseModel):
    city: str
    state: str
    postal_code: Optional[str] = None
    address_line: Optional[str] = None


class Driver(BaseModel):
    id: str = Field(default_factory=lambda: f"DRV-{uuid4().hex[:10].upper()}")
    name: str
    phone: str
    mc_number: Optional[str] = None
    dot_number: Optional[str] = None
    equipment_types: list[str] = Field(default_factory=list)
    preferred_states: list[str] = Field(default_factory=list)
    minimum_rpm: Optional[Decimal] = Field(default=None, ge=0)
    commission_percent: Decimal = Field(default=Decimal("10"), ge=0, le=100)
    status: DriverStatus = DriverStatus.ONBOARDING
    created_at: datetime = Field(default_factory=utc_now)


class DriverDocument(BaseModel):
    id: str = Field(default_factory=lambda: f"DOC-{uuid4().hex[:10].upper()}")
    driver_id: str
    document_type: DocumentType
    document_url: Optional[str] = None
    received_at: datetime = Field(default_factory=utc_now)
    expires_at: Optional[date] = None
    verified: bool = False


class OnboardingDocument(BaseModel):
    document_type: DocumentType
    document_url: Optional[str] = None
    expires_at: Optional[date] = None
    verified: bool = False


class OnboardingCase(BaseModel):
    id: str = Field(default_factory=lambda: f"ONB-{uuid4().hex[:10].upper()}")
    phone: str
    status: OnboardingStatus = OnboardingStatus.PENDING
    driver_id: Optional[str] = None
    name: Optional[str] = None
    equipment_types: list[str] = Field(default_factory=list)
    required_documents: list[DocumentType] = Field(
        default_factory=lambda: list(DocumentType)
    )
    documents: list[OnboardingDocument] = Field(default_factory=list)
    verified_documents: list[DocumentType] = Field(default_factory=list)
    last_message: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class EvidenceEvent(BaseModel):
    id: str = Field(default_factory=lambda: f"EVD-{uuid4().hex[:10].upper()}")
    load_id: str
    evidence_type: EvidenceType
    description: str
    source: Optional[str] = None
    document_url: Optional[str] = None
    metadata: dict[str, str] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=utc_now)


class Message(BaseModel):
    id: str
    channel: str = "whatsapp"
    sender: str
    text: str
    driver_id: Optional[str] = None
    intent: Optional[str] = None
    received_at: datetime = Field(default_factory=utc_now)


class DashboardSummary(BaseModel):
    active_drivers: int
    active_loads: int
    revenue: Decimal = Field(ge=0)
    payments_collected: Decimal = Field(default=Decimal("0"), ge=0)
    pending_payments: int = 0
    pending_commissions: int
    pending_contracts: int
    missing_documents: int
    recent_messages: list[Message] = Field(default_factory=list)


class Load(BaseModel):
    id: str
    origin: Address
    destination: Address
    equipment_type: str
    weight_lbs: Optional[int] = Field(default=None, ge=0)
    pickup_date: Optional[date] = None
    delivery_date: Optional[date] = None
    offered_rate: Optional[Decimal] = Field(default=None, ge=0)
    status: LoadStatus = LoadStatus.AVAILABLE
    source: Optional[str] = None
    external_reference: Optional[str] = None
    notes: Optional[str] = None


class LoadProposal(BaseModel):
    id: str = Field(default_factory=lambda: f"OFF-{uuid4().hex[:10].upper()}")
    load_id: str
    driver_id: str
    message: str
    status: ProposalStatus = ProposalStatus.SENT
    created_at: datetime = Field(default_factory=utc_now)
    responded_at: Optional[datetime] = None


class BookingCase(BaseModel):
    id: str = Field(default_factory=lambda: f"CASE-{uuid4().hex[:10].upper()}")
    load_id: str
    driver_id: str
    agreed_rate: Optional[Decimal] = Field(default=None, ge=0)
    status: BookingCaseStatus = BookingCaseStatus.DRIVER_ACCEPTED
    external_order_id: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)


class PaymentMirror(BaseModel):
    id: str = Field(default_factory=lambda: f"PAY-{uuid4().hex[:10].upper()}")
    booking_case_id: str
    external_reference: str
    amount: Decimal = Field(ge=0)
    status: PaymentStatus = PaymentStatus.PENDING
    receipt_url: Optional[str] = None
    paid_at: Optional[datetime] = None
    source: str = "trulos"
    synced_at: datetime = Field(default_factory=utc_now)


class Broker(BaseModel):
    id: str = Field(default_factory=lambda: f"BRK-{uuid4().hex[:10].upper()}")
    name: str
    contact_person: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    mc_number: Optional[str] = None
    payment_terms: Optional[str] = None
    internal_rating: Optional[int] = Field(default=None, ge=1, le=5)
    notes: Optional[str] = None


class Carrier(BaseModel):
    id: str
    legal_name: str
    mc_number: Optional[str] = None
    dot_number: Optional[str] = None
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    equipment_types: list[str] = Field(default_factory=list)
    active: bool = True
    notes: Optional[str] = None


class Stop(BaseModel):
    id: str
    trip_id: str
    sequence: int = Field(ge=1)
    stop_type: str
    location: Address
    scheduled_at: Optional[datetime] = None
    arrived_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: StopStatus = StopStatus.PENDING
    reference_number: Optional[str] = None
    notes: Optional[str] = None


class Trip(BaseModel):
    id: str
    load_id: str
    carrier_id: str
    status: TripStatus = TripStatus.PENDING
    agreed_rate: Decimal = Field(ge=0)
    dispatcher_fee: Optional[Decimal] = Field(default=None, ge=0)
    pickup_stop_ids: list[str] = Field(default_factory=list)
    delivery_stop_ids: list[str] = Field(default_factory=list)
    current_location: Optional[Address] = None
    eta: Optional[datetime] = None
    notes: Optional[str] = None


class Contract(BaseModel):
    id: str
    trip_id: str
    contract_number: str
    customer_name: str
    carrier_name: str
    agreed_rate: Decimal = Field(ge=0)
    signed_at: Optional[datetime] = None
    document_url: Optional[str] = None
    terms: Optional[str] = None
    status: ContractStatus = ContractStatus.DRAFT
    accepted_at: Optional[datetime] = None
    renewal_date: Optional[date] = None


class Commission(BaseModel):
    id: str = Field(default_factory=lambda: f"COM-{uuid4().hex[:10].upper()}")
    load_id: str
    driver_id: str
    rate: Decimal = Field(ge=0)
    percentage: Decimal = Field(ge=0, le=100)
    amount: Decimal = Field(ge=0)
    status: CommissionStatus = CommissionStatus.PENDING
    paid_at: Optional[datetime] = None


class Invoice(BaseModel):
    id: str
    invoice_number: str
    trip_id: str
    customer_name: str
    amount: Decimal = Field(gt=0)
    issued_at: Optional[date] = None
    due_date: Optional[date] = None
    status: InvoiceStatus = InvoiceStatus.DRAFT
    document_url: Optional[str] = None
    notes: Optional[str] = None


class Payment(BaseModel):
    id: str
    invoice_id: str
    amount: Decimal = Field(gt=0)
    status: PaymentStatus = PaymentStatus.PENDING
    method: Optional[str] = None
    provider_reference: Optional[str] = None
    initiated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    notes: Optional[str] = None
