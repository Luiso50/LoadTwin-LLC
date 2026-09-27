from src.database.models import DocumentType, OnboardingCase


DOCUMENT_LABELS = {
    DocumentType.MC: "MC Authority",
    DocumentType.DOT: "DOT record",
    DocumentType.INSURANCE: "Insurance certificate",
    DocumentType.W9: "W-9",
    DocumentType.CARRIER_PACKET: "Carrier packet",
}


def missing_onboarding_documents(case: OnboardingCase) -> list[DocumentType]:
    verified = set(case.verified_documents)
    return [document for document in case.required_documents if document not in verified]


def build_onboarding_message(case: OnboardingCase) -> str:
    missing = missing_onboarding_documents(case)
    if not missing:
        return "Your documents are complete. We are ready to activate your driver profile."

    document_list = "\n".join(
        f"- {DOCUMENT_LABELS[document]}" for document in missing
    )
    return (
        "Welcome to LoadTwin LLC. To complete your carrier onboarding, "
        "please send the following documents:\n"
        f"{document_list}\n"
        "Reply with one document at a time. Our team will verify each item."
    )