import asyncio
import hashlib
import hmac
import json
import logging
import os

from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field

from src.agent.approvals import ApprovalStatus, ApprovalStore
from src.agent.matching import CarrierMatch, rank_carriers_for_load
from src.agent.onboarding import build_onboarding_message
from src.agent.profitability import evaluate_load_profitability
from src.agent.request_parser import parse_load_request
from src.database.models import (
    Broker,
    BookingCase,
    BookingCaseStatus,
    Carrier,
    Commission,
    CommissionStatus,
    Contract,
    ContractStatus,
    DashboardSummary,
    DocumentType,
    Driver,
    DriverStatus,
    DriverDocument,
    EvidenceEvent,
    EvidenceType,
    Load,
    LoadProposal,
    LoadStatus,
    Message,
    OnboardingCase,
    OnboardingDocument,
    PaymentMirror,
    PaymentStatus,
    ProposalStatus,
    utc_now,
)
from src.database.operations import OperationsStore
from src.integrations.load_sources import LoadSearchCriteria, LoadSourceRegistry
from src.integrations.trulos_api import TrulosApiConfig, TrulosApiError, TrulosApiSource
from src.integrations.whatsapp import (
    IncomingWhatsAppMessage,
    WhatsAppSendError,
    extract_text_messages,
    send_whatsapp_text_message,
)


class MatchingRequest(BaseModel):
    load: Load
    carriers: list[Carrier]


class ContactRequest(BaseModel):
    name: str
    company: str | None = None
    email: EmailStr
    need: str


class LoadSearchRequest(BaseModel):
    origin_city: str | None = None
    origin_state: str | None = None
    destination_city: str | None = None
    destination_state: str | None = None
    equipment_type: str | None = None
    pickup_date: str | None = None
    minimum_rate: float | None = None


class ApprovalRequest(BaseModel):
    load: Load
    distance_miles: Decimal
    diesel_price_per_gallon: Decimal
    approver_phone: str | None = None


class LoadScanRequest(BaseModel):
    """Búsqueda de cargas + evaluación automática de rentabilidad para cada resultado.

    distance_miles y diesel_price_per_gallon se aplican por igual a todas las
    cargas encontradas (placeholder mientras no haya cálculo real por ruta).
    """

    search: LoadSearchRequest
    distance_miles: Decimal
    diesel_price_per_gallon: Decimal
    approver_phone: str | None = None


class OnboardingCompletionRequest(BaseModel):
    name: str
    equipment_types: list[str] = Field(default_factory=list)


class EmailEvidenceRequest(BaseModel):
    sender: EmailStr
    recipients: list[EmailStr] = Field(min_length=1)
    subject: str
    body: str
    document_url: str | None = None


class ProposalRequest(BaseModel):
    load_id: str
    driver_id: str
    message: str
    send_whatsapp: bool = False


class ProposalResponseRequest(BaseModel):
    status: ProposalStatus


class PaymentMirrorRequest(BaseModel):
    external_reference: str
    amount: Decimal = Field(ge=0)
    status: PaymentStatus = PaymentStatus.PENDING
    receipt_url: str | None = None
    paid_at: datetime | None = None


class TrulosOrderRequest(BaseModel):
    external_order_id: str


class BookingCaseStatusRequest(BaseModel):
    status: BookingCaseStatus
    external_order_id: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_run_periodic_load_scan())
    yield
    task.cancel()


app = FastAPI(
    title="LoadTwin API",
    version="0.1.0",
    description="API inicial para operaciones de despacho y matching de cargas.",
    lifespan=lifespan,
)

cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://127.0.0.1:8080,http://localhost:8080,https://luiso50.github.io",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

contact_requests: list[ContactRequest] = []

_load_source_list = []
try:
    _load_source_list.append(TrulosApiSource(TrulosApiConfig.from_env()))
except TrulosApiError:
    pass  # TRULOS_API_KEY no configurada: se omite la fuente hasta tener acceso Founder/Pro
load_sources = LoadSourceRegistry(_load_source_list)

