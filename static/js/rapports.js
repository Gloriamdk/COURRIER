/* All chart payloads are serialized with Django json_script. */
(() => {
    'use strict';
    document.getElementById('print-report')?.addEventListener('click', () => window.print());
    const table = document.getElementById('directions-table');
    table?.querySelectorAll('[data-sort]').forEach(button => button.addEventListener('click', () => {
        const column = Number(button.dataset.sort);
        const ascending = button.parentElement.getAttribute('aria-sort') !== 'ascending';
        const rows = Array.from(table.tBodies[0].rows).filter(row => !row.classList.contains('empty'));
        rows.sort((a, b) => {
            const left = a.cells[column].dataset.value;
            const right = b.cells[column].dataset.value;
            const result = column === 0 ? left.localeCompare(right, 'fr') : Number(left.replace(',', '.')) - Number(right.replace(',', '.'));
            return ascending ? result : -result;
        });
        table.querySelectorAll('th').forEach(th => th.setAttribute('aria-sort', 'none'));
        button.parentElement.setAttribute('aria-sort', ascending ? 'ascending' : 'descending');
        rows.forEach(row => table.tBodies[0].appendChild(row));
    }));
    const payload = document.getElementById('report-chart-data');
    if (!payload || typeof Chart === 'undefined') return;
    const data = JSON.parse(payload.textContent);
    const palette = ['#3675a9', '#198268', '#d99b32', '#bd5146', '#795c9b', '#529da0', '#9b6a50', '#58778c', '#a46387', '#6c893a', '#514e91', '#c77435', '#367c75', '#807045', '#b04c65', '#60747d'];
    const options = { responsive: true, maintainAspectRatio: false,
        animation: false,
        plugins: { legend: { position: 'bottom', labels: { boxWidth: 12, font: { size: 11 } } } } };
    new Chart(document.getElementById('monthly-chart'), { type: 'bar', data: {
        labels: data.monthly.map(row => row.month), datasets: [
            { label: 'Reçus', data: data.monthly.map(row => row.received), backgroundColor: palette[0] },
            { label: 'Traités', data: data.monthly.map(row => row.treated), backgroundColor: palette[1] }
        ] }, options: { ...options, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } } });
    [['status-chart', data.statut], ['priority-chart', data.priorite]].forEach(([id, rows]) => {
        const present = rows.filter(row => row.count > 0);
        new Chart(document.getElementById(id), { type: 'doughnut', data: {
            labels: present.map(row => `${row.label} : ${row.count} (${row.rate} %)`),
            datasets: [{ data: present.map(row => row.count), backgroundColor: palette }]
        }, options });
    });
    new Chart(document.getElementById('direction-chart'), { type: 'bar', data: {
        labels: data.directions.map(row => row.direction), datasets: [
            ...[['total', 'Affectés'], ['treated', 'Traités'], ['ongoing', 'En cours'], ['late', 'En retard']].map(([key, label], index) => ({
                label, data: data.directions.map(row => row[key]), backgroundColor: palette[index]
            })),
            { type: 'line', label: 'Taux de traitement (%)', data: data.directions.map(row => row.rate),
                borderColor: palette[4], backgroundColor: palette[4], yAxisID: 'rate', tension: 0 }
        ] }, options: { ...options, scales: {
            y: { beginAtZero: true, ticks: { precision: 0 } },
            rate: { position: 'right', min: 0, max: 100, grid: { drawOnChartArea: false }, ticks: { callback: value => `${value} %` } }
        } } });
})();
