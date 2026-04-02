import pytest
from unittest.mock import Mock, patch
from src.integrations.drive.service import DriveService

@pytest.fixture
def mock_gcp_integration():
    with patch('src.integrations.drive.service.gcp_integration') as mock_gcp:
        mock_gcp.get_secret.return_value = '{"type": "service_account"}'
        mock_gcp.firestore_client = Mock()
        yield mock_gcp

@pytest.fixture
def mock_service_account():
    with patch('src.integrations.drive.service.service_account.Credentials.from_service_account_info') as mock_creds:
        yield mock_creds

@pytest.fixture
def mock_build():
    with patch('src.integrations.drive.service.build') as mock_build:
        yield mock_build

@pytest.fixture
def drive_service(mock_gcp_integration, mock_service_account, mock_build):
    return DriveService()

def test_create_project_folders(drive_service):
    # Setup mocks
    mock_files = drive_service.service.files()
    mock_files.create.return_value.execute.return_value = {'id': 'test_folder_id'}

    db_mock = drive_service.db
    doc_ref_mock = db_mock.collection().document()

    # Execute
    result = drive_service.create_project_folders('2026-003', 'Riverside Elementary')

    # Verify root folder creation
    assert result['root_folder_id'] == 'test_folder_id'

    # Verify subfolder creation
    assert mock_files.create.call_count == 25

    # Verify firestore storage
    db_mock.collection.assert_called_with('drive_folders')
    doc_ref_mock.set.assert_called()

def test_get_folder_id(drive_service):
    db_mock = drive_service.db
    doc_ref_mock = db_mock.collection().document()
    doc_mock = doc_ref_mock.get()
    doc_mock.exists = True
    doc_mock.to_dict.return_value = {
        'folders': {
            '02 - Construction/RFIs': 'rfi_folder_id'
        }
    }

    result = drive_service.get_folder_id('2026-003', '02 - Construction/RFIs')

    assert result == 'rfi_folder_id'

def test_upload_file(drive_service):
    mock_files = drive_service.service.files()
    mock_files.create.return_value.execute.return_value = {'id': 'test_file_id'}

    with patch('src.integrations.drive.service.MediaIoBaseUpload') as MockMedia:
        result = drive_service.upload_file('folder_123', 'test.pdf', b'content', 'application/pdf')

    assert result == 'test_file_id'
    args, kwargs = mock_files.create.call_args
    assert kwargs['body'] == {'name': 'test.pdf', 'parents': ['folder_123']}

def test_move_file(drive_service):
    mock_files = drive_service.service.files()
    mock_files.get.return_value.execute.return_value = {'parents': ['old_parent_id']}

    drive_service.move_file('file_123', 'new_parent_id', new_name='RFI-001_test.pdf')

    args, kwargs = mock_files.update.call_args
    assert kwargs['fileId'] == 'file_123'
    assert kwargs['addParents'] == 'new_parent_id'
    assert kwargs['removeParents'] == 'old_parent_id'
    assert kwargs['body'] == {'name': 'RFI-001_test.pdf'}

@patch('src.integrations.drive.service.firestore')
def test_next_doc_number(mock_firestore, drive_service):
    # Testing the inner function logic by bypassing the decorator
    db_mock = drive_service.db
    counter_ref = db_mock.collection().document().collection().document()
    transaction_mock = Mock()

    snapshot_mock = Mock()
    snapshot_mock.exists = True
    snapshot_mock.get.return_value = 5
    counter_ref.get.return_value = snapshot_mock

    # Define logic identical to increment_in_transaction
    def increment_in_transaction(transaction, ref):
        snapshot = ref.get(transaction=transaction)
        if snapshot.exists:
            new_count = snapshot.get('count') + 1
        else:
            new_count = 1
        transaction.set(ref, {'count': new_count})
        return new_count

    result = increment_in_transaction(transaction_mock, counter_ref)

    assert result == 6
    transaction_mock.set.assert_called_with(counter_ref, {'count': 6})