incoming_whatsapp_messages: list[IncomingWhatsAppMessage] = []
approval_store = ApprovalStore()
operations_store = OperationsStore()


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/integrations/whatsapp/status")
def whatsapp_integration_status() -> dict[str, object]:
    return {
        "webhook_url": "/webhooks/whatsapp",
        "verify_token_configured": bool(os.getenv("WHATSAPP_VERIFY_TOKEN")),
        "app_secret_configured": bool(os.getenv("WHATSAPP_APP_SECRET")),
        "access_token_configured": bool(os.getenv("WHATSAPP_ACCESS_TOKEN")),
        "phone_number_id_configured": bool(os.getenv("WHATSAPP_PHONE_NUMBER_ID")),
        "onboarding_autoreply_enabled": os.getenv(
            "WHATSAPP_ONBOARDING_AUTOREPLY", "false"
        ).casefold() == "true",
    }


@app.post("/drivers", response_model=Driver, status_code=201)
def create_driver(driver: Driver) -> Driver:
    existing_driver = operations_store.find_driver_by_phone(driver.phone)
    if existing_driver:
        raise HTTPException(status_code=409, detail="A driver with this phone already exists")
    return operations_store.add_driver(driver)


@app.get("/drivers", response_model=list[Driver])
def list_drivers() -> list[Driver]:
    return list(operations_store.drivers.values())


@app.post("/loads", response_model=Load, status_code=201)
def create_load(load: Load) -> Load:
    return operations_store.add_load(load)


@app.get("/loads", response_model=list[Load])
def list_registered_loads() -> list[Load]:
    return list(operations_store.loads.values())


@app.post("/proposals", response_model=LoadProposal, status_code=201)
def create_load_proposal(request: ProposalRequest) -> LoadProposal:
    driver = operations_store.drivers.get(request.driver_id)
    if driver is None:
        raise HTTPException(status_code=404, detail="Driver not found")
    if request.load_id not in operations_store.loads:
        raise HTTPException(status_code=404, detail="Load not found")
    if request.send_whatsapp:
        try:
            send_whatsapp_text_message(driver.phone, request.message)
        except WhatsAppSendError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
    return operations_store.add_proposal(
        LoadProposal(
            load_id=request.load_id,
            driver_id=request.driver_id,
            message=request.message,
        )
    )


@app.get("/proposals", response_model=list[LoadProposal])
def list_load_proposals() -> list[LoadProposal]:
    return operations_store.list_proposals()


@app.post("/proposals/{proposal_id}/respond", response_model=LoadProposal)
def respond_to_load_proposal(
    proposal_id: str, request: ProposalResponseRequest
) -> LoadProposal:
    if request.status not in {ProposalStatus.ACCEPTED, ProposalStatus.REJECTED}:
        raise HTTPException(
            status_code=400,
            detail="Proposal response must be accepted or rejected",
        )
    proposal = operations_store.respond_to_proposal(proposal_id, request.status)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if request.status == ProposalStatus.ACCEPTED:
        operations_store.ensure_booking_case(proposal)
    return proposal


@app.get("/booking-cases", response_model=list[BookingCase])
def list_booking_cases() -> list[BookingCase]:
    return operations_store.list_booking_cases()


@app.post("/booking-cases/{case_id}/trulos-order", response_model=BookingCase)
def mark_case_ordered(case_id: str, request: TrulosOrderRequest) -> BookingCase:
    case = operations_store.booking_cases.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Booking case not found")
    if case.status == BookingCaseStatus.COMPLETED:
        raise HTTPException(status_code=409, detail="Completed case cannot be reordered")
    return operations_store.mark_booking_case_ordered(
        case_id, request.external_order_id
    )


@app.post("/booking-cases/{case_id}/status", response_model=BookingCase)
def update_case_status(
    case_id: str, request: BookingCaseStatusRequest
) -> BookingCase:
    case = operations_store.booking_cases.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Booking case not found")
    if (
        request.status == BookingCaseStatus.ORDERED
        and not (request.external_order_id or case.external_order_id)
    ):
        raise HTTPException(
            status_code=422,
            detail="external_order_id is required when status is ordered",
        )
    updated_case = operations_store.update_booking_case_status(
        case_id, request.status, request.external_order_id
    )
    return updated_case


@app.post("/booking-cases/{case_id}/payments", response_model=PaymentMirror, status_code=201)
def add_payment_mirror(case_id: str, request: PaymentMirrorRequest) -> PaymentMirror:
    if case_id not in operations_store.booking_cases:
        raise HTTPException(status_code=404, detail="Booking case not found")
    return operations_store.add_payment_mirror(
        PaymentMirror(booking_case_id=case_id, **request.model_dump())
    )


