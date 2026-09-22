"""Read-only statistics on incoming mail; no workflow or alert synchronization."""
from calendar import monthrange
from datetime import date, datetime, time, timedelta

from django import forms
from django.db.models import (
    Avg, Case, CharField, Count, DateTimeField, DurationField, Exists,
    ExpressionWrapper, F, OuterRef, Q, Subquery, Value, When,
)
from django.db.models.functions import Coalesce, NullIf, Trim, TruncMonth
from django.utils import timezone

from .models import Affectation, Courrier, Historique


URGENT = [Courrier.Priorite.URGENT, Courrier.Priorite.TRES_URGENT]
DONE = Q(statut=Courrier.Statut.TERMINE)
UNASSIGNED = "Sans direction renseignée"


def affectations_with_direction():
    # Prefer the recorded assignment over the user's potentially changed service.
    return Affectation.objects.annotate(
        service_brut=Coalesce(NullIf(Trim('service_concerne'), Value('')),
                             NullIf(Trim('destinataire__service_direction'), Value('')),
                             Value(UNASSIGNED), output_field=CharField()),
    ).annotate(direction=Case(When(service_brut='DAF', then=Value('DAAF')),
                             default=F('service_brut'), output_field=CharField()))


class ReportFilters(forms.Form):
    debut = forms.DateField(label="Date de début", required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    fin = forms.DateField(label="Date de fin", required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    annee = forms.IntegerField(label="Année", required=False, min_value=1900, max_value=9998)
    mois = forms.TypedChoiceField(label="Mois", required=False, coerce=int,
        choices=[('', 'Tous les mois')] + list(enumerate(
            ['Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin', 'Juillet',
             'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre'], 1)))
    direction = forms.ChoiceField(label="Direction", required=False)
    statut = forms.ChoiceField(label="Statut", required=False,
                              choices=[('', 'Tous les statuts')] + list(Courrier.Statut.choices))
    priorite = forms.ChoiceField(label="Priorité", required=False,
                                choices=[('', 'Toutes les priorités')] + list(Courrier.Priorite.choices))
    urgent = forms.ChoiceField(label="Urgence", required=False,
                              choices=[('', 'Toutes'), ('oui', 'Urgent / Très urgent'), ('non', 'Non urgent')])
    confidentialite = forms.ChoiceField(label="Confidentialité", required=False,
                                       choices=[('', 'Non disponible dans le modèle')], disabled=True)

    def __init__(self, data=None, **kwargs):
        params = data.copy() if data is not None else {}
        if not any(params.get(key) for key in ('debut', 'fin', 'annee')):
            params['annee'] = timezone.localdate().year
        super().__init__(params, **kwargs)
        directions = affectations_with_direction().order_by('direction').values_list('direction', flat=True).distinct()
        self.fields['direction'].choices = [('', 'Toutes les directions')] + [(d, d) for d in directions]

    def clean(self):
        values = super().clean()
        start, end = values.get('debut'), values.get('fin')
        year, month = values.get('annee'), values.get('mois')
        if month and not year:
            self.add_error('annee', "Indiquez l’année pour filtrer un mois.")
        if year:
            lower = date(year, month or 1, 1)
            upper = date(year, month or 12, monthrange(year, month or 12)[1])
            start = max(start, lower) if start else lower
            end = min(end, upper) if end else upper
        if start and end and start > end:
            raise forms.ValidationError("La période est vide : vérifiez les dates, l’année et le mois.")
        if end == date.max:
            self.add_error('fin', "Choisissez une date antérieure au 31/12/9999.")
        values['start'], values['end'] = start, end
        return values


def midnight(value):
    return timezone.make_aware(datetime.combine(value, time.min))


def percent(numerator, denominator):
    return round(100 * numerator / denominator, 1) if denominator else 0.0


def report_queryset(filters, now):
    qs = Courrier.objects.all().order_by()
    if filters.get('start'):
        qs = qs.filter(date_arrivee__gte=midnight(filters['start']))
    if filters.get('end'):
        qs = qs.filter(date_arrivee__lt=midnight(filters['end'] + timedelta(days=1)))
    for key in ('statut', 'priorite'):
        if filters.get(key):
            qs = qs.filter(**{key: filters[key]})
    if filters.get('urgent') == 'oui':
        qs = qs.filter(priorite__in=URGENT)
    elif filters.get('urgent') == 'non':
        qs = qs.exclude(priorite__in=URGENT)
    assignments = affectations_with_direction().filter(courrier_id=OuterRef('pk'))
    if filters.get('direction'):
        assignments = assignments.filter(direction=filters['direction'])
        qs = qs.filter(Exists(assignments))
    deadlines = assignments.filter(courrier__delai_traitement_jours__isnull=False,
                                   date_limite_traitement__isnull=False)
    late = deadlines.filter(date_limite_traitement__lt=now,
        statut_traitement__in=[Affectation.StatutTraitement.RECU, Affectation.StatutTraitement.EN_COURS])
    history = Historique.objects.filter(courrier_id=OuterRef('pk'),
        nouveau_statut=Courrier.Statut.TERMINE).exclude(ancien_statut=Courrier.Statut.TERMINE)
    finish = Coalesce(
        Subquery(history.order_by('-date_action', '-pk').values('date_action')[:1]),
        Subquery(Affectation.objects.filter(courrier_id=OuterRef('pk'),
            statut_traitement=Affectation.StatutTraitement.TRAITE,
            date_traitement__isnull=False).order_by('-date_traitement').values('date_traitement')[:1]),
        output_field=DateTimeField())
    return qs.annotate(
        finished_at=Case(When(DONE, then=finish), output_field=DateTimeField()),
        assigned_at=Subquery(assignments.order_by('date_affectation', 'pk').values('date_affectation')[:1]),
        deadline=Subquery(deadlines.order_by('date_limite_traitement').values('date_limite_traitement')[:1]),
        is_late=Case(When(DONE, then=Value(False)), default=Exists(late)),
    ).annotate(duration=ExpressionWrapper(F('finished_at') - F('assigned_at'), output_field=DurationField()))


def totals(qs):
    result = qs.aggregate(total=Count('pk'), treated=Count('pk', filter=DONE),
        ongoing=Count('pk', filter=~DONE), late=Count('pk', filter=Q(is_late=True)),
        urgent=Count('pk', filter=Q(priorite__in=URGENT)))
    result['rate'] = percent(result['treated'], result['total'])
    result['closed'] = result['treated']  # TERMINE is the sole final status.
    return result


def build_report(filters, now=None):
    now = now or timezone.now()
    qs = report_queryset(filters, now)
    kpi = totals(qs)
    distributions = {}
    for field, choices in [('statut', Courrier.Statut.choices), ('priorite', Courrier.Priorite.choices)]:
        counts = {r[field]: r for r in qs.values(field).annotate(count=Count('pk'),
                  late=Count('pk', filter=Q(is_late=True)))}
        distributions[field] = [dict(label=label, count=counts.get(code, {}).get('count', 0),
            late=counts.get(code, {}).get('late', 0),
            rate=percent(counts.get(code, {}).get('count', 0), kpi['total'])) for code, label in choices]

    received = {r['month'].strftime('%Y-%m'): r['count'] for r in qs.annotate(
        month=TruncMonth('date_arrivee')).values('month').annotate(count=Count('pk'))}
    finished = {r['month'].strftime('%Y-%m'): r['count'] for r in qs.filter(
        finished_at__isnull=False).annotate(month=TruncMonth('finished_at')).values('month').annotate(count=Count('pk'))}
    months = sorted(received.keys() | finished.keys())
    if filters.get('start') and filters.get('end'):
        cursor = filters['start'].replace(day=1)
        # Keep arbitrary multi-century requests bounded; sparse months remain visible.
        if (filters['end'].year - cursor.year) <= 20:
            while cursor <= filters['end']:
                months.append(cursor.strftime('%Y-%m'))
                cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    monthly = [dict(month=m, received=received.get(m, 0), treated=finished.get(m, 0)) for m in sorted(set(months))]

    affs = affectations_with_direction().filter(courrier_id__in=qs.values('pk'))
    if filters.get('direction'):
        affs = affs.filter(direction=filters['direction'])
    direction_done = Q(courrier__statut=Courrier.Statut.TERMINE)
    direction_late = (~direction_done & Q(courrier__delai_traitement_jours__isnull=False,
        date_limite_traitement__lt=now, statut_traitement__in=['RECU', 'EN_COURS']))
    directions = list(affs.values('direction').annotate(total=Count('courrier_id', distinct=True),
        treated=Count('courrier_id', distinct=True, filter=direction_done),
        ongoing=Count('courrier_id', distinct=True, filter=~direction_done),
        late=Count('courrier_id', distinct=True, filter=direction_late)).order_by('-treated', 'direction'))
    for row in directions:
        row['rate'] = percent(row['treated'], row['total'])

    measured = qs.filter(duration__gte=timedelta(0))
    duration_stats = measured.aggregate(average=Avg('duration'), count=Count('pk'))
    count = duration_stats['count']
    median = None
    if count:
        middle = list(measured.order_by('duration', 'pk').values_list('duration', flat=True)[(count - 1)//2:count//2 + 1])
        median = sum((v.total_seconds() for v in middle)) / len(middle) / 86400
    timing = qs.filter(finished_at__isnull=False, deadline__isnull=False).aggregate(
        on_time=Count('pk', filter=Q(finished_at__lte=F('deadline'))),
        after_deadline=Count('pk', filter=Q(finished_at__gt=F('deadline'))))
    timing.update(average=duration_stats['average'].total_seconds()/86400 if count else None,
                  median=median, measured=count,
                  missing=kpi['treated'] - count,
                  rate=percent(timing['on_time'], timing['on_time'] + timing['after_deadline']))
    urgent = totals(qs.filter(priorite__in=URGENT))
    overdue = list(qs.filter(is_late=True).order_by('deadline', 'pk').values(
        'pk', 'reference', 'designation', 'deadline')[:50])
    synthesis = [f"{kpi['total']} courriers reçus sur la période sélectionnée.",
        f"{kpi['treated']} courriers traités, soit {kpi['rate']} %.",
        f"{kpi['late']} courriers actuellement ouverts ont dépassé leur échéance."]
    if directions and directions[0]['treated']:
        best = directions[0]['treated']
        names = ', '.join(r['direction'] for r in directions if r['treated'] == best)
        synthesis.append(f"Volume traité le plus élevé : {names} ({best} courriers par direction).")
    comparison = None
    if filters.get('start') and filters.get('end') and filters['start'].year > 1:
        previous = dict(filters)
        for key in ('start', 'end'):
            d = filters[key]
            previous[key] = d.replace(year=d.year - 1, day=min(d.day, monthrange(d.year - 1, d.month)[1]))
        old = totals(report_queryset(previous, now))
        comparison = dict(start=previous['start'], end=previous['end'], rows=[
            dict(label=label, current=kpi[key], previous=old[key],
                 change=round((kpi[key]-old[key])*100/old[key], 1) if old[key] else None)
            for key, label in [('total', 'Reçus'), ('treated', 'Traités'), ('late', 'Actuellement en retard')]])
    return dict(kpi=kpi, distributions=distributions, monthly=monthly, directions=directions,
        timing=timing, urgent=urgent, overdue=overdue, synthesis=synthesis, comparison=comparison,
        filters=filters, generated_at=now, unknown_finish=qs.filter(DONE, finished_at__isnull=True).count(),
        charts=dict(monthly=monthly, directions=directions, **distributions))
