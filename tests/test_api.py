from fastapi.testclient import TestClient

from src.api.main import app


client = TestClient(app)


def test_health_check():
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}


def test_whatsapp_status_does_not_expose_secrets(monkeypatch):
    monkeypatch.setenv('WHATSAPP_VERIFY_TOKEN', 'hidden-token')
    monkeypatch.setenv('WHATSAPP_PHONE_NUMBER_ID', 'phone-id')

    response = client.get('/integrations/whatsapp/status')

    assert response.status_code == 200
    assert response.json()['verify_token_configured'] is True
    assert response.json()['phone_number_id_configured'] is True
    assert 'hidden-token' not in response.text
    assert 'phone-id' not in response.text


def test_driver_onboarding_reports_missing_documents():
    response = client.post('/drivers', json={
        'name': 'Luis Perez',
        'phone': '+17860000001',
        'equipment_types': ['Flatbed'],
    })

    assert response.status_code == 201
    driver_id = response.json()['id']
    missing = client.get(f'/drivers/{driver_id}/missing-documents')

    assert missing.status_code == 200
    assert missing.json() == ['carrier_packet', 'dot', 'insurance', 'mc', 'w9']


def test_driver_document_is_removed_from_missing_documents():
    driver = client.post('/drivers', json={
        'name': 'Ana Torres',
        'phone': '+17860000002',
    }).json()

    response = client.post(f"/drivers/{driver['id']}/documents", json={
        'driver_id': driver['id'],
        'document_type': 'w9',
        'verified': True,
    })

    assert response.status_code == 201
    assert 'w9' not in client.get(f"/drivers/{driver['id']}/missing-documents").json()


def test_load_evidence_can_be_reconstructed():
    response = client.post('/loads/L-9001/evidence', json={
        'load_id': 'L-9001',
        'evidence_type': 'whatsapp',
        'description': 'Driver accepted the rate confirmation',
        'source': '+17860000001',
    })

    assert response.status_code == 201
    evidence = client.get('/loads/L-9001/evidence')
    assert evidence.status_code == 200
    assert evidence.json()[0]['description'] == 'Driver accepted the rate confirmation'


def test_email_evidence_preserves_legal_metadata():
    response = client.post('/loads/L-9001/evidence/email', json={
        'sender': 'broker@example.com',
        'recipients': ['dispatch@loadtwinllc.com'],
        'subject': 'Rate confirmation L-9001',
        'body': 'Please find the signed rate confirmation attached.',
        'document_url': 'https://files.example.test/rate-confirmation.pdf',
    })

    assert response.status_code == 201
    event = response.json()
    assert event['evidence_type'] == 'email'
    assert event['metadata']['subject'] == 'Rate confirmation L-9001'
    assert event['document_url'].endswith('rate-confirmation.pdf')


