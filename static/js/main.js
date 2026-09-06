/*
   Scripts globaux — GEC Ministère
*/

document.addEventListener('DOMContentLoaded', function () {
    // ── Fermeture des alertes flash ────────────────────────────────────────
    document.querySelectorAll('.close-alert').forEach(function (btn) {
        btn.addEventListener('click', function () {
            const alert = this.closest('.alert');
            if (alert) {
                alert.style.opacity = '0';
                alert.style.transform = 'translateY(-4px)';
                alert.style.transition = 'opacity 0.3s, transform 0.3s';
                setTimeout(() => alert.remove(), 300);
            }
        });
    });

    // Auto-fermeture des alertes après 6 secondes
    document.querySelectorAll('.alert').forEach(function (alert) {
        setTimeout(() => {
            if (alert && alert.parentNode) {
                alert.style.opacity = '0';
                alert.style.transition = 'opacity 0.5s';
                setTimeout(() => alert.remove(), 500);
            }
        }, 6000);
    });

    // ── Panneau de notifications (toggle) ─────────────────────────────────
    const notifToggle = document.getElementById('btn-notif-toggle');
    const notifPanel  = document.getElementById('notif-panel');

    if (notifToggle && notifPanel) {
        notifToggle.addEventListener('click', function (e) {
            e.stopPropagation();
            const isHidden = notifPanel.hidden;
            notifPanel.hidden = !isHidden;
            notifToggle.setAttribute('aria-expanded', isHidden ? 'true' : 'false');
        });

        // Fermer le panneau en cliquant ailleurs
        document.addEventListener('click', function (e) {
            if (!notifPanel.hidden && !notifPanel.contains(e.target)) {
                notifPanel.hidden = true;
            }
        });

        // Marquer les notifications comme lues au clic sur "Voir le courrier"
        notifPanel.querySelectorAll('.notif-item[data-notif-id]').forEach(function (item) {
            const notifId = item.dataset.notifId;
            const link = item.querySelector('.notif-link');

            if (link && notifId) {
                link.addEventListener('click', function () {
                    // Appel AJAX pour marquer comme lue
                    fetch(`/courrier/notification/${notifId}/lue/`, {
                        method: 'POST',
                        headers: {
                            'X-CSRFToken': getCsrfToken(),
                            'Content-Type': 'application/json',
                        }
                    })
                    .then(r => r.json())
                    .then(data => {
                        if (data.status === 'ok') {
                            item.classList.remove('notif-unread');
                            // Mettre à jour le compteur dans la navbar
                            const badge = document.getElementById('notif-count');
                            if (badge) {
                                if (data.nb_non_lues > 0) {
                                    badge.textContent = data.nb_non_lues;
                                } else {
                                    badge.remove();
                                }
                            }
                        }
                    })
                    .catch(() => {}); // Ignorer silencieusement les erreurs réseau
                });
            }
        });
    }

    // ── Toggle Sidebar (Mobile) ────────────────────────────────────────────
    const sidebarToggle = document.getElementById('btn-sidebar-toggle');
    const sidebar       = document.getElementById('sidebar');

    if (sidebarToggle && sidebar) {
        sidebarToggle.addEventListener('click', function () {
            sidebar.classList.toggle('open');
        });

        // Fermer la sidebar en cliquant en dehors sur mobile
        document.addEventListener('click', function (e) {
            if (
                window.innerWidth <= 900
                && sidebar.classList.contains('open')
                && !sidebar.contains(e.target)
                && e.target !== sidebarToggle
            ) {
                sidebar.classList.remove('open');
            }
        });
    }

    // ── Marquer l'élément actif dans la sidebar ───────────────────────────
    const currentPath = window.location.pathname;
    document.querySelectorAll('.sidebar-item a').forEach(function (link) {
        if (link.getAttribute('href') && currentPath.startsWith(link.getAttribute('href'))) {
            link.closest('.sidebar-item').classList.add('active');
        }
    });

    // ── Confirmation avant actions critiques ──────────────────────────────
    document.querySelectorAll('[data-confirm]').forEach(function (el) {
        el.addEventListener('click', function (e) {
            if (!confirm(this.dataset.confirm)) {
                e.preventDefault();
            }
        });
    });

    // ── Modal pour motif de rejet (Secrétaires)
    const btnOpenRejet = document.getElementById('btn-open-rejet');
    const modalRejet = document.getElementById('modal-rejet');
    const btnCancelRejet = document.getElementById('btn-cancel-rejet');
    const formRejet = document.getElementById('form-rejet');

    if (btnOpenRejet && modalRejet) {
        btnOpenRejet.addEventListener('click', function () {
            modalRejet.style.display = 'flex';
            document.getElementById('id_motif_rejet').focus();
        });
    }

    if (btnCancelRejet && modalRejet) {
        btnCancelRejet.addEventListener('click', function () {
            modalRejet.style.display = 'none';
            formRejet.reset();
        });
    }

    if (formRejet) {
        formRejet.addEventListener('submit', function (e) {
            const motif = (document.getElementById('id_motif_rejet').value || '').trim();
            if (!motif) {
                e.preventDefault();
                alert('Veuillez saisir le motif du rejet (obligatoire).');
                document.getElementById('id_motif_rejet').focus();
                return false;
            }
            // Laisser la soumission normale du formulaire (POST)
            return true;
        });
        // Fermer le modal si l'utilisateur clique en dehors de la boîte
        modalRejet.addEventListener('click', function (e) {
            if (e.target === modalRejet) {
                modalRejet.style.display = 'none';
                formRejet.reset();
            }
        });
    }
});

// ── Utilitaire : récupérer le jeton CSRF depuis les cookies ───────────────
function getCsrfToken() {
    const match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? match[1] : '';
}
