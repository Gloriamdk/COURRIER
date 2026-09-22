"""Optional browser smoke check. Uses a temporary DB; never opens db.sqlite3.

Run: python tools/verify_reports_browser.py
Requires: pip install playwright ; python -m playwright install chromium
Screenshots and sample PDF are written under the system temporary directory.
"""
import os
import sys
import tempfile
import threading
from datetime import timedelta
from pathlib import Path
from wsgiref.simple_server import make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
os.environ['DJANGO_DEBUG'] = '1'


def main():
    from django.conf import settings
    with tempfile.TemporaryDirectory(prefix='gec-report-db-') as temporary:
        settings.DATABASES['default']['NAME'] = str(Path(temporary) / 'browser.sqlite3')
        settings.MEDIA_ROOT = str(Path(temporary) / 'media')
        settings.SECURE_SSL_REDIRECT = False
        settings.SESSION_COOKIE_SECURE = False
        settings.CSRF_COOKIE_SECURE = False
        import django
        django.setup()
        from django.contrib.staticfiles.handlers import StaticFilesHandler
        from django.core.management import call_command
        from django.core.wsgi import get_wsgi_application
        from django.db import connections
        from django.utils import timezone
        from django.utils.crypto import get_random_string
        from courrier.models import Affectation, Courrier, Decision, User
        from playwright.sync_api import sync_playwright

        call_command('migrate', verbosity=0, interactive=False)
        password = get_random_string(32)
        users = {role: User.objects.create_user(username='browser_' + role, role=role, password=password)
                 for role in ('SG', 'DC', 'MINISTRE', 'AGENT')}
        now = timezone.now()
        for i in range(12):
            completed = i % 3 == 0
            mail = Courrier.objects.create(reference=f'BROWSER-{i}', designation='Courrier de démonstration navigateur',
                cree_par=users['SG'], expediteur_nom='Vérification temporaire',
                date_arrivee=now - timedelta(days=i*5), statut='TERMINE' if completed else 'AFFECTE',
                priorite=['NORMAL', 'URGENT', 'TRES_URGENT'][i % 3], delai_traitement_jours=10)
            decision = Decision.objects.create(courrier=mail, signe_par=users['MINISTRE'])
            aff = Affectation.objects.create(courrier=mail, decision=decision, affecte_par=users['MINISTRE'],
                service_concerne=['DAAF', 'DPDT', 'DPT'][i % 3],
                date_limite_traitement=now + timedelta(days=2-i),
                date_traitement=now - timedelta(days=1) if completed else None,
                statut_traitement='TRAITE' if completed else 'EN_COURS')
            Affectation.objects.filter(pk=aff.pk).update(date_affectation=now - timedelta(days=10+i))
        output = Path(tempfile.mkdtemp(prefix='gec-report-browser-'))
        server = make_server('127.0.0.1', 0, StaticFilesHandler(get_wsgi_application()))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, channel='chromium')
                for role in ('SG', 'DC', 'MINISTRE', 'AGENT'):
                    context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                    page = context.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(base + '/login/?next=/courrier/rapports/')
                    page.locator('[name="username"]').fill(users[role].username)
                    page.locator('[name="password"]').fill(password)
                    page.locator('button[type="submit"]').click()
                    page.wait_for_url('**/courrier/rapports/')
                    if role == 'AGENT':
                        response = page.goto(base + '/courrier/rapports/')
                        assert response.status == 403
                        print('AGENT: denied (403)')
                    else:
                        page.locator('#monthly-chart').wait_for()
                        assert page.locator('#nav-rapports').is_visible()
                        page.wait_for_function('typeof Chart !== "undefined" && Object.keys(Chart.instances).length === 4')
                        assert not errors, errors
                        page.locator('button[data-sort="1"]').click()
                        assert page.locator('th[aria-sort="ascending"]').count() == 1
                        with page.expect_download() as download:
                            page.get_by_role('link', name='Exporter PDF', exact=True).click()
                        download.value.save_as(output / f'rapport-{role}.pdf')
                        assert (output / f'rapport-{role}.pdf').read_bytes().startswith(b'%PDF-')
                        page.screenshot(path=str(output / f'{role}-desktop.png'), full_page=True)
                        page.locator('#directions-table tbody a').first.click()
                        assert page.locator('#id_direction').input_value() == 'DAAF'
                        assert page.locator('#directions-table tbody tr').count() == 1
                        page.set_viewport_size({'width': 390, 'height': 844})
                        page.screenshot(path=str(output / f'{role}-mobile.png'), full_page=True)
                        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Mobile overflow'
                        assert not errors, errors
                        print(f'{role}: login, menu, 4 charts, sorting, PDF, direction filter, mobile OK')
                    context.close()
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            connections.close_all()
        print(f'Artifacts: {output}')


if __name__ == '__main__':
    main()