def test_whatsapp_message_is_persisted_once_and_linked_to_driver():
    driver = client.post('/drivers', json={
        'name': 'Message Driver',
        'phone': '+17860000003',
    }).json()
    payload = {
        'entry': [{'changes': [{'value': {'messages': [{
            'id': 'wamid.idempotent',
            'from': driver['phone'],
            'text': {'body': 'Empty in Houston, Flatbed'},
        }]}}]}]
    }

    first = client.post('/webhooks/whatsapp', json=payload)
    second = client.post('/webhooks/whatsapp', json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    messages = client.get('/messages', params={'sender': driver['phone']}).json()
    assert len(messages) == 1
    assert messages[0]['driver_id'] == driver['id']
    assert messages[0]['intent'] == 'load_search'


def test_unknown_whatsapp_sender_starts_one_onboarding_case():
    payload = {
        'entry': [{'changes': [{'value': {'messages': [{
            'id': 'wamid.onboarding',
            'from': '+17860000004',
            'text': {'body': 'I am empty in Houston. Flatbed.'},
        }]}}]}]
    }

    client.post('/webhooks/whatsapp', json=payload)
    client.post('/webhooks/whatsapp', json=payload)
    response = client.get('/onboarding/+17860000004')

    assert response.status_code == 200
    assert response.json()['status'] == 'pending'
    assert response.json()['required_documents'] == [
        'mc', 'dot', 'insurance', 'w9', 'carrier_packet'
    ]
    assert response.json()['last_message'] == 'I am empty in Houston. Flatbed.'


def test_onboarding_message_lists_missing_documents():
    phone = '+17860000006'
    client.post('/webhooks/whatsapp', json={
        'entry': [{'changes': [{'value': {'messages': [{
            'id': 'wamid.message-preview',
            'from': phone,
            'text': {'body': 'I want to onboard'},
        }]}}]}]
    })

    response = client.get(f'/onboarding/{phone}/message')

    assert response.status_code == 200
    assert 'MC Authority' in response.json()['message']
    assert 'Carrier packet' in response.json()['message']


def test_onboarding_completes_driver_only_after_all_documents_are_verified():
    phone = '+17860000005'
    client.post('/webhooks/whatsapp', json={
        'entry': [{'changes': [{'value': {'messages': [{
            'id': 'wamid.complete',
            'from': phone,
            'text': {'body': 'Please onboard me'},
        }]}}]}]
    })

    incomplete = client.post(f'/onboarding/{phone}/complete', json={
        'name': 'Complete Driver',
        'equipment_types': ['Flatbed'],
    })
    assert incomplete.status_code == 409

    for document_type in ['mc', 'dot', 'insurance', 'w9', 'carrier_packet']:
        response = client.post(f'/onboarding/{phone}/documents', json={
            'document_type': document_type,
            'document_url': 'https://files.example.test/document.pdf' if document_type == 'insurance' else None,
            'expires_at': '2027-09-24' if document_type == 'insurance' else None,
            'verified': True,
        })
        assert response.status_code == 200

    completed = client.post(f'/onboarding/{phone}/complete', json={
        'name': 'Complete Driver',
        'equipment_types': ['Flatbed'],
    })

    assert completed.status_code == 200
    assert completed.json()['status'] == 'active'
    assert client.get(f'/onboarding/{phone}').json()['status'] == 'completed'
    driver_documents = client.get(f"/drivers/{completed.json()['id']}/documents").json()
    insurance = next(document for document in driver_documents if document['document_type'] == 'insurance')
    assert insurance['document_url'] == 'https://files.example.test/document.pdf'
    assert insurance['expires_at'] == '2027-09-24'


def test_dashboard_summary_reports_operational_metrics():
    client.post('/drivers', json={
        'name': 'Dashboard Driver',
        'phone': '+17860000007',
        'status': 'active',
    })
    client.post('/loads', json={
        'id': 'L-DASH-001',
        'origin': {'city': 'Houston', 'state': 'TX'},
        'destination': {'city': 'Dallas', 'state': 'TX'},
        'equipment_type': 'Flatbed',
        'status': 'available',
    })

    response = client.get('/dashboard/summary')

    assert response.status_code == 200
    summary = response.json()
    assert summary['active_drivers'] >= 1
    assert summary['active_loads'] >= 1
    assert 'pending_commissions' in summary
    assert 'payments_collected' in summary
    assert 'pending_payments' in summary
    assert 'missing_documents' in summary
    assert isinstance(summary['recent_messages'], list)


def test_load_proposal_is_recorded_for_existing_driver_and_load():
    driver = client.post('/drivers', json={
        'name': 'Proposal Driver',
        'phone': '+17860000008',
    }).json()
    client.post('/loads', json={
        'id': 'L-PROPOSAL-001',
        'origin': {'city': 'Miami', 'state': 'FL'},
        'destination': {'city': 'Atlanta', 'state': 'GA'},
        'equipment_type': 'Dry Van',
        'offered_rate': '1800.00',
        'status': 'available',
    })

    response = client.post('/proposals', json={
        'load_id': 'L-PROPOSAL-001',
        'driver_id': driver['id'],
        'message': 'Miami to Atlanta, Dry Van, $1,800. Do you accept?',
    })

    assert response.status_code == 201
    assert response.json()['status'] == 'sent'
    assert client.get('/proposals').json()[0]['driver_id'] == driver['id']


def test_driver_can_accept_proposal_via_response_endpoint():
    driver = client.post('/drivers', json={
        'name': 'Response Driver',
        'phone': '+17860000009',
    }).json()
    client.post('/loads', json={
        'id': 'L-RESPONSE-001',
        'origin': {'city': 'Tampa', 'state': 'FL'},
        'destination': {'city': 'Orlando', 'state': 'FL'},
        'equipment_type': 'Reefer',
        'status': 'available',
    })
    proposal = client.post('/proposals', json={
        'load_id': 'L-RESPONSE-001',
        'driver_id': driver['id'],
        'message': 'Tampa to Orlando, Reefer. Do you accept?',
    }).json()

    response = client.post(f"/proposals/{proposal['id']}/respond", json={
        'status': 'accepted',
    })

    assert response.status_code == 200
    assert response.json()['status'] == 'accepted'
    assert response.json()['responded_at'] is not None
    cases = client.get('/booking-cases')
    assert cases.status_code == 200
    assert cases.json()[0]['status'] == 'driver_accepted'
    assert cases.json()[0]['agreed_rate'] is None


def test_whatsapp_acceptance_creates_booking_case():
    driver = client.post('/drivers', json={
        'name': 'WhatsApp Acceptance Driver',
        'phone': '+17860000011',
    }).json()
    client.post('/loads', json={
        'id': 'L-WA-ACCEPT-001',
        'origin': {'city': 'Miami', 'state': 'FL'},
        'destination': {'city': 'Orlando', 'state': 'FL'},
        'equipment_type': 'Dry Van',
        'offered_rate': '1500.00',
        'status': 'available',
    })
    proposal = client.post('/proposals', json={
        'load_id': 'L-WA-ACCEPT-001',
        'driver_id': driver['id'],
        'message': 'Miami to Orlando. Do you accept?',
    }).json()

    response = client.post('/webhooks/whatsapp', json={
        'entry': [{'changes': [{'value': {'messages': [{
            'id': 'wamid.accept-booking-case',
            'from': driver['phone'],
            'text': {'body': 'ACEPTO'},
        }]}}]}]
    })

    assert response.status_code == 200
    cases = client.get('/booking-cases').json()
    assert any(case['load_id'] == proposal['load_id'] for case in cases)


def test_booking_case_can_record_trulos_order_reference():
    case = client.get('/booking-cases').json()[0]

    response = client.post(f"/booking-cases/{case['id']}/trulos-order", json={
        'external_order_id': 'TRULOS-ORDER-001',
    })

    assert response.status_code == 200
    assert response.json()['status'] == 'ordered'
    assert response.json()['external_order_id'] == 'TRULOS-ORDER-001'


def test_booking_case_status_can_advance_after_trulos_order():
    case = client.get('/booking-cases').json()[0]

    response = client.post(f"/booking-cases/{case['id']}/status", json={
        'status': 'in_transit',
    })

    assert response.status_code == 200
    assert response.json()['status'] == 'in_transit'
    assert response.json()['external_order_id'] == 'TRULOS-ORDER-001'


def test_booking_case_cannot_be_ordered_without_trulos_reference():
    driver = client.post('/drivers', json={
        'name': 'Order Guard Driver',
        'phone': '+17860000010',
    }).json()
    client.post('/loads', json={
        'id': 'L-ORDER-GUARD-001',
        'origin': {'city': 'Orlando', 'state': 'FL'},
        'destination': {'city': 'Jacksonville', 'state': 'FL'},
        'equipment_type': 'Dry Van',
        'status': 'available',
    })
    proposal = client.post('/proposals', json={
        'load_id': 'L-ORDER-GUARD-001',
        'driver_id': driver['id'],
        'message': 'Orlando to Jacksonville. Do you accept?',
    }).json()
    client.post(f"/proposals/{proposal['id']}/respond", json={'status': 'accepted'})
    case = client.get('/booking-cases').json()[-1]

    response = client.post(f"/booking-cases/{case['id']}/status", json={
        'status': 'ordered',
        'external_order_id': None,
    })

    assert response.status_code == 422


def test_trulos_payment_can_be_mirrored_on_booking_case():
    case = client.get('/booking-cases').json()[0]

    response = client.post(f"/booking-cases/{case['id']}/payments", json={
        'external_reference': 'pi_trulos_001',
        'amount': '1800.00',
        'status': 'paid',
        'receipt_url': 'https://files.example.test/receipt.pdf',
    })

    assert response.status_code == 201
    assert response.json()['source'] == 'trulos'
    assert client.get(f"/booking-cases/{case['id']}/payments").json()[0]['status'] == 'paid'
    assert client.get('/payments').json()[0]['external_reference'] == 'pi_trulos_001'
    duplicate = client.post(f"/booking-cases/{case['id']}/payments", json={
        'external_reference': 'pi_trulos_001',
        'amount': '1800.00',
        'status': 'paid',
    })
    assert duplicate.status_code == 201
    assert len(client.get(f"/booking-cases/{case['id']}/payments").json()) == 1


def test_contract_can_be_accepted():
    contract = client.post('/contracts', json={
        'id': 'CON-9001',
        'trip_id': 'TRIP-9001',
        'contract_number': 'FD-2026-001',
        'customer_name': 'Acme Brokerage',
        'carrier_name': 'Luis Perez Trucking',
        'agreed_rate': '2200.00',
    }).json()

    response = client.post(f"/contracts/{contract['id']}/accept")

    assert response.status_code == 200
    assert response.json()['status'] == 'accepted'
    assert response.json()['signed_at'] is not None


def test_contract_renewal_alert_returns_contracts_inside_window():
    client.post('/contracts', json={
        'id': 'CON-RENEWAL-001',
        'trip_id': 'TRIP-RENEWAL-001',
        'contract_number': 'FD-RENEWAL-001',
        'customer_name': 'Renewal Brokerage',
        'carrier_name': 'Renewal Carrier',
        'agreed_rate': '1800.00',
        'renewal_date': '2026-10-01',
    })

    response = client.get('/contracts/renewals', params={'days': 30})

    assert response.status_code == 200
    assert any(contract['id'] == 'CON-RENEWAL-001' for contract in response.json())


def test_commissions_can_be_filtered_by_status():
    client.post('/commissions', json={
        'id': 'COM-9001',
        'load_id': 'L-9001',
        'driver_id': 'DRV-9001',
        'rate': '2200.00',
        'percentage': '10',
        'amount': '220.00',
        'status': 'pending',
    })

    response = client.get('/commissions', params={'status': 'pending'})

    assert response.status_code == 200
    assert response.json()[0]['amount'] == '220.00'


def test_matching_route_returns_compatible_carrier():
    payload = {
        'load': {
            'id': 'L-1001',
            'origin': {'city': 'Miami', 'state': 'FL'},
            'destination': {'city': 'Orlando', 'state': 'FL'},
            'equipment_type': 'Dry Van',
            'status': 'available',
        },
        'carriers': [
            {
                'id': 'C-2001',
                'legal_name': 'Atlas Logistics',
                'equipment_types': ['Dry Van', 'Reefer'],
                'active': True,
            },
            {
                'id': 'C-2002',
                'legal_name': 'Blue Route Transport',
                'equipment_types': ['Flatbed'],
                'active': True,
            },
            {
                'id': 'C-2003',
                'legal_name': 'Inactive Carrier',
                'equipment_types': ['Dry Van'],
                'active': False,
            },
        ],
    }

    response = client.post('/matching/carriers', json=payload)

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]['carrier_id'] == 'C-2001'
    assert data[0]['score'] == 100
    assert 'Compatible equipment: Dry Van' in data[0]['reasons'][0]


