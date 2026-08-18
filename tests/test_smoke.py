import pytest


PAGES = [
    '/', '/accounts', '/students', '/courses', '/tutors', '/enquiries',
    '/enquiries/kanban', '/fees', '/expenses', '/attendance', '/leaves',
    '/reports', '/payroll', '/exams', '/exams/mcq/create', '/funding',
    '/tasks', '/admin', '/admin/audit-log', '/admin/backups', '/admin/backup',
    '/google-sync', '/extras', '/salary-calculator', '/students/lifecycle',
    '/reports/excel', '/reports/pdf',
]


@pytest.mark.parametrize('path', PAGES)
def test_admin_page_loads(admin_client, path):
    resp = admin_client.get(path)
    assert resp.status_code in (200, 302), f'{path} -> {resp.status_code}'
    if resp.status_code == 200:
        # /reports/excel, /reports/pdf, /admin/backups legitimately return non-HTML
        assert resp.content_type.startswith('text/') or resp.content_type.startswith(
            'application/')


@pytest.mark.parametrize('path', PAGES)
def test_staff_page_loads(staff_client, path):
    # Staff should be denied or redirected on admin-only pages, but never 500
    resp = staff_client.get(path)
    assert resp.status_code in (200, 302, 403), f'{path} -> {resp.status_code}'


def test_error_page_404(admin_client):
    resp = admin_client.get('/this-page-does-not-exist')
    assert resp.status_code == 404