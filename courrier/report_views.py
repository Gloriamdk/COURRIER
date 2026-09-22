from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET

from .models import User
from .reporting import ReportFilters, build_report


@login_required
@require_GET
def statistiques(request, export=None):
    if not request.user.is_active or request.user.role not in {User.Role.SG, User.Role.DC, User.Role.MINISTRE}:
        raise PermissionDenied("Ce rapport est réservé au SG, au DC et au Ministre.")
    form = ReportFilters(request.GET)
    context = {'form': form}
    if not form.is_valid():
        return render(request, 'rapports/statistiques.html', context, status=400)
    report = build_report(form.cleaned_data)
    # Only validated filter values are preserved in drill-down and export links.
    params = request.GET.copy()
    for key in list(params):
        if key not in form.fields:
            del params[key]
    for row in report['directions']:
        direction_params = params.copy()
        direction_params['direction'] = row['direction']
        row['url'] = reverse('rapports_statistiques') + '?' + direction_params.urlencode()
    report['filter_labels'] = []
    for key, field in form.fields.items():
        value = form.cleaned_data.get(key)
        if value and key != 'confidentialite':
            label = dict(getattr(field, 'choices', [])).get(value, value)
            report['filter_labels'].append((field.label, str(label)))
    if export:
        from .report_exports import export_pdf, export_excel
        if export == 'pdf':
            content, mime, extension = export_pdf(report), 'application/pdf', 'pdf'
        else:
            content, mime, extension = export_excel(report), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'xlsx'
        response = HttpResponse(content, content_type=mime)
        response['Content-Disposition'] = f'attachment; filename="rapport-statistique.{extension}"'
        return response
    context.update(report=report, query_string=params.urlencode())
    return render(request, 'rapports/statistiques.html', context)
