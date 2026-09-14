from datetime import datetime, timezone
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch
from django.apps import apps
from django.db import connection
from django.test import TestCase
from .models import Courrier, CourrierSortant, User


class NumerotationSortantsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='sortants', role=User.Role.MINISTRE)

    def creer(self, **kwargs):
        courrier = Courrier.objects.create(designation='Sortie', cree_par=self.user)
        return CourrierSortant.objects.create(courrier=courrier, enregistre_par=self.user, destinataire='Destinataire', **kwargs)

    def test_sequence_annuelle_stable_apres_modification_et_suppression(self):
        with patch('courrier.models.timezone.now', return_value=datetime(2026, 9, 14, tzinfo=timezone.utc)):
            premier = self.creer()
            second = self.creer()
            self.assertEqual(premier.reference_sortie, 'SO-2026-0001')
            self.assertEqual(second.reference_sortie, 'SO-2026-0002')
            premier.objet = 'Objet modifié'
            premier.save()
            self.assertEqual(premier.reference_sortie, 'SO-2026-0001')
            second.delete()
            self.assertEqual(self.creer().reference_sortie, 'SO-2026-0003')
        with patch('courrier.models.timezone.now', return_value=datetime(2027, 1, 1, tzinfo=timezone.utc)):
            self.assertEqual(self.creer().reference_sortie, 'SO-2027-0001')

    def test_migration_renumerote_et_initialise_la_suite(self):
        with patch('courrier.models.timezone.now', return_value=datetime(2026, 9, 14, tzinfo=timezone.utc)):
            premier = self.creer(reference_sortie='SO-2026-ABCDEF')
            second = self.creer(reference_sortie='SO-2026-0001')
            migration = import_module('courrier.migrations.0029_numerotation_sortants')
            migration.numeroter_sortants(apps, SimpleNamespace(connection=connection))
            premier.refresh_from_db()
            second.refresh_from_db()
            self.assertEqual(premier.reference_sortie, 'SO-2026-0001')
            self.assertEqual(second.reference_sortie, 'SO-2026-0002')
            self.assertEqual(self.creer().reference_sortie, 'SO-2026-0003')
