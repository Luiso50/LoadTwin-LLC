from src.database.models import (
    Broker,
    BookingCase,
    BookingCaseStatus,
    Commission,
    Contract,
    DocumentType,
    Driver,
    DriverDocument,
    DriverStatus,
    EvidenceEvent,
    Load,
    LoadProposal,
    ProposalStatus,
    Message,
    OnboardingCase,
    OnboardingDocument,
    OnboardingStatus,
    PaymentMirror,
    utc_now,
)


class OperationsStore:
    """Adaptador temporal en memoria para validar los contratos de la fase 1."""

    def __init__(self) -> None:
        self.drivers: dict[str, Driver] = {}
        self.documents: dict[str, DriverDocument] = {}
        self.evidence: dict[str, EvidenceEvent] = {}
        self.brokers: dict[str, Broker] = {}
        self.contracts: dict[str, Contract] = {}
        self.commissions: dict[str, Commission] = {}
        self.messages: dict[str, Message] = {}
        self.onboarding_cases: dict[str, OnboardingCase] = {}
        self.loads: dict[str, Load] = {}
        self.proposals: dict[str, LoadProposal] = {}
        self.booking_cases: dict[str, BookingCase] = {}
        self.payment_mirrors: dict[str, PaymentMirror] = {}

    def add_driver(self, driver: Driver) -> Driver:
        self.drivers[driver.id] = driver
        return driver

    def find_driver_by_phone(self, phone: str) -> Driver | None:
        return next((driver for driver in self.drivers.values() if driver.phone == phone), None)

    def add_document(self, document: DriverDocument) -> DriverDocument:
        self.documents[document.id] = document
        return document

    def documents_for_driver(self, driver_id: str) -> list[DriverDocument]:
        return [document for document in self.documents.values() if document.driver_id == driver_id]

    def add_evidence(self, event: EvidenceEvent) -> EvidenceEvent:
        self.evidence[event.id] = event
        return event

    def evidence_for_load(self, load_id: str) -> list[EvidenceEvent]:
        return [event for event in self.evidence.values() if event.load_id == load_id]

    def add_broker(self, broker: Broker) -> Broker:
        self.brokers[broker.id] = broker
        return broker

    def add_contract(self, contract: Contract) -> Contract:
        self.contracts[contract.id] = contract
        return contract

    def add_commission(self, commission: Commission) -> Commission:
        self.commissions[commission.id] = commission
        return commission

    def commissions_by_status(self, status: str | None = None) -> list[Commission]:
        if status is None:
            return list(self.commissions.values())
        return [commission for commission in self.commissions.values() if commission.status == status]

    def add_message(self, message: Message) -> Message:
        existing_message = self.messages.get(message.id)
        if existing_message:
            return existing_message
        self.messages[message.id] = message
        return message

    def list_messages(self, sender: str | None = None) -> list[Message]:
        messages = list(self.messages.values())
        if sender is not None:
            messages = [message for message in messages if message.sender == sender]
        return messages

    def start_onboarding(self, phone: str, message: str) -> OnboardingCase:
        existing_case = self.onboarding_cases.get(phone)
        if existing_case:
            updated_case = existing_case.model_copy(
                update={"last_message": message, "updated_at": utc_now()}
            )
            self.onboarding_cases[phone] = updated_case
            return updated_case
        case = OnboardingCase(phone=phone, last_message=message)
        self.onboarding_cases[phone] = case
        return case

    def add_onboarding_document(
        self, phone: str, document: OnboardingDocument
    ) -> OnboardingCase:
        case = self.onboarding_cases.get(phone)
        if case is None:
            raise KeyError(phone)
        documents = [
            existing
            for existing in case.documents
            if existing.document_type != document.document_type
        ]
        documents.append(document)
        verified_documents = list(case.verified_documents)
        if document.verified and document.document_type not in verified_documents:
            verified_documents.append(document.document_type)
        if not document.verified:
            verified_documents = [
                item for item in verified_documents if item != document.document_type
            ]
        updated_case = case.model_copy(
            update={
                "documents": documents,
                "verified_documents": verified_documents,
                "updated_at": utc_now(),
            }
        )
        self.onboarding_cases[phone] = updated_case
        return updated_case

    def complete_onboarding(
        self, phone: str, name: str, equipment_types: list[str]
    ) -> Driver:
        case = self.onboarding_cases.get(phone)
        if case is None:
            raise KeyError(phone)
        required = set(case.required_documents)
        verified = set(case.verified_documents)
        if required - verified:
            raise ValueError("All required documents must be verified")
        if self.find_driver_by_phone(phone):
            raise ValueError("A driver with this phone already exists")

        driver = Driver(
            name=name,
            phone=phone,
            equipment_types=equipment_types,
            status=DriverStatus.ACTIVE,
        )
        self.add_driver(driver)
        for document in case.documents:
            self.add_document(
                DriverDocument(
                    driver_id=driver.id,
                    document_type=document.document_type,
                    document_url=document.document_url,
                    expires_at=document.expires_at,
                    verified=document.verified,
                )
            )
        self.onboarding_cases[phone] = case.model_copy(
            update={
                "status": OnboardingStatus.COMPLETED,
                "driver_id": driver.id,
                "name": name,
                "equipment_types": equipment_types,
                "updated_at": utc_now(),
            }
        )
        return driver

    def add_load(self, load: Load) -> Load:
        self.loads[load.id] = load
        return load

    def add_proposal(self, proposal: LoadProposal) -> LoadProposal:
        self.proposals[proposal.id] = proposal
        return proposal

    def list_proposals(self) -> list[LoadProposal]:
        return list(self.proposals.values())
    
    def latest_proposal_for_driver(self, driver_id: str) -> LoadProposal | None:
        proposals = [
            proposal
            for proposal in self.proposals.values()
            if proposal.driver_id == driver_id and proposal.status == ProposalStatus.SENT
        ]
        return max(proposals, key=lambda proposal: proposal.created_at) if proposals else None

    def respond_to_proposal(
        self, proposal_id: str, status: ProposalStatus
    ) -> LoadProposal | None:
        proposal = self.proposals.get(proposal_id)
        if proposal is None:
            return None
        updated_proposal = proposal.model_copy(
            update={
                "status": status,
                "responded_at": utc_now(),
            }
        )
        self.proposals[proposal_id] = updated_proposal
        return updated_proposal

    def add_booking_case(self, case: BookingCase) -> BookingCase:
        self.booking_cases[case.id] = case
        return case

    def booking_case_for(self, load_id: str, driver_id: str) -> BookingCase | None:
        return next(
            (
                case
                for case in self.booking_cases.values()
                if case.load_id == load_id and case.driver_id == driver_id
            ),
            None,
        )

    def list_booking_cases(self) -> list[BookingCase]:
        return list(self.booking_cases.values())

    def ensure_booking_case(self, proposal: LoadProposal) -> BookingCase | None:
        existing_case = self.booking_case_for(proposal.load_id, proposal.driver_id)
        if existing_case:
            return existing_case
        load = self.loads.get(proposal.load_id)
        if load is None:
            return None
        return self.add_booking_case(
            BookingCase(
                load_id=proposal.load_id,
                driver_id=proposal.driver_id,
                agreed_rate=load.offered_rate,
            )
        )

    def mark_booking_case_ordered(
        self, case_id: str, external_order_id: str
    ) -> BookingCase | None:
        case = self.booking_cases.get(case_id)
        if case is None:
            return None
        updated_case = case.model_copy(
            update={
                "status": BookingCaseStatus.ORDERED,
                "external_order_id": external_order_id,
            }
        )
        self.booking_cases[case_id] = updated_case
        return updated_case

    def update_booking_case_status(
        self,
        case_id: str,
        status: BookingCaseStatus,
        external_order_id: str | None = None,
    ) -> BookingCase | None:
        case = self.booking_cases.get(case_id)
        if case is None:
            return None
        updated_case = case.model_copy(
            update={
                "status": status,
                "external_order_id": external_order_id or case.external_order_id,
            }
        )
        self.booking_cases[case_id] = updated_case
        return updated_case

    def add_payment_mirror(self, payment: PaymentMirror) -> PaymentMirror:
        existing_payment = next(
            (
                existing
                for existing in self.payment_mirrors.values()
                if existing.booking_case_id == payment.booking_case_id
                and existing.external_reference == payment.external_reference
            ),
            None,
        )
        if existing_payment:
            return existing_payment
        self.payment_mirrors[payment.id] = payment
        return payment

    def payments_for_case(self, booking_case_id: str) -> list[PaymentMirror]:
        return [
            payment
            for payment in self.payment_mirrors.values()
            if payment.booking_case_id == booking_case_id
        ]