@app.get("/booking-cases/{case_id}/payments", response_model=list[PaymentMirror])
def list_payment_mirrors(case_id: str) -> list[PaymentMirror]:
    if case_id not in operations_store.booking_cases:
        raise HTTPException(status_code=404, detail="Booking case not found")
    return operations_store.payments_for_case(case_id)


@app.get("/payments", response_model=list[PaymentMirror])
def list_all_payment_mirrors() -> list[PaymentMirror]:
    return list(operations_store.payment_mirrors.values())


@app.post("/drivers/{driver_id}/documents", response_model=DriverDocument, status_code=201)
def add_driver_document(driver_id: str, document: DriverDocument) -> DriverDocument:
    if driver_id not in operations_store.drivers:
        raise HTTPException(status_code=404, detail="Driver not found")
    if document.driver_id != driver_id:
        raise HTTPException(status_code=400, detail="document.driver_id does not match the URL")
    return operations_store.add_document(document)


@app.get("/drivers/{driver_id}/documents", response_model=list[DriverDocument])
def list_driver_documents(driver_id: str) -> list[DriverDocument]:
    if driver_id not in operations_store.drivers:
        raise HTTPException(status_code=404, detail="Driver not found")
    return operations_store.documents_for_driver(driver_id)


@app.get("/drivers/{driver_id}/missing-documents", response_model=list[str])
def list_missing_driver_documents(driver_id: str) -> list[str]:
    if driver_id not in operations_store.drivers:
        raise HTTPException(status_code=404, detail="Driver not found")
    received = {document.document_type.value for document in operations_store.documents_for_driver(driver_id)}
    required = {"mc", "dot", "insurance", "w9", "carrier_packet"}
    return sorted(required - received)


@app.post("/loads/{load_id}/evidence", response_model=EvidenceEvent, status_code=201)
def add_load_evidence(load_id: str, event: EvidenceEvent) -> EvidenceEvent:
    if event.load_id != load_id:
        raise HTTPException(status_code=400, detail="event.load_id does not match the URL")
    return operations_store.add_evidence(event)


@app.get("/loads/{load_id}/evidence", response_model=list[EvidenceEvent])
def list_load_evidence(load_id: str) -> list[EvidenceEvent]:
    return operations_store.evidence_for_load(load_id)


@app.post("/loads/{load_id}/evidence/email", response_model=EvidenceEvent, status_code=201)
def add_email_evidence(load_id: str, request: EmailEvidenceRequest) -> EvidenceEvent:
    event = EvidenceEvent(
        load_id=load_id,
        evidence_type=EvidenceType.EMAIL,
        description=request.body,
        source=str(request.sender),
        document_url=request.document_url,
        metadata={
            "subject": request.subject,
            "recipients": ", ".join(str(recipient) for recipient in request.recipients),
        },
    )
    return operations_store.add_evidence(event)


@app.post("/brokers", response_model=Broker, status_code=201)
def create_broker(broker: Broker) -> Broker:
    return operations_store.add_broker(broker)


@app.get("/brokers", response_model=list[Broker])
def list_brokers() -> list[Broker]:
    return list(operations_store.brokers.values())


@app.post("/contracts", response_model=Contract, status_code=201)
def create_contract(contract: Contract) -> Contract:
    return operations_store.add_contract(contract)


@app.get("/contracts/renewals", response_model=list[Contract])
def list_contract_renewals(days: int = Query(default=30, ge=0, le=365)) -> list[Contract]:
    cutoff = date.today() + timedelta(days=days)
    return [
        contract
        for contract in operations_store.contracts.values()
        if contract.renewal_date is not None
        and contract.renewal_date <= cutoff
        and contract.status not in {ContractStatus.CANCELLED, ContractStatus.EXPIRED}
    ]