def test_contact_request_creates_record():
    payload = {
        'name': 'Ana García',
        'company': 'FreightOps',
        'email': 'ana@freightops.com',
        'need': 'Necesito mover una carga urgente'
    }

    response = client.post('/contact', json=payload)

    assert response.status_code == 201
    assert response.json()['status'] == 'received'


def test_load_search_endpoint_returns_no_results_until_a_source_is_connected():
    response = client.post('/loads/search', json={
        'origin_state': 'FL',
        'equipment_type': 'Dry Van',
    })

    assert response.status_code == 200
    assert response.json() == []


def test_assistant_turns_whatsapp_request_into_search_criteria():
    response = client.post('/assistant/search', json={
        'message': 'Busca un reefer de Miami a Dallas para mañana'
    })

    assert response.status_code == 200
    assert response.json()['criteria'] == {
        'origin_city': 'Miami',
        'origin_state': None,
        'destination_city': 'Dallas',
        'destination_state': None,
        'equipment_type': 'Reefer',
        'pickup_date': None,
        'minimum_rate': None,
    }
    assert response.json()['loads'] == []


def test_whatsapp_webhook_receives_text_message(monkeypatch):
    monkeypatch.setenv('WHATSAPP_VERIFY_TOKEN', 'test-token')
    verification = client.get('/webhooks/whatsapp', params={
        'hub.mode': 'subscribe',
        'hub.verify_token': 'test-token',
        'hub.challenge': 'challenge-123',
    })
    assert verification.status_code == 200
    assert verification.text == 'challenge-123'

    response = client.post('/webhooks/whatsapp', json={
        'entry': [{'changes': [{'value': {'messages': [{
            'id': 'wamid.test',
            'from': '17868365612',
            'text': {'body': 'Busca dry van de Miami a Dallas'},
        }]}}]}]
    })

    assert response.status_code == 200
    assert response.json()['status'] == 'received'


def test_whatsapp_webhook_validates_meta_signature(monkeypatch):
    import hashlib
    import hmac
    import json

    secret = 'app-secret'
    monkeypatch.setenv('WHATSAPP_APP_SECRET', secret)
    payload = {'entry': []}
    raw_body = json.dumps(payload).encode()
    signature = 'sha256=' + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()

    valid = client.post('/webhooks/whatsapp', content=raw_body, headers={
        'X-Hub-Signature-256': signature,
        'Content-Type': 'application/json',
    })
    invalid = client.post('/webhooks/whatsapp', content=raw_body, headers={
        'X-Hub-Signature-256': 'sha256=invalid',
        'Content-Type': 'application/json',
    })

    assert valid.status_code == 200
    assert invalid.status_code == 403
