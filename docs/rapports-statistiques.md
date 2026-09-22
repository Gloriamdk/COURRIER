# Rapports & Statistiques

Page : `/courrier/rapports/`. Accès strictement réservé aux rôles SG, DC et MINISTRE,
y compris pour les exports. Un superutilisateur avec un autre rôle n’y accède pas.

## Installation

Dans l’environnement Python utilisé par Django :

```powershell
python -m pip install -r requirements-reports.txt
python manage.py check
python manage.py test
```

Aucune migration nécessaire. Aucun changement des modèles, des utilisateurs ou du circuit.
Chart.js 4.4.8 est distribué localement avec sa licence MIT dans `static/vendor/chartjs/`.
Les données sont transmises par `json_script`, sans assouplir la politique CSP.

## Définitions

- Périmètre : objets `Courrier`, filtrés par `date_arrivee` (réception physique).
  Les `CourrierSortant` rattachés sont des réponses et ne s’ajoutent pas aux entrants.
- Traité et clôturé/classé : uniquement `Courrier.Statut.TERMINE`. Ces deux cartes
  désignent le même ensemble, car le modèle ne possède pas de statut final distinct.
  Tous les autres statuts sont inclus dans « En cours », y compris les étapes initiales.
- Une réponse `VALIDE` et une analyse validée ne constituent pas une clôture.
- Direction : `Affectation.service_concerne`, sinon `destinataire.service_direction`
  actuel. Les alias DAF et DAAF sont regroupés. Les affectations sans service connu
  ont une ligne dédiée. Le modèle ne possède pas de table `Direction`.
- Un courrier compte une fois dans le total, et une fois pour chaque direction à
  laquelle il est affecté. La somme des directions peut donc dépasser le total global.
  Les directions sans affectation ne sont pas inventées à partir des utilisateurs.
- Fin : dernière transition structurée de l’historique vers `TERMINE`, sinon dernière
  `date_traitement` d’une affectation terminée. Seulement pour les courriers actuellement
  `TERMINE` ; aucun texte libre ni numéro de version de réponse n’est interprété.
- Durée : fin moins première `date_affectation` du périmètre. Une date absente ou
  une durée négative exclut le courrier des moyennes et médianes, sans le retirer des KPI.
- Échéance : première `date_limite_traitement` connue du périmètre, uniquement si
  `delai_traitement_jours` est renseigné, conformément au service d’alertes effectif.
- Retard actuel : non terminé avec au moins une affectation RECU/EN_COURS dont
  l’échéance est strictement dépassée. Pas de délai global implicite et pas de dépendance
  à l’existence d’une ligne `Relance` ni de synchronisation déclenchée par le rapport.
- Respect des délais : fin au plus tard à la première échéance / clôtures dont la
  fin et l’échéance sont connues. Une échéance inconnue n’est pas considérée respectée.
- Urgences : priorités URGENT et TRES_URGENT.
- Confidentialité : champ supprimé par la migration historique 0004. Indicateur
  indisponible et filtre désactivé ; aucune estimation, migration ou recréation du champ.

Les filtres s’appliquent à toutes les sections et aux exports. Les dates sont inclusives
dans le fuseau Django. Année et mois restreignent la plage explicite ; une intersection
vide renvoie une erreur de formulaire. Sans dates ni année, l’année courante est utilisée.
Cliquer une direction conserve les autres filtres et restreint ses affectations et délais.

Le graphique mensuel suit les réceptions et clôtures du même ensemble de courriers :
une clôture ultérieure à la période de réception reste visible. La comparaison utilise
les mêmes dates un an auparavant (29 février ramené au 28 si nécessaire), mais les états
actuels : elle ne prétend pas reconstituer les retards historiques. Une base nulle produit
« Non calculable », jamais une variation infinie.

## Architecture et vérifications

`reporting.py` contient les filtres et les agrégations en lecture seule. Les sous-requêtes
et `Exists` évitent les multiplications dues aux affectations, historiques ou réponses.
Le nombre de requêtes ne dépend pas du nombre de directions. Les tableaux de retards
sont limités à 50 lignes ; les autres comptes restent exhaustifs. Les PDF comportent
les tables complètes, des graphiques vectoriels (20 directions / 24 mois maximum),
les filtres, les définitions et la synthèse. Excel force les textes en cellules de type
texte, même s’ils commencent par `=`.

`report_views.py` contrôle les permissions avant tout calcul. `report_exports.py`
réutilise le même rapport. Les modèles, migrations et vues du workflow sont inchangés.
Les tests dans `test_reporting.py` utilisent exclusivement la base de test Django.

Le contrôle navigateur optionnel `python tools/verify_reports_browser.py` nécessite
Playwright et Chromium (`python -m pip install playwright`, puis
`python -m playwright install chromium`). Il crée une base et des comptes temporaires,
vérifie SG/DC/Ministre, le refus Agent, les graphiques, le tri, le PDF, le rapport par
direction et le format mobile. Les captures restent dans le répertoire temporaire
indiqué à la fin du contrôle.

Validation lors de l’intégration : `manage.py check` sans erreur ; 24 nouveaux tests
de rapports réussis ; suite complète de 87 tests réussie avec le hachage MD5 substitué
uniquement dans le processus de test pour accélérer les créations répétées de comptes.
La configuration de hachage de l’application n’a pas été modifiée. Les accès navigateur
ont été vérifiés avec le hachage normal et une base temporaire. L’empreinte SHA-256 de
`db.sqlite3` est restée identique avant et après les vérifications.