@app.post("/contracts/{contract_id}/accept", response_model=Contract)
def accept_contract(contract_id: str) -> Contract:
    contract = operations_store.contracts.get(contract_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    if contract.status in {ContractStatus.CANCELLED, ContractStatus.EXPIRED}:
        raise HTTPException(status_code=409, detail="Contract cannot be accepted in its current state")
    accepted_contract = contract.model_copy(
        update={"status": ContractStatus.ACCEPTED, "signed_at": utc_now()}
    )
    operations_store.contracts[contract_id] = accepted_contract
    return accepted_contract


@app.post("/commissions", response_model=Commission, status_code=201)
def create_commission(commission: Commission) -> Commission:
    return operations_store.add_commission(commission)


@app.get("/commissions", response_model=list[Commission])
def list_commissions(status: CommissionStatus | None = None) -> list[Commission]:
    return operations_store.commissions_by_status(status.value if status else None)


@app.get("/messages", response_model=list[Message])
def list_messages(sender: str | None = None) -> list[Message]:
    return operations_store.list_messages(sender)


@app.get("/dashboard/summary", response_model=DashboardSummary)
def dashboard_summary() -> DashboardSummary:
    required_documents = set(DocumentType)
    missing_documents = sum(
        len(required_documents - {
            document.document_type
            for document in operations_store.documents_for_driver(driver.id)
            if document.verified
        })
        for driver in operations_store.drivers.values()
    )
    active_load_statuses = {
        LoadStatus.AVAILABLE,
        LoadStatus.MATCHED,
        LoadStatus.BOOKED,
        LoadStatus.IN_TRANSIT,
    }
    recent_messages = sorted(
        operations_store.list_messages(),
        key=lambda message: message.received_at,
        reverse=True,
    )[:10]
    return DashboardSummary(
        active_drivers=sum(
            driver.status == DriverStatus.ACTIVE
            for driver in operations_store.drivers.values()
        ),
        active_loads=sum(
            load.status in active_load_statuses
            for load in operations_store.loads.values()
        ),
        revenue=sum(
            commission.amount for commission in operations_store.commissions.values()
        ),
        payments_collected=sum(
            payment.amount
            for payment in operations_store.payment_mirrors.values()
            if payment.status in {PaymentStatus.PAID, PaymentStatus.COMPLETED}
        ),
        pending_payments=sum(
            payment.status in {PaymentStatus.PENDING, PaymentStatus.PROCESSING}
            for payment in operations_store.payment_mirrors.values()
        ),
        pending_commissions=sum(
            commission.status == CommissionStatus.PENDING
            for commission in operations_store.commissions.values()
        ),
        pending_contracts=sum(
            contract.status in {ContractStatus.DRAFT, ContractStatus.SENT}
            for contract in operations_store.contracts.values()
        ),
        missing_documents=missing_documents,
        recent_messages=recent_messages,
    )


@app.get("/onboarding/{phone}", response_model=OnboardingCase)
def get_onboarding_case(phone: str) -> OnboardingCase:
    onboarding_case = operations_store.onboarding_cases.get(phone)
    if onboarding_case is None:
        raise HTTPException(status_code=404, detail="Onboarding case not found")
    return onboarding_case


@app.get("/onboarding/{phone}/message")
def get_onboarding_message(phone: str) -> dict[str, str]:
    onboarding_case = operations_store.onboarding_cases.get(phone)
    if onboarding_case is None:
        raise HTTPException(status_code=404, detail="Onboarding case not found")
    return {"phone": phone, "message": build_onboarding_message(onboarding_case)}


@app.post("/onboarding/{phone}/documents", response_model=OnboardingCase)
def add_onboarding_document(phone: str, document: OnboardingDocument) -> OnboardingCase:
    try:
        return operations_store.add_onboarding_document(phone, document)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Onboarding case not found") from error


@app.post("/onboarding/{phone}/complete", response_model=Driver)
def complete_onboarding(phone: str, request: OnboardingCompletionRequest) -> Driver:
    try:
        return operations_store.complete_onboarding(
            phone, request.name, request.equipment_types
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Onboarding case not found") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/matching/carriers", response_model=list[CarrierMatch])
def match_carriers(request: MatchingRequest) -> list[CarrierMatch]:
    return rank_carriers_for_load(request.load, request.carriers)


@app.post("/loads/search", response_model=list[Load])
def search_loads(request: LoadSearchRequest) -> list[Load]:
    criteria = LoadSearchCriteria(**request.model_dump())
    return load_sources.search(criteria)


@app.post("/assistant/search")
def search_from_message(request: dict[str, str]) -> dict[str, object]:
    message = request.get("message", "")
    criteria = parse_load_request(message)
    return {
        "message": message,
        "criteria": criteria.__dict__,
        "loads": load_sources.search(criteria),
    }


@app.get("/webhooks/whatsapp")
def verify_whatsapp_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> PlainTextResponse:
    expected_token = os.getenv("WHATSAPP_VERIFY_TOKEN")
    if hub_mode != "subscribe" or not expected_token or verify_token != expected_token:
        raise HTTPException(status_code=403, detail="Webhook verification failed")
    return PlainTextResponse(challenge or "")


@app.post("/webhooks/whatsapp")
async def receive_whatsapp_webhook(request: Request) -> dict[str, int | str]:
    raw_body = await request.body()
    app_secret = os.getenv("WHATSAPP_APP_SECRET")
    signature = request.headers.get("X-Hub-Signature-256", "")
    if app_secret:
        expected_signature = "sha256=" + hmac.new(
            app_secret.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            raise HTTPException(status_code=403, detail="Invalid webhook signature")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from error

    messages = extract_text_messages(payload)
    incoming_whatsapp_messages.extend(messages)

    for message in messages:
        criteria = parse_load_request(message.text)
        driver = operations_store.find_driver_by_phone(message.sender)
        if driver is None:
            onboarding_case = operations_store.start_onboarding(message.sender, message.text)
            if os.getenv("WHATSAPP_ONBOARDING_AUTOREPLY", "false").casefold() == "true":
                try:
                    send_whatsapp_text_message(
                        message.sender, build_onboarding_message(onboarding_case)
                    )
                except WhatsAppSendError:
                    logger.exception("No se pudo enviar el mensaje de onboarding")
        message_id = message.message_id or hashlib.sha256(
            f"{message.sender}:{message.text}".encode()
        ).hexdigest()[:24]
        operations_store.add_message(
            Message(
                id=message_id,
                sender=message.sender,
                text=message.text,
                driver_id=driver.id if driver else None,
                intent="load_search" if any(vars(criteria).values()) else None,
            )
        )
        normalized_text = message.text.strip().casefold()
        if normalized_text == "aprobar":
            approval_store.resolve_latest_pending_for_phone(
                message.sender, ApprovalStatus.APPROVED
            )
        elif normalized_text == "rechazar":
            approval_store.resolve_latest_pending_for_phone(
                message.sender, ApprovalStatus.REJECTED
            )
        elif normalized_text in {"acepto", "aceptar", "accept"} and driver:
            proposal = operations_store.latest_proposal_for_driver(driver.id)
            if proposal:
                accepted_proposal = operations_store.respond_to_proposal(
                    proposal.id, ProposalStatus.ACCEPTED
                )
                if accepted_proposal:
                    operations_store.ensure_booking_case(accepted_proposal)
        elif normalized_text in {"rechazo", "reject"} and driver:
            proposal = operations_store.latest_proposal_for_driver(driver.id)
            if proposal:
                operations_store.respond_to_proposal(
                    proposal.id, ProposalStatus.REJECTED
                )

    return {"status": "received", "messages": len(messages)}


def _resolve_approver_phone(approver_phone: str | None) -> str:
    resolved = approver_phone or os.getenv("WHATSAPP_APPROVAL_RECIPIENT")
    if not resolved:
        raise HTTPException(
            status_code=400,
            detail="approver_phone no se recibió y WHATSAPP_APPROVAL_RECIPIENT no está configurado",
        )
    return resolved


def _evaluate_and_notify(
    load: Load,
    distance_miles: Decimal,
    diesel_price_per_gallon: Decimal,
    approver_phone: str,
) -> dict[str, object]:
    """Evalúa rentabilidad y, si conviene, crea la aprobación y avisa por WhatsApp."""
    try:
        assessment = evaluate_load_profitability(load, distance_miles, diesel_price_per_gallon)
    except ValueError as error:
        return {"load_id": load.id, "status": "skipped", "detail": str(error)}

    if not assessment.is_profitable:
        return {"load_id": load.id, "status": "not_profitable", "assessment": assessment.__dict__}

    approval = approval_store.create(load, assessment, approver_phone)
    message_text = (
        f"Carga rentable detectada ({load.origin.city} -> {load.destination.city}).\n"
        f"Tarifa: ${assessment.offered_rate} | Costo diésel estimado: ${assessment.estimated_fuel_cost:.2f}\n"
        f"Margen estimado: ${assessment.estimated_margin:.2f} (${assessment.rate_per_mile:.2f}/milla)\n"
        "Responde APROBAR para confirmar o RECHAZAR para descartar."
    )
    try:
        send_whatsapp_text_message(approver_phone, message_text)
    except WhatsAppSendError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    return {"load_id": load.id, "status": "pending_approval", "approval_id": approval.id}


@app.post("/approvals/request", status_code=201)
def request_load_approval(request: ApprovalRequest) -> dict[str, object]:
    """Evalúa la rentabilidad de una carga y, si conviene, pide aprobación por WhatsApp."""
    approver_phone = _resolve_approver_phone(request.approver_phone)
    result = _evaluate_and_notify(
        request.load, request.distance_miles, request.diesel_price_per_gallon, approver_phone
    )
    if result["status"] == "skipped":
        raise HTTPException(status_code=400, detail=result["detail"])
    return result


@app.post("/loads/scan")
def scan_loads_for_approval(request: LoadScanRequest) -> dict[str, object]:
    """Busca cargas en las fuentes conectadas y dispara aprobaciones automáticamente
    para las que resulten rentables (conecta /loads/search con /approvals/request).
    """
    approver_phone = _resolve_approver_phone(request.approver_phone)
    criteria = LoadSearchCriteria(**request.search.model_dump())
    loads = load_sources.search(criteria)

    results = [
        _evaluate_and_notify(
            load, request.distance_miles, request.diesel_price_per_gallon, approver_phone
        )
        for load in loads
    ]
    return {"scanned": len(loads), "results": results}


logger = logging.getLogger(__name__)

# Scan periódico desactivado por defecto: se activa solo si se configuran las
# variables de entorno necesarias (intervalo, distancia, precio de diésel y
# destinatario de la aprobación). El resto de los filtros de búsqueda son
# opcionales, igual que en /loads/scan.
async def _run_periodic_load_scan() -> None:
    interval_raw = os.getenv("LOADS_SCAN_INTERVAL_SECONDS", "")
    if not interval_raw:
        return
    try:
        interval = float(interval_raw)
    except ValueError:
        logger.warning("LOADS_SCAN_INTERVAL_SECONDS inválido; scan periódico desactivado")
        return
    if interval <= 0:
        return

    try:
        distance_miles = Decimal(os.getenv("LOADS_SCAN_DISTANCE_MILES", ""))
        diesel_price_per_gallon = Decimal(os.getenv("LOADS_SCAN_DIESEL_PRICE_PER_GALLON", ""))
    except InvalidOperation:
        logger.warning(
            "LOADS_SCAN_DISTANCE_MILES/LOADS_SCAN_DIESEL_PRICE_PER_GALLON no configuradas; "
            "scan periódico desactivado"
        )
        return

    try:
        approver_phone = _resolve_approver_phone(None)
    except HTTPException:
        logger.warning("WHATSAPP_APPROVAL_RECIPIENT no configurado; scan periódico desactivado")
        return

    minimum_rate_raw = os.getenv("LOADS_SCAN_MINIMUM_RATE")
    criteria = LoadSearchCriteria(
        origin_city=os.getenv("LOADS_SCAN_ORIGIN_CITY") or None,
        origin_state=os.getenv("LOADS_SCAN_ORIGIN_STATE") or None,
        equipment_type=os.getenv("LOADS_SCAN_EQUIPMENT_TYPE") or None,
        minimum_rate=float(minimum_rate_raw) if minimum_rate_raw else None,
    )

    logger.info("Scan periódico de cargas activado cada %s segundos", interval)
    while True:
        try:
            loads = load_sources.search(criteria)
            for load in loads:
                _evaluate_and_notify(load, distance_miles, diesel_price_per_gallon, approver_phone)
        except Exception:  # el loop no debe morir por un fallo puntual de una fuente
            logger.exception("Error en el scan periódico de cargas")
        await asyncio.sleep(interval)


@app.get("/approvals")
def list_approvals() -> list[dict[str, object]]:
    return [
        {
            "id": approval.id,
            "load_id": approval.load.id,
            "status": approval.status,
            "created_at": approval.created_at.isoformat(),
            "resolved_at": approval.resolved_at.isoformat() if approval.resolved_at else None,
        }
        for approval in approval_store.list()
    ]


@app.post("/contact", status_code=201)
def create_contact_request(request: ContactRequest) -> dict[str, str]:
    contact_requests.append(request)
    return {"status": "received", "message": "Contact request received"}