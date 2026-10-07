"""Almacén en memoria de aprobaciones pendientes (human-in-the-loop).

Igual que `contact_requests` en la API, esto vive en memoria mientras el
proceso está activo. Antes de producción debe persistirse en base de datos
para no perder aprobaciones pendientes si el servicio se reinicia.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4

from src.agent.profitability import ProfitabilityAssessment
from src.database.models import Load


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class PendingApproval:
    id: str
    load: Load
    assessment: ProfitabilityAssessment
    approver_phone: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: datetime | None = None


class ApprovalStore:
    def __init__(self) -> None:
        self._approvals: dict[str, PendingApproval] = {}

    def create(
        self,
        load: Load,
        assessment: ProfitabilityAssessment,
        approver_phone: str,
    ) -> PendingApproval:
        approval = PendingApproval(
            id=str(uuid4()),
            load=load,
            assessment=assessment,
            approver_phone=approver_phone,
        )
        self._approvals[approval.id] = approval
        return approval

    def get(self, approval_id: str) -> PendingApproval | None:
        return self._approvals.get(approval_id)

    def list(self) -> list[PendingApproval]:
        return list(self._approvals.values())

    def resolve_latest_pending_for_phone(
        self, phone: str, status: ApprovalStatus
    ) -> PendingApproval | None:
        """Resuelve la aprobación pendiente más reciente de un remitente.

        Simplificación inicial: asume una aprobación pendiente por número a la
        vez. Si hay varias cargas esperando aprobación del mismo remitente,
        habría que incluir el id de la aprobación en la respuesta de WhatsApp.
        """
        pending = [
            approval
            for approval in self._approvals.values()
            if approval.approver_phone == phone and approval.status == ApprovalStatus.PENDING
        ]
        if not pending:
            return None
        latest = max(pending, key=lambda approval: approval.created_at)
        latest.status = status
        latest.resolved_at = datetime.now(timezone.utc)
        return latest
